"""COMSOL Java API adapter, imported only inside an isolated worker."""
from pathlib import Path

class MphBackend:
    def __init__(self,spec):
        import mph
        self.client=mph.Client(cores=spec['runtime']['cores'],version=spec['runtime']['version'])

    def build(self,s,folder):
        from jpype import JInt
        m=self.client.create(s['case_id']);j=m.java;j.modelPath(str(folder));j.label(s['case_id']+'.mph')
        gspec=s['geometry'];st=s['study'];mat=s['materials']
        params={'w':f"{gspec['pillar_width_nm']}[nm]",'pitch':f"{gspec['pitch_nm']}[nm]",
          'Lx':f"{gspec['cols']}*pitch",'Ly':f"{gspec['rows']}*pitch",'sub_h':f"{gspec['substrate_nm']}[nm]",
          'air_h':f"{gspec['air_nm']}[nm]",'pml_h':f"{gspec['pml_nm']}[nm]",'height_offset':'0[nm]',
          'f_search':f"{st['search_frequency_THz']}[THz]",'lambda_ref':'c_const/f_search',
          'n_pillar':str(mat['pillar_index']),'n_sub':str(mat['substrate_index'])}
        for k,v in params.items():j.param().set(k,v)
        j.component().create('comp1',True);co=j.component('comp1');co.geom().create('geom1',3)
        geom=co.geom('geom1');geom.lengthUnit('nm')
        def block(tag,size,pos):
            geom.create(tag,'Block');b=geom.feature(tag);b.set('size',size);b.set('pos',pos);b.set('selresult','on')
        block('sub',['Lx','Ly','sub_h'],['0','0','-sub_h'])
        block('air',['Lx','Ly','air_h'],['0','0','0'])
        block('ptop',['Lx','Ly','pml_h'],['0','0','air_h'])
        block('pbot',['Lx','Ly','pml_h'],['0','0','-sub_h-pml_h'])
        tags=[]
        for y,row in enumerate(gspec['encoding']):
            for x,code in enumerate(row):
                tag=f'p{y+1}_{x+1}';tags.append(tag)
                h=gspec['height_levels_nm'][code]
                block(tag,['w','w',f'{h}[nm]+height_offset'],[f'({x}+0.5)*pitch-w/2',f'({y}+0.5)*pitch-w/2','0'])
        geom.run()
        def union(tag,inputs):
            co.selection().create(tag,'Union');v=co.selection(tag);v.set('entitydim',JInt(3));v.set('input',inputs)
        union('pillars',[f'geom1_{tag}_dom' for tag in tags])
        union('substrate',['geom1_sub_dom','geom1_pbot_dom'])
        def material(tag,eps,selection=None):
            co.material().create(tag,'Common');v=co.material(tag)
            if selection:v.selection().named(selection)
            else:v.selection().all()
            v.propertyGroup('def').set('relpermittivity',eps);v.propertyGroup('def').set('relpermeability','1');v.propertyGroup('def').set('electricconductivity','0[S/m]')
        material('airmat','1');material('submat','n_sub^2','substrate');material('pillarmat','n_pillar^2','pillars')
        co.physics().create('emw','ElectromagneticWaves','geom1');emw=co.physics('emw')
        def face(tag,axis,value):
            co.selection().create(tag,'Box');v=co.selection(tag);v.set('entitydim',JInt(2));v.set('condition','inside')
            v.set(axis+'min',value+'-0.01[nm]');v.set(axis+'max',value+'+0.01[nm]')
            return v
        for axis,length in [('x','Lx'),('y','Ly')]:
            a=face(axis+'lo',axis,'0[nm]');b=face(axis+'hi',axis,length)
            emw.create('pc'+axis,'PeriodicCondition',2);p=emw.feature('pc'+axis)
            p.set('PeriodicType','Floquet');p.set('kFloquet',['0','0','0'])
            # A named union remains valid after geometry rebuilds.
            tag='sides'+axis;co.selection().create(tag,'Union');v=co.selection(tag);v.set('entitydim',JInt(2));v.set('input',[axis+'lo',axis+'hi'])
            p.selection().named(tag)
        for tag,selection,n in [('pmltop','geom1_ptop_dom','1'),('pmlbottom','geom1_pbot_dom','n_sub')]:
            co.coordSystem().create(tag,'PML');p=co.coordSystem(tag);p.selection().named(selection)
            p.set('ScalingType','Cartesian');p.set('wavelengthSourceType','userDefined');p.set('typicalWavelength','lambda_ref/'+n)
        # Ratios are diagnostic only: PML/cavity modes must not be silently discarded.
        union('physical',['geom1_sub_dom','geom1_air_dom'])
        for name,sel in [('intpillar','pillars'),('intphys','physical')]:
            co.cpl().create(name,'Integration');co.cpl(name).selection().named(sel)
        co.variable().create('metrics');co.variable('metrics').set('pillar_fraction','intpillar(emw.normE^2)/intphys(emw.normE^2)')
        co.mesh().create('mesh1','geom1');co.mesh('mesh1').automatic(True);co.mesh('mesh1').autoMeshSize(s['mesh']['level'])
        j.study().create('std1');j.study('std1').create('eig','Eigenfrequency');eig=j.study('std1').feature('eig')
        eig.set('shift','f_search');eig.set('neigs',JInt(st['number_of_modes']));eig.set('neigsactive',True)
        eig.set('eigunit','Hz')
        return m

    def solve_point(self,m,s,offset,folder):
        import numpy as np
        from jpype import JClass
        j=m.java;co=j.component('comp1');j.param().set('height_offset',f'{offset}[nm]')
        JClass('com.comsol.model.util.ModelUtil').showProgress(str(folder/'progress.log'))
        co.geom('geom1').run();co.mesh('mesh1').run()
        expected=s['geometry']['rows']*s['geometry']['cols']
        if len(co.selection('pillars').entities(3))!=expected:raise RuntimeError('Pillar domain count mismatch after rebuild')
        if not co.mesh('mesh1').isComplete() or co.mesh('mesh1').getNumElem()<=0:raise RuntimeError('Incomplete mesh')
        m.save(str(folder/'input.mph'))
        j.study('std1').run()
        freqs=np.asarray(m.evaluate('freq'),dtype=complex).reshape(-1)
        if not len(freqs) or not np.all(np.isfinite(freqs)):raise RuntimeError('No finite eigenfrequencies returned')
        fractions=np.asarray(m.evaluate('comp1.pillar_fraction'),dtype=complex).reshape(-1)
        modes=[]
        for i,f in enumerate(freqs):
            modes.append({'solution_index':i+1,'frequency_real_Hz':float(f.real),'frequency_imag_Hz':float(f.imag),
              'frequency_real_THz':float(f.real/1e12),'Q_abs':float(abs(f.real)/(2*abs(f.imag))) if f.imag else None,
              'pillar_field_fraction':float(fractions[i].real) if i<len(fractions) else None,
              'classification':'unclassified','tracked_mode_id':None})
        m.save(str(folder/'solution.mph'))
        return {'modes':modes,'pillar_domains':expected,'mesh_elements':int(co.mesh('mesh1').getNumElem()),'mesh_complete':True,
          'solution_file':str(folder/'solution.mph'),'input_file':str(folder/'input.mph'),
          'mode_tracking':'not_performed','gap':None,
          'warnings':['PML and radiation-box modes may be present; no automatic physical-mode classification.',
                      'Q_abs includes radiation and PML truncation effects; convergence has not been established.']}

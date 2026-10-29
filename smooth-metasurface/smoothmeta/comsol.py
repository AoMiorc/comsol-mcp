"""Lazy COMSOL backend: planar polygons, named selections, one extrusion."""
import json,time
from pathlib import Path
import numpy as np
from .geometry import parts,prepare_geometry,export_geometry,validate_chiral
from . import pasteur

def build_model(client,spec,footprint,name='smooth_meta'):
    m=client.create(name)
    try:return _configure_model(m,spec,footprint,name)
    except BaseException:
        client.remove(m)
        raise


def _configure_model(m,spec,footprint,name):
    from jpype import JInt
    from mph.node import cast
    sol=spec['solver'];L=spec['geometry']['period_nm'];ch=validate_chiral(spec.get('chiral'))
    j=m.java;j.label(name+'.mph')
    params={'a':f'{L}[nm]','t':f'{sol["thicknesses_nm"][0]}[nm]',
      'sub_h':f'{sol["substrate_nm"]}[nm]','air_h':f'{sol["air_nm"]}[nm]',
      'pml_h':f'{sol["pml_nm"]}[nm]','n_slab':str(sol['slab_index']),
      'n_sub':str(sol['substrate_index']),'f_search':f'{sol["search_THz"]}[THz]',
      'lambda_ref':'c_const/f_search',
      'n_medium':str(ch['medium_index'] if ch['enabled'] else 1.),
      'medium_eps_im':str(ch['epsilon_imag']), 'medium_mu_re':str(ch['mu_real']),
      'medium_mu_im':str(ch['mu_imag']), 'kappa_re':str(ch['kappa_real']),
      'kappa_im':str(ch['kappa_imag']), 'kappa':'kappa_re+i*kappa_im',
      'eps_chiral':'n_medium^2+i*medium_eps_im', 'mu_chiral':'medium_mu_re+i*medium_mu_im',
      'c0':'1/sqrt(epsilon0_const*mu0_const)'}
    for k,v in params.items():j.param().set(k,v)
    j.component().create('comp1',True);co=j.component('comp1');co.geom().create('geom1',3)
    g=co.geom('geom1');g.lengthUnit('nm')
    def block(tag,size,pos):
        g.create(tag,'Block');b=g.feature(tag);b.set('size',size);b.set('pos',pos);b.set('selresult','on')
    block('sub',['a','a','sub_h'],['0','0','-sub_h'])
    block('air',['a','a','t+air_h'],['0','0','0'])
    block('ptop',['a','a','pml_h'],['0','0','t+air_h'])
    block('pbot',['a','a','pml_h'],['0','0','-sub_h-pml_h'])
    g.create('wp','WorkPlane');wp=g.feature('wp');wp.set('quickz','0');wp.set('unite',True)
    w=wp.geom();w.lengthUnit('nm');solid_tags=[]
    def polygon(tag,coords):
        w.create(tag,'Polygon');v=w.feature(tag);v.set('type','solid');v.set('source','table')
        v.set('table',cast([list(p) for p in list(coords)[:-1]]))
    for k,p in enumerate(parts(footprint)):
        tag=f'outer{k}';polygon(tag,p.exterior.coords);holes=[]
        for n,h in enumerate(p.interiors):
            ht=f'hole{k}_{n}';polygon(ht,h.coords);holes.append(ht)
        if holes:
            dt=f'diff{k}';w.create(dt,'Difference');d=w.feature(dt)
            d.selection('input').set([tag]);d.selection('input2').set(holes);d.set('intbnd',False);tag=dt
        solid_tags.append(tag)
    if len(solid_tags)>1:
        w.create('unified','Union');u=w.feature('unified');u.selection('input').set(solid_tags);u.set('intbnd',False)
    w.run()
    g.create('slab','Extrude');ex=g.feature('slab');ex.set('workplane','wp');ex.selection('input').set(['wp'])
    ex.set('distance',['t']);ex.set('selresult','on');g.run()
    def union(tag,inputs,dim=3):
        co.selection().create(tag,'Union');v=co.selection(tag);v.set('entitydim',JInt(dim));v.set('input',inputs)
    union('substrate',['geom1_sub_dom','geom1_pbot_dom'])
    # Include dielectric domains explicitly: the background selection may exclude them.
    union('physical',['geom1_sub_dom','geom1_air_dom','geom1_slab_dom'])
    # Remove any propagated slab domains explicitly. PMLs remain ordinary media,
    # matching Mode-CY's separation of physical chiral domains and nonchiral PMLs.
    co.selection().create('chiral_physical','Difference');sel=co.selection('chiral_physical')
    sel.set('entitydim',JInt(3));sel.set('add',['geom1_air_dom']);sel.set('subtract',['geom1_slab_dom'])
    if not len(sel.entities(3)):raise RuntimeError('No physical ambient domains found')
    def material(tag,eps,sel=None,mu='1'):
        co.material().create(tag,'Common');v=co.material(tag)
        if sel:v.selection().named(sel)
        else:v.selection().all()
        v.propertyGroup('def').set('relpermittivity',eps)
        v.propertyGroup('def').set('relpermeability',mu);v.propertyGroup('def').set('electricconductivity','0[S/m]')
    material('airmat','n_medium^2');material('submat','n_sub^2','substrate');material('slabmat','n_slab^2','geom1_slab_dom')
    if ch['enabled']:material('chiralmat','eps_chiral','chiral_physical','mu_chiral')
    co.physics().create('emw','ElectromagneticWaves','geom1');emw=co.physics('emw')
    emw.prop('ShapeProperty').set('order_electricfield','2')
    if ch['enabled']:
        emw.create('chiralwave','WaveEquationElectric',3)
        emw.feature('chiralwave').selection().named('chiral_physical')
    for axis in ['x','y']:
        for side,value in [('lo','0[nm]'),('hi','a')]:
            tag=axis+side;co.selection().create(tag,'Box');v=co.selection(tag)
            v.set('entitydim',JInt(2));v.set('condition','inside')
            v.set(axis+'min',value+'-0.001[nm]');v.set(axis+'max',value+'+0.001[nm]')
        union('side'+axis,[axis+'lo',axis+'hi'],2)
        emw.create('pc'+axis,'PeriodicCondition',2);p=emw.feature('pc'+axis)
        p.set('PeriodicType','Floquet');p.set('Floquet_source','UserDefined');p.set('kFloquet',['0','0','0'])
        p.selection().named('side'+axis)
    for tag,selection,n in [('pmltop','geom1_ptop_dom','n_medium'),('pmlbottom','geom1_pbot_dom','n_sub')]:
        co.coordSystem().create(tag,'PML');p=co.coordSystem(tag);p.selection().named(selection)
        p.set('ScalingType','Cartesian');p.set('wavelengthSourceType','userDefined');p.set('typicalWavelength','lambda_ref/'+n)
    for tag,sel in [('intslab','geom1_slab_dom'),('intphys','physical')]:
        co.cpl().create(tag,'Integration');co.cpl(tag).selection().named(sel)
    co.variable().create('metrics');v=co.variable('metrics')
    v.set('slab_fraction','intslab(emw.normE^2)/intphys(emw.normE^2)')
    v.set('ez_fraction','intslab(abs(emw.Ez)^2)/intslab(emw.normE^2)')
    if ch['enabled']:
        co.cpl().create('intchiral','Integration');co.cpl('intchiral').selection().named('chiral_physical')
        electric='+'.join(f'abs(emw.D{a}-epsilon0_const*eps_chiral*emw.E{a})^2' for a in 'xyz')
        residual='+'.join(f'abs(emw.D{a}-epsilon0_const*eps_chiral*emw.E{a}+i*kappa*emw.H{a}/c0)^2' for a in 'xyz')
        magnetic='+'.join(f'abs(emw.B{a}-mu0_const*mu_chiral*emw.H{a}-i*kappa*emw.E{a}/c0)^2' for a in 'xyz')
        dt='+'.join(f'abs(emw.dHdt{a}-emw.iomega*emw.H{a})^2' for a in 'xyz')
        dnorm='+'.join(f'abs(emw.D{a})^2' for a in 'xyz')
        bnorm='+'.join(f'abs(emw.B{a})^2' for a in 'xyz')
        hdt_norm='+'.join(f'abs(emw.iomega*emw.H{a})^2' for a in 'xyz')
        v.set('electric_chiral_fraction',f'intchiral({electric})/intchiral({dnorm})')
        v.set('electric_constitutive_residual',f'intchiral({residual})/intchiral({dnorm})')
        v.set('magnetic_constitutive_residual',f'intchiral({magnetic})/intchiral({bnorm})')
        v.set('magnetic_time_residual',f'intchiral({dt})/intchiral({hdt_norm})')
    co.mesh().create('mesh1','geom1');mesh=co.mesh('mesh1');mesh.automatic(True);mesh.autoMeshSize(sol['mesh_level'])
    j.study().create('std1');j.study('std1').create('eig','Eigenfrequency');e=j.study('std1').feature('eig')
    e.set('shift','f_search');e.set('neigs',JInt(sol['num_modes']));e.set('neigsactive',True);e.set('eigunit','Hz')
    e.set('chkeigregion',False)
    if ch['enabled']:
        pasteur.apply(emw.feature('chiralwave'))
        # B=-curl(E)/iomega makes H depend on 1/omega. Mode-CY linearizes at its
        # nonzero search frequency; the RF default reference zero is singular.
        j.study('std1').createAutoSequences('all')
        eigen=j.sol('sol1').feature('e1');eigen.set('eigref','f_search');eigen.set('transeigref',True)
    return m


def equation_audit(m,spec):
    enabled=validate_chiral(spec.get('chiral'))['enabled']
    co=m.java.component('comp1')
    report=dict(enabled=enabled,reference='Mode-CY.mph / ewfd.wee1',geometry_compiler_version=2,
        chiral_domains=list(map(int,co.selection('chiral_physical').entities(3))),
        slab_domains=list(map(int,co.selection('geom1_slab_dom').entities(3))),
        pml_domains=[*map(int,co.selection('geom1_ptop_dom').entities(3)),*map(int,co.selection('geom1_pbot_dom').entities(3))])
    if set(report['chiral_domains']) & set(report['slab_domains']+report['pml_domains']):
        raise RuntimeError('Chiral selection includes slab or PML')
    report['overrides']=pasteur.verify(co.physics('emw').feature('chiralwave')) if enabled else []
    if enabled:
        eigen=m.java.sol('sol1').feature('e1')
        report['eigen_reference']=str(eigen.getString('eigref'))
        report['eigen_reference_active']=str(eigen.getString('transeigref'))
    return report

def capture_fields(m,period_nm,thickness_nm,frequencies,path):
    """Complex E at common normalized slab-plane coordinates (geometry unit nm)."""
    from mph.node import cast
    xy=(np.arange(15)+.37)*period_nm/15
    yy,xx=np.meshgrid(xy,xy,indexing='ij')
    coords=np.array([xx.ravel(),yy.ravel(),np.full(xx.size,thickness_nm/2)])
    coll=m.java.result().numerical();node=coll.create('gap_fields','Interp')
    try:
        node.set('data','dset1');node.set('expr',cast(['emw.Ex','emw.Ey','emw.Ez']))
        node.set('solnum',cast(list(range(1,len(frequencies)+1))));node.set('coord',cast(coords.tolist()))
        node.set('ext',0.0);node.set('coorderr','off')
        values=np.asarray(node.getData(),float)+1j*np.asarray(node.getImagData(),float)
        if values.shape!=(3,len(frequencies),225) or not np.isfinite(values).all():
            raise RuntimeError('Invalid common-coordinate field samples')
        np.savez(path,field=values,frequency=frequencies,coordinates=coords)
    finally:coll.remove('gap_fields')


def evaluate_design(spec,output,client=None,build_only=False,sample_fields=False):
    """Optimization-facing entry point. Requires a normalized load_spec result."""
    from jpype import JClass
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True,exist_ok=True)
    def write(name,data):(output/name).write_text(json.dumps(data,indent=2),encoding='utf8')
    def state(status,**kw):write('status.json',{'status':status,'time':time.time(),**kw})
    state('preparing');start=time.perf_counter();m=None
    try:
        prepared=prepare_geometry(spec['encoding'],**spec['geometry']);export_geometry(prepared,output)
        if prepared['metadata']['diagonal_contacts']:
            raise ValueError('Zero-width diagonal contacts are unsupported by this COMSOL backend')
        if prepared['metadata']['opposite_material_trace_difference_nm'] > 1e-6:
            raise ValueError('COMSOL backend currently requires matching opposite material traces')
        write('spec.json',spec)
        if client is None:
            import mph
            client=mph.Client(cores=spec['solver']['cores'],version='6.4')
        state('building');t=time.perf_counter();m=build_model(client,spec,prepared['geometry'])
        write('equation_audit.json',equation_audit(m,spec))
        geometry_s=time.perf_counter()-t;m.save(str(output/'model.mph'))
        if build_only:
            state('built');return {'status':'built','geometry_build_seconds':geometry_s}
        co=m.java.component('comp1');rows=[]
        for i,thickness in enumerate(spec['solver']['thicknesses_nm']):
            folder=output/f'point_{i:03d}';folder.mkdir();m.parameter('t',f'{thickness}[nm]')
            JClass('com.comsol.model.util.ModelUtil').showProgress(str(folder/'progress.log'))
            state('meshing',point=i,thickness_nm=thickness);t=time.perf_counter()
            co.geom('geom1').run();mesh=co.mesh('mesh1');mesh.run();mesh_s=time.perf_counter()-t
            if not mesh.isComplete():raise RuntimeError('Incomplete mesh')
            elements=int(mesh.getNumElem())
            if elements>spec['solver']['max_elements']:raise RuntimeError(f'Mesh budget exceeded: {elements}')
            state('solving',point=i,mesh_elements=elements);t=time.perf_counter()
            if validate_chiral(spec.get('chiral'))['enabled']:m.java.sol('sol1').runAll()
            else:m.java.study('std1').run()
            solve_s=time.perf_counter()-t
            f=np.asarray(m.evaluate('freq'),complex).reshape(-1)
            frac=np.asarray(m.evaluate('comp1.slab_fraction'),complex).real.reshape(-1)
            ez=np.asarray(m.evaluate('comp1.ez_fraction'),complex).real.reshape(-1)
            if not len(f) or not np.all(np.isfinite(f)):raise RuntimeError('No finite modes')
            diagnostics={}
            if validate_chiral(spec.get('chiral'))['enabled']:
                write('equation_audit.json',equation_audit(m,spec))
                for metric in ['electric_chiral_fraction','electric_constitutive_residual','magnetic_constitutive_residual','magnetic_time_residual']:
                    values=np.asarray(m.evaluate('comp1.'+metric),complex).real.reshape(-1)
                    if not np.isfinite(values).all():raise RuntimeError('Nonfinite '+metric)
                    if 'residual' in metric and np.max(np.abs(values))>1e-12:
                        raise RuntimeError('Constitutive identity failed: '+metric)
                    diagnostics[metric]=values.tolist()
            # Integration check validates hole nesting, nm scaling and slab selection.
            actual=float(np.asarray(m.evaluate('comp1.intslab(1)')).real.reshape(-1)[0])
            expected=prepared['geometry'].area*thickness*1e-27
            if abs(actual/expected-1)>1e-5:raise RuntimeError('CAD slab volume mismatch')
            modes=[{'index':k+1,'real_THz':float(x.real/1e12),'imag_THz':float(x.imag/1e12),
              'Q_abs':float(abs(x.real)/(2*abs(x.imag))) if x.imag else None,
              'slab_field_fraction':float(frac[k]),'slab_Ez_fraction':float(ez[k]),'classification':'unclassified'} for k,x in enumerate(f)]
            row={'thickness_nm':thickness,'mesh_elements':elements,'mesh_seconds':mesh_s,'solve_seconds':solve_s,
              'slab_volume_m3':actual,'expected_slab_volume_m3':expected,'modes':modes,
              'chiral_diagnostics':diagnostics,'gap':None,'mode_tracking':'not_implemented'}
            if sample_fields:capture_fields(m,spec['geometry']['period_nm'],thickness,f,folder/'fields.npz')
            m.save(str(folder/'solution.mph'));write(f'point_{i:03d}/result.json',row);rows.append(row)
            write('results.json',rows)
        report={'status':'completed','geometry_build_seconds':geometry_s,'elapsed_seconds':time.perf_counter()-start,
                'points':rows,'geometry':prepared['metadata']};write('summary.json',report);state('completed')
        return report
    except BaseException as e:
        state('failed',error=str(e));raise
    finally:
        if m is not None:client.remove(m)

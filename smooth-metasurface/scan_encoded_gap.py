"""Locate a bare crossing, then compare the same encoded design at nonzero kappa."""
import argparse,copy,json,shutil,time,traceback
from pathlib import Path
import numpy as np
from smoothmeta import load_spec
from smoothmeta.comsol import evaluate_design


def pair(row):
    found=[m for m in row['modes'] if 332<m['real_THz']<338 and abs(m['imag_THz'])<.2
           and m['slab_field_fraction']>.1]
    if len(found)!=2:raise RuntimeError('Target-pair selection ambiguous: '+str(found))
    return sorted(found,key=lambda m:m['slab_Ez_fraction'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--spec',default='examples/paper_chiral_110.json')
    p.add_argument('--bracket',default='165.9,166.9')
    p.add_argument('--max-elements',type=int,default=150000);a=p.parse_args()
    out=Path(a.output).resolve()
    if out.exists() and any(out.iterdir()):raise FileExistsError('Choose new output')
    out.mkdir(parents=True,exist_ok=True)
    def write(name,data):(out/name).write_text(json.dumps(data,indent=2),encoding='utf8')
    start=time.perf_counter();rows=[];origin=[];c=None
    try:
        spec=load_spec(a.spec);spec['solver']['num_modes']=2
        if not 100<=a.max_elements<=500000:raise ValueError('max-elements must be between 100 and 500000')
        spec['solver']['max_elements']=a.max_elements
        if not spec['chiral']['enabled']:raise ValueError('Chirality must be enabled')
        write('input_spec.json',spec)
        import mph
        c=mph.Client(cores=spec['solver']['cores'],version='6.4')
        counter=0
        def run(t,zero):
            nonlocal counter
            s=copy.deepcopy(spec);s['solver']['thicknesses_nm']=[t]
            if zero:s['chiral']['kappa_real']=s['chiral']['kappa_imag']=0.
            folder=out/f'case_{counter:03d}';counter+=1
            write('status.json',dict(status='running',case=folder.name,thickness_nm=t,zero=zero,completed=len(rows)))
            result=evaluate_design(s,folder,client=c,sample_fields=True)
            row=result['points'][0];target=pair(row)
            normalized=dict(thickness_nm=t,kk='0' if zero else 'nominal',
                kappa=dict(real=s['chiral']['kappa_real'],imag=s['chiral']['kappa_imag']),
                mesh_elements=row['mesh_elements'],mesh_seconds=row['mesh_seconds'],solve_seconds=row['solve_seconds'],
                modes=[dict(index=m['index'],real_THz=m['real_THz'],imag_THz=m['imag_THz'],
                    ez_fraction=m['slab_Ez_fraction'],slab_fraction=m['slab_field_fraction']) for m in row['modes']])
            shutil.copy2(folder/'point_000/fields.npz',out/f'fields_{len(rows)+1:03d}.npz')
            rows.append(normalized);origin.append(str(folder));write('results.json',rows);write('origins.json',origin)
            print(json.dumps(dict(thickness_nm=t,zero=zero,pair=target,
                separation_THz=abs(target[1]['real_THz']-target[0]['real_THz']),solve_seconds=row['solve_seconds'])),flush=True)
            return target
        lo,hi=map(float,a.bracket.split(','))
        low=run(lo,True);high=run(hi,True)
        def detuning(p):return p[1]['real_THz']-p[0]['real_THz']
        dl,dh=detuning(low),detuning(high)
        if dl*dh>=0:raise RuntimeError(f'Bare crossing outside bracket: detunings {dl}, {dh}; completed points retained')
        center=round(lo-dl*(hi-lo)/(dh-dl),6)
        bare=run(center,True)
        # One correction is permitted when the coarse interpolated zero is insufficient.
        if abs(detuning(bare))>.002:
            slope=(dh-dl)/(hi-lo);center=round(center-detuning(bare)/slope,6)
            bare=run(center,True)
        for t in [lo,center,hi]:run(t,False)
        write('status.json',dict(status='completed',points=len(rows),center_nm=center,
            bare_center_detuning_THz=detuning(bare),elapsed_seconds=time.perf_counter()-start))
        print('Completed '+str(out),flush=True)
    except BaseException as e:
        write('status.json',dict(status='failed',error=str(e),traceback=traceback.format_exc(),completed=len(rows)));raise


if __name__=='__main__':main()

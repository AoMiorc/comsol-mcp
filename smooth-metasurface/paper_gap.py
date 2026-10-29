"""Paper-pattern encoding through the current Mode-CY constitutive backend.

Historical 20260526/wc1 experiments are in paper_gap_legacy_20260526.py.
"""
import argparse,copy,json,time
from pathlib import Path
import numpy as np
from smoothmeta import load_spec,prepare_geometry,export_geometry
from smoothmeta.comsol import evaluate_design


def paper_mask(n):
    y,x=np.meshgrid((np.arange(n)+.5)*550/n,(np.arange(n)+.5)*550/n,indexing='ij')
    return (((x-275)**2+(y-275)**2>=200**2)|(y>=465)).astype(np.uint8)


def main():
    p=argparse.ArgumentParser(description='Compiled paper pixels + Mode-CY nine-equation chirality')
    p.add_argument('--resolution',type=int,default=110);p.add_argument('--output',required=True)
    p.add_argument('--thicknesses',default='165.9');p.add_argument('--zero-control',action='store_true')
    p.add_argument('--max-elements',type=int,default=100000);p.add_argument('--build-only',action='store_true')
    p.add_argument('--prepare-only',action='store_true')
    a=p.parse_args();out=Path(a.output).resolve()
    if out.exists() and any(out.iterdir()):raise FileExistsError('Choose new output')
    # Check matrix dimensions before allocating.
    if not 2<=a.resolution<=512:raise ValueError('Resolution must be 2..512')
    out.mkdir(parents=True,exist_ok=True)
    raw=dict(encoding=paper_mask(a.resolution).tolist(),geometry=dict(period_nm=550.),
        solver=dict(thicknesses_nm=list(map(float,a.thicknesses.split(','))),max_elements=a.max_elements),
        chiral=dict(enabled=True))
    (out/'nominal_spec.json').write_text(json.dumps(raw,indent=2),encoding='utf8')
    spec=load_spec(out/'nominal_spec.json')
    prepared=prepare_geometry(spec['encoding'],**spec['geometry']);export_geometry(prepared,out/'geometry')
    from smoothmeta.preview import comparison
    comparison([prepared],out/'geometry.png')
    def status(value,**extra):(out/'status.json').write_text(json.dumps(dict(status=value,**extra),indent=2),encoding='utf8')
    if a.prepare_only:status('prepared');return
    import mph
    client=mph.Client(cores=spec['solver']['cores'],version='6.4');reports={}
    try:
        for case in ['nominal']+(['zero'] if a.zero_control else []):
            s=copy.deepcopy(spec)
            if case=='zero':s['chiral']['kappa_real']=s['chiral']['kappa_imag']=0.
            status('building' if a.build_only else 'solving',case=case)
            reports[case]=evaluate_design(s,out/case,client=client,build_only=a.build_only)
        (out/'controls.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
        final_status='built' if a.build_only else 'completed'
        status(final_status,note='All returned modes retained. No automatic target-pair gap extraction.')
        print(json.dumps(dict(status=final_status,output=str(out),cases=list(reports)),indent=2))
    except BaseException as e:
        status('failed',error=str(e));raise


if __name__=='__main__':main()

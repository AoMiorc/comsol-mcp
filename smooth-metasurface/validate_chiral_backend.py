"""Real COMSOL regression: same compiled pixels/medium, nominal and zero kappa."""
import argparse,copy,json,time
from pathlib import Path
import numpy as np
from smoothmeta import load_spec
from smoothmeta.comsol import evaluate_design


def main():
    p=argparse.ArgumentParser();p.add_argument('--spec',default='examples/demo.json');p.add_argument('--output',required=True)
    a=p.parse_args();out=Path(a.output).resolve()
    if out.exists() and any(out.iterdir()):raise FileExistsError('Choose new output')
    out.mkdir(parents=True,exist_ok=True)
    spec=load_spec(a.spec)
    if not spec['chiral']['enabled']:raise ValueError('Use an explicitly enabled chiral case')
    if spec['chiral']['kappa_real']==spec['chiral']['kappa_imag']==0:raise ValueError('Nominal kappa must be nonzero')
    import mph
    start=time.perf_counter();client=mph.Client(cores=spec['solver']['cores'],version='6.4')
    reports={}
    for case in ['nominal','zero']:
        s=copy.deepcopy(spec)
        if case=='zero':s['chiral']['kappa_real']=s['chiral']['kappa_imag']=0.
        print('COMSOL '+case,flush=True)
        reports[case]=evaluate_design(s,out/case,client=client)
    if reports['nominal']['geometry']['fingerprint']!=reports['zero']['geometry']['fingerprint']:
        raise RuntimeError('Geometry changed between controls')
    maxima={case:max(max(row['chiral_diagnostics']['electric_chiral_fraction']) for row in report['points'])
            for case,report in reports.items()}
    if maxima['nominal']<1e-14 or maxima['zero']>1e-20:
        raise RuntimeError('Constitutive coupling did not switch with kappa: '+str(maxima))
    residuals={case:max(max(row['chiral_diagnostics'][key]) for row in report['points']
        for key in ['electric_constitutive_residual','magnetic_constitutive_residual','magnetic_time_residual'])
        for case,report in reports.items()}
    result=dict(status='completed',elapsed_seconds=time.perf_counter()-start,
        same_geometry=True,nominal_and_zero_keep_same_medium=True,electric_chiral_fraction_max=maxima,
        constitutive_residual_max=residuals,points={case:report['points'] for case,report in reports.items()})
    (out/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='points'},indent=2),flush=True)


if __name__=='__main__':main()

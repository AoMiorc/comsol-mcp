import argparse,json,sys
from . import validate_case,validate_manifest,run_batch,start_batch,get_batch_status,cancel_batch,collect_results

def main():
    p=argparse.ArgumentParser(description='Encoded-height COMSOL eigenmode batches')
    sub=p.add_subparsers(dest='command',required=True)
    v=sub.add_parser('validate');v.add_argument('manifest')
    for name in ['run','start']:
        r=sub.add_parser(name);r.add_argument('manifest');r.add_argument('--output',required=True);r.add_argument('--action',choices=['build','solve'],default='solve')
    for name in ['status','cancel','collect']:
        r=sub.add_parser(name);r.add_argument('run_dir')
    a=p.parse_args()
    if a.command=='validate':out=validate_manifest(a.manifest)
    elif a.command=='run':out=run_batch(a.manifest,a.output,a.action)
    elif a.command=='start':out=start_batch(a.manifest,a.output,a.action)
    else:out={'status':get_batch_status,'cancel':cancel_batch,'collect':collect_results}[a.command](a.run_dir)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if a.command=='run' and out['status']!='completed':return 1
    return 0

if __name__=='__main__':sys.exit(main())

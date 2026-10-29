import argparse,json
from pathlib import Path
from .geometry import load_spec,prepare_geometry,export_geometry

def main():
    p=argparse.ArgumentParser(description='Periodic encoding to compact COMSOL slab geometry')
    p.add_argument('command',choices=['prepare','build','solve'])
    p.add_argument('spec');p.add_argument('--output',required=True)
    a=p.parse_args();spec=load_spec(a.spec);out=Path(a.output)
    if out.exists() and any(out.iterdir()):p.error('Output directory must be new or empty')
    if a.command=='prepare':
        from .preview import comparison
        r=prepare_geometry(spec['encoding'],**spec['geometry']);payload=export_geometry(r,out)
        (out/'spec.json').write_text(json.dumps(spec,indent=2),encoding='utf8')
        comparison([r],out/'preview.png');print(json.dumps(payload['metadata'],indent=2))
    else:
        from .comsol import evaluate_design
        r=evaluate_design(spec,out,build_only=a.command=='build')
        print(json.dumps({k:v for k,v in r.items() if k!='points'},indent=2))

if __name__=='__main__':main()

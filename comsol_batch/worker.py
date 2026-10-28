import argparse
from pathlib import Path
import traceback
from .spec import read_json,validate_case,fingerprint
from .api import write_json,valid_result

def main(folder,action):
    folder=Path(folder).resolve();s=validate_case(read_json(folder/'spec.json'));model=None
    def state(status,**kw):write_json(folder/'state.json',{'status':status,**kw})
    try:
        pending=[(i,v) for i,v in enumerate(s['tuning']['values']) if not valid_result(folder/f'point_{i:03d}',s,v)]
        if action=='solve' and not pending:state('completed');return
        state('starting')
        from .backend import MphBackend
        backend=MphBackend(s);state('building');model=backend.build(s,folder)
        model.save(str(folder/'model.mph'))
        if action=='build':state('built',model_file=str(folder/'model.mph'));return
        for index,offset in pending:
            p=folder/f'point_{index:03d}';p.mkdir(exist_ok=True)
            state('solving',point_index=index,height_offset_nm=offset)
            print(f'Solving {s["case_id"]} offset={offset} nm',flush=True)
            data=backend.solve_point(model,s,offset,p)
            write_json(p/'result.json',{'status':'completed','spec_hash':fingerprint(s),'case_id':s['case_id'],
              'height_offset_nm':offset,**data})
            print(f'Completed {len(data["modes"])} modes',flush=True)
        state('completed')
    except BaseException as e:
        state('failed',error=str(e),traceback=traceback.format_exc());raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--action',choices=['build','solve'],default='solve')
    a=p.parse_args();main(a.folder,a.action)

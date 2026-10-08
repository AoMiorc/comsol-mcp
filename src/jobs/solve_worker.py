"""Dedicated COMSOL JVM worker. All paths come from the parent-created job directory."""
import json,sys,time,traceback,os
from pathlib import Path

def main():
    folder=Path(sys.argv[1]);config=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    def state(status,**data):
        path=folder/'worker-state.json';tmp=folder/'worker-state.tmp'
        tmp.write_text(json.dumps({'status':status,'time':time.time(),**data},ensure_ascii=False),encoding='utf-8');os.replace(tmp,path)
    try:
        state('starting')
        import mph
        from jpype import JClass
        c=mph.Client(cores=config['cores'],version=config['version'])
        JClass('com.comsol.model.util.ModelUtil').showProgress(str(folder/'progress.log'))
        state('loading',version=c.version,cores=c.cores)
        model=c.load(str(folder/'input.mph'))
        study=config['study_tag']
        if study is not None and study not in [str(t) for t in model.java.study().tags()]:raise ValueError('Unknown study tag: '+study)
        state('solving',version=c.version,cores=c.cores)
        if study is None:model.solve()
        else:model.java.study(study).run()
        state('saving',version=c.version,cores=c.cores)
        model.save(str(folder/'result.mph'))
        state('completed',version=c.version,cores=c.cores,result_file=str(folder/'result.mph'))
        return 0
    except BaseException as exc:
        from src.tools.errors import error_record
        diagnostic=error_record(exc,'solver_worker',job_id=folder.name,call_id=config.get('call_id'),source='isolated_worker')
        state('failed',error=str(exc),traceback=diagnostic['traceback'],diagnostic=diagnostic)
        return 1

if __name__=='__main__':sys.exit(main())

"""Owned standalone workers provide verifiable process-level cancellation."""
import json,os,sys,subprocess,shutil,time,re,threading
from pathlib import Path
from uuid import uuid4
from .nodes import guarded,READ,WRITE
from .errors import CALL_ID,remember,failure_record,error_record
ROOT=Path(__file__).resolve().parents[2]
JOBS={}

def tail(path,limit=65536):
    if not path.exists():return ''
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-limit));return stream.read().decode('utf-8',errors='replace')

def parse_progress(text):
    matches=list(re.finditer(r'(\d+(?:\.\d+)?)[ \t]*%[ \t]*[-–:][ \t]*([^\r\n]*)',text))
    if not matches:return {'percent':None,'phase':None,'source':'not_yet_reported'}
    m=matches[-1]
    result={'percent':float(m[1]),'phase':m[2].strip() or None,'source':'COMSOL progress log','scope':'current COMSOL phase; can reset; not total job completion'}
    # Only parse this known COMSOL eigenvalue table; retain raw logs for other solver formats.
    if 'Iter' in text and 'ErrEst' in text and 'Nconv' in text:
        table=text[text.rfind('ErrEst'):]
        rows=list(re.finditer(r'(?m)^[ \t]*(\d+)[ \t]+([+-]?(?:\d*\.?\d+)(?:[eE][+-]?\d+)?)[ \t]+(\d+)[ \t]*$',table))
        if rows:
            row=rows[-1];result['eigen_iteration']={'iteration':int(row[1]),'error_estimate':float(row[2]),'converged_modes':int(row[3]),'source':'Iter ErrEst Nconv log table'}
    return result

def get_job(token):
    if token not in JOBS:raise ValueError('Unknown job ID in this MCP process')
    return JOBS[token]

def status(job):
    process=job['process'];code=process.poll();folder=job['folder'];state={}
    if (folder/'worker-state.json').exists():state=json.loads((folder/'worker-state.json').read_text(encoding='utf-8'))
    if job.get('cancelled'):phase='cancelled'
    elif code is None:phase=state.get('status','starting');phase='finishing' if phase=='completed' else phase
    elif code==0 and state.get('status')=='completed' and (folder/'result.mph').is_file():phase='completed'
    else:phase='failed'
    diagnostic=state.get('diagnostic') or job.get('diagnostic')
    if phase=='failed':
        if diagnostic is None:
            diagnostic=failure_record(state.get('error') or 'Worker exited without successful completion',
                'solver_worker',job_id=job['id'],call_id=job.get('call_id'),exit_code=code,
                traceback=state.get('traceback'),source='isolated_worker',worker_log=str(folder/'worker.log'),progress_log=str(folder/'progress.log'))
        else: remember(diagnostic)
        job['diagnostic']=diagnostic
    return {'diagnostic':diagnostic,'call_id':job.get('call_id'),'success':True,'job_id':job['id'],'status':phase,'pid':process.pid,'process_alive':code is None,'exit_code':code,
            'elapsed_seconds':(job.get('finished_at') or time.time())-job['started_at'],
            'progress':parse_progress(tail(folder/'progress.log')),'worker_state':state,
            'result_file':str(folder/'result.mph') if phase=='completed' else None,
            'result_valid':phase=='completed','cancel_method':'terminate_owned_worker','folder':str(folder)}

def start_job(file_path,study_tag=None,cores=4):
    if not 1<=cores<=6:raise ValueError('cores must be 1..6')
    source=Path(file_path).expanduser().resolve()
    if source.suffix.lower()!='.mph' or not source.is_file():raise ValueError('Requires an existing local .mph file')
    if any(j['process'].poll() is None for j in JOBS.values()):raise RuntimeError('One isolated solver job at a time per MCP process')
    token=uuid4().hex;folder=ROOT/'solver_jobs'/token;folder.mkdir(parents=True)
    shutil.copyfile(source,folder/'input.mph')
    (folder/'request.json').write_text(json.dumps({'call_id':CALL_ID.get(),'source':str(source),'study_tag':study_tag,'cores':cores,'version':os.environ.get('COMSOL_MCP_VERSION','6.4')},ensure_ascii=False),encoding='utf-8')
    # Direct base executable avoids the Windows venv redirector spawning an orphaned JVM child.
    executable=getattr(sys,'_base_executable',sys.executable)
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONPATH']=os.pathsep.join([str(ROOT)]+[str(p) for p in sys.path if p])
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (folder/'worker.log').open('wb') as log:
        process=subprocess.Popen([executable,'-u',str(ROOT/'src/jobs/solve_worker.py'),str(folder)],cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=flags)
    job={'call_id':CALL_ID.get(),'id':token,'folder':folder,'process':process,'started_at':time.time(),'lock':threading.Lock()};JOBS[token]=job
    def reap():
        process.wait();job['finished_at']=time.time()
    threading.Thread(target=reap,daemon=True).start()
    return status(job)

def cancel_job(token):
    job=get_job(token)
    with job['lock']:
        if job['process'].poll() is not None:return {**status(job),'cancel_requested':False,'message':'Job already exited; terminal result preserved'}
        job['process'].kill()
        try:job['process'].wait(timeout=10)
        except subprocess.TimeoutExpired:return {**status(job),'success':False,'cancel_requested':True,'message':'Termination not yet confirmed; do not treat as stopped'}
        job['cancelled']=True;job['finished_at']=time.time()
        (job['folder']/'cancelled.json').write_text(json.dumps({'pid':job['process'].pid,'confirmed_exit_code':job['process'].returncode,'time':time.time()}),encoding='utf-8')
        return {**status(job),'cancel_requested':True,'message':'Owned worker exited; partial output is invalid. Input copy and original are preserved.'}

def register_solver_job_tools(mcp):
    @mcp.tool(annotations=WRITE)
    @guarded
    def solver_job_start(file_path:str,study_tag:str|None=None,cores:int=4)->dict:
        """Solve a SAVED .mph copy in a dedicated headless process, with reliable hard cancellation.
        Unsaved in-memory edits are not included: save_as first. Defaults 4 cores (max6), one job at a time.
        Returns job_id; poll solver_job_status/log. No automatic load into current session or source overwrite.
        """
        return start_job(file_path,study_tag,cores)
    @mcp.tool(annotations=READ)
    @guarded
    def solver_job_status(job_id:str)->dict:
        """Read owned process liveness and actual logged COMSOL phase percentage. Phase percent can reset.
        Completion requires worker exit code 0 plus saved result; cancellation requires confirmed process exit.
        """
        return status(get_job(job_id))
    @mcp.tool(annotations=READ)
    @guarded
    def solver_job_log(job_id:str,stream:str='progress',offset:int=0,max_characters:int=20000)->dict:
        """Read incremental progress or worker log without calling the busy COMSOL JVM. Offsets are characters."""
        return read_job_log(job_id,stream,offset,max_characters)
    @mcp.tool(annotations=WRITE)
    @guarded
    def solver_job_cancel(job_id:str)->dict:
        """Hard-stop ONLY this owned dedicated worker and confirm exit. Partial results invalid; original/current session preserved.
        Does not cancel old study_solve_async jobs. Already exited jobs keep their actual terminal result.
        """
        return cancel_job(job_id)


def shutdown_owned_jobs():
    # On orderly MCP shutdown, do not leave owned workers consuming CPU unnoticed.
    for job in list(JOBS.values()):
        if job['process'].poll() is None:
            try: cancel_job(job['id'])
            except Exception: pass

import atexit
atexit.register(shutdown_owned_jobs)


def refresh_errors():
    for job in list(JOBS.values()):
        if job['process'].poll() is not None: status(job)


def read_job_log(job_id,stream='progress',offset=0,max_characters=20000):
    if stream not in ('progress','worker') or offset<0 or not 1<=max_characters<=1000000:raise ValueError('Invalid stream or page arguments')
    job=get_job(job_id);folder=job['folder'];path=folder/('progress.log' if stream=='progress' else 'worker.log')
    text=path.read_text(encoding='utf-8',errors='replace') if path.exists() else '';end=min(offset+max_characters,len(text))
    if offset>len(text):raise ValueError('Offset beyond current log')
    return {'success':True,'job_id':job_id,'call_id':job.get('call_id'),'stream':stream,'text':text[offset:end],
        'next_offset':end,'has_more':end<len(text),'file':str(path),'solver_status':status(job)}

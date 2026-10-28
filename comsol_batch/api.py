"""High-level batch API, durable status, resumable per-point outputs."""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .spec import validate_case,validate_manifest,fingerprint,read_json

def write_json(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf8');os.replace(tmp,path)

def worker_env():
    env=os.environ.copy();env['PYTHONUTF8']='1'
    env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).resolve().parents[1])]+[str(p) for p in sys.path if p])
    return env

def point_folder(root,s,index):return Path(root)/s['case_id']/f'point_{index:03d}'

def valid_result(folder,s,offset):
    path=Path(folder)/'result.json'
    try:
        r=read_json(path)
        finite_modes=isinstance(r['modes'],list) and bool(r['modes']) and all(
            isinstance(m,dict) and all(isinstance(m.get(k),(int,float)) and not isinstance(m[k],bool) and math.isfinite(m[k])
            for k in ['frequency_real_Hz','frequency_imag_Hz']) for m in r['modes'])
        return (r['status']=='completed' and r['spec_hash']==fingerprint(s) and r['height_offset_nm']==offset
                and finite_modes and (Path(folder)/'solution.mph').stat().st_size>0)
    except (OSError,KeyError,ValueError):return False

def _prepare(manifest,run_dir):
    manifest=validate_manifest(manifest);root=Path(run_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    old=root/'manifest.json'
    if old.exists() and fingerprint(read_json(old))!=fingerprint(manifest):raise ValueError('Run directory belongs to a different manifest')
    write_json(old,manifest)
    return manifest,root

def run_batch(manifest,run_dir,action='solve'):
    if action not in ['solve','build']:raise ValueError('action must be build or solve')
    manifest,root=_prepare(manifest,run_dir)
    lock=root/'runner.lock'
    try:
        with lock.open('x',encoding='utf8') as f:f.write(str(os.getpid()))
    except FileExistsError:raise RuntimeError('Runner lock exists; use status/cancel. Inspect stale lock before manual removal.')
    process=None;total=sum(len(s['tuning']['values']) for s in manifest['cases'])
    try:
        # An earlier explicit cancellation remains in force until a new run is requested.
        (root/'cancel.request').unlink(missing_ok=True)
        write_json(root/'status.json',{'status':'running','action':action,'pid':os.getpid(),'total_points':total,'started_at':time.time()})
        for s in manifest['cases']:
            if (root/'cancel.request').exists():break
            folder=root/s['case_id'];folder.mkdir(exist_ok=True);write_json(folder/'spec.json',s)
            if action=='solve' and all(valid_result(point_folder(root,s,i),s,v) for i,v in enumerate(s['tuning']['values'])):continue
            write_json(folder/'state.json',{'status':'queued'})
            cmd=[getattr(sys,'_base_executable',sys.executable),'-u','-m','comsol_batch.worker',str(folder),'--action',action]
            flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            with (folder/'worker.log').open('ab') as stream:
                process=subprocess.Popen(cmd,env=worker_env(),stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,creationflags=flags)
                began=time.monotonic();last_point=None;point_began=began;timed_out=False;cancelled=False
                while process.poll() is None:
                    if (root/'cancel.request').exists():cancelled=True;break
                    state=folder/'state.json'
                    if state.exists():
                        try:
                            current=read_json(state).get('point_index')
                            if current!=last_point:point_began=time.monotonic();last_point=current
                        except (OSError,ValueError):pass
                    if time.monotonic()-point_began>s['runtime']['timeout_seconds']:timed_out=True;break
                    time.sleep(0.5)
                if timed_out or cancelled:
                    process.kill();process.wait(timeout=20)
                    write_json(folder/'state.json',{'status':'cancelled' if cancelled else 'timed_out','point_index':last_point,'worker_exit_code':process.returncode,'result_valid':False})
                    if cancelled:break
                elif process.returncode!=0:
                    write_json(folder/'process_failure.json',{'exit_code':process.returncode,'log':str(folder/'worker.log')})
                process=None
        result=collect_results(root)
        if (root/'cancel.request').exists():status='cancelled'
        elif action=='build':status='completed' if all((root/s['case_id']/'model.mph').is_file() and read_json(root/s['case_id']/'state.json').get('status')=='built' for s in manifest['cases']) else 'failed'
        else:status='completed' if result['completed_points']==total else 'failed'
        write_json(root/'status.json',{'status':status,'action':action,'pid':os.getpid(),'finished_at':time.time(),
          'completed_points':result['completed_points'],'total_points':total})
    except BaseException as exc:
        write_json(root/'status.json',{'status':'failed','action':action,'pid':os.getpid(),'error':str(exc),'finished_at':time.time()})
        raise
    finally:
        if process is not None and process.poll() is None:process.kill();process.wait(timeout=20)
        lock.unlink(missing_ok=True)
    return get_batch_status(root)

def start_batch(manifest,run_dir,action='solve'):
    if action not in ['solve','build']:raise ValueError('action must be build or solve')
    _,root=_prepare(manifest,run_dir)
    if (root/'runner.lock').exists():raise RuntimeError('Batch is already running or has a stale lock')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (root/'runner.log').open('ab') as stream:
        p=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-u','-m','comsol_batch','run',
          str(root/'manifest.json'),'--output',str(root),'--action',action],env=worker_env(),stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,creationflags=flags)
    return {'status':'submitted','pid':p.pid,'run_dir':str(root),'action':action}

def build_case(spec,output_dir):return run_batch({'cases':[validate_case(spec)]},output_dir,action='build')

def get_batch_status(run_dir):
    root=Path(run_dir).resolve();path=root/'status.json'
    result=read_json(path) if path.exists() else {'status':'not_started'}
    result['run_dir']=str(root);result['runner_lock_present']=(root/'runner.lock').exists();result['cancel_requested']=(root/'cancel.request').exists()
    if (root/'manifest.json').exists():
        manifest=read_json(root/'manifest.json');states=[];complete=0
        for s in manifest['cases']:
            folder=root/s['case_id'];state=read_json(folder/'state.json') if (folder/'state.json').exists() else {'status':'pending'}
            count=sum(valid_result(point_folder(root,s,i),s,v) for i,v in enumerate(s['tuning']['values']));complete+=count
            states.append({'case_id':s['case_id'],'completed_points':count,**state})
        result['cases']=states;result['completed_points']=complete
    return result

def cancel_batch(run_dir):
    root=Path(run_dir).resolve()
    if not (root/'manifest.json').exists():raise ValueError('Unknown batch directory')
    if not (root/'runner.lock').exists():return {**get_batch_status(root),'cancel_requested':False}
    (root/'cancel.request').write_text('Cancel owned worker and stop queue',encoding='utf8')
    return {**get_batch_status(root),'cancel_requested':True,'message':'Requested; cancellation is confirmed only after worker exit and terminal status.'}

def collect_results(run_dir):
    root=Path(run_dir).resolve();manifest=read_json(root/'manifest.json');rows=[];points=[]
    for s in manifest['cases']:
        for i,v in enumerate(s['tuning']['values']):
            folder=point_folder(root,s,i)
            if not valid_result(folder,s,v):continue
            r=read_json(folder/'result.json');points.append(r)
            for mode in r['modes']:rows.append({'case_id':s['case_id'],'height_offset_nm':v,**mode,'solution_file':r['solution_file']})
    result={'completed_points':len(points),'mode_count':len(rows),'points':points,'gap_extracted':False}
    write_json(root/'results.json',result)
    if rows:
        with (root/'modes.csv').open('w',newline='',encoding='utf8') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return result

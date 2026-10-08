"""Bounded, correlated diagnostics shared by tools and isolated workers."""
import traceback
from datetime import datetime, timezone
from contextvars import ContextVar
from threading import RLock
from uuid import uuid4
ERRORS=[]
_LOCK=RLock()
CALL_ID=ContextVar('comsol_call_id',default=None)
CALL_RECORDS=ContextVar('comsol_call_records',default=None)


def remember(record):
    with _LOCK:
        if not any(r['error_id']==record['error_id'] for r in ERRORS):
            ERRORS.append(record);del ERRORS[:-200]
    current=CALL_RECORDS.get()
    if current is not None and not any(r['error_id']==record['error_id'] for r in current):current.append(record)
    return record


def error_record(exc,operation,severity='error',**metadata):
    chain=[];current=exc;seen=set()
    for _ in range(12):
        if current is None or id(current) in seen:break
        seen.add(id(current));chain.append(str(current))
        try: cause=current.getCause()
        except Exception:cause=None
        current=cause if cause is not None else (getattr(current,'__cause__',None) or getattr(current,'__context__',None))
    return remember({'error_id':uuid4().hex,'call_id':CALL_ID.get(),'operation':operation,
        'time':datetime.now(timezone.utc).isoformat(),'severity':severity,'error':str(exc),
        'exception_type':type(exc).__name__,'causes':chain,
        'traceback':''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)),**metadata})


def failure_record(message,operation,severity='error',**metadata):
    return remember({'error_id':uuid4().hex,'call_id':CALL_ID.get(),'operation':operation,
        'time':datetime.now(timezone.utc).isoformat(),'severity':severity,'error':str(message),
        'exception_type':None,'causes':[],'traceback':None,**metadata})


def history(limit=50,call_id=None,job_id=None,severity=None):
    if not 1<=limit<=200:raise ValueError('limit must be 1..200')
    with _LOCK:
        return [dict(r) for r in ERRORS if (call_id is None or r.get('call_id')==call_id)
                and (job_id is None or r.get('job_id')==job_id)
                and (severity is None or r.get('severity')==severity)][-limit:]

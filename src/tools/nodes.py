"""Tag-path access, reversible property edits and structured error reporting."""
from __future__ import annotations
from functools import wraps
from threading import RLock
from typing import Any
import traceback
from datetime import datetime, timezone
from mph.node import get, cast
from mcp.types import ToolAnnotations
from .session import session_manager
from .inspection import Reader, native
from ..async_handler.solver import async_solver

LOCK = RLock()
from .errors import ERRORS, error_record
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)
# Allow-list of getter collections. Never evaluate Python or arbitrary Java calls.
COLLECTIONS = {'components':'component','geometry':'geom','features':'feature',
 'materials':'material','property_groups':'propertyGroup','physics':'physics',
 'selections':'selection','mesh':'mesh','studies':'study','solvers':'sol',
 'variables':'variable','functions':'func','couplings':'cpl','coordinate_systems':'coordSystem',
 'common':'common','pairs':'pair','datasets':'dataset','numerical':'numerical',
 'exports':'export','tables':'table','plotgroups':'result'}




def guarded(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK:
            try: return fn(*args, **kwargs)
            except Exception as exc: return {'success':False,**error_record(exc,fn.__name__)}
    return wrapped


def model_for(name=None):
    model=session_manager.get_model(name)
    if model is None: raise ValueError('Model not loaded: '+str(name))
    return model


def resolve(model, path):
    """Resolve tags only: components/comp1/geometry/geom1/features/wp1/workplane_geometry.
    Result children use results/datasets/dset1; plotgroups use results/plotgroups/pg1.
    """
    parts=path.strip('/').split('/') if path.strip('/') else []
    if any(p in ('','.','..') for p in parts): raise ValueError('Invalid tag path')
    node=model.java; i=0
    if parts and parts[0]=='global': i=1
    while i<len(parts):
        group=parts[i]
        if group=='workplane_geometry':
            if str(node.getType())!='WorkPlane': raise ValueError('Not a WorkPlane')
            node=node.geom(); i+=1; continue
        if group=='results': node=node.result(); i+=1; continue
        if group not in COLLECTIONS or i+1>=len(parts): raise ValueError('Unknown collection or missing tag: '+group)
        method=COLLECTIONS[group]; tag=parts[i+1]
        # Model.result() is both a plot group collection and results root.
        if group=='plotgroups':
            tags=[str(t) for t in node.tags()]
            if tag not in tags: raise KeyError('Unknown tag '+tag)
            node=node.get(tag)
        else:
            collection=getattr(node,method)()
            tags=[str(t) for t in collection.tags()]
            if tag not in tags: raise KeyError('Unknown tag '+tag+' in '+group+'; available: '+', '.join(tags))
            node=getattr(node,method)(tag)
        i+=2
    return node


def property_info(node,key):
    names=[str(p) for p in node.properties()]
    if key not in names: raise KeyError('Unknown property '+key+'; use node_list_properties')
    dtype=str(node.getValueType(key))
    result={'key':key,'type':dtype,'value':native(get(node,key))}
    if dtype.startswith('Double'):
        getter={'Double':'getString','DoubleArray':'getStringArray','DoubleMatrix':'getStringMatrix','DoubleRowMatrix':'getStringMatrix'}.get(dtype)
        if getter: result['expression']=native(getattr(node,getter)(key))
    return result


def inspect_path(path,model_name=None,max_depth=2):
    if not 0<=max_depth<=30: raise ValueError('max_depth must be 0..30')
    model=model_for(model_name); node=resolve(model,path); r=Reader(max_depth)
    return {'success':True,'node':r.node(node,path),'read_errors':r.errors,
            'truncated_paths':r.truncated,'complete':not r.errors and not r.truncated}


def set_properties(path,properties,model_name=None):
    if async_solver.is_running: raise RuntimeError('Cannot edit while solving')
    if not properties: raise ValueError('No properties supplied')
    node=resolve(model_for(model_name),path)
    before={k:property_info(node,k) for k in properties}  # preflight before any write
    for key,info in before.items():
        if info['type'] in ('Selection','None','File'):
            raise ValueError('Use a dedicated selection/file operation for '+key)
        if properties[key] is None or isinstance(properties[key],dict):
            raise ValueError('Value must be a scalar, vector or matrix: '+key)
    attempted=[]
    try:
        for key,value in properties.items():
            attempted.append(key)
            node.set(key,cast(value))
        after={k:property_info(node,k) for k in properties}
        return {'success':True,'path':path,'before':before,'after':after,
                'saved':False,'geometry_built':False,'validation_required':True}
    except Exception as exc:
        rollback_errors={}
        for key in reversed(attempted):
            try:
                old=before[key].get('expression',before[key]['value'])
                node.set(key,cast(old))
            except Exception as restore_exc: rollback_errors[key]=str(restore_exc)
        return {'success':False,**error_record(exc,'node_set_properties'),
                'rollback_attempted':True,'rollback_errors':rollback_errors,
                'warning':'Rollback restores requested properties only; use a snapshot for full state restoration.'}


def register_node_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def node_inspect(path:str,model_name:str|None=None,max_depth:int=2)->dict:
        """Inspect an existing tag path. Example components/comp1/geometry/geom1/features/blk1.
        Work-plane children: .../features/wp1/workplane_geometry/features/c1.
        Solver: global/solvers/sol1/features/e1. Results: results/datasets/dset1.
        No labels, code execution, implicit creation, build or save.
        """
        return inspect_path(path,model_name,max_depth)

    @mcp.tool(annotations=READ)
    @guarded
    def node_list_properties(path:str,model_name:str|None=None)->dict:
        """List exposed property keys and their COMSOL data types."""
        node=resolve(model_for(model_name),path)
        return {'success':True,'properties':[{'key':str(k),'type':str(node.getValueType(str(k)))} for k in node.properties()]}

    @mcp.tool(annotations=READ)
    @guarded
    def node_get_property(path:str,key:str,model_name:str|None=None)->dict:
        """Read a scalar/vector/matrix property with its expression when supported."""
        return {'success':True,**property_info(resolve(model_for(model_name),path),key)}

    @mcp.tool(annotations=WRITE)
    @guarded
    def node_set_properties(path:str,properties:dict[str,Any],model_name:str|None=None)->dict:
        """Edit existing properties; preflight keys, read back, attempt rollback on error.
        Edits memory only. Does not build, solve or save. Snapshot first for full rollback.
        """
        return set_properties(path,properties,model_name)

    @mcp.tool(annotations=WRITE)
    @guarded
    def node_set_property(path:str,key:str,value:Any,model_name:str|None=None)->dict:
        """Set one existing node property, preserving expressions in the before/readback report."""
        return set_properties(path,{key:value},model_name)

    # Semantic entry points share exactly the same tag-path resolver and behavior.
    for name,scope in [('geometry_inspect_feature','geometry'),('physics_inspect_feature','physics'),
                       ('material_inspect_group','materials'),('mesh_inspect_feature','mesh'),
                       ('study_inspect','studies'),('solver_inspect','solvers'),
                       ('dataset_inspect','datasets'),('plotgroup_inspect','plotgroups'),
                       ('numerical_inspect','numerical'),('selection_inspect','selections')]:
        def make_reader(tool_name,required):
            @guarded
            def read(path:str,model_name:str|None=None,max_depth:int=2)->dict:
                if required not in path.split('/'): raise ValueError('Path must contain '+required)
                return inspect_path(path,model_name,max_depth)
            read.__name__=tool_name; read.__doc__='Inspect an existing '+required+' tag path; uses node_inspect path syntax.'
            return read
        mcp.tool(name=name,annotations=READ)(make_reader(name,scope))
    for name,scope in [('geometry_set_feature_property','geometry'),('material_set_property','materials'),
                       ('physics_set_property','physics'),('mesh_set_property','mesh'),
                       ('study_set_property','studies'),('solver_set_property','solvers')]:
        def make_writer(tool_name,required):
            @guarded
            def write(path:str,key:str,value:Any,model_name:str|None=None)->dict:
                if required not in path.split('/'): raise ValueError('Path must contain '+required)
                return set_properties(path,{key:value},model_name)
            write.__name__=tool_name; write.__doc__='Modify one existing '+required+' property in memory with readback; no build or save.'
            return write
        mcp.tool(name=name,annotations=WRITE)(make_writer(name,scope))

    @mcp.tool(annotations=READ)
    @guarded
    def material_list_groups(path:str,model_name:str|None=None)->dict:
        """List property-group tags below a material path."""
        node=resolve(model_for(model_name),path)
        return {'success':True,'groups':[{'tag':str(t),'label':str(node.propertyGroup(str(t)).label()),'path':path+'/property_groups/'+str(t)} for t in node.propertyGroup().tags()]}

    mcp.tool(name='material_get_property',annotations=READ)(node_get_property)

    @mcp.tool(annotations=READ)
    @guarded
    def get_last_error(job_id:str|None=None)->dict:
        """Latest error across tool calls and owned workers; optional job filter. Warnings use get_error_history."""
        from .errors import history
        from .solver_jobs import refresh_errors
        refresh_errors()
        records=history(limit=1,job_id=job_id,severity='error')
        return {'success':True,'last_error':records[-1] if records else None,'scope':'tool_calls_and_owned_workers'}

    @mcp.tool(annotations=READ)
    @guarded
    def get_error_history(limit:int=50,call_id:str|None=None,job_id:str|None=None,severity:str|None=None)->dict:
        """Recent bounded diagnostics, with caught fallback warnings and call/job correlation. Not disk-persistent."""
        from .errors import history
        from .solver_jobs import refresh_errors
        if severity not in (None,'warning','error'):raise ValueError('severity must be warning or error')
        refresh_errors()
        return {'success':True,'records':history(limit,call_id,job_id,severity),'capacity':200}

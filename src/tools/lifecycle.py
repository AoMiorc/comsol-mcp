"""Topology, snapshots, validation and complete exposed-tree dumps."""
from pathlib import Path
from uuid import uuid4
import hashlib
import json
from mph.node import cast
from .nodes import guarded, READ, WRITE, resolve, model_for, inspect_path, error_record
from .inspection import Reader, native, inspect_model
from .session import session_manager
from ..async_handler.solver import async_solver

SNAPSHOTS={}
SNAPSHOT_DIR=Path(__file__).resolve().parents[2]/'snapshots'


def target_file(file_path,suffix,overwrite=False):
    path=Path(file_path).expanduser().resolve()
    if path.suffix.lower()!=suffix: raise ValueError('File extension must be '+suffix)
    if path.exists() and not overwrite: raise FileExistsError(str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def ensure_idle():
    if async_solver.is_running: raise RuntimeError('Operation unavailable while solving')


def register_lifecycle_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def selection_list(model_name:str|None=None)->dict:
        """List named selections and bindings in materials/physics. No geometry build."""
        d=inspect_model(model_for(model_name),['selections','materials','physics'],12)
        bindings=[]
        def walk(x):
            if isinstance(x,dict):
                if 'selection' in x: bindings.append({'path':x.get('path'),'selection':x['selection']})
                for v in x.values(): walk(v)
            elif isinstance(x,list):
                for v in x: walk(v)
        walk(d)
        return {'success':True,'global_selections':d.get('global_selections'),
                'components':[{'tag':c['tag'],'selections':c['selections']} for c in d['components']],
                'bindings':bindings,'read_errors':d['read_errors']}

    @mcp.tool(annotations=READ)
    @guarded
    def entity_adjacency(geometry_path:str,from_dimension:int,to_dimension:int,entity_ids:list[int],model_name:str|None=None)->dict:
        """Adjacent entity IDs from existing finalized geometry; dimensions 0 point,1 edge,2 face,3 domain. Never builds."""
        geom=resolve(model_for(model_name),geometry_path)
        dim=int(geom.getSDim())
        if not 0<=from_dimension<=dim or not 0<=to_dimension<=dim or from_dimension==to_dimension:
            raise ValueError('Require distinct dimensions within geometry space dimension')
        counts=list(geom.getNEntities())
        if not entity_ids or any(i<1 or i>counts[from_dimension] for i in entity_ids): raise ValueError('Invalid entity IDs')
        return {'success':True,'from_dimension':from_dimension,'to_dimension':to_dimension,
                'adjacency':{str(i):native(geom.getAdj(from_dimension,to_dimension,i)) for i in entity_ids},'built':False}

    @mcp.tool(annotations=READ)
    @guarded
    def entity_bbox(geometry_path:str,entity_dimension:int,entity_ids:list[int],model_name:str|None=None)->dict:
        """Exact COMSOL measureFinal bbox [xmin,xmax,ymin,ymax,zmin,zmax].
        Temporarily sets the measurement selection and restores it. No geometry build.
        """
        geom=resolve(model_for(model_name),geometry_path); dim=int(geom.getSDim())
        if not 0<=entity_dimension<=dim: raise ValueError('Invalid dimension')
        counts=list(geom.getNEntities())
        if not entity_ids or any(i<1 or i>counts[entity_dimension] for i in entity_ids): raise ValueError('Invalid entity IDs')
        measure=geom.measureFinal(); sel=measure.selection()
        previous_dim=int(sel.dim()); previous_entities=native(sel.entities()); previous_named=str(sel.named()) if hasattr(sel,'named') else ''
        try:
            sel.geom(entity_dimension); sel.set(cast(entity_ids))
            bounds=native(measure.getBoundingBox())
        finally:
            sel.geom(previous_dim)
            if previous_named: sel.named(previous_named)
            elif previous_entities: sel.set(cast(previous_entities))
            else: sel.clear()
        return {'success':True,'bbox':bounds,'coordinate_unit':str(geom.lengthUnit()),'entity_dimension':entity_dimension,'entity_ids':entity_ids,'built':False}

    @mcp.tool(annotations=READ)
    @guarded
    def dump_model(model_name:str|None=None,recursive:bool=True,max_depth:int=12,include_equations:bool=False)->dict:
        """Dump exposed geometry/materials/physics/mesh/study/solver plus variables,
        functions, couplings, coordinate systems, common features, pairs and results.
        Set include_equations=True for raw Equation View tables on physics features.
        Not every COMSOL internal object; no automatic build or solve.
        """
        return dump_model_data(model_for(model_name),recursive,max_depth,include_equations)

    @mcp.tool(annotations=WRITE)
    @guarded
    def model_snapshot(model_name:str|None=None)->dict:
        """Save an immutable UUID .mph snapshot under local snapshots/. Does not overwrite source.
        COMSOL save target becomes a separate working copy. Returns snapshot_id for restore.
        """
        ensure_idle(); model=model_for(model_name); token=uuid4().hex
        SNAPSHOT_DIR.mkdir(exist_ok=True); path=SNAPSHOT_DIR/(token+'.mph')
        label=str(model.java.label()); old_file=str(model.file())
        # Keep COMSOL's remembered save target separate from the immutable snapshot.
        # Later model_save() must never silently overwrite the restore point.
        import shutil
        working_path=SNAPSHOT_DIR/('working_'+token+'.mph')
        try: model.save(str(working_path))
        finally: model.java.label(label)
        shutil.copyfile(working_path,path)
        info={'snapshot_id':token,'path':str(path),'model_name':model.name(),'original_file':old_file,
              'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        path.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        SNAPSHOTS[token]=info
        return {'success':True,**info,'current_save_path':str(model.file())}

    @mcp.tool(annotations=WRITE)
    @guarded
    def model_restore(snapshot_id:str)->dict:
        """Restore snapshot into a NEW current model, preserving existing loaded models.
        Does not overwrite any .mph. Restored model has a unique name.
        """
        ensure_idle()
        if len(snapshot_id)!=32 or any(c not in '0123456789abcdef' for c in snapshot_id): raise ValueError('Invalid snapshot ID')
        path=SNAPSHOT_DIR/(snapshot_id+'.mph'); meta=path.with_suffix('.json')
        info=json.loads(meta.read_text(encoding='utf-8'))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']: raise ValueError('Snapshot checksum mismatch')
        # Copy to unique path so MPh load caching cannot return an already-loaded model.
        import shutil
        restored_path=SNAPSHOT_DIR/('restored_'+uuid4().hex+'.mph')
        shutil.copyfile(path,restored_path)
        restored=session_manager.client.load(str(restored_path))
        restored.java.label('restored_'+uuid4().hex[:10])
        name=session_manager.add_model(restored); session_manager.set_current_model(name)
        return {'success':True,'model_name':name,'snapshot_id':snapshot_id,'existing_models_preserved':True,'file':str(restored_path)}

    @mcp.tool(annotations=WRITE)
    @guarded
    def model_save_as(file_path:str,model_name:str|None=None,overwrite:bool=False)->dict:
        """Save to explicit .mph path; existing files rejected unless overwrite=true."""
        ensure_idle(); path=target_file(file_path,'.mph',overwrite); model=model_for(model_name)
        label=str(model.java.label())
        try: model.save(str(path))
        finally: model.java.label(label)
        return {'success':True,'file':str(path)}

    @mcp.tool(annotations=WRITE)
    @guarded
    def export_java(file_path:str,model_name:str|None=None,overwrite:bool=False)->dict:
        """Export COMSOL Java representation to .java; no Java execution."""
        path=target_file(file_path,'.java',overwrite)
        import re
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',path.stem):
            raise ValueError('Java filename must be a valid identifier, e.g. model_export.java')
        model=model_for(model_name)
        label=str(model.java.label())
        try: model.save(str(path),format='Java')
        finally: model.java.label(label)
        return {'success':True,'file':str(path),'bytes':path.stat().st_size}

    @mcp.tool(annotations=READ)
    @guarded
    def validate_model(model_name:str|None=None)->dict:
        """Check existing finalized geometry and report model problems/selection read errors.
        Does not build or solve; does not guarantee solver convergence or physical validity.
        """
        model=model_for(model_name); checks=[]
        for ct in model.java.component().tags():
            c=model.java.component(str(ct))
            for gt in c.geom().tags():
                try:
                    c.geom(str(gt)).check(); checks.append({'component':str(ct),'geometry':str(gt),'valid':True})
                except Exception as exc: checks.append({'component':str(ct),'geometry':str(gt),'valid':False,'error':str(exc)})
        problems=[]
        for problem in model.problems(): problems.append({str(k):str(v) for k,v in problem.items()})
        d=inspect_model(model,['materials','physics','selections'],12)
        return {'success':True,'geometry_checks':checks,'problems':problems,'read_errors':d['read_errors'],
                'checks_passed':all(c['valid'] for c in checks) and not problems and not d['read_errors'],
                'scope':'existing geometry validity, reported problems, selection readability; no rebuild or solve'}


def dump_model_data(model,recursive=True,max_depth=12,include_equations=False):
    depth=max_depth if recursive else 0
    d=inspect_model(model,max_depth=depth)
    if not d.get('success'): return d
    r=Reader(depth); java=model.java
    for c in d['components']:
        comp=java.component(c['tag'])
        for key,method in [('variables','variable'),('functions','func'),('couplings','cpl'),('coordinate_systems','coordSystem'),('common','common'),('pairs','pair')]:
            if hasattr(comp,method): c[key]=r.collection(comp,method,'components/'+c['tag']+'/'+key,0)
    for key,method in [('variables','variable'),('functions','func')]:
        d['global_'+key]=r.collection(java,method,'global/'+key,0)
    result=java.result(); d['results']={}
    for key,method in [('datasets','dataset'),('numerical','numerical'),('exports','export'),('tables','table')]:
        d['results'][key]=r.collection(result,method,'results/'+key,0)
    d['results']['plotgroups']=[r.node(result.get(str(t)),'results/plotgroups/'+str(t)) for t in result.tags()]
    d['read_errors']+=r.errors; d['truncated_paths']+=r.truncated
    d['complete']=not d['read_errors'] and not d['truncated_paths']
    if include_equations:
        from .equations import TABLES
        def attach(value):
            if isinstance(value, dict):
                path=value.get('path','')
                if '/physics/' in path and '/features/' in path and 'tag' in value:
                    try:
                        info=resolve(model,path).featureInfo('info')
                        value['equation_tables']={table:r.read(path+'/equation_tables/'+table,lambda t=table:info.getInfoTable(t)) for table in TABLES}
                    except Exception as exc:
                        r.errors.append({'path':path+'/equation_tables','error':str(exc)})
                for child in list(value.values()): attach(child)
            elif isinstance(value,list):
                for child in value: attach(child)
        before=len(r.errors); attach(d)
        d['read_errors']+=r.errors[before:]
    d['complete']=not d['read_errors'] and not d['truncated_paths']
    d['scope']='Supported exposed collections; optional Equation View tables. Not every internal object or external file content.'
    d['equations_included']=include_equations
    return d

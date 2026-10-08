"""Headless image export and opt-in COMSOL progress log capture."""
from pathlib import Path
from uuid import uuid4
from mph.node import get,cast
from .nodes import guarded,READ,WRITE,model_for,resolve
from .lifecycle import target_file,ensure_idle
from ..async_handler.solver import async_solver
LOG_PATH=None

def export_image(path,file_path,model_name,overwrite):
    ensure_idle(); node=resolve(model_for(model_name),path)
    destination=target_file(file_path,'.png',overwrite)
    image=node.image(); settings={'imagetype':'png','pngfilename':str(destination)}
    before={k:get(image,k) for k in settings}
    try:
        for k,v in settings.items(): image.set(k,cast(v))
        image.export()
    finally:
        for k,v in before.items(): image.set(k,cast(v))
    if not destination.is_file() or destination.stat().st_size==0: raise RuntimeError('COMSOL did not produce an image')
    return {'success':True,'file':str(destination),'bytes':destination.stat().st_size,'source_path':path}

def register_output_tools(mcp):
    @mcp.tool(annotations=WRITE)
    @guarded
    def export_geometry_image(geometry_path:str,file_path:str,model_name:str|None=None,overwrite:bool=False)->dict:
        """Export existing geometry/feature to PNG using COMSOL image().export(), no Desktop window.
        Requires graphics support in headless session; propagates renderer failures. Restores image settings.
        """
        if 'geometry' not in geometry_path.split('/'): raise ValueError('Requires geometry tag path')
        return export_image(geometry_path,file_path,model_name,overwrite)

    @mcp.tool(annotations=WRITE)
    @guarded
    def export_plot_image(plotgroup_path:str,file_path:str,model_name:str|None=None,overwrite:bool=False)->dict:
        """Export an existing result plot group to PNG, preserving image settings. No solver run."""
        if 'plotgroups' not in plotgroup_path.split('/'): raise ValueError('Requires results/plotgroups/tag')
        ensure_idle(); model=model_for(model_name); node=resolve(model,plotgroup_path)
        destination=target_file(file_path,'.png',overwrite)
        exports=model.java.result().export(); tag='mcpimg'+uuid4().hex[:12]
        try:
            image=exports.create(tag,'Image')
            image.set('plotgroup',str(node.tag()))
            image.set('imagetype','png'); image.set('pngfilename',str(destination))
            image.run()
        finally:
            if tag in [str(t) for t in exports.tags()]: exports.remove(tag)
        if not destination.is_file() or destination.stat().st_size==0: raise RuntimeError('COMSOL did not produce a plot image')
        return {'success':True,'file':str(destination),'bytes':destination.stat().st_size,'temporary_export_removed':True}

    @mcp.tool(annotations=WRITE)
    @guarded
    def solver_log_start(model_name:str|None=None)->dict:
        """Enable COMSOL progress-file capture for FUTURE operations in this JVM.
        Must call before solve. Cannot recover historical uncaptured logs. No solve triggered.
        """
        ensure_idle(); model_for(model_name)
        from jpype import JClass
        global LOG_PATH
        folder=Path(__file__).resolve().parents[2]/'logs'; folder.mkdir(exist_ok=True)
        path=folder/('solver_'+uuid4().hex+'.log')
        JClass('com.comsol.model.util.ModelUtil').showProgress(str(path))
        LOG_PATH=path
        return {'success':True,'file':str(path),'scope':'future COMSOL operations in this process'}

    @mcp.tool(annotations=READ)
    @guarded
    def get_solver_log(offset:int=0,max_characters:int=20000,job_id:str|None=None,stream:str='progress')->dict:
        """Read paginated captured solver progress with traceback/status. Call solver_log_start before solving.
        Pass job_id for isolated worker progress/worker logs with correlated diagnostic.
        No invented progress percentage; lifecycle status is not COMSOL iteration progress.
        """
        if job_id is not None:
            from .solver_jobs import read_job_log
            return read_job_log(job_id,stream,offset,max_characters)
        if stream!='progress':raise ValueError('worker stream requires job_id')
        if offset<0 or not 1<=max_characters<=1000000: raise ValueError('Invalid pagination')
        text=LOG_PATH.read_text(encoding='utf-8',errors='replace') if LOG_PATH and LOG_PATH.exists() else ''
        end=min(offset+max_characters,len(text))
        return {'success':True,'capture_enabled':LOG_PATH is not None,'file':str(LOG_PATH) if LOG_PATH else None,
                'text':text[offset:end],'next_offset':end,'has_more':end<len(text),'solver_status':async_solver.get_progress(),
                'scope':'captured progress only; historical uncaptured logs unavailable'}

    @mcp.tool(annotations=WRITE)
    @guarded
    def build_geometry(geometry_path:str,model_name:str|None=None)->dict:
        """Explicitly rebuild geometry. May invalidate entity IDs, mesh and solutions. Does not save or solve."""
        ensure_idle(); geom=resolve(model_for(model_name),geometry_path); geom.run()
        return {'success':True,'geometry_path':geometry_path,'built':True,'entity_ids_may_have_changed':True,'saved':False}

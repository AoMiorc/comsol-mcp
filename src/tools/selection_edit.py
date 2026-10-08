"""Validated selection binding edits on existing finalized component geometry."""
from mph.node import cast
from .nodes import guarded,READ,WRITE,resolve,model_for,error_record
from .lifecycle import ensure_idle
from .inspection import native

def selection_at(model,path):
    parts=path.strip('/').split('/')
    if len(parts)<4 or parts[0]!='components' or 'geometry' in parts: raise ValueError('Requires component entity selection, not geometry-object selection')
    node=resolve(model,path)
    if parts[-2]=='selections':
        if str(node.getType())!='Explicit': raise ValueError('Only Explicit named selection entities may be edited; use node properties for Box/Ball/etc')
        return node
    if hasattr(node,'hasSelection') and not node.hasSelection(): raise ValueError('Node has no editable selection')
    return node.selection()

def state(sel):
    return {'geometry':str(sel.geom()),'dimension':int(sel.dim()),'named':str(sel.named()) if hasattr(sel,'named') else '',
            'input_entities':native(sel.inputEntities()),'entities':native(sel.entities()),'inheriting':bool(sel.isInheriting()),'global':bool(sel.isGlobal())}

def restore(sel,old):
    if old['named']: sel.named(old['named'])
    else:
        if hasattr(sel,'named'): sel.named('')
        sel.set(cast(old['input_entities']))

def register_selection_edit_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def selection_get_binding(path:str,model_name:str|None=None)->dict:
        """Read exact binding and input entities of a component material/physics/mesh selection or Explicit selection node."""
        return {'success':True,**state(selection_at(model_for(model_name),path))}

    @mcp.tool(annotations=WRITE)
    @guarded
    def selection_set_binding(path:str,entity_ids:list[int]|None=None,named_selection:str|None=None,allow_empty:bool=False,model_name:str|None=None)->dict:
        """Bind an existing node to explicit entity IDs OR a component named selection tag.
        Exactly one input required. Checks current geometry/dimension and ID bounds; reads back; attempts rollback on failure.
        Does not alter dimension, create nodes, build, solve or save. Inherited/global bindings and geometry-object selections unsupported.
        """
        ensure_idle()
        if (entity_ids is None)==(named_selection is None): raise ValueError('Supply exactly one of entity_ids/named_selection')
        model=model_for(model_name);sel=selection_at(model,path);before=state(sel)
        if before['inheriting'] or before['global'] or before['dimension']<0: raise ValueError('Inherited/global binding requires a dedicated operation')
        comp=model.java.component(path.strip('/').split('/')[1]);geom=comp.geom(before['geometry'])
        if entity_ids is not None:
            if not entity_ids and not allow_empty: raise ValueError('Empty selection requires allow_empty=true')
            count=int(geom.getNEntities()[before['dimension']])
            if any(i<1 or i>count for i in entity_ids) or len(set(entity_ids))!=len(entity_ids): raise ValueError('Invalid or duplicate entity ID')
        else:
            if not hasattr(sel,'named'): raise ValueError('This selection cannot bind by name')
            if path.strip('/').split('/')[-2]=='selections': raise ValueError('Named selection self/reference composition unsupported')
            if named_selection not in [str(t) for t in comp.selection().tags()]: raise ValueError('Named selection not found in component')
            target=comp.selection(named_selection)
            if str(target.geom())!=before['geometry'] or int(target.dim())!=before['dimension']: raise ValueError('Named selection geometry/dimension mismatch')
            if not list(target.entities()) and not allow_empty: raise ValueError('Named selection is empty')
        try:
            if named_selection is not None: sel.named(named_selection)
            else:
                if hasattr(sel,'named'): sel.named('')
                sel.set(cast(entity_ids))
            after=state(sel)
            if named_selection is not None and after['named']!=named_selection: raise RuntimeError('Named binding readback mismatch')
            if entity_ids is not None and sorted(after['entities'])!=sorted(entity_ids): raise RuntimeError('Entity readback mismatch')
        except Exception as exc:
            failure=error_record(exc,'selection_set_binding');rollback_error=None
            try: restore(sel,before)
            except Exception as re: rollback_error=str(re)
            return {'success':False,**failure,'rollback_attempted':True,'rollback_error':rollback_error}
        return {'success':True,'path':path,'before':before,'after':after,'saved':False,'validation_required':True}

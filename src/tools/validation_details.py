"""Current geometry identity evidence and explicit COMSOL dependency checks."""
import math
from mph.node import cast
from .inspection import native
from .nodes import resolve


def issue(items,path,kind,detail,severity='review',**extra):
    items.append({'path':path,'kind':kind,'detail':detail,'severity':severity,**extra})


def close(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-30)
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(close(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    return a==b


def measure_entities(geom,keys):
    """Inspect finalized entity geometry while restoring the measurement selection."""
    measure=geom.measureFinal();sel=measure.selection()
    previous_dim=int(sel.dim());previous=native(sel.entities());named=str(sel.named())
    previous_input=native(sel.inputEntities()) if hasattr(sel,'inputEntities') else previous
    result={}
    try:
        for dim,entity in sorted(keys):
            sel.geom(dim);sel.set(cast([entity]))
            value={'bbox':native(measure.getBoundingBox()),'unit':str(geom.lengthUnit())}
            if dim>0:
                value['measure']=float(measure.getVolume())
                value['adjacent_lower_ids']=native(geom.getAdj(dim,dim-1,entity))
            result[f'{dim}:{entity}']=value
    finally:
        sel.geom(previous_dim)
        if named:sel.named(named)
        elif previous_input is None:sel.all()
        elif previous_input:sel.set(cast(previous_input))
        else:sel.clear()
    return result


def enrich(model,data,all_nodes,max_entities=2000):
    issues=data['issues'];bindings={};fingerprints={};pending={};dirty=set()
    for n in all_nodes:
        path=n['path']
        if '/geometry/' in path and '/features/' in path and n.get('active') is not False:
            try:
                feature=resolve(model,path)
                if hasattr(feature,'status'):
                    state=str(feature.status())
                    if state not in ('built',''): 
                        geometry='/'.join(path.split('/')[:4]);dirty.add(geometry)
                        issue(issues,path,'geometry_requires_build',state,'error' if state=='error' else 'review',geometry=geometry)
            except Exception as exc:issue(issues,path,'geometry_state_unavailable',str(exc),'unknown')
    for path,mesh in data['meshes'].items():
        try:
            obj=resolve(model,path);mesh.update(complete=bool(obj.isComplete()),geometry=str(obj.geom()),has_problems=bool(obj.hasProblems()))
            if mesh['empty'] or not mesh['complete']:issue(issues,path,'mesh_requires_build','Mesh is empty or not complete')
            if mesh['has_problems']:issue(issues,path,'mesh_problems','COMSOL reports mesh problems; review mesh warnings/errors','review')
        except Exception as exc:issue(issues,path,'mesh_state_unavailable',str(exc),'unknown')
    for tag,solution in data['solutions'].items():
        path='global/solvers/'+tag
        try:
            obj=model.java.sol(tag);solution.update(study=str(obj.study()),has_problems=bool(obj.hasProblems()))
            if solution['has_problems']:
                message=obj.getErrorMessage()
                issue(issues,path,'solver_problems',str(message) if message else 'Solver reports warnings/problems','error' if message else 'review')
            if solution['empty']:issue(issues,path,'solution_empty','No stored solution')
        except Exception as exc:issue(issues,path,'solution_state_unavailable',str(exc),'unknown')
    for n in all_nodes:
        path=n['path'];selection=n.get('selection')
        if not isinstance(selection,dict) or not path.startswith('components/') or '/geometry/' in path:continue
        dim=selection.get('dimension',-1)
        if not isinstance(dim,int) or dim<0 or selection.get('is_global'):continue
        try:
            obj=resolve(model,path);sel=obj if hasattr(obj,'entities') else obj.selection();ct=path.split('/')[1];gt=str(sel.geom())
            geometry=f'components/{ct}/geometry/{gt}';entities=[int(v) for v in sel.entities()];named=str(sel.named()) if hasattr(sel,'named') else ''
            inputs=native(sel.inputEntities()) if hasattr(sel,'inputEntities') else None
            bindings[path]={'geometry':geometry,'dimension':dim,'entities':entities,'input_entities':inputs,'named':named}
            if named:
                try:
                    target=model.java.component(ct).selection(named)
                    if int(target.dim())!=dim or str(target.geom())!=gt:issue(issues,path,'named_selection_mismatch',named,'error')
                except Exception as exc:issue(issues,path,'named_selection_missing',str(exc),'error',target=named)
            counts=data['geometry'].get(geometry,{}).get('counts')
            if counts is None or dim>=len(counts):issue(issues,path,'binding_geometry_unavailable',geometry,'unknown');continue
            if isinstance(inputs,list):
                invalid=[i for i in inputs if isinstance(i,int) and (i<1 or i>counts[dim])]
                if invalid:issue(issues,path,'invalid_input_entity_ids',str(invalid),'error')
            if geometry in dirty:
                issue(issues,path,'binding_waits_for_geometry','Geometry is not current; rebuild before checking physical location','unknown');continue
            pending.setdefault(geometry,set()).update((dim,i) for i in entities if 1<=i<=counts[dim])
        except Exception as exc:issue(issues,path,'binding_unreadable',str(exc),'unknown')
    remaining=max_entities
    for geometry,keys in sorted(pending.items()):
        selected=set(sorted(keys)[:remaining]);remaining-=len(selected)
        if len(selected)<len(keys):issue(issues,geometry,'entity_fingerprint_limit',f'{len(selected)} of {len(keys)} entities measured; raise max_entities','unknown')
        try:fingerprints[geometry]=measure_entities(resolve(model,geometry),selected)
        except Exception as exc:issue(issues,geometry,'entity_fingerprint_unavailable',str(exc),'unknown')
    data.update(bindings=bindings,entity_fingerprints=fingerprints,dirty_geometry=sorted(dirty))
    data['references']=references(data,all_nodes,issues)


def references(data,all_nodes,issues):
    paths={n['path'] for n in all_nodes};refs=[]
    def check(path,key,target):
        exists=target in paths;refs.append({'source':path,'property':key,'target':target,'exists':exists})
        if not exists:issue(issues,path,'missing_reference',key+' references '+target,'error',target=target)
    sentinels={'','none','parent','auto','current','zero','default','fromparent'}
    for tag,sol in data['solutions'].items():
        study=sol.get('study')
        if study:check('global/solvers/'+tag,'study','global/studies/'+study)
    for path,mesh in data['meshes'].items():
        if mesh.get('geometry'):check(path,'geom','/'.join(path.split('/')[:2])+'/geometry/'+mesh['geometry'])
    for n in all_nodes:
        path=n['path'];p=n.get('properties',{})
        if path.startswith('results/'):
            for key in ('data','data1','data2'):
                value=p.get(key)
                if isinstance(value,str) and value.lower() not in sentinels:check(path,key,'results/datasets/'+value)
            if n.get('type')=='Solution' and isinstance(p.get('solution'),str):check(path,'solution','global/solvers/'+p['solution'])
            ct=p.get('comp');gt=p.get('geom')
            if isinstance(ct,str) and ct and isinstance(gt,str) and gt:check(path,'comp/geom',f'components/{ct}/geometry/{gt}')
        if n.get('type')=='StudyStep':
            study=p.get('study');step=p.get('studystep')
            if isinstance(study,str) and study:
                check(path,'study','global/studies/'+study)
                if isinstance(step,str) and step:check(path,'studystep',f'global/studies/{study}/features/{step}')
        if path.startswith('global/studies/') and isinstance(p.get('mesh'),list):
            values=p['mesh']
            for index in range(0,len(values)-1,2):
                geometry,mesh=values[index:index+2]
                candidates=[k for k in paths if k.startswith('components/') and k.endswith('/geometry/'+str(geometry))]
                if len(candidates)==1:
                    check(path,'mesh','/'.join(candidates[0].split('/')[:2])+'/mesh/'+str(mesh))
                elif not candidates:issue(issues,path,'missing_reference','Study mesh geometry '+str(geometry)+' is absent','error')
                else:issue(issues,path,'ambiguous_mesh_reference',str(geometry),'unknown')
    graph={}
    for r in refs:
        if r['source'].startswith('results/datasets/') and r['target'].startswith('results/datasets/') and r['exists']:
            graph.setdefault(r['source'],[]).append(r['target'])
    visited=set();active=set()
    def walk(path):
        if path in active:issue(issues,path,'dataset_reference_cycle','Dataset dependency cycle','error');return
        if path in visited:return
        active.add(path)
        for target in graph.get(path,[]):walk(target)
        active.remove(path);visited.add(path)
    for path in graph:walk(path)
    return refs


def compare_bindings(old,new):
    output=[]
    for path in sorted(set(old.get('bindings',{}))|set(new.get('bindings',{}))):
        a=old.get('bindings',{}).get(path);b=new.get('bindings',{}).get(path)
        if a is None or b is None:output.append({'path':path,'status':'binding_added_or_removed'});continue
        if a!=b:output.append({'path':path,'status':'binding_changed','before':a,'after':b});continue
        geometry=b['geometry'];dim=b['dimension'];previous=old.get('entity_fingerprints',{}).get(geometry,{});current=new.get('entity_fingerprints',{}).get(geometry,{})
        moved=[];unknown=[]
        for entity in b['entities']:
            key=f'{dim}:{entity}'
            if key not in previous or key not in current:unknown.append(entity)
            elif not close(previous[key],current[key]):moved.append(entity)
        if moved:output.append({'path':path,'status':'same_ids_geometry_changed','entity_ids':moved})
        if unknown:output.append({'path':path,'status':'geometry_identity_unchecked','entity_ids':unknown})
    return output

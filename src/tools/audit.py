"""Read-only change baselines and conservative invalidation diagnostics."""
import hashlib,json
from uuid import uuid4
from .nodes import guarded,READ,model_for,resolve
from .inspection import inspect_model,native
from .validation_details import enrich,compare_bindings
BASELINES={}

def digest(data): return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def nodes(data):
    if isinstance(data,dict):
        if 'path' in data and 'tag' in data: yield data
        for v in data.values(): yield from nodes(v)
    elif isinstance(data,list):
        for v in data: yield from nodes(v)

def capture(model,max_entities=2000):
    if not 1<=max_entities<=10000:raise ValueError("max_entities must be 1..10000")
    from .lifecycle import dump_model_data
    d=dump_model_data(model,max_depth=20,include_equations=True)
    signatures={n['path']:digest({k:n[k] for k in ('type','properties','expressions','selection','property_selections','active','equation_tables') if k in n}) for n in nodes(d)}
    geometry={};meshes={};solutions={};issues=[]
    for ct in model.java.component().tags():
        c=model.java.component(str(ct))
        for gt in c.geom().tags():
            path=f'components/{ct}/geometry/{gt}';g=c.geom(str(gt))
            try: geometry[path]={'counts':native(g.getNEntities()),'bbox':native(g.getBoundingBox())}
            except Exception as e: issues.append({'path':path,'kind':'geometry_unavailable','detail':str(e)})
        for mt in c.mesh().tags():
            try: meshes[f'components/{ct}/mesh/{mt}']={'empty':bool(c.mesh(str(mt)).isEmpty())}
            except Exception as e: issues.append({'path':f'components/{ct}/mesh/{mt}','kind':'mesh_state_unavailable','detail':str(e)})
    for st in model.java.sol().tags():
        solutions[str(st)]={'empty':bool(model.java.sol(str(st)).isEmpty())}
    for n in nodes(d):
        selection=n.get('selection');path=n['path']
        if not isinstance(selection,dict) or not path.startswith('components/') or '/geometry/' in path: continue
        if selection.get('is_global') or selection.get('dimension',-1)<0: continue
        try:
            node=resolve(model,path);sel=node if hasattr(node,'entities') else node.selection()
            geom_tag=str(sel.geom());ct=path.split('/')[1];dim=int(sel.dim());ents=[int(v) for v in sel.entities()]
            geom=geometry.get(f'components/{ct}/geometry/{geom_tag}')
            if geom and 0<=dim<len(geom['counts']):
                invalid=[v for v in ents if v<1 or v>geom['counts'][dim]]
                if invalid: issues.append({'path':path,'kind':'invalid_entity_ids','entities':invalid})
            if not ents: issues.append({'path':path,'kind':'empty_selection','severity':'review','detail':'May be intentional; not proof of failure'})
        except Exception as e: issues.append({'path':path,'kind':'binding_unreadable','detail':str(e)})
    issues += [{'kind':'read_error',**e} for e in d['read_errors']]
    result={'model_identity':id(model),'model_tag':str(model.java.tag()),'parameters':d['parameters'],'signatures':signatures,'geometry':geometry,'meshes':meshes,'solutions':solutions,'issues':issues,'truncated_paths':d['truncated_paths']}
    enrich(model,result,list(nodes(d)),max_entities)
    return result

def compare(old,new):
    keys=set(old['signatures'])|set(new['signatures'])
    changed=sorted(k for k in keys if old['signatures'].get(k)!=new['signatures'].get(k))
    parameters=old['parameters']!=new['parameters']
    geometry=old['geometry']!=new['geometry'] or any('/geometry/' in p for p in changed)
    bindings=compare_bindings(old,new)
    geometry=geometry or any(b['status']=='same_ids_geometry_changed' for b in bindings)
    dirty=bool(new.get('dirty_geometry'))
    computational_changes=[p for p in changed if not p.startswith('results/')]
    return {'binding_changes':bindings,'geometry_requires_build':dirty,'changed_paths':changed,'parameters_changed':parameters,'geometry_changed':geometry,
            'review_entity_bindings':geometry or parameters or bool(bindings),
            'mesh_may_be_stale':dirty or geometry or parameters or old.get('meshes',{})!=new.get('meshes',{}) or any('/mesh/' in p for p in changed),
            'solution_may_be_stale':bool(computational_changes or parameters or geometry or old.get('meshes',{})!=new.get('meshes',{}))}

def register_audit_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def model_check_baseline(model_name:str|None=None,max_entities:int=2000)->dict:
        """Capture pre-edit settings, finalized per-entity bbox/measure/adjacency, references and build states.
        max_entities bounds total physical fingerprints; truncation is explicit.
        Baselines are process-local (latest 16); no rebuild/solve/save. Use before modifying a model.
        """
        value=capture(model_for(model_name),max_entities);token=uuid4().hex;BASELINES[token]=value
        while len(BASELINES)>16: BASELINES.pop(next(iter(BASELINES)))
        return {'success':True,'baseline_id':token,'issues':value['issues'],'meshes':value['meshes'],'solutions':value['solutions'],'truncated_paths':value['truncated_paths'],**assessment(value)}

    @mcp.tool(annotations=READ)
    @guarded
    def check_model(baseline_id:str|None=None,model_name:str|None=None,max_entities:int=2000)->dict:
        """Check per-entity geometric identity evidence, build states and explicit references against baseline.
        Reports invalid/review_required/incomplete/no_issues_detected; max_entities bounds measurement.
        No automatic rebuild/solve; valid entity numbers do not prove the same geometric identity.
        Reports missing/empty data and read errors. Does not guarantee physical correctness or convergence.
        """
        current=capture(model_for(model_name),max_entities);changes=None
        if baseline_id is not None:
            if baseline_id not in BASELINES: raise ValueError('Unknown/expired baseline; capture before editing in this process')
            old=BASELINES[baseline_id]
            if old['model_tag']!=current['model_tag'] or old.get('model_identity')!=current.get('model_identity'): raise ValueError('Baseline belongs to another model')
            changes=compare(old,current)
        return {'success':True,'issues':current['issues'],'changes':changes,'meshes':current['meshes'],'solutions':current['solutions'],
                'references':current['references'],'truncated_paths':current['truncated_paths'],**assessment(current,changes),
                'scope':'Current finalized geometry fingerprints and explicit study/mesh/solver/dataset references. Same fingerprints do not prove identical geometry or physical validity; no automatic build/solve/save.'}


def assessment(value,changes=None):
    issues=value['issues'];unknown_kinds={'read_error','binding_unreadable','geometry_unavailable','mesh_state_unavailable'}
    incomplete=bool(value['truncated_paths']) or any(i.get('severity')=='unknown' or i['kind'] in unknown_kinds for i in issues)
    invalid=any(i.get('severity')=='error' or i['kind']=='invalid_entity_ids' for i in issues)
    review=bool(issues) or bool(changes and (changes['review_entity_bindings'] or changes['mesh_may_be_stale'] or changes['solution_may_be_stale']))
    actions=[]
    if value.get('dirty_geometry'):actions.append('Rebuild geometry explicitly, then recheck selection identity against the same baseline')
    if changes and changes.get('binding_changes'):actions.append('Review changed or unchecked entity bindings before meshing/solving; no automatic remapping was performed')
    if any(m.get('empty') or not m.get('complete',True) for m in value['meshes'].values()) or (changes and changes['mesh_may_be_stale']):actions.append('Review/rebuild mesh after geometry and selections are confirmed')
    if changes and changes['solution_may_be_stale']:actions.append('Stored solution may predate edits; recompute after prerequisites are confirmed')
    if invalid:actions.insert(0,'Resolve reported errors/missing references before solving')
    return {'complete':not incomplete,'checks_passed':not invalid and not incomplete and not review,
            'verdict':'invalid' if invalid else 'incomplete' if incomplete else 'review_required' if review else 'no_issues_detected',
            'recommended_actions':actions,'measured_entities':sum(len(v) for v in value.get('entity_fingerprints',{}).values()),
            'checked_reference_kinds':['named_selection','mesh_geometry','study_mesh','solver_study','solver_study_step','result_dataset','dataset_solution','dataset_geometry','dataset_cycles'],
            'identity_limit':'bbox, geometric measure and adjacency are evidence, not an exact shape equivalence proof'}

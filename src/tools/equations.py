"""Equation View through COMSOL FeatureInfo, no GUI dependency."""
from mph.node import cast
from .nodes import guarded,READ,WRITE,resolve,model_for
from .inspection import native
from .lifecycle import ensure_idle
from .errors import error_record
TABLES=('Expression','Weak','Constraint','Shape')

def info_at(path,model_name):
    if 'physics' not in path.split('/'): raise ValueError('Requires a physics feature tag path')
    return resolve(model_for(model_name),path).featureInfo('info')

def register_equation_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def equation_inspect(path:str,table:str='Expression',recursive:bool=False,model_name:str|None=None)->dict:
        """Read raw Equation View rows: Expression, Weak, Constraint, Shape.
        Columns follow COMSOL 6.4 API; raw rows retain variable IDs, scope and definition occurrences.
        Expression rows: lock,name,expression,unit,description,entities,operation,occurrence.
        Weak rows: lock,expression,identifier,order,frame,entities,dimension.
        """
        if table not in TABLES: raise ValueError('Unknown Equation View table')
        f=info_at(path,model_name)
        rows=native(f.getInfoTable(table,cast(['recursive']))) if recursive else native(f.getInfoTable(table))
        return {'success':True,'path':path,'table':table,'rows':rows,'count':len(rows),'recursive':recursive}

    @mcp.tool(annotations=READ)
    @guarded
    def equation_list(path:str,model_name:str|None=None)->dict:
        """List available Equation View tables and row counts on a physics feature."""
        f=info_at(path,model_name)
        return {'success':True,'tables':{t:len(f.getInfoTable(t)) for t in TABLES}}

    @mcp.tool(annotations=READ)
    @guarded
    def equation_definitions(path:str,identifier:str,model_name:str|None=None)->dict:
        """Read exact definition occurrences, generated/current expressions and per-occurrence overrides.
        Expression table occurrence numbers are explicit; never confuse them with geometric dimensions.
        """
        f=info_at(path,model_name); entries=definitions(f,identifier)
        return {'success':True,'identifier':identifier,'definitions':entries,'overrides':snapshot(f,identifier,entries)}

    @mcp.tool(annotations=WRITE)
    @guarded
    def equation_set_expression(path:str,identifier:str,expressions:list[str],occurrence:int=0,model_name:str|None=None)->dict:
        """Change one existing definition; preserve sibling occurrences. Verified rollback on failure.
        For constraints use [constraint,constraint_force]. Changes memory only; no solve/save.
        """
        ensure_idle()
        return edit(info_at(path,model_name),identifier,{occurrence:expressions})

    @mcp.tool(annotations=WRITE)
    @guarded
    def equation_set_expressions(path:str,identifier:str,definitions_by_occurrence:dict[str,list[str]],model_name:str|None=None)->dict:
        """Transactionally change several occurrences of one identifier, e.g. {"0":["2"],"1":["3"]}.
        Preflight all entries, preserve siblings and restore the entire identifier on write/readback failure.
        """
        ensure_idle(); changes={}
        for key,value in definitions_by_occurrence.items():
            if not key.isdecimal() or str(int(key))!=key: raise ValueError('Occurrence keys must be canonical nonnegative integers')
            changes[int(key)]=value
        return edit(info_at(path,model_name),identifier,changes)

    @mcp.tool(annotations=WRITE)
    @guarded
    def equation_reset_expression(path:str,identifier:str,model_name:str|None=None,occurrence:int|None=None)->dict:
        """Reset one occurrence while preserving siblings; omit occurrence to reset the whole identifier.
        COMSOL only exposes identifier-wide removeLock; selected reset reconstructs retained overrides.
        Verified rollback on failure. Memory only, no solve/save.
        """
        ensure_idle();f=info_at(path,model_name);entries=definitions(f,identifier)
        return edit(f,identifier,{i:None for i in entries} if occurrence is None else {occurrence:None})


def definitions(info,identifier):
    entries={}
    for table,column,expr_columns in [('Expression',1,[2]),('Weak',2,[1]),('Constraint',4,[1,2])]:
        rows=[r for r in native(info.getInfoTable(table)) if len(r)>column and r[column]==identifier]
        if table!='Expression' and len(rows)>1:
            raise ValueError('Ambiguous definition numbers for '+table+'; refusing to infer occurrence from geometric dimension')
        for row in rows:
            occurrence=int(row[7]) if table=='Expression' else 0
            if occurrence in entries: raise ValueError('Identifier has ambiguous table/occurrence mapping')
            entries[occurrence]={'occurrence':occurrence,'table':table,'expressions':[row[i] for i in expr_columns],'row':row}
    if not entries: raise ValueError('Identifier absent from supported Equation View identifier columns')
    return entries


def snapshot(info,identifier,entries):
    return {i:native(info.getStringArray(identifier,i)) for i in entries}


def restore(info,identifier,state):
    info.removeLock(identifier)
    for i,value in state.items():
        if value is not None: info.set(identifier,i,cast(value))
    if snapshot(info,identifier,state)!=state: raise RuntimeError('Equation override restoration readback differs')


def edit(info,identifier,changes):
    entries=definitions(info,identifier)
    if not changes: raise ValueError('No occurrence changes supplied')
    for i,value in changes.items():
        if i not in entries: raise ValueError('Unknown occurrence '+str(i)+'; available: '+str(sorted(entries)))
        if value is not None and (len(value)!=len(entries[i]['expressions']) or any(not isinstance(e,str) or not e.strip() for e in value)):
            raise ValueError('Wrong expression count or blank expression for occurrence '+str(i))
    before=snapshot(info,identifier,entries);expected={**before,**changes}
    try:
        if any(value is None for value in changes.values()): restore(info,identifier,expected)
        else:
            for i,value in changes.items(): info.set(identifier,i,cast(value))
        after=snapshot(info,identifier,entries)
        if after!=expected: raise RuntimeError('Equation override or sibling readback differs')
    except Exception as exc:
        failure=error_record(exc,'equation_edit');rollback_error=None
        try: restore(info,identifier,before)
        except Exception as rollback_exc: rollback_error=error_record(rollback_exc,'equation_rollback')
        return {'success':False,**failure,'before_overrides':before,'rollback_attempted':True,
                'rollback_verified':rollback_error is None,'rollback_error':rollback_error,'saved':False}
    return {'success':True,'identifier':identifier,'changed_occurrences':sorted(changes),
            'before_overrides':before,'after_overrides':after,'siblings_verified':True,'saved':False,'validation_required':True}

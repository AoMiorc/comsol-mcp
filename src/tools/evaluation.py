"""Lossless JSON evaluation including complex values and all solution indices."""
import numpy as np
from .nodes import guarded, READ, model_for

def encode(value):
    a=np.asarray(value)
    def safe(x):
        if isinstance(x,list): return [safe(v) for v in x]
        if isinstance(x,float) and not np.isfinite(x): return str(x)
        return x
    if np.iscomplexobj(a):
        return {'encoding':'complex','shape':list(a.shape),'real':safe(a.real.tolist()),'imag':safe(a.imag.tolist())}
    return {'encoding':'real','shape':list(a.shape),'value':safe(a.tolist())}

def evaluate_data(expression,unit=None,dataset=None,inner=None,outer=None,model_name=None):
    model=model_for(model_name)
    if isinstance(inner,int): inner=[inner]
    if dataset is not None:
        matches=[n for n in model/'datasets' if n.tag()==dataset or n.name()==dataset]
        if len(matches)!=1: raise ValueError('Dataset tag/label must identify exactly one node')
        dataset_node=matches[0]
    else: dataset_node=None
    # MPh accepts a single outer index. Loop explicitly instead of silently dropping values.
    indices=outer if isinstance(outer,list) else [outer]
    data=[]
    for index in indices:
        value=model.evaluate(expression,unit=unit,dataset=dataset_node,inner=inner,outer=index)
        data.append({'outer':index,**encode(value)})
    return {'success':True,'expression':expression,'requested_unit':unit,'dataset':dataset,'inner':inner,'results':data,'truncated':False}

def register_evaluation_tools(mcp):
    @mcp.tool(annotations=READ)
    @guarded
    def evaluate(expression:str|list[str],unit:str|list[str]|None=None,dataset:str|None=None,inner:int|str|list[int]|None=None,outer:int|list[int]|None=None,model_name:str|None=None)->dict:
        """Evaluate on an existing solution dataset (tag or label). Preserve all modes and complex real/imag arrays.
        Inner: first,last,or 1-based indices. Outer: one index or list. No solve. Derived datasets unsupported by MPh.
        """
        return evaluate_data(expression,unit,dataset,inner,outer,model_name)

    mcp.tool(name='evaluate_global',annotations=READ)(evaluate)

    @mcp.tool(annotations=READ)
    @guarded
    def evaluate_field(expression:str,dataset:str|None=None,inner:int|str|list[int]|None='first',outer:int|None=None,model_name:str|None=None)->dict:
        """Return field values at COMSOL evaluation points alongside x,y,z arrays.
        Uses the existing solution dataset, model/default units; no arbitrary-point interpolation or solve.
        May return large arrays: select one inner/outer solution first.
        """
        model=model_for(model_name)
        dims=[int(model.java.component(str(c)).geom(str(g)).getSDim()) for c in model.java.component().tags() for g in model.java.component(str(c)).geom().tags()]
        axes=['x','y','z'][:max(dims)]
        result=evaluate_data(axes+[expression],None,dataset,inner,outer,model_name)
        result['array_order']=axes+[expression]
        return result

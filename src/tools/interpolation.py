"""Direct COMSOL Interp evaluation with explicit axes, cleanup and stored-result support."""
from uuid import uuid4
import numpy as np
from mph.node import cast
from .nodes import guarded,WRITE,model_for,resolve
from .lifecycle import ensure_idle
from .evaluation import encode
from .paged_results import store_result

def validate_points(points,dimension):
    values=np.asarray(points,dtype=float)
    if values.ndim!=2 or values.shape[1]!=dimension or not 1<=len(values)<=10000 or not np.isfinite(values).all():
        raise ValueError('points must be 1..10000 finite coordinate rows, each matching geometry dimension')
    return values

def interp(model,dataset,expressions,inner,outer,points=None,units=None):
    ensure_idle()
    if not expressions or any(not e.strip() for e in expressions): raise ValueError('Expressions cannot be empty')
    if not inner or any(i<1 for i in inner) or len(set(inner))!=len(inner): raise ValueError('inner must be unique positive 1-based solution indices')
    if outer<1: raise ValueError('outer must be a positive 1-based index')
    datasets=model.java.result().dataset()
    if dataset not in [str(t) for t in datasets.tags()]: raise ValueError('Unknown dataset tag')
    collection=model.java.result().numerical();tag='mcpinterp'+uuid4().hex[:12]
    try:
        node=collection.create(tag,'Interp')
        node.set('data',dataset);node.set('expr',cast(expressions));node.set('solnum',cast(inner));node.set('outersolnum',cast(outer))
        node.set('ext',0.0);node.set('coorderr','off')
        if units is not None:
            if len(units)!=len(expressions): raise ValueError('One unit required per expression')
            node.set('unit',cast(units))
        if points is not None: node.set('coord',cast(points.T.tolist()))
        real=np.array(node.getData(),dtype=float)
        values=real+1j*np.array(node.getImagData(),dtype=float) if node.isComplex() else real
        coordinates=np.array(node.getCoordinates(),dtype=float)
        if values.ndim!=3: raise RuntimeError('Unexpected COMSOL Interp axes; refusing ambiguous output')
        valid=np.isfinite(values)
        return {'success':True,'expression':expressions,'dataset':dataset,'dataset_type':str(datasets.get(dataset).getType()),
                'inner':inner,'outer':outer,'requested_unit':units,'resolved_units':[str(u) for u in node.getStringArray('unit')],
                'axes':['expression','solution','point'],'coordinates':encode(coordinates),
                'coordinate_axes':['coordinate_dimension','point'],'results':[{'outer':outer,**encode(values)}],
                'nonfinite_count':int((~valid).sum()),'validity_note':'Nonfinite values may mean outside geometry or undefined expression; no extrapolation (ext=0).',
                'temporary_node_removed':True,'truncated':False}
    finally:
        if tag in [str(t) for t in collection.tags()]: collection.remove(tag)

def deliver(data,store):
    if not store: return data
    summary=store_result(data)
    summary.update(axes=data['axes'],nonfinite_count=data['nonfinite_count'],resolved_units=data['resolved_units'],dataset_type=data['dataset_type'])
    return summary

def register_interpolation_tools(mcp):
    @mcp.tool(annotations=WRITE)
    @guarded
    def evaluate_points(points:list[list[float]],expressions:list[str],dataset:str='dset1',geometry_path:str='components/comp1/geometry/geom1',inner:list[int]|None=None,outer:int=1,units:list[str]|None=None,store:bool=True,model_name:str|None=None)->dict:
        """Interpolate existing Solution data at explicit point rows [[x,y,z],...]. Coordinates use geometry length unit.
        No extrapolation; undefined/outside values are encoded as nan with nonfinite_count. Default first inner/outer solution.
        geometry_path must match dataset geometry. No solve/build. By default store for evaluate_read_page/export; store=false returns arrays.
        """
        model=model_for(model_name);geom=resolve(model,geometry_path)
        ds=model.java.result().dataset(dataset)
        if str(ds.getType())!='Solution': raise ValueError('Explicit coordinate interpolation currently requires a Solution dataset')
        # Verify geometry association rather than accepting coordinates from another component.
        props=[str(k) for k in ds.properties()]
        parts=geometry_path.strip('/').split('/')
        if len(parts)!=4 or parts[0]!='components' or parts[2]!='geometry': raise ValueError('Use components/tag/geometry/tag')
        if 'geom' in props and str(ds.getString('geom'))!=parts[3]: raise ValueError('Dataset geometry mismatch')
        if 'comp' in props and str(ds.getString('comp'))!=parts[1]: raise ValueError('Dataset component mismatch')
        data=interp(model,dataset,expressions,[1] if inner is None else inner,outer,validate_points(points,int(geom.getSDim())),units)
        data['input_points']=points;data['coordinate_unit']=str(geom.lengthUnit())
        return deliver(data,store)

    @mcp.tool(annotations=WRITE)
    @guarded
    def evaluate_dataset(dataset:str,expressions:list[str],inner:list[int]|None=None,outer:int=1,units:list[str]|None=None,store:bool=True,model_name:str|None=None)->dict:
        """Evaluate existing derived dataset using its own interpolation points (CutPlane, CutLine, Join where compatible).
        Join may require data1(expr)/data2(expr). Unsupported COMSOL combinations return errors, never silent fallback.
        Defaults to saved-result ID for paging/export. Axes expression,solution,point; no solve/build or dataset creation.
        """
        data=interp(model_for(model_name),dataset,expressions,[1] if inner is None else inner,outer,units=units)
        return deliver(data,store)

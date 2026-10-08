"""Persist evaluated results once, then read bounded pages without reevaluation."""
import csv,json,math,shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import numpy as np
from .nodes import guarded,READ,WRITE
from .evaluation import evaluate_data
from .lifecycle import target_file
DATA_DIR=Path(__file__).resolve().parents[2]/'evaluated_data'

def data_path(result_id):
    if len(result_id)!=32 or any(c not in '0123456789abcdef' for c in result_id): raise ValueError('Invalid result ID')
    return DATA_DIR/(result_id+'.json')

def page(data,series,offset,limit):
    if not 0<=series<len(data['results']): raise ValueError('Unknown series')
    if offset<0 or not 1<=limit<=1000: raise ValueError('Require offset>=0 and limit 1..1000')
    source=data['results'][series];total=math.prod(source['shape'])
    if offset>total: raise ValueError('Offset exceeds total values')
    end=min(offset+limit,total)
    result={k:source[k] for k in ('outer','encoding','shape')}
    for k in (('real','imag') if source['encoding']=='complex' else ('value',)):
        result[k]=np.asarray(source[k],dtype=object).reshape(-1)[offset:end].tolist()
    return {'success':True,**result,'series':series,'offset':offset,'next_offset':end,'total_values':total,'has_more':end<total,'flatten_order':'C','snapshot_created_at':data['created_at']}

def store_result(data):
    data['created_at']=datetime.now(timezone.utc).isoformat();token=uuid4().hex
    DATA_DIR.mkdir(exist_ok=True);path=data_path(token)
    with path.open('x',encoding='utf-8') as stream: json.dump(data,stream,ensure_ascii=False,allow_nan=False)
    return {'success':True,'result_id':token,'created_at':data['created_at'],'file':str(path),'expression':data['expression'],'series':[{'index':i,'outer':r['outer'],'shape':r['shape'],'encoding':r['encoding'],'total_values':math.prod(r['shape'])} for i,r in enumerate(data['results'])],'snapshot_not_live':True}

def register_paged_results_tools(mcp):
    @mcp.tool(annotations=WRITE)
    @guarded
    def evaluate_store(expression:str|list[str],unit:str|list[str]|None=None,dataset:str|None=None,inner:int|str|list[int]|None='first',outer:int|list[int]|None=None,model_name:str|None=None)->dict:
        """Evaluate once into a local immutable JSON result snapshot; return metadata only.
        For fields pass ['x','y','z','emw.normE']. Page using evaluate_read_page or export using evaluated_data_export.
        Bounds response size, not COMSOL evaluation memory. Existing solution datasets only. Never solves.
        """
        data=evaluate_data(expression,unit,dataset,inner,outer,model_name)
        return store_result(data)

    @mcp.tool(annotations=READ)
    @guarded
    def evaluate_read_page(result_id:str,series:int=0,offset:int=0,limit:int=100)->dict:
        """Read at most 1000 flattened scalar values (C order) from a saved result, with real/imag together.
        No evaluation repeated; snapshot remains unchanged after model edits. Shape retained for reconstruction.
        """
        data=json.loads(data_path(result_id).read_text(encoding='utf-8'))
        return {'result_id':result_id,**page(data,series,offset,limit)}

    @mcp.tool(annotations=WRITE)
    @guarded
    def evaluated_data_export(result_id:str,file_path:str,format:str='json',overwrite:bool=False)->dict:
        """Export stored values to JSON or CSV. CSV columns: series,outer,flat_index,indices,real,imag.
        Indices are zero-based array indices; all modes and complex components preserved. No reevaluation.
        """
        if format not in ('json','csv'): raise ValueError('Use json or csv')
        source=data_path(result_id)
        if not source.is_file(): raise FileNotFoundError(str(source))
        path=target_file(file_path,'.'+format,overwrite)
        if path==source: raise ValueError('Cannot overwrite immutable result snapshot')
        if format=='json': shutil.copyfile(source,path)
        else:
            data=json.loads(source.read_text(encoding='utf-8'))
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['series','outer','flat_index','indices','real','imag'])
                for i,r in enumerate(data['results']):
                    re=np.asarray(r.get('real',r.get('value')),dtype=object).reshape(-1)
                    im=np.asarray(r['imag'],dtype=object).reshape(-1) if r['encoding']=='complex' else None
                    for j,value in enumerate(re):
                        indices=[int(v) for v in np.unravel_index(j,tuple(r['shape']))] if r['shape'] else []
                        writer.writerow([i,r['outer'],j,json.dumps(indices),value,im[j] if im is not None else 0])
        return {'success':True,'file':str(path),'bytes':path.stat().st_size,'format':format,'result_id':result_id}

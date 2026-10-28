"""Strict, serializable inputs; validation never starts COMSOL."""
import hashlib
import json
import math
import re
from pathlib import Path

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def _number(value, name, positive=True):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if positive and value<=0:raise ValueError(f'{name} must be positive')
    return value

def _keys(value, allowed, name):
    if not isinstance(value,dict):raise ValueError(f'{name} must be an object')
    extra=set(value)-set(allowed)
    if extra:raise ValueError(f'{name}: unknown fields {sorted(extra)}')

def validate_case(value, base_dir=None):
    if isinstance(value,(str,Path)):
        path=Path(value).resolve();base_dir=path.parent;value=read_json(path)
    s=json.loads(json.dumps(value));base=Path(base_dir or '.').resolve()
    _keys(s,['case_id','template','geometry','materials','tuning','study','mesh','runtime'],'case')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',s.get('case_id','')):
        raise ValueError('case_id must be 1..64 ASCII letters, digits, underscores or hyphens')
    s.setdefault('template','height_array_eigenmode')
    if s['template']!='height_array_eigenmode':raise ValueError('Unsupported template')
    g=s.setdefault('geometry',{})
    _keys(g,['rows','cols','pillar_width_nm','pitch_nm','height_levels_nm','encoding','encoding_file','substrate_nm','air_nm','pml_nm'],'geometry')
    for k,d in [('rows',9),('cols',9)]:
        g.setdefault(k,d)
        if type(g[k]) is not int or not 1<=g[k]<=25:raise ValueError(f'{k} must be an integer from 1 to 25')
    for k,d in [('pillar_width_nm',100),('pitch_nm',150),('substrate_nm',500),('air_nm',750),('pml_nm',400)]:
        g.setdefault(k,d);_number(g[k],k)
    if g['pillar_width_nm']>=g['pitch_nm']:raise ValueError('pillar_width_nm must be smaller than pitch_nm')
    if 'encoding_file' in g:
        if 'encoding' in g:raise ValueError('Supply encoding OR encoding_file')
        path=(base/g.pop('encoding_file')).resolve();g['encoding']=read_json(path)
    levels=g.setdefault('height_levels_nm',[100,200])
    if not isinstance(levels,list) or not levels:raise ValueError('height_levels_nm must be nonempty')
    for v in levels:_number(v,'height_levels_nm')
    a=g.get('encoding')
    if not isinstance(a,list) or len(a)!=g['rows']:raise ValueError('encoding row count mismatch')
    for row in a:
        if not isinstance(row,list) or len(row)!=g['cols']:raise ValueError('encoding column count mismatch')
        if any(type(v) is not int or not 0<=v<len(levels) for v in row):raise ValueError('encoding must contain valid integer height-level indices')
    mat=s.setdefault('materials',{})
    _keys(mat,['pillar_index','substrate_index'],'materials')
    for k,d in [('pillar_index',2.4),('substrate_index',1.45)]:mat.setdefault(k,d);_number(mat[k],k)
    t=s.setdefault('tuning',{})
    _keys(t,['parameter','values'],'tuning');t.setdefault('parameter','height_offset_nm');t.setdefault('values',[0])
    if t['parameter']!='height_offset_nm':raise ValueError('Only height_offset_nm is implemented')
    vals=t['values']
    if not isinstance(vals,list) or not vals:raise ValueError('tuning.values must be nonempty')
    for v in vals:_number(v,'height_offset_nm',False)
    if len(set(vals))!=len(vals):raise ValueError('Duplicate tuning values')
    used=[levels[v] for row in a for v in row]
    if min(used)+min(vals)<=0:raise ValueError('Tuned pillar heights must remain positive')
    if max(used)+max(vals)>=g['air_nm']:raise ValueError('Pillars must remain below the air/PML interface')
    st=s.setdefault('study',{})
    _keys(st,['type','search_frequency_THz','number_of_modes'],'study')
    st.setdefault('type','eigenfrequency');st.setdefault('search_frequency_THz',335);st.setdefault('number_of_modes',6)
    if st['type']!='eigenfrequency':raise ValueError('Only eigenfrequency studies are implemented')
    _number(st['search_frequency_THz'],'search_frequency_THz')
    if type(st['number_of_modes']) is not int or not 1<=st['number_of_modes']<=40:raise ValueError('number_of_modes must be 1..40')
    mesh=s.setdefault('mesh',{});_keys(mesh,['level'],'mesh');mesh.setdefault('level',5)
    if type(mesh['level']) is not int or not 1<=mesh['level']<=9:raise ValueError('mesh.level must be 1..9')
    rt=s.setdefault('runtime',{});_keys(rt,['cores','timeout_seconds','version'],'runtime')
    rt.setdefault('cores',4);rt.setdefault('timeout_seconds',1800);rt.setdefault('version','6.4')
    if type(rt['cores']) is not int or not 1<=rt['cores']<=6:raise ValueError('cores must be 1..6')
    _number(rt['timeout_seconds'],'timeout_seconds')
    if not isinstance(rt['version'],str) or not re.fullmatch(r'\d+\.\d+',rt['version']):raise ValueError('Invalid COMSOL version')
    return s

def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_manifest(value):
    base=Path('.')
    if isinstance(value,(str,Path)):
        path=Path(value).resolve();base=path.parent;value=read_json(path)
    _keys(value,['cases'],'manifest')
    if not isinstance(value.get('cases'),list) or not value['cases']:raise ValueError('cases must be a nonempty list')
    cases=[validate_case((base/v) if isinstance(v,str) else v,base) for v in value['cases']]
    if len({s['case_id'] for s in cases})!=len(cases):raise ValueError('Duplicate case_id')
    return {'cases':cases}

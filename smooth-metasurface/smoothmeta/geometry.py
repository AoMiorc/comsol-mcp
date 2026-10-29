"""Exact binary mask compiler: row-run merging, integer union, collinear merging."""
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from shapely import normalize
from shapely.affinity import scale
from shapely.geometry import Polygon, MultiPolygon, box, mapping
from shapely.ops import unary_union

SOLVER_DEFAULTS = dict(thicknesses_nm=[165.9], slab_index=2.4, substrate_index=1.45,
    air_nm=750., substrate_nm=750., pml_nm=350., search_THz=335.,
    num_modes=6, mesh_level=4, cores=4, max_elements=100000)
CHIRAL_DEFAULTS = dict(enabled=False, medium_index=1.45, epsilon_imag=-1e-4,
    mu_real=1., mu_imag=-1e-5, kappa_real=1.2e-4, kappa_imag=-3e-5)


def validate_chiral(settings=None):
    if settings is None: settings={}
    if not isinstance(settings,dict) or set(settings)-set(CHIRAL_DEFAULTS):
        raise ValueError('Unknown chiral settings')
    result={**CHIRAL_DEFAULTS,**settings}
    if type(result['enabled']) is not bool:raise ValueError('chiral.enabled must be boolean')
    for key,value in result.items():
        if key=='enabled':continue
        if type(value) not in (int,float) or not np.isfinite(value):raise ValueError('Invalid chiral.'+key)
    if result['medium_index']<=0 or result['mu_real']<=0:raise ValueError('Positive medium_index and mu_real required')
    return result


def validate(encoding, period_nm=550.):
    a = np.asarray(encoding)
    if a.ndim != 2 or min(a.shape) < 2 or max(a.shape) > 512 or not np.isin(a, [0, 1]).all():
        raise ValueError('Expected binary 2D matrix, dimensions 2..512')
    if not a.any():
        raise ValueError('Empty material mask')
    if isinstance(period_nm, bool) or not isinstance(period_nm, (int, float)) or not np.isfinite(period_nm) or period_nm <= 0:
        raise ValueError('period_nm must be finite and positive')
    return a.astype(np.uint8), dict(period_nm=float(period_nm))


def load_spec(path):
    path = Path(path)
    s = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(s, dict) or set(s) - {'encoding', 'encoding_file', 'geometry', 'solver', 'chiral'}:
        raise ValueError('Unknown spec fields')
    if ('encoding' in s) == ('encoding_file' in s):
        raise ValueError('Supply exactly one of encoding or encoding_file')
    if set(s.get('geometry', {})) - {'period_nm'}:
        raise ValueError('Exact compiler supports period_nm only; smoothing settings are obsolete')
    source = s.get('encoding')
    if 'encoding_file' in s:
        f = path.parent / s['encoding_file']
        source = np.load(f, allow_pickle=False) if f.suffix == '.npy' else json.loads(f.read_text(encoding='utf-8-sig'))
    a, opts = validate(source, **s.get('geometry', {}))
    if set(s.get('solver', {})) - set(SOLVER_DEFAULTS):
        raise ValueError('Unknown solver fields')
    sol = {**SOLVER_DEFAULTS, **s.get('solver', {})}
    for k in ['slab_index', 'substrate_index', 'air_nm', 'substrate_nm', 'pml_nm', 'search_THz']:
        if type(sol[k]) not in (int, float) or not np.isfinite(sol[k]) or sol[k] <= 0:
            raise ValueError('Invalid ' + k)
    for k, lo, hi in [('num_modes', 1, 30), ('mesh_level', 1, 9), ('cores', 1, 6), ('max_elements', 100, 500000)]:
        if type(sol[k]) is not int or not lo <= sol[k] <= hi:
            raise ValueError('Invalid ' + k)
    ts = sol['thicknesses_nm']
    if not isinstance(ts, list) or not ts or len(ts) > 30 or any(type(t) not in (int, float) or not np.isfinite(t) or t <= 0 for t in ts):
        raise ValueError('Invalid thicknesses_nm')
    if len(set(ts)) != len(ts):
        raise ValueError('Duplicate thickness values')
    return dict(encoding=a.tolist(), geometry=opts, solver=sol, chiral=validate_chiral(s.get('chiral')))


def parts(g):
    if g.is_empty: return []
    if isinstance(g, Polygon): return [g]
    if isinstance(g, MultiPolygon): return list(g.geoms)
    raise ValueError('Expected polygon geometry: ' + g.geom_type)


def signature(g):
    p = parts(g)
    return len(p), sum(len(x.interiors) for x in p)


def vertices(g):
    return sum(len(r.coords) - 1 for p in parts(g) for r in [p.exterior, *p.interiors])


def merged_rectangles(a):
    """Disjoint run tiling, not a globally minimal rectangle cover."""
    active = {}; rectangles = []; row_runs = 0
    for y in range(len(a) + 1):
        row = a[y] if y < len(a) else np.zeros(a.shape[1], dtype=np.uint8)
        cuts = np.flatnonzero(np.diff(np.r_[0, row, 0].astype(int)))
        runs = {tuple(map(int, pair)) for pair in cuts.reshape(-1, 2)}
        row_runs += len(runs)
        for interval in active.keys() - runs:
            rectangles.append((interval[0], active[interval], interval[1], y))
        active = {interval: active.get(interval, y) for interval in runs}
    return sorted(rectangles), row_runs


def _corners(ring):
    c = np.asarray(ring.coords[:-1], dtype=np.int64)
    incoming = c - np.roll(c, 1, axis=0)
    outgoing = np.roll(c, -1, axis=0) - c
    cross = incoming[:, 0] * outgoing[:, 1] - incoming[:, 1] * outgoing[:, 0]
    return c[cross != 0].tolist()


def exact_pixels(a, L):
    rectangles, _ = merged_rectangles(np.asarray(a))
    g = unary_union([box(*r) for r in rectangles])
    return scale(g, xfact=L/a.shape[1], yfact=L/a.shape[0], origin=(0, 0))


def prepare_geometry(encoding, **kwargs):
    start = time.perf_counter()
    a, opts = validate(encoding, **kwargs)
    rectangles, row_runs = merged_rectangles(a)
    raw = unary_union([box(*r) for r in rectangles])
    compact = normalize(unary_union([Polygon(_corners(p.exterior), [_corners(h) for h in p.interiors]) for p in parts(raw)]))
    difference = compact.symmetric_difference(raw).area
    if not compact.is_valid or difference != 0 or signature(compact) != signature(raw):
        raise RuntimeError('Exact geometry invariant failed')
    if compact.area != int(a.sum()):
        raise RuntimeError('Pixel area invariant failed')
    L = opts['period_nm']; ny, nx = a.shape
    g = scale(compact, xfact=L/nx, yfact=L/ny, origin=(0, 0))
    diagonal = ((a[:-1, :-1] == a[1:, 1:]) & (a[1:, :-1] == a[:-1, 1:]) & (a[:-1, :-1] != a[1:, :-1]))
    contacts = int(diagonal.sum())
    seam = max(float(np.count_nonzero(a[:, 0] != a[:, -1]))*L/ny,
               float(np.count_nonzero(a[0] != a[-1]))*L/nx)
    exposed = int(4*int(a.sum()) - 2*(int((a[:, :-1] & a[:, 1:]).sum()) + int((a[:-1] & a[1:]).sum())))
    warnings = ['Exact compression does not guarantee fewer FEM elements or a larger optical gap.']
    if contacts: warnings.append('Zero-width diagonal contacts exist; COMSOL backend rejects them.')
    if seam: warnings.append('Opposite material traces differ; current COMSOL backend requires matching traces.')
    fingerprint = hashlib.sha256(a.tobytes() + json.dumps([list(a.shape), opts, 2], sort_keys=True).encode()).hexdigest()
    meta = dict(geometry_version=2, fingerprint=fingerprint, settings=opts, input_shape=list(a.shape),
        filled_pixels=int(a.sum()), row_runs=row_runs, merged_rectangles=len(rectangles),
        exposed_unit_edges=exposed, vertices_before_collinear_merge=vertices(raw), vertices_final=vertices(compact),
        final_components_holes=signature(compact), area_fraction=float(a.mean()),
        symmetric_difference_grid_area=difference, exact_geometry_verified=True,
        diagonal_contacts=contacts, opposite_material_trace_difference_nm=seam,
        preparation_seconds=time.perf_counter()-start, geometry_type='exact_orthogonal_polygons',
        warnings=warnings, manufacturability_certified=False)
    return dict(geometry=g, encoding=a, metadata=meta)


def export_geometry(result, folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    payload = dict(metadata=result['metadata'], polygons_nm=[dict(outer=list(p.exterior.coords)[:-1],
        holes=[list(h.coords)[:-1] for h in p.interiors]) for p in parts(result['geometry'])])
    (folder/'geometry.json').write_text(json.dumps(payload, indent=2), encoding='utf8')
    (folder/'geometry.geojson').write_text(json.dumps(dict(type='Feature', properties={'units': 'nm'}, geometry=mapping(result['geometry']))), encoding='utf8')
    np.save(folder/'encoding.npy', result['encoding'])
    return payload

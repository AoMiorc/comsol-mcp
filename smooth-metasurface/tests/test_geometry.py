import json
import numpy as np
import pytest
from shapely.geometry import box
from shapely.ops import unary_union
from smoothmeta.geometry import prepare_geometry, load_spec, signature, merged_rectangles


def assert_exact(a):
    r = prepare_geometry(a, period_nm=float(a.shape[1]))
    from shapely.affinity import scale
    ref = unary_union([box(int(x), int(y), int(x)+1, int(y)+1) for y, x in np.argwhere(a)])
    ref = scale(ref, xfact=1, yfact=a.shape[1]/a.shape[0], origin=(0, 0))
    assert r['geometry'].symmetric_difference(ref).area == 0
    assert r['geometry'].is_valid
    assert signature(r['geometry']) == signature(ref)
    return r


def test_full_native_220():
    r = assert_exact(np.ones((220, 220), dtype=np.uint8))
    assert r['metadata']['vertices_final'] == 4
    assert r['metadata']['merged_rectangles'] == 1


def test_holes_islands_and_sharp_notch():
    a = np.ones((30, 30), dtype=np.uint8)
    a[3:27, 3:27] = 0
    a[9:19, 10:21] = 1
    a[0:2, 15:18] = 0
    r = assert_exact(a)
    assert signature(r['geometry']) == (2, 1)
    assert (15., 2.) in list(max(r['geometry'].geoms, key=lambda p:p.area).exterior.coords)


@pytest.mark.parametrize('seed', range(16))
def test_random_masks_against_independent_pixel_union(seed):
    a = np.random.default_rng(seed).integers(0, 2, (12, 12), dtype=np.uint8)
    assert_exact(a)


def test_checkerboard_no_false_compression():
    a = (np.indices((12, 12)).sum(axis=0) % 2).astype(np.uint8)
    r = assert_exact(a)
    assert r['metadata']['vertices_final'] == 4*int(a.sum())
    assert r['metadata']['diagonal_contacts'] == 121


def test_run_merge_preserves_single_pixel_corner():
    a = np.zeros((20, 20), dtype=np.uint8)
    a[2:17, 4:13] = 1; a[16, 13] = 1
    r = assert_exact(a)
    assert r['metadata']['vertices_final'] == 6
    assert len(merged_rectangles(a)[0]) == 2


def test_nonmatching_seam_is_reported_not_modified():
    a = np.zeros((8, 8), dtype=np.uint8); a[1:6, :3] = 1
    r = assert_exact(a)
    assert r['metadata']['opposite_material_trace_difference_nm'] > 0


def test_spec_file_and_obsolete_settings(tmp_path):
    np.save(tmp_path/'mask.npy', np.ones((4, 4)))
    p = tmp_path/'spec.json'
    p.write_text(json.dumps(dict(encoding_file='mask.npy', geometry=dict(period_nm=550))))
    assert load_spec(p)['encoding'] == np.ones((4, 4)).tolist()
    p.write_text(json.dumps(dict(encoding=[[1,1],[1,1]], geometry=dict(sigma_nm=0))))
    with pytest.raises(ValueError, match='obsolete'): load_spec(p)


@pytest.mark.parametrize('a', [np.zeros((4,4)), [[0,2],[1,0]], [[1]], [[1,0],[1]]])
def test_invalid_masks(a):
    with pytest.raises(ValueError): prepare_geometry(a)

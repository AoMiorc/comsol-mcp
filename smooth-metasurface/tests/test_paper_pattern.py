import numpy as np
from paper_gap import paper_mask
from smoothmeta.geometry import prepare_geometry


def test_paper_pattern_symmetry_and_cut():
    a=paper_mask(110)
    assert np.array_equal(a,a[:,::-1])  # preserve the original mirror symmetry
    assert np.all(a[93:,:])  # cut starts at 465 nm on the 5 nm grid
    assert not a[92,54]      # hole remains below the cut
    assert a.sum()==7110
    r=prepare_geometry(a,period_nm=550)
    assert r['metadata']['final_components_holes']==(1,1)
    assert r['metadata']['vertices_final']==184
    assert r['metadata']['opposite_material_trace_difference_nm']==0

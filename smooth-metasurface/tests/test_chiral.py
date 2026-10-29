import json
from pathlib import Path
import pytest
from smoothmeta.geometry import load_spec, validate_chiral
from smoothmeta.pasteur import equations


def test_mode_cy_nine_constitutive_definitions():
    reference=json.loads((Path(__file__).parent/'fixtures/mode_cy_reference.json').read_text(encoding='utf8'))
    actual=equations('ewfd')
    assert actual=={row['identifier']:row['expression'] for row in reference}
    assert set(actual)=={'ewfd.'+v for v in ['Dx','Dy','Dz','Hx','Hy','Hz','dHdtx','dHdty','dHdtz']}
    mapped=equations()
    assert all('ewfd.' not in e for e in mapped.values())
    assert all('emw.iomega' in mapped['emw.dHdt'+a] for a in 'xyz')


def test_zero_chirality_preserves_same_medium():
    a=validate_chiral({'enabled':True});b=validate_chiral({'enabled':True,'kappa_real':0,'kappa_imag':0})
    assert all(a[k]==b[k] for k in a if not k.startswith('kappa_'))
    assert b['enabled']


@pytest.mark.parametrize('settings', [{'enabled':'true'}, {'kappa_real':float('nan')},
    {'kappa_imag':True}, {'medium_index':0}, {'mu_real':-1}, {'kapa':.1}])
def test_invalid_physics_settings(settings):
    with pytest.raises(ValueError):validate_chiral(settings)


def test_legacy_spec_does_not_silently_change_physics(tmp_path):
    p=tmp_path/'legacy.json';p.write_text(json.dumps({'encoding':[[1,1],[1,0]]}))
    assert load_spec(p)['chiral']['enabled'] is False

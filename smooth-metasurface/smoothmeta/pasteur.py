"""Mode-CY Equation View overrides, isolated to a physical chiral wave-equation feature.

The reference uses ewfd. Namespace mapping is the sole expression change here.
No weak-form approximation is substituted for the nine constitutive definitions.
"""
import json
from importlib.resources import files


def equations(namespace='emw'):
    source=json.loads(files('smoothmeta').joinpath('mode_cy_equations.json').read_text(encoding='utf8'))
    return {item['identifier'].replace('ewfd.',namespace+'.'):
        item['expression'].replace('ewfd.',namespace+'.') for item in source}


def verify(feature, namespace='emw'):
    info=feature.featureInfo('info');expected=equations(namespace)
    rows=info.getInfoTable('Expression')
    checks=[]
    for identifier,expression in expected.items():
        occurrences=[int(str(row[7])) for row in rows if str(row[1])==identifier]
        if occurrences!=[0]:raise RuntimeError(f'Ambiguous occurrence for {identifier}: {occurrences}')
        locked=info.getStringArray(identifier,0)
        actual=None if locked is None else list(map(str,locked))
        current=[str(row[2]) for row in rows if str(row[1])==identifier and int(str(row[7]))==0]
        if actual!=[expression] or current!=[expression]:
            raise RuntimeError('Constitutive override missing or changed: '+identifier)
        checks.append(dict(identifier=identifier,occurrence=0,expression=expression,verified=True))
    return checks


def apply(feature, namespace='emw'):
    from mph.node import cast
    info=feature.featureInfo('info');rows=info.getInfoTable('Expression')
    expected=equations(namespace)
    # Fail before mutation if the installed COMSOL interface has another definition layout.
    for identifier in expected:
        occurrences=[int(str(row[7])) for row in rows if str(row[1])==identifier]
        if occurrences!=[0]:raise RuntimeError(f'Unsupported definition layout for {identifier}: {occurrences}')
    for identifier,expression in expected.items():info.set(identifier,0,cast([expression]))
    return verify(feature,namespace)

"""Read-only inspection of the live Java model, including nested work planes.

Never builds geometry, evaluates expressions, solves, or saves. Errors and depth
limits are data, not empty success results. Entity IDs refer to the current mesh/
geometry and must not be assumed stable after geometry changes.
"""

from .errors import error_record
from pathlib import Path
import math
import jpype
from mph.node import get
from mcp.types import ToolAnnotations
from .session import session_manager


def native(value):
    if jpype.isJVMStarted() and isinstance(value, jpype.JString):
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, 'tolist'):
        return native(value.tolist())
    if isinstance(value, dict):
        return {str(k): native(v) for k, v in value.items()}
    return [native(v) for v in value]


class Reader:
    def __init__(self, max_depth):
        self.max_depth = max_depth
        self.errors = []
        self.truncated = []

    def read(self, path, fn):
        try:
            return native(fn())
        except Exception as exc:
            error = {'path': path, 'error': str(exc)}
            self.errors.append(error)
            return {'read_error': str(exc)}

    def selection(self, selection, path):
        data = {}
        # Only getters: all(), set(), geom(...) are deliberately never called.
        for key, method in [('dimension', 'dim'), ('named', 'named'),
                            ('entities', 'entities'), ('is_global', 'isGlobal')]:
            if method == 'entities' and hasattr(selection, 'objects'):
                continue
            if hasattr(selection, method):
                data[key] = self.read(path + '/' + key, lambda m=method: getattr(selection, m)())
        if hasattr(selection, 'objects'):
            objects = self.read(path + '/objects', lambda: selection.objects())
            data['objects'] = objects
            if isinstance(objects, list) and hasattr(selection, 'entities') and data.get('dimension') != -1:
                data['object_entities'] = {obj: self.read(path + '/' + obj, lambda o=obj: selection.entities(o)) for obj in objects}
        return data

    def collection(self, parent, method, path, depth):
        try:
            collection = getattr(parent, method)()
            tags = [str(t) for t in collection.tags()]
        except Exception as exc:
            self.errors.append({'path': path, 'error': str(exc)})
            return {'read_error': str(exc)}
        if depth > self.max_depth and tags:
            self.truncated.append(path)
            return {'truncated': True, 'tags': tags}
        result = []
        for tag in tags:
            child_path = path + '/' + tag
            try:
                child = getattr(parent, method)(tag)
                result.append(self.node(child, child_path, depth))
            except Exception as exc:
                self.errors.append({'path': child_path, 'error': str(exc)})
                result.append({'tag': tag, 'path': child_path, 'read_error': str(exc)})
        return result

    def node(self, java, path, depth=0):
        result = {'path': path}
        for key, method in [('tag', 'tag'), ('label', 'label'), ('type', 'getType'), ('active', 'isActive')]:
            if method == 'getType' and hasattr(java, 'lengthUnit'):
                result['type'] = 'GeometrySequence'
                result['space_dimension'] = self.read(path + '/space_dimension', lambda: java.getSDim())
                continue
            if hasattr(java, method):
                result[key] = self.read(path + '/' + key, lambda m=method: getattr(java, m)())
        if hasattr(java, 'properties'):
            names = self.read(path + '/property_names', lambda: java.properties())
            result['properties'] = {}
            if isinstance(names, list):
                for name in names:
                    prop_path = path + '/properties/' + name
                    result['properties'][name] = self.read(prop_path, lambda n=name: get(java, n))
                    datatype = self.read(prop_path + '/type', lambda n=name: str(java.getValueType(n)))
                    if isinstance(datatype, str) and datatype.startswith('Double'):
                        getter = {'Double': 'getString', 'DoubleArray': 'getStringArray',
                                  'DoubleMatrix': 'getStringMatrix', 'DoubleRowMatrix': 'getStringMatrix'}.get(datatype)
                        if getter:
                            result.setdefault('expressions', {})[name] = self.read(
                                path + '/expressions/' + name, lambda n=name, m=getter: getattr(java, m)(n))
                    if datatype == 'Selection':
                        try:
                            result.setdefault('property_selections', {})[name] = self.selection(java.selection(name), prop_path)
                        except Exception as exc:
                            self.errors.append({'path': prop_path + '/selection', 'error': str(exc)})
                            result.setdefault('property_selections', {})[name] = {'read_error': str(exc)}
        has_selection = True
        if hasattr(java, 'hasSelection'):
            has_selection = self.read(path + '/has_selection', lambda: bool(java.hasSelection()))
            result['has_selection'] = has_selection
        if hasattr(java, 'entities') and hasattr(java, 'dim'):
            result['selection'] = self.selection(java, path + '/selection')
        elif has_selection is True and hasattr(java, 'selection') and not hasattr(java, 'lengthUnit'):
            # Geometry features require selection(property), handled above.
            if result.get('type') not in ('WorkPlane',) and '/geometry/' not in path:
                try:
                    result['selection'] = self.selection(java.selection(), path + '/selection')
                except Exception as exc:
                    self.errors.append({'path': path + '/selection', 'error': str(exc)})
                    result['selection'] = {'read_error': str(exc)}
        for method, key in [('feature', 'features'), ('propertyGroup', 'property_groups')]:
            if hasattr(java, method):
                result[key] = self.collection(java, method, path + '/' + key, depth + 1)
        if result.get('type') == 'WorkPlane':
            if depth >= self.max_depth:
                result['workplane_geometry'] = {'truncated': True}
                self.truncated.append(path + '/workplane_geometry')
            else:
                try:
                    result['workplane_geometry'] = self.node(java.geom(), path + '/workplane_geometry', depth + 1)
                except Exception as exc:
                    self.errors.append({'path': path + '/workplane_geometry', 'error': str(exc)})
                    result['workplane_geometry'] = {'read_error': str(exc)}
        if hasattr(java, 'lengthUnit'):
            result['length_unit'] = self.read(path + '/length_unit', lambda: java.lengthUnit())
        return result


def inspect_model(model, sections=None, max_depth=12):
    allowed = ['geometry', 'materials', 'physics', 'selections', 'mesh', 'studies', 'solvers']
    sections = allowed if sections is None else sections
    unknown = sorted(set(sections) - set(allowed))
    if unknown or not 0 <= max_depth <= 30:
        return {'success': False, 'error': 'Unknown sections or max_depth outside 0..30', 'allowed_sections': allowed}
    reader = Reader(max_depth)
    result = {'success': True, 'source': 'live_comsol_java_api', 'model': model.name(),
              'requested_sections': sections, 'parameters': model.parameters(), 'components': []}
    java = model.java
    for tag in java.component().tags():
        comp = java.component(str(tag))
        entry = {'tag': str(tag), 'label': str(comp.label())}
        for section, method in [('geometry', 'geom'), ('materials', 'material'), ('physics', 'physics'), ('selections', 'selection'), ('mesh', 'mesh')]:
            if section in sections:
                entry[section] = reader.collection(comp, method, 'components/' + str(tag) + '/' + section, 0)
        result['components'].append(entry)
    for section, method in [('studies', 'study'), ('solvers', 'sol'), ('materials', 'material'), ('selections', 'selection')]:
        if section in sections:
            result['global_' + section] = reader.collection(java, method, 'global/' + section, 0)
    result.update(read_errors=reader.errors, truncated_paths=reader.truncated,
                  complete=not reader.errors and not reader.truncated,
                  scope='Requested collections and exposed properties; not a complete serialization of every COMSOL object. Expressions are not evaluated.')
    return result


def register_inspection_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def model_inspect_detailed(model_name: str | None = None, sections: list[str] | None = None, max_depth: int = 12) -> dict:
        """Read live geometry recursively (including work planes), materials and entity
        selections, physics features/boundaries, mesh, studies and solver settings.
        sections: geometry, materials, physics, selections, mesh, studies, solvers.
        Reports read_errors and truncated_paths; complete applies only to requested
        scope. Does not build, solve, modify or save. Property expressions keep units.
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {'success': False, 'error': 'Model not loaded: ' + str(model_name)}
        try:
            return inspect_model(model, sections, max_depth)
        except Exception as exc:
            return {**error_record(exc, 'model_inspect_detailed'), 'success': False, 'error': str(exc)}

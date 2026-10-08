import unittest
from unittest.mock import patch
from src.tools.inspection import Reader, native, inspect_model

class Props:
    def tag(self): return 'f1'
    def properties(self): return ['bad', 'good']
    def getValueType(self, name):
        if name == 'bad': raise ValueError('unavailable property')
        return 'String'
    def getString(self, name): return '550[nm]'

class Collection:
    def tags(self): return ['f1']
class Parent:
    def feature(self, tag=None):
        return Collection() if tag is None else Props()
class ObjectSelection:
    def dim(self): return -1
    def objects(self): return ['sq1','c1']
    def entities(self, obj): raise AssertionError('Whole-object selection must not call entities')
class EntitySelection:
    def dim(self): return 2
    def entities(self): return [3,13]
    def named(self): return ''
    def isGlobal(self): return False

class InspectionTests(unittest.TestCase):
    def test_bad_property_does_not_drop_node(self):
        r=Reader(3); node=r.node(Props(),'physics/f1')
        self.assertEqual(node['properties']['good'],'550[nm]')
        self.assertIn('read_error',node['properties']['bad'])
        self.assertTrue(r.errors)
    def test_limit_reports_omitted_tags(self):
        r=Reader(0); result=r.collection(Parent(),'feature','geometry/features',1)
        self.assertEqual(result['tags'],['f1']); self.assertTrue(result['truncated'])
    def test_object_selection_uses_object_names(self):
        r=Reader(3); self.assertEqual(r.selection(ObjectSelection(),'input')['objects'],['sq1','c1'])
        self.assertFalse(r.errors)
    def test_boundary_ids_preserved(self):
        r=Reader(3); self.assertEqual(r.selection(EntitySelection(),'boundary')['entities'],[3,13])
    def test_invalid_scope_rejected_before_model_access(self):
        self.assertFalse(inspect_model(None,['typo'])['success'])
        self.assertFalse(inspect_model(None,max_depth=31)['success'])
    def test_nonfinite_serializable(self):
        self.assertEqual(native(float('inf')),'inf')

if __name__=='__main__': unittest.main()

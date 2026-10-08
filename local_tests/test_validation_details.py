import copy,unittest
from unittest.mock import patch
from src.tools.validation_details import compare_bindings,references,measure_entities
from src.tools.audit import assessment,compare

class ValidationTests(unittest.TestCase):
    def state(self):
        return {'bindings':{'physics/port':{'geometry':'geom','dimension':2,'entities':[3]}},
                'entity_fingerprints':{'geom':{'2:3':{'bbox':[0.,1.,0.,1.],'measure':1.,'adjacent_lower_ids':[1,2]}}}}
    def test_same_id_same_bbox_changed_area_detected(self):
        old=self.state();new=copy.deepcopy(old);new['entity_fingerprints']['geom']['2:3']['measure']=0.8
        self.assertEqual(compare_bindings(old,new)[0]['status'],'same_ids_geometry_changed')
    def test_missing_measurement_is_not_unchanged(self):
        old=self.state();new=copy.deepcopy(old);new['entity_fingerprints']={}
        self.assertEqual(compare_bindings(old,new)[0]['status'],'geometry_identity_unchecked')
    def test_numeric_roundoff_not_reported_as_geometry_change(self):
        old=self.state();new=copy.deepcopy(old);new['entity_fingerprints']['geom']['2:3']['measure']+=1e-12
        self.assertEqual(compare_bindings(old,new),[])
    def test_broken_study_and_dataset_cycle(self):
        data={'meshes':{},'solutions':{'s':{'study':'missing'}}};issues=[]
        allnodes=[{'path':'results/datasets/a','properties':{'data':'b'}},{'path':'results/datasets/b','properties':{'data':'a'}}]
        references(data,allnodes,issues)
        self.assertIn('missing_reference',[i['kind'] for i in issues]);self.assertIn('dataset_reference_cycle',[i['kind'] for i in issues])
    def test_parent_dataset_reference_is_not_missing(self):
        issues=[];references({'meshes':{},'solutions':{}},[{'path':'results/plotgroups/a/features/x','properties':{'data':'parent'}}],issues)
        self.assertEqual(issues,[])
    def test_incomplete_never_passes(self):
        d={'issues':[{'kind':'entity_fingerprint_limit','severity':'unknown'}],'meshes':{},'truncated_paths':[]}
        result=assessment(d);self.assertFalse(result['complete']);self.assertFalse(result['checks_passed']);self.assertEqual(result['verdict'],'incomplete')
    def test_measurement_selection_restored_after_failure(self):
        class Selection:
            dimension=2;ids=[4,5]
            def dim(self):return self.dimension
            def entities(self):return self.ids[:]
            def named(self):return ''
            def geom(self,dim):self.dimension=dim
            def set(self,ids):self.ids=list(ids)
            def clear(self):self.ids=[]
        sel=Selection()
        class Measure:
            def selection(self):return sel
            def getBoundingBox(self):raise RuntimeError('measurement failed')
        class Geometry:
            def measureFinal(self):return Measure()
        with patch('src.tools.validation_details.cast',side_effect=lambda x:x):
            with self.assertRaises(RuntimeError):measure_entities(Geometry(),{(3,1)})
        self.assertEqual(sel.dim(),2);self.assertEqual(sel.entities(),[4,5])

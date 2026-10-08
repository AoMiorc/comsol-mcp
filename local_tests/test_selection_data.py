import unittest,json
from src.tools.paged_results import page,data_path
from src.tools.audit import compare

class SelectionDataTests(unittest.TestCase):
    def test_complex_page_boundary_and_end(self):
        data={'created_at':'now','results':[{'outer':2,'encoding':'complex','shape':[2,2],'real':[[1,2],[3,4]],'imag':[[5,6],[7,8]]}]}
        result=page(data,0,1,2)
        self.assertEqual(result['real'],[2,3]);self.assertEqual(result['imag'],[6,7]);self.assertTrue(result['has_more'])
        self.assertEqual(result['shape'],[2,2]);self.assertEqual(page(data,0,4,2)['real'],[])
        with self.assertRaises(ValueError):page(data,0,5,2)
        with self.assertRaises(ValueError):page(data,0,0,1001)

    def test_scalar_and_nonfinite_page(self):
        data={'created_at':'now','results':[{'outer':None,'encoding':'real','shape':[],'value':'nan'}]}
        result=page(data,0,0,1);self.assertEqual(result['value'],['nan']);self.assertFalse(result['has_more'])
        json.dumps(result,allow_nan=False)

    def test_tokens_cannot_escape_data_folder(self):
        with self.assertRaises(ValueError):data_path('../arbitrary')

    def test_change_diagnostics_distinguish_geometry_and_physics(self):
        before={'signatures':{'components/comp1/physics/emw':'a'},'parameters':{},'geometry':{}}
        same=compare(before,before);self.assertFalse(same['solution_may_be_stale'])
        after={**before,'signatures':{'components/comp1/physics/emw':'b'}}
        result=compare(before,after);self.assertTrue(result['solution_may_be_stale']);self.assertFalse(result['mesh_may_be_stale'])
        after={**before,'parameters':{'a':'1[nm]'}}
        result=compare(before,after);self.assertTrue(result['review_entity_bindings']);self.assertTrue(result['mesh_may_be_stale'])

if __name__=='__main__':unittest.main()

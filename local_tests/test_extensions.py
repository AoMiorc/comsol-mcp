import json
import unittest
from unittest.mock import patch
import numpy as np
from src.tools.evaluation import encode
from src.tools.nodes import set_properties
from src.async_handler.solver import AsyncSolver

class ExtensionTests(unittest.TestCase):
    def test_complex_modes_are_not_dropped(self):
        d=encode(np.array([1+2j,3-4j]))
        self.assertEqual(d['real'],[1.,3.]); self.assertEqual(d['imag'],[2.,-4.])
        self.assertEqual(d['shape'],[2]); json.dumps(d,allow_nan=False)

    def test_nonfinite_values_are_json_safe(self):
        d=encode(np.array([np.inf,np.nan])); json.dumps(d,allow_nan=False)
        self.assertEqual(d['value'],['inf','nan'])

    def test_partial_write_failure_restores_expressions(self):
        class Node:
            values={'a':'r','b':'t'}
            def set(self,key,value):
                if value=='reject': raise ValueError('setter rejected')
                self.values[key]=value
        n=Node()
        def info(node,key): return {'key':key,'type':'Double','value':1.,'expression':node.values[key]}
        with patch('src.tools.nodes.resolve',return_value=n),patch('src.tools.nodes.model_for'),patch('src.tools.nodes.property_info',side_effect=info),patch('src.tools.nodes.cast',side_effect=lambda x:x):
            d=set_properties('fake',{'a':'r+1','b':'reject'})
        self.assertFalse(d['success']); self.assertEqual(n.values,{'a':'r','b':'t'})
        self.assertEqual(d['rollback_errors'],{})

    def test_solver_failure_retains_traceback(self):
        class Model:
            def name(self): return 'test'
            def solve(self,study): raise ValueError('intentional failure')
        solver=AsyncSolver(); self.assertTrue(solver.start_solve(Model()))
        self.assertTrue(solver.wait(5)); d=solver.get_progress()
        self.assertEqual(d['status'],'failed'); self.assertIn('intentional failure',d['traceback'])
        self.assertEqual(d['progress'],0.)

if __name__=='__main__': unittest.main()

import unittest
from unittest.mock import patch
from src.tools.equations import edit,definitions

class Info:
    def __init__(self):self.values={0:['old0'],1:None,2:['old2']};self.reject=None;self.failed=False
    def getInfoTable(self,table):
        return [[None,'epsilon',str(i),'1','desc','domain','',''+str(i)] for i in range(3)] if table=='Expression' else []
    def getStringArray(self,name,i):return self.values[i]
    def removeLock(self,name):self.values={i:None for i in self.values}
    def set(self,name,i,value):
        self.values[i]=value
        if i==self.reject and not self.failed:self.failed=True;raise RuntimeError('failure after partial setter mutation')

class EquationTransactions(unittest.TestCase):
    def setUp(self):self.cast=patch('src.tools.equations.cast',side_effect=lambda x:x);self.cast.start();self.addCleanup(self.cast.stop)
    def test_single_write_preserves_siblings(self):
        f=Info();d=edit(f,'epsilon',{1:['new1']});self.assertTrue(d['success']);self.assertEqual(f.values,{0:['old0'],1:['new1'],2:['old2']})
    def test_partial_batch_restores_preexisting_and_absent_overrides(self):
        f=Info();before=f.values.copy();f.reject=1;d=edit(f,'epsilon',{0:['new0'],1:['new1']})
        self.assertFalse(d['success']);self.assertTrue(d['rollback_verified']);self.assertEqual(f.values,before)
    def test_reset_one_keeps_other_locks(self):
        f=Info();d=edit(f,'epsilon',{0:None});self.assertTrue(d['success']);self.assertEqual(f.values,{0:None,1:None,2:['old2']})
    def test_invalid_occurrence_rejected_before_write(self):
        f=Info();before=f.values.copy()
        with self.assertRaises(ValueError):edit(f,'epsilon',{3:['bad']})
        self.assertEqual(f.values,before)
    def test_identifier_must_be_identifier_column(self):
        with self.assertRaises(ValueError):definitions(Info(),'desc')
    def test_rollback_failure_explicit(self):
        f=Info();f.reject=1
        def fail_reset(name):raise RuntimeError('restore failed')
        f.removeLock=fail_reset;d=edit(f,'epsilon',{1:['new']})
        self.assertFalse(d['rollback_verified']);self.assertIn('restore failed',d['rollback_error']['error'])

import json,tempfile,time,unittest
from pathlib import Path
from src.tools.solver_jobs import status
from src.tools.errors import history

class WorkerDiagnostics(unittest.TestCase):
    def test_abrupt_exit_recorded_once_and_correlated(self):
        class Process:
            pid=123
            def poll(self):return 7
        with tempfile.TemporaryDirectory() as directory:
            job={'id':'test-abrupt','folder':Path(directory),'process':Process(),'started_at':time.time(),'call_id':'start-call'}
            a=status(job);b=status(job)
            self.assertEqual(a['status'],'failed');self.assertEqual(a['diagnostic']['error_id'],b['diagnostic']['error_id'])
            self.assertEqual(a['diagnostic']['call_id'],'start-call');self.assertEqual(len(history(job_id='test-abrupt')),1)
    def test_cancel_does_not_become_error(self):
        class Process:
            pid=124
            def poll(self):return 1
        with tempfile.TemporaryDirectory() as directory:
            job={'id':'test-cancel','folder':Path(directory),'process':Process(),'started_at':time.time(),'cancelled':True}
            self.assertEqual(status(job)['status'],'cancelled');self.assertEqual(history(job_id='test-cancel'),[])

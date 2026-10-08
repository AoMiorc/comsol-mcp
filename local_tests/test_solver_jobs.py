import unittest,tempfile,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
from src.tools.solver_jobs import JOBS,cancel_job,status,parse_progress
import threading

class SolverJobsTests(unittest.TestCase):
    def test_parse_actual_phase_not_fake_overall(self):
        d=parse_progress('当前进度: 80 % - 求解\nCurrent progress: 2 % - Mesh\n')
        self.assertEqual(d['percent'],2);self.assertEqual(d['phase'],'Mesh')
        self.assertIsNone(parse_progress('Starting JVM')['percent'])

    def test_empty_phase_does_not_consume_next_line(self):
        d=parse_progress('Iter ErrEst Nconv\n   1 1.1e-06 6\n当前进度: 100 % - \nMemory: 1116/1708\n')
        self.assertIsNone(d['phase']);self.assertEqual(d['eigen_iteration']['converged_modes'],6)
        self.assertAlmostEqual(d['eigen_iteration']['error_estimate'],1.1e-6)

    def test_kill_confirms_real_process_exit_and_repeat_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-c','import time; time.sleep(60)'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            token=uuid4().hex
            JOBS[token]={'id':token,'folder':Path(tmp),'process':p,'started_at':time.time(),'lock':threading.Lock()}
            try:
                self.assertTrue(status(JOBS[token])['process_alive'])
                r=cancel_job(token);self.assertFalse(r['process_alive']);self.assertIsNotNone(p.poll())
                self.assertEqual(r['status'],'cancelled');self.assertFalse(r['result_valid'])
                self.assertFalse(cancel_job(token)['cancel_requested'])
            finally:
                if p.poll() is None:p.kill();p.wait()
                JOBS.pop(token)

    def test_already_completed_not_relabelled_cancelled(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'result.mph').write_bytes(b'test');(folder/'worker-state.json').write_text(json.dumps({'status':'completed'}))
            p=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-c','pass'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));p.wait()
            token=uuid4().hex;JOBS[token]={'id':token,'folder':folder,'process':p,'started_at':time.time(),'lock':threading.Lock()}
            try:
                r=cancel_job(token);self.assertEqual(r['status'],'completed');self.assertTrue(r['result_valid']);self.assertFalse(r['cancel_requested'])
            finally:JOBS.pop(token)

if __name__=='__main__':unittest.main()

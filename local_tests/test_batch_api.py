"""Pure-Python contract tests: no COMSOL license or JVM required."""
import copy,json,tempfile,unittest,subprocess,sys,threading,time
from pathlib import Path
from unittest.mock import patch
from comsol_batch import validate_case,validate_manifest,run_batch,cancel_batch,collect_results
from comsol_batch.api import write_json,valid_result
from comsol_batch.spec import fingerprint

def example():
    return {'case_id':'test','geometry':{'rows':2,'cols':2,'encoding':[[0,1],[1,0]]},'tuning':{'values':[0,10]}}

class BatchContractTests(unittest.TestCase):
    def test_external_encoding_is_resolved_before_hashing(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);write_json(root/'code.json',[[0,1],[1,0]])
            v=example();v['geometry'].pop('encoding');v['geometry']['encoding_file']='code.json'
            write_json(root/'case.json',v)
            self.assertEqual(validate_case(root/'case.json'),validate_case(example()))

    def test_bad_encoding_and_invalid_geometry_fail_before_work(self):
        for edit in [lambda s:s['geometry'].update(encoding=[[0,2],[1,0]]),
                     lambda s:s['geometry'].update(encoding=[[0,True],[1,0]]),
                     lambda s:s['geometry'].update(pillar_width_nm=160),
                     lambda s:s.update(tuning={'values':[-100]}),
                     lambda s:s.update(case_id='../escape'),
                     lambda s:s.update(stduy={})]:
            with self.subTest(edit=edit):
                s=example();edit(s)
                with self.assertRaises(ValueError):validate_case(s)

    def test_duplicate_ids_and_tuning_rejected(self):
        with self.assertRaises(ValueError):validate_manifest({'cases':[example(),example()]})
        s=example();s['tuning']['values']=[0,0]
        with self.assertRaises(ValueError):validate_case(s)

    def test_resume_uses_hash_and_requires_saved_solution(self):
        s=validate_case(example())
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);folder=root/'test'/'point_000';folder.mkdir(parents=True)
            r={'status':'completed','spec_hash':fingerprint(s),'height_offset_nm':0,'modes':[{'solution_index':1,'frequency_real_Hz':3e14,'frequency_imag_Hz':1e10}],'solution_file':str(folder/'solution.mph')}
            write_json(folder/'result.json',r)
            self.assertFalse(valid_result(folder,s,0))
            (folder/'solution.mph').write_bytes(b'fixture')
            self.assertTrue(valid_result(folder,s,0))
            altered=copy.deepcopy(s);altered['study']['number_of_modes']=10
            self.assertFalse(valid_result(folder,altered,0))
            r['modes'][0]['frequency_real_Hz']=float('nan')
            (folder/'result.json').write_text(json.dumps(r),encoding='utf8')
            self.assertFalse(valid_result(folder,s,0))

    def test_completed_batch_resumes_without_spawning(self):
        s=validate_case(example())
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for i,v in enumerate(s['tuning']['values']):
                folder=root/'test'/f'point_{i:03d}';folder.mkdir(parents=True)
                (folder/'solution.mph').write_bytes(b'fixture')
                write_json(folder/'result.json',{'status':'completed','spec_hash':fingerprint(s),'case_id':'test','height_offset_nm':v,
                  'solution_file':str(folder/'solution.mph'),'modes':[{'solution_index':1,'frequency_real_Hz':3e14,'frequency_imag_Hz':1e10}]})
            with patch('comsol_batch.api.subprocess.Popen',side_effect=AssertionError('must not spawn')):
                result=run_batch({'cases':[s]},root)
            self.assertEqual(result['status'],'completed');self.assertEqual(result['completed_points'],2)
            self.assertFalse((root/'runner.lock').exists())
            self.assertFalse(collect_results(root)['gap_extracted'])

    def test_manifest_mismatch_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            s=validate_case(example());root=Path(t);write_json(root/'manifest.json',{'cases':[s]})
            changed=copy.deepcopy(s);changed['geometry']['pitch_nm']=170
            with self.assertRaises(ValueError):run_batch({'cases':[changed]},root)
            self.assertEqual(read(root/'manifest.json'),{'cases':[s]})

    def test_cancel_is_request_until_worker_exits(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);write_json(root/'manifest.json',{'cases':[validate_case(example())]})
            self.assertFalse(cancel_batch(root)['cancel_requested'])
            (root/'runner.lock').write_text('owned runner')
            result=cancel_batch(root)
            self.assertTrue(result['cancel_requested']);self.assertNotEqual(result['status'],'cancelled')

    def test_timeout_kills_the_owned_process(self):
        original=subprocess.Popen;owned=[]
        def launch(*args,**kwargs):
            process=original([getattr(sys,'_base_executable',sys.executable),'-c','import time;time.sleep(30)'],**kwargs)
            owned.append(process);return process
        with tempfile.TemporaryDirectory() as t:
            s=example();s['runtime']={'timeout_seconds':0.1}
            with patch('comsol_batch.api.subprocess.Popen',side_effect=launch):result=run_batch({'cases':[s]},t)
            self.assertEqual(result['status'],'failed');self.assertIsNotNone(owned[0].poll())
            self.assertEqual(result['cases'][0]['status'],'timed_out')

    def test_cancel_confirms_process_exit_and_stops_queue(self):
        original=subprocess.Popen;owned=[]
        def launch(*args,**kwargs):
            process=original([getattr(sys,'_base_executable',sys.executable),'-c','import time;time.sleep(30)'],**kwargs)
            owned.append(process);return process
        with tempfile.TemporaryDirectory() as t:
            def request_cancel():
                while not owned:time.sleep(0.01)
                cancel_batch(t)
            thread=threading.Thread(target=request_cancel);thread.start()
            with patch('comsol_batch.api.subprocess.Popen',side_effect=launch):result=run_batch({'cases':[example()]},t)
            thread.join(timeout=2)
            self.assertEqual(result['status'],'cancelled');self.assertIsNotNone(owned[0].poll())
            self.assertFalse((Path(t)/'runner.lock').exists())

    def test_mcp_adapter_registers_real_tool_schemas(self):
        import asyncio
        from mcp.server.fastmcp import FastMCP
        from src.tools.batch import register_batch_tools
        mcp=FastMCP('test');register_batch_tools(mcp)
        names={tool.name for tool in asyncio.run(mcp.list_tools())}
        self.assertEqual(names,{'batch_validate','batch_start','batch_status','batch_cancel','batch_collect'})

def read(path):return json.loads(path.read_text(encoding='utf8'))

if __name__=='__main__':unittest.main()

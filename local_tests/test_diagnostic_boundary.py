import unittest
from src.tools.diagnostics import DiagnosticToolManager
from src.tools.errors import error_record,history
from mcp.server.fastmcp.exceptions import ToolError

class DiagnosticBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_failure_recorded(self):
        manager=DiagnosticToolManager()
        def check()->dict:return {'success':False,'error':'missing model'}
        manager.add_tool(check);r=await manager.call_tool('check',{})
        self.assertEqual(history(call_id=r['call_id'])[-1]['error'],'missing model');self.assertIsNone(r['traceback'])
    async def test_validation_and_unknown_tool_keep_protocol_failure(self):
        manager=DiagnosticToolManager()
        def check(n:int)->dict:return {'success':True}
        manager.add_tool(check)
        for name,args in [('check',{'n':'bad'}),('absent',{})]:
            with self.assertRaises(ToolError):await manager.call_tool(name,args)
            self.assertEqual(history(limit=1)[0]['operation'],name)
    async def test_recovered_warning_attached_to_success(self):
        manager=DiagnosticToolManager()
        def fallback()->dict:
            try:raise ValueError('unsupported optional getter')
            except ValueError as e:error_record(e,'fallback',severity='warning')
            return {'success':True}
        manager.add_tool(fallback);r=await manager.call_tool('fallback',{})
        self.assertTrue(r['success']);self.assertEqual(r['diagnostics'][0]['severity'],'warning')
    async def test_converted_wire_result_retains_diagnostics(self):
        manager=DiagnosticToolManager()
        def check()->dict:return {'success':False,'error':'no model'}
        manager.add_tool(check);r=await manager.call_tool('check',{},convert_result=True)
        self.assertIn('error_id',str(r))

import unittest
from unittest.mock import patch
from mcp.server.fastmcp import FastMCP
from src.tools.parameters import register_parameter_tools
from src.tools.nodes import ERRORS as extended_errors
from src.tools.errors import ERRORS

class ErrorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_exception_reaches_shared_history(self):
        class BadModel:
            def parameter(self,*args,**kwargs):
                raise ValueError('parameter access failed')
        mcp=FastMCP('test'); register_parameter_tools(mcp)
        with patch('src.tools.parameters.session_manager.get_model',return_value=BadModel()):
            result=await mcp._tool_manager.call_tool('param_get',{'name':'missing'})
        self.assertFalse(result['success'])
        self.assertIn('ValueError: parameter access failed',result['traceback'])
        self.assertEqual(result['operation'],'param_get')
        self.assertIs(ERRORS,extended_errors)
        self.assertEqual(ERRORS[-1]['causes'],['parameter access failed'])

    async def test_legacy_success_does_not_overwrite_last_error(self):
        class GoodModel:
            def parameter(self,*args,**kwargs): return '1[m]'
            def description(self,*args): return 'length'
        mcp=FastMCP('test');register_parameter_tools(mcp);before=list(ERRORS)
        with patch('src.tools.parameters.session_manager.get_model',return_value=GoodModel()):
            result=await mcp._tool_manager.call_tool('param_get',{'name':'a'})
        self.assertTrue(result['success']);self.assertEqual(ERRORS,before)

"""FastMCP tool-call diagnostics, including preflight and argument validation failures."""
import json
from uuid import uuid4
from mcp.server.fastmcp.tools.tool_manager import ToolManager
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import UrlElicitationRequiredError
from .errors import CALL_ID,CALL_RECORDS,error_record,failure_record


class DiagnosticToolManager(ToolManager):
    async def call_tool(self,name,arguments,context=None,convert_result=False):
        token=CALL_ID.set(uuid4().hex);records=[];record_token=CALL_RECORDS.set(records)
        try:
            result=await super().call_tool(name,arguments,context,convert_result=False)
            if name not in ('get_last_error','get_error_history') and isinstance(result,dict):
                if result.get('success') is False and not result.get('error_id'):
                    record=next((r for r in reversed(records) if r['severity']=='error'),None)
                    if record is None:record=failure_record(result.get('error',result.get('message','Tool returned success=false')),name)
                    result={**record,**result}
                if records:result={**result,'call_id':CALL_ID.get(),'diagnostics':[{'error_id':r['error_id'],'severity':r['severity'],'operation':r['operation']} for r in records]}
            return self.get_tool(name).fn_metadata.convert_result(result) if convert_result else result
        except UrlElicitationRequiredError:
            raise
        except Exception as exc:
            record=error_record(exc,name,source='tool_dispatch_or_validation')
            raise ToolError(json.dumps(record,ensure_ascii=False)) from exc
        finally:
            CALL_RECORDS.reset(record_token);CALL_ID.reset(token)

"""Thin MCP transport adapter; high-level implementation is reusable in Python."""
from pathlib import Path
from comsol_batch import validate_manifest,start_batch,get_batch_status,cancel_batch,collect_results

def register_batch_tools(mcp):
    @mcp.tool()
    def batch_validate(manifest:dict)->dict:
        """Validate encoded-height eigenmode cases without starting COMSOL. Inline encoding matrices only."""
        return validate_manifest(manifest)
    @mcp.tool()
    def batch_start(manifest:dict,run_dir:str,action:str='solve')->dict:
        """Start an isolated sequential encoded-height batch. action=build or solve. Sources remain untouched."""
        return start_batch(manifest,run_dir,action)
    @mcp.tool()
    def batch_status(run_dir:str)->dict:
        """Read durable batch and per-case states. Only terminal worker exit confirms cancellation."""
        return get_batch_status(run_dir)
    @mcp.tool()
    def batch_cancel(run_dir:str)->dict:
        """Request cancellation of this batch's owned worker and stop the queue. Poll status for confirmation."""
        return cancel_batch(run_dir)
    @mcp.tool()
    def batch_collect(run_dir:str)->dict:
        """Collect completed mode candidates. Does not infer mode identities or coupling gaps."""
        return collect_results(run_dir)

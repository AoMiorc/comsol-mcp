"""COMSOL MCP Server - Main entry point."""

import logging
import os
from mcp.server.fastmcp import FastMCP

from .tools.session import register_session_tools, session_manager
from .tools.model import register_model_tools
from .tools.inspection import register_inspection_tools
from .tools.nodes import register_node_tools
from .tools.lifecycle import register_lifecycle_tools
from .tools.evaluation import register_evaluation_tools
from .tools.equations import register_equation_tools
from .tools.output import register_output_tools
from .tools.selection_edit import register_selection_edit_tools
from .tools.paged_results import register_paged_results_tools
from .tools.audit import register_audit_tools
from .tools.interpolation import register_interpolation_tools
from .tools.solver_jobs import register_solver_job_tools
from .tools.parameters import register_parameter_tools
from .tools.geometry import register_geometry_tools
from .tools.physics import register_physics_tools
from .tools.electrochemistry import register_electrochemistry_tools
from .tools.mesh import register_mesh_tools
from .tools.study import register_study_tools
from .tools.results import register_results_tools
from .resources.model_resources import register_model_resources
from .knowledge.embedded import register_knowledge_tools

logging.basicConfig(level=logging.INFO)
# MPh logs at INFO level while the JVM starts, which deadlocks with JPype (reproduced on Windows + COMSOL 6.3)
logging.getLogger('mph').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

from .tools.diagnostics import DiagnosticToolManager

mcp = FastMCP("COMSOL MCP")
mcp._tool_manager = DiagnosticToolManager()

# Keep transport checks enabled; allow only loopback origins and the local DeepSeek++ extension.
from mcp.server.transport_security import TransportSecuritySettings
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
    allowed_origins=[
        "http://127.0.0.1", "http://127.0.0.1:*",
        "http://localhost", "http://localhost:*",
        "http://[::1]", "http://[::1]:*",
        "chrome-extension://kdmpkkahkhdmdhfkdihkopikgcocbpbf",
    ],
)



def register_all_tools() -> None:
    """Register all MCP tools."""
    register_session_tools(mcp)
    register_model_tools(mcp)
    register_inspection_tools(mcp)
    register_node_tools(mcp)
    register_lifecycle_tools(mcp)
    register_evaluation_tools(mcp)
    register_equation_tools(mcp)
    register_output_tools(mcp)
    register_selection_edit_tools(mcp)
    register_paged_results_tools(mcp)
    register_audit_tools(mcp)
    register_interpolation_tools(mcp)
    register_solver_job_tools(mcp)
    register_parameter_tools(mcp)
    register_geometry_tools(mcp)
    register_physics_tools(mcp)
    register_electrochemistry_tools(mcp)
    register_mesh_tools(mcp)
    register_study_tools(mcp)
    register_results_tools(mcp)
    register_knowledge_tools(mcp)
    logger.info("Registered all tools")


def register_all_resources() -> None:
    """Register all MCP resources."""
    register_model_resources(mcp)
    logger.info("Registered all resources")


def main() -> None:
    """Run the MCP server."""
    logger.info("Starting COMSOL MCP Server...")
    
    register_all_tools()
    register_all_resources()
    
    transport = os.environ.get("COMSOL_MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "stdio":
        # The stdio transport immediately spawns a thread blocked on stdin (fd 0), and
        # JPype's startJVM deadlocks forever while fd 0 is read by another thread, so the
        # JVM must be started before mcp.run() (reproduced on Windows + COMSOL 6.3).
        logger.info(f"COMSOL pre-start: {session_manager.start()}")
    else:
        mcp.settings.host = os.environ.get("COMSOL_MCP_HOST", "127.0.0.1")
        if mcp.settings.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("COMSOL MCP HTTP must bind to a loopback address")
        mcp.settings.port = int(os.environ.get("COMSOL_MCP_PORT", "8765"))
        logger.info(
            f"HTTP transport '{transport}' on {mcp.settings.host}:{mcp.settings.port}"
            " (COMSOL starts lazily on first tool call)"
        )

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()

"""
Jenkins MCP Tools
=================

Connects to the Jenkins MCP server for pipeline monitoring tools.

Architecture:
    JenkinsAgent
        └── McpToolset (jenkins-mcp-server)
            ├── jenkins_get_pipelines
            ├── jenkins_get_job_info
            ├── jenkins_get_build_info
            ├── jenkins_get_test_report
            ├── jenkins_get_golden_regression
            └── jenkins_get_golden_regression_tfa
"""

import logging
import os
import sys
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Load .env from project root to ensure environment variables are available
# This is critical for MCP server subprocesses which need CURRENT_RELEASE
try:
    from dotenv import load_dotenv

    _current_dir = os.path.dirname(os.path.abspath(__file__))
    for _levels in [
        os.path.join(_current_dir, "..", "..", ".."),  # local dev
        os.path.join(_current_dir, "..", ".."),  # Docker
    ]:
        _env_path = os.path.join(_levels, ".env")
        if os.path.exists(_env_path):
            load_dotenv(_env_path)
            logger.debug("Loaded .env from %s", _env_path)
            break
except ImportError:
    pass  # dotenv not installed


# MCP_SERVERS_DIR is set by the Dockerfile (ENV MCP_SERVERS_DIR=/app/mcp_servers).
# Local dev falls back to the relative path from this file → project root.
MCP_SERVERS_PATH = os.environ.get(
    "MCP_SERVERS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp_servers"),
)

# Try to import MCP support (same imports as release_readiness_agent)
try:
    from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
    from mcp import StdioServerParameters

    HAS_MCP = True
except ImportError as e:
    HAS_MCP = False
    McpToolset = None
    StdioConnectionParams = None
    StdioServerParameters = None
    logger.warning("MCP support not available: %s", e)


def check_mcp_available() -> bool:
    """Check if MCP support is available."""
    return HAS_MCP


def _get_uv_path() -> Optional[str]:
    """
    Find uv executable if installed.

    Note: We prefer using Python directly if mcp is already installed,
    as uv can have permission issues with cache directories.
    """
    import shutil

    # Check if mcp is available in current Python environment
    try:
        import mcp

        # mcp is installed, use Python directly
        return None
    except ImportError:
        # mcp not in current env, try uv
        return shutil.which("uv")


async def connect_to_jenkins_server() -> Tuple[Any, Optional[Callable]]:
    """
    Connect to Jenkins MCP server.

    Returns:
        Tuple of (McpToolset, cleanup_function)
    """
    if not HAS_MCP:
        logger.error("MCP support not available")
        return None, None

    # Get server path
    server_dir = "jenkins-mcp-server"
    server_path = os.path.join(MCP_SERVERS_PATH, server_dir, "server.py")

    if not os.path.exists(server_path):
        logger.error("Jenkins MCP server not found: %s", server_path)
        return None, None

    try:
        logger.info("Connecting to Jenkins MCP server: %s", server_path)

        # Use uv if available, otherwise use Python interpreter
        uv_path = _get_uv_path()

        if uv_path:
            logger.info("Using uv to run jenkins server")
            command = uv_path
            args = ["run", server_path]
        else:
            logger.info("Using Python interpreter for jenkins server")
            command = sys.executable
            args = [server_path]

        # Pass environment variables so MCP server can reach backend API
        env = os.environ.copy()

        # Ensure required environment variables are set for MCP servers
        api_base = os.environ.get("BACKEND_URL", "http://localhost:8000")
        env["BACKEND_URL"] = api_base

        # CRITICAL: MCP servers require CURRENT_RELEASE - pass it explicitly
        current_release = os.environ.get("CURRENT_RELEASE")
        if current_release:
            env["CURRENT_RELEASE"] = current_release
            logger.info(
                "[MCP] Starting jenkins server with CURRENT_RELEASE=%s, BACKEND_URL=%s", current_release, api_base
            )
        else:
            logger.error("[MCP] CURRENT_RELEASE not set! Jenkins MCP server will fail.")
            logger.error("[MCP] Set CURRENT_RELEASE in your .env file (e.g., CURRENT_RELEASE=R134)")
            raise EnvironmentError(
                "CURRENT_RELEASE environment variable is required for Jenkins MCP server. "
                "Set it in your .env file (e.g., CURRENT_RELEASE=R134)"
            )

        # Create server parameters (from mcp package)
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        # Create connection params (from google.adk)
        connection_params = StdioConnectionParams(
            server_params=server_params,
            timeout=30.0,  # 30 second timeout for MCP connection (faster startup)
        )

        # Create McpToolset - it connects lazily when tools are accessed
        toolset = McpToolset(connection_params=connection_params)

        # Test connection by getting tools
        tools = await toolset.get_tools()

        logger.info("Connected to jenkins: %s tools available", len(tools))
        for tool in tools[:3]:
            logger.debug("  - %s", tool.name)

        # Return toolset and cleanup function
        async def cleanup():
            await toolset.close()

        return toolset, cleanup

    except BrokenPipeError:
        logger.error("Jenkins MCP server crashed on startup.")
        logger.error("Common causes:")
        logger.error("  1. CURRENT_RELEASE not set in .env file")
        logger.error("  2. mcp package not installed: pip install mcp>=1.0.0")
        logger.error("  3. Backend server not running at %s", os.environ.get("BACKEND_URL", "http://localhost:8000"))
        logger.error("Check: CURRENT_RELEASE=%s", os.environ.get("CURRENT_RELEASE", "NOT SET"))
        return None, None
    except EnvironmentError as e:
        logger.error("Environment configuration error for Jenkins MCP server: %s", e)
        return None, None
    except Exception as e:
        logger.error("Failed to connect to Jenkins MCP server: %s: %s", type(e).__name__, e)
        import traceback

        traceback.print_exc()
        return None, None


async def get_jenkins_mcp_tools() -> Tuple[List[Any], Callable]:
    """
    Get Jenkins MCP toolset.

    Returns:
        Tuple of (list of McpToolset, cleanup function)
    """
    if not HAS_MCP:
        logger.warning("MCP not available - returning empty toolsets")

        async def noop_cleanup():
            pass

        return [], noop_cleanup

    toolset, cleanup = await connect_to_jenkins_server()

    if toolset is None:
        logger.warning("Failed to connect to Jenkins MCP server")

        async def noop_cleanup():
            pass

        return [], noop_cleanup

    # Combined cleanup function
    async def combined_cleanup():
        if cleanup:
            try:
                await cleanup()
            except Exception as e:
                logger.warning("Cleanup error: %s", e)

    return [toolset], combined_cleanup

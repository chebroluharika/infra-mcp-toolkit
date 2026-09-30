"""
MCP Tools Integration for Release Readiness Agent
==================================================

Provides MCP (Model Context Protocol) toolset integration for ADK agents.
MCP allows agents to connect to external tool servers (JIRA, Calendar, Jenkins, TestRail).

MCP Servers Available:
- jira-mcp-server: Bug tracking, release status, escalations
- release-calendar-mcp-server: Release dates, milestones
- jenkins-mcp-server: CI/CD pipeline status
- testrail-mcp-server: Test execution status

Usage:
    from release_readiness_agent.tools.mcp_tools import get_mcp_tools

    # Get all MCP tools for the agent
    tools, cleanup = await get_mcp_tools()

    agent = LlmAgent(tools=tools, ...)

    # When done (optional - cleans up MCP server processes)
    await cleanup()
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

# Check ADK MCP support
try:
    # Use McpToolset (non-deprecated) instead of MCPToolset
    from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
    from mcp import StdioServerParameters

    HAS_MCP = True
except ImportError as e:
    HAS_MCP = False
    McpToolset = None
    StdioConnectionParams = None
    StdioServerParameters = None
    logger.warning("ADK McpToolset not available: %s", e)


# Server configuration
MCP_SERVERS = {
    "jira": {
        "dir": "jira-mcp-server",
        "description": "JIRA bug tracking, escalations, and release readiness",
    },
    "calendar": {
        "dir": "release-calendar-mcp-server",
        "description": "Google Calendar release dates",
    },
    "jenkins": {
        "dir": "jenkins-mcp-server",
        "description": "Jenkins CI/CD pipeline status",
    },
    "testrail": {
        "dir": "testrail-mcp-server",
        "description": "TestRail test execution",
    },
    "github": {
        "dir": "github-mcp-server",
        "description": "GitHub commits before/after branch cut",
    },
}


# Public exports
__all__ = [
    "McpToolset",
    "StdioConnectionParams",
    "StdioServerParameters",
    "check_mcp_available",
    "get_mcp_server_path",
    "get_mcp_tools",
    "MCP_SERVERS_PATH",
    "MCP_SERVERS",
]


def check_mcp_available() -> bool:
    """
    Check if MCP toolset is available.

    Returns:
        True if google.adk.tools.mcp_tool is installed and importable.
    """
    return HAS_MCP


def get_mcp_server_path(server_id: str) -> Optional[str]:
    """
    Get the file path for an MCP server.

    Args:
        server_id: One of "jira", "calendar", "jenkins", "testrail"

    Returns:
        Full path to server.py, or None if not found.
    """
    if server_id not in MCP_SERVERS:
        logger.error("Unknown MCP server: {server_id}. Valid: %s", list(MCP_SERVERS.keys()))
        return None

    server_dir = MCP_SERVERS[server_id]["dir"]
    server_path = os.path.join(MCP_SERVERS_PATH, server_dir, "server.py")

    if not os.path.exists(server_path):
        logger.error("MCP server not found: %s", server_path)
        return None

    return server_path


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


async def connect_to_mcp_server(server_id: str) -> Tuple[Any, Optional[Callable]]:
    """
    Connect to a single MCP server and return the toolset.

    Args:
        server_id: Server identifier (jira, calendar, jenkins, testrail)

    Returns:
        Tuple of (MCPToolset instance, cleanup_function)
    """
    if not HAS_MCP:
        logger.warning("MCP not available, skipping %s", server_id)
        return None, None

    server_path = get_mcp_server_path(server_id)
    if not server_path:
        return None, None

    try:
        logger.info("Connecting to MCP server: {server_id} (%s)", server_path)

        # Use uv if available (auto-installs dependencies from script header)
        # Otherwise fall back to current Python interpreter
        uv_path = _get_uv_path()

        if uv_path:
            logger.info("Using uv to run %s server", server_id)
            command = uv_path
            args = ["run", server_path]
        else:
            logger.info("Using Python interpreter for %s server", server_id)
            command = sys.executable
            args = [server_path]

        # Create server parameters (from mcp package)
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
                "[MCP] Starting %s server with CURRENT_RELEASE=%s, BACKEND_URL=%s", server_id, current_release, api_base
            )
        else:
            logger.error("[MCP] CURRENT_RELEASE not set! MCP server %s will fail.", server_id)
            logger.error("[MCP] Set CURRENT_RELEASE in your .env file (e.g., CURRENT_RELEASE=R134)")
            raise EnvironmentError(
                f"CURRENT_RELEASE environment variable is required for MCP server {server_id}. "
                "Set it in your .env file (e.g., CURRENT_RELEASE=R134)"
            )

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

        logger.info("Connected to {server_id}: %s tools available", len(tools))
        for tool in tools[:3]:
            logger.debug("  - %s", tool.name)

        # Return toolset and cleanup function
        async def cleanup():
            await toolset.close()

        return toolset, cleanup

    except BrokenPipeError:
        logger.error("MCP server %s crashed on startup.", server_id)
        logger.error("Common causes:")
        logger.error("  1. CURRENT_RELEASE not set in .env file")
        logger.error("  2. mcp package not installed: pip install mcp>=1.0.0")
        logger.error("  3. Backend server not running at %s", os.environ.get("BACKEND_URL", "http://localhost:8000"))
        logger.error("Check: CURRENT_RELEASE=%s", os.environ.get("CURRENT_RELEASE", "NOT SET"))
        return None, None
    except EnvironmentError as e:
        logger.error("Environment configuration error for MCP server %s: %s", server_id, e)
        return None, None
    except Exception as e:
        logger.error("Failed to connect to MCP server %s: %s: %s", server_id, type(e).__name__, e)
        import traceback

        traceback.print_exc()
        return None, None


async def get_mcp_tools(servers: Optional[List[str]] = None) -> Tuple[List[Any], Callable]:
    """
    Get toolsets from multiple MCP servers.

    Args:
        servers: List of server IDs to connect to.
                 Default: ["jira", "calendar", "testrail", "jenkins", "github"]

    Returns:
        Tuple of (list_of_MCPToolset_instances, cleanup_function)

    Note:
        In google-adk 1.x, agents accept toolsets directly in the tools list.
        Each MCPToolset is added as-is; the agent handles tool discovery.

    Example:
        toolsets, cleanup = await get_mcp_tools(["jira", "calendar"])
        agent = LlmAgent(tools=toolsets, ...)

        # When done
        await cleanup()
    """
    import asyncio
    import time

    if servers is None:
        servers = ["jira", "calendar", "testrail", "jenkins", "github"]

    # PERFORMANCE FIX: Connect to all MCP servers in parallel instead of sequentially
    # This reduces startup time from ~15-25s to ~3-5s (5 servers × 3-5s each → max(3-5s))
    _start = time.time()
    logger.info("[MCP] Connecting to %d servers in parallel: %s", len(servers), servers)

    # Connect to all servers concurrently
    results = await asyncio.gather(*[connect_to_mcp_server(server_id) for server_id in servers], return_exceptions=True)

    all_toolsets = []
    cleanup_funcs = []

    for i, result in enumerate(results):
        server_id = servers[i]
        if isinstance(result, Exception):
            logger.warning("[MCP] Failed to connect to %s: %s", server_id, result)
            continue

        toolset, cleanup = result
        if toolset:
            all_toolsets.append(toolset)
        if cleanup:
            cleanup_funcs.append(cleanup)

    # Combined cleanup function
    async def cleanup_all():
        for cleanup in cleanup_funcs:
            try:
                await cleanup()
            except Exception as e:
                logger.warning("Cleanup error: %s", e)

    _elapsed = round(time.time() - _start, 2)
    logger.info("[MCP] Connected to %d/%d servers in %.2fs: %s", len(all_toolsets), len(servers), _elapsed, servers)
    return all_toolsets, cleanup_all

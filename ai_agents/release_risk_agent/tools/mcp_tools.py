"""
MCP Tools Connection for Release Risk Agent
============================================

Connects to the release-risk-mcp-server via stdio subprocess.
"""

import logging
import os

logger = logging.getLogger(__name__)


def get_release_risk_mcp_config():
    """
    Get MCP toolset configuration for release-risk-mcp-server.

    Returns:
        Tuple of (MCPToolset, exit_stack) for use with LlmAgent
    """
    try:
        from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters
    except ImportError:
        logger.error("google-adk not installed. Run: pip install google-adk>=0.5.0")
        raise

    mcp_server_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "mcp_servers",
        "release-risk-mcp-server",
        "server.py",
    )

    if not os.path.exists(mcp_server_path):
        raise FileNotFoundError(f"MCP server not found: {mcp_server_path}")

    env = os.environ.copy()
    env.setdefault("API_BASE_URL", "http://localhost:8000")
    env.setdefault("CURRENT_RELEASE", os.getenv("CURRENT_RELEASE", "R136"))

    return MCPToolset(
        connection_params=StdioServerParameters(
            command="uv",
            args=["run", mcp_server_path],
            env=env,
        )
    )


async def get_release_risk_tools():
    """
    Async factory to get release risk MCP tools.

    Returns:
        Tuple of (tools_list, cleanup_function)
    """
    from contextlib import AsyncExitStack

    toolset = get_release_risk_mcp_config()
    exit_stack = AsyncExitStack()

    tools, cleanup = await toolset.get_tools_for_agent_async(exit_stack)

    logger.info("Loaded %d release risk MCP tools", len(tools))

    return tools, exit_stack.aclose

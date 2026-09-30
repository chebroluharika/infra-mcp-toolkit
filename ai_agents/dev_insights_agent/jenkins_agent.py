"""
Jenkins Data Agent (Sub-agent for Dev Insights — MCP-based)
============================================================

Specialized LlmAgent connected to the jenkins-mcp-server for fetching
CI/CD pipeline data. Used as a sub-agent of the dev_insights orchestrator.

Architecture:
    JenkinsDataAgent (LlmAgent)
        └── MCP Server: jenkins-mcp-server
            ├── jenkins_get_pipelines — all pipeline statuses
            └── jenkins_get_job_builds — build history for a specific job
"""

import logging
from typing import Any, Callable, List, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None

JENKINS_TOOLS = {
    "jenkins_get_pipelines",
    "jenkins_get_job_builds",
}

JENKINS_DATA_INSTRUCTION = """You are a Jenkins CI/CD data specialist agent. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

1. `jenkins_get_pipelines()` — List all monitored pipeline statuses (passing/failing/unstable)
2. `jenkins_get_job_builds(job_name, limit)` — Build history for a specific job (last N builds with status)

## GUIDELINES

- For "pipeline health" or "CI/CD status" → use `jenkins_get_pipelines`
- For "recent builds of job X" or build failure details → use `jenkins_get_job_builds`
- Return the tool output as-is — the orchestrator will synthesize it
"""


async def _get_filtered_tools(toolsets: List[Any], allowed: set) -> List[Any]:
    """Extract individual tools from MCP toolsets, keeping only allowed ones."""
    filtered = []
    for ts in toolsets:
        tools = await ts.get_tools()
        for tool in tools:
            if tool.name in allowed:
                filtered.append(tool)
    return filtered


async def create_jenkins_data_agent_async(
    name: str = "jenkins_data_agent",
    description: str = "Jenkins CI/CD data specialist: pipeline health and build history",
) -> Tuple["LlmAgent", Callable]:
    """
    Create the Jenkins Data Agent connected to jenkins-mcp-server.

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed")

    from release_readiness_agent.tools.mcp_tools import check_mcp_available, get_mcp_tools

    if not check_mcp_available():
        raise RuntimeError("MCP support not available")

    toolsets, cleanup = await get_mcp_tools(["jenkins"])
    if not toolsets:
        raise RuntimeError("Could not connect to jenkins-mcp-server")

    tools = await _get_filtered_tools(toolsets, JENKINS_TOOLS)
    logger.info("JenkinsDataAgent: %d tools from jenkins-mcp-server", len(tools))

    model = get_litellm_model()

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=JENKINS_DATA_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created JenkinsDataAgent (MCP-based) with %d tools", len(tools))
    return agent, cleanup

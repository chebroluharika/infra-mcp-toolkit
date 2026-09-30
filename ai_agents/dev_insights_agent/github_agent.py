"""
GitHub Data Agent (Sub-agent for Dev Insights — MCP-based)
===========================================================

Specialized LlmAgent connected to the github-mcp-server for fetching
developer-related GitHub data. Used as a sub-agent of the dev_insights
orchestrator.

Architecture:
    GitHubDataAgent (LlmAgent)
        └── MCP Server: github-mcp-server
            ├── github_get_open_prs             — all open PRs
            ├── github_get_pr_review_workload   — review load per developer
            ├── github_get_code_contributors    — repo contribution patterns
            └── github_get_pr_ticket_references — JIRA keys in PR titles/branches
"""

import logging
from typing import Any, Callable, List, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None

GITHUB_TOOLS = {
    "github_get_open_prs",
    "github_get_pr_review_workload",
    "github_get_code_contributors",
    "github_get_pr_ticket_references",
}

GITHUB_DATA_INSTRUCTION = """You are a GitHub data specialist agent. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

1. `github_get_open_prs()` — List all open PRs with author, reviewers, age, size, repo
2. `github_get_pr_review_workload()` — Review load per developer (pending reviews, authored PRs, stale reviews)
3. `github_get_code_contributors()` — Repo contribution patterns (who contributes where, concentration)
4. `github_get_pr_ticket_references()` — JIRA ticket keys found in PR titles and branches

## GUIDELINES

- For workload questions → use `github_get_pr_review_workload`
- For code ownership / bus factor → use `github_get_code_contributors`
- For cross-concern linking (PR↔JIRA) → use `github_get_pr_ticket_references`
- For a general PR listing → use `github_get_open_prs`
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


async def create_github_data_agent_async(
    name: str = "github_data_agent",
    description: str = "GitHub data specialist: PR review workload, code contributors, and ticket references",
) -> Tuple["LlmAgent", Callable]:
    """
    Create the GitHub Data Agent connected to github-mcp-server.

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed")

    from release_readiness_agent.tools.mcp_tools import check_mcp_available, get_mcp_tools

    if not check_mcp_available():
        raise RuntimeError("MCP support not available")

    toolsets, cleanup = await get_mcp_tools(["github"])
    if not toolsets:
        raise RuntimeError("Could not connect to github-mcp-server")

    tools = await _get_filtered_tools(toolsets, GITHUB_TOOLS)
    logger.info("GitHubDataAgent: %d tools from github-mcp-server", len(tools))

    model = get_litellm_model()

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=GITHUB_DATA_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created GitHubDataAgent (MCP-based) with %d tools", len(tools))
    return agent, cleanup

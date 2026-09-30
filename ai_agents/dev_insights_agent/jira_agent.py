"""
JIRA Data Agent (Sub-agent for Dev Insights — MCP-based)
=========================================================

Specialized LlmAgent connected to the jira-mcp-server for fetching
developer-related JIRA data. Used as a sub-agent of the dev_insights
orchestrator.

Architecture:
    JiraDataAgent (LlmAgent)
        └── MCP Server: jira-mcp-server
            ├── jira_search_issues       — flexible JQL search
            ├── jira_get_action_items_by_assignee — workload by person
            ├── jira_get_escalations_summary      — customer escalations
            ├── jira_get_bugs                     — bug listing with filters
            └── jira_get_issue                    — single issue details
"""

import logging
from typing import Any, Callable, List, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None

JIRA_TOOLS = {
    "jira_search_issues",
    "jira_get_action_items_by_assignee",
    "jira_get_escalations_summary",
    "jira_get_bugs",
    "jira_get_bugs_summary",
    "jira_get_issue",
    "jira_get_customer_escalations",
}

JIRA_DATA_INSTRUCTION = """You are a JIRA data specialist agent. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

1. `jira_search_issues(jql)` — **Flexible search** — construct JQL for any filtered query.
   Use this for component ownership, developer workload, and any custom query.
2. `jira_get_action_items_by_assignee(fix_version, component)` — Open items grouped by assignee
3. `jira_get_escalations_summary(release)` — Customer escalation summary (EHF/IMF)
4. `jira_get_bugs(project_key, status, priority, fix_version)` — Bug listing with filters
5. `jira_get_bugs_summary(fix_version)` — Bug counts by status and priority
6. `jira_get_issue(issue_key)` — Single issue details
7. `jira_get_customer_escalations(release_version)` — Detailed escalations with aging

## JQL CONSTRUCTION GUIDE

Build JQL from the orchestrator's request:

| Need | JQL Pattern |
|------|-------------|
| Component ownership | `project = ENG AND fixVersion = "135.0" AND component = "X" AND assignee IS NOT EMPTY` |
| All items by assignee | `project = ENG AND fixVersion = "135.0" AND assignee IS NOT EMPTY AND status NOT IN (Closed, Done)` |
| Items for one person | `project = ENG AND assignee = "John" AND status NOT IN (Closed, Done)` |
| Escalation bugs | `project = ENG AND labels = "Customer_Escalation" AND status NOT IN (Closed)` |
| Bugs by component | `project = ENG AND issuetype = Bug AND component = "YOUR_PRODUCT"` |
| High priority items | `project = ENG AND priority IN (P0, P1, Blocker) AND status NOT IN (Closed, Done)` |

## GUIDELINES

- For team-wide workload → use `jira_get_action_items_by_assignee` or `jira_search_issues`
- For component ownership → use `jira_search_issues` with component in JQL
- For escalations → use `jira_get_escalations_summary`
- For individual developer items → use `jira_search_issues` with assignee in JQL
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


async def create_jira_data_agent_async(
    name: str = "jira_data_agent",
    description: str = "JIRA data specialist: developer workload, component ownership, escalations, bug queries via JQL",
) -> Tuple["LlmAgent", Callable]:
    """
    Create the JIRA Data Agent connected to jira-mcp-server.

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed")

    from release_readiness_agent.tools.mcp_tools import check_mcp_available, get_mcp_tools

    if not check_mcp_available():
        raise RuntimeError("MCP support not available")

    toolsets, cleanup = await get_mcp_tools(["jira"])
    if not toolsets:
        raise RuntimeError("Could not connect to jira-mcp-server")

    tools = await _get_filtered_tools(toolsets, JIRA_TOOLS)
    logger.info("JiraDataAgent: %d tools from jira-mcp-server", len(tools))

    model = get_litellm_model()

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=JIRA_DATA_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created JiraDataAgent (MCP-based) with %d tools", len(tools))
    return agent, cleanup

"""
Dev Insights Agent (ADK Orchestrator — MCP-based)
===================================================

Multi-agent orchestrator using Google ADK's sub_agents pattern.
Coordinates jira_data_agent, github_data_agent, and jenkins_data_agent
— each connected to their respective MCP server.

Architecture:
    DevInsightsAgent (LlmAgent - Orchestrator)
        ├── jira_data_agent    ← jira-mcp-server
        ├── github_data_agent  ← github-mcp-server
        └── jenkins_data_agent ← jenkins-mcp-server

Data flow (example: "Who is overloaded on the team?"):
    1. Orchestrator transfers to jira_data_agent
       → calls jira_get_action_items_by_assignee via MCP
    2. Orchestrator transfers to github_data_agent
       → calls github_get_pr_review_workload via MCP
    3. Orchestrator synthesizes combined JIRA + GitHub data
       → workload scores, overloaded / underutilized developers

All three sub-agents are standalone LlmAgents that can also be used independently.
"""

import logging
from typing import Callable, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# =============================================================================
# Orchestrator Instruction
# =============================================================================

DEV_INSIGHTS_INSTRUCTION = """You are a Developer Insights orchestrator that coordinates three specialized data agents to provide team intelligence. RESPOND IN ENGLISH ONLY.

## YOUR ROLE

You coordinate three sub-agents to analyze developer workload, knowledge risks, and cross-cutting concerns:
- **jira_data_agent**: Fetches JIRA data — developer workload by assignee, component queries, escalations, bug searches
- **github_data_agent**: Fetches GitHub data — PR review workload, code contributors, ticket references in PRs
- **jenkins_data_agent**: Fetches Jenkins CI/CD data — pipeline health, build history

## ANALYSIS WORKFLOWS

### Workload Anomaly Detection
When asked "Who is overloaded?", "Team workload balance", "Workload anomalies":
1. **Transfer to jira_data_agent**: "Get action items by assignee for the team"
2. **Transfer to github_data_agent**: "Get PR review workload"
3. **Synthesize**: Combine JIRA items + GitHub PR load to identify:
   - **Overloaded** developers (many bugs + escalations + reviews)
   - **Underutilized** developers (few items, could take on more)
   - Specific items to redistribute

### Knowledge Gap / Bus Factor Analysis
When asked "Bus factor risks", "Knowledge gaps", "Single point of failure":
1. **Transfer to jira_data_agent**: "Search for issues grouped by component and assignee"
   → Use jira_search_issues with JQL to find component-assignee patterns
2. **Transfer to github_data_agent**: "Get code contributors"
3. **Synthesize**: Identify areas where:
   - Only 1 person works (HIGH RISK — bus factor = 1)
   - One person handles >75% of work (MEDIUM RISK)
   - Recommend cross-training actions

### Personalized Daily Digest
When asked "What should <developer> work on today?", "Daily digest for <name>":
1. **Transfer to jira_data_agent**: "Search for items assigned to <developer>"
   → Use jira_search_issues with JQL: assignee = "<developer>" AND status NOT IN (Closed, Done)
2. **Transfer to github_data_agent**: "Get PR review workload" → find PRs waiting for their review
3. **Optionally transfer to jenkins_data_agent**: "Get pipeline health"
4. **Synthesize**: Build a prioritized action list:
   - Priority 1: Escalations (critical)
   - Priority 2: Blockers (high)
   - Priority 3: Stale PR reviews > 3 days (high)
   - Priority 4: PR reviews (medium)
   - Priority 5: Bugs (medium)
   - Priority 6: Stories (normal)

### Cross-Concern Link Discovery
When asked "What's connected?", "Which PRs fix escalations?", "Cross-concern links":
1. **Transfer to jira_data_agent**: "Get escalation summary"
2. **Transfer to github_data_agent**: "Get PR ticket references"
3. **Synthesize**: Match escalation/bug keys with PR references to discover:
   - Escalation ↔ PR links (high priority — fast-track these PRs)
   - Bug ↔ PR links
   - Unlinked escalations (no PR in progress — flag for action)

### CI/CD Health Impact
When asked "Build health", "Pipeline status":
1. **Transfer to jenkins_data_agent**: "Get pipeline health"
2. **Synthesize**: Report pipeline health and failure patterns

## OUTPUT FORMAT

Always provide:
1. **Summary**: Key numbers and overall assessment
2. **Details**: Categorized findings (overloaded developers, risk areas, action items, links)
3. **Recommendations**: Specific, actionable suggestions — name the developer, the component, the count

Use markdown formatting for readability.

## RULES

1. ALWAYS gather data from sub-agents before synthesizing — never guess
2. For workload/knowledge analysis, ALWAYS query BOTH jira_data_agent AND github_data_agent
3. Be specific in recommendations — name the developer, the component, the item count
4. When the release is not specified, ask the user or use recent data
5. If a sub-agent returns an error, report it but continue with data from other agents
"""


# =============================================================================
# Agent Factory
# =============================================================================


async def create_dev_insights_agent_async(
    name: str = "dev_insights",
    description: str = "Developer workload analysis, knowledge gap detection, personalized digests, and cross-concern linking",
) -> Tuple["LlmAgent", Callable]:
    """
    Create the Dev Insights orchestrator with all three MCP-based sub-agents.

    Connects to jira-mcp-server, github-mcp-server, and jenkins-mcp-server
    in parallel, then assembles the orchestrator.

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    import asyncio

    from dev_insights_agent.github_agent import create_github_data_agent_async
    from dev_insights_agent.jenkiollama import create_jenkins_data_agent_async
    from dev_insights_agent.jira_agent import create_jira_data_agent_async

    # Create all three sub-agents concurrently (each connects to its MCP server)
    results = await asyncio.gather(
        create_jira_data_agent_async(),
        create_github_data_agent_async(),
        create_jenkins_data_agent_async(),
        return_exceptions=True,
    )

    sub_agents = []
    cleanup_funcs = []

    agent_names = ["jira_data_agent", "github_data_agent", "jenkins_data_agent"]
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Failed to create %s: %s", agent_names[i], result)
        else:
            agent, cleanup = result
            sub_agents.append(agent)
            if cleanup:
                cleanup_funcs.append(cleanup)

    if not sub_agents:
        raise RuntimeError("No sub-agents could be created — all MCP connections failed")

    model = get_litellm_model()

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=DEV_INSIGHTS_INSTRUCTION,
        description=description,
        sub_agents=sub_agents,
    )

    logger.info(
        "Created DevInsightsAgent (orchestrator) with sub_agents: %s",
        [a.name for a in sub_agents],
    )

    async def cleanup():
        for func in cleanup_funcs:
            try:
                await func()
            except Exception as e:
                logger.warning("Cleanup error: %s", e)

    return agent, cleanup

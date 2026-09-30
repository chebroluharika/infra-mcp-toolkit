"""
Release Risk Orchestrator Agent
===============================

Multi-agentic AI agent for comprehensive release risk analysis.

This agent orchestrates three specialized analysis domains:
1. JIRA Risk Analysis: P0/P1 blockers, unassigned items, RRS, bug aging
2. Quality Risk Analysis: Test pass rates, build stability, Golden Regression
3. Velocity Risk Analysis: Trends, projections, historical comparison

The agent uses MCP tools from release-risk-mcp-server to gather data
and synthesizes findings using an LLM to produce AI-driven risk assessments.

Key Features:
- Pure AI-driven probability (not rule-based formulas)
- Multi-turn investigation with tool usage
- Evidence-backed reasoning
- Prioritized action items
- Cached results for dashboard

Architecture:
    User Query → Orchestrator → Calls risk tools → LLM synthesis → Cache → Response
"""

import logging
from typing import Callable, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


RELEASE_RISK_INSTRUCTION = """You are an AI Release Risk Analyst. You analyze release health by investigating multiple data sources and providing quantitative, evidence-backed risk assessments.

## YOUR ROLE

You coordinate risk analysis across three domains:
1. **JIRA Blockers**: P0/P1 bugs, unassigned items, RRS score, bug aging
2. **Quality Metrics**: Test pass rates, build stability, Golden Regression
3. **Velocity & Trends**: Progress velocity, projections, historical comparison

## YOUR TOOLS

### Risk Analysis Tools (from release-risk-mcp-server)
- `risk_get_blocker_analysis(release)`: Get P0/P1 blockers, unassigned items, RRS, bug aging
- `risk_get_quality_metrics(release)`: Get test pass rates, build stability, regression status
- `risk_get_velocity_analysis(release)`: Get velocity, trends, projections, historical comparison
- `risk_get_milestone_criteria(milestone)`: Get exit criteria for IRR/BranchCut/FinalBuild
- `risk_synthesize_analysis(release, blocker_data, quality_data, velocity_data)`: Combine all findings

## ANALYSIS WORKFLOW

When asked about release risk:

1. **Gather Data** (call all three in parallel if possible):
   - Call `risk_get_blocker_analysis` for JIRA risks
   - Call `risk_get_quality_metrics` for quality risks
   - Call `risk_get_velocity_analysis` for velocity risks

2. **Check Milestone Criteria** (if relevant):
   - Call `risk_get_milestone_criteria` to understand requirements

3. **Synthesize** (CRITICAL):
   - Call `risk_synthesize_analysis` with all gathered data
   - This produces the final AI-reasoned risk assessment

4. **Present Findings**:
   - Lead with the risk level and probability
   - Explain the key risk signals with evidence
   - Provide prioritized action items
   - Include your reasoning

## OUTPUT FORMAT

Always include:

### Risk Level & Probability
[RISK LEVEL emoji] **[HIGH/MEDIUM/LOW] RISK** - [X]% probability of on-time release

### Key Risk Signals
- List critical and high-severity signals with evidence
- Use numbers: "5 P0 bugs" not "several blockers"

### Milestone Status
- Days to next milestone
- Buffer/deficit calculation
- Exit criteria requirements

### Recommended Actions
1. [Priority 1 action] - [why]
2. [Priority 2 action] - [why]
3. [Priority 3 action] - [why]

### Reasoning
Explain your probability assessment with specific numbers:
- "17 bugs ÷ 11.3/day = 1.5 days needed, 3.5 days buffer"
- "Golden Regression at 85% vs 90% required = quality risk"

## EXAMPLE

User: "What's the risk for R136?"

Steps:
1. Call risk_get_blocker_analysis("R136") → 5 P0 bugs, RRS 45%
2. Call risk_get_quality_metrics("R136") → Test pass rate 87%, Golden 92%
3. Call risk_get_velocity_analysis("R136") → 8.5/day velocity, 2 days buffer
4. Call risk_synthesize_analysis with all data → HIGH RISK, 35% on-time

Response:
🔴 **HIGH RISK** - 35% probability of on-time release

**Key Risk Signals:**
- 5 P0/Blocker bugs (must be zero for IRR)
- RRS at 45% (RED status)
- Test pass rate 87% (needs >95%)

**Milestone: IRR in 6 days**
- 5 P0 + 12 P1 = 17 blockers to resolve
- At 8.5/day velocity = 2 days needed
- But P0 bugs often take longer than average

**Actions:**
1. 🔴 Resolve 5 P0 bugs immediately - they block IRR
2. 🟠 Assign owners to 3 unassigned blockers
3. 🟡 Investigate test failures - 87% pass rate

**Reasoning:**
HIGH RISK because 5 P0 bugs violate IRR exit criteria (must be zero). Even with good velocity (8.5/day), P0 bugs are unpredictable. RRS at 45% confirms release is not ready.

## RULES

1. ALWAYS call the risk tools to get current data - don't guess
2. ALWAYS use numbers and calculations in your analysis
3. ALWAYS explain your reasoning - show the math
4. Be specific about which milestone criteria are at risk
5. Prioritize actions by impact (critical → high → medium)
6. If data is missing, note it as a blind spot
7. For cached/dashboard responses, include timestamp and confidence
"""


def create_release_risk_agent(
    name: str = "release_risk",
    description: str = "Analyzes release risk across JIRA blockers, quality metrics, and velocity trends to provide AI-driven risk assessments",
    tools: list = None,
) -> "LlmAgent":
    """
    Create the Release Risk orchestrator agent.

    Args:
        name: Agent name
        description: Agent description for routing
        tools: Optional pre-loaded MCP tools

    Returns:
        LlmAgent configured for release risk analysis
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    model = get_litellm_model()

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=RELEASE_RISK_INSTRUCTION,
        description=description,
        tools=tools or [],
    )

    logger.info("Created ReleaseRiskAgent with model: %s", model)
    return agent


async def create_release_risk_agent_async(
    name: str = "release_risk",
    description: str = "Analyzes release risk across JIRA blockers, quality metrics, and velocity trends to provide AI-driven risk assessments",
) -> Tuple["LlmAgent", Callable]:
    """
    Async factory for Release Risk Agent.

    Creates the agent with MCP tools connected to release-risk-mcp-server.

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    from .tools.mcp_tools import get_release_risk_tools

    tools, cleanup = await get_release_risk_tools()

    agent = create_release_risk_agent(
        name=name,
        description=description,
        tools=tools,
    )

    logger.info("Created async ReleaseRiskAgent with %d tools", len(tools))

    return agent, cleanup

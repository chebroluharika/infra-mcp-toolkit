"""
Escalation Analysis Agent (ADK Orchestrator)
=============================================

Multi-agent orchestrator that coordinates github_agent and testrail_agent
to produce categorized test recommendations for customer escalation PRs.

Architecture:
    EscalationAnalysisAgent (LlmAgent - Orchestrator)
        └── sub_agents:
            ├── github_agent: PR details, code context, dependencies
            └── testrail_agent: Test case matching, coverage gaps

Output:
    - MUST RUN: TestRail cases directly impacted
    - SHOULD RUN: TestRail cases impacted via dependencies
    - MANUAL QA SCENARIOS: New scenarios not in TestRail
    - TEST GAPS: Areas with no TestRail coverage

Access:
    - Chat: via root router pattern matching
    - API: via POST /api/agents/analyze-pr endpoint
"""

from .agent import create_escalation_analysis_agent, create_escalation_analysis_agent_async

__all__ = [
    "create_escalation_analysis_agent",
    "create_escalation_analysis_agent_async",
]

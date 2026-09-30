"""
Release Risk Agent
==================

Multi-agentic orchestrator for comprehensive release risk analysis.
Coordinates three specialized sub-agents to analyze JIRA blockers,
quality metrics, and velocity trends, then synthesizes a final
AI-driven risk assessment.

Architecture:
    ReleaseRiskOrchestrator (LlmAgent)
        ├── jira_risk_agent: Analyzes blockers, bugs, RRS
        ├── quality_risk_agent: Analyzes tests, builds, regressions
        └── velocity_risk_agent: Analyzes trends, predictions, history

The orchestrator calls tools from the release-risk-mcp-server to
gather data from each domain, then uses an LLM to synthesize
findings into a cohesive risk assessment.

Usage:
    from release_risk_agent import create_release_risk_agent_async

    agent, cleanup = await create_release_risk_agent_async()
    # Use agent...
    await cleanup()
"""

from .agent import create_release_risk_agent, create_release_risk_agent_async

__all__ = [
    "create_release_risk_agent",
    "create_release_risk_agent_async",
]

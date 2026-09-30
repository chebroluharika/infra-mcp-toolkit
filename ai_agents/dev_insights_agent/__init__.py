"""
Dev Insights Agent (Multi-Agent Orchestrator — MCP-based)
==========================================================

Coordinates three specialized sub-agents, each connected to its MCP server:

    DevInsightsAgent (orchestrator)
        ├── jira_data_agent    ← jira-mcp-server
        ├── github_data_agent  ← github-mcp-server
        └── jenkins_data_agent ← jenkins-mcp-server

Capabilities:
- Knowledge Gap / Bus Factor analysis
- Personalized Daily Digest (per-developer action items)
- Workload Anomaly detection (overloaded / underutilized)
- Cross-Concern Link discovery (escalation↔PR, component clusters)
"""

from .agent import create_dev_insights_agent_async

__all__ = ["create_dev_insights_agent_async"]

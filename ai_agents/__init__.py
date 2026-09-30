"""
AI Agents (ADK + MCP)
=====================

Multi-agent AI system using Google ADK with MCP tool servers.

Architecture (ADK Pattern):
    Root Agent (entry point)
    └── Sub-agents (specialists)
        ├── release_readiness - MCP tools for JIRA, Calendar, TestRail, Jenkins, GitHub
        └── documentation - Documentation search with RAG

MCP Servers:
- jira-mcp-server: Bugs, escalations, release status
- release-calendar-mcp-server: Release dates, milestones
- testrail-mcp-server: Test execution status
- jenkins-mcp-server: CI/CD pipeline status
- github-mcp-server: Commit tracking

Usage:
    from ai_agents import create_root_agent_async
    root_agent, cleanup = await create_root_agent_async()
"""

from .core import check_adk_available, get_runner
from .docs_agent import create_docs_agent
from .release_readiness_agent import create_release_agent_async
from .root_agent import create_root_agent_async
from .tfa_agent import TFAAgent, get_tfa_agent

__all__ = [
    # Core
    "get_runner",
    "check_adk_available",
    # Agents (MCP-based)
    "create_root_agent_async",
    "create_release_agent_async",
    "create_docs_agent",
    "TFAAgent",
    "get_tfa_agent",
]

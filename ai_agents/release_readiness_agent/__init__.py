"""
Release Readiness Agent (ADK + MCP)
===================================

Handles release status, bugs, tests, milestones, and escalations.
Tools are provided by MCP servers (JIRA, Calendar, TestRail, Jenkins, GitHub).

Usage:
    agent, cleanup = await create_release_agent_async()
"""

from .agent import create_release_agent_async, get_release_adk_agent

__all__ = [
    "create_release_agent_async",
    "get_release_adk_agent",
]

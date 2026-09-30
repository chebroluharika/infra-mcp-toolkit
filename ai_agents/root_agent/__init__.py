"""
Root Agent (ADK + MCP)
======================

Main root agent that routes queries to specialized sub-agents.
Uses ADK's native sub_agents and transfer_to_agent mechanism.

Architecture:
    RootAgent (LlmAgent)
        └── sub_agents=[release_readiness, jenkiollama, documentation]

The root agent's LLM decides which sub-agent to transfer to based on
the query content and each sub-agent's description.

Usage:
    root_agent, cleanup = await create_root_agent_async()
"""

from .agent import create_root_agent_async, get_root_agent

__all__ = [
    "create_root_agent_async",
    "get_root_agent",
]

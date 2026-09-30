"""
Core Utilities
==============

Shared utilities for all AI agents.

Modules:
- models: Dataclasses (AgentResponse, AgentInfo, ToolResult, SessionInfo)
- base: Model configuration and ADK availability checks
- runner: Agent execution with session management
- utils: Query extraction and response formatting
- agent_communication: Agent registry for dynamic routing
"""

from .agent_communication import AgentRegistry, query_agent
from .base import check_adk_available, ensure_ollama_configured, get_litellm_model
from .models import AgentInfo, AgentResponse, SessionInfo, ToolResult
from .runner import AgentRunner, get_runner
from .utils import CoreUtils, get_utils

# Configure Ollama globally on module import (ensures headers are set early)
ensure_ollama_configured()

__all__ = [
    # Models (Dataclasses)
    "AgentResponse",
    "AgentInfo",
    "ToolResult",
    "SessionInfo",
    # Base
    "check_adk_available",
    "get_litellm_model",
    "ensure_ollama_configured",
    # Runner
    "AgentRunner",
    "get_runner",
    # Utilities
    "CoreUtils",
    "get_utils",
    # Agent Communication
    "AgentRegistry",
    "query_agent",
]

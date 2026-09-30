"""
ADK Data Models
===============

Dataclasses for ADK agent system.

Usage:
    from core.models import AgentResponse, AgentInfo, ToolResult, SessionInfo
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class AgentResponse:
    """
    Response from agent execution.

    Returned by AgentRunner.run() after processing a query.
    """

    content: str
    session_id: str
    agent_name: str = "unknown"
    tools_used: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentInfo:
    """
    Registered agent metadata.

    Used by AgentRegistry to store agent information.
    """

    name: str
    description: str
    factory: Callable  # Function that creates the agent instance
    capabilities: List[str] = field(default_factory=list)
    example_queries: List[str] = field(default_factory=list)
    _instance: Any = field(default=None, repr=False)

    def get_instance(self):
        """Get or create agent instance (singleton)."""
        if self._instance is None:
            self._instance = self.factory()
        return self._instance

    def clear_instance(self):
        """Clear cached instance."""
        self._instance = None


@dataclass
class ToolResult:
    """
    Result from tool execution.

    Used by runner when executing tool calls.
    """

    success: bool
    data: Any = None
    error: Optional[str] = None
    tool_name: Optional[str] = None
    execution_time_ms: Optional[float] = None


@dataclass
class SessionInfo:
    """
    Session information for agent conversations.

    Used for tracking conversation context.
    """

    session_id: str
    agent_name: str
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    message_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

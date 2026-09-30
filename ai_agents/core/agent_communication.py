"""
Agent Registry
==============

Dynamic agent registry for multi-agent routing.

Usage:
    from core.agent_communication import AgentRegistry

    # Register a new agent
    AgentRegistry.register(
        name="my_agent",
        description="What this agent does",
        factory=create_my_agent,
        capabilities=["cap1", "cap2"],
    )

    # Query an agent
    result = await query_agent("my_agent", "question")
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from .models import AgentInfo

logger = logging.getLogger(__name__)


# =============================================================================
# Agent Registry
# =============================================================================


class AgentRegistry:
    """
    Central registry for ADK agents.

    Enables:
    - Dynamic agent discovery
    - Agent lookup by name
    - Tool descriptions for LLM instructions
    """

    _agents: Dict[str, AgentInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        description: str,
        factory: Callable,
        capabilities: List[str] = None,
        example_queries: List[str] = None,
    ) -> None:
        """Register an agent."""
        cls._agents[name] = AgentInfo(
            name=name,
            description=description,
            factory=factory,
            capabilities=capabilities or [],
            example_queries=example_queries or [],
        )
        logger.info("Registered agent: %s", name)

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Remove an agent from registry."""
        if name in cls._agents:
            del cls._agents[name]
            return True
        return False

    @classmethod
    def get(cls, name: str) -> Optional[AgentInfo]:
        """Get agent info by name."""
        return cls._agents.get(name)

    @classmethod
    def get_instance(cls, name: str) -> Optional[Any]:
        """Get agent instance by name."""
        info = cls._agents.get(name)
        return info.get_instance() if info else None

    @classmethod
    def list_agents(cls) -> List[str]:
        """List all registered agent names."""
        return list(cls._agents.keys())

    @classmethod
    def clear_instances(cls) -> None:
        """Clear all cached agent instances."""
        for info in cls._agents.values():
            info.clear_instance()

    @classmethod
    def get_tool_descriptions(cls, exclude: str = None) -> str:
        """
        Get agent descriptions for LLM instructions.

        Args:
            exclude: Agent name to exclude

        Returns:
            Formatted markdown describing available agents
        """
        lines = ["## Available Agents", ""]
        lines.append("Query other agents for specialized tasks.")
        lines.append("")

        for name, info in cls._agents.items():
            if name == exclude:
                continue

            lines.append(f"### {name}")
            lines.append(f"**{info.description}**")
            lines.append("")

            if info.capabilities:
                lines.append("Capabilities:")
                for cap in info.capabilities:
                    lines.append(f"- {cap}")
                lines.append("")

            if info.example_queries:
                lines.append("Example queries:")
                for q in info.example_queries[:2]:
                    lines.append(f'- "{q}"')
                lines.append("")

        return "\n".join(lines)


# =============================================================================
# Cross-Agent Query (for Runner's JSON tool call handling)
# =============================================================================


async def query_agent(
    agent_name: str,
    query: str,
    context: str = None,
    session_id: str = None,
) -> Dict[str, Any]:
    """
    Query an agent programmatically.

    Used by Runner when handling JSON tool calls (e.g., from LLM).

    Args:
        agent_name: Name of the agent to query
        query: The question to ask
        context: Optional context
        session_id: Session ID for context sharing

    Returns:
        Dict with response and metadata
    """
    try:
        from core.runner import get_runner

        agent_info = AgentRegistry.get(agent_name)
        if not agent_info:
            return {
                "success": False,
                "error": f"Unknown agent: {agent_name}",
                "available_agents": AgentRegistry.list_agents(),
            }

        agent = agent_info.get_instance()
        runner = get_runner()

        # Build query with context
        full_query = f"Context: {context}\n\nQuestion: {query}" if context else query

        # Use shared or cross-agent session
        effective_session_id = session_id or f"cross-agent-{agent_name}"

        response = await runner.run(
            agent=agent,
            message=full_query,
            session_id=effective_session_id,
        )

        if not response.content or response.error:
            raise ValueError(response.error or "Empty response")

        return {
            "success": True,
            "agent": agent_name,
            "response": response.content,
            "tools_used": response.tools_used,
        }

    except Exception as e:
        logger.error("Cross-agent query failed: %s", e)
        return {
            "success": False,
            "agent": agent_name,
            "error": str(e),
        }


# =============================================================================
# Built-in Agent Registration
# =============================================================================


def _register_builtin_agents():
    """Register built-in agents on module load."""

    def _create_release_agent():
        from release_readiness_agent.agent import create_release_agent

        return create_release_agent()

    AgentRegistry.register(
        name="release_readiness",
        description="Release status, bugs, stories, milestones, escalations, CI/CD",
        factory=_create_release_agent,
        capabilities=[
            "release health score",
            "bug tracking (critical, regression, P0/P1)",
            "milestone status (IRR, Branch Cut, Final Build)",
            "escalations (EHF, IMF)",
            "code commits after branch cut",
            "test execution status",
        ],
        example_queries=[
            "What is the release readiness score?",
            "Are there any critical bugs?",
            "Show me commits after branch cut",
        ],
    )

    def _create_docs_agent():
        from docs_agent.agent import create_docs_agent

        return create_docs_agent()

    AgentRegistry.register(
        name="documentation",
        description="Documentation search using semantic search (RAG)",
        factory=_create_docs_agent,
        capabilities=[
            "documentation search",
            "how-to guides",
            "configuration instructions",
            "troubleshooting steps",
        ],
        example_queries=[
            "How do I configure proxy settings?",
            "What are the system requirements?",
        ],
    )

    # --- New agents for test recommendation pipeline ---

    def _create_github_agent():
        from github_agent.agent import create_github_agent

        return create_github_agent()

    AgentRegistry.register(
        name="github_agent",
        description="Code-aware GitHub analysis: PR details, file context, dependency graphs",
        factory=_create_github_agent,
        capabilities=[
            "PR analysis (files changed, stats, author)",
            "code context retrieval (file purpose, functions, docstrings)",
            "dependency graph queries (what depends on a file)",
            "repository indexing into FAISS",
        ],
        example_queries=[
            "Analyze PR #7887 in your-org/your-product",
            "What does session_manager.py do?",
            "What files depend on auth/login.py?",
        ],
    )

    def _create_testrail_agent():
        from testrail_agent.agent import create_testrail_agent

        return create_testrail_agent()

    AgentRegistry.register(
        name="testrail_agent",
        description="Test-aware TestRail analysis: test case search, coverage gaps, test run status",
        factory=_create_testrail_agent,
        capabilities=[
            "test case semantic search",
            "test coverage analysis",
            "test run status queries",
            "TestRail indexing into FAISS",
        ],
        example_queries=[
            "Find tests for session management",
            "Check test coverage for login, NPA, steering",
            "Index TestRail milestone 5319",
        ],
    )

    def _create_escalation_agent():
        from escalation_analysis_agent.agent import create_escalation_analysis_agent

        return create_escalation_analysis_agent()

    AgentRegistry.register(
        name="escalation_analysis",
        description="Analyzes PRs from customer escalations to recommend QA tests using code context and TestRail matching",
        factory=_create_escalation_agent,
        capabilities=[
            "PR test impact analysis",
            "MUST RUN / SHOULD RUN test recommendations",
            "manual QA scenario generation",
            "test gap identification",
        ],
        example_queries=[
            "Analyze PR #7887 for test impact",
            "What should QA test for this escalation?",
            "Find test gaps for PR changes",
        ],
    )

    # --- Dev Insights agent for team intelligence (MCP-based orchestrator) ---
    # Note: This agent is async-only (MCP connections). It is created via
    # create_dev_insights_agent_async() in root_agent/agent.py.
    # The registry entry uses a placeholder factory; the real creation
    # happens in root_agent's AgentConfig (is_async=True).

    def _create_dev_insights_agent():
        raise RuntimeError(
            "dev_insights requires async creation (MCP servers). " "Use create_dev_insights_agent_async() instead."
        )

    AgentRegistry.register(
        name="dev_insights",
        description="Developer workload analysis, knowledge gap detection, personalized digests, and cross-concern linking",
        factory=_create_dev_insights_agent,
        capabilities=[
            "knowledge gap / bus factor analysis",
            "personalized daily digest per developer",
            "workload anomaly detection (overloaded / underutilized)",
            "cross-concern link discovery (escalation↔PR, component clusters)",
        ],
        example_queries=[
            "Who is overloaded on the team?",
            "What should John work on today?",
            "Show bus factor risks for R135",
            "Which PRs are linked to escalations?",
        ],
    )

    logger.info("Registered %s built-in agents", len(AgentRegistry.list_agents()))


# Register on import
try:
    _register_builtin_agents()
except Exception as e:
    logger.warning("Could not auto-register agents: %s", e)

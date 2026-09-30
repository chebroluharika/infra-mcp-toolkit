"""
Root Agent (ADK + MCP) - Multi-Agent with Code Routing
=======================================================

Architecture:
    Router (code-based, instant)
        ├── release_readiness (LlmAgent + MCP tools) - LLM picks Jira/Calendar/GitHub tools
        ├── jenkiollama (LlmAgent + MCP tools) - LLM picks Jenkins tools
        └── documentation (LlmAgent + tools) - LLM picks doc search tools

How it works:
    1. Router uses patterns to select the right specialized agent (instant, no LLM)
    2. Specialized agent uses LLM to decide which MCP tool to call
    3. Single LLM call per query - works with local LLMs

Usage:
    router, cleanup = await create_root_agent_async()
    # Runner calls router.route(query) to get the right agent
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from core.base import check_adk_available

logger = logging.getLogger(__name__)

# ADK imports
if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# =============================================================================
# Routing Patterns
# =============================================================================

ROUTING_PATTERNS = {
    "jenkiollama": [
        r"\b(jenkins|pipeline|pipelines|ci/?cd)\b",
        r"\b(tfa|test\s*failure\s*analysis)\b",
        r"\b(root\s*cause|why\s*(did|does|is).*fail)\b",
        r"\b(build\s*#?\d+|build\s*number|build\s+\d+)\b",
        r"\b(golden\s*regression)\b",
        r"\b(pdv|endpoint\s*pdv)\b",  # Endpoint PDV runs
        r"\b(list|show|get)\s*(latest|last|recent)?\s*\d*\s*(builds?|runs?|pipelines?)\b",
        r"\bbuilds?\s+(for|of)\s+\w+",
        r"\b(backend|frontend|client)\s*(build|pipeline)",
    ],
    "documentation": [
        r"\b(how\s+(to|do|can)\s+(i\s+)?(install|configure|setup|set\s*up))\b",
        r"\b(documentation|docs?)\s+(for|about|on)\b",
        r"\b(install(ation)?|uninstall)\s+(your-company|client|your-product)\b",
        r"\b(configure|configuration|setup|settings?)\s+(guide|steps?|your-company|client)\b",
        r"\b(troubleshoot|troubleshooting|debug|diagnose)\b",
        r"\bwhat\s+is\s+(your-company|your-product|steering|npa|private\s*access)\b",
        r"\b(supported|support)\s+(os|operating|platform)",  # Supported OS queries
        r"\b(os|operating|platform)\s+(support|requirement)",
        r"\b(windows|macos|linux|android|ios|chromeos)\b.*\b(support|version|require)",
        r"\b(version|versions)\s+(of\s+)?(windows|macos|linux|android|ios)",  # "versions of macOS"
        r"\bwhat\s+(windows|macos|linux|android|ios|os)\s+(version|are)",  # "what macOS versions"
        r"\b(deploy|deployment)\s+(option|method|way)",  # Deployment queries
        r"\b(port|ports|network)\s+(require|config|setting)",  # Network/port queries
        r"\b(steer|steering)\b",  # Steering queries
        r"\b(resource|cpu|memory|battery)\s+(usage|utilization)",  # Resource queries
    ],
    "release_readiness": [
        r"\b(jira|bug|bugs|story|stories|issue|issues)\b",
        r"\b(irr|branch\s*cut|final\s*build|milestone)\b",
        r"\b(release|r\d{3})\s*(status|ready|green|red|yellow)\b",
        r"\b(is\s+r?\d{3}\s+green)\b",
        r"\b(rrs|release\s*readiness|readiness\s*score)\b",
        r"\b(critical|blocker|p0|p1)\b",
        r"\b(escalation|ehf|imf)\b",
        r"\b(calendar|schedule|dates?|when\s+is)\b",
        r"\b(commit|commits)\s+(before|after|for)\b",
        r"\b(who\s+(is\s+working|has)|assigned\s+to|assignee|by\s+assignee|action\s*items?|open\s*items?)\b",
        r"\b(more\s*info|moreinfo|needs?\s+info|pending\s+info)\b",
        r"\b(your-product|ns\s*client|npa|epdlp|component)\b",  # Component-related queries
    ],
    "escalation_analysis": [
        r"\b(test\s*gap|test\s*coverage|what.*test|recommend.*test)\b",
        r"\b(escalation.*analy[sz]|customer.*escalation.*analy)\b",
        r"\b(pr\s*#?\d+|pull\s*request)\s*(analy[sz]|impact|test)\b",
        r"\b(what\s+should\s+qa\s+(test|run|check))\b",
        r"\b(impact\s*analysis|code\s*impact)\b",
        r"\b(analyze\s+pr|pr\s+analysis)\b",
        r"\b(must\s*run|should\s*run|test\s*scenario)\b",
        r"\b(testrail.*match|match.*testrail)\b",
    ],
    "dev_insights": [
        r"\b(workload|overload|underutil|capacity)\b",
        r"\b(who\s+is\s+(overloaded|busy|free|available))\b",
        r"\b(bus\s*factor|knowledge\s*(gap|risk|silo))\b",
        r"\b(single\s*point\s*of\s*failure|sole\s*owner|only\s*person)\b",
        r"\b(daily\s*digest|morning\s*brief|action\s*summary)\b",
        r"\b(what\s+should\s+\w+\s+work\s+on)\b",
        r"\b(cross[\s-]*concern|connected\s*issues?|linked\s*items?)\b",
        r"\b(team\s*(balance|distribution|health|insight))\b",
        r"\b(developer\s*(insight|workload|summary|digest))\b",
        r"\b(rebalance|redistribute)\b",
    ],
    "release_risk": [
        r"\b(risk|risky)\s*(analysis|assess|predict|evaluat)\b",
        r"\b(release\s*risk|risk\s*predict)\b",
        r"\b(will|can)\s+we\s+(hit|make|meet)\s+(milestone|irr|branch\s*cut|final\s*build)\b",
        r"\b(on[\s-]*track|slip|delay)\s*(risk|predict|analysis)\b",
        r"\b(probability|chance|likelihood)\s*(of|for)?\s*(release|milestone|on[\s-]*time)\b",
        r"\b(should\s+i\s+be\s+worried|concerned|worried\s+about)\s*(release|milestone|r\d{3})\b",
        r"\b(what\s*['\u2019]?s?\s+the\s+risk)\b",
        r"\b(risk\s*level|risk\s*score)\b",
        r"\b(analyze\s*risk|risk\s*for\s*r\d{3})\b",
        r"\b(predict|forecast)\s*(release|milestone)\b",
    ],
}

DEFAULT_AGENT = "release_readiness"


# =============================================================================
# Agent Configuration
# =============================================================================


@dataclass
class AgentConfig:
    """Configuration for a specialized agent."""

    name: str
    factory: Callable
    is_async: bool = True


AGENT_CONFIGS = [
    AgentConfig(
        name="jenkiollama",
        factory=lambda: __import__(
            "jenkiollama", fromlist=["create_jenkiollama_async"]
        ).create_jenkiollama_async(),
        is_async=True,
    ),
    AgentConfig(
        name="documentation",
        factory=lambda: __import__("docs_agent", fromlist=["create_docs_agent"]).create_docs_agent(),
        is_async=False,
    ),
    AgentConfig(
        name="release_readiness",
        factory=lambda: __import__(
            "release_readiness_agent", fromlist=["create_release_agent_async"]
        ).create_release_agent_async(),
        is_async=True,
    ),
    AgentConfig(
        name="escalation_analysis",
        factory=lambda: __import__(
            "escalation_analysis_agent", fromlist=["create_escalation_analysis_agent_async"]
        ).create_escalation_analysis_agent_async(),
        is_async=True,
    ),
    AgentConfig(
        name="dev_insights",
        factory=lambda: __import__(
            "dev_insights_agent", fromlist=["create_dev_insights_agent_async"]
        ).create_dev_insights_agent_async(),
        is_async=True,
    ),
    AgentConfig(
        name="release_risk",
        factory=lambda: __import__(
            "release_risk_agent", fromlist=["create_release_risk_agent_async"]
        ).create_release_risk_agent_async(),
        is_async=True,
    ),
]


# =============================================================================
# Router
# =============================================================================


class AgentRouter:
    """
    Routes queries to specialized agents using pattern matching.

    The routing is instant (no LLM call). Each specialized agent then
    uses its LLM to decide which MCP tool to call.
    """

    def __init__(self, agents: Dict[str, LlmAgent]):
        self.agents = agents
        self.name = "router"  # For compatibility with runner

    def route(self, query: str) -> LlmAgent:
        """
        Route query to the appropriate specialized agent.

        Args:
            query: User's question

        Returns:
            The LlmAgent best suited to handle this query
        """
        query_lower = query.lower()

        # Check each agent's patterns
        for agent_name, patterns in ROUTING_PATTERNS.items():
            if agent_name not in self.agents:
                continue
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    logger.info("[Router] '{query[:50]}' → %s", agent_name)
                    return self.agents[agent_name]

        # Default agent
        default = self.agents.get(DEFAULT_AGENT, list(self.agents.values())[0])
        logger.info("[Router] '{query[:50]}' → %s (default)", default.name)
        return default

    def get_agent(self, name: str) -> Optional[LlmAgent]:
        """Get agent by name."""
        return self.agents.get(name)

    @property
    def agent_names(self) -> List[str]:
        """List of available agent names."""
        return list(self.agents.keys())


# =============================================================================
# Factory
# =============================================================================


async def _create_agent(config: AgentConfig) -> Tuple[str, Optional[LlmAgent], Optional[Callable]]:
    """Create an agent from config."""
    try:
        if config.is_async:
            agent, cleanup = await config.factory()
        else:
            agent = config.factory()
            cleanup = None

        logger.info("✅ %s agent created", config.name)
        return config.name, agent, cleanup
    except Exception as e:
        logger.warning("⚠️ Failed to create %s: %s", config.name, e)
        return config.name, None, None


async def create_root_agent_async() -> Tuple[AgentRouter, Callable]:
    """
    Create the agent router with all specialized agents.

    Returns either SemanticRouter (LLM-based) or AgentRouter (pattern-based)
    based on configuration.

    Returns:
        Tuple of (Router, cleanup function)
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed")

    # Create all agents concurrently
    results = await asyncio.gather(*[_create_agent(config) for config in AGENT_CONFIGS], return_exceptions=True)

    # Collect successful agents
    agents = {}
    cleanup_funcs = []

    for result in results:
        if isinstance(result, Exception):
            logger.warning("Agent creation failed: %s", result)
            continue
        name, agent, cleanup = result
        if agent:
            agents[name] = agent
            if cleanup:
                cleanup_funcs.append(cleanup)

    if not agents:
        raise RuntimeError("No agents could be created!")

    # Create router based on configuration
    from core.base import get_settings

    settings = get_settings()

    # Check for NLP routing (embedding-based, no LLM call)
    use_nlp_routing = getattr(settings, "use_nlp_routing", True)  # Default to NLP

    if use_nlp_routing:
        # Use NLP-based routing (embeddings + cosine similarity)
        from core.intent_classifier import create_nlp_router

        router = create_nlp_router(agents)
        logger.info("✅ NLPRouter (embedding-based) ready with agents: %s", list(agents.keys()))
    elif settings.use_semantic_routing:
        # Use LLM-powered semantic routing (slow, more accurate)
        from core.semantic_router import create_semantic_router

        router = create_semantic_router(agents)
        logger.info("✅ SemanticRouter (LLM-based) ready with agents: %s", list(agents.keys()))
    else:
        # Use pattern-based routing (fast, less flexible)
        router = AgentRouter(agents)
        logger.info("✅ AgentRouter (pattern-based) ready with agents: %s", router.agent_names)

    # Cleanup function
    async def cleanup():
        for func in cleanup_funcs:
            try:
                result = func()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("Cleanup error: %s", e)

    return router, cleanup


# =============================================================================
# Singleton
# =============================================================================

_router: Optional[AgentRouter] = None
_cleanup: Optional[Callable] = None


async def get_root_agent() -> Tuple[AgentRouter, Callable]:
    """Get or create router singleton."""
    global _router, _cleanup
    if _router is None:
        _router, _cleanup = await create_root_agent_async()
    return _router, _cleanup

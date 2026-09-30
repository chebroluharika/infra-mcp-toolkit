"""
Semantic Router
================

LLM-powered query routing with structured output and confidence scoring.

Uses few-shot prompting to classify queries into agent categories:
- release_readiness: JIRA bugs, releases, milestones, dates
- jenkins: CI/CD pipelines, builds, test failures
- documentation: How-to guides, installation, configuration

Features:
- Structured JSON output for reliable parsing
- Confidence scoring with fallback to pattern matching
- Few-shot examples for better local model performance
- English enforcement for Qwen/Chinese models

Usage:
    router = SemanticRouter(agents_dict)
    agent, confidence = await router.route_async("show me critical bugs")
"""

import json
import logging
import re
from typing import Any, Dict, Tuple

# Import from core.base which already handles config import correctly
from core.base import get_english_system_prompt, get_settings

logger = logging.getLogger(__name__)


class SemanticRouter:
    """
    LLM-powered semantic routing for agent selection.

    Uses structured output (JSON) and few-shot prompting for reliable
    routing decisions with local models like Qwen and Gemma.
    """

    def __init__(self, agents: Dict[str, Any]):
        """
        Initialize semantic router.

        Args:
            agents: Dictionary mapping agent names to agent instances
        """
        self.agents = agents
        self.settings = get_settings()
        self.agent_descriptions = {
            "release_readiness": (
                "Handles queries about JIRA bugs, release status, milestones, "
                "critical issues, release dates, code commits, GitHub, calendars, "
                "escalations, action items by assignee, open items, "
                "YOUR_PRODUCT/NPA/EPDLP components, and who has work assigned"
            ),
            "jenkiollama": (
                "Handles queries about Jenkins CI/CD pipelines, build status, "
                "test failures, test failure analysis (TFA), root cause analysis, "
                "build numbers, pipeline runs, build history, 'list builds for X', "
                "'last N runs for Y', Backend Regression, golden regression, "
                "Endpoint PDV runs, PDV status, and CI/CD builds"
            ),
            "documentation": (
                "Handles queries about installation guides, configuration steps, "
                "how-to documentation, troubleshooting, YourCompany client setup, "
                "and feature explanations"
            ),
            "escalation_analysis": (
                "Handles queries about test gaps, test coverage analysis, "
                "PR impact analysis, pull request testing recommendations, "
                "what QA should test, code impact analysis, must-run tests, "
                "TestRail matching, and escalation root cause analysis"
            ),
            "dev_insights": (
                "Handles queries about developer workload, team capacity, "
                "who is overloaded or available, bus factor, knowledge gaps, "
                "single points of failure, daily digest, morning briefs, "
                "cross-concerns, team health, and workload rebalancing"
            ),
            "release_risk": (
                "Handles queries about release risk prediction, risk analysis, "
                "milestone probability, will we hit IRR/branch cut, on-track status, "
                "delay predictions, risk scores, and release forecasting"
            ),
        }

        # LLM is initialized per-request using litellm directly
        self.llm = True  # Flag to indicate LLM is available

    def route(self, query: str) -> Tuple[Any, float]:
        """
        Route query to appropriate agent (synchronous wrapper).

        Note: This should NOT be called when event loop is running.
        Use route_async() instead in async contexts.

        Args:
            query: User query

        Returns:
            Tuple of (agent, confidence_score)
        """
        import asyncio

        try:
            # Create a new event loop for sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.route_async(query))
            finally:
                loop.close()
        except Exception:
            # Fallback to default agent
            default_agent = self.agents.get("release_readiness", list(self.agents.values())[0])
            return default_agent, 0.5

    async def route_async(self, query: str) -> Tuple[Any, float]:
        """
        Route query to appropriate agent using LLM with retry logic.

        Args:
            query: User query

        Returns:
            Tuple of (agent, confidence_score)
        """
        if not self.llm:
            logger.warning("LLM not available for routing, using default agent")
            return self._get_default_agent()

        max_retries = getattr(self.settings, "max_routing_retries", 2)
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Build routing prompt (with retry hint if not first attempt)
                prompt = self._build_routing_prompt(query, attempt)

                # Use litellm directly for routing
                import litellm

                model_string = self.settings.get_litellm_model_string()

                response = await litellm.acompletion(
                    model=model_string,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.settings.routing_temperature,
                    max_tokens=256,
                )

                response_text = response.choices[0].message.content

                # Parse structured response
                agent_name, confidence, reasoning = self._parse_routing_response(response_text)

                # Check if we got a valid response
                if confidence >= self.settings.routing_confidence_threshold:
                    logger.info(
                        "[SemanticRouter] Query: '%s' → Agent: %s (confidence: %.2f, attempt: %d)",
                        query[:50],
                        agent_name,
                        confidence,
                        attempt + 1,
                    )
                    agent = self.agents.get(agent_name)
                    if agent:
                        return agent, confidence

                # Low confidence or invalid agent - retry with rephrased prompt
                if attempt < max_retries:
                    logger.warning(
                        "[SemanticRouter] Attempt %d: Low confidence (%.2f) or invalid agent, retrying...",
                        attempt + 1,
                        confidence,
                    )
                    continue

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning("[SemanticRouter] Attempt %d failed: %s, retrying...", attempt + 1, e)
                    continue

        # All retries exhausted - fall back to pattern matching
        logger.warning(
            "[SemanticRouter] All %d attempts failed, falling back to pattern matching. Last error: %s",
            max_retries + 1,
            last_error,
        )
        return self._pattern_fallback(query)

    def _get_default_agent(self) -> Tuple[Any, float]:
        """Get default agent with low confidence."""
        default_agent = self.agents.get("release_readiness", list(self.agents.values())[0])
        return default_agent, 0.5

    def _pattern_fallback(self, query: str) -> Tuple[Any, float]:
        """Fallback to pattern-based routing when LLM fails."""
        query_lower = query.lower()

        # Jenkins patterns
        jenkins_patterns = ["jenkins", "pipeline", "build", "ci/cd", "tfa", "test failure", "pdv"]
        if any(p in query_lower for p in jenkins_patterns):
            agent = self.agents.get("jenkiollama") or self.agents.get("jenkins")
            if agent:
                logger.info("[SemanticRouter] Pattern fallback → jenkiollama")
                return agent, 0.7

        # Documentation patterns
        doc_patterns = ["install", "configure", "how to", "setup", "troubleshoot", "documentation"]
        if any(p in query_lower for p in doc_patterns):
            agent = self.agents.get("documentation")
            if agent:
                logger.info("[SemanticRouter] Pattern fallback → documentation")
                return agent, 0.7

        # Escalation analysis patterns
        escalation_patterns = ["pr ", "pull request", "test gap", "impact analysis", "what should qa"]
        if any(p in query_lower for p in escalation_patterns):
            agent = self.agents.get("escalation_analysis")
            if agent:
                logger.info("[SemanticRouter] Pattern fallback → escalation_analysis")
                return agent, 0.7

        # Dev insights patterns
        dev_patterns = ["workload", "overload", "bus factor", "knowledge gap", "capacity"]
        if any(p in query_lower for p in dev_patterns):
            agent = self.agents.get("dev_insights")
            if agent:
                logger.info("[SemanticRouter] Pattern fallback → dev_insights")
                return agent, 0.7

        # Release risk patterns
        risk_patterns = ["risk", "will we hit", "on track", "probability", "forecast"]
        if any(p in query_lower for p in risk_patterns):
            agent = self.agents.get("release_risk")
            if agent:
                logger.info("[SemanticRouter] Pattern fallback → release_risk")
                return agent, 0.7

        # Default to release_readiness
        logger.info("[SemanticRouter] Pattern fallback → release_readiness (default)")
        return self._get_default_agent()

    def _build_routing_prompt(self, query: str, attempt: int = 0) -> str:
        """Build few-shot routing prompt with structured output."""

        english_prompt = get_english_system_prompt()

        # Add retry hint for subsequent attempts
        retry_hint = ""
        if attempt > 0:
            retry_hint = f"""
IMPORTANT: This is retry attempt {attempt + 1}. Your previous response was invalid or had low confidence.
Please output ONLY valid JSON with high confidence. Do not add any explanation or markdown.
"""

        # Build agent list dynamically from available agents
        agent_list = []
        for i, (name, desc) in enumerate(self.agent_descriptions.items(), 1):
            if name in self.agents:
                agent_list.append(f"{i}. **{name}**: {desc}")
        agent_list_str = "\n".join(agent_list)

        prompt = f"""{english_prompt}{retry_hint}You are a query routing assistant. Your task is to classify user queries into one of these agent categories:

**Available Agents:**
{agent_list_str}

**Instructions:**
- Analyze the query and determine which agent is most appropriate
- Output ONLY a JSON object with this exact structure:
{{"agent": "agent_name", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
- confidence should be 0.9+ for clear matches, 0.7-0.9 for likely matches, <0.7 for uncertain
- Do NOT include any other text, explanations, or markdown formatting

**Examples:**

Query: "show me critical bugs for R134"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "asking about critical bugs (JIRA)"}}

Query: "what's the IRR status?"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "IRR is a release milestone tracked in JIRA"}}

Query: "Is R135 green?"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "asking about release readiness status (green/yellow/red)"}}

Query: "why did build 123 fail?"
{{"agent": "jenkiollama", "confidence": 0.95, "reasoning": "asking about build failure (Jenkins)"}}

Query: "show me test failure analysis for backend pipeline"
{{"agent": "jenkiollama", "confidence": 0.95, "reasoning": "TFA (test failure analysis) is Jenkins feature"}}

Query: "how do I install your-company client?"
{{"agent": "documentation", "confidence": 0.95, "reasoning": "asking for installation instructions"}}

Query: "what is steering mode?"
{{"agent": "documentation", "confidence": 0.90, "reasoning": "asking for feature explanation"}}

Query: "list all pipelines"
{{"agent": "jenkiollama", "confidence": 0.95, "reasoning": "asking about Jenkins pipelines"}}

Query: "last 5 builds for your-product-test"
{{"agent": "jenkiollama", "confidence": 0.95, "reasoning": "asking for build history (Jenkins)"}}

Query: "when is branch cut?"
{{"agent": "release_readiness", "confidence": 0.90, "reasoning": "branch cut date in release calendar"}}

Query: "who is working on P0 bugs?"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "asking about bug assignees (JIRA)"}}

Query: "analyze PR #1234 for test impact"
{{"agent": "escalation_analysis", "confidence": 0.95, "reasoning": "PR analysis and test recommendations"}}

Query: "what tests should QA run for this change?"
{{"agent": "escalation_analysis", "confidence": 0.95, "reasoning": "test gap analysis and recommendations"}}

Query: "who is overloaded on the team?"
{{"agent": "dev_insights", "confidence": 0.95, "reasoning": "developer workload analysis"}}

Query: "show me the bus factor for R135"
{{"agent": "dev_insights", "confidence": 0.95, "reasoning": "knowledge risk and single points of failure"}}

Query: "what's the risk of missing IRR?"
{{"agent": "release_risk", "confidence": 0.95, "reasoning": "release risk prediction and milestone probability"}}

Query: "will we hit branch cut on time?"
{{"agent": "release_risk", "confidence": 0.95, "reasoning": "milestone timeline risk assessment"}}

Query: "what are the action items for R135?"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "asking about open action items (JIRA)"}}

Query: "who has the most open items for YOUR_PRODUCT?"
{{"agent": "release_readiness", "confidence": 0.95, "reasoning": "asking about open items by assignee for a component (JIRA)"}}

Query: "show me commits for R135"
{{"agent": "release_readiness", "confidence": 0.90, "reasoning": "code commits tracked via GitHub integration"}}

**Now classify this query:**

Query: "{query}"
"""

        return prompt

    def _parse_routing_response(self, response_text: str) -> Tuple[str, float, str]:
        """
        Parse LLM response to extract agent name, confidence, and reasoning.

        Args:
            response_text: Raw LLM response

        Returns:
            Tuple of (agent_name, confidence, reasoning)
        """
        try:
            # Clean response (remove markdown code blocks if present)
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                # Extract JSON from code block
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1)
                else:
                    # Try to find JSON between ```
                    cleaned = re.sub(r"```(?:json)?", "", cleaned).strip()

            # Parse JSON
            data = json.loads(cleaned)

            agent = data.get("agent", "release_readiness")
            confidence = float(data.get("confidence", 0.5))
            reasoning = data.get("reasoning", "no reasoning provided")

            # Validate agent name
            if agent not in self.agent_descriptions:
                logger.warning("[SemanticRouter] Invalid agent '%s', using default", agent)
                agent = "release_readiness"
                confidence = 0.5

            # Clamp confidence to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            return agent, confidence, reasoning

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("[SemanticRouter] Failed to parse response: %s. Response: %s", e, response_text)
            # Try to extract agent name from text as fallback
            agent_name = self._extract_agent_from_text(response_text)
            return agent_name, 0.5, "fallback parsing"

    def _extract_agent_from_text(self, text: str) -> str:
        """Fallback: extract agent name from free-form text."""
        text_lower = text.lower()

        # Look for agent names in response
        for agent_name in self.agent_descriptions.keys():
            if agent_name in text_lower:
                return agent_name

        # Check for keywords mapped to agents
        if any(word in text_lower for word in ["jenkins", "pipeline", "build", "ci/cd", "tfa"]):
            return "jenkiollama"
        elif any(word in text_lower for word in ["install", "configure", "how to", "documentation"]):
            return "documentation"
        elif any(word in text_lower for word in ["pr", "pull request", "test gap", "impact"]):
            return "escalation_analysis"
        elif any(word in text_lower for word in ["workload", "overload", "bus factor", "capacity"]):
            return "dev_insights"
        elif any(word in text_lower for word in ["risk", "probability", "forecast", "on track"]):
            return "release_risk"
        else:
            return "release_readiness"  # Default


def create_semantic_router(agents: Dict[str, Any]) -> SemanticRouter:
    """
    Factory function to create semantic router.

    Args:
        agents: Dictionary of agent name -> agent instance

    Returns:
        SemanticRouter instance
    """
    return SemanticRouter(agents)

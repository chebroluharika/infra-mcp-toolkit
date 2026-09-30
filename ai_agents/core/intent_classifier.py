"""
Intent Classifier (NLP-based, No LLM)
=====================================

Fast intent classification using sentence embeddings and cosine similarity.
No LLM call required - uses lightweight embedding model for instant routing.

Features:
- Uses API embeddings (nomic-embed-text) or SentenceTransformer
- Cosine similarity matching against example queries
- Sub-100ms routing decisions
- Fallback to keyword matching if embeddings unavailable

Usage:
    classifier = IntentClassifier()
    await classifier.initialize()

    intent, confidence = await classifier.classify("Is R135 green?")
    # Returns: ("release_readiness", 0.92)
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class IntentExample:
    """Example query for intent training."""

    query: str
    intent: str


# Training examples for each intent
INTENT_EXAMPLES: List[IntentExample] = [
    # ===== RELEASE READINESS =====
    # Release status queries
    IntentExample("Is R135 green?", "release_readiness"),
    IntentExample("Is R134 green?", "release_readiness"),
    IntentExample("is release R135 green", "release_readiness"),
    IntentExample("what is the release status", "release_readiness"),
    IntentExample("release readiness status", "release_readiness"),
    IntentExample("is the release ready", "release_readiness"),
    IntentExample("RRS score for R135", "release_readiness"),
    IntentExample("release readiness score", "release_readiness"),
    IntentExample("is R134 ready for release", "release_readiness"),
    IntentExample("release health check", "release_readiness"),
    # Bug/JIRA queries
    IntentExample("show critical bugs", "release_readiness"),
    IntentExample("list P0 bugs", "release_readiness"),
    IntentExample("critical issues for R135", "release_readiness"),
    IntentExample("how many blocker bugs", "release_readiness"),
    IntentExample("show me jira bugs", "release_readiness"),
    IntentExample("open bugs for this release", "release_readiness"),
    IntentExample("P1 bugs assigned to me", "release_readiness"),
    IntentExample("bugs in more info status", "release_readiness"),
    IntentExample("bugs needing info", "release_readiness"),
    IntentExample("moreinfo bugs", "release_readiness"),
    # Milestone/Calendar queries
    IntentExample("when is branch cut", "release_readiness"),
    IntentExample("when is IRR", "release_readiness"),
    IntentExample("what are the release dates", "release_readiness"),
    IntentExample("release calendar", "release_readiness"),
    IntentExample("milestone dates", "release_readiness"),
    IntentExample("when is final build", "release_readiness"),
    IntentExample("release schedule", "release_readiness"),
    # Milestone STATUS queries (completion, not dates)
    IntentExample("IRR status", "release_readiness"),
    IntentExample("what's the IRR status", "release_readiness"),
    IntentExample("how did IRR go", "release_readiness"),
    IntentExample("branch cut status", "release_readiness"),
    IntentExample("final build status", "release_readiness"),
    IntentExample("milestone status", "release_readiness"),
    IntentExample("are we ready for IRR", "release_readiness"),
    IntentExample("are we ready for branch cut", "release_readiness"),
    # Assignee/Action items
    IntentExample("who has most open items", "release_readiness"),
    IntentExample("who has the most open items for YOUR_PRODUCT", "release_readiness"),
    IntentExample("who has the most open items for YOUR_PRODUCT component", "release_readiness"),
    IntentExample("open items for YOUR_PRODUCT", "release_readiness"),
    IntentExample("YOUR_PRODUCT bugs", "release_readiness"),
    IntentExample("YOUR_PRODUCT component bugs", "release_readiness"),
    IntentExample("action items for YOUR_PRODUCT", "release_readiness"),
    IntentExample("action items by assignee", "release_readiness"),
    IntentExample("who is working on P0 bugs", "release_readiness"),
    IntentExample("bugs assigned to John", "release_readiness"),
    IntentExample("open items for R135", "release_readiness"),
    IntentExample("show escalations", "release_readiness"),
    IntentExample("EHF requests", "release_readiness"),
    # Commits/GitHub
    IntentExample("commits after branch cut", "release_readiness"),
    IntentExample("show commits for R135", "release_readiness"),
    IntentExample("code changes after freeze", "release_readiness"),
    IntentExample("github commits", "release_readiness"),
    # Stories
    IntentExample("show stories for R135", "release_readiness"),
    IntentExample("incomplete stories", "release_readiness"),
    IntentExample("story status", "release_readiness"),
    # ===== JENKINS =====
    # Pipeline queries
    IntentExample("show all pipelines", "jenkins"),
    IntentExample("list pipelines", "jenkins"),
    IntentExample("pipeline status", "jenkins"),
    IntentExample("CI/CD status", "jenkins"),
    IntentExample("jenkins pipelines", "jenkins"),
    IntentExample("what pipelines are failing", "jenkins"),
    # Build queries
    IntentExample("list builds for Backend Regression", "jenkins"),
    IntentExample("top 10 builds for your-product-test pipeline", "jenkins"),
    IntentExample("last 5 runs for backend pipeline", "jenkins"),
    IntentExample("build history", "jenkins"),
    IntentExample("recent builds", "jenkins"),
    IntentExample("show build 123", "jenkins"),
    IntentExample("build number 456 status", "jenkins"),
    # Test failure analysis
    IntentExample("why did build 123 fail", "jenkins"),
    IntentExample("test failure analysis", "jenkins"),
    IntentExample("TFA for build 456", "jenkins"),
    IntentExample("root cause analysis", "jenkins"),
    IntentExample("what tests failed", "jenkins"),
    IntentExample("failing tests in build", "jenkins"),
    # Golden Regression / PDV
    IntentExample("Endpoint PDV runs", "jenkins"),
    IntentExample("PDV status", "jenkins"),
    IntentExample("golden regression", "jenkins"),
    IntentExample("golden regression suite status", "jenkins"),
    IntentExample("PDV pipeline runs", "jenkins"),
    IntentExample("endpoint PDV builds", "jenkins"),
    IntentExample("show PDV runs by stack", "jenkins"),
    # ===== DOCUMENTATION =====
    IntentExample("how to install YourCompany Client", "documentation"),
    IntentExample("installation guide", "documentation"),
    IntentExample("configure your-company client", "documentation"),
    IntentExample("setup instructions", "documentation"),
    IntentExample("troubleshoot client", "documentation"),
    IntentExample("what is steering mode", "documentation"),
    IntentExample("supported operating systems", "documentation"),
    IntentExample("what OS are supported", "documentation"),
    IntentExample("system requirements", "documentation"),
    IntentExample("proxy configuration", "documentation"),
    IntentExample("VPN settings", "documentation"),
    IntentExample("client enrollment", "documentation"),
    IntentExample("uninstall your-company client", "documentation"),
    IntentExample("documentation for your-company", "documentation"),
    IntentExample("help with client setup", "documentation"),
]


class IntentClassifier:
    """
    Fast intent classification using embeddings.

    Uses cosine similarity between query embedding and example embeddings
    to determine intent. No LLM call required.
    """

    def __init__(
        self,
        embedding_model: str = "nomic-embed-text",
        embedding_url: str = None,
        similarity_threshold: float = 0.65,
    ):
        self.embedding_model = embedding_model
        self.embedding_url = embedding_url or os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434")
        self.similarity_threshold = similarity_threshold

        # State
        self._initialized = False
        self._example_embeddings: Optional[np.ndarray] = None
        self._example_intents: List[str] = []
        self._embedder = None

    async def initialize(self):
        """Initialize embeddings for all examples."""
        if self._initialized:
            return

        logger.info("Initializing intent classifier with %d examples...", len(INTENT_EXAMPLES))

        try:
            import httpx

            example_texts = [ex.query for ex in INTENT_EXAMPLES]
            self._example_intents = [ex.intent for ex in INTENT_EXAMPLES]

            embeddings = []
            async with httpx.AsyncClient(timeout=30, verify=False) as client:
                for text in example_texts:
                    response = await client.post(
                        f"{self.embedding_url}/api/embeddings", json={"model": self.embedding_model, "prompt": text}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        embeddings.append(data["embedding"])
                    else:
                        raise RuntimeError(f"Embedding failed: {response.status_code}")

            self._example_embeddings = np.array(embeddings)
            self._initialized = True
            logger.info("Intent classifier initialized with %d embeddings", len(embeddings))

        except Exception as e:
            logger.warning("Failed to initialize embeddings: %s. Using keyword fallback.", e)
            self._initialized = True  # Still mark as initialized, use fallback

    async def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a single text."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                response = await client.post(
                    f"{self.embedding_url}/api/embeddings", json={"model": self.embedding_model, "prompt": text}
                )
                if response.status_code == 200:
                    data = response.json()
                    return np.array(data["embedding"])
        except Exception as e:
            logger.warning("Embedding request failed: %s", e)
        return None

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)

    async def classify(self, query: str) -> Tuple[str, float]:
        """
        Classify query intent.

        Args:
            query: User query

        Returns:
            Tuple of (intent_name, confidence_score)
        """
        if not self._initialized:
            await self.initialize()

        # Try embedding-based classification
        if self._example_embeddings is not None:
            query_embedding = await self._get_embedding(query)

            if query_embedding is not None:
                # Compute similarities to all examples
                similarities = [self._cosine_similarity(query_embedding, ex_emb) for ex_emb in self._example_embeddings]

                # Get top matches
                top_indices = np.argsort(similarities)[::-1][:5]
                top_similarities = [similarities[i] for i in top_indices]
                top_intents = [self._example_intents[i] for i in top_indices]

                # Vote among top matches
                intent_scores: Dict[str, List[float]] = {}
                for intent, score in zip(top_intents, top_similarities):
                    if intent not in intent_scores:
                        intent_scores[intent] = []
                    intent_scores[intent].append(score)

                # Pick intent with highest average score
                best_intent = max(intent_scores.keys(), key=lambda i: np.mean(intent_scores[i]))
                confidence = float(np.mean(intent_scores[best_intent]))

                if confidence >= self.similarity_threshold:
                    logger.info("[IntentClassifier] '%s' → %s (confidence: %.2f)", query[:50], best_intent, confidence)
                    return best_intent, confidence

        # Fallback to keyword matching
        return self._keyword_fallback(query)

    def _keyword_fallback(self, query: str) -> Tuple[str, float]:
        """Keyword-based fallback classification."""
        query_lower = query.lower()

        # Jenkins keywords
        jenkins_keywords = [
            "jenkins",
            "pipeline",
            "build",
            "ci/cd",
            "tfa",
            "test failure",
            "root cause",
            "golden regression",
            "pdv",
            "endpoint pdv",
        ]
        jenkins_score = sum(1 for kw in jenkins_keywords if kw in query_lower)

        # Documentation keywords
        doc_keywords = [
            "install",
            "configure",
            "setup",
            "how to",
            "documentation",
            "troubleshoot",
            "what is",
            "supported os",
            "system requirements",
            "macos",
            "windows",
            "linux",
            "android",
            "ios",
            "chromeos",
            "version",
            "versions",
            "supported",
            "deployment",
            "deploy",
            "port",
            "ports",
            "network",
            "steering",
            "npa",
            "private access",
            "resource",
            "cpu",
            "memory",
            "battery",
            "utilization",
        ]
        doc_score = sum(1 for kw in doc_keywords if kw in query_lower)

        # Release readiness keywords
        release_keywords = [
            "release",
            "r134",
            "r135",
            "r136",
            "green",
            "red",
            "yellow",
            "bug",
            "jira",
            "critical",
            "blocker",
            "p0",
            "p1",
            "irr",
            "branch cut",
            "milestone",
            "calendar",
            "schedule",
            "commit",
            "assignee",
            "escalation",
            "ehf",
            "rrs",
            "more info",
            "moreinfo",
            "story",
            "stories",
        ]
        release_score = sum(1 for kw in release_keywords if kw in query_lower)

        # Special pattern for "is R### green"
        if re.search(r"is\s+r?\d{3}\s+(green|ready|red|yellow)", query_lower):
            release_score += 5  # Strong boost

        scores = {
            "jenkins": jenkins_score,
            "documentation": doc_score,
            "release_readiness": release_score,
        }

        best_intent = max(scores.keys(), key=lambda k: scores[k])
        max_score = scores[best_intent]

        # Normalize confidence
        if max_score > 0:
            confidence = min(0.9, 0.5 + (max_score * 0.1))
        else:
            # Default to release_readiness
            best_intent = "release_readiness"
            confidence = 0.5

        logger.info("[IntentClassifier] Keyword fallback: '%s' → %s (score: %d)", query[:50], best_intent, max_score)
        return best_intent, confidence


# Agent name mapping (classifier uses short names, router uses full names)
INTENT_TO_AGENT = {
    "release_readiness": "release_readiness",
    "jenkins": "jenkiollama",
    "documentation": "documentation",
}


class NLPRouter:
    """
    NLP-based router using IntentClassifier.

    Drop-in replacement for SemanticRouter but uses embeddings instead of LLM.
    """

    def __init__(self, agents: Dict[str, Any]):
        self.agents = agents
        self.classifier = IntentClassifier()
        self.name = "nlp_router"
        self._initialized = False

    async def _ensure_initialized(self):
        """Initialize classifier if needed."""
        if not self._initialized:
            await self.classifier.initialize()
            self._initialized = True

    def route(self, query: str) -> Any:
        """
        Synchronous route (for compatibility).
        Uses keyword fallback since we can't do async here.
        """
        intent, confidence = self.classifier._keyword_fallback(query)
        agent_name = INTENT_TO_AGENT.get(intent, "release_readiness")

        agent = self.agents.get(agent_name)
        if agent:
            return agent

        # Try alternate names
        for name in [intent, f"{intent}_agent"]:
            if name in self.agents:
                return self.agents[name]

        return list(self.agents.values())[0]

    async def route_async(self, query: str) -> Tuple[Any, float]:
        """
        Async route with confidence score.

        Returns:
            Tuple of (agent, confidence)
        """
        await self._ensure_initialized()

        intent, confidence = await self.classifier.classify(query)
        agent_name = INTENT_TO_AGENT.get(intent, "release_readiness")

        agent = self.agents.get(agent_name)
        if agent:
            return agent, confidence

        # Try alternate names
        for name in [intent, f"{intent}_agent"]:
            if name in self.agents:
                return self.agents[name], confidence

        # Default
        return list(self.agents.values())[0], 0.5

    def get_agent(self, name: str) -> Optional[Any]:
        """Get agent by name."""
        return self.agents.get(name)

    @property
    def agent_names(self) -> List[str]:
        """List of available agent names."""
        return list(self.agents.keys())

    @property
    def sub_agents(self) -> List[Any]:
        """List of sub-agents (for compatibility)."""
        return list(self.agents.values())


def create_nlp_router(agents: Dict[str, Any]) -> NLPRouter:
    """Factory function to create NLP router."""
    return NLPRouter(agents)

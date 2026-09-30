"""
Intent Classifier for JIRA Comments
====================================

Uses Ollama embeddings to semantically classify comments by intent.
Much faster than LLM calls - just embedding + cosine similarity.

Intents:
- passed: Test passed, completed successfully
- failed: Test failed, regression found
- blocked: Blocked by dependency, waiting
- in_progress: Currently testing, working on
- info: General status update, notes
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx
import numpy as np

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# Intent definitions with example phrases for embedding
INTENT_EXAMPLES = {
    "passed": [
        "All tests passed successfully",
        "Regression tests completed with 100% pass rate",
        "Test execution completed - all passed",
        "Verified and working correctly",
        "Testing done, no issues found",
        "✅ Passed all test cases",
        "Green build, all checks passed",
    ],
    "failed": [
        "Test failed due to regression",
        "Found critical bug during testing",
        "Failing test cases identified",
        "❌ Failed - needs investigation",
        "Regression detected in this build",
        "Test execution failed with errors",
        "Multiple test failures reported",
    ],
    "blocked": [
        "Blocked waiting for build",
        "Cannot proceed - dependency not ready",
        "Blocked by environment issue",
        "Waiting for fix from dev team",
        "On hold pending code changes",
        "Blocked - infrastructure down",
        "Cannot test - missing prerequisites",
    ],
    "in_progress": [
        "Currently running regression tests",
        "Testing in progress on this build",
        "Working on test execution",
        "Automation running, will update soon",
        "Started testing, partial results",
        "🔄 In progress - 50% complete",
        "Executing test suite now",
    ],
    "info": [
        "Updated test configuration",
        "Notes for reference",
        "Configuration changes applied",
        "General status update",
        "Documenting test approach",
    ],
}

# Dimension for nomic-embed-text model
EMBEDDING_DIM = 768


class IntentClassifier:
    """
    Fast intent classifier using embeddings.

    Pre-computes intent embeddings at startup, then classifies
    new text by finding the closest intent (cosine similarity).
    """

    def __init__(self):
        self.base_url = OLLAMA_BASE_URL
        self.model = EMBEDDING_MODEL
        self._intent_embeddings: Dict[str, np.ndarray] = {}
        self._initialized = False
        self._available = None

    async def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a single text from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=30, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                if response.status_code == 200:
                    data = response.json()
                    return np.array(data["embedding"], dtype=np.float32)
                else:
                    logger.warning("Embedding request failed: %s", response.status_code)
                    return None
        except Exception as e:
            logger.warning("Failed to get embedding: %s", e)
            return None

    async def is_available(self) -> bool:
        """Check if Ollama embedding model is available."""
        if self._available is not None:
            return self._available

        try:
            async with httpx.AsyncClient(timeout=5, verify=False) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    model_base = self.model.split(":")[0]
                    self._available = any(model_base in m for m in models)
                    if not self._available:
                        logger.info("Embedding model %s not found. Available: %s", self.model, models)
                    return self._available
                return False
        except Exception as e:
            logger.warning("Ollama not available for embeddings: %s", e)
            self._available = False
            return False

    async def initialize(self) -> bool:
        """
        Initialize by computing embeddings for all intent examples.

        Returns True if successful, False if Ollama not available.
        """
        if self._initialized:
            return True

        if not await self.is_available():
            logger.info("Intent classifier not available (Ollama embedding model not found)")
            return False

        logger.info("Initializing intent classifier with %s...", self.model)

        # Compute average embedding for each intent
        for intent, examples in INTENT_EXAMPLES.items():
            embeddings = []
            for example in examples:
                emb = await self._get_embedding(example)
                if emb is not None:
                    embeddings.append(emb)

            if embeddings:
                # Average embedding represents the intent
                self._intent_embeddings[intent] = np.mean(embeddings, axis=0)
                logger.debug("Computed embedding for intent '%s' from %d examples", intent, len(embeddings))

        self._initialized = len(self._intent_embeddings) > 0
        logger.info("Intent classifier initialized with %d intents", len(self._intent_embeddings))
        return self._initialized

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def classify(self, text: str) -> Tuple[str, float]:
        """
        Classify text into an intent.

        Args:
            text: The comment text to classify

        Returns:
            Tuple of (intent, confidence_score)
        """
        if not self._initialized:
            if not await self.initialize():
                return ("info", 0.0)

        # Get embedding for the input text
        text_embedding = await self._get_embedding(text)
        if text_embedding is None:
            return ("info", 0.0)

        # Find most similar intent
        best_intent = "info"
        best_score = 0.0

        for intent, intent_embedding in self._intent_embeddings.items():
            score = self._cosine_similarity(text_embedding, intent_embedding)
            if score > best_score:
                best_score = score
                best_intent = intent

        return (best_intent, best_score)

    async def classify_with_summary(self, text: str) -> Dict:
        """
        Classify text and extract a short summary.

        Returns dict with intent, confidence, and summary.
        """
        intent, confidence = await self.classify(text)

        # Extract first meaningful sentence as summary
        sentences = text.replace("\n", " ").split(". ")
        summary = ""
        for sentence in sentences:
            sentence = sentence.strip()
            # Skip very short sentences or headers
            if len(sentence) > 15 and not sentence.startswith(("#", "-", "*", "[")):
                summary = sentence[:150]  # Limit length
                if len(sentence) > 150:
                    summary += "..."
                break

        if not summary and text.strip():
            # Fallback: use first 100 chars
            summary = text.strip()[:100]
            if len(text.strip()) > 100:
                summary += "..."

        return {
            "intent": intent,
            "confidence": round(confidence, 3),
            "summary": summary,
        }

    async def classify_comments(self, comments: List[Dict]) -> Dict:
        """
        Classify multiple comments and aggregate results.

        Returns structured analysis with:
        - Overall intent (most recent/dominant)
        - Test results by status
        - Summary notes
        """
        if not comments:
            return {
                "intent": "info",
                "confidence": 0.0,
                "test_results": [],
                "summary_notes": [],
                "passed_count": 0,
                "failed_count": 0,
                "in_progress_count": 0,
                "blocked_count": 0,
            }

        results = []
        intent_counts = {"passed": 0, "failed": 0, "blocked": 0, "in_progress": 0, "info": 0}

        # Analyze each comment
        for comment in comments[:5]:  # Limit to 5 most recent
            body = comment.get("body", "")
            if not body.strip():
                continue

            # Classify the comment
            analysis = await self.classify_with_summary(body)
            intent = analysis["intent"]
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

            if analysis["summary"]:
                results.append(
                    {
                        "intent": intent,
                        "summary": analysis["summary"],
                        "confidence": analysis["confidence"],
                    }
                )

        # Determine overall intent (most recent meaningful one, or most common)
        # Priority: failed > blocked > in_progress > passed > info
        priority = ["failed", "blocked", "in_progress", "passed", "info"]
        overall_intent = "info"
        for p in priority:
            if intent_counts.get(p, 0) > 0:
                overall_intent = p
                break

        # Build test results from classified comments
        test_results = []
        summary_notes = []

        for r in results[:10]:
            if r["intent"] in ["passed", "failed", "in_progress", "blocked"]:
                test_results.append(
                    {
                        "status": r["intent"],
                        "item": r["summary"],
                    }
                )
            else:
                summary_notes.append(r["summary"])

        return {
            "intent": overall_intent,
            "confidence": results[0]["confidence"] if results else 0.0,
            "test_results": test_results,
            "summary_notes": summary_notes[:3],
            "passed_count": intent_counts["passed"],
            "failed_count": intent_counts["failed"],
            "in_progress_count": intent_counts["in_progress"],
            "blocked_count": intent_counts["blocked"],
        }


# Singleton instance
_classifier: Optional[IntentClassifier] = None


async def get_intent_classifier() -> IntentClassifier:
    """Get or create the intent classifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
        await _classifier.initialize()
    return _classifier


# Pattern-based fallback (fast, no Ollama needed)
def classify_by_pattern(text: str) -> Tuple[str, List[Dict]]:
    """
    Fast pattern-based classification as fallback.

    Returns (overall_intent, test_results_list)
    """
    test_results = []
    intent_counts = {"passed": 0, "failed": 0, "blocked": 0, "in_progress": 0}

    lines = text.split("\n")
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check for passed items
        if any(marker in line_stripped for marker in ["✅", "passed", "PASSED", "✔", "green", "success"]):
            test_results.append({"status": "passed", "item": line_stripped[:150]})
            intent_counts["passed"] += 1
        # Check for failed items
        elif any(marker in line_stripped for marker in ["❌", "failed", "FAILED", "✘", "red", "failure", "regression"]):
            test_results.append({"status": "failed", "item": line_stripped[:150]})
            intent_counts["failed"] += 1
        # Check for blocked items
        elif any(
            marker in line_stripped.lower()
            for marker in ["blocked", "waiting", "on hold", "dependency", "cannot proceed"]
        ):
            test_results.append({"status": "blocked", "item": line_stripped[:150]})
            intent_counts["blocked"] += 1
        # Check for in-progress items
        elif any(
            marker in line_stripped for marker in ["🔄", "in progress", "IN PROGRESS", "WIP", "running", "executing"]
        ):
            test_results.append({"status": "in_progress", "item": line_stripped[:150]})
            intent_counts["in_progress"] += 1

    # Determine overall intent by priority
    if intent_counts["failed"] > 0:
        overall = "failed"
    elif intent_counts["blocked"] > 0:
        overall = "blocked"
    elif intent_counts["in_progress"] > 0:
        overall = "in_progress"
    elif intent_counts["passed"] > 0:
        overall = "passed"
    else:
        overall = "info"

    return overall, test_results

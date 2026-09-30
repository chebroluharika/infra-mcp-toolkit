"""
Test Failure Analysis (TFA) Agent with RAG
===========================================

Uses Retrieval Augmented Generation with LLM for intelligent log analysis.
Uses Ollama Gateway for LLM inference and embeddings.
Features: Vector store with semantic embeddings, semantic search, root cause analysis.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from .ollama_mixin import OllamaMixin

logger = logging.getLogger(__name__)


@dataclass
class TestFailure:
    """Represents a test failure for storage and retrieval"""

    id: str
    job_name: str
    build_number: int
    test_name: str
    test_class: str
    error_message: str
    stack_trace: str
    console_snippet: str
    timestamp: str
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    resolved: bool = False


class TFAVectorStore:
    """
    Vector store for TFA using Ollama embeddings or fallback to simple hashing.

    Uses the shared embedding provider from core/embeddings.py which supports:
    - API embeddings (Ollama Gateway with qwen3-embedding)
    - Sentence Transformers (local fallback)
    - Simple word-frequency hashing (emergency fallback)
    """

    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self.failures: Dict[str, TestFailure] = {}
        self.embeddings: Dict[str, np.ndarray] = {}
        self._embedding_provider = None
        self._embedding_initialized = False
        self._use_api_embeddings = False
        self._load()

    def _init_embedding_provider(self):
        """Initialize embedding provider (lazy, called on first embed)."""
        if self._embedding_initialized:
            return

        self._embedding_initialized = True

        try:
            # Import shared embedding provider
            import sys

            ai_agents_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if ai_agents_dir not in sys.path:
                sys.path.insert(0, ai_agents_dir)

            from core.embeddings import get_embedding_provider

            # Try to get API embeddings (Ollama)
            embedding_url = os.getenv("EMBEDDING_BASE_URL", "")
            if embedding_url:
                self._embedding_provider = get_embedding_provider("api")
                self._use_api_embeddings = True
                logger.info("TFA using API embeddings: %s", embedding_url)
            else:
                # Try sentence-transformers as fallback
                try:
                    self._embedding_provider = get_embedding_provider("sentence-transformers")
                    self._use_api_embeddings = True
                    logger.info("TFA using sentence-transformers embeddings")
                except Exception:
                    logger.info("TFA using simple word-frequency embeddings (no API or sentence-transformers)")
                    self._use_api_embeddings = False
        except Exception as e:
            logger.warning("Failed to initialize embedding provider: %s. Using simple embeddings.", e)
            self._use_api_embeddings = False

    def _load(self):
        """Load knowledge base from disk"""
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                for item in data.get("failures", []):
                    item.setdefault("console_snippet", "")
                    failure = TestFailure(**item)
                    self.failures[failure.id] = failure

                # Load cached embeddings if available
                cached_embeddings = data.get("embeddings", {})
                for fid, emb in cached_embeddings.items():
                    if fid in self.failures:
                        self.embeddings[fid] = np.array(emb, dtype=np.float32)

            logger.info("Loaded %s failures (%s with cached embeddings)", len(self.failures), len(self.embeddings))
        except Exception as e:
            logger.error("Failed to load TFA knowledge base: %s", e)

    def _save(self):
        """Save knowledge base to disk"""
        try:
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)

            # Convert embeddings to lists for JSON serialization
            embeddings_json = {fid: emb.tolist() for fid, emb in self.embeddings.items()}

            with open(self.storage_path, "w") as f:
                json.dump(
                    {
                        "failures": [asdict(f) for f in self.failures.values()],
                        "embeddings": embeddings_json,
                        "updated_at": datetime.now().isoformat(),
                        "embedding_type": "api" if self._use_api_embeddings else "simple",
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error("Failed to save: %s", e)

    def _simple_embed(self, text: str) -> np.ndarray:
        """Fallback: simple word-frequency embedding (no API needed)."""
        words = [w for w in text.lower().split() if len(w) > 2]
        freq = {}
        for w in words:
            w = "".join(c for c in w if c.isalnum())
            freq[w] = freq.get(w, 0) + 1

        vec = np.zeros(256, dtype=np.float32)
        for w, c in freq.items():
            vec[hash(w) % 256] += c

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    async def _embed_async(self, text: str) -> np.ndarray:
        """Get embedding for text (async, uses API if available)."""
        self._init_embedding_provider()

        if self._use_api_embeddings and self._embedding_provider:
            try:
                return await self._embedding_provider.embed_query(text)
            except Exception as e:
                logger.warning("API embedding failed, using simple fallback: %s", e)
                return self._simple_embed(text)
        else:
            return self._simple_embed(text)

    def _embed_sync(self, text: str) -> np.ndarray:
        """Get embedding for text (sync wrapper)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, use thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(lambda: asyncio.run(self._embed_async(text)))
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(self._embed_async(text))
        except Exception:
            # Ultimate fallback
            return self._simple_embed(text)

    def _similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        na, nb = np.linalg.norm(v1), np.linalg.norm(v2)
        if na > 0 and nb > 0:
            return float(np.dot(v1, v2) / (na * nb))
        return 0.0

    async def add_async(self, failure: TestFailure):
        """Add failure to knowledge base (async)."""
        self.failures[failure.id] = failure
        text = f"{failure.test_name} {failure.error_message}"
        self.embeddings[failure.id] = await self._embed_async(text)
        self._save()

    def add(self, failure: TestFailure):
        """Add failure to knowledge base (sync)."""
        self.failures[failure.id] = failure
        text = f"{failure.test_name} {failure.error_message}"
        # Use simple embedding for sync add to avoid blocking
        self.embeddings[failure.id] = self._simple_embed(text)
        self._save()

    async def search_async(self, query: str, top_k: int = 5) -> List[tuple]:
        """Search for similar failures (async, uses API embeddings)."""
        if not self.failures:
            return []

        qe = await self._embed_async(query)

        # Re-embed any failures that don't have embeddings yet
        for fid, failure in self.failures.items():
            if fid not in self.embeddings:
                text = f"{failure.test_name} {failure.error_message}"
                self.embeddings[fid] = await self._embed_async(text)

        scores = [
            (self.failures[fid], self._similarity(qe, e)) for fid, e in self.embeddings.items() if fid in self.failures
        ]
        return sorted(scores, key=lambda x: x[1], reverse=True)[:top_k]

    def search(self, query: str, top_k: int = 5) -> List[tuple]:
        """Search for similar failures (sync)."""
        if not self.failures:
            return []

        qe = self._simple_embed(query)  # Use simple for sync search

        # Ensure all failures have embeddings
        for fid, failure in self.failures.items():
            if fid not in self.embeddings:
                text = f"{failure.test_name} {failure.error_message}"
                self.embeddings[fid] = self._simple_embed(text)

        scores = [
            (self.failures[fid], self._similarity(qe, e)) for fid, e in self.embeddings.items() if fid in self.failures
        ]
        return sorted(scores, key=lambda x: x[1], reverse=True)[:top_k]

    def update_resolution(self, fid: str, root_cause: str, resolution: str):
        """Update failure resolution"""
        if fid in self.failures:
            self.failures[fid].root_cause = root_cause
            self.failures[fid].resolution = resolution
            self.failures[fid].resolved = True
            self._save()

    @property
    def embedding_type(self) -> str:
        """Return the type of embeddings being used."""
        self._init_embedding_provider()
        if self._use_api_embeddings:
            return "api" if os.getenv("EMBEDDING_BASE_URL") else "sentence-transformers"
        return "simple"


# Keep backward compatibility alias
SimpleVectorStore = TFAVectorStore


TFA_SYSTEM_PROMPT = """You are a CI/CD log analyzer for YourCompany Client tests. Inspect the error message and traceback to identify the root cause.

IMPORTANT: Quote the EXACT error message verbatim from the input. Do not generalize.

Provide your analysis in EXACTLY this format:
Reason: <quote the EXACT error message and traceback verbatim from the log>
Fix: <suggested solution to fix this error>
Steps: <immediate next steps to resolve>

Example for IndexError:
Reason: IndexError: list index out of range
Fix: Add bounds checking before accessing list elements
Steps: 1. Check list length before indexing 2. Add try/except handling"""


# Use shared knowledge manager for documentation sources
from core.knowledge_manager import get_knowledge_manager


class TFAAgent(OllamaMixin):
    """Test Failure Analysis Agent using RAG with Ollama Gateway."""

    def __init__(self, knowledge_base_path: str = None):
        self._init_ollama()
        kb_path = knowledge_base_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "tfa_knowledge_base.json"
        )
        os.makedirs(os.path.dirname(kb_path), exist_ok=True)
        self.knowledge_base = TFAVectorStore(kb_path)

    def _extract_errors(self, log: str) -> Dict[str, List[str]]:
        """Extract error patterns from log (prioritized)"""
        patterns = {"assertions": [], "exceptions": [], "errors": [], "timeouts": []}
        ignore = ["insecurerequestwarning", "deprecationwarning", "unverified https"]

        for i, line in enumerate(log.split("\n")):
            ll = line.lower()
            if any(kw in ll for kw in ignore):
                continue

            if "assertionerror:" in ll or (line.startswith("E ") and "assert" in ll):
                patterns["assertions"].append(line[:500])
            elif any(f"{e}:" in ll for e in ["indexerror", "keyerror", "valueerror", "typeerror"]):
                patterns["exceptions"].append(line[:400])
            elif "timeout" in ll or "timed out" in ll:
                patterns["timeouts"].append(line[:300])
            elif "error:" in ll and "warning" not in ll:
                patterns["errors"].append(line[:400])

        # Deduplicate and limit
        for k in patterns:
            patterns[k] = list(dict.fromkeys(patterns[k]))[:5]
        return patterns

    async def _get_product_knowledge(self, job_name: str, test_name: str, error_message: str) -> Dict[str, Any]:
        """
        Retrieve documentation relevant to the failure.

        Uses KnowledgeManager to search all configured sources in knowledge_sources.yaml.
        To add new documentation sources, edit knowledge_sources.yaml.
        """
        product_context = {
            "docs": [],
            "confluence_docs": [],
        }

        try:
            km = get_knowledge_manager()

            # Build search query from failure context
            search_query = f"{job_name} {test_name} {error_message[:200]} troubleshooting"

            # Search all configured sources
            results = await km.search(search_query, max_results=5, agent="tfa")

            # Separate results by source type
            for doc in results:
                doc_entry = {
                    "title": doc.title,
                    "content": doc.content,
                    "url": doc.url,
                    "source": doc.source_name,
                }

                if doc.source_type == "confluence":
                    product_context["confluence_docs"].append(doc_entry)
                else:
                    product_context["docs"].append(doc_entry)

            if results:
                logger.info("Retrieved %d docs from %d sources", len(results), len(set(r.source_name for r in results)))

        except Exception as e:
            logger.debug("Could not retrieve product docs: %s", e)

        return product_context

    async def analyze_failure(
        self,
        job_name: str,
        build_number: int,
        test_name: str,
        test_class: str,
        error_message: str,
        stack_trace: str = "",
        console_output: str = "",
    ) -> Dict[str, Any]:
        """Analyze a test failure using RAG with semantic embeddings and product knowledge."""
        failure_id = hashlib.md5(f"{job_name}:{build_number}:{test_name}".encode()).hexdigest()

        # Get relevant documentation from configured sources
        product_context = await self._get_product_knowledge(job_name, test_name, error_message)

        # Search similar failures using semantic embeddings
        similar = await self.knowledge_base.search_async(f"{test_name} {error_message}", top_k=5)

        # LLM analysis is REQUIRED for pure RAG-based TFA
        llm = await self._get_ollama()
        if not llm:
            logger.error("LLM unavailable for TFA - cannot perform analysis")
            return {
                "job_name": job_name,
                "build_number": build_number,
                "test_name": test_name,
                "test_class": test_class,
                "error": "LLM service unavailable",
                "error_type": "llm_unavailable",
                "analysis": None,
                "product_context": product_context,
                "similar_failures": [
                    {
                        "test_name": f.test_name,
                        "similarity": round(s, 2),
                        "root_cause": f.root_cause,
                        "resolved": f.resolved,
                    }
                    for f, s in similar
                    if s > 0.3
                ],
                "failure_id": failure_id,
                "analysis_method": "error",
                "llm_backend": "unavailable",
                "llm_model": "none",
                "embedding_type": self.knowledge_base.embedding_type,
            }

        # Generate analysis with LLM + RAG context + product knowledge
        prompt = self._build_prompt(
            job_name, build_number, test_name, error_message, console_output, similar, product_context
        )
        response = await llm.generate(prompt, TFA_SYSTEM_PROMPT)

        if not response:
            logger.error("LLM returned empty response for TFA")
            return {
                "job_name": job_name,
                "build_number": build_number,
                "test_name": test_name,
                "test_class": test_class,
                "error": "LLM returned empty response",
                "error_type": "llm_error",
                "analysis": None,
                "similar_failures": [
                    {
                        "test_name": f.test_name,
                        "similarity": round(s, 2),
                        "root_cause": f.root_cause,
                        "resolved": f.resolved,
                    }
                    for f, s in similar
                    if s > 0.3
                ],
                "failure_id": failure_id,
                "analysis_method": "error",
                "llm_backend": self.llm_backend or "none",
                "llm_model": self.llm_model_name or "none",
                "embedding_type": self.knowledge_base.embedding_type,
            }

        analysis = self._parse_response(response, error_message)

        # Enhance recommendations with product-specific tips
        if product_context and product_context.get("troubleshooting_tips"):
            existing_recs = analysis.get("recommendations", [])
            product_tips = [f"[Product] {tip}" for tip in product_context["troubleshooting_tips"][:2]]
            analysis["recommendations"] = existing_recs + product_tips

        # Store failure with semantic embedding
        failure = TestFailure(
            id=failure_id,
            job_name=job_name,
            build_number=build_number,
            test_name=test_name,
            test_class=test_class,
            error_message=error_message[:1000],
            stack_trace=stack_trace[:2000],
            console_snippet=console_output[-1000:],
            timestamp=datetime.now().isoformat(),
            root_cause=analysis.get("root_cause"),
        )
        await self.knowledge_base.add_async(failure)

        return {
            "job_name": job_name,
            "build_number": build_number,
            "test_name": test_name,
            "test_class": test_class,
            "analysis": analysis,
            "product_context": product_context,
            "similar_failures": [
                {
                    "test_name": f.test_name,
                    "similarity": round(s, 2),
                    "root_cause": f.root_cause,
                    "resolved": f.resolved,
                }
                for f, s in similar
                if s > 0.3
            ],
            "failure_id": failure_id,
            "analysis_method": "llm_rag",
            "llm_backend": self.llm_backend,
            "llm_model": self.llm_model_name,
            "embedding_type": self.knowledge_base.embedding_type,
        }

    def _clean_error_message(self, error_message: str) -> str:
        """Clean error message by removing noise like HTML, base64 data, etc."""
        import re

        if not error_message:
            return ""

        # Remove base64 encoded data (fonts, images, etc.)
        # Pattern matches: base64,<long string of base64 chars>
        error_message = re.sub(r"base64,[A-Za-z0-9+/=]{100,}", "[base64 data removed]", error_message)

        # Remove inline CSS/style blocks
        error_message = re.sub(
            r"<style[^>]*>.*?</style>", "[style removed]", error_message, flags=re.DOTALL | re.IGNORECASE
        )

        # Remove HTML tags but keep content
        error_message = re.sub(r"<[^>]+>", " ", error_message)

        # Remove data URLs
        error_message = re.sub(r"url\(data:[^)]+\)", "[data url removed]", error_message)

        # Collapse multiple whitespace/newlines
        error_message = re.sub(r"\s+", " ", error_message)
        error_message = re.sub(r"\n{3,}", "\n\n", error_message)

        return error_message.strip()

    def _build_prompt(
        self, job_name, build_number, test_name, error_message, console, similar, product_context=None
    ) -> str:
        """Build prompt with documentation context"""
        # Extract error blocks from console output
        error_blocks = self._extract_errors(console)
        error_content = ""
        if error_blocks.get("exceptions"):
            error_content = "\n".join(error_blocks["exceptions"][:3])
        elif error_blocks.get("errors"):
            error_content = "\n".join(error_blocks["errors"][:3])

        # Clean error message (remove HTML, base64, etc.)
        error_message_clean = self._clean_error_message(error_message)

        # Truncate error message to avoid exceeding LLM context window
        # Keep first 1500 chars (most relevant) + last 500 chars (often contains root cause)
        if len(error_message_clean) > 2000:
            error_message_truncated = error_message_clean[:1500] + "\n...[truncated]...\n" + error_message_clean[-500:]
        else:
            error_message_truncated = error_message_clean

        prompt = f"Test: {test_name}\n" f"Error Message: {error_message_truncated}\n\n"

        if error_content:
            prompt += f"Additional Error Context:\n{error_content[:1000]}\n\n"

        # Add documentation context from configured sources
        has_docs = False
        if product_context:
            # Add Confluence docs (internal wiki) - highest priority
            confluence_docs = product_context.get("confluence_docs", [])
            if confluence_docs:
                has_docs = True
                prompt += "Relevant Documentation (from Confluence):\n"
                for doc in confluence_docs[:2]:
                    prompt += f"### {doc.get('title', 'Untitled')}\n"
                    prompt += f"{doc.get('content', '')[:400]}\n"
                    if doc.get("url"):
                        prompt += f"Source: {doc.get('url')}\n"
                    prompt += "\n"

            # Add public documentation snippets
            docs = product_context.get("docs", [])
            if docs:
                has_docs = True
                prompt += "Public Documentation:\n"
                for doc in docs[:2]:
                    prompt += f"- {doc.get('title', '')}: {doc.get('content', '')[:200]}...\n"
                prompt += "\n"

        prompt += (
            "Identify the root cause of the failure. "
            "Quote the EXACT error message verbatim. "
            "Do not generalize - use the exact error shown above.\n"
        )

        if has_docs:
            prompt += "Use the documentation above to suggest relevant fixes.\n"

        prompt += (
            "\nProvide your analysis in this format:\n"
            "Reason: <exact error message>\n"
            "Fix: <suggested solution>\n"
            "Steps: <next steps>"
        )
        return prompt

    def _parse_response(self, response: str, original_error: str = "") -> Dict[str, Any]:
        """Parse LLM response in Reason/Fix/Steps format (CICD-Analysis style)"""
        text = response.strip() if response else ""

        # Extract Reason/Fix/Steps using regex (matching reference implementation)
        reason_match = re.search(r"Reason\s*:\s*(.*?)(?=\nFix\s*:|$)", text, re.IGNORECASE | re.DOTALL)
        fix_match = re.search(r"Fix\s*:\s*(.*?)(?=\nSteps\s*:|$)", text, re.IGNORECASE | re.DOTALL)
        steps_match = re.search(r"Steps\s*:\s*(.*?)(?=$)", text, re.IGNORECASE | re.DOTALL)

        reason = reason_match.group(1).strip() if reason_match else ""
        fix = fix_match.group(1).strip() if fix_match else ""
        steps = steps_match.group(1).strip() if steps_match else ""

        # Use original error if reason is empty or looks invalid
        if not reason or len(reason) < 5 or "|" in reason:
            reason = original_error if original_error else "Analysis incomplete"

        # Determine category from reason
        category = self._categorize_error(reason)

        # Build recommendations from fix and steps - parse into individual points
        recommendations = self._parse_recommendations(fix, steps)
        if not recommendations:
            recommendations = ["Review error details", "Check recent code changes"]

        return {
            "root_cause": reason,
            "category": category,
            "severity": "high" if category in ["connection", "resource", "server_error"] else "medium",
            "recommendations": recommendations,
            "confidence": "high" if reason_match else "low",
            "raw_analysis": text,
        }

    def _parse_recommendations(self, fix: str, steps: str) -> List[str]:
        """Parse fix and steps into clean individual recommendation points"""
        recommendations = []

        # Combine fix and steps
        combined = f"{fix}\n{steps}".strip()
        if not combined:
            return recommendations

        # First, normalize the text - add newlines before numbered items that are inline
        # This handles cases like "... 1. **Text** 2. **Text2**..." on same line
        combined = re.sub(r"(?<=[.!?\s])\s*(\d+)\.\s*\*\*", r"\n\1. **", combined)
        combined = re.sub(r"(?<=[.!?\s])\s*(\d+)\.\s+", r"\n\1. ", combined)

        # Split by common delimiters: numbered lists, bullet points, newlines
        # Pattern matches: 1. or 1) or - or * or newlines
        lines = re.split(r"\n+|\s*(?:^|\s)\d+\.\s*|\s*\d+\)\s*|\s*[-*•]\s+", combined)

        for line in lines:
            # Clean up the line
            line = line.strip()
            # Remove markdown bold markers (both ** and *)
            line = re.sub(r"\*\*([^*]+)\*\*:?\s*", r"\1: ", line)  # **Bold**: -> Bold:
            line = re.sub(r"\*([^*]+)\*", r"\1", line)  # *italic* -> italic
            # Clean up double colons and extra spaces
            line = re.sub(r":+\s*", ": ", line).strip()
            line = re.sub(r"\s+", " ", line)
            # Remove leading/trailing punctuation artifacts
            line = line.strip(".:;,")

            # Skip empty or too short lines
            if not line or len(line) < 5:
                continue

            # Skip lines that are just headers
            if line.lower() in ["fix", "steps", "recommendation", "recommendations"]:
                continue

            # Capitalize first letter if needed
            if line[0].islower():
                line = line[0].upper() + line[1:]

            # Ensure it ends properly
            if not line.endswith((".", "!", "?")):
                line = line + "."

            recommendations.append(line)

        # Deduplicate while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            rec_lower = rec.lower()
            if rec_lower not in seen:
                seen.add(rec_lower)
                unique_recommendations.append(rec)

        return unique_recommendations[:8]  # Limit to 8 recommendations

    def _categorize_error(self, error_text: str) -> str:
        """Categorize error based on error text"""
        error_lower = error_text.lower()
        categories = {
            "indexerror": "index_error",
            "keyerror": "key_error",
            "typeerror": "type_error",
            "valueerror": "value_error",
            "attributeerror": "attribute_error",
            "assertionerror": "assertion",
            "timeout": "timeout",
            "connection": "connection",
            "401": "authentication",
            "403": "authorization",
            "404": "not_found",
            "500": "server_error",
        }
        for keyword, category in categories.items():
            if keyword in error_lower:
                return category
        return "unknown"

    async def analyze_build_error(
        self,
        job_name: str,
        build_number: int,
        console_output: str,
        error_lines: List[str],
        commits: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a build error (for Dev pipelines) using LLM.

        Unlike test failure analysis, this focuses on:
        - Console error messages
        - Build/compilation errors
        - Code changes that may have caused the failure
        """
        commits = commits or []

        # Build context for analysis
        commit_summary = ""
        if commits:
            commit_summary = f"\n\nRecent commits ({len(commits)}):\n"
            for c in commits[:5]:
                commit_summary += (
                    f"- {c.get('id', '')[:7]}: {c.get('message', '')[:100]} by {c.get('author', 'unknown')}\n"
                )
                files = c.get("files", [])[:5]
                if files:
                    commit_summary += f"  Files: {', '.join(files)}\n"

        # Extract key errors from console
        error_context = "\n".join(error_lines[:15]) if error_lines else ""

        # LLM analysis is REQUIRED for pure RAG-based TFA
        llm = await self._get_ollama()

        if not llm:
            logger.error("LLM unavailable for build error analysis")
            return {
                "error": "LLM service unavailable",
                "error_type": "llm_unavailable",
                "analysis_type": "error",
                "root_cause": None,
                "category": "build_error",
                "severity": "unknown",
                "recommendations": ["LLM service is unavailable. Please check Ollama Gateway configuration."],
                "confidence": "none",
                "llm_backend": "unavailable",
                "llm_model": "none",
            }

        if not (error_lines or commits):
            return {
                "error": "No error context available",
                "error_type": "no_context",
                "analysis_type": "error",
                "root_cause": "Build failed but no error details available",
                "category": "build_error",
                "severity": "unknown",
                "recommendations": ["Check Jenkins console output for error details"],
                "confidence": "none",
                "llm_backend": self.llm_backend,
                "llm_model": self.llm_model_name,
            }

        prompt = self._build_build_error_prompt(job_name, build_number, error_context, commit_summary)
        system_prompt = """You are a CI/CD build failure analyzer. Analyze the build errors and recent commits to identify the root cause.

IMPORTANT RULES:
- Be specific and actionable
- Quote exact error messages when possible
- DO NOT use markdown formatting (no ** or * or `)
- Each point should be on its own line
- Keep recommendations concise (one sentence each)

Provide your analysis in EXACTLY this format:
Reason: <one clear sentence about what caused the build to fail>
Fix: <the primary solution in one sentence>
Steps:
1. <first action>
2. <second action>
3. <third action>

Focus on:
- Compilation/build errors
- Dependency issues
- Configuration problems
- Code changes that may have broken the build"""

        response = await llm.generate(prompt, system_prompt)

        if not response:
            logger.error("LLM returned empty response for build error analysis")
            return {
                "error": "LLM returned empty response",
                "error_type": "llm_error",
                "analysis_type": "error",
                "root_cause": None,
                "category": "build_error",
                "severity": "unknown",
                "recommendations": ["LLM analysis failed. Please retry or check Ollama Gateway."],
                "confidence": "none",
                "llm_backend": self.llm_backend,
                "llm_model": self.llm_model_name,
            }

        analysis = self._parse_response(response, error_lines[0] if error_lines else "Build failed")
        return {
            "analysis_type": "llm_build_analysis",
            "root_cause": analysis.get("root_cause", "Build failure detected"),
            "category": analysis.get("category", "build_error"),
            "severity": "high",
            "recommendations": analysis.get("recommendations", []),
            "confidence": analysis.get("confidence", "medium"),
            "raw_analysis": analysis.get("raw_analysis", ""),
            "llm_backend": self.llm_backend,
            "llm_model": self.llm_model_name,
        }

    def _build_build_error_prompt(
        self, job_name: str, build_number: int, error_context: str, commit_summary: str
    ) -> str:
        """Build prompt for build error analysis"""
        prompt = f"Build: {job_name} #{build_number}\n\n"

        if error_context:
            prompt += f"Error messages from console:\n```\n{error_context}\n```\n"

        if commit_summary:
            prompt += commit_summary

        prompt += "\nAnalyze this build failure. What is the root cause and how can it be fixed?"
        return prompt

    def get_statistics(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        failures = list(self.knowledge_base.failures.values())
        resolved = [f for f in failures if f.resolved]
        return {
            "total_failures": len(failures),
            "resolved_failures": len(resolved),
            "resolution_rate": round(len(resolved) / len(failures) * 100, 1) if failures else 0,
            "embedding_type": self.knowledge_base.embedding_type,
            "llm_backend": self.llm_backend or "none",
            "llm_model": self.llm_model_name or "pattern_only",
        }


# Singleton
_tfa_agent: Optional[TFAAgent] = None


def get_tfa_agent() -> TFAAgent:
    """Get TFA agent singleton"""
    global _tfa_agent
    if _tfa_agent is None:
        _tfa_agent = TFAAgent()
    return _tfa_agent

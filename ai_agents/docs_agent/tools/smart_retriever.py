"""
Smart Retriever
================

Implements intelligent retrieval using:
1. Query Rewriting - Optimize queries for retrieval
2. Title-based Matching - Prioritize pages with matching titles
3. Hybrid Search - Combine semantic + keyword search
4. Self-Correction - Re-query if results are insufficient

Based on Agentic RAG best practices.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from .embeddings import get_embedding_provider
from .vector_store import FAISSVectorStore, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result from smart retrieval."""

    chunks: List[SearchResult]
    query_used: str
    retrieval_method: str
    confidence: float


class SmartRetriever:
    """
    Intelligent document retriever with query understanding.

    Features:
    - Query rewriting for better retrieval
    - Title-based page matching
    - Hybrid search (semantic + BM25)
    - Automatic fallback strategies
    """

    def __init__(
        self,
        embedding_provider: str = "sentence-transformers",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self._embedder = None
        self._store = None
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._initialized = False

        # Query patterns for specific topics
        self._topic_patterns = {
            "supported_os": [
                r"(what|which).*(supported|support).*(os|operating|platform)",
                r"(supported|support).*(os|operating|platform)",
                r"(os|operating|platform).*(support|supported|requirement)",
                r"(windows|macos|linux|android|ios).*(support|version)",
            ],
            "install": [
                r"(how|steps?).*(install|setup|deploy)",
                r"install.*(client|your-company)",
            ],
            "configure": [
                r"(how|steps?).*(configure|config|setting)",
                r"(configure|configuration).*(client|your-company)",
            ],
            "troubleshoot": [
                r"(troubleshoot|debug|fix|issue|problem|error)",
            ],
        }

        # Topic to page title mapping
        self._topic_to_title = {
            "supported_os": "YourCompany Client Supported OS and Platform",
            "install": "YourCompany Client Deployment Options",
            "configure": "YourCompany Client Configuration",
            "troubleshoot": "YourCompany Client Troubleshooting Guide",
        }

    async def initialize(self):
        """Initialize embedder and vector store."""
        if self._initialized:
            return

        self._embedder = get_embedding_provider(
            self._embedding_provider,
            self._embedding_model,
        )

        self._store = FAISSVectorStore(dimension=self._embedder.dimension)
        self._store.load()

        self._initialized = True
        logger.info("SmartRetriever initialized with %d documents", self._store.size)

    def _detect_topic(self, query: str) -> Optional[str]:
        """Detect the topic of the query using pattern matching."""
        query_lower = query.lower()

        for topic, patterns in self._topic_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return topic

        return None

    def _rewrite_query(self, query: str, topic: Optional[str] = None) -> str:
        """Rewrite query for better retrieval."""
        # Add topic-specific keywords
        if topic == "supported_os":
            return f"YourCompany Client supported operating systems platforms Windows macOS Linux Android iOS versions {query}"
        elif topic == "install":
            return f"YourCompany Client installation deployment steps {query}"
        elif topic == "configure":
            return f"YourCompany Client configuration settings setup {query}"
        elif topic == "troubleshoot":
            return f"YourCompany Client troubleshooting debug fix {query}"

        return query

    async def _get_chunks_by_title(self, title_substring: str, max_chunks: int = 3) -> List[SearchResult]:
        """Get chunks from pages matching a title substring."""
        matching_chunks = []

        for chunk_id, meta in self._store._metadata.items():
            source_title = meta.get("source_title", "").lower()
            if title_substring.lower() in source_title:
                # Create SearchResult from metadata
                result = SearchResult(
                    chunk_id=chunk_id,
                    content=meta.get("content", ""),
                    source_url=meta.get("source_url", ""),
                    source_title=meta.get("source_title", ""),
                    heading=meta.get("heading"),
                    score=1.0,  # High score for direct match
                    chunk_index=meta.get("chunk_index", 0),
                )
                matching_chunks.append(result)

        # Sort by chunk_index (prefer earlier chunks) and limit
        matching_chunks.sort(key=lambda x: x.chunk_index)
        return matching_chunks[:max_chunks]

    async def _semantic_search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """Perform semantic search."""
        query_embedding = await self._embedder.embed_query(query)
        return await self._store.search(query_embedding, top_k=top_k)

    async def _hybrid_search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """Perform hybrid search (semantic + BM25)."""
        query_embedding = await self._embedder.embed_query(query)
        return await self._store.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            semantic_weight=0.3,
            keyword_weight=0.7,
        )

    def _validate_results(self, results: List[SearchResult], topic: Optional[str]) -> bool:
        """Check if results are relevant to the topic."""
        if not results:
            return False

        if topic == "supported_os":
            # Check if any result mentions OS versions
            os_keywords = ["windows", "macos", "linux", "android", "ios", "ubuntu"]
            for r in results[:3]:
                content_lower = r.content.lower()
                matches = sum(1 for kw in os_keywords if kw in content_lower)
                if matches >= 2:
                    return True
            return False

        return True

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> RetrievalResult:
        """
        Retrieve relevant documents using smart strategies.

        Strategy:
        1. Detect topic from query
        2. If topic detected, try title-based retrieval first
        3. Fall back to hybrid search with query rewriting
        4. Validate results and retry if needed
        """
        await self.initialize()

        # Step 1: Detect topic
        topic = self._detect_topic(query)
        logger.info("Query: %s, Detected topic: %s", query[:50], topic)

        # Step 2: Try title-based retrieval for known topics
        if topic and topic in self._topic_to_title:
            title = self._topic_to_title[topic]
            chunks = await self._get_chunks_by_title(title, max_chunks=top_k)

            if chunks and self._validate_results(chunks, topic):
                logger.info("Title-based retrieval successful: %d chunks", len(chunks))
                return RetrievalResult(
                    chunks=chunks,
                    query_used=f"title:{title}",
                    retrieval_method="title_match",
                    confidence=0.95,
                )

        # Step 3: Hybrid search with query rewriting
        rewritten_query = self._rewrite_query(query, topic)
        results = await self._hybrid_search(rewritten_query, top_k=top_k * 2)

        # Apply topic-specific boosting
        if topic:
            target_title = self._topic_to_title.get(topic, "").lower()
            for r in results:
                title_lower = r.source_title.lower()

                # Boost matching titles
                if target_title and target_title in title_lower:
                    r.score += 0.5
                    if r.chunk_index == 0:
                        r.score += 0.3

                # Penalize Golden Release pages for non-release queries
                if "golden release" in title_lower and topic != "release":
                    r.score -= 0.3

            results.sort(key=lambda x: x.score, reverse=True)

        results = results[:top_k]

        if self._validate_results(results, topic):
            return RetrievalResult(
                chunks=results,
                query_used=rewritten_query,
                retrieval_method="hybrid_search",
                confidence=0.8,
            )

        # Step 4: Fallback to pure semantic search
        results = await self._semantic_search(query, top_k=top_k)

        return RetrievalResult(
            chunks=results,
            query_used=query,
            retrieval_method="semantic_fallback",
            confidence=0.5,
        )


# Singleton instance
_retriever: Optional[SmartRetriever] = None


async def get_smart_retriever() -> SmartRetriever:
    """Get or create smart retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = SmartRetriever()
        await _retriever.initialize()
    return _retriever

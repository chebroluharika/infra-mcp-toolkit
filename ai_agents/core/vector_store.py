"""
Shared FAISS Vector Store
=========================

FAISS-based vector store for similarity search across all agents.

Features:
- Efficient cosine similarity search
- Hybrid search (BM25 + semantic)
- Index persistence (save/load)
- Flexible metadata storage (works for docs, code, test cases, failures)

Used by:
- docs_agent: document chunk retrieval
- github_agent: code context retrieval
- testrail_agent: test case matching
- tfa_agent: test failure similarity

Usage:
    from core.vector_store import FAISSVectorStore, SearchResult

    store = FAISSVectorStore(dimension=2560, index_path="/path/to/index")
    await store.add_documents(chunks, embeddings)
    results = await store.search(query_embedding, top_k=10)
"""

import logging
import math
import os
import pickle
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Try to import FAISS
try:
    import faiss

    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    logger.warning("FAISS not installed. Install with: pip install faiss-cpu")


@dataclass
class SearchResult:
    """
    A single search result from FAISS.

    Core fields are always present. Additional metadata is stored in `metadata` dict
    for flexibility across different use cases (docs, code, test cases, etc).
    """

    chunk_id: str
    content: str
    score: float
    # Common optional fields (backward compatible with docs_agent)
    source_url: str = ""
    source_title: str = ""
    heading: Optional[str] = None
    chunk_index: int = 0
    # Flexible metadata for any additional fields
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": self.score,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
        }
        result.update(self.metadata)
        return result


class FAISSVectorStore:
    """
    FAISS-based vector store with flexible metadata.

    Uses FAISS IndexFlatIP (Inner Product) for cosine similarity search.
    Metadata is stored in a pickle alongside the FAISS index.

    The metadata schema is flexible — each use case can store different fields:
    - docs_agent: source_url, source_title, heading, chunk_index
    - github_agent: file_path, function_name, docstring, imports
    - testrail_agent: case_id, title, description, run_name, run_id
    - tfa_agent: job_name, test_name, error_message, root_cause
    """

    def __init__(
        self,
        dimension: int = 2560,
        index_path: str = None,
    ):
        if not HAS_FAISS:
            raise RuntimeError("FAISS not installed. Run: pip install faiss-cpu")

        self.dimension = dimension
        self.index_path = index_path or os.path.join(os.path.dirname(__file__), "..", "data", "faiss_index")

        # FAISS index
        self._index: Optional[faiss.Index] = None

        # Metadata storage (chunk_id -> full metadata dict)
        self._metadata: Dict[str, Dict[str, Any]] = {}

        # ID to index mapping
        self._id_to_idx: Dict[str, int] = {}
        self._idx_to_id: Dict[int, str] = {}

        # Ensure directory exists
        os.makedirs(self.index_path, exist_ok=True)

    def _create_index(self):
        """Create a new FAISS index."""
        self._index = faiss.IndexFlatIP(self.dimension)
        logger.info("Created FAISS index with dimension %s", self.dimension)

    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize vectors for cosine similarity."""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return vectors / norms

    async def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
    ):
        """
        Add chunks with their embeddings to the index.

        Args:
            chunks: List of dicts. Required: 'chunk_id', 'content'.
                    All other fields are stored as metadata.
            embeddings: Numpy array of shape (n_chunks, dimension)
        """
        if self._index is None:
            self.dimension = embeddings.shape[1]
            self._create_index()

        normalized = self._normalize_vectors(embeddings)

        start_idx = self._index.ntotal
        self._index.add(normalized)

        for i, chunk in enumerate(chunks):
            idx = start_idx + i
            chunk_id = chunk.get("chunk_id", str(idx))

            self._id_to_idx[chunk_id] = idx
            self._idx_to_id[idx] = chunk_id

            # Store ALL fields as metadata (flexible schema)
            self._metadata[chunk_id] = {**chunk}

        logger.info("Added %d chunks to index (total: %d)", len(chunks), self._index.ntotal)

    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """
        Search for similar documents by embedding.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return

        Returns:
            List of SearchResult objects sorted by score descending
        """
        if self._index is None or self._index.ntotal == 0:
            logger.warning("Index is empty")
            return []

        query = query_embedding.reshape(1, -1)
        query = self._normalize_vectors(query)

        scores, indices = self._index.search(query, min(top_k, self._index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue

            chunk_id = self._idx_to_id.get(idx)
            if chunk_id is None:
                continue

            meta = self._metadata.get(chunk_id, {})

            # Extract known fields, put rest in metadata
            extra_meta = {
                k: v
                for k, v in meta.items()
                if k
                not in (
                    "chunk_id",
                    "content",
                    "source_url",
                    "source_title",
                    "heading",
                    "chunk_index",
                )
            }

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    content=meta.get("content", ""),
                    source_url=meta.get("source_url", ""),
                    source_title=meta.get("source_title", ""),
                    heading=meta.get("heading"),
                    score=float(score),
                    chunk_index=meta.get("chunk_index", 0),
                    metadata=extra_meta,
                )
            )

        return results

    async def search_with_filter(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        filter_fn=None,
    ) -> List[SearchResult]:
        """
        Search with a metadata filter function.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            filter_fn: Optional function(metadata_dict) -> bool to filter results

        Returns:
            Filtered list of SearchResult objects
        """
        # Over-fetch to account for filtering
        candidates = await self.search(query_embedding, top_k=top_k * 3)

        if filter_fn is None:
            return candidates[:top_k]

        filtered = []
        for result in candidates:
            full_meta = self._metadata.get(result.chunk_id, {})
            if filter_fn(full_meta):
                filtered.append(result)
                if len(filtered) >= top_k:
                    break

        return filtered

    def save(self):
        """Save index and metadata to disk."""
        if self._index is None:
            logger.warning("No index to save")
            return

        index_file = os.path.join(self.index_path, "index.faiss")
        faiss.write_index(self._index, index_file)

        metadata_file = os.path.join(self.index_path, "metadata.pkl")
        with open(metadata_file, "wb") as f:
            pickle.dump(
                {
                    "metadata": self._metadata,
                    "id_to_idx": self._id_to_idx,
                    "idx_to_id": self._idx_to_id,
                    "dimension": self.dimension,
                },
                f,
            )

        logger.info("Saved index to %s (%d vectors)", self.index_path, self._index.ntotal)

    def load(self) -> bool:
        """Load index and metadata from disk."""
        index_file = os.path.join(self.index_path, "index.faiss")
        metadata_file = os.path.join(self.index_path, "metadata.pkl")

        if not os.path.exists(index_file) or not os.path.exists(metadata_file):
            logger.warning("No saved index found at %s", self.index_path)
            return False

        try:
            self._index = faiss.read_index(index_file)

            with open(metadata_file, "rb") as f:
                data = pickle.load(f)
                self._metadata = data["metadata"]
                self._id_to_idx = data["id_to_idx"]
                self._idx_to_id = data["idx_to_id"]
                self.dimension = data["dimension"]

            logger.info(
                "Loaded index from %s (%d vectors)",
                self.index_path,
                self._index.ntotal,
            )
            return True

        except Exception as e:
            logger.error("Error loading index: %s", e)
            return False

    def clear(self):
        """Clear the index and all metadata."""
        self._index = None
        self._metadata = {}
        self._id_to_idx = {}
        self._idx_to_id = {}
        logger.info("Cleared index")

    @property
    def size(self) -> int:
        """Return number of vectors in index."""
        return self._index.ntotal if self._index else 0

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            "total_vectors": self.size,
            "dimension": self.dimension,
            "unique_sources": len(set(m.get("source_url", "") for m in self._metadata.values())),
            "index_path": self.index_path,
        }

    def get_metadata(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Get full metadata for a specific chunk."""
        return self._metadata.get(chunk_id)

    # =========================================================================
    # BM25 Hybrid Search
    # =========================================================================

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        text = text.lower()
        tokens = re.findall(r"\b[a-z0-9]+\b", text)
        return [t for t in tokens if len(t) > 1]

    def _compute_bm25_score(
        self,
        query_tokens: List[str],
        doc_tokens: List[str],
        avg_doc_len: float,
        doc_freqs: Dict[str, int],
        total_docs: int,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> float:
        """Compute BM25 score for a document."""
        score = 0.0
        doc_len = len(doc_tokens)
        doc_counter = Counter(doc_tokens)

        for term in query_tokens:
            if term not in doc_counter:
                continue

            tf = doc_counter[term]
            df = doc_freqs.get(term, 0)

            if df == 0:
                continue

            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))

            score += idf * tf_norm

        return score

    async def hybrid_search(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int = 5,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> List[SearchResult]:
        """
        Hybrid search combining semantic (embedding) and keyword (BM25) search.

        Args:
            query: Original query text
            query_embedding: Query embedding vector
            top_k: Number of results to return
            semantic_weight: Weight for semantic similarity (0-1)
            keyword_weight: Weight for BM25 keyword matching (0-1)

        Returns:
            List of SearchResult objects with combined scores
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        semantic_results = await self.search(query_embedding, top_k=min(100, self.size))

        if not semantic_results:
            return []

        query_tokens = self._tokenize(query)

        # Build document frequency map
        all_doc_tokens = {}
        doc_freqs = Counter()

        for chunk_id, meta in self._metadata.items():
            content = meta.get("content", "") + " " + meta.get("source_title", "")
            tokens = self._tokenize(content)
            all_doc_tokens[chunk_id] = tokens
            doc_freqs.update(set(tokens))

        total_docs = len(self._metadata)
        avg_doc_len = sum(len(t) for t in all_doc_tokens.values()) / max(total_docs, 1)

        # Normalize semantic scores
        max_semantic = max(r.score for r in semantic_results)
        min_semantic = min(r.score for r in semantic_results)
        semantic_range = max_semantic - min_semantic if max_semantic != min_semantic else 1

        bm25_scores = {}
        for result in semantic_results:
            doc_tokens = all_doc_tokens.get(result.chunk_id, [])
            bm25_scores[result.chunk_id] = self._compute_bm25_score(
                query_tokens, doc_tokens, avg_doc_len, doc_freqs, total_docs
            )

        max_bm25 = max(bm25_scores.values()) if bm25_scores else 1
        min_bm25 = min(bm25_scores.values()) if bm25_scores else 0
        bm25_range = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1

        combined_results = []
        for result in semantic_results:
            norm_semantic = (result.score - min_semantic) / semantic_range
            norm_bm25 = (bm25_scores.get(result.chunk_id, 0) - min_bm25) / bm25_range

            combined_score = (semantic_weight * norm_semantic) + (keyword_weight * norm_bm25)

            combined_results.append(
                SearchResult(
                    chunk_id=result.chunk_id,
                    content=result.content,
                    source_url=result.source_url,
                    source_title=result.source_title,
                    heading=result.heading,
                    score=combined_score,
                    chunk_index=result.chunk_index,
                    metadata=result.metadata,
                )
            )

        combined_results.sort(key=lambda x: x.score, reverse=True)
        return combined_results[:top_k]

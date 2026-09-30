"""
FAISS Vector Store
==================

FAISS-based vector store for document retrieval.

Features:
- Efficient similarity search
- Hybrid search (BM25 + semantic)
- Index persistence (save/load)
- Metadata storage alongside vectors



Usage:
    from .vector_store import FAISSVectorStore

    store = FAISSVectorStore()
    await store.add_documents(chunks, embeddings)
    results = await store.search("How to configure?", top_k=5)
"""

import logging
import math
import os
import pickle
import re
from collections import Counter
from dataclasses import dataclass
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

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")


@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    content: str
    source_url: str
    source_title: str
    heading: Optional[str]
    score: float
    chunk_index: int = 0  # Position in original document (0 = first chunk)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "heading": self.heading,
            "score": self.score,
            "chunk_index": self.chunk_index,
        }


class FAISSVectorStore:
    """
    FAISS-based vector store for document retrieval.

    Uses FAISS IndexFlatIP (Inner Product) for similarity search.
    For larger datasets, can switch to IndexIVFFlat for faster search.
    """

    def __init__(
        self,
        dimension: int = 768,
        index_path: str = FAISS_INDEX_DIR,
    ):
        if not HAS_FAISS:
            raise RuntimeError("FAISS not installed. Run: pip install faiss-cpu")

        self.dimension = dimension
        self.index_path = index_path

        # FAISS index
        self._index: Optional[faiss.Index] = None

        # Metadata storage (chunk_id -> metadata)
        self._metadata: Dict[str, Dict[str, Any]] = {}

        # ID to index mapping
        self._id_to_idx: Dict[str, int] = {}
        self._idx_to_id: Dict[int, str] = {}

        # Ensure directory exists
        os.makedirs(self.index_path, exist_ok=True)

    def _create_index(self):
        """Create a new FAISS index."""
        # Use Inner Product (cosine similarity with normalized vectors)
        self._index = faiss.IndexFlatIP(self.dimension)
        logger.info("Created FAISS index with dimension %s", self.dimension)

    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize vectors for cosine similarity."""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        return vectors / norms

    async def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
    ):
        """
        Add document chunks with their embeddings to the index.

        Args:
            chunks: List of chunk dicts with 'chunk_id', 'content', etc.
            embeddings: Numpy array of embeddings (n_chunks x dimension)
        """
        if self._index is None:
            self.dimension = embeddings.shape[1]
            self._create_index()

        # Normalize for cosine similarity
        normalized = self._normalize_vectors(embeddings)

        # Add to FAISS index
        start_idx = self._index.ntotal
        self._index.add(normalized)

        # Store metadata and mappings
        for i, chunk in enumerate(chunks):
            idx = start_idx + i
            chunk_id = chunk.get("chunk_id", str(idx))

            self._id_to_idx[chunk_id] = idx
            self._idx_to_id[idx] = chunk_id

            self._metadata[chunk_id] = {
                "chunk_id": chunk_id,
                "content": chunk.get("content", ""),
                "source_url": chunk.get("source_url", ""),
                "source_title": chunk.get("source_title", ""),
                "heading": chunk.get("heading"),
                "chunk_index": chunk.get("chunk_index", 0),
            }

        logger.info("Added %d chunks to index (total: %d)", len(chunks), self._index.ntotal)

    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """
        Search for similar documents.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return

        Returns:
            List of SearchResult objects
        """
        if self._index is None or self._index.ntotal == 0:
            logger.warning("Index is empty")
            return []

        # Normalize query
        query = query_embedding.reshape(1, -1)
        query = self._normalize_vectors(query)

        # Search
        scores, indices = self._index.search(query, min(top_k, self._index.ntotal))

        # Build results
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for not found
                continue

            chunk_id = self._idx_to_id.get(idx)
            if chunk_id is None:
                continue

            metadata = self._metadata.get(chunk_id, {})

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    content=metadata.get("content", ""),
                    source_url=metadata.get("source_url", ""),
                    source_title=metadata.get("source_title", ""),
                    heading=metadata.get("heading"),
                    score=float(score),
                    chunk_index=metadata.get("chunk_index", 0),
                )
            )

        return results

    def save(self):
        """Save index and metadata to disk."""
        if self._index is None:
            logger.warning("No index to save")
            return

        # Save FAISS index
        index_file = os.path.join(self.index_path, "index.faiss")
        faiss.write_index(self._index, index_file)

        # Save metadata
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
            logger.warning("No saved index found")
            return False

        try:
            # Load FAISS index
            self._index = faiss.read_index(index_file)

            # Load metadata
            with open(metadata_file, "rb") as f:
                data = pickle.load(f)
                self._metadata = data["metadata"]
                self._id_to_idx = data["id_to_idx"]
                self._idx_to_id = data["idx_to_id"]
                self.dimension = data["dimension"]

            logger.info("Loaded index from %s (%d vectors)", self.index_path, self._index.ntotal)
            return True

        except Exception as e:
            logger.error("Error loading index: %s", e)
            return False

    def clear(self):
        """Clear the index."""
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

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        # Lowercase and split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r"\b[a-z0-9]+\b", text)
        # Remove very short tokens
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

            # IDF
            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)

            # TF normalization
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))

            score += idf * tf_norm

        return score

    async def hybrid_search(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int = 5,
        semantic_weight: float = 0.5,
        keyword_weight: float = 0.5,
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

        # 1. Get semantic search results (more than we need)
        semantic_results = await self.search(query_embedding, top_k=min(100, self.size))

        if not semantic_results:
            return []

        # 2. Compute BM25 scores for all documents
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

        # 3. Combine scores
        combined_results = []

        # Normalize semantic scores to 0-1 range
        max_semantic = max(r.score for r in semantic_results) if semantic_results else 1
        min_semantic = min(r.score for r in semantic_results) if semantic_results else 0
        semantic_range = max_semantic - min_semantic if max_semantic != min_semantic else 1

        # Compute BM25 scores for semantic results
        bm25_scores = {}
        for result in semantic_results:
            doc_tokens = all_doc_tokens.get(result.chunk_id, [])
            bm25_scores[result.chunk_id] = self._compute_bm25_score(
                query_tokens, doc_tokens, avg_doc_len, doc_freqs, total_docs
            )

        # Normalize BM25 scores
        max_bm25 = max(bm25_scores.values()) if bm25_scores else 1
        min_bm25 = min(bm25_scores.values()) if bm25_scores else 0
        bm25_range = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1

        for result in semantic_results:
            # Normalize scores to 0-1
            norm_semantic = (result.score - min_semantic) / semantic_range
            norm_bm25 = (bm25_scores.get(result.chunk_id, 0) - min_bm25) / bm25_range

            # Combined score
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
                )
            )

        # Sort by combined score
        combined_results.sort(key=lambda x: x.score, reverse=True)

        return combined_results[:top_k]

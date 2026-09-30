"""
Shared Embeddings Provider
==========================

Generates embeddings for text using:
- API-based embeddings (via EMBEDDING_BASE_URL - Ollama or other server)
- Sentence Transformers (local, free fallback)
- OpenAI embeddings (cloud, paid)

This module is shared across all agents:
- docs_agent: document chunk embeddings
- github_agent: code chunk embeddings
- testrail_agent: test case embeddings
- tfa_agent: test failure embeddings

Usage:
    from core.embeddings import get_embedding_provider

    provider = get_embedding_provider("api", model="qwen3-embedding")
    embeddings = await provider.embed_texts(["text1", "text2"])
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a single query."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return embedding dimension."""
        pass


class APIEmbeddings(EmbeddingProvider):
    """
    Embeddings via API server.

    Supports multiple endpoint formats:
    1. TEI (Text Embeddings Inference): /tei/embeddings (uses "inputs" field, no auth)
    2. OpenAI-compatible: /v1/embeddings (uses "input" field, Bearer auth)
    3. Ollama-style: /api/embeddings (uses "prompt" field, x-api-key auth)

    Auto-detects format based on URL path.
    """

    def __init__(
        self,
        model: str = "default",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model
        self.base_url = base_url or os.getenv("EMBEDDING_BASE_URL", "")
        self.api_key = api_key or os.getenv("EMBEDDING_API_KEY", "")
        self._dimension = None

        # Auto-detect endpoint format based on URL
        if self.base_url:
            if "/tei" in self.base_url:
                self._format = "tei"
            elif "/v1" in self.base_url:
                self._format = "openai"
            else:
                self._format = "ollama"
        else:
            self._format = "ollama"

        if not self.base_url:
            logger.warning("APIEmbeddings: No base_url configured. " "Set EMBEDDING_BASE_URL environment variable.")

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            dimensions = {
                "default": 1024,  # TEI default
                "qwen3-embedding": 2560,
                "qwen3-embedding:0.6b": 1024,
                "qwen3-embedding:8b": 4096,
                "nomic-embed-text": 768,
                "all-minilm": 384,
                "mxbai-embed-large": 1024,
                "snowflake-arctic-embed": 1024,
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
            }
            self._dimension = dimensions.get(self.model, 1024)
        return self._dimension

    def _truncate_text(self, text: str, max_tokens: int = 250) -> str:
        """Truncate text to approximate token limit (rough estimate: 1 token ≈ 4 chars)."""
        max_chars = max_tokens * 4  # Conservative estimate
        if len(text) <= max_chars:
            return text
        # Truncate and add indicator
        return text[: max_chars - 20] + "... [truncated]"

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text via API."""
        import httpx

        if not self.base_url:
            raise RuntimeError(
                "APIEmbeddings: base_url not configured. " "Set EMBEDDING_BASE_URL environment variable."
            )

        # Truncate text to avoid 512 token limit errors
        text = self._truncate_text(text)

        headers = {"Content-Type": "application/json"}

        if self._format == "tei":
            # TEI format: /tei/embeddings with "inputs" field, no auth needed
            url = self.base_url.rstrip("/")
            if not url.endswith("/embeddings"):
                url = f"{url}/embeddings"
            payload = {"inputs": text}
        elif self._format == "openai":
            # OpenAI-compatible format: /v1/embeddings with Bearer auth
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            url = f"{self.base_url.rstrip('/')}/embeddings"
            payload = {"model": self.model, "input": text}
        else:
            # Ollama-style format: /api/embeddings with x-api-key
            if self.api_key:
                headers["x-api-key"] = self.api_key
            url = f"{self.base_url.rstrip('/')}/api/embeddings"
            payload = {"model": self.model, "prompt": text}

        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code != 200:
                raise RuntimeError(f"Embedding error ({response.status_code}): {response.text[:200]}")

            data = response.json()

            # Handle different response formats
            if self._format == "tei":
                # TEI format: [[...embedding...]] (list of lists)
                if isinstance(data, list) and len(data) > 0:
                    embedding = data[0] if isinstance(data[0], list) else data
                else:
                    embedding = None
            elif self._format == "openai":
                # OpenAI format: {"data": [{"embedding": [...]}]}
                if "data" in data and len(data["data"]) > 0:
                    embedding = data["data"][0].get("embedding")
                else:
                    embedding = None
            else:
                # Ollama format: {"embedding": [...]}
                embedding = data.get("embedding")

            if not embedding:
                raise RuntimeError(f"No embedding returned. Response: {str(data)[:200]}")

            if self._dimension is None or self._dimension != len(embedding):
                self._dimension = len(embedding)
                logger.info(
                    "APIEmbeddings: detected dimension=%d (format=%s)",
                    self._dimension,
                    self._format,
                )

            return embedding

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts (sequential)."""
        embeddings = []
        total = len(texts)

        for i, text in enumerate(texts):
            try:
                emb = await self._get_embedding(text)
                embeddings.append(emb)
            except Exception as e:
                logger.error("Failed to embed text %d/%d: %s", i + 1, total, e)
                raise

            if (i + 1) % 50 == 0 or (i + 1) == total:
                logger.info("Embedded %d/%d texts", i + 1, total)

        return np.array(embeddings, dtype=np.float32)

    async def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a single query."""
        embedding = await self._get_embedding(query)
        return np.array(embedding, dtype=np.float32)


class SentenceTransformerEmbeddings(EmbeddingProvider):
    """
    Embeddings using Sentence Transformers (local, no API needed).

    Models:
    - all-MiniLM-L6-v2 (384 dimensions, fast)
    - all-mpnet-base-v2 (768 dimensions, better quality)
    - multi-qa-mpnet-base-dot-v1 (768 dimensions, optimized for QA)
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.model_name = model
        self._model = None
        self._dimension = None

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info("Loaded SentenceTransformer: %s", self.model_name)
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. " "Install with: pip install sentence-transformers"
                )
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=True)
        return np.array(embeddings, dtype=np.float32)

    async def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a single query."""
        model = self._load_model()
        embedding = model.encode([query])[0]
        return np.array(embedding, dtype=np.float32)


class OpenAIEmbeddings(EmbeddingProvider):
    """
    Embeddings using OpenAI API.

    Models:
    - text-embedding-3-small (1536 dimensions)
    - text-embedding-3-large (3072 dimensions)
    - text-embedding-ada-002 (1536 dimensions, legacy)
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str = None,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError("OpenAI API key required")

        self._dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

    @property
    def dimension(self) -> int:
        return self._dimensions.get(self.model, 1536)

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        import httpx

        embeddings = []
        batch_size = 100

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            async with httpx.AsyncClient(timeout=60, verify=False) as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "input": batch,
                    },
                )

                if response.status_code != 200:
                    raise RuntimeError(f"OpenAI embedding error: {response.text}")

                data = response.json()
                batch_embeddings = [item["embedding"] for item in data["data"]]
                embeddings.extend(batch_embeddings)

            logger.info("Embedded %d/%d texts", min(i + batch_size, len(texts)), len(texts))

        return np.array(embeddings, dtype=np.float32)

    async def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a single query."""
        result = await self.embed_texts([query])
        return result[0]


OllamaEmbeddings = APIEmbeddings  # backward compatibility alias


def get_embedding_provider(
    provider: str = "api",
    model: str = None,
    base_url: str = None,
    api_key: str = None,
) -> EmbeddingProvider:
    """
    Get embedding provider by name.

    Args:
        provider: 'api', 'tei', 'ollama', 'sentence-transformers', or 'openai'
        model: Optional model name override
        base_url: Optional base URL for embedding server
        api_key: Optional API key

    Returns:
        EmbeddingProvider instance

    Priority: api/tei (if configured) > sentence-transformers (fallback)
    """
    if provider in ("api", "ollama", "tei"):
        embedding_url = base_url or os.getenv("EMBEDDING_BASE_URL", "")
        if embedding_url:
            # Use default model for TEI, or specified model for others
            default_model = "default" if "/tei" in embedding_url else "qwen3-embedding"
            return APIEmbeddings(
                model=model or os.getenv("EMBEDDING_MODEL", default_model),
                base_url=embedding_url,
                api_key=api_key,
            )
        else:
            logger.warning(
                "APIEmbeddings requested but EMBEDDING_BASE_URL not set. " "Falling back to sentence-transformers."
            )
            return SentenceTransformerEmbeddings(model=model or "all-MiniLM-L6-v2")
    elif provider == "sentence-transformers":
        return SentenceTransformerEmbeddings(model=model or "all-MiniLM-L6-v2")
    elif provider == "openai":
        return OpenAIEmbeddings(model=model or "text-embedding-3-small", api_key=api_key)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")

"""
Embeddings Generator
====================

Generates embeddings for document chunks using:
- API-based embeddings (via EMBEDDING_BASE_URL)
- Sentence Transformers (local, free)
- OpenAI embeddings (cloud, paid)
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List

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
    Embeddings using an API server (/api/embeddings endpoint).

    Models:
    - nomic-embed-text (768 dimensions, good quality)
    - all-minilm (384 dimensions, fast)
    - mxbai-embed-large (1024 dimensions, best quality)
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = None,
    ):
        self.model = model
        self.base_url = base_url or os.getenv("EMBEDDING_BASE_URL", "")
        self._dimension = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Default dimensions for known models
            dimensions = {
                "nomic-embed-text": 768,
                "all-minilm": 384,
                "mxbai-embed-large": 1024,
            }
            self._dimension = dimensions.get(self.model, 768)
        return self._dimension

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text."""
        import httpx

        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )

            if response.status_code != 200:
                raise RuntimeError(f"Embedding error: {response.status_code}")

            data = response.json()
            return data["embedding"]

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        embeddings = []

        for i, text in enumerate(texts):
            try:
                embedding = await self._get_embedding(text)
                embeddings.append(embedding)

                if (i + 1) % 10 == 0:
                    logger.info("Embedded %d/%d texts", i + 1, len(texts))

            except Exception as e:
                logger.error("Error embedding text %d: %s", i, e)
                # Use zero vector as fallback
                embeddings.append([0.0] * self.dimension)

        self._dimension = len(embeddings[0]) if embeddings else 768
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

        # Dimensions for models
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
) -> EmbeddingProvider:
    """
    Get embedding provider by name.

    Args:
        provider: 'api' (or 'ollama' for compat), 'sentence-transformers', or 'openai'
        model: Optional model name override

    Returns:
        EmbeddingProvider instance
    """
    if provider in ("api", "ollama"):
        return APIEmbeddings(model=model or "nomic-embed-text")
    elif provider == "sentence-transformers":
        return SentenceTransformerEmbeddings(model=model or "all-MiniLM-L6-v2")
    elif provider == "openai":
        return OpenAIEmbeddings(model=model or "text-embedding-3-small")
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")

"""
Documentation RAG Tools
=======================

RAG pipeline for documentation search.
- Scraper: Fetches documentation from web
- Chunker: Splits documents into chunks
- Embeddings: Creates vector embeddings
- FAISS Store: Vector similarity search
"""

from .chunker import DocumentChunk, TextChunker
from .embeddings import get_embedding_provider
from .rag_pipeline import RAGPipeline, get_rag_pipeline
from .scraper import DocumentationScraper
from .vector_store import FAISSVectorStore

__all__ = [
    "RAGPipeline",
    "get_rag_pipeline",
    "FAISSVectorStore",
    "DocumentationScraper",
    "TextChunker",
    "DocumentChunk",
    "get_embedding_provider",
]

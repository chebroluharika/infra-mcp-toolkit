"""
RAG Pipeline
============

Retrieval-Augmented Generation pipeline for documentation queries.

Flow:
1. User query → Embedding
2. Embedding → FAISS search → Top-K chunks
3. Chunks + Query → LLM → Response



Usage:
    from .rag_pipeline import RAGPipeline

    pipeline = RAGPipeline()
    await pipeline.initialize()
    response = await pipeline.query("How do I configure the client?")
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .chunker import TextChunker
from .embeddings import EmbeddingProvider, get_embedding_provider
from .scraper import DocumentationScraper
from .vector_store import FAISSVectorStore, SearchResult

logger = logging.getLogger(__name__)

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class RAGPipeline:
    """
    Complete RAG pipeline for documentation Q&A.

    Orchestrates:
    - Document scraping
    - Text chunking
    - Embedding generation
    - Vector storage
    - Retrieval and response generation
    """

    def __init__(
        self,
        embedding_provider: str = "sentence-transformers",
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 1500,  # Larger chunks to preserve more context
        chunk_overlap: int = 300,
        top_k: int = 5,
    ):
        self.top_k = top_k

        # Components
        self._embedder: Optional[EmbeddingProvider] = None
        self._vector_store: Optional[FAISSVectorStore] = None
        self._chunker = TextChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # Config
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model

        # State
        self._initialized = False

    async def initialize(self, force_rebuild: bool = False):
        """
        Initialize the RAG pipeline.

        Loads existing index or builds from scratch if not found.

        Args:
            force_rebuild: If True, rebuild index even if exists
        """
        if self._initialized and not force_rebuild:
            return

        logger.info("Initializing RAG pipeline...")

        # Initialize embedder
        self._embedder = get_embedding_provider(
            provider=self._embedding_provider,
            model=self._embedding_model,
        )

        # Initialize vector store
        self._vector_store = FAISSVectorStore(
            dimension=self._embedder.dimension,
        )

        # Try to load existing index
        if not force_rebuild and self._vector_store.load():
            logger.info("Loaded existing index")
            self._initialized = True
            return

        # Build index from scraped docs
        await self._build_index()
        self._initialized = True

    async def _build_index(self):
        """Build vector index from documentation."""
        logger.info("Building vector index...")

        # Load scraped pages
        scraper = DocumentationScraper()
        pages = scraper.load_scraped_pages()

        if not pages:
            logger.warning("No scraped pages found. Run scraper first.")
            logger.info("Hint: python -m docs_agent.scraper")
            return

        # Convert to documents
        documents = [
            {
                "url": page.url,
                "title": page.title,
                "content": page.content,
            }
            for page in pages
        ]

        # Chunk documents
        chunks = self._chunker.chunk_documents(documents)

        if not chunks:
            logger.warning("No chunks created")
            return

        logger.info("Created %d chunks from %d documents", len(chunks), len(documents))

        # Generate embeddings
        texts = [chunk.content for chunk in chunks]
        embeddings = await self._embedder.embed_texts(texts)

        # Add to vector store
        chunk_dicts = [chunk.to_dict() for chunk in chunks]
        await self._vector_store.add_documents(chunk_dicts, embeddings)

        # Save index
        self._vector_store.save()

        logger.info("Index built and saved successfully")

    async def search(
        self,
        query: str,
        top_k: int = None,
        use_hybrid: bool = True,
    ) -> List[SearchResult]:
        """
        Search for relevant documentation chunks.

        Args:
            query: User query
            top_k: Number of results (default: self.top_k)
            use_hybrid: Use hybrid search (semantic + BM25)

        Returns:
            List of SearchResult objects
        """
        if not self._initialized:
            await self.initialize()

        if self._vector_store.size == 0:
            logger.warning("Index is empty")
            return []

        # Generate query embedding
        query_embedding = await self._embedder.embed_query(query)

        # Use hybrid search for better keyword matching
        if use_hybrid:
            results = await self._vector_store.hybrid_search(
                query=query,
                query_embedding=query_embedding,
                top_k=top_k or self.top_k,
                semantic_weight=0.4,  # 40% semantic
                keyword_weight=0.6,  # 60% keyword (BM25)
            )
        else:
            results = await self._vector_store.search(
                query_embedding,
                top_k=top_k or self.top_k,
            )

        return results

    async def query(
        self,
        question: str,
        include_sources: bool = True,
    ) -> Dict[str, Any]:
        """
        Answer a question using RAG.

        Args:
            question: User question
            include_sources: Whether to include source references

        Returns:
            Dict with answer and metadata
        """
        # Use hybrid search (semantic + BM25 keyword matching)
        # This naturally handles keyword relevance without complex reranking
        results = await self.search(question, top_k=10, use_hybrid=True)

        # Simple reranking: prefer chunk 0 (overview) and penalize irrelevant pages
        if results:
            query_lower = question.lower()

            for result in results:
                boost = 0.0
                title_lower = (result.source_title or "").lower()

                # Prefer earlier chunks (chunk 0 usually has overview/main content)
                chunk_idx = getattr(result, "chunk_index", 0) or 0
                if chunk_idx == 0:
                    boost += 0.15
                elif chunk_idx == 1:
                    boost += 0.05

                # Penalize "Golden Release" pages unless specifically asked
                if "golden release" in title_lower and "release" not in query_lower and "update" not in query_lower:
                    boost -= 0.2

                result.score = result.score + boost

            # Re-sort by boosted score
            results.sort(key=lambda x: x.score, reverse=True)

            # Take top 5
            results = results[:5]

        if not results:
            return {
                "answer": "I couldn't find relevant information in the documentation.",
                "sources": [],
                "chunks_used": 0,
            }

        # Build context from chunks - use source title as heading
        context_parts = []
        sources = []
        seen_urls = set()
        seen_content = set()

        for result in results:
            # Deduplicate similar content
            content_preview = result.content[:100].lower()
            if content_preview in seen_content:
                continue
            seen_content.add(content_preview)

            # Use source title as the heading (most reliable)
            title = result.source_title or ""
            # Clean up title
            title = title.replace(" - YourCompany Knowledge Portal", "").strip()

            if title:
                content = f"**{title}**\n\n{result.content}"
            else:
                content = result.content
            context_parts.append(content)

            # Deduplicate sources
            if result.source_url and result.source_url not in seen_urls:
                seen_urls.add(result.source_url)
                sources.append(
                    {
                        "url": result.source_url,
                        "title": result.source_title or "",
                    }
                )

        context = "\n\n---\n\n".join(context_parts)

        return {
            "context": context,
            "sources": sources if include_sources else [],
            "chunks_used": len(results),
            "top_scores": [r.score for r in results[:3]],
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        stats = {
            "initialized": self._initialized,
            "embedding_provider": self._embedding_provider,
            "embedding_model": self._embedding_model,
            "top_k": self.top_k,
        }

        if self._vector_store:
            stats.update(self._vector_store.get_stats())

        return stats


async def get_rag_pipeline() -> RAGPipeline:
    """
    Get RAG pipeline instance.

    Creates a new instance each time but the underlying vector store
    is loaded from disk, so it's fast after the first call.
    """
    pipeline = RAGPipeline()
    await pipeline.initialize()
    return pipeline


# CLI for testing
if __name__ == "__main__":
    import argparse
    import asyncio

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="RAG Pipeline CLI")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild index")
    parser.add_argument("--query", type=str, help="Query to test")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    args = parser.parse_args()

    async def main():
        pipeline = RAGPipeline()
        await pipeline.initialize(force_rebuild=args.rebuild)

        if args.stats:
            print(json.dumps(pipeline.get_stats(), indent=2))

        if args.query:
            result = await pipeline.query(args.query)
            print(f"\nQuery: {args.query}")
            print(f"Chunks used: {result['chunks_used']}")
            print(f"Sources: {len(result['sources'])}")
            print(f"\nContext:\n{result.get('context', 'N/A')[:500]}...")

    asyncio.run(main())

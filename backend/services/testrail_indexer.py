"""
TestRail Indexer Service
========================

Indexes TestRail test cases into FAISS for semantic search.

Two indexing modes:
1. API Mode: Live fetch from TestRail API (may hit rate limits)
2. Cache Mode: Index from local JSON cache (no API calls, no rate limits)

Flow (API Mode):
    Milestone → get_all_runs_for_milestone() → for each run:
        get_tests_with_cases(run_id) → embed title+description → FAISS

Flow (Cache Mode):
    Read testrail_cache.json → parse tests → embed → FAISS
    (Use backend/scripts/export_testrail.py to create the cache)

Each test case is embedded with: "{run_name}: {title}. {description}"
Metadata includes case_id, run_name, run_id, status, priority, testrail_url.

Usage:
    indexer = TestRailIndexer()

    # From API (may hit rate limits)
    stats = await indexer.index_milestone(project_id=38, milestone_id=5319)

    # From cache (no API calls - recommended)
    stats = await indexer.index_from_cache()

    # Search
    results = await indexer.search("session timeout authentication", top_k=10)
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Add ai_agents to path for shared imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ai_agents_dir = os.path.join(_project_root, "ai_agents")
if _ai_agents_dir not in sys.path:
    sys.path.insert(0, _ai_agents_dir)

from core.embeddings import EmbeddingProvider, get_embedding_provider
from core.vector_store import FAISSVectorStore, SearchResult

# Index and cache storage paths
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
TESTRAIL_INDEX_DIR = os.path.join(DATA_DIR, "testrail_faiss_index")
TESTRAIL_CACHE_FILE = os.path.join(DATA_DIR, "testrail_cache.json")


class TestRailIndexer:
    """
    Indexes TestRail test cases into FAISS for semantic matching.

    Test cases are fetched from TestRail via the existing TestRailClient,
    embedded using the shared APIEmbeddings (qwen3-embedding),
    and stored in a FAISS index for fast similarity search.
    """

    def __init__(
        self,
        embeddings: Optional[EmbeddingProvider] = None,
        index_path: str = TESTRAIL_INDEX_DIR,
    ):
        self._embeddings = embeddings
        self._store = FAISSVectorStore(index_path=index_path)
        self._index_path = index_path
        self._last_indexed: Optional[str] = None
        self._indexed_milestone: Optional[int] = None

        # Try to load existing index
        if self._store.load():
            logger.info(
                "TestRailIndexer: loaded existing index (%d vectors)",
                self._store.size,
            )

    def _get_embeddings(self) -> EmbeddingProvider:
        """Lazy-load embedding provider."""
        if self._embeddings is None:
            self._embeddings = get_embedding_provider(
                provider="ollama",
                model=os.getenv("EMBEDDING_MODEL", "qwen3-embedding"),
                base_url=os.getenv("EMBEDDING_BASE_URL", ""),
                api_key=os.getenv("EMBEDDING_API_KEY", ""),
            )
        return self._embeddings

    def _build_embedding_text(self, test: Dict, run_name: str) -> str:
        """
        Build the text to embed for a test case.

        Format: "{run_name}: {title}. {description}"
        """
        title = test.get("case_title") or test.get("title", "")
        description = test.get("case_description", "")
        steps = test.get("case_steps", "")
        expected = test.get("case_expected", "")

        parts = [f"{run_name}: {title}"]

        if description:
            parts.append(description[:500])
        if steps:
            parts.append(f"Steps: {steps[:300]}")
        if expected:
            parts.append(f"Expected: {expected[:200]}")

        return ". ".join(parts)

    async def index_milestone(
        self,
        project_id: int,
        milestone_id: int,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Index all test cases from all runs in a milestone.

        Args:
            project_id: TestRail project ID
            milestone_id: TestRail milestone ID
            force: If True, re-index even if already indexed

        Returns:
            Dict with indexing statistics
        """
        from services.testrail_client import get_testrail_client

        client = get_testrail_client()

        if not client.is_configured():
            return {"error": "TestRail not configured", "indexed": 0}

        # Check if already indexed
        if not force and self._indexed_milestone == milestone_id and self._store.size > 0:
            return {
                "status": "already_indexed",
                "milestone_id": milestone_id,
                "total_vectors": self._store.size,
                "last_indexed": self._last_indexed,
            }

        logger.info(
            "TestRailIndexer: starting index for milestone %d (project %d)",
            milestone_id,
            project_id,
        )

        # Clear existing index
        self._store.clear()

        # Fetch all runs for milestone
        all_runs = await client.get_all_runs_for_milestone(project_id, milestone_id)
        active_runs = [r for r in all_runs if not r.get("is_completed", False)]

        if not active_runs:
            active_runs = all_runs[:20]  # Fall back to all runs if none active

        logger.info(
            "TestRailIndexer: found %d runs (%d active) for milestone %d",
            len(all_runs),
            len(active_runs),
            milestone_id,
        )

        # Collect all test cases with their run context
        all_chunks = []
        all_texts = []
        total_tests = 0
        runs_processed = 0

        for run in active_runs:
            run_id = run["id"]
            run_name = run.get("name", f"Run {run_id}")

            try:
                tests = await client.get_tests_with_cases(run_id)
                runs_processed += 1

                for test in tests:
                    case_id = test.get("case_id")
                    if not case_id:
                        continue

                    # Build embedding text
                    embed_text = self._build_embedding_text(test, run_name)

                    # Build chunk with metadata
                    chunk_id = f"TR-C{case_id}-R{run_id}"
                    chunk = {
                        "chunk_id": chunk_id,
                        "content": embed_text,
                        "case_id": case_id,
                        "test_id": test.get("id"),
                        "title": test.get("case_title") or test.get("title", ""),
                        "description": test.get("case_description", ""),
                        "steps": test.get("case_steps", ""),
                        "expected": test.get("case_expected", ""),
                        "run_id": run_id,
                        "run_name": run_name,
                        "status": test.get("status", "unknown"),
                        "priority_id": test.get("priority_id"),
                        "case_refs": test.get("case_refs", ""),
                        "testrail_url": (f"{client.base_url}/index.php?/cases/view/{case_id}"),
                        "milestone_id": milestone_id,
                        "source_url": f"{client.base_url}/index.php?/cases/view/{case_id}",
                        "source_title": run_name,
                    }

                    all_chunks.append(chunk)
                    all_texts.append(embed_text)
                    total_tests += 1

                logger.info(
                    "TestRailIndexer: run '%s' (%d) → %d tests",
                    run_name,
                    run_id,
                    len(tests),
                )

            except Exception as e:
                logger.warning(
                    "TestRailIndexer: failed to fetch tests for run %d: %s",
                    run_id,
                    e,
                )
                continue

        if not all_chunks:
            return {
                "status": "no_tests_found",
                "milestone_id": milestone_id,
                "runs_found": len(all_runs),
                "indexed": 0,
            }

        # Embed all texts
        logger.info(
            "TestRailIndexer: embedding %d test cases with %s...",
            len(all_texts),
            self._get_embeddings().__class__.__name__,
        )
        embeddings = await self._get_embeddings().embed_texts(all_texts)

        # Add to FAISS
        await self._store.add_documents(all_chunks, embeddings)

        # Save to disk
        self._store.save()
        self._last_indexed = datetime.now().isoformat()
        self._indexed_milestone = milestone_id

        stats = {
            "status": "success",
            "milestone_id": milestone_id,
            "total_runs": len(all_runs),
            "runs_processed": runs_processed,
            "total_tests_indexed": total_tests,
            "total_vectors": self._store.size,
            "embedding_model": self._get_embeddings().__class__.__name__,
            "index_path": self._index_path,
            "last_indexed": self._last_indexed,
        }

        logger.info("TestRailIndexer: indexing complete — %s", stats)
        return stats

    async def index_from_cache(
        self,
        cache_file: str = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Index test cases from local JSON cache (no API calls).

        Use this to avoid TestRail rate limiting. First run:
            python backend/scripts/export_testrail.py --project-id 38 --milestone-id 5319

        Then call this method to index from the cached data.

        Args:
            cache_file: Path to cache JSON file (default: backend/data/testrail_cache.json)
            force: If True, re-index even if already indexed

        Returns:
            Dict with indexing statistics
        """
        cache_path = Path(cache_file or TESTRAIL_CACHE_FILE)

        if not cache_path.exists():
            return {
                "error": f"Cache file not found: {cache_path}",
                "hint": "Run: python backend/scripts/export_testrail.py --project-id <PID> --milestone-id <MID>",
                "indexed": 0,
            }

        logger.info("TestRailIndexer: loading cache from %s", cache_path)

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON in cache file: {e}", "indexed": 0}

        metadata = cache_data.get("metadata", {})
        runs = cache_data.get("runs", [])
        milestone_id = metadata.get("milestone_id")
        testrail_url = metadata.get("testrail_url", "")

        # Check if already indexed from this cache
        if not force and self._indexed_milestone == milestone_id and self._store.size > 0:
            return {
                "status": "already_indexed",
                "source": "cache",
                "milestone_id": milestone_id,
                "total_vectors": self._store.size,
                "last_indexed": self._last_indexed,
                "cache_exported_at": metadata.get("exported_at"),
            }

        logger.info(
            "TestRailIndexer: indexing from cache — %d runs, exported at %s",
            len(runs),
            metadata.get("exported_at"),
        )

        # Clear existing index
        self._store.clear()

        # Collect all test cases
        all_chunks = []
        all_texts = []
        total_tests = 0
        runs_processed = 0

        for run in runs:
            run_id = run.get("id")
            run_name = run.get("name", f"Run {run_id}")
            tests = run.get("tests", [])

            for test in tests:
                case_id = test.get("case_id")
                if not case_id:
                    continue

                # Build embedding text
                embed_text = self._build_embedding_text(test, run_name)

                # Build chunk with metadata
                chunk_id = f"TR-C{case_id}-R{run_id}"
                chunk = {
                    "chunk_id": chunk_id,
                    "content": embed_text,
                    "case_id": case_id,
                    "test_id": test.get("id"),
                    "title": test.get("case_title") or test.get("title", ""),
                    "description": test.get("case_description", ""),
                    "steps": test.get("case_steps", ""),
                    "expected": test.get("case_expected", ""),
                    "run_id": run_id,
                    "run_name": run_name,
                    "status": test.get("status", "unknown"),
                    "priority_id": test.get("priority_id"),
                    "case_refs": test.get("case_refs", ""),
                    "testrail_url": f"{testrail_url}/index.php?/cases/view/{case_id}",
                    "milestone_id": milestone_id,
                    "source_url": f"{testrail_url}/index.php?/cases/view/{case_id}",
                    "source_title": run_name,
                }

                all_chunks.append(chunk)
                all_texts.append(embed_text)
                total_tests += 1

            runs_processed += 1

            if runs_processed % 10 == 0:
                logger.info(
                    "TestRailIndexer: processed %d/%d runs (%d tests)",
                    runs_processed,
                    len(runs),
                    total_tests,
                )

        if not all_chunks:
            return {
                "status": "no_tests_found",
                "source": "cache",
                "milestone_id": milestone_id,
                "runs_found": len(runs),
                "indexed": 0,
            }

        # Embed all texts
        logger.info(
            "TestRailIndexer: embedding %d test cases with %s...",
            len(all_texts),
            self._get_embeddings().__class__.__name__,
        )
        embeddings = await self._get_embeddings().embed_texts(all_texts)

        # Add to FAISS
        await self._store.add_documents(all_chunks, embeddings)

        # Save to disk
        self._store.save()
        self._last_indexed = datetime.now().isoformat()
        self._indexed_milestone = milestone_id

        stats = {
            "status": "success",
            "source": "cache",
            "cache_file": str(cache_path),
            "cache_exported_at": metadata.get("exported_at"),
            "milestone_id": milestone_id,
            "total_runs": len(runs),
            "runs_processed": runs_processed,
            "total_tests_indexed": total_tests,
            "total_vectors": self._store.size,
            "embedding_model": self._get_embeddings().__class__.__name__,
            "index_path": self._index_path,
            "last_indexed": self._last_indexed,
        }

        logger.info("TestRailIndexer: cache indexing complete — %s", stats)
        return stats

    async def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> List[SearchResult]:
        """
        Search for test cases matching a query using hybrid search.

        Args:
            query: Natural language query describing the area/feature
            top_k: Number of results to return
            semantic_weight: Weight for embedding similarity
            keyword_weight: Weight for BM25 keyword matching

        Returns:
            List of SearchResult objects with matched test cases
        """
        if self._store.size == 0:
            logger.warning("TestRailIndexer: index is empty, run index_milestone first")
            return []

        query_embedding = await self._get_embeddings().embed_query(query)

        results = await self._store.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
        )

        return results

    async def search_for_files(
        self,
        file_contexts: List[Dict[str, str]],
        top_k_per_file: int = 5,
    ) -> Dict[str, List[SearchResult]]:
        """
        Search for test cases matching multiple file contexts.

        Used by ContextRetriever to find TestRail cases for each changed file.

        Args:
            file_contexts: List of dicts with 'file_path', 'purpose', 'functions'
            top_k_per_file: Number of results per file

        Returns:
            Dict mapping file_path to list of matching test cases
        """
        results = {}

        for ctx in file_contexts:
            file_path = ctx.get("file_path", "")
            purpose = ctx.get("purpose", "")
            functions = ctx.get("functions", "")

            query = f"{purpose} {functions} {file_path}"
            matches = await self.search(query, top_k=top_k_per_file)
            results[file_path] = matches

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get indexer statistics."""
        return {
            "total_vectors": self._store.size,
            "indexed_milestone": self._indexed_milestone,
            "last_indexed": self._last_indexed,
            "index_path": self._index_path,
            **self._store.get_stats(),
        }


# Singleton
_testrail_indexer: Optional[TestRailIndexer] = None


def get_testrail_indexer() -> TestRailIndexer:
    """Get singleton TestRailIndexer instance."""
    global _testrail_indexer
    if _testrail_indexer is None:
        _testrail_indexer = TestRailIndexer()
    return _testrail_indexer

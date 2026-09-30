"""
Test Code Indexer Service
==========================

Thin wrapper around RepoIndexer that indexes test files from
your-company-qe/your-product-tests into a dedicated FAISS store.

Reuses ALL of RepoIndexer's logic:
- GitHub API file tree fetching
- Raw file content fetching
- Python AST parsing (functions, classes, docstrings, imports)
- FAISS embedding + hybrid search
- Dependency graph building

The only difference: a path_filter restricts indexing to test_*.py files
under the tests/ directory, and storage goes to a separate FAISS path.

Usage:
    indexer = get_test_code_indexer()
    stats = await indexer.index_test_repo()
    results = await indexer.search("session timeout authentication", top_k=10)
"""

import logging
import os
from typing import Any, Dict, List, Optional

from services.repo_indexer import RepoIndexer

logger = logging.getLogger(__name__)

# Storage paths (separate from the product code repo index)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
TEST_CODE_INDEX_DIR = os.path.join(DATA_DIR, "test_code_faiss_index")
TEST_CODE_DEP_GRAPH_PATH = os.path.join(DATA_DIR, "test_code_dep_graph.pkl")

# Default test repo
DEFAULT_OWNER = "your-company-qe"
DEFAULT_REPO = "your-product-tests"
DEFAULT_BRANCH = "main"


def _is_test_file(path: str) -> bool:
    """
    Filter: only test_*.py files under any tests/ directory.

    Matches paths like:
        your-product-tests/tests/api/test_session.py
        your-product-tests/tests/npa/tunnel/test_setup.py
        your-product-tests/tests/test_basic.py

    Rejects:
        your-product-tests/conftest.py
        your-product-tests/tests/api/helpers.py
        your-product-tests/utils/test_utils.py  (not under tests/)
    """
    return "/tests/" in path and os.path.basename(path).startswith("test_") and path.endswith(".py")


class TestCodeIndexer:
    """
    Indexes test code from your-company-qe/your-product-tests into FAISS.

    Wraps a RepoIndexer instance with:
    - Separate FAISS store (test_code_faiss_index)
    - Path filter (only test_*.py under tests/)
    - Default repo pointing to the QE test repo
    """

    def __init__(
        self,
        index_path: str = TEST_CODE_INDEX_DIR,
        dep_graph_path: str = TEST_CODE_DEP_GRAPH_PATH,
    ):
        self._indexer = RepoIndexer(
            index_path=index_path,
            dep_graph_path=dep_graph_path,
        )

    async def index_test_repo(
        self,
        owner: str = DEFAULT_OWNER,
        repo: str = DEFAULT_REPO,
        branch: str = DEFAULT_BRANCH,
        force: bool = False,
        max_files: int = 2000,
    ) -> Dict[str, Any]:
        """
        Index test files from the QE test repository.

        Fetches test_*.py files under tests/, AST-parses them for
        function names + docstrings, and stores in FAISS.

        Args:
            owner: Repository owner (default: your-company-qe)
            repo: Repository name (default: your-product-tests)
            branch: Branch to index (default: main)
            force: If True, re-index even if already indexed
            max_files: Maximum test files to index

        Returns:
            Dict with indexing statistics
        """
        logger.info(
            "TestCodeIndexer: indexing test files from %s/%s:%s",
            owner,
            repo,
            branch,
        )
        return await self._indexer.index_repo(
            owner=owner,
            repo=repo,
            branch=branch,
            force=force,
            max_files=max_files,
            path_filter=_is_test_file,
        )

    async def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List:
        """
        Search for test code matching a query using hybrid search.

        Args:
            query: Natural language query (e.g., "session timeout handling")
            top_k: Number of results to return

        Returns:
            List of SearchResult objects from the test code FAISS index
        """
        return await self._indexer.search(query, top_k=top_k)

    def get_stats(self) -> Dict[str, Any]:
        """Get test code index statistics."""
        stats = self._indexer.get_stats()
        stats["index_type"] = "test_code"
        stats["default_repo"] = f"{DEFAULT_OWNER}/{DEFAULT_REPO}"
        return stats


# Singleton
_test_code_indexer: Optional[TestCodeIndexer] = None


def get_test_code_indexer() -> TestCodeIndexer:
    """Get singleton TestCodeIndexer instance."""
    global _test_code_indexer
    if _test_code_indexer is None:
        _test_code_indexer = TestCodeIndexer()
    return _test_code_indexer

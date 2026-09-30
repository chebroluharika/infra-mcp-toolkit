"""
GitHub Agent (ADK + Tools)
==========================

ADK LlmAgent for code-aware GitHub analysis.
Uses FAISS-backed repository index for understanding code context.

Architecture:
    GitHubAgent (LlmAgent)
        └── Tools (Python functions):
            ├── fetch_pr_details: Get PR files, stats, author from GitHub API
            ├── get_code_context: Query repo FAISS for file purpose/functions
            ├── get_file_dependencies: Lookup dependency graph
            └── index_repository: Re-index a repo into FAISS

This agent is:
- Standalone: usable directly for "analyze PR #7887" queries
- Reusable: sub-agent of escalation_analysis_agent
- Exportable: any team can add it to their agent system
"""

import logging
import os
import sys
from typing import Any, Callable, Dict, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

# ADK imports
if check_adk_available():
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool
else:
    LlmAgent = None
    FunctionTool = None

# Add backend to path for service imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# =============================================================================
# Tool Functions
# =============================================================================


async def fetch_pr_details(
    owner: str,
    repo: str,
    pr_number: int,
) -> Dict[str, Any]:
    """
    Fetch pull request details from GitHub including changed files and stats.

    Args:
        owner: Repository owner (e.g., 'netSkope')
        repo: Repository name (e.g., 'client')
        pr_number: Pull request number

    Returns:
        Dict with PR title, author, files changed, stats, and body
    """
    try:
        sys.path.insert(0, _backend_dir)
        from utilities.github import fetch_pr_details as _fetch_pr

        result = await _fetch_pr(owner, repo, pr_number, include_files=True)

        if result.get("status") == "not_found":
            return {"error": f"PR #{pr_number} not found in {owner}/{repo}"}
        if result.get("status") != "success":
            return {"error": result.get("error", "Failed to fetch PR")}

        # Build a concise summary for the LLM
        files = result.get("files", [])
        file_summary = []
        for f in files[:30]:
            file_summary.append(f"- {f['filename']} ({f['status']}: +{f['additions']}/-{f['deletions']})")

        return {
            "pr_number": pr_number,
            "title": result.get("title", ""),
            "author": result.get("author", ""),
            "state": result.get("state", ""),
            "merged": result.get("merged", False),
            "url": result.get("url", ""),
            "stats": result.get("stats", {}),
            "files_count": len(files),
            "files": file_summary,
            "file_paths": [f["filename"] for f in files],
            "qa_test_recommendations": result.get("qa_test_recommendations", []),
        }

    except Exception as e:
        logger.error("fetch_pr_details failed: %s", e)
        return {"error": str(e)}


async def get_code_context(
    file_path: str,
) -> Dict[str, Any]:
    """
    Get code context for a file from the repository FAISS index.

    Returns the file's purpose, functions, classes, and docstrings
    based on AST parsing stored in the index.

    Args:
        file_path: Path to the file in the repository (e.g., 'src/auth/session.py')

    Returns:
        Dict with file purpose, functions, classes, and docstrings
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.repo_indexer import get_repo_indexer

        indexer = get_repo_indexer()

        if indexer.get_stats()["total_vectors"] == 0:
            return {"error": "Repository not indexed yet. Run index_repository first."}

        results = await indexer.get_file_context(file_path, top_k=5)

        if not results:
            # Try fuzzy search by filename
            basename = os.path.basename(file_path)
            results = await indexer.search(f"File: {basename}", top_k=3)

        chunks = []
        for r in results:
            meta = r.metadata
            chunks.append(
                {
                    "type": meta.get("chunk_type", "unknown"),
                    "name": meta.get("name", ""),
                    "signature": meta.get("signature", ""),
                    "docstring": meta.get("docstring", ""),
                    "methods": meta.get("methods", []),
                    "score": r.score,
                }
            )

        return {
            "file_path": file_path,
            "chunks": chunks,
            "found": len(chunks) > 0,
        }

    except Exception as e:
        logger.error("get_code_context failed: %s", e)
        return {"error": str(e)}


async def get_file_dependencies(
    file_path: str,
) -> Dict[str, Any]:
    """
    Get dependency information for a file from the dependency graph.

    Shows what this file imports and what other files import it.
    Useful for understanding the blast radius of a code change.

    Args:
        file_path: Path to the file in the repository

    Returns:
        Dict with 'imports' (what this file uses) and 'imported_by' (what depends on it)
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.repo_indexer import get_repo_indexer

        indexer = get_repo_indexer()
        deps = indexer.get_dependencies(file_path)

        return {
            "file_path": file_path,
            "imports": deps.get("imports", []),
            "imported_by": deps.get("imported_by", []),
            "has_dependents": len(deps.get("imported_by", [])) > 0,
        }

    except Exception as e:
        logger.error("get_file_dependencies failed: %s", e)
        return {"error": str(e)}


async def index_repository(
    owner: str,
    repo: str,
    branch: str = "main",
) -> Dict[str, Any]:
    """
    Index or re-index a GitHub repository into the FAISS code index.

    This fetches the file tree, parses Python files (AST), builds a dependency graph,
    and stores code chunks in FAISS for semantic search.

    Args:
        owner: Repository owner (e.g., 'netSkope')
        repo: Repository name (e.g., 'client')
        branch: Branch to index (default: 'main')

    Returns:
        Dict with indexing statistics
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.repo_indexer import get_repo_indexer

        indexer = get_repo_indexer()
        stats = await indexer.index_repo(owner, repo, branch=branch, force=True)
        return stats

    except Exception as e:
        logger.error("index_repository failed: %s", e)
        return {"error": str(e)}


# =============================================================================
# Agent Instruction
# =============================================================================

GITHUB_AGENT_INSTRUCTION = """You are a code-aware GitHub analysis agent. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

1. `fetch_pr_details(owner, repo, pr_number)` — Get PR metadata, changed files, stats
2. `get_code_context(file_path)` — Get file purpose, functions, docstrings from repo index
3. `get_file_dependencies(file_path)` — Get import/export relationships
4. `index_repository(owner, repo, branch)` — Re-index a repo into FAISS

## WHEN ANALYZING A PR

1. First, call `fetch_pr_details` to get the list of changed files
2. For each important changed file, call `get_code_context` to understand what it does
3. For files with changes, call `get_file_dependencies` to find the blast radius

## OUTPUT FORMAT

Return a structured summary:
- **PR Overview**: title, author, stats
- **Changed Files**: for each file, its purpose and what changed
- **Dependencies**: files that depend on the changed files (could break)
- **QA Recommendations from PR**: if the PR author included test recommendations

Be concise. Focus on information useful for QA test planning.
"""


# =============================================================================
# Agent Factory
# =============================================================================


def create_github_agent(
    name: str = "github_agent",
    description: str = "Code-aware GitHub analysis: PR details, file context, dependency graphs",
) -> "LlmAgent":
    """
    Create the GitHub Agent with tools.

    Returns:
        LlmAgent instance
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    model = get_litellm_model()

    tools = [
        FunctionTool(fetch_pr_details),
        FunctionTool(get_code_context),
        FunctionTool(get_file_dependencies),
        FunctionTool(index_repository),
    ]

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=GITHUB_AGENT_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created GitHubAgent with %d tools", len(tools))
    return agent


async def create_github_agent_async(
    name: str = "github_agent",
    description: str = "Code-aware GitHub analysis: PR details, file context, dependency graphs",
) -> Tuple["LlmAgent", Callable]:
    """
    Async factory for GitHubAgent (compatible with root_agent pattern).

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    agent = create_github_agent(name=name, description=description)

    async def cleanup():
        pass  # No MCP connections to clean up

    return agent, cleanup

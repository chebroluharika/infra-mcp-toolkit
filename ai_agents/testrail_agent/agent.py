"""
TestRail Agent (ADK + Tools)
============================

ADK LlmAgent for test-aware TestRail analysis.
Uses FAISS-backed test case index for semantic test matching.

Architecture:
    TestRailAgent (LlmAgent)
        └── Tools (Python functions):
            ├── search_test_cases: Semantic search for matching test cases
            ├── get_test_coverage: Check coverage for feature areas
            ├── get_test_run_details: Get run status from TestRail API
            └── index_testrail: Re-index TestRail cases into FAISS

This agent is:
- Standalone: usable directly for "find tests for session management" queries
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


async def search_test_cases(
    query: str,
    top_k: int = 10,
    min_score: float = 0.5,
) -> Dict[str, Any]:
    """
    Search for TestRail test cases matching a natural language query.

    Uses hybrid search (semantic + BM25) against the FAISS-indexed TestRail cases.
    Returns test cases with case IDs, titles, descriptions, run names, and scores.

    Args:
        query: Natural language description of the feature or area
               (e.g., 'session timeout authentication', 'NPA tunnel setup')
        top_k: Number of results to return (default: 10)
        min_score: Minimum relevance score threshold (default: 0.5)

    Returns:
        Dict with matched test cases including case_id, title, run_name, score
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.testrail_indexer import get_testrail_indexer

        indexer = get_testrail_indexer()

        if indexer.get_stats()["total_vectors"] == 0:
            return {
                "error": "TestRail not indexed yet. Run index_testrail first.",
                "matches": [],
            }

        # Fetch more results to account for duplicates, then deduplicate
        results = await indexer.search(query, top_k=top_k * 3)

        matches = []
        seen_case_ids = set()

        for r in results:
            # Apply minimum score threshold
            if r.score < min_score:
                continue

            meta = r.metadata
            case_id = meta.get("case_id", "")

            # Skip duplicates (same case_id)
            if case_id in seen_case_ids:
                continue
            seen_case_ids.add(case_id)

            # Handle None values for optional fields
            description = meta.get("description") or ""
            matches.append(
                {
                    "case_id": f"C{case_id}",
                    "title": meta.get("title", ""),
                    "description": description[:200],
                    "run_name": meta.get("run_name", ""),
                    "run_id": meta.get("run_id"),
                    "status": meta.get("status", "unknown"),
                    "testrail_url": meta.get("testrail_url", ""),
                    "score": round(r.score, 3),
                }
            )

            # Stop after getting enough unique results
            if len(matches) >= top_k:
                break

        return {
            "query": query,
            "matches": matches,
            "total_found": len(matches),
            "min_score_applied": min_score,
        }

    except Exception as e:
        logger.error("search_test_cases failed: %s", e)
        return {"error": str(e), "matches": []}


async def get_test_coverage(
    areas: str,
) -> Dict[str, Any]:
    """
    Check test coverage for multiple feature areas.

    Searches for test cases in each area and reports coverage level.
    An area with fewer than 2 matching test cases is flagged as a gap.

    Args:
        areas: Comma-separated list of feature areas to check
               (e.g., 'session management, login authentication, NPA tunnels')

    Returns:
        Dict with coverage status per area and identified gaps
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.testrail_indexer import get_testrail_indexer

        indexer = get_testrail_indexer()

        if indexer.get_stats()["total_vectors"] == 0:
            return {"error": "TestRail not indexed yet. Run index_testrail first."}

        area_list = [a.strip() for a in areas.split(",") if a.strip()]

        coverage = []
        gaps = []

        for area in area_list:
            results = await indexer.search(area, top_k=5)

            high_confidence = [r for r in results if r.score > 0.5]

            area_result = {
                "area": area,
                "test_cases_found": len(results),
                "high_confidence_matches": len(high_confidence),
                "coverage_level": (
                    "good" if len(high_confidence) >= 3 else "partial" if len(high_confidence) >= 1 else "none"
                ),
                "top_cases": [
                    {
                        "case_id": f"C{r.metadata.get('case_id', '')}",
                        "title": r.metadata.get("title", ""),
                        "score": round(r.score, 3),
                    }
                    for r in results[:3]
                ],
            }

            coverage.append(area_result)

            if area_result["coverage_level"] == "none":
                gaps.append(area)

        return {
            "coverage": coverage,
            "gaps": gaps,
            "total_areas": len(area_list),
            "areas_with_gaps": len(gaps),
        }

    except Exception as e:
        logger.error("get_test_coverage failed: %s", e)
        return {"error": str(e)}


async def get_test_run_details(
    run_id: int,
) -> Dict[str, Any]:
    """
    Get details for a specific TestRail test run.

    Fetches pass/fail/untested counts and test list from TestRail API.

    Args:
        run_id: TestRail run ID

    Returns:
        Dict with run name, counts, pass rate, and test list
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.testrail_client import get_testrail_client

        client = get_testrail_client()

        if not client.is_configured():
            return {"error": "TestRail not configured"}

        summary = await client.get_run_summary(run_id)
        return summary

    except Exception as e:
        logger.error("get_test_run_details failed: %s", e)
        return {"error": str(e)}


async def index_testrail(
    milestone_id: int = 5319,
    project_id: int = 38,
) -> Dict[str, Any]:
    """
    Index or re-index TestRail test cases from a milestone into FAISS.

    Fetches all test cases from all runs in the milestone, embeds their
    titles and descriptions, and stores them in FAISS for semantic search.

    Args:
        milestone_id: TestRail milestone ID (default: 5319 for current release)
        project_id: TestRail project ID (default: 38 for NS Client)

    Returns:
        Dict with indexing statistics
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.testrail_indexer import get_testrail_indexer

        indexer = get_testrail_indexer()
        stats = await indexer.index_milestone(
            project_id=project_id,
            milestone_id=milestone_id,
            force=True,
        )
        return stats

    except Exception as e:
        logger.error("index_testrail failed: %s", e)
        return {"error": str(e)}


async def search_test_code(
    query: str,
    top_k: int = 10,
    min_score: float = 0.5,
) -> Dict[str, Any]:
    """
    Search for test functions in the QE test code repository (your-company-qe/your-product-tests).

    Searches the FAISS-indexed test code for matching test functions based on their
    docstrings, function names, and file paths. Use this alongside search_test_cases
    to get richer test scenario descriptions (docstrings are more detailed than
    TestRail case descriptions).

    Args:
        query: Natural language description of the feature or area
               (e.g., 'session timeout authentication', 'NPA tunnel setup')
        top_k: Number of results to return (default: 10)
        min_score: Minimum relevance score threshold (default: 0.5)

    Returns:
        Dict with matched test functions including file_path, function_name,
        docstring, github_url, and relevance score
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.test_code_indexer import get_test_code_indexer

        indexer = get_test_code_indexer()

        if indexer.get_stats()["total_vectors"] == 0:
            return {
                "error": "Test code not indexed yet. Run index_test_code first.",
                "matches": [],
            }

        # Fetch more results to allow for filtering
        results = await indexer.search(query, top_k=top_k * 3)

        matches = []
        seen_functions = set()

        for r in results:
            # Apply minimum score threshold
            if r.score < min_score:
                continue

            meta = r.metadata
            file_path = meta.get("file_path", r.source_title or "")
            function_name = meta.get("name", "")

            # Skip duplicates (same function in same file)
            func_key = f"{file_path}:{function_name}"
            if func_key in seen_functions:
                continue
            seen_functions.add(func_key)

            docstring = meta.get("docstring", "")
            github_url = meta.get(
                "source_url",
                r.source_url or f"https://github.com/your-company-qe/your-product-tests/blob/main/{file_path}",
            )

            matches.append(
                {
                    "file_path": file_path,
                    "function_name": function_name,
                    "type": meta.get("chunk_type", "function"),
                    "docstring": docstring[:500],
                    "signature": meta.get("signature", ""),
                    "github_url": github_url,
                    "score": round(r.score, 3),
                }
            )

            # Stop after getting enough unique results
            if len(matches) >= top_k:
                break

        return {
            "query": query,
            "source": "test_code (your-company-qe/your-product-tests)",
            "matches": matches,
            "total_found": len(matches),
            "min_score_applied": min_score,
        }

    except Exception as e:
        logger.error("search_test_code failed: %s", e)
        return {"error": str(e), "matches": []}


async def index_test_code(
    owner: str = "your-company-qe",
    repo: str = "your-product-tests",
    branch: str = "main",
) -> Dict[str, Any]:
    """
    Index or re-index test code from the QE test repository into FAISS.

    Fetches all test_*.py files under tests/, AST-parses them for function
    names and docstrings, and stores in FAISS for semantic search.

    Args:
        owner: Repository owner (default: your-company-qe)
        repo: Repository name (default: your-product-tests)
        branch: Branch to index (default: main)

    Returns:
        Dict with indexing statistics
    """
    try:
        sys.path.insert(0, _backend_dir)
        from services.test_code_indexer import get_test_code_indexer

        indexer = get_test_code_indexer()
        stats = await indexer.index_test_repo(
            owner=owner,
            repo=repo,
            branch=branch,
            force=True,
        )
        return stats

    except Exception as e:
        logger.error("index_test_code failed: %s", e)
        return {"error": str(e)}


# =============================================================================
# Agent Instruction
# =============================================================================

TESTRAIL_AGENT_INSTRUCTION = """You are a test-aware TestRail analysis agent. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

1. `search_test_cases(query, top_k)` — Search TestRail cases matching a description
2. `search_test_code(query, top_k)` — Search test code docstrings from your-company-qe/your-product-tests
3. `get_test_coverage(areas)` — Check test coverage for comma-separated feature areas
4. `get_test_run_details(run_id)` — Get test run pass/fail/untested counts
5. `index_testrail(milestone_id, project_id)` — Re-index TestRail cases into FAISS
6. `index_test_code(owner, repo, branch)` — Re-index test code into FAISS

## WHEN SEARCHING FOR RELEVANT TESTS

1. ALWAYS call BOTH `search_test_cases` AND `search_test_code` for the same query.
   - `search_test_cases` returns TestRail case IDs and titles (may have minimal descriptions)
   - `search_test_code` returns test function docstrings (rich scenario descriptions)
   These are complementary — test code docstrings fill in the detail that TestRail lacks.
2. If asked about multiple areas, use `get_test_coverage` with comma-separated areas.
3. Merge results from both sources and deduplicate by relevance.

## OUTPUT FORMAT

For each matched test, include:
- **Case ID**: TestRail case ID (e.g., C12345) if from TestRail
- **Title**: Test case title or function name
- **Run Name**: Which test run it belongs to (TestRail) or file path (test code)
- **Description**: Brief description — prefer the test code docstring if available
- **GitHub URL**: Link to test source code (for test code matches)
- **Relevance Score**: How well it matches (0-1)

Also identify TEST GAPS — areas where no test case was found with high confidence
in either TestRail or test code.

Be concise. Focus on information useful for QA test planning.
"""


# =============================================================================
# Agent Factory
# =============================================================================


def create_testrail_agent(
    name: str = "testrail_agent",
    description: str = "Test-aware analysis: TestRail case search, test code docstring search, coverage gaps, test run status",
) -> "LlmAgent":
    """
    Create the TestRail Agent with tools.

    Returns:
        LlmAgent instance
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    model = get_litellm_model()

    tools = [
        FunctionTool(search_test_cases),
        FunctionTool(search_test_code),
        FunctionTool(get_test_coverage),
        FunctionTool(get_test_run_details),
        FunctionTool(index_testrail),
        FunctionTool(index_test_code),
    ]

    agent = LlmAgent(
        name=name,
        model=model,
        instruction=TESTRAIL_AGENT_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created TestRailAgent with %d tools", len(tools))
    return agent


async def create_testrail_agent_async(
    name: str = "testrail_agent",
    description: str = "Test-aware analysis: TestRail case search, test code docstring search, coverage gaps, test run status",
) -> Tuple["LlmAgent", Callable]:
    """
    Async factory for TestRailAgent (compatible with root_agent pattern).

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    agent = create_testrail_agent(name=name, description=description)

    async def cleanup():
        pass

    return agent, cleanup

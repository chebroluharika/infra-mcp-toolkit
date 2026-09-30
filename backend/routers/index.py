"""
Index & Agent Analysis Router
==============================

Endpoints for managing FAISS indexes and running agent-based PR analysis.

Index Endpoints:
    - POST /api/index/testrail/reindex - Index TestRail test cases into FAISS (live API)
    - POST /api/index/testrail/reindex-from-cache - Index from local JSON cache (no API)
    - POST /api/index/repo/reindex - Index GitHub repo into FAISS
    - GET /api/index/status - Get index statistics

Agent Analysis Endpoint:
    - POST /api/agents/analyze-pr - Run multi-agent PR analysis
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# File path for storing ticket analysis results
ANALYSIS_CACHE_FILE = os.path.join(os.environ.get("DATA_DIR", "/app/data"), "ticket_analysis_cache.json")

# Add ai_agents to path for agent imports
_AI_AGENTS_PATH_ADDED = False


def _ensure_ai_agents_path():
    """Add ai_agents to path if not already added."""
    global _AI_AGENTS_PATH_ADDED
    if not _AI_AGENTS_PATH_ADDED:
        ai_agents_path = os.path.join(os.path.dirname(__file__), "..", "..", "ai_agents")
        if ai_agents_path not in sys.path:
            sys.path.insert(0, ai_agents_path)
        _AI_AGENTS_PATH_ADDED = True


# =============================================================================
# Ticket Analysis Storage (for aggregated views)
# =============================================================================


def _load_analysis_cache() -> Dict[str, Any]:
    """Load the ticket analysis cache from disk."""
    try:
        if os.path.exists(ANALYSIS_CACHE_FILE):
            with open(ANALYSIS_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Could not load analysis cache: %s", e)
    return {"tickets": {}, "updated_at": None}


def _save_analysis_cache(cache: Dict[str, Any]):
    """Save the ticket analysis cache to disk."""
    try:
        cache["updated_at"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(ANALYSIS_CACHE_FILE), exist_ok=True)
        with open(ANALYSIS_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.warning("Could not save analysis cache: %s", e)


def _store_ticket_analysis(
    ticket_key: str,
    customer: str,
    impacted_features: List[str],
    priority: str = None,
    summary: str = None,
    sub_component: str = None,
):
    """
    Store ticket analysis result for later aggregation.

    This is called after each ticket analysis completes, storing:
    - ticket_key
    - customer
    - impacted_features (from PR file analysis)
    - priority, summary, sub_component (from JIRA)
    """
    if not ticket_key:
        return

    cache = _load_analysis_cache()

    cache["tickets"][ticket_key] = {
        "ticket_key": ticket_key,
        "customer": customer,
        "impacted_features": impacted_features,
        "priority": priority,
        "summary": summary,
        "sub_component": sub_component,
        "analyzed_at": datetime.now().isoformat(),
    }

    _save_analysis_cache(cache)
    logger.info("Stored analysis for ticket %s (customer: %s, features: %s)", ticket_key, customer, impacted_features)


def _get_customer_feature_aggregation() -> Dict[str, Any]:
    """
    Aggregate stored ticket analyses by customer.

    Returns:
        {
            "customers": [
                {
                    "customer": "Deloitte",
                    "ticket_count": 5,
                    "impacted_features": {"NSC-Windows": 3, "NSC-MacOS": 2},
                    "tickets": [...]
                }
            ]
        }
    """
    from collections import defaultdict

    cache = _load_analysis_cache()
    tickets = cache.get("tickets", {})

    # Aggregate by customer
    customer_data = defaultdict(
        lambda: {
            "customer": "",
            "ticket_count": 0,
            "blockers": 0,
            "criticals": 0,
            "impacted_features": defaultdict(int),
            "tickets": [],
        }
    )

    for ticket_key, ticket in tickets.items():
        customer = ticket.get("customer") or "Unknown"
        if not customer or customer == "Unknown":
            continue

        cd = customer_data[customer]
        cd["customer"] = customer
        cd["ticket_count"] += 1

        priority = ticket.get("priority", "")
        if priority == "Blocker":
            cd["blockers"] += 1
        elif priority == "Critical":
            cd["criticals"] += 1

        # Count impacted features
        for feature in ticket.get("impacted_features", []):
            cd["impacted_features"][feature] += 1

        cd["tickets"].append(
            {
                "key": ticket_key,
                "summary": ticket.get("summary", "")[:60],
                "priority": priority,
                "impacted_features": ticket.get("impacted_features", []),
            }
        )

    # Convert to list and sort
    result = []
    for customer, data in customer_data.items():
        result.append(
            {
                "customer": customer,
                "ticket_count": data["ticket_count"],
                "blockers": data["blockers"],
                "criticals": data["criticals"],
                "impacted_features": sorted(
                    [{"name": k, "count": v} for k, v in data["impacted_features"].items()], key=lambda x: -x["count"]
                ),
                "tickets": data["tickets"][:10],
            }
        )

    result.sort(key=lambda x: -x["ticket_count"])

    return {
        "total_customers": len(result),
        "total_tickets_analyzed": len(tickets),
        "updated_at": cache.get("updated_at"),
        "customers": result,
    }


router = APIRouter(tags=["Index & Agent Analysis"])


# =============================================================================
# Request/Response Models
# =============================================================================


class AnalyzePrRequest(BaseModel):
    """Request model for single-PR analysis."""

    owner: str = "your-org"
    repo: str = "client"
    pr_number: int
    ticket_key: Optional[str] = None
    session_id: str = "escalation-analysis"


class AnalyzeTicketRequest(BaseModel):
    """Request model for full-ticket analysis (all PRs + JIRA context)."""

    ticket_key: str
    session_id: str = "escalation-analysis"


class IndexStatusResponse(BaseModel):
    """Response model for index status."""

    testrail_index: dict
    repo_index: dict


# =============================================================================
# Index Endpoints
# =============================================================================


@router.post("/api/index/testrail/reindex")
async def reindex_testrail(
    milestone_id: int = Query(default=5319, description="TestRail milestone ID"),
    project_id: int = Query(default=38, description="TestRail project ID"),
):
    """
    Index or re-index TestRail test cases from a milestone into FAISS.

    Fetches all test cases from all runs in the milestone, embeds their
    titles and descriptions using qwen3-embedding, and stores in FAISS.

    WARNING: This makes live API calls to TestRail and may hit rate limits.
    For large milestones, use /api/index/testrail/reindex-from-cache instead.
    """
    try:
        from services.testrail_indexer import get_testrail_indexer

        indexer = get_testrail_indexer()
        stats = await indexer.index_milestone(
            project_id=project_id,
            milestone_id=milestone_id,
            force=True,
        )
        return stats
    except Exception as e:
        logger.error("TestRail reindex failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/index/testrail/reindex-from-cache")
async def reindex_testrail_from_cache(
    cache_file: str = Query(
        default=None,
        description="Path to cache JSON file (default: backend/data/testrail_cache.json)",
    ),
    force: bool = Query(
        default=False,
        description="Force re-index even if already indexed",
    ),
):
    """
    Index TestRail test cases from a local JSON cache (no API calls).

    This avoids TestRail rate limiting by reading from a pre-exported cache file.

    Steps:
        1. Export data first (off-peak hours):
           python backend/scripts/export_testrail.py --project-id 38 --milestone-id 5319

        2. Then call this endpoint to index from the cache:
           curl -X POST 'http://localhost:8000/api/index/testrail/reindex-from-cache'

    Returns:
        Indexing statistics including source, total tests indexed, and cache metadata.
    """
    try:
        from services.testrail_indexer import get_testrail_indexer

        indexer = get_testrail_indexer()
        stats = await indexer.index_from_cache(
            cache_file=cache_file,
            force=force,
        )

        if stats.get("error"):
            raise HTTPException(status_code=400, detail=stats["error"])

        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error("TestRail cache reindex failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/index/repo/reindex")
async def reindex_repo(
    owner: str = Query(default="your-org", description="Repository owner"),
    repo: str = Query(default="client", description="Repository name"),
    branch: str = Query(default="main", description="Branch to index"),
    max_files: int = Query(default=50000, description="Maximum files to index (default 50000)"),
):
    """
    Index or re-index a GitHub repository into FAISS.

    Fetches file tree (uses recursive Contents API for large repos),
    parses code files (Python AST, C++ regex), builds dependency graph,
    and stores code chunks in FAISS.

    For very large repos, increase max_files but be aware of:
    - Longer indexing time (more GitHub API calls)
    - Larger disk usage for FAISS index
    - Potential GitHub API rate limiting
    """
    try:
        from services.repo_indexer import get_repo_indexer

        indexer = get_repo_indexer()
        stats = await indexer.index_repo(owner, repo, branch=branch, force=True, max_files=max_files)
        return stats
    except Exception as e:
        logger.error("Repo reindex failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/index/testcode/reindex")
async def reindex_test_code(
    owner: str = Query(default="your-company-qe", description="Test repo owner"),
    repo: str = Query(default="your-product-tests", description="Test repo name"),
    branch: str = Query(default="main", description="Branch to index"),
):
    """
    Index or re-index test code from the QE test repository into FAISS.

    Fetches test_*.py files under tests/, AST-parses them for function
    names and docstrings (rich scenario descriptions), and stores in FAISS.
    This supplements TestRail data with detailed test code docstrings.
    """
    try:
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
        logger.error("Test code reindex failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/index/status")
async def get_index_status():
    """
    Get statistics for all FAISS indexes.

    Returns vector counts, last indexed timestamps, and storage paths
    for TestRail, repo, and test code indexes.
    """
    try:
        from services.repo_indexer import get_repo_indexer
        from services.test_code_indexer import get_test_code_indexer
        from services.testrail_indexer import get_testrail_indexer

        testrail_stats = get_testrail_indexer().get_stats()
        repo_stats = get_repo_indexer().get_stats()
        test_code_stats = get_test_code_indexer().get_stats()

        return {
            "testrail_index": testrail_stats,
            "repo_index": repo_stats,
            "test_code_index": test_code_stats,
        }
    except Exception as e:
        logger.error("Index status failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Agent-Based PR Analysis Endpoint
# =============================================================================


async def _fetch_jira_context(ticket_key: str) -> dict:
    """
    Fetch JIRA ticket context for enriching agent analysis.

    Returns description, components, comments, and all PR links.
    """
    from services.escalation_service import get_escalation_service
    from services.jira_client import get_jira_client

    jira = get_jira_client()
    service = get_escalation_service()

    context = {
        "ticket_key": ticket_key,
        "summary": "",
        "description": "",
        "components": [],
        "comments": [],
        "pull_requests": [],
    }

    try:
        # Get ticket details (includes description, components, linked issues, PRs)
        details = await service.get_ticket_details(ticket_key)
        if details.get("error"):
            context["error"] = details["error"]
            return context

        context["summary"] = details.get("summary", "")
        context["description"] = details.get("description", "")
        context["components"] = details.get("components", [])
        context["pull_requests"] = details.get("pull_requests", [])
        context["priority"] = details.get("priority", "")
        context["labels"] = details.get("labels", [])
        context["assignee"] = details.get("assignee", "")

        # Fetch comments (already exists in jira_client but unused until now)
        try:
            comments = await jira.get_issue_comments(ticket_key, max_results=10)
            context["comments"] = [
                {
                    "author": c.get("author", ""),
                    "body": c.get("body", "")[:500],
                    "created": c.get("created", ""),
                }
                for c in comments
            ]
        except Exception as e:
            logger.warning("Could not fetch comments for %s: %s", ticket_key, e)

    except Exception as e:
        logger.warning("Could not fetch JIRA context for %s: %s", ticket_key, e)
        context["error"] = str(e)

    return context


def _build_jira_context_prompt(jira_ctx: dict) -> str:
    """Build a prompt section from JIRA context data."""
    parts = []

    if jira_ctx.get("ticket_key"):
        parts.append(f"## JIRA TICKET: {jira_ctx['ticket_key']}")
        if jira_ctx.get("summary"):
            parts.append(f"**Summary**: {jira_ctx['summary']}")
        if jira_ctx.get("priority"):
            parts.append(f"**Priority**: {jira_ctx['priority']}")
        if jira_ctx.get("components"):
            parts.append(f"**Components**: {', '.join(jira_ctx['components'])}")
        if jira_ctx.get("labels"):
            parts.append(f"**Labels**: {', '.join(jira_ctx['labels'][:10])}")

    if jira_ctx.get("description"):
        desc = jira_ctx["description"][:1500]
        parts.append(f"\n**Ticket Description**:\n{desc}")

    if jira_ctx.get("comments"):
        parts.append("\n**Recent Comments**:")
        for c in jira_ctx["comments"][:5]:
            parts.append(f"- [{c.get('author', 'Unknown')}]: {c.get('body', '')[:300]}")

    return "\n".join(parts) if parts else ""


# Load feature mappings from JSON config file
FEATURE_MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), "feature_mappings.json")


def _load_feature_mappings():
    """Load feature mappings from JSON configuration file."""
    try:
        with open(FEATURE_MAPPINGS_FILE, "r") as f:
            mappings = json.load(f)

        # Flatten file_to_feature categories into a single dict
        file_mapping = {}
        for category, patterns in mappings.get("file_to_feature", {}).items():
            if category == "_comment":
                continue
            if isinstance(patterns, dict):
                for pattern, feature in patterns.items():
                    if pattern != "_comment":
                        file_mapping[pattern] = feature

        # Get customer label mappings (exclude _comment)
        customer_mapping = {k: v for k, v in mappings.get("customer_label_to_features", {}).items() if k != "_comment"}

        return file_mapping, customer_mapping
    except Exception as e:
        logger.error("Failed to load feature mappings: %s", e)
        return {}, {}


# Load mappings at module level
FILE_TO_FEATURE_MAPPING, CUSTOMER_LABEL_TO_FEATURES = _load_feature_mappings()


def _extract_features_from_customer_label(customer: str) -> list:
    """
    Extract implied features from customer label.
    e.g., 'l3_client_steering' -> ['NSC-SVC-Steering']
    """
    if not customer:
        return []

    features = []
    customer_lower = customer.lower()

    for keyword, feature_list in CUSTOMER_LABEL_TO_FEATURES.items():
        if keyword in customer_lower:
            features.extend(feature_list)

    return features


def _extract_impacted_features(pr_details_list: list, customer: str = None) -> list:
    """
    Extract impacted features from PR file changes and customer context.

    Maps changed file paths to feature/component names using FILE_TO_FEATURE_MAPPING.
    Also extracts implied features from customer label (e.g., l3_client_steering -> Steering).

    DEPRECATED: Use _extract_impacted_features_from_ai() for AI-based extraction.
    """
    features = set()

    # Extract features from PR file changes
    for pr in pr_details_list:
        files = pr.get("files", [])
        for file_info in files:
            # file_info can be a dict with 'filename' or just a string
            if isinstance(file_info, dict):
                filepath = file_info.get("filename", "")
            else:
                filepath = str(file_info)

            filepath_lower = filepath.lower()

            # Match against known patterns
            for pattern, feature in FILE_TO_FEATURE_MAPPING.items():
                if pattern in filepath_lower:
                    features.add(feature)

            # Also extract from directory structure
            parts = filepath.split("/")
            if len(parts) > 1:
                # Add top-level directory as a feature hint
                top_dir = parts[0]
                if top_dir and top_dir not in ["src", "lib", "test", "tests", "."]:
                    features.add(f"Module:{top_dir}")

    # Add features implied by customer label
    if customer:
        customer_features = _extract_features_from_customer_label(customer)
        features.update(customer_features)

    return sorted(list(features))


async def _extract_impacted_features_from_ai(pr_details_list: list) -> list:
    """
    Extract impacted features from PR file changes using AI analysis.

    Uses CommitAnalyzer with LLM to analyze code changes and extract:
    - Components/features impacted by the code changes
    - Testing recommendations based on code analysis

    This provides more accurate feature detection than static file path mapping.
    """
    try:
        from services.commit_analyzer import get_commit_analyzer

        all_components: set = set()
        analyzer = get_commit_analyzer()

        for pr in pr_details_list:
            files = pr.get("files", [])
            if not files:
                continue

            try:
                # Run AI analysis on the PR files
                analysis = await analyzer.analyze_commit(
                    commit_data={
                        "files": files,
                        "stats": pr.get("stats", {}),
                        "message": pr.get("title", ""),
                        "sha": f"PR#{pr.get('pr_number', 'unknown')}",
                    },
                    include_llm_analysis=True,
                )

                # Extract components from pattern-based analysis
                for component in analysis.get("files_by_component", {}).keys():
                    if component and component != "other":
                        all_components.add(component.replace("_", " ").title())

                # Extract components from LLM analysis (more accurate)
                llm = analysis.get("llm_analysis") or {}
                if llm.get("available"):
                    for comp in llm.get("components", []):
                        all_components.add(comp)

            except Exception as e:
                logger.warning("AI analysis failed for PR: %s", e)
                continue

        return sorted(all_components)

    except ImportError:
        logger.warning("CommitAnalyzer not available, falling back to static mapping")
        return _extract_impacted_features(pr_details_list)
    except Exception as e:
        logger.error("AI feature extraction failed: %s", e)
        return _extract_impacted_features(pr_details_list)


def _extract_customer_from_labels(labels: list) -> str:
    """Extract customer name from JIRA labels if available."""
    # Labels sometimes contain customer identifiers
    # This is a fallback if customer field is not set
    for label in labels:
        if label and not label.startswith("jira_") and not label.isdigit():
            # Skip known non-customer labels
            if label.lower() not in ["premium_support", "escalated", "blocker"]:
                return label
    return None


def _parse_agent_response(content: str) -> dict:
    """Extract JSON from agent response (may be wrapped in markdown or reasoning text)."""
    import json as _json
    import re

    # First, try to find the analysis JSON by looking for {"pr_summary"
    # This handles cases where there are other JSON snippets in the reasoning
    pr_summary_match = re.search(r'\{"pr_summary"', content)
    if pr_summary_match:
        json_start = pr_summary_match.start()
        json_end = content.rfind("}") + 1
        if json_end > json_start:
            try:
                return _json.loads(content[json_start:json_end])
            except _json.JSONDecodeError:
                pass

    # Fallback: try finding any JSON object
    json_start = content.find("{")
    json_end = content.rfind("}") + 1

    if json_start >= 0 and json_end > json_start:
        try:
            return _json.loads(content[json_start:json_end])
        except _json.JSONDecodeError:
            pass
    return {}


@router.post("/api/agents/analyze-pr")
async def analyze_pr_with_agents(request: AnalyzePrRequest):
    """
    Analyze a PR using the multi-agent escalation analysis system.

    Optionally enriched with JIRA context (description, components, comments)
    when ticket_key is provided.

    Flow:
        1. Fetch PR details including changed files
        2. (Optional) Fetch JIRA ticket context
        3. Extract impacted features/components from code changes
        4. Orchestrator → github_agent: fetch PR details, code context, deps
        5. Orchestrator → testrail_agent: search matching TestRail cases
        6. Orchestrator: synthesize MUST RUN / SHOULD RUN / MANUAL QA / TEST GAPS

    Returns:
        Structured JSON with categorized test recommendations and impacted features
    """
    _ensure_ai_agents_path()

    try:
        from core.runner import get_runner
        from escalation_analysis_agent.agent import create_escalation_analysis_agent
        from utilities.github import fetch_pr_details

        runner = get_runner()
        agent = create_escalation_analysis_agent()

        # Fetch PR details including files for impacted feature extraction
        pr_details = await fetch_pr_details(request.owner, request.repo, request.pr_number, include_files=True)

        pr_details_list = []
        if pr_details.get("status") == "success":
            pr_details_list.append(
                {
                    "pr_number": request.pr_number,
                    "owner": request.owner,
                    "repo": request.repo,
                    "title": pr_details.get("title", ""),
                    "author": pr_details.get("author", ""),
                    "merged": pr_details.get("merged", False),
                    "stats": pr_details.get("stats", {}),
                    "files": pr_details.get("files", []),
                }
            )

        # Extract impacted features from PR file changes using AI analysis
        impacted_features = await _extract_impacted_features_from_ai(pr_details_list)

        # Build the analysis query
        query_parts = [
            f"Analyze PR #{request.pr_number} in {request.owner}/{request.repo}.",
            "Get the PR details and code context from github_agent,",
            "then find matching TestRail test cases from testrail_agent,",
            "and produce categorized test recommendations.",
        ]

        # Enrich with JIRA context if ticket_key provided
        jira_ctx = {}
        if request.ticket_key:
            jira_ctx = await _fetch_jira_context(request.ticket_key)
            jira_prompt = _build_jira_context_prompt(jira_ctx)
            if jira_prompt:
                query_parts.append(f"\n\n{jira_prompt}")

        query = " ".join(query_parts)

        response = await runner.run(
            agent=agent,
            message=query,
            session_id=request.session_id,
        )

        if response.error:
            raise HTTPException(status_code=500, detail=response.error)

        result = _parse_agent_response(response.content)

        # Inject impacted_features into analysis object for frontend compatibility
        # Frontend does: h = e.analysis || e, so impacted_features must be in analysis
        analysis_with_features = result.copy() if result else {}
        analysis_with_features["impacted_features"] = impacted_features

        # Also inject JIRA context used by AI for display
        if jira_ctx and not jira_ctx.get("error"):
            analysis_with_features["jira_context_used"] = {
                "customer_scenario": jira_ctx.get("summary"),
                "sub_component": jira_ctx.get("sub_component"),
                "components": jira_ctx.get("components", []),
            }

        # Build response with impacted features
        base_response = {
            "status": "success",
            "pr_number": request.pr_number,
            "owner": request.owner,
            "repo": request.repo,
            "ticket_key": request.ticket_key,
            "impacted_features": impacted_features,
            "pr_details": pr_details_list[0] if pr_details_list else None,
            "agent": response.agent_name,
            "tools_used": response.tools_used,
            "analysis": analysis_with_features,
        }

        # Add JIRA context if available
        if jira_ctx and not jira_ctx.get("error"):
            base_response["jira_context"] = {
                "summary": jira_ctx.get("summary"),
                "components": jira_ctx.get("components"),
                "sub_component": jira_ctx.get("sub_component"),
                "customer": jira_ctx.get("customer") or _extract_customer_from_labels(jira_ctx.get("labels", [])),
            }

        return base_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Agent PR analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agents/analyze-ticket")
async def analyze_ticket_with_agents(request: AnalyzeTicketRequest):
    """
    Analyze ALL PRs for a JIRA ticket using the multi-agent system.

    Fetches ticket context (description, components, comments) and all linked PRs,
    then runs a combined analysis across all PRs for a holistic view.

    Flow:
        1. Fetch JIRA ticket details + all PR links
        2. For each PR: github_agent fetches details, code context, deps
        3. testrail_agent searches matching TestRail cases for all changed files
        4. Orchestrator synthesizes combined MUST RUN / SHOULD RUN / MANUAL QA / TEST GAPS

    Returns:
        Combined analysis with JIRA context across all PRs
    """
    _ensure_ai_agents_path()

    try:
        # Fetch JIRA context (includes all PRs)
        jira_ctx = await _fetch_jira_context(request.ticket_key)

        if jira_ctx.get("error"):
            raise HTTPException(
                status_code=404,
                detail=f"Could not fetch ticket {request.ticket_key}: {jira_ctx['error']}",
            )

        prs = jira_ctx.get("pull_requests", [])
        if not prs:
            return {
                "status": "no_prs",
                "ticket_key": request.ticket_key,
                "message": "No PRs found for this ticket",
                "jira_context": {
                    "summary": jira_ctx.get("summary"),
                    "components": jira_ctx.get("components"),
                },
            }

        # Parse and fetch details for each PR
        import re

        from utilities.github import fetch_pr_details

        pr_list_text = []
        pr_details_list = []

        async def _fetch_one_pr(pr_info):
            url = pr_info.get("url", "")
            gh_match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)/pull/(\d+)", url)
            if gh_match:
                owner, repo, number = gh_match.group(1), gh_match.group(2), int(gh_match.group(3))
                try:
                    details = await fetch_pr_details(owner, repo, number, include_files=True)
                    if details.get("status") == "success":
                        return {
                            "pr_number": number,
                            "owner": owner,
                            "repo": repo,
                            "title": details.get("title", ""),
                            "author": details.get("author", ""),
                            "url": url,
                            "merged": details.get("merged", False),
                            "stats": details.get("stats", {}),
                            "files": details.get("files", []),
                            "qa_test_recommendations": details.get("qa_test_recommendations", []),
                        }
                except Exception as e:
                    logger.debug("Failed to fetch PR details for %s: %s", url, e)
            return None

        import asyncio as _asyncio

        pr_detail_results = await _asyncio.gather(*[_fetch_one_pr(pr) for pr in prs])

        for pr, detail in zip(prs, pr_detail_results):
            url = pr.get("url", "")
            gh_match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)/pull/(\d+)", url)
            if gh_match:
                pr_list_text.append(f"- PR #{gh_match.group(3)} in {gh_match.group(1)}/{gh_match.group(2)} ({url})")
            elif pr.get("name"):
                pr_list_text.append(f"- {pr['name']} ({url})")
            if detail:
                pr_details_list.append(detail)

        # Build JIRA context prompt
        jira_prompt = _build_jira_context_prompt(jira_ctx)

        # Build the combined analysis query
        query = (
            f"Analyze ALL the following PRs together for JIRA ticket {request.ticket_key}. "
            f"This is a combined analysis — consider the cumulative impact of all changes.\n\n"
            f"## PRs to analyze:\n"
            f"{chr(10).join(pr_list_text)}\n\n"
            f"For EACH PR, use github_agent to fetch PR details and code context.\n"
            f"Then use testrail_agent to find matching test cases for ALL changed files combined.\n"
            f"Produce a single combined recommendation covering all PRs.\n\n"
            f"{jira_prompt}"
        )

        from core.runner import get_runner
        from escalation_analysis_agent.agent import create_escalation_analysis_agent

        runner = get_runner()
        agent = create_escalation_analysis_agent()

        response = await runner.run(
            agent=agent,
            message=query,
            session_id=request.session_id,
        )

        if response.error:
            raise HTTPException(status_code=500, detail=response.error)

        result = _parse_agent_response(response.content)

        # Get customer (for storage, not for feature extraction)
        customer = jira_ctx.get("customer") or _extract_customer_from_labels(jira_ctx.get("labels", []))

        # Extract impacted features from AI analysis of PR file changes
        # Uses CommitAnalyzer with LLM to analyze code changes
        impacted_features = await _extract_impacted_features_from_ai(pr_details_list)

        # Store the analysis result for aggregation
        _store_ticket_analysis(
            ticket_key=request.ticket_key,
            customer=customer,
            impacted_features=impacted_features,
            priority=jira_ctx.get("priority"),
            summary=jira_ctx.get("summary"),
            sub_component=jira_ctx.get("sub_component"),
        )

        # Inject impacted_features into analysis object for frontend compatibility
        # Frontend does: h = e.analysis || e, so impacted_features must be in analysis
        analysis_with_features = result.copy() if result else {}
        analysis_with_features["impacted_features"] = impacted_features

        # Also inject JIRA context used by AI for display
        analysis_with_features["jira_context_used"] = {
            "customer_scenario": jira_ctx.get("summary"),
            "sub_component": jira_ctx.get("sub_component"),
            "components": jira_ctx.get("components", []),
        }

        return {
            "status": "success",
            "ticket_key": request.ticket_key,
            "total_prs": len(prs),
            "prs_analyzed": pr_list_text,
            "pr_details": pr_details_list,
            "jira_context": {
                "summary": jira_ctx.get("summary"),
                "components": jira_ctx.get("components"),
                "comments_count": len(jira_ctx.get("comments", [])),
            },
            "impacted_features": impacted_features,
            "customer": customer,
            "analysis": analysis_with_features,
            "analysis_text": response.content if not result else None,
            "agent": response.agent_name,
            "tools_used": response.tools_used,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Agent ticket analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/escalation-analysis/customer-features")
async def get_customer_features(
    limit: int = Query(default=20, description="Max customers to return"),
):
    """
    Get aggregated view of impacted features by customer.

    This aggregates results from ticket analyses that have been run,
    showing which features are causing issues for each customer.

    Data is populated when `/api/agents/analyze-ticket` is called.

    Returns:
        - List of customers with their escalation counts
        - Impacted features (from PR analysis) per customer
        - Recent tickets per customer
    """
    try:
        aggregation = _get_customer_feature_aggregation()

        return {
            "status": "success",
            "total_customers": aggregation["total_customers"],
            "total_tickets_analyzed": aggregation["total_tickets_analyzed"],
            "updated_at": aggregation["updated_at"],
            "customers": aggregation["customers"][:limit],
        }
    except Exception as e:
        logger.error("Customer features aggregation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class BatchFeatureExtractionRequest(BaseModel):
    """Request for batch feature extraction from ticket metadata."""

    ticket_keys: List[str] = []
    release_id: Optional[str] = None
    limit: int = 100


@router.post("/api/escalation-analysis/extract-features-batch")
async def extract_features_batch(request: BatchFeatureExtractionRequest):
    """
    Extract impacted features from ticket metadata in batch (lightweight, no AI agents).

    This extracts features based on:
    - Sub-component field
    - Customer labels (l3_client_* patterns)
    - Component fields

    Use this to populate AI features for tickets without running full PR analysis.
    """
    from services.jira_client import JiraClient

    try:
        jira = JiraClient()

        # Get tickets either from request or by release
        if request.ticket_keys:
            ticket_keys = request.ticket_keys[: request.limit]
        elif request.release_id:
            # Fetch escalation tickets for the release
            jql = (
                f"project = ENG AND issuetype = Escalation "
                f'AND "Fix Version/s" ~ "{request.release_id}" '
                f"ORDER BY created DESC"
            )
            result = await jira.search_issues(jql, max_results=request.limit)
            # search_issues returns a list of issues directly
            if isinstance(result, list):
                ticket_keys = [issue.key for issue in result]
            elif isinstance(result, dict):
                ticket_keys = [issue.key for issue in result.get("issues", [])]
            else:
                ticket_keys = []
        else:
            return {"error": "Provide either ticket_keys or release_id"}

        analyzed = 0
        skipped = 0
        errors = []

        cache = _load_analysis_cache()

        logger.info("Starting batch extraction for %d tickets", len(ticket_keys))

        for ticket_key in ticket_keys:
            try:
                # Skip if already analyzed
                if ticket_key in cache.get("tickets", {}):
                    skipped += 1
                    continue

                # Fetch ticket details
                issue = await jira.get_issue(ticket_key)
                if not issue:
                    errors.append(f"{ticket_key}: not found")
                    continue

                # Handle JiraClient response - fields are at top level, not nested
                # The JiraClient returns a flattened dict with processed fields
                fields = issue  # The entire issue dict contains the fields

                # Extract sub-component (already flattened by JiraClient)
                sub_component = fields.get("sub_component")

                # Extract customer from labels
                labels = fields.get("labels", [])
                customer = None
                for label in labels:
                    if label and label.startswith("l3_"):
                        customer = label
                        break

                # Also check salesforce_account field
                if not customer:
                    customer = fields.get("salesforce_account")

                # Extract features from sub-component and customer label
                features = set()

                # From sub-component
                if sub_component:
                    features.add(sub_component)
                    # Also check if sub_component maps to known features
                    sub_lower = sub_component.lower()
                    for keyword, feature_list in CUSTOMER_LABEL_TO_FEATURES.items():
                        if keyword in sub_lower:
                            features.update(feature_list)

                # From customer label
                if customer:
                    customer_features = _extract_features_from_customer_label(customer)
                    features.update(customer_features)

                # From components (already a list of strings from JiraClient)
                components = fields.get("components", [])
                for comp in components:
                    comp_name = comp.get("name", "") if isinstance(comp, dict) else str(comp)
                    if comp_name:
                        features.add(comp_name)

                # Get priority and summary
                priority = fields.get("priority")
                summary = fields.get("summary", "")

                # Store the analysis
                if features:
                    _store_ticket_analysis(
                        ticket_key=ticket_key,
                        customer=customer,
                        impacted_features=sorted(list(features)),
                        priority=priority,
                        summary=summary[:100] if summary else None,
                        sub_component=sub_component,
                    )
                    analyzed += 1
                else:
                    skipped += 1

            except Exception as e:
                errors.append(f"{ticket_key}: {str(e)}")

        return {
            "status": "success",
            "total_requested": len(ticket_keys),
            "analyzed": analyzed,
            "skipped": skipped,
            "errors": errors[:10] if errors else [],
            "message": f"Extracted features for {analyzed} tickets",
        }

    except Exception as e:
        logger.error("Batch feature extraction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class BatchAIAnalysisRequest(BaseModel):
    """Request for batch AI impact analysis."""

    ticket_keys: List[str] = []
    limit: int = 20
    skip_analyzed: bool = True


@router.post("/api/escalation-analysis/analyze-impact-batch")
async def analyze_impact_batch(request: BatchAIAnalysisRequest):
    """
    Run AI-powered impact analysis on multiple tickets in batch.

    This uses the LLM to analyze PR code changes and extract:
    - impacted_features: AI-determined product components/features affected
    - test_areas: AI-recommended test areas based on code analysis

    Only tickets with linked PRs will have full AI analysis.
    """
    from services.escalation_service import get_escalation_service

    try:
        service = get_escalation_service()

        ticket_keys = request.ticket_keys[: request.limit]

        analyzed = 0
        skipped = 0
        no_prs = 0
        errors = []
        results = []

        cache = _load_analysis_cache()

        for ticket_key in ticket_keys:
            try:
                # Skip if already analyzed and flag is set
                if request.skip_analyzed and ticket_key in cache.get("tickets", {}):
                    existing = cache["tickets"][ticket_key]
                    # Check if it has AI-analyzed features (more than just metadata)
                    features = existing.get("impacted_features", [])
                    if features and any("(" in f or len(f.split()) > 2 for f in features):
                        skipped += 1
                        continue

                # Run AI impact analysis
                result = await service.analyze_single_ticket_impact(ticket_key)

                if result.get("error"):
                    errors.append(f"{ticket_key}: {result['error']}")
                    continue

                if result.get("pr_count", 0) == 0:
                    no_prs += 1
                    continue

                # Store the AI analysis result
                impacted_features = result.get("impacted_features", [])
                if impacted_features:
                    # Get additional context for storage
                    details = await service.get_ticket_details(ticket_key)
                    customer = details.get("customer") or _extract_customer_from_labels(details.get("labels", []))

                    _store_ticket_analysis(
                        ticket_key=ticket_key,
                        customer=customer,
                        impacted_features=impacted_features,
                        priority=details.get("priority"),
                        summary=result.get("summary", "")[:100],
                        sub_component=details.get("sub_component"),
                    )
                    analyzed += 1
                    results.append(
                        {
                            "ticket_key": ticket_key,
                            "impacted_features": impacted_features,
                            "test_areas": result.get("test_areas", [])[:5],
                            "pr_count": result.get("pr_count", 0),
                        }
                    )
                else:
                    skipped += 1

            except Exception as e:
                errors.append(f"{ticket_key}: {str(e)}")

        return {
            "status": "success",
            "total_requested": len(ticket_keys),
            "analyzed": analyzed,
            "skipped": skipped,
            "no_prs": no_prs,
            "errors": errors[:10] if errors else [],
            "results": results[:10],
            "message": f"AI analysis completed for {analyzed} tickets",
        }

    except Exception as e:
        logger.error("Batch AI analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Ticket Analysis Scheduler Endpoints
# =============================================================================


@router.get("/api/ticket-analysis/scheduler/status")
async def get_ticket_analysis_scheduler_status():
    """
    Get the status of the ticket analysis scheduler.

    Returns schedule configuration, last run info, and cache statistics.
    """
    try:
        from services.ticket_analysis_scheduler import get_scheduler_status

        return get_scheduler_status()
    except ImportError:
        return {
            "enabled": False,
            "error": "Scheduler module not available",
            "hint": "Mount ticket_analysis_scheduler.py in the container",
        }
    except Exception as e:
        logger.error("Error getting scheduler status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ticket-analysis/scheduler/trigger")
async def trigger_ticket_analysis(
    limit: int = Query(default=50, description="Max tickets to analyze"),
):
    """
    Manually trigger ticket analysis job.

    Useful for:
    - Testing the scheduler
    - Running analysis on-demand outside scheduled time
    - Processing newly created tickets immediately
    """
    try:
        from services.ticket_analysis_scheduler import trigger_analysis_now

        result = await trigger_analysis_now(limit=limit)
        return result
    except ImportError:
        raise HTTPException(
            status_code=501, detail="Scheduler module not available. Mount ticket_analysis_scheduler.py"
        )
    except Exception as e:
        logger.error("Error triggering analysis: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

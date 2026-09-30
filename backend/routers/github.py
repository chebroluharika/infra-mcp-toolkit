"""
GitHub Repository Commit Tracking Router
=========================================

Provides REST endpoints for GitHub integration using DIRECT API calls.

Endpoints:
    - GET /api/github/commits - Get commits with branch cut flagging
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from config import get_default_release_id, get_github_repos, get_release_dates, get_repo_branch
from fastapi import APIRouter, HTTPException, Query
from utilities.github import categorize_commits, fetch_commits
from utilities.jira import parse_date_safe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])

# =============================================================================
# Response Cache for /commits endpoint
# =============================================================================

_commits_cache: Dict[str, Dict[str, Any]] = {}
_commits_cache_time: Dict[str, float] = {}
_COMMITS_CACHE_TTL = 120  # 2 minutes

_pending_reviews_cache: Dict[str, Dict[str, Any]] = {}
_pending_reviews_cache_time: Dict[str, float] = {}
_PENDING_REVIEWS_CACHE_TTL = 180  # 3 minutes


@router.get("/commits")
async def get_commits_after_branch_cut(
    release: Optional[str] = Query(None, description="Release ID like R134"),
    repo: Optional[str] = Query(None, description="Specific repo to query"),
):
    """
    Get commits from monitored repositories, flagging those after branch cut.

    PURPOSE:
        Returns recent commits from configured GitHub repositories with special
        flagging for commits made after the branch cut date. This helps identify
        potentially risky changes that may have missed the release train.

    WHEN TO USE:
        - Viewing "Commits After Branch Cut" on Release Readiness page
        - Identifying late commits that need review
        - Auditing code changes between branch cut and final build
        - Checking commit activity per repository

    PARAMETERS:
        - release (str): Release ID like "R135" (default: current release)
        - repo (str): Filter to specific repository (optional)

    RETURNS (after branch cut):
        {
            "release": "R135",
            "branchCutDate": "2026-01-17",
            "finalBuildDate": "2026-01-24",
            "branchCutPassed": true,
            "repos": {
                "frontend": {
                    "name": "frontend",
                    "branch": "release/135.0",
                    "url": "https://github.com/your-company/frontend",
                    "status": "success",
                    "commits": [...],
                    "flaggedCommits": [
                        {
                            "sha": "abc123",
                            "message": "Fix critical bug",
                            "author": "john.doe",
                            "date": "2026-01-18T10:00:00",
                            "url": "https://github.com/..."
                        }
                    ],
                    "stats": {
                        "total": 50,
                        "flagged": 3
                    }
                }
            },
            "summary": {
                "totalRepos": 5,
                "totalCommits": 200,
                "flaggedCommits": 10,
                "reposWithFlaggedCommits": 2
            },
            "overall_risk": "🟡",    # 🟢 (0 flagged), 🟡 (1-10), 🔴 (>10)
            "source": "github-direct"
        }

    RETURNS (before branch cut):
        {
            "branchCutPassed": false,
            "daysToBranchCut": 5,
            "message": "Branch cut is scheduled for 2026-01-17 (5 days away)",
            "repos": {},
            "summary": {...}
        }

    FLAGGING LOGIC:
        - Commits between branch cut and final build are flagged
        - Commits before branch cut are not flagged
        - Commits after final build are not flagged

    RELATED ENDPOINTS:
        - GET /api/jira/release-readiness - Full release tracking
        - GET /api/config/releases - Release dates configuration
    """
    release_id = release or get_default_release_id()
    release_dates = get_release_dates(release_id)

    # Need branch cut date for filtering
    if not release_dates or not release_dates.get("branch_cut"):
        raise HTTPException(status_code=404, detail=f"No branch cut date for {release_id}")

    branch_cut_date = parse_date_safe(release_dates["branch_cut"])
    if not branch_cut_date:
        raise HTTPException(status_code=500, detail="Invalid branch cut date format")
    branch_cut_date = branch_cut_date.replace(tzinfo=None)

    today = datetime.now().replace(tzinfo=None)

    # Check if branch cut date has passed
    branch_cut_passed = today.date() > branch_cut_date.date()
    days_to_branch_cut = (branch_cut_date.date() - today.date()).days if not branch_cut_passed else 0

    # Get final build date as end date for flagging (commits after final build are not flagged)
    final_build_date = None
    if release_dates.get("final_build"):
        final_build_date = parse_date_safe(release_dates["final_build"])
        if final_build_date:
            final_build_date = final_build_date.replace(tzinfo=None)

    # If branch cut hasn't passed yet, return early with a message
    if not branch_cut_passed:
        return {
            "release": release_id,
            "branchCutDate": release_dates.get("branch_cut"),
            "finalBuildDate": release_dates.get("final_build"),
            "generatedAt": datetime.now().isoformat(),
            "branchCutPassed": False,
            "daysToBranchCut": days_to_branch_cut,
            "message": f"Branch cut for {release_id} is scheduled for {release_dates.get('branch_cut')} ({days_to_branch_cut} days away). Flagged commits will be calculated after branch cut.",
            "repos": {},
            "summary": {
                "totalRepos": 0,
                "totalCommits": 0,
                "flaggedCommits": 0,
                "reposWithFlaggedCommits": 0,
            },
            "overall_risk": "⏳",
            "source": "github-direct",
        }

    # Check response cache
    cache_key = f"commits:{release_id}:{repo or 'all'}"
    cached = _commits_cache.get(cache_key)
    if cached and (time.time() - _commits_cache_time.get(cache_key, 0)) < _COMMITS_CACHE_TTL:
        logger.info("Returning cached commits data for %s", cache_key)
        return {**cached, "cached": True}

    # Get configured repos with their correct branch names
    repos_config = get_github_repos()
    if repo:
        # Filter to single repo if specified
        repos_config = {k: v for k, v in repos_config.items() if k == repo or v.get("repo") == repo}

    # Build fetch tasks for ALL repos, then execute in parallel
    async def fetch_repo_commits(repo_key: str, config: dict) -> tuple:
        """Fetch commits for a single repo. Returns (repo_key, config, api_result)."""
        repo_name = config.get("repo", repo_key)
        owner = config.get("owner", "netSkope")
        branch = get_repo_branch(repo_key, release_id)
        api_result = await fetch_commits(
            owner=owner,
            repo=repo_name,
            branch=branch,
            max_commits=100,
        )
        return repo_key, config, branch, api_result

    # Run ALL GitHub API calls in parallel for ~Nx speedup
    fetch_tasks = [fetch_repo_commits(rk, cfg) for rk, cfg in repos_config.items()]
    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    # Process results
    repos_data = {}
    total_commits = 0
    flagged_commits = 0

    for result in results:
        if isinstance(result, Exception):
            logger.error("Error fetching repo commits: %s", result)
            continue

        repo_key, config, branch, api_result = result
        repo_name = config.get("repo", repo_key)
        owner = config.get("owner", "netSkope")

        if "error" in api_result:
            repos_data[repo_key] = {
                "name": repo_name,
                "branch": branch,
                "status": api_result.get("status", "error"),
                "error": api_result.get("error"),
                "commits": [],
                "flaggedCommits": [],
                "stats": {"total": 0, "flagged": 0},
            }
            continue

        raw_commits = api_result.get("commits", [])

        # Categorize commits by branch cut date, up to final build date
        all_commits, after_cut_commits = categorize_commits(raw_commits, branch_cut_date, final_build_date)

        repos_data[repo_key] = {
            "name": repo_name,
            "owner": owner,
            "branch": branch,
            "url": f"https://github.com/{owner}/{repo_name}/commits/{branch}",
            "description": config.get("description", ""),
            "status": "success",
            "commits": all_commits[:20],  # Limit for response size
            "flaggedCommits": after_cut_commits,
            "stats": {
                "total": len(all_commits),
                "flagged": len(after_cut_commits),
            },
        }

        total_commits += len(all_commits)
        flagged_commits += len(after_cut_commits)

    # Determine overall risk
    overall_risk = "🟢"
    if flagged_commits > 10:
        overall_risk = "🔴"
    elif flagged_commits > 0:
        overall_risk = "🟡"

    response = {
        "release": release_id,
        "branchCutDate": release_dates.get("branch_cut"),
        "finalBuildDate": release_dates.get("final_build"),
        "generatedAt": datetime.now().isoformat(),
        "branchCutPassed": True,
        "repos": repos_data,
        "summary": {
            "totalRepos": len(repos_data),
            "totalCommits": total_commits,
            "flaggedCommits": flagged_commits,
            "reposWithFlaggedCommits": sum(1 for r in repos_data.values() if r["stats"]["flagged"] > 0),
        },
        "overall_risk": overall_risk,
        "source": "github-direct",
    }

    # Cache the response
    _commits_cache[cache_key] = response
    _commits_cache_time[cache_key] = time.time()

    return response


@router.get("/commit-analysis")
async def analyze_commit(
    owner: str = Query(..., description="Repository owner (e.g., 'netSkope')"),
    repo: str = Query(..., description="Repository name"),
    sha: str = Query(..., description="Commit SHA (full or short)"),
    include_llm: bool = Query(True, description="Include LLM semantic analysis"),
):
    """
    Analyze a single commit to understand its impact.

    PURPOSE:
        Provides detailed analysis of a commit including:
        - Files changed grouped by component
        - Predicted test areas that might be impacted
        - LLM-generated semantic summary and risk assessment

    WHEN TO USE:
        - Clicking "Analyze" on a flagged commit in Release Readiness
        - Understanding the scope and risk of a specific change
        - Identifying what tests should be run for a commit

    PARAMETERS:
        - owner: GitHub owner/organization
        - repo: Repository name
        - sha: Commit SHA (can be short or full)
        - include_llm: Whether to include LLM analysis (default: true)

    RETURNS:
        {
            "sha": "abc123",
            "message": "Fix authentication bug",
            "stats": {"total_files": 5, "additions": 120, "deletions": 30},
            "files_by_component": {
                "auth": {
                    "count": 3,
                    "files": [{"filename": "auth/login.py", "status": "modified", ...}]
                }
            },
            "test_impact": {
                "areas": {"Authentication Tests": 3, "Security Tests": 2},
                "primary_areas": ["Authentication Tests", "Security Tests"]
            },
            "llm_analysis": {
                "summary": "Fixes a security vulnerability in the login flow...",
                "risk_level": "high",
                "testing_recommendations": ["Authentication Tests", "Regression Tests"]
            }
        }
    """
    from services.commit_analyzer import get_commit_analyzer
    from utilities.github import fetch_commit_details

    # Fetch commit details from GitHub
    commit_data = await fetch_commit_details(owner, repo, sha)

    if commit_data.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Commit {sha} not found in {owner}/{repo}")
    if commit_data.get("error"):
        raise HTTPException(status_code=500, detail=commit_data.get("error"))

    # Analyze the commit
    analyzer = get_commit_analyzer()
    analysis = await analyzer.analyze_commit(commit_data, include_llm_analysis=include_llm)

    return {
        **analysis,
        "repo": repo,
        "owner": owner,
        "commit_url": commit_data.get("url", ""),
        "analyzed_at": datetime.now().isoformat(),
    }


@router.get("/pr-analysis")
async def analyze_pr(
    owner: str = Query(..., description="Repository owner (e.g., 'netSkope')"),
    repo: str = Query(..., description="Repository name"),
    pr_number: int = Query(..., description="Pull request number"),
    include_llm: bool = Query(True, description="Include LLM semantic analysis"),
):
    """
    Analyze a pull request by number to understand its impact.

    Works like commit-analysis but accepts a PR number instead of a commit SHA.
    Fetches PR files and metadata, then runs the same analysis pipeline.
    """
    from services.commit_analyzer import get_commit_analyzer
    from utilities.github import fetch_pr_details

    pr_data = await fetch_pr_details(owner, repo, pr_number, include_files=True)

    if pr_data.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"PR #{pr_number} not found in {owner}/{repo}")
    if pr_data.get("status") != "success":
        raise HTTPException(status_code=500, detail=pr_data.get("error", "Failed to fetch PR"))

    qa_recommendations = pr_data.get("qa_test_recommendations", [])

    # Adapt PR data to the shape analyze_commit expects
    commit_data = {
        "sha": f"PR-{pr_number}",
        "message": pr_data.get("title", f"PR #{pr_number}"),
        "files": pr_data.get("files", []),
        "stats": pr_data.get("stats", {}),
        "qa_test_recommendations": qa_recommendations,
    }

    analyzer = get_commit_analyzer()
    analysis = await analyzer.analyze_commit(commit_data, include_llm_analysis=include_llm)

    return {
        **analysis,
        "pr_number": pr_number,
        "pr_title": pr_data.get("title", ""),
        "pr_url": pr_data.get("url", ""),
        "pr_author": pr_data.get("author", ""),
        "pr_state": pr_data.get("state", ""),
        "merged": pr_data.get("merged", False),
        "repo": repo,
        "owner": owner,
        "qa_test_recommendations": qa_recommendations,
        "analyzed_at": datetime.now().isoformat(),
    }


@router.get("/commit-analysis/status")
async def get_analysis_status():
    """
    Check the status of NSAgent Gateway for commit analysis.
    """
    from services.commit_analyzer import get_commit_analyzer

    analyzer = get_commit_analyzer()
    status = await analyzer.is_available()

    return {
        "available": status.get("available", False),
        "backend": status.get("backend", "nsagent"),
        "base_url": status.get("base_url"),
        "model": status.get("model"),
        "configured": status.get("configured", False),
        "gateway_reachable": status.get("gateway_reachable", False),
        "error": status.get("error"),
        "setup_instructions": {
            "step1": "Set ADK_LLM_PROVIDER=nsagent in .env",
            "step2": "Set ADK_NSAGENT_BASE_URL to your gateway URL",
            "step3": "Set ADK_NSAGENT_API_TOKEN to your API token",
        },
    }


def get_size_label(additions: int, deletions: int) -> str:
    """Categorize PR size based on lines changed."""
    total = additions + deletions
    if total <= 10:
        return "XS"
    elif total <= 50:
        return "S"
    elif total <= 200:
        return "M"
    elif total <= 500:
        return "L"
    else:
        return "XL"


def get_age_category(days_old: int) -> str:
    """Categorize PR age for urgency coloring."""
    if days_old <= 1:
        return "fresh"  # green
    elif days_old <= 3:
        return "normal"  # default
    elif days_old <= 7:
        return "aging"  # yellow
    else:
        return "stale"  # red


@router.get("/pending-reviews")
async def get_pending_pr_reviews(
    release: str = Query(None, description="Release version filter (optional)"),
    include_details: bool = Query(True, description="Include CI status and review details (slower)"),
):
    """
    Get open pull requests pending review with full details.

    Fetches open PRs from configured repositories with:
    - CI/CD status (checks)
    - Review status (approved, changes requested, pending)
    - Size indicators (lines changed)
    - Labels, comments, commits count
    - Merge conflict status
    - Age-based urgency

    RETURNS:
        {
            "pull_requests": [
                {
                    "id": 12345,
                    "number": 234,
                    "title": "Fix authentication bug",
                    "repo": "client",
                    "author": "johndoe",
                    "age": "2 days",
                    "age_days": 2,
                    "age_category": "normal",
                    "target_branch": "Release135",
                    "size": "M",
                    "additions": 120,
                    "deletions": 30,
                    "changed_files": 5,
                    "commits": 3,
                    "comments": 2,
                    "labels": ["bug", "priority-high"],
                    "mergeable": true,
                    "ci_status": "success",
                    "review_status": "approved",
                    "reviews_summary": {"approved": 1, "changes_requested": 0, "pending": 1}
                }
            ],
            "total": 5
        }
    """
    import httpx
    from config import get_github_repos, settings

    github_token = settings.github_token
    if not github_token:
        return {"pull_requests": [], "total": 0, "error": "GitHub token not configured"}

    # Check cache
    cache_key = f"pending_reviews:{release or 'all'}:{include_details}"
    if cache_key in _pending_reviews_cache:
        cache_age = time.time() - _pending_reviews_cache_time.get(cache_key, 0)
        if cache_age < _PENDING_REVIEWS_CACHE_TTL:
            logger.debug("Returning cached pending reviews (age: %.0fs)", cache_age)
            return _pending_reviews_cache[cache_key]

    repos = get_github_repos()
    all_prs = []
    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient(timeout=60) as client:
        for repo_key, repo_config in repos.items():
            owner = repo_config.get("owner", "netSkope")
            repo = repo_config.get("repo", repo_key)

            try:
                # Fetch open PRs with full details
                response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/pulls",
                    headers=headers,
                    params={"state": "open", "sort": "created", "direction": "desc", "per_page": 20},
                )

                if response.status_code != 200:
                    logger.warning("Failed to fetch PRs for %s/%s: %s", owner, repo, response.status_code)
                    continue

                prs = response.json()

                for pr in prs:
                    pr_number = pr.get("number")

                    # Calculate age
                    created_at = pr.get("created_at", "")
                    age = ""
                    days_old = 0
                    if created_at:
                        try:
                            created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            days_old = (datetime.now(created_date.tzinfo) - created_date).days
                            if days_old == 0:
                                hours_old = (datetime.now(created_date.tzinfo) - created_date).seconds // 3600
                                age = f"{hours_old}h"
                            else:
                                age = f"{days_old}d"
                        except Exception:
                            age = "?"

                    # Basic PR data
                    additions = pr.get("additions", 0) or 0
                    deletions = pr.get("deletions", 0) or 0
                    changed_files = pr.get("changed_files", 0) or 0

                    # Get labels
                    labels = [label.get("name", "") for label in pr.get("labels", [])]

                    # Get reviewers and assignees
                    reviewers = [r.get("login", "") for r in pr.get("requested_reviewers", [])]
                    assignees = [a.get("login", "") for a in pr.get("assignees", [])]

                    pr_data = {
                        "id": pr.get("id"),
                        "number": pr_number,
                        "title": pr.get("title"),
                        "repo": repo,
                        "owner": owner,
                        "author": pr.get("user", {}).get("login", "Unknown"),
                        "age": age,
                        "age_days": days_old,
                        "age_category": get_age_category(days_old),
                        "created_at": created_at,
                        "updated_at": pr.get("updated_at", ""),
                        "url": pr.get("html_url"),
                        "target_branch": pr.get("base", {}).get("ref", ""),
                        "source_branch": pr.get("head", {}).get("ref", ""),
                        "additions": additions,
                        "deletions": deletions,
                        "changed_files": changed_files,
                        "size": get_size_label(additions, deletions),
                        "commits": pr.get("commits", 0) or 0,
                        "comments": pr.get("comments", 0) or 0,
                        "review_comments": pr.get("review_comments", 0) or 0,
                        "labels": labels,
                        "reviewers": reviewers,
                        "assignees": assignees,
                        "draft": pr.get("draft", False),
                        "mergeable": pr.get("mergeable"),  # Can be None if not yet computed
                        "mergeable_state": pr.get("mergeable_state", "unknown"),
                        # Defaults for CI and review status
                        "ci_status": "unknown",
                        "review_status": "pending",
                        "reviews_summary": {"approved": 0, "changes_requested": 0, "pending": len(reviewers)},
                    }

                    all_prs.append(pr_data)

            except Exception as e:
                logger.warning("Error fetching PRs for %s/%s: %s", owner, repo, e)
                continue

        # Fetch CI status and reviews in parallel using shared utility
        if include_details and all_prs:
            from utilities.github import fetch_pr_details as _fetch_pr_details

            async def _enrich_pr(pr_item):
                """Enrich a PR dict with CI status and review data via shared utility."""
                details = await _fetch_pr_details(
                    owner=pr_item["owner"],
                    repo=pr_item["repo"],
                    pr_number=pr_item["number"],
                    include_files=False,
                    include_ci_status=True,
                    include_reviews=True,
                )
                if details.get("status") == "success":
                    pr_item["ci_status"] = details.get("ci_status", "unknown")
                    pr_item["review_status"] = details.get("review_status", "pending")
                    pr_item["reviews_summary"] = details.get("reviews_summary", pr_item["reviews_summary"])

            import asyncio

            await asyncio.gather(*[_enrich_pr(pr) for pr in all_prs[:15]])

    # Filter out draft PRs
    active_prs = [pr for pr in all_prs if not pr.get("draft")]

    # Enhanced priority scoring system
    def calculate_priority_score(pr):
        """
        Calculate priority score for a PR. Lower score = higher priority.

        Factors considered:
        - CI failed: +0 (highest priority - needs fixing)
        - Changes requested: +10 (author needs to act)
        - Merge conflicts: +20 (blocking merge)
        - Has urgent/hotfix label: +30
        - Stale (>7 days): +40
        - Aging (4-7 days): +50
        - Pending review: +60
        - Approved & CI passing: +100 (ready to merge, less urgent)
        - Fresh: +80
        """
        score = 0

        # CI status (failed CI is highest priority)
        ci_status = pr.get("ci_status", "unknown")
        if ci_status == "failure":
            score += 0  # Highest priority
        elif ci_status == "pending":
            score += 50
        elif ci_status == "success":
            score += 70
        else:
            score += 60  # Unknown

        # Review status
        review_status = pr.get("review_status", "pending")
        if review_status == "changes_requested":
            score += 5  # High priority - author needs to act
        elif review_status == "pending":
            score += 30
        elif review_status == "partially_approved":
            score += 40
        elif review_status == "approved":
            score += 80  # Lower priority - ready to merge

        # Merge conflicts
        if pr.get("mergeable") is False:
            score -= 30  # Boost priority (lower score)

        # Urgent labels
        labels = [lbl.lower() for lbl in pr.get("labels", [])]
        urgent_labels = ["urgent", "hotfix", "critical", "blocker", "priority-high", "p1", "p0"]
        if any(ul in label for label in labels for ul in urgent_labels):
            score -= 40  # Boost priority

        # Age factor
        age_category = pr.get("age_category", "normal")
        if age_category == "stale":
            score -= 20  # Boost priority
        elif age_category == "aging":
            score -= 10
        elif age_category == "fresh":
            score += 20  # Lower priority

        # Store the score for display/debugging
        pr["priority_score"] = score

        return score

    # Sort by priority score (lower = higher priority), then by created_at
    active_prs.sort(key=lambda x: (calculate_priority_score(x), x.get("created_at", "")))

    result = {"pull_requests": active_prs, "total": len(active_prs)}

    # Cache the result
    _pending_reviews_cache[cache_key] = result
    _pending_reviews_cache_time[cache_key] = time.time()

    return result

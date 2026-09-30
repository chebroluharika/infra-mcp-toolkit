"""
GitHub Utilities
================
Utility functions for GitHub API interactions.
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx
from config import settings
from utilities.jira import parse_date_safe

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def parse_version_tag(tag_name: str) -> Tuple[int, ...]:
    """
    Parse a version tag into a tuple of integers for comparison.

    Handles formats like:
    - v25.148.4 -> (25, 148, 4)
    - 25.148.4 -> (25, 148, 4)
    - v107.0.10 -> (107, 0, 10)
    - 20260121.1.1 -> (20260121, 1, 1)

    Returns a tuple of integers for comparison. Non-numeric parts are ignored.
    Returns (0,) for unparseable versions so they sort to the beginning.
    """
    # Remove 'v' prefix if present
    version = tag_name.lstrip("v")

    # Split by dots and convert to integers
    parts = []
    for part in version.split("."):
        # Extract numeric portion
        match = re.match(r"^(\d+)", part)
        if match:
            parts.append(int(match.group(1)))

    return tuple(parts) if parts else (0,)


def get_latest_semver_tag(tags: List[Dict], version_prefix: str = None) -> Optional[Dict]:
    """
    Get the latest tag by semantic version (not by creation date).

    Args:
        tags: List of tag dicts with 'name' field
        version_prefix: Optional prefix to filter tags (e.g., 'v25.' to only consider v25.x.x tags)

    Returns:
        The tag with the highest semantic version, or None if no tags
    """
    if not tags:
        return None

    # Filter tags by prefix if specified
    filtered_tags = tags
    if version_prefix:
        filtered_tags = [t for t in tags if t.get("name", "").startswith(version_prefix)]
        # If no tags match the prefix, fall back to all tags
        if not filtered_tags:
            filtered_tags = tags

    # Sort tags by parsed version (descending)
    sorted_tags = sorted(filtered_tags, key=lambda t: parse_version_tag(t.get("name", "")), reverse=True)

    return sorted_tags[0] if sorted_tags else None


def get_github_headers() -> Dict[str, str]:
    """Get headers for GitHub API requests with optional auth."""
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "QE-Dashboard/1.0"}
    token = getattr(settings, "github_token", None)
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


async def fetch_commits(  # pylint: disable=too-many-return-statements
    owner: str, repo: str, branch: str, max_commits: int = 50
) -> Dict:
    """
    Fetch commits from GitHub API.

    Returns dict with 'commits' list and 'status' ('success', 'not_found', 'rate_limited', 'error').
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits"
    params = {"sha": branch, "per_page": min(max_commits, 100)}

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, params=params, headers=get_github_headers())

            if response.status_code == 404:
                # Could be: repo doesn't exist, wrong name, or token lacks 'repo' scope
                err_msg = f"Not found or no access: {owner}/{repo}@{branch}. Check repo name and token permissions."
                return {"error": err_msg, "commits": [], "status": "not_found"}
            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
                if remaining == "0":
                    return {"error": "Rate limited. Try again later.", "commits": [], "status": "rate_limited"}
                return {"error": "Access denied. Token may lack 'repo' scope.", "commits": [], "status": "forbidden"}
            if response.status_code != 200:
                return {"error": f"API error: {response.status_code}", "commits": [], "status": "error"}

            commits = [
                {
                    "sha": commit.get("sha", "")[:8],
                    "full_sha": commit.get("sha", ""),
                    "message": commit.get("commit", {}).get("message", "").split("\n")[0][:100],
                    "author": commit.get("commit", {}).get("author", {}).get("name", "Unknown"),
                    "date": commit.get("commit", {}).get("author", {}).get("date", ""),
                    "url": commit.get("html_url", ""),
                }
                for commit in response.json()
            ]
            return {"commits": commits, "status": "success", "count": len(commits)}

    except httpx.TimeoutException:
        return {"error": "Request timed out", "commits": [], "status": "timeout"}
    except (httpx.HTTPError, ValueError) as err:
        logger.error("GitHub API error: %s", err)
        return {"error": str(err), "commits": [], "status": "error"}


async def fetch_commit_details(owner: str, repo: str, sha: str) -> Dict:
    """
    Fetch detailed commit information including files changed.

    Uses GitHub API /repos/{owner}/{repo}/commits/{sha} to get:
    - Full commit message
    - Files changed with additions/deletions
    - Patch content for each file

    Returns dict with 'files', 'stats', and commit metadata.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{sha}"

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, headers=get_github_headers())

            if response.status_code == 404:
                return {"error": f"Commit not found: {sha}", "status": "not_found"}
            if response.status_code == 403:
                return {"error": "Rate limited or access denied", "status": "forbidden"}
            if response.status_code != 200:
                return {"error": f"API error: {response.status_code}", "status": "error"}

            data = response.json()

            # Extract file changes
            files = []
            for f in data.get("files", []):
                files.append(
                    {
                        "filename": f.get("filename", ""),
                        "status": f.get("status", ""),  # added, removed, modified, renamed
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "changes": f.get("changes", 0),
                        "patch": f.get("patch", "")[:500] if f.get("patch") else "",  # Truncate patch
                    }
                )

            # Extract commit metadata
            commit_data = data.get("commit", {})

            return {
                "sha": data.get("sha", "")[:8],
                "full_sha": data.get("sha", ""),
                "message": commit_data.get("message", ""),
                "author": commit_data.get("author", {}).get("name", "Unknown"),
                "date": commit_data.get("author", {}).get("date", ""),
                "url": data.get("html_url", ""),
                "files": files,
                "stats": {
                    "total_files": len(files),
                    "additions": data.get("stats", {}).get("additions", 0),
                    "deletions": data.get("stats", {}).get("deletions", 0),
                    "total_changes": data.get("stats", {}).get("total", 0),
                },
                "status": "success",
            }

    except httpx.TimeoutException:
        return {"error": "Request timed out", "status": "timeout"}
    except (httpx.HTTPError, ValueError) as err:
        logger.error("GitHub API error fetching commit details: %s", err)
        return {"error": str(err), "status": "error"}


def extract_qa_test_recommendations(body: Optional[str]) -> List[str]:
    """
    Extract QA Test Recommendations from a PR description body.

    Looks for a markdown section with heading containing 'QA Test Recommendation'
    (case-insensitive), then extracts bullet points or numbered list items from it.
    Stops at the next markdown heading or end of body.

    Returns a list of recommendation strings (empty list if section not found).
    """
    if not body:
        return []

    # Match heading like "## QA Test Recommendations", "### QA Test Recommendations", etc.
    heading_pattern = re.compile(
        r"^#{1,4}\s+.*QA\s+Test\s+Recommend[^\n]*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = heading_pattern.search(body)
    if not match:
        return []

    # Extract content between this heading and the next heading (or end of body)
    start = match.end()
    next_heading = re.search(r"^#{1,4}\s+", body[start:], re.MULTILINE)
    section = body[start : start + next_heading.start()] if next_heading else body[start:]

    recommendations = []
    for line in section.strip().splitlines():
        line = line.strip()
        # Match bullet points (- or *) or numbered items (1. 2.)
        item_match = re.match(r"^(?:[-*]|\d+[.)]\s*)\s*(.*)", line)
        if item_match:
            text = item_match.group(1).strip()
            if text:
                recommendations.append(text)
        elif line and not line.startswith("#"):
            # Plain text lines that aren't empty or headings
            if len(line) > 5:
                recommendations.append(line)

    return recommendations


async def fetch_pr_details(
    owner: str,
    repo: str,
    pr_number: int,
    include_files: bool = True,
    include_ci_status: bool = False,
    include_reviews: bool = False,
) -> Dict:
    """
    Fetch pull request details from GitHub API.

    Single shared utility for all PR data fetching. Used by:
    - Escalation Analysis: metadata + files for AI analysis
    - Pending PR Reviews: metadata + CI status + reviews

    Args:
        owner: Repository owner (e.g., 'netSkope')
        repo: Repository name
        pr_number: PR number
        include_files: Fetch files changed with patches (for analysis)
        include_ci_status: Fetch CI check status via commit status API
        include_reviews: Fetch review status (approved/changes_requested)

    Returns dict with PR metadata and requested details. Always includes 'status' field.
    """
    headers = get_github_headers()
    base_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            # Always fetch PR metadata
            pr_response = await client.get(base_url, headers=headers)

            if pr_response.status_code == 404:
                return {"error": f"PR #{pr_number} not found in {owner}/{repo}", "status": "not_found"}
            if pr_response.status_code == 403:
                return {"error": "Rate limited or access denied", "status": "forbidden"}
            if pr_response.status_code != 200:
                return {"error": f"API error: {pr_response.status_code}", "status": "error"}

            pr_data = pr_response.json()

            full_body = pr_data.get("body") or ""
            qa_recommendations = extract_qa_test_recommendations(full_body)

            result = {
                "pr_number": pr_number,
                "title": pr_data.get("title", ""),
                "body": full_body[:2000],
                "state": pr_data.get("state", ""),
                "author": pr_data.get("user", {}).get("login", "Unknown"),
                "url": pr_data.get("html_url", ""),
                "merged": pr_data.get("merged", False),
                "merged_at": pr_data.get("merged_at"),
                "created_at": pr_data.get("created_at"),
                "qa_test_recommendations": qa_recommendations,
                "stats": {
                    "total_files": pr_data.get("changed_files", 0),
                    "additions": pr_data.get("additions", 0),
                    "deletions": pr_data.get("deletions", 0),
                    "total_changes": pr_data.get("additions", 0) + pr_data.get("deletions", 0),
                },
                "status": "success",
            }

            # Fetch files changed (for commit analysis / escalation analysis)
            if include_files:
                files_url = f"{base_url}/files"
                files_response = await client.get(files_url, headers=headers, params={"per_page": 100})
                files = []
                if files_response.status_code == 200:
                    for f in files_response.json():
                        files.append(
                            {
                                "filename": f.get("filename", ""),
                                "status": f.get("status", ""),
                                "additions": f.get("additions", 0),
                                "deletions": f.get("deletions", 0),
                                "changes": f.get("changes", 0),
                                "patch": (f.get("patch") or "")[:500],
                            }
                        )
                result["files"] = files
                result["stats"]["total_files"] = len(files)

            # Fetch CI status via last commit's combined status
            if include_ci_status:
                ci_status = "unknown"
                try:
                    commits_resp = await client.get(f"{base_url}/commits", headers=headers, params={"per_page": 1})
                    if commits_resp.status_code == 200:
                        commits = commits_resp.json()
                        if commits:
                            sha = commits[-1].get("sha", "")
                            if sha:
                                status_resp = await client.get(
                                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{sha}/status",
                                    headers=headers,
                                )
                                if status_resp.status_code == 200:
                                    ci_status = status_resp.json().get("state", "unknown")
                except Exception as e:
                    logger.debug("Error fetching CI status for PR #%s: %s", pr_number, e)
                result["ci_status"] = ci_status

            # Fetch review status
            if include_reviews:
                reviews_summary = {"approved": 0, "changes_requested": 0, "pending": 0}
                review_status = "pending"
                try:
                    reviews_resp = await client.get(f"{base_url}/reviews", headers=headers)
                    if reviews_resp.status_code == 200:
                        latest_reviews = {}
                        for review in reviews_resp.json():
                            user = review.get("user", {}).get("login", "")
                            state = review.get("state", "").lower()
                            if user and state in ["approved", "changes_requested", "pending"]:
                                latest_reviews[user] = state

                        approved = sum(1 for s in latest_reviews.values() if s == "approved")
                        changes_requested = sum(1 for s in latest_reviews.values() if s == "changes_requested")
                        reviewers = [r.get("login", "") for r in pr_data.get("requested_reviewers", [])]
                        pending = len(reviewers)

                        reviews_summary = {
                            "approved": approved,
                            "changes_requested": changes_requested,
                            "pending": pending,
                        }

                        if changes_requested > 0:
                            review_status = "changes_requested"
                        elif approved > 0 and pending == 0:
                            review_status = "approved"
                        elif approved > 0:
                            review_status = "partially_approved"
                except Exception as e:
                    logger.debug("Error fetching reviews for PR #%s: %s", pr_number, e)
                result["reviews_summary"] = reviews_summary
                result["review_status"] = review_status

            return result

    except httpx.TimeoutException:
        return {"error": "Request timed out", "status": "timeout"}
    except (httpx.HTTPError, ValueError) as err:
        logger.error("GitHub API error fetching PR details: %s", err)
        return {"error": str(err), "status": "error"}


def categorize_commits(commits: List[Dict], cutoff_date: datetime, end_date: datetime = None) -> tuple:
    """
    Categorize commits as before/after a cutoff date, up to an optional end date.
    Commits AFTER the cutoff day (next day onwards) and BEFORE/ON the end date are flagged.

    Args:
        commits: List of commit dictionaries
        cutoff_date: Start date (branch cut) - commits after this are flagged
        end_date: End date (final build) - commits after this are NOT flagged (optional)

    Returns (all_commits, flagged_commits) with isAfterCutoff flag added.
    """
    # Use end of cutoff day (23:59:59) so commits ON the cutoff day are not flagged
    cutoff_end_of_day = cutoff_date.replace(hour=23, minute=59, second=59, tzinfo=None)

    # Use end of end_date day if provided
    end_date_end_of_day = None
    if end_date:
        end_date_end_of_day = end_date.replace(hour=23, minute=59, second=59, tzinfo=None)

    all_commits, flagged = [], []
    for commit in commits:
        commit_date = parse_date_safe(commit.get("date"))
        commit_date_naive = commit_date.replace(tzinfo=None) if commit_date else None

        # Commit is flagged if:
        # 1. It's after the branch cut date
        # 2. AND (no end_date OR it's before/on the end_date)
        is_after_cutoff = commit_date_naive > cutoff_end_of_day if commit_date_naive else False
        is_before_end = True
        if end_date_end_of_day and commit_date_naive:
            is_before_end = commit_date_naive <= end_date_end_of_day

        is_flagged = is_after_cutoff and is_before_end

        commit_data = {
            **commit,
            "isAfterBranchCut": is_flagged,
            "formattedDate": commit_date.strftime("%Y-%m-%d %H:%M") if commit_date else commit.get("date"),
        }
        all_commits.append(commit_data)
        if is_flagged:
            flagged.append(commit_data)

    return all_commits, flagged


async def fetch_repo_tags(owner: str, repo: str, per_page: int = 30, fetch_dates: bool = False) -> Dict:
    """
    Fetch tags from a GitHub repository.

    Args:
        owner: Repository owner
        repo: Repository name
        per_page: Number of tags to fetch
        fetch_dates: If True, fetch commit dates for each tag (slow, makes N+1 API calls)
                    If False, just return tag names without dates (fast, single API call)

    Returns dict with 'tags' list and 'status'.
    Each tag has: name, commit_sha, created_at (only if fetch_dates=True)
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/tags"
    params = {"per_page": per_page}

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            response = await client.get(url, params=params, headers=get_github_headers())

            if response.status_code == 404:
                return {"error": f"Repository not found: {owner}/{repo}", "tags": [], "status": "not_found"}
            if response.status_code == 403:
                return {"error": "Access denied or rate limited", "tags": [], "status": "forbidden"}
            if response.status_code != 200:
                return {"error": f"API error: {response.status_code}", "tags": [], "status": "error"}

            tags_data = response.json()
            tags = []

            for idx, tag in enumerate(tags_data):
                tag_name = tag.get("name", "")
                commit_sha = tag.get("commit", {}).get("sha", "")
                commit_url = tag.get("commit", {}).get("url", "")

                created_at = None
                # Only fetch dates if requested and only for first 5 tags to limit API calls
                if fetch_dates and commit_url and idx < 5:
                    try:
                        commit_response = await client.get(commit_url, headers=get_github_headers(), timeout=5.0)
                        if commit_response.status_code == 200:
                            commit_data = commit_response.json()
                            created_at = commit_data.get("commit", {}).get("committer", {}).get("date")
                    except Exception as e:
                        logger.warning("Failed to fetch commit date for tag %s: %s", tag_name, e)

                tags.append(
                    {
                        "name": tag_name,
                        "commit_sha": commit_sha[:8] if commit_sha else "",
                        "full_sha": commit_sha,
                        "created_at": created_at,
                    }
                )

            return {"tags": tags, "status": "success", "count": len(tags)}

    except httpx.TimeoutException:
        return {"error": "Request timed out", "tags": [], "status": "timeout"}
    except (httpx.HTTPError, ValueError) as err:
        logger.error("GitHub API error fetching tags: %s", err)
        return {"error": str(err), "tags": [], "status": "error"}


def find_tag_after_date(tags: List[Dict], after_date: datetime) -> Optional[Dict]:
    """
    Find the first tag created after a given date.

    Args:
        tags: List of tag dicts with 'name' and 'created_at' fields
        after_date: The cutoff date (e.g., branch cut date)

    Returns:
        The first tag created after the date, or None if not found
    """
    # Sort tags by created_at descending (newest first)
    dated_tags = []
    for tag in tags:
        created_at_str = tag.get("created_at")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                dated_tags.append({**tag, "created_at_dt": created_at})
            except (ValueError, TypeError):
                continue

    # Sort by date ascending (oldest first)
    dated_tags.sort(key=lambda t: t["created_at_dt"])

    # Find the first tag after the cutoff date
    for tag in dated_tags:
        if tag["created_at_dt"].replace(tzinfo=None) > after_date:
            return {
                "name": tag["name"],
                "commit_sha": tag.get("commit_sha"),
                "created_at": tag.get("created_at"),
            }

    return None

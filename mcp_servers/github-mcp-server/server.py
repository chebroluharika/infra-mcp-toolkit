# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.0.0",
#   "httpx>=0.27.0",
#   "python-dotenv>=1.0.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
GitHub MCP Server
Exposes GitHub API as MCP tools for AI agents

Usage:
    uv run server.py

Environment Variables:
    GITHUB_TOKEN - GitHub personal access token
    GITHUB_ORG - GitHub organization (default: your-company)
"""

import os
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("github-mcp-server")

# Default release from environment variable (single source of truth - REQUIRED)
DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
if not DEFAULT_RELEASE:
    raise EnvironmentError(
        "CURRENT_RELEASE environment variable is required! "
        "Set it in your .env file or docker-compose.yml (e.g., CURRENT_RELEASE=R134)"
    )

# Repository configuration
DEFAULT_REPOS = [
    "client",
    "service",
    "enrollment-service",
    "device-classification",
]


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool()
async def github_get_commits(release: str = DEFAULT_RELEASE, repo: str = "", max_commits: int = 50) -> Dict[str, Any]:
    """
    Get recent commits from a GitHub repository.

    Use when asked: "recent commits", "what was committed?", "code changes"

    Args:
        release: Release ID like "R134" or "135" (will be normalized to R135)
        repo: Repository name (optional, e.g., "client", "device-classification")
        max_commits: Maximum commits to return (default 50)

    Returns:
        List of commits with author, message, and date
    """
    # Call backend API which has correct branch config per repo
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize release format: "135.0" → "R135", "R135.0" → "R135", "R135" → "R135"
    release_str = str(release).strip().upper()
    # Remove R prefix if present
    if release_str.startswith("R"):
        release_str = release_str[1:]
    # Extract numeric part (e.g., "135.0" → "135")
    release_num = release_str.split(".")[0]
    release_id = f"R{release_num}"

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            params = {"release": release_id}
            if repo:
                params["repo"] = repo
            response = await client.get(f"{api_base}/api/github/commits", params=params)

            if response.status_code != 200:
                return {"repo": repo, "error": f"Backend returned {response.status_code}", "commits": []}

            data = response.json()
            repos_data = data.get("repos", {})

            # If no specific repo, aggregate all repos
            if not repo:
                all_commits = []
                for repo_name, repo_val in repos_data.items():
                    for commit in repo_val.get("commits", []):
                        commit["repo"] = repo_name
                        all_commits.append(commit)

                # Sort by date descending
                all_commits.sort(key=lambda x: x.get("date", ""), reverse=True)
                commits = all_commits[:max_commits]
                repo = "all repos"
                branch = "multiple"
            else:
                # Find the specific repo data
                repo_data = None
                for key, val in repos_data.items():
                    if key == repo or val.get("name") == repo:
                        repo_data = val
                        break

                if not repo_data:
                    return {"repo": repo, "error": f"Repository {repo} not found", "commits": []}

                commits = repo_data.get("commits", [])[:max_commits]
                branch = repo_data.get("branch", "main")

            # Build nice display
            display_lines = [
                f"## 📝 Recent Commits for {repo or 'all repos'}",
                "",
                f"**Branch:** {branch} | **Release:** {release_id} | **Showing:** {len(commits)} commits",
                "",
            ]

            if commits:
                display_lines.extend(
                    [
                        "| Date | Author | Message |",
                        "|------|--------|---------|",
                    ]
                )
                for commit in commits[:15]:
                    date = commit.get("date", "")[:10]  # Just the date part
                    author = commit.get("author", "Unknown")
                    msg = commit.get("message", "")
                    # Truncate long messages
                    if len(msg) > 60:
                        msg = msg[:60] + "..."
                    # Escape pipe characters in message
                    msg = msg.replace("|", "\\|")
                    display_lines.append(f"| {date} | {author} | {msg} |")

                if len(commits) > 15:
                    display_lines.append(f"\n*... and {len(commits) - 15} more commits*")
            else:
                display_lines.append("No commits found for this release.")

            return {
                "repo": repo,
                "branch": branch,
                "release": release,
                "total_commits": len(commits),
                "commits": commits,
                "source": "backend-api",
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"repo": repo, "error": str(err), "commits": []}


@mcp.tool()
async def github_get_commits_after_branch_cut(release: str = DEFAULT_RELEASE, repo: str = "") -> Dict[str, Any]:
    """
    Get commits made AFTER branch cut (risky commits that need review).

    Use when asked: "commits after branch cut", "late commits", "post-branch commits", "flagged commits"

    Args:
        release: Release ID like "R134" or "135" (will be normalized to R135)
        repo: Repository name (optional, e.g., "client", "device-classification")

    Returns:
        Commits that were added after branch cut date
    """
    # Call backend API which has correct branch config per repo
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize release format: "135.0" → "R135", "R135.0" → "R135", "R135" → "R135"
    release_str = str(release).strip().upper()
    # Remove R prefix if present
    if release_str.startswith("R"):
        release_str = release_str[1:]
    # Extract numeric part (e.g., "135.0" → "135")
    release_num = release_str.split(".")[0]
    release_id = f"R{release_num}"

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            url = f"{api_base}/api/github/commits"
            params = {"release": release_id}
            if repo:
                params["repo"] = repo
            response = await client.get(url, params=params)

            if response.status_code != 200:
                return {
                    "repo": repo,
                    "release": release,
                    "error": f"Backend API returned {response.status_code}",
                    "commits": [],
                    "source": "github-mcp",
                }

            data = response.json()
            repos_data = data.get("repos", {})
            branch_cut_date = data.get("branchCutDate", "")

            # If no specific repo, aggregate all repos
            if not repo:
                all_flagged = []
                repo_names = []
                for repo_name, repo_val in repos_data.items():
                    repo_names.append(repo_name)
                    for commit in repo_val.get("flaggedCommits", []):
                        commit["repo"] = repo_name
                        all_flagged.append(commit)

                # Sort by date descending
                all_flagged.sort(key=lambda x: x.get("date", ""), reverse=True)
                flagged_commits = all_flagged
                repo = "all repos"
                branch = "multiple"
            else:
                # Find the specific repo data
                repo_data = None
                for key, val in repos_data.items():
                    if key == repo or val.get("name") == repo:
                        repo_data = val
                        break

                if not repo_data:
                    return {
                        "repo": repo,
                        "release": release,
                        "error": f"Repository {repo} not found",
                        "commits": [],
                        "source": "github-mcp",
                    }

                branch = repo_data.get("branch", "main")
                flagged_commits = repo_data.get("flaggedCommits", [])

            # Determine risk level
            if len(flagged_commits) == 0:
                risk = "low"
                risk_emoji = "🟢"
                message = "No commits after branch cut - all clear!"
            elif len(flagged_commits) <= 5:
                risk = "medium"
                risk_emoji = "🟡"
                message = f"{len(flagged_commits)} commits after branch cut - review recommended"
            else:
                risk = "high"
                risk_emoji = "🔴"
                message = f"{len(flagged_commits)} commits after branch cut - review required!"

            # Build display
            display_lines = [
                f"## {risk_emoji} Commits After Branch Cut for {release}",
                "",
                f"**Repo:** {repo} | **Branch:** {branch} | **Branch Cut:** {branch_cut_date}",
                f"**Commits After Cut:** {len(flagged_commits)} | **Risk Level:** {risk.upper()}",
                "",
            ]

            if flagged_commits:
                display_lines.extend(
                    [
                        "### ⚠️ Late Commits (Need Review)",
                        "",
                        "| Date | Author | Message |",
                        "|------|--------|---------|",
                    ]
                )
                for commit in flagged_commits[:15]:
                    date = commit.get("date", "")[:10]
                    author = commit.get("author", "Unknown")
                    msg = commit.get("message", "")
                    if len(msg) > 50:
                        msg = msg[:50] + "..."
                    msg = msg.replace("|", "\\|")
                    display_lines.append(f"| {date} | {author} | {msg} |")

                if len(flagged_commits) > 15:
                    display_lines.append(f"\n*... and {len(flagged_commits) - 15} more commits*")
            else:
                display_lines.extend(
                    [
                        "### ✅ All Clear!",
                        "",
                        "No commits were made after branch cut. The release branch is clean.",
                    ]
                )

            return {
                "repo": repo,
                "branch": branch,
                "release": release,
                "branch_cut_date": branch_cut_date,
                "commits_after_cut": len(flagged_commits),
                "risk_level": risk,
                "risk_emoji": risk_emoji,
                "message": message,
                "commits": flagged_commits[:20],
                "source": "github-mcp",
                "display": "\n".join(display_lines),
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"repo": repo, "release": release, "error": str(err), "commits": [], "source": "github-mcp"}


@mcp.tool()
async def github_get_commits_before_branch_cut(repo: str, release: str = DEFAULT_RELEASE) -> Dict[str, Any]:
    """
    Get commits made BEFORE branch cut (that made it into release).

    Use when asked: "commits before branch cut", "what's in the release?"

    Args:
        repo: Repository name (e.g., "client", "device-classification")
        release: Release ID like "R134"

    Returns:
        Commits that were included before branch cut date
    """
    # Call backend API which has correct branch config per repo
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            url = f"{api_base}/api/github/commits"
            params = {"release": release, "repo": repo}
            response = await client.get(url, params=params)

            if response.status_code != 200:
                return {
                    "repo": repo,
                    "release": release,
                    "error": f"Backend API returned {response.status_code}",
                    "commits": [],
                    "source": "github-mcp",
                }

            data = response.json()
            repos_data = data.get("repos", {})
            branch_cut_date = data.get("branchCutDate", "")

            # Find the repo data
            repo_data = None
            for key, val in repos_data.items():
                if key == repo or val.get("name") == repo:
                    repo_data = val
                    break

            if not repo_data:
                return {
                    "repo": repo,
                    "release": release,
                    "error": f"Repository {repo} not found in response",
                    "commits": [],
                    "source": "github-mcp",
                }

            all_commits = repo_data.get("commits", [])
            branch = repo_data.get("branch", "main")

            # Filter to before branch cut only
            before_commits = [c for c in all_commits if not c.get("isAfterBranchCut", False)]

            # Create formatted display text
            display_lines = [
                f"## 📦 Commits Before Branch Cut: {repo}",
                "",
                f"**Branch:** {branch} | **Release:** {release} | **Branch Cut:** {branch_cut_date}",
                f"**Total Commits:** {len(before_commits)}",
                "",
            ]

            if before_commits:
                display_lines.extend(
                    [
                        "### Recent Commits",
                        "",
                        "| SHA | Author | Message |",
                        "|-----|--------|---------|",
                    ]
                )
                for commit in before_commits[:10]:
                    sha = commit.get("sha", commit.get("hash", ""))[:7]
                    author = commit.get("author", "Unknown")
                    commit_msg = commit.get("message", "")
                    msg = (commit_msg[:45] + "...") if len(commit_msg) > 45 else commit_msg
                    display_lines.append(f"| {sha} | {author} | {msg} |")

                if len(before_commits) > 10:
                    display_lines.append(f"\n*... and {len(before_commits) - 10} more commits*")
            else:
                display_lines.append("No commits found before branch cut.")

            return {
                "repo": repo,
                "branch": branch,
                "release": release,
                "branch_cut_date": branch_cut_date,
                "total_commits_before_cut": len(before_commits),
                "commits": before_commits[:20],
                "message": f"{len(before_commits)} commits included in {release} before branch cut",
                "display": "\n".join(display_lines),
                "source": "github-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"repo": repo, "release": release, "error": str(err), "commits": [], "source": "github-mcp"}


@mcp.tool()
async def github_get_branches(repo: str) -> Dict[str, Any]:
    """
    List GitHub repository branches.

    ONLY use for: "list branches", "what branches exist?"

    DO NOT use for:
    - "when is branch cut?" → use calendar_get_release_dates (date question)
    - "branch cut status" → use jira_get_milestone_status (milestone status)

    Args:
        repo: Repository name

    Returns:
        List of branches
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/github/branches", params={"repo": repo})

            if response.status_code != 200:
                return {"repo": repo, "error": f"Backend returned {response.status_code}", "total_branches": 0}

            return response.json()
        except (httpx.HTTPError, ValueError) as err:
            return {"repo": repo, "error": str(err), "total_branches": 0}


@mcp.tool()
async def github_compare_branches(repo: str, base: str = "main", head: str = "release/134") -> Dict[str, Any]:
    """
    Compare two branches to see commits difference.

    Use when asked: "compare branches", "what's different between branches?"

    Args:
        repo: Repository name
        base: Base branch (e.g., "main")
        head: Head branch to compare (e.g., "release/134")

    Returns:
        Comparison with ahead/behind counts and commit list
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            response = await client.get(
                f"{api_base}/api/github/compare", params={"repo": repo, "base": base, "head": head}
            )

            if response.status_code != 200:
                return {"repo": repo, "error": f"Backend returned {response.status_code}"}

            return response.json()
        except (httpx.HTTPError, ValueError) as err:
            return {"repo": repo, "base": base, "head": head, "error": str(err)}


@mcp.tool()
async def github_get_release_commits_summary(repos: Optional[List[str]] = None, release: str = "134") -> Dict[str, Any]:
    """
    Get commits summary across multiple repos for a release.
    Shows commits before and after branch cut for each repo.

    Use when asked: "release commits", "what changed in R134?"

    Args:
        repos: List of repos to check (default: client, service, enrollment-service, device-classification)
        release: Release number like "134"

    Returns:
        Summary of commits per repo with before/after branch cut counts
    """
    # Call backend API which handles all repos with correct branch config
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    release_id = f"R{release}" if not release.startswith("R") else release

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Get commits for all repos (or just the filtered ones)
            params = {"release": release_id}
            if repos:
                # Backend doesn't filter by repos list, so we'll filter the response
                pass

            response = await client.get(f"{api_base}/api/github/commits", params=params)

            if response.status_code != 200:
                return {"release": release_id, "error": f"Backend returned {response.status_code}"}

            data = response.json()
            repos_data = data.get("repos", {})

            # Filter to requested repos if specified
            if repos:
                repos_data = {k: v for k, v in repos_data.items() if k in repos or v.get("name") in repos}

            results = []
            total_before = 0
            total_after = 0

            for repo_key, repo_data in repos_data.items():
                if not isinstance(repo_data, dict):
                    continue

                all_commits = repo_data.get("commits", [])
                flagged = repo_data.get("flaggedCommits", [])

                before = len([c for c in all_commits if not c.get("isAfterBranchCut", False)])
                after = len(flagged)

                total_before += before
                total_after += after

                results.append(
                    {
                        "repo": repo_data.get("name", repo_key),
                        "branch": repo_data.get("branch", ""),
                        "total_commits": len(all_commits),
                        "before_cut": before,
                        "after_cut": after,
                        "after_cut_commits": flagged[:5] if flagged else [],
                        "risk": "🔴" if after > 5 else ("🟡" if after > 0 else "🟢"),
                    }
                )

            # Build display
            overall_risk = "🔴" if total_after > 10 else ("🟡" if total_after > 0 else "🟢")
            branch_cut_date = data.get("branchCutDate", "")

            display_lines = [
                f"## {overall_risk} Commits After Branch Cut for {release_id}",
                "",
                f"**Branch Cut Date:** {branch_cut_date} | **Repos Analyzed:** {len(results)}",
                f"**Total After Cut:** {total_after} | **Total Before Cut:** {total_before}",
                "",
            ]

            if total_after > 0:
                display_lines.extend(
                    [
                        "### ⚠️ Flagged Commits by Repository",
                        "",
                        "| Repo | Branch | After Cut | Risk |",
                        "|------|--------|-----------|------|",
                    ]
                )
                for r in results:
                    if r["after_cut"] > 0:
                        display_lines.append(f"| {r['repo']} | {r['branch']} | {r['after_cut']} | {r['risk']} |")

                display_lines.append("")
                display_lines.append("### Latest Flagged Commits")
                display_lines.append("")
                for r in results:
                    if r.get("after_cut_commits"):
                        display_lines.append(f"**{r['repo']}:**")
                        for c in r["after_cut_commits"][:3]:
                            msg = c.get("message", "")[:50]
                            display_lines.append(f"- `{c.get('sha', '')[:8]}` {msg}")
                        display_lines.append("")
            else:
                display_lines.extend(
                    [
                        "### ✅ All Clear!",
                        "",
                        "No commits were made after branch cut across all repos.",
                        "The release branches are clean.",
                    ]
                )

            return {
                "release": release_id,
                "branch_cut_date": branch_cut_date,
                "repos_analyzed": len(results),
                "total_commits_before_cut": total_before,
                "total_commits_after_cut": total_after,
                "by_repo": results,
                "overall_risk": overall_risk,
                "source": "backend-api",
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"release": release_id, "error": str(err)}


# =============================================================================
# PR / Dev Insights Tools
# =============================================================================


@mcp.tool()
async def github_get_open_prs() -> Dict[str, Any]:
    """
    Get all open pull requests across configured repos with author, reviewers, age, and size.

    Use when asked: "open PRs", "pending pull requests", "PR list", "who has PRs open?"

    Returns:
        List of open PRs with author, reviewers, age, repo, size, and review status.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(
                f"{api_base}/api/github/pending-reviews",
                params={"include_details": "false"},
            )
            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}", "pull_requests": []}

            data = response.json()
            prs = data.get("pull_requests", [])

            display_lines = [
                "## Open Pull Requests",
                "",
                f"**Total:** {len(prs)}",
                "",
                "| Repo | PR# | Title | Author | Reviewers | Age | Size |",
                "|------|-----|-------|--------|-----------|-----|------|",
            ]
            for pr in prs[:25]:
                reviewers = ", ".join(pr.get("reviewers", [])[:3]) or "none"
                title = pr.get("title", "")[:45]
                if len(pr.get("title", "")) > 45:
                    title += "..."
                display_lines.append(
                    f"| {pr.get('repo', '')} | #{pr.get('number', '')} "
                    f"| {title} | {pr.get('author', '')} "
                    f"| {reviewers} | {pr.get('age', '')} | {pr.get('size', '')} |"
                )

            return {
                "total": len(prs),
                "pull_requests": prs,
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError) as err:
            return {"error": str(err), "pull_requests": []}


@mcp.tool()
async def github_get_pr_review_workload() -> Dict[str, Any]:
    """
    Get PR review workload per developer: how many PRs each person needs to review and has authored.

    Use when asked: "PR review workload", "who has pending reviews?",
    "review load", "who needs to review PRs?", "developer PR workload"

    Returns:
        Per-developer breakdown of pending reviews, authored PRs, and stale reviews.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(
                f"{api_base}/api/github/pending-reviews",
                params={"include_details": "false"},
            )
            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}", "developers": []}

            data = response.json()
            prs = data.get("pull_requests", [])

            reviewer_load: Dict[str, Dict[str, Any]] = {}
            for pr in prs:
                author = pr.get("author", "")
                age_days = pr.get("age_days", 0)
                repo = pr.get("repo", "")

                if author:
                    if author not in reviewer_load:
                        reviewer_load[author] = {
                            "reviews_pending": 0,
                            "prs_authored": 0,
                            "stale_reviews": 0,
                            "repos": {},
                        }
                    reviewer_load[author]["prs_authored"] += 1
                    reviewer_load[author]["repos"][repo] = reviewer_load[author]["repos"].get(repo, 0) + 1

                for reviewer in pr.get("reviewers", []):
                    if reviewer not in reviewer_load:
                        reviewer_load[reviewer] = {
                            "reviews_pending": 0,
                            "prs_authored": 0,
                            "stale_reviews": 0,
                            "repos": {},
                        }
                    reviewer_load[reviewer]["reviews_pending"] += 1
                    reviewer_load[reviewer]["repos"][repo] = reviewer_load[reviewer]["repos"].get(repo, 0) + 1
                    if age_days > 3:
                        reviewer_load[reviewer]["stale_reviews"] += 1

            developers = sorted(
                [{"developer": name, **info} for name, info in reviewer_load.items()],
                key=lambda x: x["reviews_pending"] + x["prs_authored"],
                reverse=True,
            )

            display_lines = [
                "## PR Review Workload",
                "",
                f"**Total Open PRs:** {len(prs)} | **Developers:** {len(developers)}",
                "",
                "| Developer | Reviews Pending | PRs Authored | Stale (>3d) |",
                "|-----------|----------------|--------------|-------------|",
            ]
            for dev in developers[:20]:
                display_lines.append(
                    f"| {dev['developer']} | {dev['reviews_pending']} "
                    f"| {dev['prs_authored']} | {dev['stale_reviews']} |"
                )

            return {
                "total_open_prs": len(prs),
                "total_developers": len(developers),
                "developers": developers,
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError) as err:
            return {"error": str(err), "developers": []}


@mcp.tool()
async def github_get_code_contributors() -> Dict[str, Any]:
    """
    Get code contribution patterns: which developers contribute to which repos.

    Use when asked: "code contributors", "who contributes to which repo?",
    "code ownership", "bus factor", "contributor concentration"

    Returns:
        Per-repo contributor breakdown with concentration metrics.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(
                f"{api_base}/api/github/pending-reviews",
                params={"include_details": "false"},
            )
            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}", "repos": []}

            data = response.json()
            prs = data.get("pull_requests", [])

            repo_authors: Dict[str, Dict[str, int]] = {}
            repo_reviewers: Dict[str, Dict[str, int]] = {}

            for pr in prs:
                author = pr.get("author", "")
                repo = pr.get("repo", "")
                if not repo:
                    continue
                if repo not in repo_authors:
                    repo_authors[repo] = {}
                    repo_reviewers[repo] = {}
                if author:
                    repo_authors[repo][author] = repo_authors[repo].get(author, 0) + 1
                for reviewer in pr.get("reviewers", []):
                    repo_reviewers[repo][reviewer] = repo_reviewers[repo].get(reviewer, 0) + 1

            repos = []
            for repo, authors in repo_authors.items():
                total = sum(authors.values())
                sorted_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)
                top_name = sorted_authors[0][0] if sorted_authors else ""
                top_count = sorted_authors[0][1] if sorted_authors else 0
                repos.append(
                    {
                        "repo": repo,
                        "total_prs": total,
                        "num_contributors": len(authors),
                        "top_contributor": top_name,
                        "top_contributor_share_pct": round(top_count / total * 100) if total else 0,
                        "all_contributors": dict(sorted_authors[:10]),
                        "reviewers": dict(
                            sorted(repo_reviewers.get(repo, {}).items(), key=lambda x: x[1], reverse=True)[:10]
                        ),
                    }
                )
            repos.sort(key=lambda x: x["total_prs"], reverse=True)

            display_lines = [
                "## Code Contributors by Repository",
                "",
                "| Repo | PRs | Contributors | Top Contributor | Share |",
                "|------|-----|-------------|-----------------|-------|",
            ]
            for r in repos:
                display_lines.append(
                    f"| {r['repo']} | {r['total_prs']} | {r['num_contributors']} "
                    f"| {r['top_contributor']} | {r['top_contributor_share_pct']}% |"
                )

            return {
                "total_repos": len(repos),
                "total_open_prs": len(prs),
                "repos": repos,
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError) as err:
            return {"error": str(err), "repos": []}


@mcp.tool()
async def github_get_pr_ticket_references() -> Dict[str, Any]:
    """
    Find JIRA ticket keys referenced in open PR titles and branch names.

    Use when asked: "PRs linked to tickets", "which PRs fix JIRA issues?",
    "cross-concern links", "PR ticket references", "escalation PRs"

    Returns:
        PR-to-ticket mappings and ticket-to-PR reverse mappings.
    """
    import re

    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    jira_pattern = re.compile(r"\b([A-Z]{2,10}-\d{1,6})\b")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(
                f"{api_base}/api/github/pending-reviews",
                params={"include_details": "false"},
            )
            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}", "pr_ticket_links": []}

            data = response.json()
            prs = data.get("pull_requests", [])

            pr_ticket_links = []
            ticket_to_prs: Dict[str, List[Dict]] = {}

            for pr in prs:
                title = pr.get("title", "")
                branch = pr.get("source_branch", "")
                search_text = f"{title} {branch}"

                tickets = set(jira_pattern.findall(search_text))
                if tickets:
                    pr_info = {
                        "number": pr.get("number"),
                        "title": title,
                        "repo": pr.get("repo", ""),
                        "url": pr.get("url", ""),
                        "author": pr.get("author", ""),
                        "age": pr.get("age", ""),
                        "referenced_tickets": sorted(tickets),
                    }
                    pr_ticket_links.append(pr_info)
                    for ticket in tickets:
                        if ticket not in ticket_to_prs:
                            ticket_to_prs[ticket] = []
                        ticket_to_prs[ticket].append(
                            {
                                "number": pr.get("number"),
                                "repo": pr.get("repo", ""),
                                "title": title[:80],
                                "url": pr.get("url", ""),
                            }
                        )

            display_lines = [
                "## PR ↔ JIRA Ticket References",
                "",
                f"**PRs with tickets:** {len(pr_ticket_links)} | **Unique tickets:** {len(ticket_to_prs)}",
                "",
            ]
            if pr_ticket_links:
                display_lines.extend(
                    [
                        "| PR | Repo | Tickets | Author |",
                        "|----|------|---------|--------|",
                    ]
                )
                for link in pr_ticket_links[:20]:
                    tickets_str = ", ".join(link["referenced_tickets"][:3])
                    display_lines.append(f"| #{link['number']} | {link['repo']} | {tickets_str} | {link['author']} |")
            else:
                display_lines.append("No JIRA ticket references found in open PRs.")

            return {
                "total_prs_with_tickets": len(pr_ticket_links),
                "total_unique_tickets": len(ticket_to_prs),
                "pr_ticket_links": pr_ticket_links,
                "ticket_to_prs": ticket_to_prs,
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError) as err:
            return {"error": str(err), "pr_ticket_links": []}


if __name__ == "__main__":
    # Run with stdio transport (required for subprocess communication)
    mcp.run(transport="stdio")

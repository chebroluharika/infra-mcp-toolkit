"""
Dev Insights Service
====================

Core business logic for developer-focused AI insights:
1. Knowledge Gap Agent - Identifies bus factor risks (single-person dependencies)
2. Personalized Daily Digest Agent - Per-developer prioritized action summary
3. Workload Anomaly Agent - Detects overloaded/underutilized developers
4. Cross-Concern Linker Agent - Connects related items across data sources

Data Sources:
- JIRA: Issues, assignments, components, escalations
- GitHub: PRs, reviews, commits, code ownership
- Jenkins: Build failures, test results
"""

import asyncio
import json
import logging
import os
import statistics
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_cache: Dict[str, Any] = {}
_cache_times: Dict[str, float] = {}
CACHE_TTL = 300  # 5 minutes

BOT_ACCOUNTS = {
    "cicd-bot",
    "copilot",
    "dependabot",
    "renovate",
    "cfsalerts",
    "github-actions",
    "unassigned",
    "unknown",
}


def _get_cached(key: str) -> Optional[Any]:
    if key in _cache and time.time() - _cache_times.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None


def _set_cached(key: str, value: Any):
    _cache[key] = value
    _cache_times[key] = time.time()


def _is_bot(name: str) -> bool:
    """Filter out bot/service accounts."""
    if not name:
        return True
    lower = name.lower().strip()
    if lower in BOT_ACCOUNTS:
        return True
    if any(bot in lower for bot in ("bot", "automation", "renovate", "dependabot")):
        return True
    return False


# =============================================================================
# Identity Mapping (JIRA display names ↔ GitHub logins)
# =============================================================================

_identity_map: Optional[Dict[str, str]] = None
_reverse_identity_map: Optional[Dict[str, str]] = None


def _load_identity_maps():
    """Build bidirectional JIRA↔GitHub identity mapping from user_mapping.json."""
    global _identity_map, _reverse_identity_map
    if _identity_map is not None:
        return

    _identity_map = {}  # jira_name_lower → jira_name
    _reverse_identity_map = {}  # github_login_lower → jira_name

    mapping_path = os.path.join(os.path.dirname(__file__), "..", "user_mapping.json")
    if not os.path.exists(mapping_path):
        return

    try:
        with open(mapping_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Could not load user_mapping.json: %s", e)
        return

    for jira_name, info in data.items():
        if jira_name.startswith("_"):
            continue
        _identity_map[jira_name.lower()] = jira_name

        github = (info.get("github") or "").strip().lower()
        if github:
            _reverse_identity_map[github] = jira_name

        handle = (info.get("handle") or "").strip().lower()
        if handle and handle not in _reverse_identity_map:
            _reverse_identity_map[handle] = jira_name


def _canonical_name(name: str) -> str:
    """
    Map any identifier (JIRA display name or GitHub login) to a canonical JIRA display name.
    Falls back to the original input if no mapping is found.
    """
    _load_identity_maps()
    if not name:
        return ""

    lower = name.lower().strip()

    if lower in _reverse_identity_map:
        return _reverse_identity_map[lower]

    if lower in _identity_map:
        return _identity_map[lower]

    return name


# =============================================================================
# JIRA Helpers
# =============================================================================


def _get_jira_client():
    from services.jira_client import JiraClient

    return JiraClient()


async def _fetch_jira_issues(jql: str, fields: List[str] = None, max_results: int = 200) -> List[Dict]:
    client = _get_jira_client()
    if not client.is_configured():
        return []
    try:
        return await client.search_issues(jql, max_results=max_results, fields=fields)
    except Exception as e:
        logger.warning("JIRA fetch failed: %s", e)
        return []


# =============================================================================
# GitHub Helpers
# =============================================================================


async def _fetch_github_prs(state: str = "open") -> List[Dict]:
    from config import get_github_repos, settings

    token = settings.github_token
    if not token:
        return []

    repos = get_github_repos()
    all_prs = []
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient(timeout=30) as http:
        for key, repo_cfg in repos.items():
            owner = repo_cfg["owner"]
            repo = repo_cfg["repo"]
            try:
                resp = await http.get(
                    f"https://api.github.com/repos/{owner}/{repo}/pulls",
                    params={"state": state, "per_page": 100, "sort": "updated"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    for pr in resp.json():
                        pr["_repo_key"] = key
                        pr["_repo_name"] = repo
                        all_prs.append(pr)
            except Exception as e:
                logger.warning("GitHub PR fetch failed for %s/%s: %s", owner, repo, e)

    return all_prs


async def _fetch_github_commits(owner: str, repo: str, branch: str = "develop", since_days: int = 30) -> List[Dict]:
    from config import settings

    token = settings.github_token
    if not token:
        return []

    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    commits = []
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            resp = await http.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"sha": branch, "since": since, "per_page": 100},
                headers=headers,
            )
            if resp.status_code == 200:
                commits = resp.json()
        except Exception as e:
            logger.warning("GitHub commit fetch failed: %s", e)

    return commits


# =============================================================================
# 1. Knowledge Gap Agent
# =============================================================================


async def analyze_knowledge_gaps(release: str = None) -> Dict[str, Any]:
    """
    Identifies areas where only one developer has expertise (bus factor risk).

    Analyzes:
    - JIRA component ownership: who works on which components
    - GitHub PR reviews: who reviews which areas
    - Code commits: who contributes to which directories/files
    """
    cache_key = f"knowledge_gaps:{release}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    # Parallel data fetching
    jql_assigned = (
        f'project = ENG AND fixVersion = "{_format_release(release)}" AND assignee is not EMPTY'
        if release
        else "project = ENG AND updated >= -90d AND assignee is not EMPTY"
    )
    jql_resolved = (
        f'project = ENG AND fixVersion = "{_format_release(release)}" AND status in (Resolved, Done, Closed)'
        if release
        else "project = ENG AND updated >= -90d AND status in (Resolved, Done, Closed)"
    )

    fields = ["assignee", "components", "issuetype", "status", "summary", "labels"]

    assigned_issues, resolved_issues, open_prs = await asyncio.gather(
        _fetch_jira_issues(jql_assigned, fields=fields),
        _fetch_jira_issues(jql_resolved, fields=fields),
        _fetch_github_prs("open"),
        return_exceptions=True,
    )

    if isinstance(assigned_issues, Exception):
        assigned_issues = []
    if isinstance(resolved_issues, Exception):
        resolved_issues = []
    if isinstance(open_prs, Exception):
        open_prs = []

    all_issues = assigned_issues + resolved_issues

    # --- Component ownership analysis ---
    component_owners: Dict[str, Counter] = defaultdict(Counter)
    for issue in all_issues:
        assignee = _extract_assignee(issue)
        if not assignee or _is_bot(assignee):
            continue
        assignee = _canonical_name(assignee)
        components = _extract_components(issue)
        for comp in components:
            component_owners[comp][assignee] += 1

    # --- PR review analysis ---
    reviewer_areas: Dict[str, Counter] = defaultdict(Counter)
    author_repos: Dict[str, Counter] = defaultdict(Counter)
    for pr in open_prs:
        author = pr.get("user", {}).get("login", "Unknown")
        if _is_bot(author):
            continue
        author = _canonical_name(author)
        repo = pr.get("_repo_name", "unknown")
        author_repos[repo][author] += 1

        reviewers = pr.get("requested_reviewers", [])
        for reviewer in reviewers:
            name = reviewer.get("login", "Unknown")
            if not _is_bot(name):
                name = _canonical_name(name)
                reviewer_areas[repo][name] += 1

    # --- Identify risks ---
    high_risk = []
    medium_risk = []
    low_risk = []

    for component, owners in component_owners.items():
        total_issues = sum(owners.values())
        num_contributors = len(owners)
        top_contributor, top_count = owners.most_common(1)[0]
        concentration = top_count / total_issues if total_issues > 0 else 0

        entry = {
            "area": component,
            "type": "jira_component",
            "total_items": total_issues,
            "contributors": num_contributors,
            "top_contributor": top_contributor,
            "top_contributor_share": round(concentration * 100),
            "all_contributors": dict(owners.most_common(10)),
        }

        if num_contributors == 1 and total_issues >= 3:
            entry["risk"] = "high"
            entry["reason"] = f"Only {top_contributor} works on {component} ({total_issues} issues)"
            entry["recommendation"] = f"Cross-train another engineer on {component}"
            high_risk.append(entry)
        elif concentration >= 0.75 and total_issues >= 5:
            entry["risk"] = "medium"
            entry["reason"] = f"{top_contributor} handles {entry['top_contributor_share']}% of {component} work"
            entry["recommendation"] = f"Distribute {component} work more evenly"
            medium_risk.append(entry)
        elif num_contributors <= 2 and total_issues >= 3:
            entry["risk"] = "low"
            entry["reason"] = f"Only {num_contributors} contributors to {component}"
            low_risk.append(entry)

    for repo, authors in author_repos.items():
        num_authors = len(authors)
        total_prs = sum(authors.values())
        if num_authors > 0:
            top_author, top_count = authors.most_common(1)[0]
            concentration = top_count / total_prs if total_prs > 0 else 0

            if num_authors == 1 and total_prs >= 2:
                high_risk.append(
                    {
                        "area": f"{repo} (PRs)",
                        "type": "github_repo",
                        "total_items": total_prs,
                        "contributors": num_authors,
                        "top_contributor": top_author,
                        "top_contributor_share": 100,
                        "risk": "high",
                        "reason": f"Only {top_author} submits PRs to {repo}",
                        "recommendation": f"Encourage more contributors to {repo}",
                    }
                )

    high_risk.sort(key=lambda x: x.get("total_items", 0), reverse=True)
    medium_risk.sort(key=lambda x: x.get("total_items", 0), reverse=True)

    result = {
        "summary": {
            "total_areas_analyzed": len(component_owners) + len(author_repos),
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(medium_risk),
            "low_risk_count": len(low_risk),
            "bus_factor_score": _calculate_bus_factor_score(high_risk, medium_risk, len(component_owners)),
        },
        "high_risk": high_risk[:15],
        "medium_risk": medium_risk[:15],
        "low_risk": low_risk[:10],
        "recommendations": _generate_knowledge_recommendations(high_risk, medium_risk),
    }

    _set_cached(cache_key, result)
    return result


def _calculate_bus_factor_score(high: list, medium: list, total_areas: int) -> Optional[int]:
    """0-100 score where 100 = no bus factor risk, 0 = critical risk. None if insufficient data."""
    if total_areas < 2:
        return None
    risk_score = (len(high) * 3 + len(medium)) / max(total_areas, 1)
    return max(0, min(100, int(100 - risk_score * 25)))


def _generate_knowledge_recommendations(high_risk: list, medium_risk: list) -> List[Dict]:
    recs = []
    sole_owners = set()
    for item in high_risk:
        owner = item.get("top_contributor", "")
        if owner not in sole_owners:
            sole_owners.add(owner)
            areas = [x["area"] for x in high_risk if x.get("top_contributor") == owner]
            recs.append(
                {
                    "type": "cross_training",
                    "priority": "high",
                    "developer": owner,
                    "areas": areas[:5],
                    "action": f"Schedule knowledge transfer sessions for {owner}'s sole-owned areas: {', '.join(areas[:3])}",
                }
            )

    concentrated = defaultdict(list)
    for item in medium_risk:
        concentrated[item.get("top_contributor", "")].append(item["area"])
    for dev, areas in list(concentrated.items())[:5]:
        recs.append(
            {
                "type": "workload_distribution",
                "priority": "medium",
                "developer": dev,
                "areas": areas[:5],
                "action": f"Distribute work in {', '.join(areas[:3])} to reduce {dev}'s concentration",
            }
        )

    return recs[:10]


# =============================================================================
# 2. Personalized Daily Digest Agent
# =============================================================================


async def generate_daily_digest(developer: str, release: str = None) -> Dict[str, Any]:
    """
    Generates a prioritized daily summary for a specific developer.

    Aggregates:
    - Their open bugs/stories with priority
    - PRs waiting for their review
    - PRs they authored needing attention
    - Escalations assigned to them
    - Build failures in their recent commits
    """
    cache_key = f"daily_digest:{developer}:{release}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    release_jql = f' AND fixVersion = "{_format_release(release)}"' if release else ""

    jql_assigned = f'project = ENG AND assignee = "{developer}" AND status not in (Closed, Done, Resolved){release_jql} ORDER BY priority ASC, updated DESC'
    jql_escalations = f'project = ENG AND assignee = "{developer}" AND (labels = "NS_Client" OR labels = "Customer_Escalation") AND status not in (Closed, Done){release_jql}'
    jql_review = f'project = ENG AND "Code Reviewer" = "{developer}" AND status = "In Review"'

    fields = ["summary", "priority", "status", "issuetype", "components", "labels", "updated", "created", "assignee"]

    assigned_task, escalations_task, review_task, prs_task = await asyncio.gather(
        _fetch_jira_issues(jql_assigned, fields=fields, max_results=50),
        _fetch_jira_issues(jql_escalations, fields=fields, max_results=20),
        _fetch_jira_issues(jql_review, fields=fields, max_results=20),
        _fetch_github_prs("open"),
        return_exceptions=True,
    )

    assigned_items = assigned_task if not isinstance(assigned_task, Exception) else []
    escalation_items = escalations_task if not isinstance(escalations_task, Exception) else []
    review_items = review_task if not isinstance(review_task, Exception) else []
    all_prs = prs_task if not isinstance(prs_task, Exception) else []

    # Categorize assigned items
    blockers = []
    bugs = []
    stories = []
    others = []
    for issue in assigned_items:
        priority = _extract_field(issue, "priority", "Medium")
        item = {
            "key": issue.get("key"),
            "summary": issue.get("summary") or issue.get("fields", {}).get("summary", ""),
            "priority": priority,
            "status": _extract_field(issue, "status", "Open"),
            "type": _extract_field(issue, "issuetype", "Task"),
            "components": _extract_components(issue),
        }

        if priority in ("Blocker", "P1", "Highest"):
            blockers.append(item)
        elif item["type"].lower() == "bug":
            bugs.append(item)
        elif item["type"].lower() in ("story", "task"):
            stories.append(item)
        else:
            others.append(item)

    # PRs needing attention
    dev_lower = developer.lower()
    prs_authored = []
    prs_to_review = []
    for pr in all_prs:
        author = (pr.get("user", {}) or {}).get("login", "").lower()
        reviewers = [r.get("login", "").lower() for r in (pr.get("requested_reviewers") or [])]
        assignees = [a.get("login", "").lower() for a in (pr.get("assignees") or [])]

        pr_info = {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "repo": pr.get("_repo_name", ""),
            "url": pr.get("html_url", ""),
            "author": (pr.get("user", {}) or {}).get("login", ""),
            "age_days": _days_since(pr.get("created_at")),
            "updated": pr.get("updated_at", ""),
        }

        if dev_lower in reviewers:
            prs_to_review.append(pr_info)
        elif dev_lower == author or dev_lower in assignees:
            prs_authored.append(pr_info)

    # Format escalations
    escalation_list = []
    for issue in escalation_items:
        escalation_list.append(
            {
                "key": issue.get("key"),
                "summary": issue.get("summary") or issue.get("fields", {}).get("summary", ""),
                "priority": _extract_field(issue, "priority", "Medium"),
                "status": _extract_field(issue, "status", "Open"),
            }
        )

    # Build prioritized action items
    action_items = []
    for esc in escalation_list:
        action_items.append(
            {
                "priority": 1,
                "category": "escalation",
                "action": f"Resolve escalation {esc['key']}: {esc['summary'][:80]}",
                "urgency": "critical",
            }
        )
    for blocker in blockers:
        action_items.append(
            {
                "priority": 2,
                "category": "blocker",
                "action": f"Fix blocker {blocker['key']}: {blocker['summary'][:80]}",
                "urgency": "high",
            }
        )
    for pr in prs_to_review:
        stale = pr.get("age_days", 0) > 3
        action_items.append(
            {
                "priority": 3 if stale else 4,
                "category": "pr_review",
                "action": f"Review PR #{pr['number']} in {pr['repo']}: {pr['title'][:60]}",
                "urgency": "high" if stale else "medium",
            }
        )
    for bug in bugs[:5]:
        action_items.append(
            {
                "priority": 5,
                "category": "bug",
                "action": f"Fix bug {bug['key']}: {bug['summary'][:80]}",
                "urgency": "medium",
            }
        )

    action_items.sort(key=lambda x: x["priority"])

    result = {
        "developer": developer,
        "release": release,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_assigned": len(assigned_items),
            "blockers": len(blockers),
            "bugs": len(bugs),
            "stories": len(stories),
            "escalations": len(escalation_list),
            "prs_to_review": len(prs_to_review),
            "prs_authored": len(prs_authored),
        },
        "action_items": action_items[:15],
        "escalations": escalation_list,
        "blockers": blockers,
        "bugs": bugs[:10],
        "stories": stories[:10],
        "prs_to_review": prs_to_review,
        "prs_authored": prs_authored,
        "code_reviews": [
            {"key": i.get("key"), "summary": i.get("fields", {}).get("summary", "")} for i in review_items[:10]
        ],
    }

    _set_cached(cache_key, result)
    return result


# =============================================================================
# 3. Workload Anomaly Agent
# =============================================================================


async def detect_workload_anomalies(release: str = None) -> Dict[str, Any]:
    """
    Detects overloaded and underutilized developers.

    Calculates a workload score per developer based on:
    - Open bug count (weighted by priority)
    - Open story count
    - Pending PR reviews
    - Active escalations
    Flags outliers using standard deviation.
    """
    cache_key = f"workload_anomalies:{release}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    release_jql = f' AND fixVersion = "{_format_release(release)}"' if release else ""
    jql = f"project = ENG AND status not in (Closed, Done, Resolved) AND assignee is not EMPTY{release_jql}"
    fields = ["assignee", "priority", "issuetype", "status", "labels", "components"]

    issues, prs = await asyncio.gather(
        _fetch_jira_issues(jql, fields=fields, max_results=500),
        _fetch_github_prs("open"),
        return_exceptions=True,
    )

    if isinstance(issues, Exception):
        issues = []
    if isinstance(prs, Exception):
        prs = []

    # Count items per developer (use canonical names to merge JIRA + GitHub identities)
    dev_workload: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "bugs": 0,
            "stories": 0,
            "blockers": 0,
            "escalations": 0,
            "pr_reviews": 0,
            "prs_authored": 0,
            "total_items": 0,
            "high_priority": 0,
            "components": Counter(),
        }
    )

    for issue in issues:
        assignee = _extract_assignee(issue)
        if not assignee or _is_bot(assignee):
            continue

        assignee = _canonical_name(assignee)
        issue_type = _extract_field(issue, "issuetype", "").lower()
        priority = _extract_field(issue, "priority", "Medium")
        labels = _extract_labels(issue)

        w = dev_workload[assignee]
        w["total_items"] += 1

        if issue_type == "bug":
            w["bugs"] += 1
        elif issue_type in ("story", "task"):
            w["stories"] += 1

        if priority in ("Blocker", "P1", "Highest", "Critical"):
            w["blockers"] += 1
            w["high_priority"] += 1
        elif priority in ("P2", "High"):
            w["high_priority"] += 1

        if "Customer_Escalation" in labels or "NS_Client" in labels:
            w["escalations"] += 1

        for comp in _extract_components(issue):
            w["components"][comp] += 1

    for pr in prs:
        author = (pr.get("user", {}) or {}).get("login", "")
        if author and not _is_bot(author):
            author = _canonical_name(author)
            dev_workload[author]["prs_authored"] += 1
            dev_workload[author]["total_items"] += 1

        for reviewer in pr.get("requested_reviewers") or []:
            name = reviewer.get("login", "")
            if name and not _is_bot(name):
                name = _canonical_name(name)
                dev_workload[name]["pr_reviews"] += 1
                dev_workload[name]["total_items"] += 1

    # Calculate workload scores
    WEIGHTS = {
        "blockers": 5,
        "escalations": 4,
        "bugs": 2,
        "stories": 1.5,
        "pr_reviews": 1,
        "prs_authored": 1,
    }

    scores = {}
    for dev, w in dev_workload.items():
        score = sum(w.get(k, 0) * v for k, v in WEIGHTS.items())
        scores[dev] = round(score, 1)
        w["workload_score"] = round(score, 1)
        w["components"] = dict(w["components"].most_common(5))

    if not scores:
        return {
            "summary": {"total_developers": 0},
            "developers": [],
            "overloaded": [],
            "underutilized": [],
            "balanced": [],
        }

    score_values = list(scores.values())
    mean_score = statistics.mean(score_values) if score_values else 0
    std_score = statistics.stdev(score_values) if len(score_values) > 1 else 0

    overloaded = []
    underutilized = []
    balanced = []

    overload_threshold = mean_score + 1.5 * std_score
    underutil_threshold = max(mean_score - 1.0 * std_score, 0)

    for dev, w in dev_workload.items():
        score = w["workload_score"]
        entry = {
            "developer": dev,
            "workload_score": score,
            "items": {k: v for k, v in w.items() if k not in ("workload_score", "components", "total_items")},
            "total_items": w["total_items"],
            "top_components": w.get("components", {}),
        }

        if score > overload_threshold and w["total_items"] >= 3:
            entry["status"] = "overloaded"
            entry["deviation"] = round((score - mean_score) / std_score, 1) if std_score > 0 else 0
            entry["recommendation"] = _generate_workload_recommendation(dev, w, "overloaded")
            overloaded.append(entry)
        elif score < underutil_threshold and mean_score > 5:
            entry["status"] = "underutilized"
            entry["deviation"] = round((mean_score - score) / std_score, 1) if std_score > 0 else 0
            entry["recommendation"] = _generate_workload_recommendation(dev, w, "underutilized")
            underutilized.append(entry)
        else:
            entry["status"] = "balanced"
            balanced.append(entry)

    overloaded.sort(key=lambda x: x["workload_score"], reverse=True)
    underutilized.sort(key=lambda x: x["workload_score"])
    balanced.sort(key=lambda x: x["workload_score"], reverse=True)

    result = {
        "summary": {
            "total_developers": len(dev_workload),
            "overloaded_count": len(overloaded),
            "underutilized_count": len(underutilized),
            "balanced_count": len(balanced),
            "mean_workload": round(mean_score, 1),
            "std_deviation": round(std_score, 1),
            "overload_threshold": round(overload_threshold, 1),
        },
        "overloaded": overloaded[:10],
        "underutilized": underutilized[:10],
        "balanced": balanced[:20],
    }

    _set_cached(cache_key, result)
    return result


def _generate_workload_recommendation(dev: str, workload: dict, status: str) -> str:
    if status == "overloaded":
        parts = []
        if workload.get("blockers", 0) >= 2:
            parts.append(f"has {workload['blockers']} blockers")
        if workload.get("escalations", 0) >= 2:
            parts.append(f"{workload['escalations']} escalations")
        if workload.get("pr_reviews", 0) >= 3:
            parts.append(f"{workload['pr_reviews']} pending reviews")
        detail = ", ".join(parts) if parts else f"{workload.get('total_items', 0)} total items"
        return f"{dev} is overloaded ({detail}). Consider redistributing lower-priority items."
    else:
        components = list(workload.get("components", {}).keys())
        if components:
            return f"{dev} has capacity. Could help with: {', '.join(components[:3])}"
        return f"{dev} has low workload and could take on additional items."


# =============================================================================
# 4. Cross-Concern Linker Agent
# =============================================================================


async def find_cross_concern_links(release: str = None) -> Dict[str, Any]:
    """
    Finds connections between items across different data sources.

    Links:
    - Escalations ↔ PRs (via JIRA issue keys in PR titles/branches)
    - Bugs ↔ Components ↔ Other bugs (common component clusters)
    - PRs ↔ Test failures (matching file paths)
    - Escalations ↔ Builds ↔ Stacks (deployment correlation)
    """
    cache_key = f"cross_concern_links:{release}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    release_jql = f' AND fixVersion = "{_format_release(release)}"' if release else ""

    jql_escalations = f'project = ENG AND (labels = "NS_Client" OR labels = "Customer_Escalation") AND status not in (Closed){release_jql}'
    jql_bugs = f"project = ENG AND issuetype = Bug AND status not in (Closed, Done){release_jql}"

    fields = ["summary", "assignee", "priority", "status", "issuetype", "components", "labels", "issuelinks"]

    escalations_task, bugs_task, prs_task = await asyncio.gather(
        _fetch_jira_issues(jql_escalations, fields=fields, max_results=100),
        _fetch_jira_issues(jql_bugs, fields=fields, max_results=200),
        _fetch_github_prs("open"),
        return_exceptions=True,
    )

    escalations = escalations_task if not isinstance(escalations_task, Exception) else []
    bugs = bugs_task if not isinstance(bugs_task, Exception) else []
    prs = prs_task if not isinstance(prs_task, Exception) else []

    links = []

    # --- Escalation ↔ PR links (ticket keys in PR title/branch) ---
    escalation_keys = {i.get("key", "").upper() for i in escalations if i.get("key")}
    bug_keys = {i.get("key", "").upper() for i in bugs if i.get("key")}
    all_jira_keys = escalation_keys | bug_keys

    jira_key_to_issue = {}
    for issue in escalations + bugs:
        key = issue.get("key", "").upper()
        jira_key_to_issue[key] = {
            "key": issue.get("key"),
            "summary": issue.get("summary") or issue.get("fields", {}).get("summary", ""),
            "type": _extract_field(issue, "issuetype", ""),
            "priority": _extract_field(issue, "priority", ""),
            "assignee": _extract_assignee(issue),
            "components": _extract_components(issue),
        }

    for pr in prs:
        title = (pr.get("title") or "").upper()
        branch = (pr.get("head", {}) or {}).get("ref", "").upper()
        body = (pr.get("body") or "")[:500].upper()
        search_text = f"{title} {branch} {body}"

        for jira_key in all_jira_keys:
            if jira_key in search_text:
                issue_info = jira_key_to_issue.get(jira_key, {})
                is_escalation = jira_key in escalation_keys
                links.append(
                    {
                        "type": "escalation_pr" if is_escalation else "bug_pr",
                        "severity": "high" if is_escalation else "medium",
                        "source": {
                            "type": "jira_escalation" if is_escalation else "jira_bug",
                            "key": issue_info.get("key", jira_key),
                            "summary": issue_info.get("summary", ""),
                            "priority": issue_info.get("priority", ""),
                        },
                        "target": {
                            "type": "github_pr",
                            "number": pr.get("number"),
                            "title": pr.get("title", ""),
                            "repo": pr.get("_repo_name", ""),
                            "url": pr.get("html_url", ""),
                            "author": (pr.get("user", {}) or {}).get("login", ""),
                        },
                        "relationship": f"PR #{pr.get('number')} in {pr.get('_repo_name', '')} references {jira_key}",
                    }
                )

    # --- Component cluster analysis (bugs sharing components) ---
    component_bugs: Dict[str, List[Dict]] = defaultdict(list)
    for issue in bugs:
        components = _extract_components(issue)
        for comp in components:
            component_bugs[comp].append(
                {
                    "key": issue.get("key"),
                    "summary": (issue.get("summary") or issue.get("fields", {}).get("summary", ""))[:100],
                    "priority": _extract_field(issue, "priority", ""),
                    "assignee": _extract_assignee(issue),
                }
            )

    component_clusters = []
    for comp, comp_bugs in component_bugs.items():
        if len(comp_bugs) >= 3:
            assignees = list({b["assignee"] for b in comp_bugs if b.get("assignee")})
            priorities = Counter(b["priority"] for b in comp_bugs)
            component_clusters.append(
                {
                    "component": comp,
                    "bug_count": len(comp_bugs),
                    "assignees": assignees,
                    "priority_breakdown": dict(priorities),
                    "bugs": comp_bugs[:5],
                    "insight": f"{comp} has {len(comp_bugs)} open bugs across {len(assignees)} developer(s) — may indicate a systemic issue",
                }
            )

    component_clusters.sort(key=lambda x: x["bug_count"], reverse=True)

    # --- JIRA issue link analysis ---
    linked_chains = []
    for issue in escalations:
        issue_links = issue.get("issuelinks") or issue.get("fields", {}).get("issuelinks") or []
        if issue_links:
            chain = {
                "root": {
                    "key": issue.get("key"),
                    "summary": (issue.get("summary") or issue.get("fields", {}).get("summary", ""))[:100],
                    "type": "escalation",
                },
                "linked_items": [],
            }
            for link in issue_links[:5]:
                linked = link.get("outwardIssue") or link.get("inwardIssue") or {}
                if linked:
                    chain["linked_items"].append(
                        {
                            "key": linked.get("key", ""),
                            "summary": (linked.get("fields", {}).get("summary") or linked.get("summary", ""))[:80],
                            "relationship": link.get("type", {}).get(
                                "outward", link.get("type", {}).get("name", "related")
                            ),
                        }
                    )
            if chain["linked_items"]:
                linked_chains.append(chain)

    links.sort(key=lambda x: 0 if x.get("severity") == "high" else 1)

    result = {
        "summary": {
            "total_links_found": len(links),
            "escalation_pr_links": sum(1 for lnk in links if lnk["type"] == "escalation_pr"),
            "bug_pr_links": sum(1 for lnk in links if lnk["type"] == "bug_pr"),
            "component_clusters": len(component_clusters),
            "linked_chains": len(linked_chains),
        },
        "links": links[:30],
        "component_clusters": component_clusters[:10],
        "linked_chains": linked_chains[:10],
        "insights": _generate_cross_concern_insights(links, component_clusters),
    }

    _set_cached(cache_key, result)
    return result


def _generate_cross_concern_insights(links: list, clusters: list) -> List[str]:
    insights = []

    esc_pr_count = sum(1 for lnk in links if lnk["type"] == "escalation_pr")
    if esc_pr_count > 0:
        insights.append(
            f"{esc_pr_count} open PR(s) are linked to customer escalations — these should be prioritized for review and merge."
        )

    if esc_pr_count == 0 and len(links) > 0:
        insights.append("No escalation-linked PRs found. Verify escalation fixes are in progress.")

    hot_components = [c for c in clusters if c["bug_count"] >= 5]
    for comp in hot_components[:3]:
        insights.append(
            f"Component '{comp['component']}' is a hotspot with {comp['bug_count']} bugs — consider a focused bug bash."
        )

    multi_dev = [c for c in clusters if len(c.get("assignees", [])) == 1 and c["bug_count"] >= 3]
    for comp in multi_dev[:2]:
        insights.append(
            f"All {comp['bug_count']} bugs in '{comp['component']}' are assigned to {comp['assignees'][0]} — review workload balance."
        )

    if not insights:
        insights.append("No critical cross-concern patterns detected. Items appear well-distributed.")

    return insights


# =============================================================================
# Utility Functions
# =============================================================================


def _format_release(release: str) -> str:
    """Format release ID to JIRA fixVersion. R135 → 135.0.0 (matches release_data_service)."""
    if not release:
        return ""
    release = release.strip()
    if release.upper().startswith("R") and "." not in release:
        version = release[1:]
        return f"{version}.0.0"
    return release


def _extract_assignee(issue: Dict) -> str:
    """Extract assignee from JiraClient's flattened issue format or raw JIRA format."""
    assignee = issue.get("assignee")
    if isinstance(assignee, str):
        return assignee if assignee != "Unassigned" else ""
    if isinstance(assignee, dict):
        return assignee.get("displayName") or assignee.get("name") or ""
    f = issue.get("fields", {})
    fa = f.get("assignee")
    if isinstance(fa, dict):
        return fa.get("displayName") or fa.get("name") or ""
    if isinstance(fa, str):
        return fa if fa != "Unassigned" else ""
    return ""


def _extract_components(issue: Dict) -> List[str]:
    """Extract components from JiraClient's flattened format or raw JIRA format."""
    components = issue.get("components") or []
    if components and isinstance(components[0], str):
        return [c for c in components if c]
    if components and isinstance(components[0], dict):
        return [c.get("name", "") for c in components if isinstance(c, dict) and c.get("name")]
    f = issue.get("fields", {})
    raw_comps = f.get("components") or []
    if raw_comps and isinstance(raw_comps[0], dict):
        return [c.get("name", "") for c in raw_comps if isinstance(c, dict) and c.get("name")]
    return []


def _extract_field(issue: Dict, field: str, default="") -> str:
    """Extract a field from either flat or nested JIRA format."""
    val = issue.get(field)
    if val is not None:
        if isinstance(val, dict):
            return val.get("name", default)
        return str(val) if val else default
    f = issue.get("fields", {})
    fval = f.get(field)
    if fval is not None:
        if isinstance(fval, dict):
            return fval.get("name", default)
        return str(fval) if fval else default
    return default


def _extract_labels(issue: Dict) -> List[str]:
    """Extract labels from either flat or nested JIRA format."""
    labels = issue.get("labels")
    if labels is not None:
        return labels if isinstance(labels, list) else []
    f = issue.get("fields", {})
    return f.get("labels") or []


def _days_since(date_str: str) -> int:
    if not date_str:
        return 0
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0

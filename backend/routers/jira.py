"""
JIRA API Router
===============

Provides REST endpoints for JIRA integration.

Uses direct JIRA API calls (not MCP) for data fetching.

Endpoints:
    - GET /api/jira/regression-tracking/hierarchy - Epic-based regression tracking
    - GET /api/jira/regression-tracking/progress - Regression progress over time
    - GET /api/jira/issue/{key}/comments - Get issue comments
    - GET /api/jira/issue/{key}/parsed-comments - Get parsed test results from comments
    - GET /api/jira/milestone/irr - IRR milestone tracking
    - GET /api/jira/milestone/branch-cut - Branch cut milestone tracking
    - GET /api/jira/milestone/final-build - Final build milestone tracking
    - GET /api/jira/resolution-progress - Day-wise resolution progress
    - GET /api/jira/release-readiness - Release readiness tracking
    - GET /api/jira/release-data/* - Centralized release data endpoints
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from config import get_release_dates, get_release_lead, is_release_completed
from fastapi import APIRouter, HTTPException, Query
from services.jira_client import JiraAuthError, get_jira_client
from services.trend_tracker import analyze_trends, save_daily_snapshot
from utilities.jira import (
    analyze_blockers,
    calculate_rrs_score,
    determine_phase,
    get_phase_status,
    get_readiness_recommendation,
    get_release_id_from_param,
    parse_date_safe,
    parse_version_from_release,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jira", tags=["jira"])

# =============================================================================
# Regression Summary Cache (for lightweight Overview page reads)
# =============================================================================

REGRESSION_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "regression_cache.json")


def _load_regression_cache() -> dict:
    """Load cached regression summaries from file."""
    import json

    try:
        if os.path.exists(REGRESSION_CACHE_FILE):
            with open(REGRESSION_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load regression cache: {e}")
    return {}


def _save_regression_cache(epic_key: str, data: dict) -> None:
    """Save regression summary to cache file."""
    import json

    try:
        cache = _load_regression_cache()
        cache[epic_key] = data
        os.makedirs(os.path.dirname(REGRESSION_CACHE_FILE), exist_ok=True)
        with open(REGRESSION_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2, default=str)
        logger.debug(f"Cached regression summary for {epic_key}")
    except Exception as e:
        logger.warning(f"Failed to save regression cache: {e}")


def get_cached_regression_summary(epic_keys: list) -> dict:
    """Get cached regression summaries for given epic keys (no API calls)."""
    cache = _load_regression_cache()
    result = {}
    for key in epic_keys:
        if key in cache:
            result[key] = cache[key]
    return result


# =============================================================================
# Regression Tracking Hierarchy Endpoints (Epic-based)
# =============================================================================

# Category keywords for classifying child epics
CATEGORY_KEYWORDS = {
    "automation": ["automation", "automated", "auto regression"],
    "manual": ["manual", "feature validation", "manual feature"],
    "non_functional": ["non-functional", "nonfunctional", "non functional", "performance", "stress", "load"],
}


def classify_epic_category(epic_summary: str) -> str:
    """Classify an epic into a category based on its summary text."""
    summary_lower = epic_summary.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in summary_lower:
                return category
    return "other"


def get_status_category(status: str) -> str:
    """Map JIRA status to a simplified status category."""
    status_lower = (status or "").lower()
    done_statuses = ["done", "closed", "completed", "resolved", "pending close"]
    in_progress_statuses = ["in progress", "in review", "code review", "testing", "qa"]
    blocked_statuses = ["blocked", "on hold", "waiting"]

    for done_status in done_statuses:
        if done_status in status_lower:
            return "done"
    for ip_status in in_progress_statuses:
        if ip_status in status_lower:
            return "in_progress"
    for blocked_status in blocked_statuses:
        if blocked_status in status_lower:
            return "blocked"
    return "todo"


@router.get("/regression-tracking/hierarchy")
async def get_regression_tracking_hierarchy(
    epic_key: str = Query(..., description="Parent epic key for regression tracking"),
):
    """
    Get hierarchical regression testing progress for a parent epic.

    PURPOSE:
        Returns regression testing progress organized by test category
        (Automation, Manual, Non-Functional). Shows stories with their
        subtasks and completion status. Used to track regression testing
        progress on the Regression Tracking page.

    HIERARCHY (R135+):
        Parent Epic (e.g., ENG-856257)
        ├── Story 1 (linked via Parent Link) → Sub-tasks
        ├── Story 2 (linked via Parent Link) → Sub-tasks
        └── ...

        Stories are classified into categories based on their summary keywords.

    PARAMETERS:
        - epic_key (str): Parent JIRA epic key (e.g., "ENG-856257")

    RETURNS:
        {
            "parent_epic": {
                "key": "ENG-856257",
                "summary": "R135 Regression Testing",
                "status": "In Progress",
                "url": "https://your-org.atlassian.net/browse/..."
            },
            "categories": {
                "automation": {
                    "stories": [
                        {
                            "key": "ENG-12346",
                            "summary": "Automated Regression for Backend",
                            "status": "Done",
                            "status_category": "done",
                            "assignee": "john.doe",
                            "subtask_count": 5,
                            "subtask_done": 5
                        }
                    ],
                    "summary": {
                        "total": 20,
                        "done": 15,
                        "in_progress": 3,
                        "blocked": 1,
                        "todo": 1,
                        "completion_percent": 75
                    }
                },
                "manual": {...},
                "non_functional": {...},
                "other": {...}
            },
            "overall_summary": {
                "total": 50,
                "done": 35,
                "in_progress": 10,
                "blocked": 2,
                "completion_percent": 70
            },
            "dataSource": "jira-direct"
        }

    CATEGORY CLASSIFICATION (based on story summary):
        - automation: Keywords like "automation", "automated"
        - manual: Keywords like "manual", "feature validation"
        - non_functional: Keywords like "performance", "load", "stress"
        - other: Uncategorized items

    TESTRAIL MAPPING (for automation stories):
        - "Automated Regression for Backend" → "Backend Regression" TestRail run
        - Story summaries are matched to TestRail runs in the frontend

    RELATED ENDPOINTS:
        - GET /api/jira/regression-tracking/progress - Timeline/chart data
        - GET /api/jira/release-readiness - Release tracking
        - GET /api/testrail/milestone-data - TestRail test execution
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        # Step 1: Fetch the parent epic
        parent_epic_data = await jira.get_issue(epic_key)
        if not parent_epic_data:
            raise HTTPException(status_code=404, detail=f"Epic {epic_key} not found")

        parent_epic = {
            "key": parent_epic_data.get("key"),
            "summary": parent_epic_data.get("summary"),
            "status": parent_epic_data.get("status"),
            "url": f"https://your-org.atlassian.net/browse/{epic_key}",
        }

        # Step 2: Fetch all child Stories directly under the parent epic via Parent Link
        child_stories = []
        query_used = None

        try:
            # Primary approach: Parent Link (used in R135+ hierarchy)
            parent_link_jql = f'"Parent Link" = {epic_key} ORDER BY status ASC, priority DESC'
            child_stories = await jira.search_issues(parent_link_jql, max_results=1000, fetch_all=True)
            if child_stories:
                query_used = "Parent Link"
                logger.info(f"Found {len(child_stories)} stories via Parent Link for {epic_key}")
        except Exception as e:
            logger.debug(f"Parent Link query failed: {e}")

        # Fallback: Epic Link (for classic projects)
        if not child_stories:
            try:
                epic_link_jql = f'"Epic Link" = {epic_key} ORDER BY status ASC, priority DESC'
                child_stories = await jira.search_issues(epic_link_jql, max_results=1000, fetch_all=True)
                if child_stories:
                    query_used = "Epic Link"
                    logger.info(f"Found {len(child_stories)} stories via Epic Link for {epic_key}")
            except Exception as e:
                logger.debug(f"Epic Link query failed: {e}")

        logger.info(f"Total child stories found for {epic_key}: {len(child_stories)} (query: {query_used})")

        # Step 3: Initialize categories - will contain flattened subtasks (not stories)
        categories = {
            "automation": {"stories": [], "summary": {}},
            "manual": {"stories": [], "summary": {}},
            "non_functional": {"stories": [], "summary": {}},
            "other": {"stories": [], "summary": {}},
        }

        # Step 4: Classify each story by its summary and fetch its subtasks
        if child_stories:
            # Prepare stories with their categories based on summary keywords
            stories_with_category = [
                (classify_epic_category(story.get("summary", "")), story) for story in child_stories
            ]

            # Build story data for all stories in parallel (includes fetching subtasks)
            story_data_tasks = [_build_story_data(jira, story) for (_, story) in stories_with_category]
            story_data_results = await asyncio.gather(*story_data_tasks, return_exceptions=True)

            # Flatten: Add subtasks directly to categories (not the parent stories)
            for (category, _), story_data in zip(stories_with_category, story_data_results):
                if isinstance(story_data, Exception):
                    logger.warning(f"Error building story data: {story_data}")
                    continue

                # Add parent story info to each subtask and flatten into category
                parent_info = {
                    "parent_key": story_data["key"],
                    "parent_summary": story_data["summary"],
                    "parent_url": story_data["url"],
                }

                for subtask in story_data.get("subtasks", []):
                    # Merge parent info into subtask
                    subtask_with_parent = {**subtask, **parent_info}
                    categories[category]["stories"].append(subtask_with_parent)

                # If no subtasks, add the story itself (fallback)
                if not story_data.get("subtasks"):
                    categories[category]["stories"].append(story_data)

        # Step 5: Calculate summaries for each category (now based on subtasks)
        overall_summary = {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "todo": 0}

        for cat_key, cat_data in categories.items():
            items = cat_data["stories"]  # These are now subtasks
            total = len(items)
            done = sum(1 for s in items if s["status_category"] == "done")
            in_progress = sum(1 for s in items if s["status_category"] == "in_progress")
            blocked = sum(1 for s in items if s["status_category"] == "blocked")
            todo = total - done - in_progress - blocked

            cat_data["summary"] = {
                "total": total,
                "done": done,
                "in_progress": in_progress,
                "blocked": blocked,
                "todo": todo,
                "completion_percent": round((done / total * 100) if total > 0 else 0),
            }

            # Add to overall summary
            overall_summary["total"] += total
            overall_summary["done"] += done
            overall_summary["in_progress"] += in_progress
            overall_summary["blocked"] += blocked
            overall_summary["todo"] += todo

        overall_summary["completion_percent"] = round(
            (overall_summary["done"] / overall_summary["total"] * 100) if overall_summary["total"] > 0 else 0
        )

        # Step 6: Build labels summary as platform → feature hierarchy
        # Map raw prefixes to display platform categories
        PREFIX_TO_PLATFORM = [
            ("w11-64bit", "Windows 11"),
            ("w11-32bit", "Windows 11"),
            ("w10-64bit", "Windows 10"),
            ("w10-32bit", "Windows 10"),
            ("windows", "Windows"),
            ("mac", "Mac"),
            ("android", "Android"),
            ("ios", "iOS"),
            ("chrome", "Chrome"),
            ("installupg", "InstallUPG"),
            ("interop", "Interop"),
        ]
        SKIP_LABELS = {"no-code", "no_code", "client-regression"}

        def _parse_label(label: str):
            """Parse label into (platform_display, feature). Returns None if skipped."""
            ll = label.lower()
            if ll in SKIP_LABELS:
                return None
            for prefix, platform_name in PREFIX_TO_PLATFORM:
                if ll.startswith(prefix + "-"):
                    feature = label[len(prefix) + 1 :]
                    return platform_name, feature
                if ll == prefix:
                    return platform_name, prefix
            return None

        labels_summary = {}
        for cat_data in categories.values():
            for item in cat_data["stories"]:
                for label in item.get("labels", []):
                    parsed = _parse_label(label)
                    if not parsed:
                        continue
                    platform, feature = parsed
                    status_cat = item.get("status_category", "todo")

                    if platform not in labels_summary:
                        labels_summary[platform] = {
                            "total": 0,
                            "done": 0,
                            "in_progress": 0,
                            "blocked": 0,
                            "todo": 0,
                            "features": {},
                        }
                    labels_summary[platform]["total"] += 1
                    labels_summary[platform][status_cat] = labels_summary[platform].get(status_cat, 0) + 1

                    if feature not in labels_summary[platform]["features"]:
                        labels_summary[platform]["features"][feature] = {
                            "total": 0,
                            "done": 0,
                            "in_progress": 0,
                            "blocked": 0,
                            "todo": 0,
                        }
                    labels_summary[platform]["features"][feature]["total"] += 1
                    labels_summary[platform]["features"][feature][status_cat] = (
                        labels_summary[platform]["features"][feature].get(status_cat, 0) + 1
                    )

        # Cache the summary for Overview page (lightweight read)
        try:
            cache_data = {
                "epic_key": epic_key,
                "overall_summary": overall_summary,
                "updated_at": datetime.now().isoformat(),
            }
            _save_regression_cache(epic_key, cache_data)
        except Exception as cache_err:
            logger.warning(f"Failed to cache regression summary: {cache_err}")

        return {
            "parent_epic": parent_epic,
            "categories": categories,
            "overall_summary": overall_summary,
            "labels_summary": labels_summary,
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching regression tracking hierarchy: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


@router.get("/regression-tracking/quick-summary")
async def get_regression_quick_summary(
    epic_key: str = Query(..., description="Regression epic key"),
):
    """
    Get lightweight regression progress (only 2 JIRA calls).

    This endpoint is optimized for the Overview page - it fetches only
    the counts needed for progress calculation, not the full hierarchy.

    APPROACH:
        1. Fetch all stories under the epic (1 JIRA call)
        2. Fetch all subtasks for those stories in ONE batch query (1 JIRA call)
        3. Count statuses and calculate percentage

    RETURNS:
        {
            "epic_key": "ENG-856257",
            "overall_summary": {
                "total": 100,
                "done": 51,
                "in_progress": 30,
                "blocked": 5,
                "todo": 14,
                "completion_percent": 51
            },
            "dataSource": "jira-quick"
        }
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        # Step 1: Get all stories under the epic (1 JIRA call)
        stories = []
        try:
            parent_link_jql = f'"Parent Link" = {epic_key}'
            stories = await jira.search_issues(parent_link_jql, max_results=500, fetch_all=True)
            logger.info(f"Quick summary: Found {len(stories)} stories under {epic_key}")
        except Exception as e:
            logger.debug(f"Parent Link query failed: {e}")
            # Fallback to Epic Link
            try:
                epic_link_jql = f'"Epic Link" = {epic_key}'
                stories = await jira.search_issues(epic_link_jql, max_results=500, fetch_all=True)
            except Exception as e2:
                logger.warning(f"Epic Link query also failed: {e2}")

        if not stories:
            return {
                "epic_key": epic_key,
                "overall_summary": {
                    "total": 0,
                    "done": 0,
                    "in_progress": 0,
                    "blocked": 0,
                    "todo": 0,
                    "completion_percent": 0,
                },
                "dataSource": "jira-quick",
            }

        # Step 2: Get all subtasks for these stories in ONE query (1 JIRA call)
        story_keys = [s.get("key") for s in stories if s.get("key")]

        # Build batch query: "Parent Link" in (STORY1, STORY2, ...)
        # JIRA has limits, so chunk if needed
        all_subtasks = []
        chunk_size = 50  # JIRA IN clause limit

        for i in range(0, len(story_keys), chunk_size):
            chunk = story_keys[i : i + chunk_size]
            keys_str = ", ".join(chunk)
            subtasks_jql = f'"Parent Link" in ({keys_str})'

            try:
                subtasks = await jira.search_issues(subtasks_jql, max_results=1000, fetch_all=True)
                all_subtasks.extend(subtasks)
            except Exception as e:
                logger.warning(f"Failed to fetch subtasks batch: {e}")

        logger.info(f"Quick summary: Found {len(all_subtasks)} total subtasks")

        # Step 3: Count statuses
        total = len(all_subtasks)
        done = 0
        in_progress = 0
        blocked = 0

        for subtask in all_subtasks:
            status = subtask.get("status", "").lower()
            status_cat = get_status_category(status)

            if status_cat == "done":
                done += 1
            elif status_cat == "in_progress":
                in_progress += 1
            elif status_cat == "blocked":
                blocked += 1

        todo = total - done - in_progress - blocked
        completion_percent = round((done / total * 100) if total > 0 else 0)

        return {
            "epic_key": epic_key,
            "overall_summary": {
                "total": total,
                "done": done,
                "in_progress": in_progress,
                "blocked": blocked,
                "todo": todo,
                "completion_percent": completion_percent,
            },
            "dataSource": "jira-quick",
            "generatedAt": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching quick regression summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


async def _build_story_data(jira, issue: dict) -> dict:
    """Build issue data (Story) with its subtasks."""
    issue_key = issue.get("key")
    status = issue.get("status", "")
    status_category = get_status_category(status)
    issue_type = issue.get("issuetype", "Story")

    # Fetch subtasks for this story via Parent Link (R135+ hierarchy)
    subtasks = []
    subtask_done = 0
    subtask_issues = []

    try:
        subtasks_jql = f'"Parent Link" = {issue_key} ORDER BY status ASC'
        subtask_issues = await jira.search_issues(subtasks_jql, max_results=200, fetch_all=True)
        if subtask_issues:
            logger.info(f"Found {len(subtask_issues)} subtasks for {issue_key}")
    except Exception as e:
        logger.warning(f"Failed to fetch subtasks for {issue_key}: {e}")

    # Process subtasks
    for subtask in subtask_issues:
        sub_status = subtask.get("status", "")
        sub_status_category = get_status_category(sub_status)
        subtasks.append(
            {
                "key": subtask.get("key"),
                "summary": subtask.get("summary"),
                "status": sub_status,
                "status_category": sub_status_category,
                "issuetype": subtask.get("issuetype", "Sub-task"),
                "assignee": subtask.get("assignee"),
                "assignee_email": subtask.get("assignee_email", ""),
                "qa": subtask.get("qa"),
                "qa_email": subtask.get("qa_email", ""),
                "url": f"https://your-org.atlassian.net/browse/{subtask.get('key')}",
                "labels": subtask.get("labels", []),
            }
        )
        if sub_status_category == "done":
            subtask_done += 1

    return {
        "key": issue_key,
        "summary": issue.get("summary"),
        "status": status,
        "status_category": status_category,
        "issuetype": issue_type,
        "assignee": issue.get("assignee"),
        "assignee_email": issue.get("assignee_email", ""),
        "qa": issue.get("qa"),
        "qa_email": issue.get("qa_email", ""),
        "priority": issue.get("priority"),
        "url": f"https://your-org.atlassian.net/browse/{issue_key}",
        "labels": issue.get("labels", []),
        "subtask_count": len(subtasks),
        "subtask_done": subtask_done,
        "subtasks": subtasks,
    }


@router.get("/regression-tracking/progress")
async def get_regression_tracking_progress(
    epic_key: str = Query(..., description="Parent epic key for regression tracking"),
):
    """
    Get progress/timeline data for regression tracking.

    Returns chart data showing completion over time based on issue resolution dates.
    Matches the hierarchy endpoint by querying subtasks under child stories.

    Hierarchy: Parent Epic -> Child Stories -> Subtasks (tracked items)
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        # Step 1: Fetch child stories under the parent epic (same as hierarchy endpoint)
        child_stories = []

        # Primary: Parent Link (R135+ hierarchy)
        try:
            parent_link_jql = f'"Parent Link" = {epic_key} ORDER BY key ASC'
            child_stories = await jira.search_issues(parent_link_jql, max_results=1000, fetch_all=True)
            if child_stories:
                logger.info(f"Progress: Found {len(child_stories)} child stories via Parent Link")
        except Exception as e:
            logger.debug(f"Parent Link query failed: {e}")

        # Fallback: Epic Link (classic projects)
        if not child_stories:
            try:
                epic_link_jql = f'"Epic Link" = {epic_key} ORDER BY key ASC'
                child_stories = await jira.search_issues(epic_link_jql, max_results=1000, fetch_all=True)
                if child_stories:
                    logger.info(f"Progress: Found {len(child_stories)} child stories via Epic Link")
            except Exception as e:
                logger.debug(f"Epic Link query failed: {e}")

        # Step 2: For each child story, fetch its resolved subtasks
        all_resolved_items = []

        async def fetch_resolved_subtasks(story_key: str):
            """Fetch resolved subtasks for a given story."""
            try:
                subtasks_jql = f""""Parent Link" = {story_key}
                    AND status IN (Done, Closed, Completed, Resolved, "Pending Close")
                    ORDER BY resolutiondate ASC"""
                subtasks = await jira.search_issues(subtasks_jql, max_results=500, fetch_all=True)
                return subtasks
            except Exception as e:
                logger.warning(f"Failed to fetch subtasks for {story_key}: {e}")
                return []

        # Fetch subtasks for all stories in parallel
        if child_stories:
            story_keys = [story.get("key") for story in child_stories if story.get("key")]
            subtask_results = await asyncio.gather(
                *[fetch_resolved_subtasks(key) for key in story_keys], return_exceptions=True
            )

            for result in subtask_results:
                if isinstance(result, list):
                    all_resolved_items.extend(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Error fetching subtasks: {result}")

            logger.info(f"Progress: Found {len(all_resolved_items)} resolved subtasks total")

        # Fallback: If no subtasks found, check if stories themselves are the work items
        # (for cases where there's no subtask level)
        if not all_resolved_items and child_stories:
            resolved_stories = [
                s
                for s in child_stories
                if s.get("status", "").lower() in ["done", "closed", "completed", "resolved", "pending close"]
            ]
            all_resolved_items = resolved_stories
            logger.info(f"Progress: Using {len(all_resolved_items)} resolved stories (no subtasks found)")

        # Step 3: Build daily completion counts from resolved items
        daily_counts = {}
        for issue in all_resolved_items:
            # Use resolutiondate or updated as fallback
            resolved_date = issue.get("resolutiondate") or issue.get("updated")
            if resolved_date:
                # Extract just the date part (YYYY-MM-DD)
                date_str = resolved_date[:10] if len(resolved_date) >= 10 else None
                if date_str:
                    if date_str not in daily_counts:
                        daily_counts[date_str] = 0
                    daily_counts[date_str] += 1

        # Sort by date and build cumulative chart data
        sorted_dates = sorted(daily_counts.keys())
        chart_data = []
        cumulative_total = 0

        for date_str in sorted_dates:
            cumulative_total += daily_counts[date_str]
            try:
                display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
            except ValueError:
                display_date = date_str

            chart_data.append(
                {
                    "date": date_str,
                    "displayDate": display_date,
                    "daily": daily_counts[date_str],
                    "total": cumulative_total,
                }
            )

        # Calculate summary stats
        total_days = len(sorted_dates)
        avg_per_day = round(cumulative_total / total_days, 1) if total_days > 0 else 0

        return {
            "epic_key": epic_key,
            "chartData": chart_data,
            "summary": {
                "totalCompleted": cumulative_total,
                "daysWithProgress": total_days,
                "avgPerDay": avg_per_day,
            },
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching regression tracking progress: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


@router.get("/issue/{issue_key}")
async def get_issue(issue_key: str):
    """
    Get a single JIRA issue by key.

    Returns issue details including summary, status, assignee, priority, etc.
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        issue = await jira.get_issue(issue_key)
        if not issue:
            raise HTTPException(status_code=404, detail=f"Issue {issue_key} not found")

        return {
            "issue_key": issue_key,
            "issue": issue,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching issue %s: %s", issue_key, e)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


@router.get("/search")
async def search_issues(
    jql: str = Query(..., description="JQL query string"),
    max_results: int = Query(default=50, description="Maximum number of results"),
):
    """
    Search JIRA issues using JQL.

    This is a flexible endpoint that allows any JQL query.

    Examples:
        - fixVersion = "135.0" AND assignee IS EMPTY
        - project = ENG AND status = Open
        - issuetype = Bug AND priority = P0
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        issues = await jira.search_issues(jql, max_results=max_results)
        return {
            "jql": jql,
            "count": len(issues),
            "issues": issues,
        }
    except Exception as e:
        logger.error("Error searching issues with JQL '%s': %s", jql, e)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


@router.get("/issue/{issue_key}/comments")
async def get_issue_comments(
    issue_key: str,
    max_comments: int = Query(default=5, description="Maximum number of comments to return"),
):
    """Get comments for a specific JIRA issue."""
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        comments = await jira.get_issue_comments(issue_key, max_results=max_comments)
        return {
            "issue_key": issue_key,
            "comments": comments,
            "count": len(comments),
        }
    except Exception as e:
        logger.error("Error fetching comments for %s: %s", issue_key, e)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


@router.get("/issue/{issue_key}/parsed-comments")
async def get_issue_parsed_comments(
    issue_key: str,
    use_semantic: bool = Query(
        True, description="Use semantic intent classification (faster pattern fallback if unavailable)"
    ),
):
    """
    Get parsed/structured comments for a JIRA issue with semantic intent classification.

    Uses embeddings to semantically understand comment intent:
    - passed: Test completed successfully
    - failed: Test failed, regression found
    - blocked: Waiting for dependency, cannot proceed
    - in_progress: Currently testing
    - info: General status update

    Falls back to fast pattern matching if embeddings unavailable.
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        comments = await jira.get_issue_comments(issue_key, max_results=10)

        if not comments:
            return {
                "issue_key": issue_key,
                "intent": "info",
                "test_results": [],
                "summary_notes": [],
                "passed_count": 0,
                "failed_count": 0,
                "in_progress_count": 0,
                "blocked_count": 0,
                "classification_method": "none",
            }

        # Try semantic classification if enabled
        if use_semantic:
            try:
                from services.intent_classifier import get_intent_classifier

                classifier = await get_intent_classifier()
                if classifier._initialized:
                    result = await classifier.classify_comments(comments)
                    return {
                        "issue_key": issue_key,
                        "intent": result["intent"],
                        "test_results": result["test_results"][:20],
                        "summary_notes": result["summary_notes"],
                        "passed_count": result["passed_count"],
                        "failed_count": result["failed_count"],
                        "in_progress_count": result["in_progress_count"],
                        "blocked_count": result.get("blocked_count", 0),
                        "classification_method": "semantic",
                    }
            except Exception as e:
                logger.warning("Semantic classification failed, using pattern fallback: %s", e)

        # Pattern-based fallback (fast, no external dependencies)
        from services.intent_classifier import classify_by_pattern

        test_results = []
        summary_notes = []
        passed_count = 0
        failed_count = 0
        in_progress_count = 0
        blocked_count = 0
        overall_intent = "info"

        for comment in comments:
            body = comment.get("body", "")
            if not body.strip():
                continue

            intent, results = classify_by_pattern(body)
            test_results.extend(results)

            # Count by status
            for r in results:
                if r["status"] == "passed":
                    passed_count += 1
                elif r["status"] == "failed":
                    failed_count += 1
                elif r["status"] == "in_progress":
                    in_progress_count += 1
                elif r["status"] == "blocked":
                    blocked_count += 1

            # Update overall intent (priority-based)
            if intent == "failed" or (intent != "info" and overall_intent == "info"):
                overall_intent = intent

            # Extract summary notes from comments without explicit markers
            if not results:
                lines = body.split("\n")
                for line in lines:
                    line_stripped = line.strip()
                    if len(line_stripped) > 15 and not line_stripped.startswith(("#", "-", "*", "[")):
                        if len(summary_notes) < 3:
                            summary_notes.append(line_stripped[:200])
                        break

        return {
            "issue_key": issue_key,
            "intent": overall_intent,
            "test_results": test_results[:20],
            "summary_notes": summary_notes,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "in_progress_count": in_progress_count,
            "blocked_count": blocked_count,
            "classification_method": "pattern",
        }
    except Exception as e:
        logger.error("Error fetching parsed comments for %s: %s", issue_key, e)
        raise HTTPException(status_code=500, detail=f"JIRA error: {str(e)}") from e


# =============================================================================
# Dashboard Endpoints
# =============================================================================


# =============================================================================
# Release Readiness Tracking
# =============================================================================

COMPONENT_JQL_MAP = {
    "YOUR_PRODUCT": 'component = "NS Client (NSC)"',
}
TRACKED_COMPONENTS = list(COMPONENT_JQL_MAP.keys())


# =============================================================================
# Milestone Tracking Endpoints
# =============================================================================


@router.get("/milestone/irr")
async def get_irr_milestone_data(
    release: Optional[str] = Query(None),
    component: Optional[str] = Query(None, description="Component filter: YOUR_PRODUCT"),
):
    """
    Get IRR (Internal Release Review) milestone tracking data.

    PURPOSE:
        Tracks resolution status against the IRR milestone date. Shows
        which items were resolved on time, late, or still open. Used
        to measure release readiness at the IRR checkpoint.

    WHEN TO USE:
        - Viewing IRR milestone status on Release Readiness page
        - Checking how many items missed the IRR deadline
        - Identifying late resolutions for retrospective
        - Tracking on-time rate for release health

    PARAMETERS:
        - release (str): Release ID like "R135" (default: current release)
        - component (str): Component filter, currently "YOUR_PRODUCT"

    RETURNS:
        {
            "release": "R135",
            "milestone": "IRR",
            "milestoneName": "Internal Release Review",
            "milestoneDate": "2026-01-10",
            "deadlinePassed": true,
            "daysSinceDeadline": 5,
            "status": "yellow",
            "summary": {
                "totalStories": 50,
                "resolvedOnTime": 40,
                "resolvedAfterDeadline": 5,
                "stillOpen": 5,
                "onTimePercentage": 80
            },
            "issues": [...],        # Still open items
            "lateIssues": [...],    # Resolved after deadline
            "by_assignee": {...}    # Breakdown by assignee
        }

    MILESTONE REQUIREMENT:
        All Stories and Bugs should be RESOLVED by IRR date.

    RELATED ENDPOINTS:
        - GET /api/jira/milestone/branch-cut - Branch cut milestone
        - GET /api/jira/milestone/final-build - Final build milestone
        - GET /api/jira/resolution-progress - Daily resolution chart
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    release_id = get_release_id_from_param(release)
    _, fix_version, next_fix_version = parse_version_from_release(release_id)
    release_dates = get_release_dates(release_id)

    if not release_dates or not release_dates.get("irr"):
        return {"error": f"No IRR date configured for {release_id}", "release": release_id}

    irr_date = parse_date_safe(release_dates.get("irr")).date()
    irr_date_str = irr_date.strftime("%Y-%m-%d")
    final_build_date = parse_date_safe(release_dates.get("final_build")).date()
    today = datetime.now().date()
    deadline_passed = today > irr_date

    # Limit "resolved late" to final_build_date for consistency with Resolution Progress
    end_date = min(today, final_build_date)
    end_date_str = end_date.strftime("%Y-%m-%d")

    try:
        # Get milestone data - YOUR_PRODUCT only, includes both Stories and Bugs
        result = await jira.get_milestone_data(
            fix_version=fix_version,
            next_fix_version=next_fix_version,
            milestone_date=irr_date_str,
            include_bugs=True,
            final_build_date=end_date_str,
        )

        # Extract counts
        still_open = result.get("still_open", 0)
        resolved_on_time = result.get("resolved_on_time", 0)
        resolved_late = result.get("resolved_late", 0)
        total_items = result.get("total_items", 0)
        stories_data = result.get("stories", {})
        bugs_data = result.get("bugs", {})

        # Determine status based on open items
        if still_open == 0:
            status = "green"
        elif result.get("on_time_rate", 0) >= 80:
            status = "yellow"
        else:
            status = "red"

        # Build component data for YOUR_PRODUCT
        components = {
            "YOUR_PRODUCT": {
                "resolvedOnTime": resolved_on_time,
                "counts": {
                    "total": total_items,
                    "resolvedOnTime": resolved_on_time,
                    "resolvedAfterDeadline": resolved_late,
                    "stillOpen": still_open,
                    "totalMissed": resolved_late + still_open,
                    # Story/Bug breakdown
                    "stories": stories_data,
                    "bugs": bugs_data,
                },
            }
        }

        # Build summary
        summary = {
            "totalStories": total_items,  # Total items (stories + bugs)
            "resolvedOnTime": resolved_on_time,
            "resolvedAfterDeadline": resolved_late,
            "stillOpen": still_open,
            "totalMissed": resolved_late + still_open,
            "onTimePercentage": result.get("on_time_rate", 0),
            "byComponent": {k: v["counts"] for k, v in components.items()},
            # Detailed breakdown
            "stories": stories_data,
            "bugs": bugs_data,
        }

        # Build issues list from open issues
        open_issues = result.get("open_issues", [])
        late_issues = result.get("late_issues", [])

        issues = [
            {
                "key": issue.get("key"),
                "summary": issue.get("summary"),
                "assignee": issue.get("assignee", "Unassigned"),
                "priority": issue.get("priority"),
                "status": issue.get("status"),
                "type": issue.get("issuetype", "Story"),
                "url": issue.get("url"),
                "component": "YOUR_PRODUCT",
            }
            for issue in open_issues
        ]

        return {
            "release": release_id,
            "fixVersion": fix_version,
            "milestone": "IRR",
            "milestoneName": "Internal Release Review",
            "milestoneDate": irr_date_str,
            "irrPassed": deadline_passed,
            "deadlinePassed": deadline_passed,
            "daysToIRR": (irr_date - today).days if not deadline_passed else None,
            "daysToDeadline": (irr_date - today).days if not deadline_passed else None,
            "daysSinceIRR": (today - irr_date).days if deadline_passed else None,
            "daysSinceDeadline": (today - irr_date).days if deadline_passed else None,
            "requirement": "All Stories and Bugs should be RESOLVED by IRR",
            "status": status,
            # Frontend expected fields
            "components": components,
            "summary": summary,
            "issues": issues,
            "lateIssues": [
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "assignee": issue.get("assignee", "Unassigned"),
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "type": issue.get("issuetype", "Story"),
                    "component": "YOUR_PRODUCT",
                }
                for issue in late_issues
            ],
            # Raw data
            "total_items": total_items,
            "resolved_on_time": resolved_on_time,
            "resolved_late": resolved_late,
            "still_open": still_open,
            "on_time_rate": result.get("on_time_rate", 0),
            "by_assignee": result.get("by_assignee", {}),
            "late_by_assignee": result.get("late_by_assignee", {}),
            # JQL queries for transparency (displayed in info tooltips)
            "jql": result.get("jql", {}),
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Error fetching IRR data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/milestone/branch-cut")
async def get_branch_cut_milestone_data(
    release: Optional[str] = Query(None),
    component: Optional[str] = Query(None, description="Component filter: YOUR_PRODUCT"),
):
    """
    Get Branch Cut milestone tracking for YOUR_PRODUCT component.

    Tracks all Stories and Bugs for the release, categorized by:
    - Resolved On Time: Resolved on or before Branch Cut date
    - Resolved Late: Resolved after Branch Cut date
    - Still Open: Not yet resolved
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    release_id = get_release_id_from_param(release)
    _, fix_version, next_fix_version = parse_version_from_release(release_id)
    release_dates = get_release_dates(release_id)

    if not release_dates or not release_dates.get("branch_cut"):
        return {"error": f"No Branch Cut date configured for {release_id}", "release": release_id}

    branch_cut_date = parse_date_safe(release_dates.get("branch_cut")).date()
    branch_cut_date_str = branch_cut_date.strftime("%Y-%m-%d")
    final_build_date = parse_date_safe(release_dates.get("final_build")).date()
    today = datetime.now().date()
    deadline_passed = today > branch_cut_date

    # Limit "resolved late" to final_build_date for consistency with Resolution Progress
    end_date = min(today, final_build_date)
    end_date_str = end_date.strftime("%Y-%m-%d")

    try:
        # Get milestone data - YOUR_PRODUCT only, includes both Stories and Bugs
        result = await jira.get_milestone_data(
            fix_version=fix_version,
            next_fix_version=next_fix_version,
            milestone_date=branch_cut_date_str,
            include_bugs=True,
            final_build_date=end_date_str,
        )

        # Extract counts
        still_open = result.get("still_open", 0)
        resolved_on_time = result.get("resolved_on_time", 0)
        resolved_late = result.get("resolved_late", 0)
        total_items = result.get("total_items", 0)
        stories_data = result.get("stories", {})
        bugs_data = result.get("bugs", {})

        # Determine status
        if still_open == 0:
            status = "green"
        elif result.get("on_time_rate", 0) >= 80:
            status = "yellow"
        else:
            status = "red"

        # Build component data for YOUR_PRODUCT
        components = {
            "YOUR_PRODUCT": {
                "resolvedOnTime": resolved_on_time,
                "counts": {
                    "total": total_items,
                    "resolvedOnTime": resolved_on_time,
                    "resolvedAfterDeadline": resolved_late,
                    "stillOpen": still_open,
                    "totalMissed": resolved_late + still_open,
                    "stories": stories_data,
                    "bugs": bugs_data,
                },
            }
        }

        summary = {
            "totalStories": total_items,
            "resolvedOnTime": resolved_on_time,
            "resolvedAfterDeadline": resolved_late,
            "stillOpen": still_open,
            "totalMissed": resolved_late + still_open,
            "onTimePercentage": result.get("on_time_rate", 0),
            "byComponent": {k: v["counts"] for k, v in components.items()},
            "stories": stories_data,
            "bugs": bugs_data,
        }

        open_issues = result.get("open_issues", [])
        late_issues = result.get("late_issues", [])

        issues = [
            {
                "key": issue.get("key"),
                "summary": issue.get("summary"),
                "assignee": issue.get("assignee", "Unassigned"),
                "priority": issue.get("priority"),
                "status": issue.get("status"),
                "type": issue.get("issuetype", "Story"),
                "url": issue.get("url"),
                "component": "YOUR_PRODUCT",
            }
            for issue in open_issues
        ]

        return {
            "release": release_id,
            "fixVersion": fix_version,
            "milestone": "BRANCH_CUT",
            "milestoneName": "Branch Cut",
            "milestoneDate": branch_cut_date_str,
            "deadlinePassed": deadline_passed,
            "daysToDeadline": (branch_cut_date - today).days if not deadline_passed else None,
            "daysSinceDeadline": (today - branch_cut_date).days if deadline_passed else None,
            "requirement": "All Stories and Bugs should be RESOLVED by Branch Cut",
            "status": status,
            "components": components,
            "summary": summary,
            "issues": issues,
            "lateIssues": [
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "assignee": issue.get("assignee", "Unassigned"),
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "type": issue.get("issuetype", "Story"),
                    "component": "YOUR_PRODUCT",
                }
                for issue in late_issues
            ],
            "total_items": total_items,
            "resolved_on_time": resolved_on_time,
            "resolved_late": resolved_late,
            "still_open": still_open,
            "on_time_rate": result.get("on_time_rate", 0),
            "by_assignee": result.get("by_assignee", {}),
            "late_by_assignee": result.get("late_by_assignee", {}),
            # JQL queries for transparency (displayed in info tooltips)
            "jql": result.get("jql", {}),
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Error fetching Branch Cut data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/milestone/final-build")
async def get_final_build_milestone_data(
    release: Optional[str] = Query(None),
    component: Optional[str] = Query(None, description="Component filter: YOUR_PRODUCT"),
):
    """
    Get Final Build milestone tracking for YOUR_PRODUCT component.

    Tracks all Stories and Bugs for the release, categorized by:
    - Closed On Time: Resolved/Closed on or before Final Build date
    - Closed Late: Resolved/Closed after Final Build date
    - Still Open: Not yet resolved/closed

    Requirement: All stories AND bugs should be CLOSED or COMPLETED.
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    release_id = get_release_id_from_param(release)
    _, fix_version, next_fix_version = parse_version_from_release(release_id)
    release_dates = get_release_dates(release_id)
    today = datetime.now().date()

    if not release_dates or not release_dates.get("final_build"):
        return {"error": f"No Final Build date configured for {release_id}", "release": release_id}

    final_build_date = parse_date_safe(release_dates.get("final_build")).date()
    final_build_date_str = final_build_date.strftime("%Y-%m-%d")
    deadline_passed = today > final_build_date
    days_since = (today - final_build_date).days if deadline_passed else None
    days_to = (final_build_date - today).days if not deadline_passed else None

    # Limit "resolved late" to final_build_date for consistency with Resolution Progress
    end_date = min(today, final_build_date)
    end_date_str = end_date.strftime("%Y-%m-%d")

    try:
        # Get milestone data - YOUR_PRODUCT only, includes both Stories and Bugs
        result = await jira.get_milestone_data(
            fix_version=fix_version,
            next_fix_version=next_fix_version,
            milestone_date=final_build_date_str,
            include_bugs=True,
            final_build_date=end_date_str,
        )

        # Extract counts
        still_open = result.get("still_open", 0)
        resolved_on_time = result.get("resolved_on_time", 0)
        resolved_late = result.get("resolved_late", 0)
        total_items = result.get("total_items", 0)
        stories_data = result.get("stories", {})
        bugs_data = result.get("bugs", {})

        # Determine status
        if still_open == 0:
            status = "green"
        elif result.get("on_time_rate", 0) >= 80:
            status = "yellow"
        else:
            status = "red"

        # Build component data for YOUR_PRODUCT
        components = {
            "YOUR_PRODUCT": {
                "closedOnTime": resolved_on_time,
                "counts": {
                    "total": total_items,
                    "closedOnTime": resolved_on_time,
                    "closedLate": resolved_late,
                    "notClosed": still_open,
                    "storiesNotClosed": stories_data.get("open", 0),
                    "bugsNotClosed": bugs_data.get("open", 0),
                    "stories": stories_data,
                    "bugs": bugs_data,
                },
            }
        }

        summary = {
            "totalItems": total_items,
            "closedOnTime": resolved_on_time,
            "closedLate": resolved_late,
            "totalNotClosed": still_open,
            "storiesNotClosed": stories_data.get("open", 0),
            "bugsNotClosed": bugs_data.get("open", 0),
            "onTimePercentage": result.get("on_time_rate", 0),
            "byComponent": {k: v["counts"] for k, v in components.items()},
            "stories": stories_data,
            "bugs": bugs_data,
        }

        open_issues = result.get("open_issues", [])
        late_issues = result.get("late_issues", [])

        issues = [
            {
                "key": issue.get("key"),
                "summary": issue.get("summary"),
                "assignee": issue.get("assignee", "Unassigned"),
                "priority": issue.get("priority"),
                "status": issue.get("status"),
                "type": issue.get("issuetype", "Story"),
                "url": issue.get("url"),
                "component": "YOUR_PRODUCT",
            }
            for issue in open_issues
        ]

        return {
            "release": release_id,
            "fixVersion": fix_version,
            "milestone": "FINAL_BUILD",
            "milestoneName": "Final Build",
            "milestoneDate": final_build_date_str,
            "deadlinePassed": deadline_passed,
            "daysToDeadline": days_to,
            "daysSinceDeadline": days_since,
            "requirement": "All Stories AND Bugs should be CLOSED or COMPLETED",
            "status": status,
            "components": components,
            "summary": summary,
            "issues": issues,
            "lateIssues": [
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "assignee": issue.get("assignee", "Unassigned"),
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "type": issue.get("issuetype", "Story"),
                    "component": "YOUR_PRODUCT",
                }
                for issue in late_issues
            ],
            "qualityMetrics": {
                "totalItems": total_items,
                "closedOnTime": resolved_on_time,
                "closedLate": resolved_late,
                "onTimeRate": result.get("on_time_rate", 0),
                "notClosedCount": still_open,
                "status": "good" if still_open == 0 else "warning" if still_open <= 5 else "critical",
            },
            "total_items": total_items,
            "resolved_on_time": resolved_on_time,
            "resolved_late": resolved_late,
            "still_open": still_open,
            "on_time_rate": result.get("on_time_rate", 0),
            "by_assignee": result.get("by_assignee", {}),
            "late_by_assignee": result.get("late_by_assignee", {}),
            # JQL queries for transparency (displayed in info tooltips)
            "jql": result.get("jql", {}),
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Error fetching Final Build data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/resolution-progress")
async def get_resolution_progress(release: Optional[str] = Query(None)):
    """
    Get day-wise resolution progress for bugs and stories from IRR to Final Build.

    Shows cumulative resolved count per day for each component, useful for
    tracking progress as a graph over time. Uses direct JIRA API.
    """
    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    release_id = get_release_id_from_param(release)
    version_num, fix_version, next_fix_version = parse_version_from_release(release_id)
    release_dates = get_release_dates(release_id)
    today = datetime.now().date()

    if not release_dates:
        return {"error": f"No release dates configured for {release_id}", "release": release_id}

    irr_date = parse_date_safe(release_dates.get("irr")).date()
    final_build_date = parse_date_safe(release_dates.get("final_build")).date()

    # End date is the earlier of today or final_build_date
    end_date = min(today, final_build_date)

    try:
        # Fetch ALL resolved stories and bugs for this release (with resolved date)
        # No date filter - we want ALL resolved items for the release
        # Items resolved before IRR will be counted as baseline on IRR day
        all_resolved = []

        # Build base JQL for transparency (displayed in info tooltip)
        component_filter = COMPONENT_JQL_MAP.get("YOUR_PRODUCT", 'component = "NS Client (NSC)"')
        base_jql = (
            f'(fixVersion = "{fix_version}") AND '
            f"(project = ENG AND {component_filter} AND "
            f'status in (resolved, closed, "Pending Close") AND '
            f"type not in (EPIC, Sub-task, task, Escalation))"
        )

        for component in TRACKED_COMPONENTS:
            component_filter = COMPONENT_JQL_MAP.get(component, f"project = {component}")

            # Query for ALL resolved items for this release
            # Only major release (X.0.0) and ENG project
            resolved_jql = f"""(fixVersion = "{fix_version}") AND
                (project = ENG AND {component_filter} AND
                status in (resolved, closed, "Pending Close") AND
                type not in (EPIC, Sub-task, task, Escalation))
                ORDER BY resolutiondate ASC"""

            resolved_result = await jira.search_issues(resolved_jql, max_results=1000, fetch_all=True)
            for issue in resolved_result:
                resolved_date = issue.get("resolutiondate") or issue.get("updated")
                issue_type = issue.get("issuetype", "Story")
                if resolved_date:
                    all_resolved.append(
                        {
                            "key": issue.get("key"),
                            "type": issue_type,
                            "component": component,
                            "resolved": resolved_date[:10] if resolved_date else None,
                        }
                    )

        # Build day-wise data from IRR to end_date
        day_data = {}
        current_date = irr_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            day_data[date_str] = {
                "date": date_str,
                "displayDate": current_date.strftime("%b %d"),
                "stories": 0,
                "bugs": 0,
                "total": 0,
                "YOUR_PRODUCT_stories": 0,
                "YOUR_PRODUCT_bugs": 0,
            }
            current_date += timedelta(days=1)

        # Count resolutions per day
        # Items resolved before IRR are counted on IRR date as baseline
        irr_date_str = irr_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        for item in all_resolved:
            resolved_date = item.get("resolved")
            if not resolved_date:
                continue

            item_type = item.get("type", "Story")
            component = item.get("component", "YOUR_PRODUCT")

            # Determine which day to count this item on
            if resolved_date < irr_date_str:
                # Resolved before IRR - count on IRR day as baseline
                count_date = irr_date_str
            elif resolved_date > end_date_str:
                # Resolved after end date - skip (shouldn't happen with current data)
                continue
            else:
                # Resolved within the range - count on actual date
                count_date = resolved_date

            if count_date in day_data:
                if item_type == "Story":
                    day_data[count_date]["stories"] += 1
                    day_data[count_date][f"{component}_stories"] = (
                        day_data[count_date].get(f"{component}_stories", 0) + 1
                    )
                else:
                    day_data[count_date]["bugs"] += 1
                    day_data[count_date][f"{component}_bugs"] = day_data[count_date].get(f"{component}_bugs", 0) + 1

                day_data[count_date]["total"] += 1

        # Convert to sorted list and calculate cumulative totals
        sorted_days = sorted(day_data.values(), key=lambda x: x["date"])

        cumulative_stories = 0
        cumulative_bugs = 0
        cumulative_by_component = {comp: {"stories": 0, "bugs": 0} for comp in TRACKED_COMPONENTS}

        chart_data = []
        for day in sorted_days:
            cumulative_stories += day["stories"]
            cumulative_bugs += day["bugs"]

            for comp in TRACKED_COMPONENTS:
                cumulative_by_component[comp]["stories"] += day.get(f"{comp}_stories", 0)
                cumulative_by_component[comp]["bugs"] += day.get(f"{comp}_bugs", 0)

            chart_data.append(
                {
                    "date": day["date"],
                    "displayDate": day["displayDate"],
                    "dailyStories": day["stories"],
                    "dailyBugs": day["bugs"],
                    "dailyTotal": day["total"],
                    "cumulativeStories": cumulative_stories,
                    "cumulativeBugs": cumulative_bugs,
                    "cumulativeTotal": cumulative_stories + cumulative_bugs,
                    # Per-component cumulative (YOUR_PRODUCT only)
                    "YOUR_PRODUCT": cumulative_by_component["YOUR_PRODUCT"]["stories"]
                    + cumulative_by_component["YOUR_PRODUCT"]["bugs"],
                }
            )

        # Count items resolved before IRR (baseline)
        pre_irr_count = sum(1 for item in all_resolved if item.get("resolved") and item.get("resolved") < irr_date_str)

        # Summary stats
        total_resolved = cumulative_stories + cumulative_bugs
        days_elapsed = (end_date - irr_date).days + 1
        days_remaining = max(0, (final_build_date - today).days)

        return {
            "release": release_id,
            "fixVersion": fix_version,
            "timeline": {
                "irr_date": irr_date.isoformat(),
                "final_build_date": final_build_date.isoformat(),
                "today": today.isoformat(),
                "days_elapsed": days_elapsed,
                "days_remaining": days_remaining,
            },
            "summary": {
                "totalResolved": total_resolved,
                "totalStories": cumulative_stories,
                "totalBugs": cumulative_bugs,
                "resolvedBeforeIRR": pre_irr_count,
                "resolvedAfterIRR": total_resolved - pre_irr_count,
                "avgPerDay": round((total_resolved - pre_irr_count) / max(days_elapsed, 1), 1),
                "byComponent": {
                    comp: cumulative_by_component[comp]["stories"] + cumulative_by_component[comp]["bugs"]
                    for comp in TRACKED_COMPONENTS
                },
            },
            "chartData": chart_data,
            # JQL query for transparency (displayed in info tooltip)
            "jql": base_jql,
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching resolution progress: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-readiness")
async def get_release_readiness(
    release: Optional[str] = Query(None),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get comprehensive Release Readiness Tracking data.

    PURPOSE:
        Primary endpoint for the Release Readiness page. Returns all open
        JIRA items (stories, bugs) for a release with phase awareness,
        assignee breakdown, QA backlog, and readiness assessment.

    WHEN TO USE:
        - Loading Release Readiness page
        - Getting detailed release status with all open items
        - Viewing items by assignee or QA owner
        - Tracking progress toward milestones (IRR, Branch Cut, Final Build)

    PARAMETERS:
        - release (str): Release ID like "R135" (default: current release)
        - refresh (bool): Force refresh cached data (default: False)

    RETURNS:
        {
            "release": "R135",
            "fixVersion": "135.0.0",
            "releaseLead": "John Doe",
            "currentPhase": {
                "phase": "branch_cut",
                "trackBugs": true,
                "message": "Focus on bug fixes only",
                "requirement": "All stories should be RESOLVED"
            },
            "timeline": {
                "irr_date": "2026-01-10",
                "branch_cut_date": "2026-01-17",
                "final_build_date": "2026-01-24"
            },
            "summary": {
                "total_bc_stories": 15,
                "total_bc_bugs": 8,
                "total_fb_issues": 23,
                "total_code_review": 5
            },
            "releaseSummary": {
                "phase": "Branch Cut",
                "daysRemaining": 7,
                "totalOpen": 23,
                "status": "On Track"
            },
            "storiesByAssignee": [
                {
                    "assignee": "john.doe",
                    "open": 5,
                    "bugs": 2,
                    "stories": 3,
                    "tickets": [...]
                }
            ],
            "resolvedByQA": [...],
            "componentsData": {
                "YOUR_PRODUCT": {
                    "summary": {...},
                    "issues": [...]
                }
            },
            "readinessAssessment": {
                "overall_status": "On Track",
                "recommendation": "Continue current pace"
            },
            "trendAnalysis": {...},
            "blockersAnalysis": {...}
        }

    RELEASE PHASES:
        - Pre-IRR: All work in progress
        - IRR to Branch Cut: Stories should be resolved
        - Branch Cut to Final Build: Bugs should be resolved
        - Post Final Build: All items should be closed

    RELATED ENDPOINTS:
        - GET /api/overview - High-level release summary
        - GET /api/jira/milestone/irr - IRR milestone details
        - GET /api/jira/milestone/branch-cut - Branch cut details
        - GET /api/jira/release-data - Raw release data
    """
    from services.release_data_service import get_release_data_service

    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    release_id = get_release_id_from_param(release)
    version_num, fix_version, next_fix_version = parse_version_from_release(release_id)

    # Get release dates
    release_dates = get_release_dates(release_id)
    today = datetime.now().date()

    if release_dates:
        irr_date = (parse_date_safe(release_dates.get("irr")) or datetime.now()).date()
        branch_cut_date = (parse_date_safe(release_dates.get("branch_cut")) or datetime.now()).date()
        final_build_date = (parse_date_safe(release_dates.get("final_build")) or datetime.now()).date()
        # Parse all deploy dates (Day 1-4)
        day1_deploy_date = parse_date_safe(release_dates.get("day1_deploy"))
        day1_deploy_date = day1_deploy_date.date() if day1_deploy_date else None
        day2_deploy_date = parse_date_safe(release_dates.get("day2_deploy"))
        day2_deploy_date = day2_deploy_date.date() if day2_deploy_date else None
        day3_deploy_date = parse_date_safe(release_dates.get("day3_deploy"))
        day3_deploy_date = day3_deploy_date.date() if day3_deploy_date else None
        day4_deploy_date = parse_date_safe(release_dates.get("day4_deploy"))
        day4_deploy_date = day4_deploy_date.date() if day4_deploy_date else None
    else:
        logger.warning("No release dates for %s. Add to config.py RELEASE_DATES.", release_id)
        branch_cut_date = today
        irr_date = today - timedelta(days=7)
        final_build_date = today + timedelta(days=14)
        day1_deploy_date = None
        day2_deploy_date = None
        day3_deploy_date = None
        day4_deploy_date = None

    # Check if release is completed (fully deployed)
    release_is_completed = is_release_completed(release_id)

    # Determine phase using utility function (includes all deploy phases)
    current_phase, deadline_name, deadline_date, track_bugs, phase_message, phase_requirement = determine_phase(
        today,
        irr_date,
        branch_cut_date,
        final_build_date,
        day1_deploy_date,
        day2_deploy_date,
        day3_deploy_date,
        day4_deploy_date,
    )

    # For completed releases, override phase info
    if release_is_completed:
        current_phase = "completed"
        deadline_name = "Deployed"
        phase_message = "This release has been fully deployed to production."
        phase_requirement = "Release complete - no action required"
        days_remaining = 0
    else:
        # Calculate days remaining until the current phase deadline
        days_remaining = (deadline_date - today).days

    try:
        # Use centralized ReleaseDataService with phase-aware JQL
        # Branch Cut phase: Stricter filtering (excludes Resolved bugs, 48h filter)
        # Final Build phase: Simpler filtering (includes all open items)
        release_service = get_release_data_service()

        # QA Backlog JQL - Resolved/Pending Close items for QA verification
        # Only major release (X.0.0) and ENG project
        qa_backlog_jql = (
            f'(fixVersion = "{fix_version}") AND '
            f'(project = ENG AND component = "NS Client (NSC)" AND type IN (Bug, Story, Task) AND '
            f'status IN (Resolved, "Pending Close"))'
        )
        qa_backlog_fields = [
            "summary",
            "status",
            "priority",
            "assignee",
            "reporter",
            "issuetype",
            "components",
            "fixVersions",
            "customfield_10200",
        ]

        # Developer Workload JQL - matches JIRA dashboard exactly
        # Includes ENG, OPS, CD projects, no 48h filter, no label exclusions
        developer_workload_jql = (
            f"(fixVersion IN ({fix_version})) AND "
            f'(project in (ENG, OPS, CD) AND component = "NS Client (NSC)" AND '
            f'status not in (resolved, closed, "Pending Close") AND '
            f"type not in (EPIC, Sub-task, task, Escalation))"
        )
        developer_workload_fields = [
            "summary",
            "status",
            "priority",
            "assignee",
            "reporter",
            "issuetype",
            "components",
            "fixVersions",
        ]

        # Assignee Summary JQL - broader query for Slack notifications
        # Matches user's JIRA filter: ENG/OPS/CD, includes Resolved, no label exclusions
        assignee_summary_jql = (
            f'(fixVersion = "{fix_version}") AND '
            f'(project in (ENG, OPS, CD) AND component = "NS Client (NSC)" AND '
            f'status not in (closed, "Pending Close") AND '
            f"type not in (EPIC, Sub-task, task, Escalation))"
        )

        # Run all JIRA queries in parallel for faster response
        # Pass current_phase to use phase-appropriate JQL for release data
        release_data, resolved_issues, developer_workload_issues, assignee_summary_issues = await asyncio.gather(
            release_service.get_release_data(release_id, force_refresh=refresh, phase=current_phase),
            jira.search_issues(qa_backlog_jql, max_results=500, fetch_all=True, fields=qa_backlog_fields),
            jira.search_issues(
                developer_workload_jql, max_results=500, fetch_all=True, fields=developer_workload_fields
            ),
            jira.search_issues(
                assignee_summary_jql, max_results=1000, fetch_all=True, fields=developer_workload_fields
            ),
        )

        # Get all items from centralized service
        all_items = release_data.get("items", [])
        summary = release_data.get("summary", {})

        # Build issues list with component info
        all_issues = [
            {
                "key": i.get("key"),
                "summary": i.get("summary"),
                "assignee": i.get("assignee"),
                "assignee_email": i.get("assignee_email", ""),
                "priority": i.get("priority"),
                "status": i.get("status"),
                "type": i.get("issuetype", "Story"),
                "url": i.get("url"),
                "component": "YOUR_PRODUCT",
                "reporter": i.get("reporter"),
            }
            for i in all_items
        ]

        # Calculate totals from centralized data
        total_stories = summary.get("stories", 0)
        total_bugs = summary.get("bugs", 0)
        total_code_review = summary.get("code_review", 0)
        total_open = summary.get("total", 0)

        # Get blocker count for RRS calculation
        blockers = release_service.get_blockers(release_data)
        blocker_count = len(blockers)

        # Calculate RRS score using shared utility function (consistent with Overview page)
        rrs_score = calculate_rrs_score(
            open_stories=total_stories,
            open_bugs=total_bugs,
            blocker_count=blocker_count,
            code_review_count=total_code_review,
        )

        logger.info(
            f"Release Readiness {release_id}: Open Items={total_open} (stories={total_stories}, bugs={total_bugs}), "
            f"blockers={blocker_count}, rrs_score={rrs_score}%"
        )

        # Build components_data for YOUR_PRODUCT
        components_data = {
            "YOUR_PRODUCT": {
                "summary": {
                    "bc_stories": total_stories,
                    "bc_bugs": total_bugs,
                    "fb_total": total_open,
                    "code_review": total_code_review,
                },
                "issues": all_issues,
            }
        }

        # Group Developer Workload issues by assignee (uses separate JQL matching JIRA dashboard)
        # JQL: (fixVersion IN (X.0.0)) AND (project in (ENG, OPS, CD) AND component = "NS Client (NSC)"
        #      AND status not in (resolved, closed, "Pending Close") AND type not in (EPIC, Sub-task, task, Escalation))
        issues_by_assignee = {}
        for issue in developer_workload_issues:
            assignee = issue.get("assignee", "Unassigned")
            issue_type = (issue.get("issuetype") or "Story").lower()
            status = issue.get("status", "")

            if assignee not in issues_by_assignee:
                issues_by_assignee[assignee] = {
                    "open": 0,
                    "code_review": 0,
                    "bugs": 0,
                    "stories": 0,
                    "tickets": [],
                }

            issues_by_assignee[assignee]["open"] += 1

            if "bug" in issue_type:
                issues_by_assignee[assignee]["bugs"] += 1
            else:
                issues_by_assignee[assignee]["stories"] += 1

            if status.lower() == "code review":
                issues_by_assignee[assignee]["code_review"] += 1

            issues_by_assignee[assignee]["tickets"].append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "status": status,
                    "priority": issue.get("priority"),
                    "type": issue.get("issuetype", "Story"),
                    "url": issue.get("url"),
                    "reporter": issue.get("reporter"),
                    "component": "YOUR_PRODUCT",
                }
            )

        sorted_assignees = sorted(issues_by_assignee.items(), key=lambda x: x[1]["open"], reverse=True)

        logger.info(
            f"Developer Workload {release_id}: {len(developer_workload_issues)} issues across {len(issues_by_assignee)} assignees"
        )

        logger.info(
            f"Release Readiness {release_id}: Open Items={total_open} (stories={total_stories}, bugs={total_bugs}), cached={release_data.get('metadata', {}).get('cached', False)}"
        )

        # Process QA Backlog results (fetched in parallel above)
        resolved_by_qa = {}

        for issue in resolved_issues:
            # Use QA field (customfield_10200) instead of assignee for QA Backlog grouping
            qa_name = issue.get("qa") or "Unassigned"
            status = issue.get("status", "Resolved")
            issue_type = issue.get("issuetype", "Story")
            is_bug = issue_type == "Bug"

            if qa_name not in resolved_by_qa:
                resolved_by_qa[qa_name] = {
                    "total": 0,
                    "resolved": 0,
                    "pending_close": 0,
                    "stories": 0,
                    "bugs": 0,
                    "tickets": [],
                    "qa_email": issue.get("qa_email", ""),
                }
            resolved_by_qa[qa_name]["total"] += 1

            # Track by type
            if is_bug:
                resolved_by_qa[qa_name]["bugs"] += 1
            else:
                resolved_by_qa[qa_name]["stories"] += 1

            if status.lower() == "pending close":
                resolved_by_qa[qa_name]["pending_close"] += 1
            else:
                resolved_by_qa[qa_name]["resolved"] += 1
            resolved_by_qa[qa_name]["tickets"].append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "type": issue.get("issuetype"),
                    "status": status,
                    "priority": issue.get("priority"),
                    "url": issue.get("url"),
                    "reporter": issue.get("reporter"),
                    "assignee": issue.get("assignee"),  # Keep assignee for reference
                    "qa": issue.get("qa"),
                    "component": "YOUR_PRODUCT",
                }
            )

        sorted_resolved_by_qa = sorted(resolved_by_qa.items(), key=lambda x: x[1]["resolved"], reverse=True)
        total_resolved_only = sum(d["resolved"] for d in resolved_by_qa.values())
        total_pending_close = sum(d["pending_close"] for d in resolved_by_qa.values())

        # Status using utility function
        phase_status, overall_status = get_phase_status(days_remaining, total_open, total_code_review)

        # Save snapshot
        try:
            save_daily_snapshot(
                release_id,
                total_stories,
                total_bugs,
                total_code_review,
                {
                    c: {"stories": d["summary"]["bc_stories"], "bugs": d["summary"]["bc_bugs"]}
                    for c, d in components_data.items()
                },
            )
        except Exception as e:
            logger.warning("Failed to save trend snapshot: %s", e)

        # Get JQL from release data metadata for transparency
        jql_query = release_data.get("metadata", {}).get("jql", "")

        return {
            "release": release_id,
            "fixVersion": fix_version,
            "releaseLead": get_release_lead(release_id),
            "dashboardName": "Release Readiness Tracking",
            "jiraDashboardUrl": "https://your-org.atlassian.net/jira/dashboards/20524",
            "components": ["YOUR_PRODUCT"],  # Centralized JQL only queries YOUR_PRODUCT component
            "dataSource": "jira-direct",
            "generatedAt": datetime.now().isoformat(),
            "metadata": {
                "jql": jql_query,
                "cached": release_data.get("metadata", {}).get("cached", False),
                "fetched_at": release_data.get("metadata", {}).get("fetched_at"),
            },
            "currentPhase": {
                "phase": current_phase,
                "trackBugs": track_bugs,
                "message": phase_message,
                "requirement": phase_requirement,
            },
            "timeline": {
                "irr_date": irr_date.isoformat(),
                "branch_cut_date": branch_cut_date.isoformat(),
                "final_build_date": final_build_date.isoformat(),
                "day1_deploy": day1_deploy_date.isoformat() if day1_deploy_date else None,
                "day2_deploy": day2_deploy_date.isoformat() if day2_deploy_date else None,
                "day3_deploy": day3_deploy_date.isoformat() if day3_deploy_date else None,
                "day4_deploy": day4_deploy_date.isoformat() if day4_deploy_date else None,
            },
            "summary": {
                "total_bc_stories": total_stories,
                "total_bc_bugs": total_bugs,
                "total_fb_issues": total_open,
                "total_code_review": total_code_review,
            },
            "releaseSummary": {
                "release": release_id,
                "phase": current_phase.replace("_", " ").title(),
                "phaseName": deadline_name,
                "daysRemaining": days_remaining,
                "requirement": phase_requirement,
                "totalOpen": total_open,
                "openStories": total_stories,
                "openBugs": total_bugs,
                "inCodeReview": total_code_review,
                "qaPending": total_resolved_only,
                "status": phase_status,
                "rrsScore": rrs_score,  # Release Readiness Score (consistent with Overview)
            },
            "phaseCountdown": {
                "current_phase": current_phase,
                "deadline_name": deadline_name,
                "deadline_date": deadline_date.isoformat(),
                "days_remaining": days_remaining,
                "status": phase_status,
                "message": phase_message,
                "open_stories": total_stories,
                "open_bugs": total_bugs,
            },
            "storiesByAssignee": [{"assignee": a, **d} for a, d in sorted_assignees],
            "resolvedByQA": [{"qa": qa, **data} for qa, data in sorted_resolved_by_qa],
            "totalResolvedOnly": total_resolved_only,
            "totalPendingClose": total_pending_close,
            "componentsData": components_data,
            "assigneeSummaryIssues": [
                {
                    "key": i.get("key"),
                    "summary": i.get("summary"),
                    "assignee": i.get("assignee"),
                    "assignee_email": i.get("assignee_email", ""),
                    "priority": i.get("priority"),
                    "status": i.get("status"),
                    "type": i.get("issuetype", "Story"),
                    "url": i.get("url"),
                    "reporter": i.get("reporter"),
                }
                for i in assignee_summary_issues
            ],
            "readinessAssessment": {
                "overall_status": overall_status,
                "recommendation": get_readiness_recommendation(
                    total_stories, total_bugs, total_open, total_code_review
                ),
            },
            "trendAnalysis": analyze_trends(release_id, irr_date=irr_date.strftime("%Y-%m-%d")),
            "blockersAnalysis": analyze_blockers(all_issues, issues_by_assignee, days_remaining),
        }
    except JiraAuthError as e:
        logger.error("JIRA authentication error: %s", e)
        raise HTTPException(
            status_code=401,
            detail={
                "error": "jira_auth_error",
                "message": str(e),
                "action": "Update JIRA_API_TOKEN in .env file and restart the backend",
            },
        ) from e
    except Exception as e:
        logger.error("Error fetching release readiness data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch release readiness data: {str(e)}") from e


# =============================================================================
# Centralized Release Data API Endpoints
# =============================================================================
# These endpoints expose the ReleaseDataService functions for frontend use.
# Single JQL query fetches all data, then filters are applied server-side.


@router.get("/release-data")
async def get_release_data(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get all open JIRA items for a release using centralized service.

    PURPOSE:
        Raw data endpoint that returns all open JIRA items for a release.
        Uses a single optimized JQL query with 2-minute caching. This is
        the base data source for release-readiness and related endpoints.

    WHEN TO USE:
        - Getting raw JIRA data for custom processing
        - Building custom views of release data
        - Debugging release data issues
        - Direct access to all open items

    PARAMETERS:
        - release (str): Release ID like "R135" (default: current release)
        - refresh (bool): Force refresh cached data (default: False)

    RETURNS:
        {
            "items": [
                {
                    "key": "YOUR_PRODUCT-12345",
                    "summary": "Fix login bug",
                    "status": "In Progress",
                    "issuetype": "Bug",
                    "priority": "High",
                    "assignee": "john.doe",
                    "url": "https://..."
                }
            ],
            "summary": {
                "total": 23,
                "stories": 15,
                "bugs": 8,
                "code_review": 5,
                "by_priority": {
                    "High": 5,
                    "Medium": 10,
                    "Low": 8
                }
            },
            "metadata": {
                "jql": "...",
                "fetched_at": "2026-02-03T10:00:00",
                "cached": true,
                "cache_age_seconds": 45
            }
        }

    CACHING:
        - Data cached for 2 minutes
        - Use refresh=true to force cache refresh

    RELATED ENDPOINTS:
        - GET /api/jira/release-data/summary - Counts only (lighter)
        - GET /api/jira/release-data/by-assignee - Grouped by assignee
        - GET /api/jira/release-data/blockers - Critical items only
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        return data
    except Exception as e:
        logger.error("Error fetching release data: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/summary")
async def get_release_summary(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get release summary (counts only, no item details).

    Lighter endpoint for Overview tiles that only need counts.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        metrics = service.calculate_readiness_metrics(data)

        return {
            "release_id": release_id,
            "summary": data.get("summary", {}),
            "metrics": metrics,
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
                "fetched_at": data.get("metadata", {}).get("fetched_at"),
            },
        }
    except Exception as e:
        logger.error("Error fetching release summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/by-assignee")
async def get_release_data_by_assignee(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get release data grouped by assignee.

    Uses centralized data, applies group_by_assignee filter.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        by_assignee = service.group_by_assignee(data)

        # Sort by total items descending
        sorted_assignees = sorted(by_assignee.items(), key=lambda x: x[1]["total"], reverse=True)

        return {
            "release_id": release_id,
            "total_assignees": len(sorted_assignees),
            "assignees": [{"assignee": assignee, **details} for assignee, details in sorted_assignees],
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
            },
        }
    except Exception as e:
        logger.error("Error fetching release data by assignee: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/blockers")
async def get_release_blockers(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get blocker and critical priority items for a release.

    PURPOSE:
        Returns only the highest priority items (Blocker, Critical, Highest)
        that need immediate attention. These items can block the release.

    WHEN TO USE:
        - Getting list of blockers for urgent review
        - Displaying critical items on Overview page
        - Calculating blocker count for RRS score
        - Prioritizing work on release blockers

    PARAMETERS:
        - release (str): Release ID like "R135" (default: current release)
        - refresh (bool): Force refresh cached data (default: False)

    RETURNS:
        {
            "release_id": "R135",
            "count": 3,
            "blockers": [
                {
                    "key": "YOUR_PRODUCT-12345",
                    "summary": "Critical login failure",
                    "priority": "Blocker",
                    "status": "In Progress",
                    "assignee": "john.doe",
                    "type": "Bug",
                    "url": "https://..."
                }
            ]
        }

    PRIORITY LEVELS INCLUDED:
        - Blocker
        - Critical
        - Highest

    RELATED ENDPOINTS:
        - GET /api/jira/release-data - All open items
        - GET /api/jira/release-readiness - Full release tracking
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        blockers = service.get_blockers(data)

        return {
            "release_id": release_id,
            "count": len(blockers),
            "blockers": [
                {
                    "key": item.get("key"),
                    "summary": item.get("summary"),
                    "priority": item.get("priority"),
                    "status": item.get("status"),
                    "assignee": item.get("assignee"),
                    "type": item.get("issuetype"),
                    "url": item.get("url"),
                }
                for item in blockers
            ],
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
            },
        }
    except Exception as e:
        logger.error("Error fetching blockers: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/code-review")
async def get_release_code_review(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get items in Code Review status for a release.

    Uses centralized data, applies status filter for Code Review.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        code_review_items = service.get_code_review_items(data)

        return {
            "release_id": release_id,
            "count": len(code_review_items),
            "items": [
                {
                    "key": item.get("key"),
                    "summary": item.get("summary"),
                    "priority": item.get("priority"),
                    "assignee": item.get("assignee"),
                    "type": item.get("issuetype"),
                    "url": item.get("url"),
                }
                for item in code_review_items
            ],
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
            },
        }
    except Exception as e:
        logger.error("Error fetching code review items: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/by-status")
async def get_release_data_by_status(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get release data grouped by status.

    Uses centralized data, applies group_by_status filter.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        by_status = service.group_by_status(data)

        # Build response with counts and items per status
        status_data = []
        for status, items in sorted(by_status.items(), key=lambda x: len(x[1]), reverse=True):
            status_data.append(
                {
                    "status": status,
                    "count": len(items),
                    "items": [
                        {
                            "key": item.get("key"),
                            "summary": item.get("summary"),
                            "priority": item.get("priority"),
                            "assignee": item.get("assignee"),
                            "type": item.get("issuetype"),
                        }
                        for item in items[:10]  # Limit to 10 items per status
                    ],
                }
            )

        return {
            "release_id": release_id,
            "total_statuses": len(status_data),
            "statuses": status_data,
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
            },
        }
    except Exception as e:
        logger.error("Error fetching release data by status: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/by-priority")
async def get_release_data_by_priority(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get release data grouped by priority.

    Uses centralized data, applies group_by_priority filter.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        by_priority = service.group_by_priority(data)

        # Priority order for sorting
        priority_order = ["Highest", "Blocker", "Critical", "High", "Medium", "Low", "Lowest"]

        # Build response with counts per priority
        priority_data = []
        for priority in priority_order:
            items = by_priority.get(priority, [])
            if items:
                priority_data.append(
                    {
                        "priority": priority,
                        "count": len(items),
                        "items": [
                            {
                                "key": item.get("key"),
                                "summary": item.get("summary"),
                                "status": item.get("status"),
                                "assignee": item.get("assignee"),
                                "type": item.get("issuetype"),
                            }
                            for item in items[:5]  # Limit to 5 items per priority
                        ],
                    }
                )

        # Add any priorities not in the order list
        for priority, items in by_priority.items():
            if priority not in priority_order and items:
                priority_data.append(
                    {
                        "priority": priority,
                        "count": len(items),
                        "items": [
                            {
                                "key": item.get("key"),
                                "summary": item.get("summary"),
                                "status": item.get("status"),
                                "assignee": item.get("assignee"),
                            }
                            for item in items[:5]
                        ],
                    }
                )

        return {
            "release_id": release_id,
            "priorities": priority_data,
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
            },
        }
    except Exception as e:
        logger.error("Error fetching release data by priority: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/release-data/metrics")
async def get_release_metrics(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get release readiness metrics.

    Calculates health score, status, and recommendations based on centralized data.
    Ideal for Overview tiles that need quick status indicators.
    """
    from services.release_data_service import get_release_data_service

    release_id = get_release_id_from_param(release)
    service = get_release_data_service()

    try:
        data = await service.get_release_data(release_id, force_refresh=refresh)
        metrics = service.calculate_readiness_metrics(data)

        return {
            "release_id": release_id,
            **metrics,
            "metadata": {
                "cached": data.get("metadata", {}).get("cached", False),
                "fetched_at": data.get("metadata", {}).get("fetched_at"),
            },
        }
    except Exception as e:
        logger.error("Error fetching release metrics: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# Items Moved Out of Release Endpoint
# =============================================================================


@router.get("/items-moved-out")
async def get_items_moved_out(
    release: Optional[str] = Query(None, description="Release ID (e.g., R135)"),
    refresh: bool = Query(default=False, description="Force refresh cached data"),
):
    """
    Get items (bugs/stories) that were moved out of a release after the IRR date.

    PURPOSE:
        Tracks issues that had their fixVersion changed FROM the specified release
        to another release after the IRR date. Helps identify scope changes and
        items that were deferred to future releases.

    WHEN TO USE:
        - Viewing Release Readiness page
        - Tracking scope changes during a release cycle
        - Identifying deferred items for retrospectives

    PARAMETERS:
        - release (str): Release ID (e.g., "R135")
        - refresh (bool): Force refresh cached data

    RETURNS:
        {
            "release_id": "R135",
            "fix_version": "135.0.0",
            "irr_date": "2026-01-08",
            "total_moved_out": 12,
            "bugs_count": 8,
            "stories_count": 4,
            "by_priority": {
                "Highest": 1,
                "High": 3,
                "Medium": 5,
                "Low": 2,
                "Lowest": 1
            },
            "items": [...],
            "jira_url": "https://..."
        }
    """
    release_id = get_release_id_from_param(release)

    # Get release dates from config
    release_dates = get_release_dates(release_id)
    irr_date = release_dates.get("irr", "")

    if not irr_date:
        raise HTTPException(
            status_code=400,
            detail=f"IRR date not found for release {release_id}. Check release calendar.",
        )

    # Convert release ID (R135) to fix version format (135.0.0)
    release_num = release_id.replace("R", "")
    fix_version = f"{release_num}.0.0"

    # Build JQL query for items moved out of this release
    # This query finds issues where:
    # - Type is Bug or Story
    # - fixVersion WAS the release version
    # - fixVersion is now different (not the original version)
    # - fixVersion is not empty (moved to another release, not just removed)
    # - Updated after IRR date
    # - In the tracked projects and component
    jql = (
        f"(type = Bug OR type = Story) AND "
        f'fixVersion WAS "{fix_version}" AND '
        f'fixVersion != "{fix_version}" AND '
        f"fixVersion IS NOT EMPTY AND "
        f'updated >= "{irr_date}" AND '
        f"project = ENG AND "
        f'component = "NS Client (NSC)" '
        f"ORDER BY priority DESC, updated DESC"
    )

    logger.info(f"Fetching items moved out for {release_id} with JQL: {jql[:100]}...")

    try:
        jira = get_jira_client()

        if refresh:
            jira.clear_cache()

        issues = await jira.search_issues(jql, max_results=500, fetch_all=True)

        # Count by type
        bugs = [i for i in issues if i.get("issuetype") == "Bug"]
        stories = [i for i in issues if i.get("issuetype") == "Story"]

        # Count by priority
        priority_counts = {}
        for issue in issues:
            priority = issue.get("priority", "Unknown")
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        # Order priorities
        priority_order = ["Highest", "Blocker", "Critical", "High", "Medium", "Low", "Lowest"]
        ordered_priorities = {}
        for p in priority_order:
            if p in priority_counts:
                ordered_priorities[p] = priority_counts[p]
        # Add any priorities not in the standard order
        for p, count in priority_counts.items():
            if p not in ordered_priorities:
                ordered_priorities[p] = count

        # Build JIRA URL for the query
        jira_base_url = os.getenv("JIRA_URL", "https://your-org.atlassian.net")
        import urllib.parse

        jira_url = f"{jira_base_url}/issues/?jql={urllib.parse.quote(jql)}"

        # Format items for response (limit details to first 20)
        items_list = []
        for issue in issues[:20]:
            items_list.append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "type": issue.get("issuetype"),
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "assignee": issue.get("assignee"),
                    "current_fix_version": issue.get("fixVersions", [None])[0] if issue.get("fixVersions") else None,
                }
            )

        return {
            "release_id": release_id,
            "fix_version": fix_version,
            "irr_date": irr_date,
            "total_moved_out": len(issues),
            "bugs_count": len(bugs),
            "stories_count": len(stories),
            "by_priority": ordered_priorities,
            "items": items_list,
            "jira_url": jira_url,
        }

    except JiraAuthError as e:
        logger.error("JIRA auth error: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching items moved out: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# NPLANs Tracking Endpoint (Google Sheets)
# =============================================================================


@router.get("/nplans")
async def get_nplans(
    release: str = Query(..., description="Release version (e.g., 135, R135)"),
):
    """
    Get NPLANs/Features planned for a specific release.

    Fetches data from the WEEKLY STATUS REPORT Google Sheet,
    specifically from the RELEASES/QUALITY/REGRESSIONS/CUSTOMER ISSUES table.

    Args:
        release: Release version (e.g., "135", "R135", "135.0.0")

    Returns:
        {
            "release": "135",
            "total": 12,
            "items": [
                {
                    "id": "NPLAN-5417",
                    "description": "NPA | Client to LBR selection Improvements",
                    "status": "SHIPPED",
                    "notes": "ADDED(11/Dec)",
                    "jira_url": "https://your-org.atlassian.net/browse/NPLAN-5417"
                },
                ...
            ],
            "by_status": {"SHIPPED": 5, "ONTRACK": 4, "TBD": 3},
            "spreadsheet_url": "..."
        }
    """
    try:
        from services.gsheets_client import get_nplans_for_release

        result = await get_nplans_for_release(release)

        if "error" in result and result.get("total", 0) == 0:
            # Return empty result with error info but don't fail
            logger.warning("NPLANs fetch warning: %s", result.get("error"))

        return result

    except Exception as e:
        logger.error("Error fetching NPLANs: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch NPLANs: {str(e)}") from e


# =============================================================================
# NPLAN Bugs Tracking Endpoint
# =============================================================================


@router.get("/nplan-bugs")
async def get_nplan_bugs(
    release: str = Query(..., description="Release version (e.g., 135, R135)"),
    include_closed: bool = Query(True, description="Include closed bugs"),
):
    """
    Get bugs linked to NPLANs for a specific release.

    Fetches NPLANs from Google Sheets, then queries JIRA for bugs
    with labels matching NPLAN IDs (e.g., nplan-5417) AND fixVersion matching
    the selected release (e.g., 137.0.0).

    Sample JQL: (labels = nplan-6021) AND project = ENG AND fixVersion = "137.0.0"

    Args:
        release: Release version (e.g., "135", "R135")
        include_closed: Whether to include closed bugs (default: True)

    Returns:
        {
            "release": "135",
            "nplan_bugs": {
                "NPLAN-5417": {
                    "nplan_id": "NPLAN-5417",
                    "bugs": [
                        {
                            "key": "ENG-12345",
                            "summary": "Bug description",
                            "status": "In Progress",
                            "priority": "High",
                            "assignee": "John Doe",
                            "url": "https://..."
                        }
                    ],
                    "total": 3,
                    "open": 2,
                    "by_priority": {"Critical": 1, "High": 2},
                    "by_status": {"In Progress": 2, "Resolved": 1}
                }
            },
            "summary": {
                "total_nplans": 12,
                "nplans_with_bugs": 5,
                "total_bugs": 15,
                "open_bugs": 10,
                "by_priority": {"Critical": 3, "High": 5, "Medium": 7},
                "by_status": {"Open": 4, "In Progress": 6, "Resolved": 5}
            }
        }
    """
    try:
        from services.gsheets_client import get_nplans_for_release

        # Step 1: Get NPLANs for this release from Google Sheets
        nplans_result = await get_nplans_for_release(release)

        if "error" in nplans_result and nplans_result.get("total", 0) == 0:
            logger.warning("No NPLANs found for release %s: %s", release, nplans_result.get("error"))
            return {
                "release": release,
                "nplan_bugs": {},
                "summary": {
                    "total_nplans": 0,
                    "nplans_with_bugs": 0,
                    "total_bugs": 0,
                    "open_bugs": 0,
                    "by_priority": {},
                    "by_status": {},
                },
                "error": nplans_result.get("error"),
            }

        # Step 2: Extract NPLAN IDs from the items
        nplan_ids = []
        for item in nplans_result.get("items", []):
            nplan_id = item.get("id")
            if nplan_id and nplan_id.startswith("NPLAN-"):
                nplan_ids.append(nplan_id)

        if not nplan_ids:
            logger.info("No valid NPLAN IDs found for release %s", release)
            return {
                "release": release,
                "nplan_bugs": {},
                "summary": {
                    "total_nplans": nplans_result.get("total", 0),
                    "nplans_with_bugs": 0,
                    "total_bugs": 0,
                    "open_bugs": 0,
                    "by_priority": {},
                    "by_status": {},
                },
            }

        # Step 3: Build fixVersion from release (e.g., "137" or "R137" -> "137.0.0")
        release_num = release.upper().replace("R", "").strip()
        fix_version = f"{release_num}.0.0"

        # Step 4: Query JIRA for bugs with these NPLAN labels AND matching fixVersion
        jira = get_jira_client()
        bugs_result = await jira.search_bugs_by_nplan_labels(
            nplan_ids, include_closed=include_closed, fix_version=fix_version
        )

        # Add release info to response
        bugs_result["release"] = nplans_result.get("release", release)
        bugs_result["fix_version"] = fix_version

        return bugs_result

    except JiraAuthError as e:
        logger.error("JIRA auth error fetching NPLAN bugs: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching NPLAN bugs: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch NPLAN bugs: {str(e)}") from e


# =============================================================================
# NPLAN Work Items Tracking Endpoint (for Dev Insights)
# =============================================================================


@router.get("/nplan-workitems")
async def get_nplan_workitems(
    release: str = Query(..., description="Release version (e.g., 136, R136)"),
    include_closed: bool = Query(True, description="Include closed items"),
):
    """
    Get all work items (Stories, Bugs, Tasks, Epics) under NPLANs for a release.

    Fetches NPLANs from Google Sheets, then queries JIRA for child work items
    using: parent = NPLAN-XXXX OR issueKey IN portfolioChildIssuesOf("NPLAN-XXXX")

    Args:
        release: Release version (e.g., "136", "R136")
        include_closed: Whether to include closed items (default: True)

    Returns:
        {
            "release": "136",
            "nplan_workitems": {
                "NPLAN-6364": {
                    "nplan_id": "NPLAN-6364",
                    "items": [
                        {
                            "key": "ENG-45123",
                            "summary": "Implement OAuth flow",
                            "status": "In Progress",
                            "priority": "High",
                            "assignee": "John Doe",
                            "issuetype": "Story",
                            "url": "https://..."
                        }
                    ],
                    "total": 23,
                    "open": 8,
                    "closed": 15,
                    "completion_pct": 65.2,
                    "by_type": {"Story": 15, "Bug": 5, "Task": 3},
                    "by_status": {"Closed": 15, "In Progress": 5, "Open": 3},
                    "by_assignee": {"John Doe": 5, "Jane Smith": 3}
                }
            },
            "nplans_metadata": {
                "NPLAN-6364": {
                    "id": "NPLAN-6364",
                    "description": "System Browser-Based Authentication",
                    "status": "ONTRACK"
                }
            },
            "summary": {
                "total_nplans": 14,
                "nplans_with_items": 12,
                "total_items": 142,
                "open_items": 55,
                "closed_items": 87,
                "completion_pct": 61.3,
                "by_type": {"Story": 80, "Bug": 40, "Task": 22},
                "by_status": {"Closed": 87, "In Progress": 30, "Open": 25}
            }
        }
    """
    try:
        from services.gsheets_client import get_nplans_for_release

        # Step 1: Get NPLANs for this release from Google Sheets
        nplans_result = await get_nplans_for_release(release)

        if "error" in nplans_result and nplans_result.get("total", 0) == 0:
            logger.warning("No NPLANs found for release %s: %s", release, nplans_result.get("error"))
            return {
                "release": release,
                "nplan_workitems": {},
                "nplans_metadata": {},
                "summary": {
                    "total_nplans": 0,
                    "nplans_with_items": 0,
                    "total_items": 0,
                    "open_items": 0,
                    "closed_items": 0,
                    "completion_pct": 0,
                    "by_type": {},
                    "by_status": {},
                },
                "error": nplans_result.get("error"),
            }

        # Step 2: Extract NPLAN IDs and metadata from the items
        nplan_ids = []
        nplans_metadata = {}
        for item in nplans_result.get("items", []):
            nplan_id = item.get("id")
            if nplan_id and nplan_id.startswith("NPLAN-"):
                nplan_ids.append(nplan_id)
                nplans_metadata[nplan_id] = {
                    "id": nplan_id,
                    "description": item.get("description", ""),
                    "status": item.get("status", "TBD"),
                    "notes": item.get("notes", ""),
                    "jira_url": item.get("jira_url", f"https://your-org.atlassian.net/browse/{nplan_id}"),
                }

        if not nplan_ids:
            logger.info("No valid NPLAN IDs found for release %s", release)
            return {
                "release": release,
                "nplan_workitems": {},
                "nplans_metadata": {},
                "summary": {
                    "total_nplans": nplans_result.get("total", 0),
                    "nplans_with_items": 0,
                    "total_items": 0,
                    "open_items": 0,
                    "closed_items": 0,
                    "completion_pct": 0,
                    "by_type": {},
                    "by_status": {},
                },
            }

        # Step 3: Query JIRA for work items under these NPLANs
        jira = get_jira_client()
        workitems_result = await jira.search_nplan_workitems(nplan_ids, include_closed=include_closed)

        # Add release info and metadata to response
        workitems_result["release"] = nplans_result.get("release", release)
        workitems_result["nplans_metadata"] = nplans_metadata

        return workitems_result

    except JiraAuthError as e:
        logger.error("JIRA auth error fetching NPLAN work items: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching NPLAN work items: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch NPLAN work items: {str(e)}") from e


# =============================================================================
# NPLAN Dev Status (Merge Status) Endpoint
# =============================================================================


@router.get("/nplan-dev-status")
async def get_nplan_dev_status(
    release: str = Query(..., description="Release version (e.g., 137, R137)"),
):
    """
    Get PR/merge status for all ENG tickets under each NPLAN in a release.

    Collects ENG tickets from TWO sources per NPLAN:
      1. Child workitems (parent = NPLAN-XXXX or portfolioChildIssuesOf)
      2. Label-linked bugs (labels = nplan-xxxx)
    De-duplicates by key, then batch-fetches development status (PRs + commits)
    for every unique ENG ticket.

    Merge status logic per ticket:
      - PRs exist → MERGED (all merged) / PARTIAL (some merged) / OPEN / DECLINED
      - No PRs, commits exist → check if merged to develop/main/nplan branch → MERGED or COMMITTED
      - No PRs, no commits → NONE

    NPLAN-level summary uses total_items as denominator (not just items with dev activity).
    """
    try:
        from services.gsheets_client import get_nplans_for_release

        # Step 1: Get NPLANs for this release
        nplans_result = await get_nplans_for_release(release)

        if "error" in nplans_result and nplans_result.get("total", 0) == 0:
            return {"release": release, "nplan_dev_status": {}}

        nplan_ids = [
            item.get("id") for item in nplans_result.get("items", []) if item.get("id", "").startswith("NPLAN-")
        ]

        if not nplan_ids:
            return {"release": release, "nplan_dev_status": {}}

        jira = get_jira_client()

        # Build fixVersion from release (e.g., "137" or "R137" -> "137.0.0")
        release_num = release.upper().replace("R", "").strip()
        fix_version = f"{release_num}.0.0"

        # Step 2: Fetch BOTH workitems and label-linked bugs concurrently
        # Label-linked bugs are filtered by fixVersion to only include bugs targeted for this release
        workitems_result, bugs_result = await asyncio.gather(
            jira.search_nplan_workitems(nplan_ids, include_closed=True),
            jira.search_bugs_by_nplan_labels(nplan_ids, include_closed=True, fix_version=fix_version),
        )

        # Step 3: For each NPLAN, merge both sources into a single de-duped list of ENG keys
        nplan_all_keys = {}  # nplan_id -> {key: {key, summary, status, source}}
        for nplan_id in nplan_ids:
            keys_map = {}

            # Source 1: Child workitems
            nplan_workitems = workitems_result.get("nplan_workitems", {}).get(nplan_id, {})
            for item in nplan_workitems.get("items", []):
                key = item.get("key", "")
                if key:
                    keys_map[key] = {
                        "key": key,
                        "summary": item.get("summary", ""),
                        "status": item.get("status", ""),
                    }

            # Source 2: Label-linked bugs
            nplan_bugs = bugs_result.get("nplan_bugs", {}).get(nplan_id, {})
            for bug in nplan_bugs.get("bugs", []):
                key = bug.get("key", "")
                if key and key not in keys_map:
                    keys_map[key] = {
                        "key": key,
                        "summary": bug.get("summary", ""),
                        "status": bug.get("status", ""),
                    }

            nplan_all_keys[nplan_id] = keys_map

        # Step 4: Collect ALL unique ENG keys across all NPLANs for a single batch fetch
        all_unique_keys = set()
        for keys_map in nplan_all_keys.values():
            all_unique_keys.update(keys_map.keys())

        if not all_unique_keys:
            nplan_dev_status = {}
            for nplan_id in nplan_ids:
                nplan_dev_status[nplan_id] = {
                    "total_items": 0,
                    "merged": 0,
                    "open": 0,
                    "none": 0,
                    "merge_status": "NONE",
                    "items": [],
                    "items_by_key": {},
                }
            return {"release": nplans_result.get("release", release), "nplan_dev_status": nplan_dev_status}

        # Step 5: Fetch dev status for all unique keys.
        # The jira client's semaphore (limit 10) naturally throttles concurrency.
        # The _dev_status_request helper retries on 429 with exponential backoff.
        # Launching all at once lets the semaphore pipeline requests efficiently
        # instead of waiting for each chunk to fully complete before starting the next.

        async def fetch_dev_status_for_key(key):
            try:
                dev_info = await asyncio.wait_for(
                    jira.get_issue_dev_status(key),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning("Dev status timeout for %s", key)
                dev_info = {"pull_requests": [], "commits": []}
            except Exception as exc:
                logger.warning("Dev status error for %s: %s", key, exc)
                dev_info = {"pull_requests": [], "commits": []}

            prs = dev_info.get("pull_requests", [])
            commits = dev_info.get("commits", [])
            pr_merged = sum(1 for pr in prs if pr.get("status", "").upper() == "MERGED")
            pr_open = sum(1 for pr in prs if pr.get("status", "").upper() in ("OPEN", "DRAFT"))

            return key, {
                "pr_count": len(prs),
                "pr_merged": pr_merged,
                "pr_open": pr_open,
                "commit_count": len(commits),
                "commits": commits,
                "prs": [
                    {
                        "name": pr.get("name", ""),
                        "url": pr.get("url", ""),
                        "status": pr.get("status", ""),
                    }
                    for pr in prs
                ],
            }

        keys_list = list(all_unique_keys)
        logger.info("Fetching dev status for %d unique ENG keys", len(keys_list))

        all_results = await asyncio.gather(*[fetch_dev_status_for_key(k) for k in keys_list])
        global_dev_lookup = {key: dev_info for key, dev_info in all_results}

        logger.info(
            "Dev status fetched: %d keys, %d with PRs, %d with commits",
            len(global_dev_lookup),
            sum(1 for v in global_dev_lookup.values() if v["pr_count"] > 0),
            sum(1 for v in global_dev_lookup.values() if v["commit_count"] > 0),
        )

        # Step 6: Build per-NPLAN results using the global lookup
        def compute_item_merge_status(dev_info, nplan_id):
            """Determine merge status for a single ENG ticket."""
            commits = dev_info.get("commits", [])
            pr_count = dev_info.get("pr_count", 0)
            pr_merged = dev_info.get("pr_merged", 0)
            pr_open = dev_info.get("pr_open", 0)

            if pr_count > 0:
                if pr_merged == pr_count:
                    return "MERGED"
                elif pr_merged > 0:
                    return "PARTIAL"
                elif pr_open > 0:
                    return "OPEN"
                else:
                    return "DECLINED"
            elif dev_info.get("commit_count", 0) > 0:
                # Check if any commit is merged to a target branch
                merge_branches = set()
                for c in commits:
                    for b in c.get("merge_branches", []):
                        merge_branches.add(b.lower())
                # Target: develop, main, master, or the nplan-specific branch
                target_branches = {"develop", "main", "master"}
                nplan_num = nplan_id.split("-")[-1] if "-" in nplan_id else ""
                # Common NPLAN branch naming patterns
                for variant in [
                    nplan_id.lower().replace("-", "/"),
                    nplan_id.lower(),
                    f"nplan/{nplan_num}",
                    f"feature/{nplan_id.lower()}",
                ]:
                    target_branches.add(variant)
                if merge_branches & target_branches:
                    return "MERGED"
                else:
                    return "COMMITTED"
            else:
                return "NONE"

        nplan_dev_status = {}
        for nplan_id in nplan_ids:
            keys_map = nplan_all_keys.get(nplan_id, {})

            if not keys_map:
                nplan_dev_status[nplan_id] = {
                    "total_items": 0,
                    "merged": 0,
                    "open": 0,
                    "none": 0,
                    "merge_status": "NONE",
                    "items": [],
                    "items_by_key": {},
                }
                continue

            items = []
            items_by_key = {}
            for key, meta in keys_map.items():
                dev_info = global_dev_lookup.get(
                    key, {"pr_count": 0, "pr_merged": 0, "pr_open": 0, "commit_count": 0, "commits": [], "prs": []}
                )
                item_status = compute_item_merge_status(dev_info, nplan_id)
                item_result = {
                    "key": key,
                    "summary": meta.get("summary", ""),
                    "status": meta.get("status", ""),
                    "pr_count": dev_info.get("pr_count", 0),
                    "pr_merged": dev_info.get("pr_merged", 0),
                    "pr_open": dev_info.get("pr_open", 0),
                    "commit_count": dev_info.get("commit_count", 0),
                    "merge_status": item_status,
                    "prs": dev_info.get("prs", []),
                }
                items.append(item_result)
                items_by_key[key] = item_result

            total_items = len(items)
            merged_count = sum(1 for r in items if r["merge_status"] == "MERGED")
            open_count = sum(1 for r in items if r["merge_status"] in ("OPEN", "PARTIAL"))
            none_count = sum(1 for r in items if r["merge_status"] == "NONE")

            # Overall NPLAN merge status — denominator is total_items, not just items with dev
            if total_items == 0:
                overall_status = "NONE"
            elif merged_count == total_items:
                overall_status = "MERGED"
            elif merged_count > 0:
                overall_status = "PARTIAL"
            elif open_count > 0:
                overall_status = "OPEN"
            else:
                overall_status = "NONE"

            nplan_dev_status[nplan_id] = {
                "total_items": total_items,
                "merged": merged_count,
                "open": open_count,
                "none": none_count,
                "merge_status": overall_status,
                "items": items,
                "items_by_key": items_by_key,
            }

        return {"release": nplans_result.get("release", release), "nplan_dev_status": nplan_dev_status}

    except JiraAuthError as e:
        logger.error("JIRA auth error fetching NPLAN dev status: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching NPLAN dev status: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch NPLAN dev status: {str(e)}") from e


# =============================================================================
# Customer Escalations Endpoint
# =============================================================================


@router.get("/escalations")
async def get_escalations(
    release: str = Query(None, description="Release version filter (e.g., R134)"),
):
    """
    Get customer escalations for NS Client component filtered by release.

    Fetches unresolved customer escalation issues from ENG project
    that are targeted for the specified release.

    JQL: component = "NS Client (NSC)" AND resolution = Unresolved AND
         project = ENG AND issuetype in (Escalation) AND
         "Type of Escalation[Dropdown]" in (Customer) AND
         fixVersion = "{release}.0.0"

    Returns:
        {
            "issues": [
                {
                    "key": "ENG-12345",
                    "summary": "Critical auth failure",
                    "priority": "P1",
                    "assignee": "John Doe",
                    "status": "In Progress",
                    "age": "3 days",
                    "url": "https://..."
                }
            ],
            "total": 5,
            "jira_url": "https://..."
        }
    """
    try:
        jira = get_jira_client()

        # JQL for customer escalations - NS Client component with Customer escalation type
        jql_parts = [
            'component = "NS Client (NSC)"',
            "resolution = Unresolved",
            "project = ENG",
            "issuetype in (Escalation)",
            '"Type of Escalation[Dropdown]" in (Customer)',
        ]

        # Add release filter if provided
        # Convert release format: "R135" -> "135.0.0"
        if release:
            # Extract the numeric part from release (e.g., "R135" -> "135")
            release_number = release.replace("R", "").replace("r", "").strip()
            # Construct fixVersion format (e.g., "135" -> "135.0.0")
            fix_version = f"{release_number}.0.0"
            jql_parts.append(f'fixVersion = "{fix_version}"')

        jql = " AND ".join(jql_parts)
        jql += " ORDER BY priority DESC, created DESC"

        logger.info("Fetching customer escalations with JQL: %s", jql)

        issues = await jira.search_issues(
            jql,
            max_results=50,
            fields=["key", "summary", "priority", "assignee", "status", "created", "labels", "fixVersions"],
        )

        result_issues = []
        jira_base_url = os.getenv("JIRA_URL", "https://your-org.atlassian.net")

        for issue in issues:
            created = issue.get("created")
            age = ""
            if created:
                try:
                    created_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_old = (datetime.now(created_date.tzinfo) - created_date).days
                    age = f"{days_old} day{'s' if days_old != 1 else ''}"
                except Exception:
                    age = "Unknown"

            # Get fix version(s)
            fix_versions = issue.get("fixVersions", [])
            fix_version = fix_versions[0] if fix_versions else None

            result_issues.append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "priority": issue.get("priority"),
                    "assignee": issue.get("assignee") or "Unassigned",
                    "status": issue.get("status"),
                    "age": age,
                    "fixVersion": fix_version,
                    "url": f"{jira_base_url}/browse/{issue.get('key')}",
                }
            )

        # Build JIRA URL for "Open all in JIRA" link
        from urllib.parse import quote

        jira_search_url = f"{jira_base_url}/issues/?jql={quote(jql)}"

        return {
            "issues": result_issues,
            "total": len(result_issues),
            "jira_url": jira_search_url,
            "jql": jql,  # Include JQL for debugging
        }

    except JiraAuthError as e:
        logger.error("JIRA auth error: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching escalations: %s", e)
        # Return empty list instead of error for graceful degradation
        return {"issues": [], "total": 0, "error": str(e)}


# =============================================================================
# Security Issues Endpoint
# =============================================================================


@router.get("/security-issues")
async def get_security_issues(
    release: str = Query(None, description="Release version filter (e.g., R134)"),
):
    """
    Get security-related issues for NS Client.

    Uses the team's standard security JQL query:
    - PSIRT issues (summary or labels)
    - Security labeled issues (excluding SCA/SAST/IAC/secret_removal)
    - Security escalations
    - Filtered to NS Client component

    Optionally filters by release fixVersion.

    Returns:
        {
            "issues": [
                {
                    "key": "ENG-123",
                    "summary": "Security vulnerability fix",
                    "severity": "Critical",
                    "assignee": "Jane Doe",
                    "status": "In Progress",
                    "type": "Bug",
                    "fixVersion": "134.0.0",
                    "url": "https://..."
                }
            ],
            "total": 7,
            "jira_url": "https://..."
        }
    """
    try:
        jira = get_jira_client()

        # Parse release version for JQL
        version_num = release.replace("R", "") if release else None
        fix_version = f"{version_num}.0.0" if version_num else None

        # Security issues JQL - matches team's standard query
        # First clause: PSIRT/Security labeled issues filtered by fixVersion
        # Second clause: Security escalations filtered by fixVersion
        fix_version_clause = f"AND fixVersion = {fix_version} " if fix_version else ""
        jql = (
            "("
            '(summary ~ "PSIRT" OR labels = PSIRT OR labels = Security OR labels = nplan-5481) '
            f"{fix_version_clause}"
            "AND component IS NOT EMPTY "
            'AND ("Product Category[Dropdown]" = Client OR component IN ("NS Client (NSC)")) '
            "AND status NOT IN (Closed, Resolved, DUPLICATE, Beta, GA, GA-Controlled, Completed)"
            ") OR ("
            'component IN ("NS Client (NSC)") '
            f"{fix_version_clause}"
            'AND "Type of Escalation[Dropdown]" IN (Security) '
            "AND status NOT IN (Resolved, Closed, DUPLICATE, Beta, GA, GA-Controlled, Completed)"
            ") "
            "ORDER BY assignee ASC, issuetype ASC"
        )

        logger.info("Fetching security issues with JQL: %s", jql)

        issues = await jira.search_issues(jql, max_results=200, fetch_all=True)

        result_issues = []
        jira_base_url = os.getenv("JIRA_URL", "https://your-org.atlassian.net")

        # Map priority to severity
        severity_map = {
            "Highest": "Critical",
            "Blocker": "Critical",
            "Critical": "Critical",
            "High": "High",
            "Medium": "Medium",
            "Low": "Low",
            "Lowest": "Low",
        }

        for issue in issues:
            # Get fix versions from issue
            fix_versions = issue.get("fixVersions") or []
            fix_version_names = [fv.get("name") if isinstance(fv, dict) else str(fv) for fv in fix_versions]

            priority = issue.get("priority", "Medium")
            severity = severity_map.get(priority, "Medium")
            issue_type = issue.get("issuetype", "Issue")

            result_issues.append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "priority": priority,
                    "severity": severity,
                    "assignee": issue.get("assignee") or "Unassigned",
                    "status": issue.get("status"),
                    "type": issue_type,
                    "fixVersion": ", ".join(fix_version_names) if fix_version_names else None,
                    "labels": issue.get("labels", []),
                    "url": f"{jira_base_url}/browse/{issue.get('key')}",
                }
            )

        # Build JIRA URL for "Open in JIRA" link
        jira_search_url = f"{jira_base_url}/issues/?jql={jql.replace(' ', '%20')}"

        return {"issues": result_issues, "total": len(result_issues), "jira_url": jira_search_url}

    except JiraAuthError as e:
        logger.error("JIRA auth error: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error fetching security issues: %s", e)
        # Return empty list instead of error for graceful degradation
        return {"issues": [], "total": 0, "error": str(e)}


# =============================================================================
# Feature Insights — Active NPLANs by lifecycle phase
# =============================================================================

STATUS_PHASE_ORDER = ["Under Review", "Design In Progress", "Implementation In Progress", "Beta"]
STATUS_PHASE_META = {
    "Under Review": {"key": "under_review", "color": "#3b82f6", "order": 0},
    "Design In Progress": {"key": "design_in_progress", "color": "#8b5cf6", "order": 1},
    "Implementation In Progress": {"key": "implementation_in_progress", "color": "#f59e0b", "order": 2},
    "Beta": {"key": "beta", "color": "#10b981", "order": 3},
}

QUARTER_COLORS = {"Q1": "#3b82f6", "Q2": "#8b5cf6", "Q3": "#f59e0b", "Q4": "#10b981"}

# Health signal thresholds
SIGNAL_THRESHOLDS = {
    "blocked_ratio_red": 0.25,
    "blocked_ratio_amber": 0.10,
    "no_eng_tickets": True,
    "low_progress_red": 0.10,
    "low_progress_amber": 0.30,
}

# Server-side cache for feature-insights (avoids re-fetching on every page load)
_feature_insights_cache: Dict = {}
_feature_insights_cache_time: float = 0.0
FEATURE_INSIGHTS_CACHE_TTL = 120  # 2 minutes


def _parse_quarter_from_delivery_target(dt_value):
    """Extract year and quarter from delivery target like '26-Q2-May' or '26-Q2-May-R137'."""
    import re

    if not dt_value:
        return None, None
    match = re.match(r"(\d{2})-(Q\d)", str(dt_value))
    if match:
        year = int("20" + match.group(1))
        quarter = match.group(2)
        return year, quarter
    return None, None


def _compute_health_signal(nplan_data):
    """Compute RAG health signal for an NPLAN based on ticket health."""
    eng = nplan_data.get("eng_tickets", {})
    total = eng.get("total", 0)
    blocked = eng.get("blocked", 0)
    done = eng.get("done", 0)
    status = nplan_data.get("status", "")

    # Red: no ENG tickets at all (risk of no implementation)
    if total == 0:
        return "red", "No ENG tickets linked"

    blocked_ratio = blocked / total if total > 0 else 0
    progress_ratio = done / total if total > 0 else 0

    # Red: high blocked ratio
    if blocked_ratio >= SIGNAL_THRESHOLDS["blocked_ratio_red"]:
        return "red", f"{blocked}/{total} ENG tickets blocked ({blocked_ratio:.0%})"

    # Red: in Implementation/Beta but very low completion
    if status in ("Implementation In Progress", "Beta") and progress_ratio < SIGNAL_THRESHOLDS["low_progress_red"]:
        return "red", f"Only {done}/{total} done ({progress_ratio:.0%}) in {status}"

    # Amber: moderate blocked ratio
    if blocked_ratio >= SIGNAL_THRESHOLDS["blocked_ratio_amber"]:
        return "amber", f"{blocked}/{total} ENG tickets blocked ({blocked_ratio:.0%})"

    # Amber: in Implementation/Beta but low completion
    if status in ("Implementation In Progress", "Beta") and progress_ratio < SIGNAL_THRESHOLDS["low_progress_amber"]:
        return "amber", f"{done}/{total} done ({progress_ratio:.0%}) in {status}"

    # Green: healthy
    return "green", f"{done}/{total} done ({progress_ratio:.0%})"


@router.get("/feature-insights")
async def get_feature_insights(
    refresh: bool = Query(False, description="Force refresh cached data"),
):
    """
    Get active NPLANs grouped by lifecycle phase with related tickets.

    Returns NPLANs from "YourCompany Product Plan" where Owner Eng Function = Client,
    excluding Backlog and GA statuses. Each NPLAN includes:
      - ENG tickets (with blocked/delayed flags)
      - Non-ENG tickets (IO, CAP, SIA, PCM, etc.)
      - Related NPLANs (via issue links)
    """
    global _feature_insights_cache, _feature_insights_cache_time

    # Return cached data if fresh (2 min TTL)
    if (
        not refresh
        and _feature_insights_cache
        and (time.time() - _feature_insights_cache_time) < FEATURE_INSIGHTS_CACHE_TTL
    ):
        logger.info("Feature Insights: returning cached data (age %.1fs)", time.time() - _feature_insights_cache_time)
        return _feature_insights_cache

    jira = get_jira_client()
    if not jira.is_configured():
        raise HTTPException(status_code=503, detail="JIRA not configured")

    try:
        # Step 1: Build JQL — try cf[] syntax first, fall back to display name
        owner_field_id = await jira.discover_custom_field_id("Owner Eng Function")
        excluded_statuses = 'Backlog, GA, "GA - Controlled", Closed, Done'

        # Try cf[] syntax first (faster), if no results fall back to display name
        jql = None
        nplan_issues = None
        for field_clause in [
            f'cf[{owner_field_id.replace("customfield_", "")}] = "Client"' if owner_field_id else None,
            '"Owner Eng Function[Dropdown]" = "Client"',
        ]:
            if not field_clause:
                continue
            jql = (
                f'project = "YourCompany Product Plan" AND {field_clause} '
                f"AND status NOT IN ({excluded_statuses}) ORDER BY status"
            )
            logger.info("Feature Insights JQL attempt: %s", jql)
            try:
                nplan_issues = await jira.search_issues(jql, max_results=200, fetch_all=True, include_links=True)
                if nplan_issues:
                    break
            except Exception as jql_err:
                logger.warning("JQL attempt failed: %s — %s", field_clause, jql_err)
                nplan_issues = None
        if not nplan_issues:
            return {
                "total_nplans": 0,
                "status_groups": {},
                "summary": {
                    "by_status": {},
                    "total_eng_tickets": 0,
                    "total_blocked_eng": 0,
                    "total_non_eng_tickets": 0,
                    "total_related_nplans": 0,
                },
                "sunburst_data": {"categories": []},
            }

        nplan_keys = [n["key"] for n in nplan_issues]
        logger.info("Feature Insights: found %d active NPLANs", len(nplan_keys))

        # Step 3: Links already fetched in the search query (include_links=True)
        # Build links map directly from search results — no extra API calls needed
        links_by_nplan = {}
        for nplan in nplan_issues:
            linked = nplan.get("linked_issues", [])
            if linked:
                links_by_nplan[nplan["key"]] = {"linked_issues": linked}

        # Step 4: Fetch child ENG tickets via portfolioChildIssuesOf (batch of 10)
        nplan_child_jql_parts = [f'issue in portfolioChildIssuesOf("{k}")' for k in nplan_keys]
        batch_size = 10
        child_tasks = []
        for i in range(0, len(nplan_child_jql_parts), batch_size):
            batch = nplan_child_jql_parts[i : i + batch_size]
            batch_jql = f'({" OR ".join(batch)}) ORDER BY key'
            child_tasks.append(jira.search_issues(batch_jql, max_results=500, fetch_all=True))

        child_batch_results = await asyncio.gather(*child_tasks, return_exceptions=True)
        all_child_issues = []
        for result in child_batch_results:
            if isinstance(result, Exception):
                logger.warning("Error fetching child tickets batch: %s", result)
            else:
                all_child_issues.extend(result)

        child_tickets_by_nplan = {k: [] for k in nplan_keys}

        # Map child tickets to their parent NPLAN
        for child in all_child_issues:
            parent_obj = child.get("parent")
            parent_key = ""
            if isinstance(parent_obj, dict):
                parent_key = parent_obj.get("key", "")
            elif isinstance(parent_obj, str):
                parent_key = parent_obj
            if parent_key in child_tickets_by_nplan:
                child_tickets_by_nplan[parent_key].append(child)

        # Step 5: Build per-NPLAN data with classified linked issues
        jira_base_url = jira.base_url
        nplan_data_list = []

        for nplan in nplan_issues:
            nplan_key = nplan["key"]
            nplan_status = nplan.get("status", "")

            linked_issues = []
            if nplan_key in links_by_nplan:
                linked_issues = links_by_nplan[nplan_key].get("linked_issues", [])

            # Classify linked issues into 3 buckets
            eng_items = {}
            non_eng_items = []
            related_nplans = []

            for link in linked_issues:
                link_key = link.get("key", "")
                project_prefix = link_key.split("-")[0] if "-" in link_key else ""

                if project_prefix == "ENG":
                    eng_items[link_key] = link
                elif project_prefix == "NPLAN":
                    related_nplans.append(
                        {
                            "key": link_key,
                            "summary": link.get("summary", ""),
                            "status": link.get("status", ""),
                            "link_type": link.get("link_type", ""),
                            "direction": link.get("direction", ""),
                            "url": link.get("url", f"{jira_base_url}/browse/{link_key}"),
                        }
                    )
                else:
                    non_eng_items.append(
                        {
                            "key": link_key,
                            "summary": link.get("summary", ""),
                            "status": link.get("status", ""),
                            "priority": link.get("priority", ""),
                            "project": project_prefix,
                            "link_type": link.get("link_type", ""),
                            "direction": link.get("direction", ""),
                            "url": link.get("url", f"{jira_base_url}/browse/{link_key}"),
                        }
                    )

            # Merge child tickets (de-duplicate by key)
            for child in child_tickets_by_nplan.get(nplan_key, []):
                child_key = child.get("key", "")
                if child_key and child_key not in eng_items:
                    eng_items[child_key] = {
                        "key": child_key,
                        "summary": child.get("summary", ""),
                        "status": child.get("status", ""),
                        "priority": child.get("priority", ""),
                        "assignee": child.get("assignee", ""),
                        "url": f"{jira_base_url}/browse/{child_key}",
                    }

            # Apply blocked/delayed logic to ENG tickets
            eng_ticket_list = []
            blocked_count = 0
            in_progress_count = 0
            done_count = 0
            todo_count = 0

            for ek, edata in eng_items.items():
                status_cat = get_status_category(edata.get("status", ""))
                is_blocked = status_cat == "blocked"
                if is_blocked:
                    blocked_count += 1
                elif status_cat == "done":
                    done_count += 1
                elif status_cat == "in_progress":
                    in_progress_count += 1
                else:
                    todo_count += 1

                eng_ticket_list.append(
                    {
                        "key": ek,
                        "summary": edata.get("summary", ""),
                        "status": edata.get("status", ""),
                        "status_category": status_cat,
                        "is_blocked": is_blocked,
                        "priority": edata.get("priority", ""),
                        "assignee": edata.get("assignee", ""),
                        "url": edata.get("url", f"{jira_base_url}/browse/{ek}"),
                    }
                )

            status_sort = {"blocked": 0, "in_progress": 1, "todo": 2, "done": 3}
            eng_ticket_list.sort(key=lambda t: status_sort.get(t["status_category"], 4))

            nplan_entry = {
                "key": nplan_key,
                "summary": nplan.get("summary", ""),
                "status": nplan_status,
                "assignee": nplan.get("assignee", ""),
                "delivery_target_beta": nplan.get("delivery_target_beta", ""),
                "delivery_target_ga": nplan.get("delivery_target_ga", ""),
                "url": f"{jira_base_url}/browse/{nplan_key}",
                "eng_tickets": {
                    "total": len(eng_ticket_list),
                    "blocked": blocked_count,
                    "in_progress": in_progress_count,
                    "done": done_count,
                    "todo": todo_count,
                    "items": eng_ticket_list,
                },
                "non_eng_tickets": {
                    "total": len(non_eng_items),
                    "items": non_eng_items,
                },
                "related_nplans": {
                    "total": len(related_nplans),
                    "items": related_nplans,
                },
            }

            # Compute health signal
            signal, signal_reason = _compute_health_signal(nplan_entry)
            nplan_entry["health_signal"] = signal
            nplan_entry["signal_reason"] = signal_reason

            nplan_data_list.append(nplan_entry)

        # Step 6: Group by status phase
        status_groups = {}
        for phase_name in STATUS_PHASE_ORDER:
            meta = STATUS_PHASE_META[phase_name]
            phase_nplans = [n for n in nplan_data_list if n["status"] == phase_name]
            status_groups[meta["key"]] = {
                "label": phase_name,
                "count": len(phase_nplans),
                "color": meta["color"],
                "nplans": phase_nplans,
            }

        # NPLANs with unexpected statuses → "other" group
        known_statuses = set(STATUS_PHASE_ORDER)
        other_nplans = [n for n in nplan_data_list if n["status"] not in known_statuses]
        if other_nplans:
            status_groups["other"] = {
                "label": "Other",
                "count": len(other_nplans),
                "color": "#6b7280",
                "nplans": other_nplans,
            }

        # Step 7: Summary
        total_eng = sum(n["eng_tickets"]["total"] for n in nplan_data_list)
        total_blocked = sum(n["eng_tickets"]["blocked"] for n in nplan_data_list)
        total_non_eng = sum(n["non_eng_tickets"]["total"] for n in nplan_data_list)
        total_related = sum(n["related_nplans"]["total"] for n in nplan_data_list)
        by_status = {}
        for n in nplan_data_list:
            s = n["status"]
            by_status[s] = by_status.get(s, 0) + 1

        # Step 8: Sunburst chart data
        sunburst_categories = []
        for phase_name in STATUS_PHASE_ORDER:
            meta = STATUS_PHASE_META[phase_name]
            phase_nplans = [n for n in nplan_data_list if n["status"] == phase_name]
            if not phase_nplans:
                continue
            children = []
            for n in phase_nplans:
                eng_count = max(n["eng_tickets"]["total"], 1)
                children.append(
                    {
                        "name": f"{n['key']}: {n['summary'][:50]}",
                        "key": n["key"],
                        "value": eng_count,
                        "blocked": n["eng_tickets"]["blocked"],
                    }
                )
            sunburst_categories.append(
                {
                    "name": phase_name,
                    "key": meta["key"],
                    "color": meta["color"],
                    "count": len(phase_nplans),
                    "children": children,
                }
            )

        # Step 9: Quarter-wise grouping using delivery_target_beta
        quarter_data = {}
        available_years = set()
        for n in nplan_data_list:
            dt = n.get("delivery_target_beta") or n.get("delivery_target_ga") or ""
            year, quarter = _parse_quarter_from_delivery_target(dt)
            n["quarter"] = quarter or "Unplanned"
            n["quarter_year"] = year
            if year:
                available_years.add(year)
            q_key = f"{year}-{quarter}" if year and quarter else "Unplanned"
            if q_key not in quarter_data:
                quarter_data[q_key] = {
                    "year": year,
                    "quarter": quarter or "Unplanned",
                    "label": f"{quarter} {year}" if year and quarter else "Unplanned",
                    "color": QUARTER_COLORS.get(quarter, "#6b7280"),
                    "nplans": [],
                    "status_breakdown": {},
                }
            quarter_data[q_key]["nplans"].append(n["key"])
            s = n["status"]
            quarter_data[q_key]["status_breakdown"][s] = quarter_data[q_key]["status_breakdown"].get(s, 0) + 1

        # Sort quarters chronologically
        sorted_quarters = sorted(
            quarter_data.values(),
            key=lambda q: (q["year"] or 9999, q["quarter"] or "ZZ"),
        )

        # Build per-year quarter sunburst data
        yearly_quarter_charts = {}
        for year in sorted(available_years):
            year_nplans = [n for n in nplan_data_list if n.get("quarter_year") == year]
            if not year_nplans:
                continue
            q_categories = []
            for q_name in ["Q1", "Q2", "Q3", "Q4"]:
                q_nplans = [n for n in year_nplans if n.get("quarter") == q_name]
                if not q_nplans:
                    continue
                children = []
                for n in q_nplans:
                    eng_count = max(n["eng_tickets"]["total"], 1)
                    children.append(
                        {
                            "name": f"{n['key']}: {n['summary'][:50]}",
                            "key": n["key"],
                            "value": eng_count,
                            "blocked": n["eng_tickets"]["blocked"],
                            "signal": n.get("health_signal", "green"),
                        }
                    )
                q_categories.append(
                    {
                        "name": q_name,
                        "key": q_name.lower(),
                        "color": QUARTER_COLORS.get(q_name, "#6b7280"),
                        "count": len(q_nplans),
                        "children": children,
                    }
                )
            yearly_quarter_charts[str(year)] = {"categories": q_categories}

        # Step 10: Health signal summary
        signal_counts = {"red": 0, "amber": 0, "green": 0}
        for n in nplan_data_list:
            sig = n.get("health_signal", "green")
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        jira_url = f"{jira_base_url}/issues/?jql={jql.replace(' ', '%20')}"

        response = {
            "total_nplans": len(nplan_data_list),
            "status_groups": status_groups,
            "summary": {
                "by_status": by_status,
                "total_eng_tickets": total_eng,
                "total_blocked_eng": total_blocked,
                "total_non_eng_tickets": total_non_eng,
                "total_related_nplans": total_related,
            },
            "sunburst_data": {"categories": sunburst_categories},
            "quarter_view": {
                "available_years": sorted(available_years),
                "quarters": sorted_quarters,
                "yearly_charts": yearly_quarter_charts,
            },
            "health_signals": {
                "counts": signal_counts,
                "thresholds": SIGNAL_THRESHOLDS,
            },
            "jira_url": jira_url,
        }

        # Cache the response
        _feature_insights_cache = response
        _feature_insights_cache_time = time.time()
        return response

    except JiraAuthError as e:
        logger.error("JIRA auth error in feature-insights: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.error("Error in feature-insights: %s", e)
        return {
            "total_nplans": 0,
            "status_groups": {},
            "summary": {
                "by_status": {},
                "total_eng_tickets": 0,
                "total_blocked_eng": 0,
                "total_non_eng_tickets": 0,
                "total_related_nplans": 0,
            },
            "sunburst_data": {"categories": []},
            "error": str(e),
        }

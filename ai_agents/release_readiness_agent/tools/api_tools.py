"""
API Tools for Release Readiness Agent
=====================================

Tools return formatted markdown responses (not raw JSON).
ADK discovers tools from function signatures and docstrings.
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx
from core.utils import get_utils

logger = logging.getLogger(__name__)

# Backend API URL - uses BACKEND_URL env var (set in docker-compose.yml)
API_BASE = os.environ.get("BACKEND_URL", "http://localhost:8000")

# Get shared formatter instance
_utils = get_utils()


async def _api_get(endpoint: str, params: Dict = None) -> Dict[str, Any]:
    """Make API GET request with error handling."""
    try:
        async with httpx.AsyncClient(timeout=90, verify=False) as client:
            response = await client.get(f"{API_BASE}{endpoint}", params=params or {})
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"error": str(e)}


# =============================================================================
# RELEASE HEALTH TOOLS
# =============================================================================


async def calculate_release_readiness_score(release_id: str = "R134", component: str = "YOUR_PRODUCT") -> str:
    """
    Is the release ready? Check health score (green/yellow/red status).

    Use when asked: "is release green?", "release status", "are we ready to ship?"
    Score: 100% - (openItems × 3%). Green ≥85%, Yellow 70-84%, Red <70%

    Args:
        release_id: Release identifier like R134
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    # Default to YOUR_PRODUCT if not specified or empty
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"

    params = {"release": release_id}
    data = await _api_get("/api/jira/release-readiness", params)
    return _utils.format_release_readiness(data, target_component)


async def explain_release_readiness_score(release_id: str = "R134") -> str:
    """
    Why is the score low? How to improve it? Root cause analysis with recommendations.

    Use when asked: "why is RRS 61%?", "how to improve score?", "what's blocking us?"

    Args:
        release_id: Release identifier like R134
    """
    data = await _api_get("/api/jira/release-readiness", {"release": release_id})
    # Return detailed analysis
    rrs = data.get("rrs", data)
    overall = rrs.get("overall", 0)

    lines = [_utils.format_release_readiness(data)]

    # Add recommendations based on score
    if overall < 85:
        lines.append("\n### Recommendations to Improve Score")
        components = rrs.get("components", {})
        for name, score in components.items():
            if score < 85:
                lines.append(f"- Focus on **{name}** (currently {score}%)")

    return "\n".join(lines)


async def get_resolution_progress(release_id: str = "R134") -> str:
    """
    How is bug/story resolution progressing? Day-by-day trend from IRR to Final Build.

    Use when asked: "resolution progress", "how are we trending?", "velocity"

    Args:
        release_id: Release identifier like R134
    """
    data = await _api_get("/api/jira/resolution-progress", {"release": release_id})

    timeline = data.get("timeline", {})
    summary = data.get("summary", {})

    resolved = summary.get("resolved", 0)
    remaining = summary.get("remaining", 0)

    lines = [
        f"## 📊 Resolution Progress: {release_id}",
        "",
        f"**Resolved:** {resolved}",
        f"**Remaining:** {remaining}",
        "",
    ]

    if timeline:
        lines.append("### Daily Trend")
        for date, count in list(timeline.items())[-7:]:  # Last 7 days
            lines.append(f"- {date}: {count} resolved")

    return "\n".join(lines)


# =============================================================================
# MILESTONE TOOLS
# =============================================================================


async def get_irr_status(release_id: str = "R134", component: str = "YOUR_PRODUCT") -> str:
    """
    IRR milestone status - on-time rate, late items, still-open items.

    Use when asked: "IRR status", "how did IRR go?", "stories resolved by IRR"

    Args:
        release_id: Release identifier like R134
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"
    data = await _api_get("/api/jira/milestone/irr", {"release": release_id})
    return _utils.format_milestone_status(data, "IRR", target_component)


async def get_branch_cut_status(release_id: str = "R134", component: str = "YOUR_PRODUCT") -> str:
    """
    Branch Cut milestone status - stories resolved vs still open.

    Use when asked: "branch cut status", "are we ready for branch cut?"

    Args:
        release_id: Release identifier like R134
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"
    data = await _api_get("/api/jira/milestone/branch-cut", {"release": release_id})
    return _utils.format_milestone_status(data, "Branch Cut", target_component)


async def get_final_build_status(release_id: str = "R134", component: str = "YOUR_PRODUCT") -> str:
    """
    Final Build milestone status - blocking items before final build.

    Use when asked: "final build status", "what's blocking final build?"

    Args:
        release_id: Release identifier like R134
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"
    data = await _api_get("/api/jira/milestone/final-build", {"release": release_id})
    return _utils.format_milestone_status(data, "Final Build", target_component)


async def calendar_get_release_dates(release_id: str = "R134") -> str:
    """
    Release timeline and key dates - IRR, Branch Cut, Final Build, Deployment.

    Use when asked: "when is code freeze?", "milestone dates", "release timeline"

    Args:
        release_id: Release identifier like R134
    """
    # Add .0 suffix for major releases if not present
    release_name = release_id if "." in release_id else f"{release_id}.0"
    data = await _api_get(f"/api/release-calendar/releases/{release_name}")
    return _utils.format_release_dates(data)


# =============================================================================
# BUG TOOLS
# =============================================================================


async def jira_get_critical_bugs(project_key: str = "ENG", component: str = "YOUR_PRODUCT") -> str:
    """
    Critical/blocker bugs needing immediate attention - P0/P1 priority.

    Use when asked: "critical bugs", "blockers", "P0 issues", "what's blocking?"

    Args:
        project_key: JIRA project key (default ENG)
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"
    params = {"project_key": project_key, "component": target_component}
    data = await _api_get("/api/jira/bugs/critical", params)
    return _utils.format_critical_bugs(data, target_component)


async def jira_get_regression_bugs(
    project_key: str = "ENG", fix_version: str = "134.0", component: str = "YOUR_PRODUCT"
) -> str:
    """
    Regression bugs - issues that broke previously working functionality.

    Use when asked: "regression bugs", "what regressed?", "new bugs introduced"

    Args:
        project_key: JIRA project key (default ENG)
        fix_version: Fix version like 134.0
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"
    params = {"project_key": project_key, "fix_version": fix_version, "component": target_component}
    data = await _api_get("/api/jira/bugs/regression", params)
    return _utils.format_regression_bugs(data, target_component)


async def jira_get_moreinfo_items(release_id: str = "R134") -> str:
    """
    Items stuck in MoreInfo status - waiting for additional information.

    Use when asked: "moreinfo bugs", "awaiting information", "stuck items"

    Args:
        release_id: Release identifier like R134
    """
    data = await _api_get("/api/jira/release-readiness", {"release": release_id})

    # Extract moreinfo items from release readiness data
    moreinfo = data.get("moreinfo", data.get("moreInfoItems", []))

    if not moreinfo:
        return "## ✅ MoreInfo Items\n\nNo items stuck in MoreInfo status!"

    lines = [f"## ⏳ MoreInfo Items - {len(moreinfo)} total", ""]

    for item in moreinfo[:15]:
        if isinstance(item, dict):
            key = item.get("key", "N/A")
            summary = (item.get("summary", ""))[:50]
            reporter = item.get("reporter", "Unknown")
            lines.append(f"- **{key}**: {summary} | Waiting on: {reporter}")

    return "\n".join(lines)


async def jira_get_escalations_summary(project_key: str = "ENG") -> str:
    """
    Customer escalations - EHF (Engineering Hot Fix) and IMF (Immediate Fix).

    Use when asked: "escalations", "EHF", "IMF", "customer issues"

    Args:
        project_key: JIRA project key (default ENG)
    """
    data = await _api_get("/api/jira/escalations", {"project_key": project_key})
    return _utils.format_escalations(data)


# =============================================================================
# WORK & ASSIGNMENT TOOLS
# =============================================================================


async def jira_get_action_items(release_id: str = "R134", component: str = "YOUR_PRODUCT") -> str:
    """
    Open items by assignee - workload analysis, who has most items.

    Use when asked: "action items", "workload", "who has most bugs?", "assignee load"

    Args:
        release_id: Release identifier like R134
        component: Component filter - defaults to YOUR_PRODUCT (dashboard focus)
    """
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"

    params = {"release": release_id}
    data = await _api_get("/api/jira/release-readiness", params)

    # Extract items from componentsData filtered by target component
    components_data = data.get("componentsData", {})
    comp_issues = []

    if target_component.upper() in components_data:
        comp_issues = components_data[target_component.upper()].get("issues", [])

    if not comp_issues:
        return f"## 📋 Action Items: {release_id} ({target_component})\n\n✅ No open action items found!"

    # Group by assignee
    assignee_counts = {}
    for issue in comp_issues:
        assignee = issue.get("assignee") or "Unassigned"
        assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1

    lines = [f"## 📋 Action Items: {release_id} ({target_component})", ""]

    # Sort by count descending
    sorted_assignees = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)
    for assignee, count in sorted_assignees[:10]:
        lines.append(f"- **{assignee}:** {count} items")

    lines.append("")
    lines.append(f"**Total Open:** {len(comp_issues)} items")

    return "\n".join(lines)


# =============================================================================
# TESTING TOOLS
# =============================================================================


async def get_test_execution(release_id: str = "R134") -> str:
    """
    Test execution status - pass/fail rates from TestRail.

    Use when asked: "test results", "pass rate", "test execution", "how are tests?"

    Args:
        release_id: Release identifier like R134
    """
    data = await _api_get("/api/testrail/milestone-data", {"release": release_id})
    return _utils.format_test_execution(data)


async def get_untested_cases(release_id: str = "R134") -> str:
    """
    Untested test cases grouped by owner - what's not yet tested.

    Use when asked: "untested cases", "what's not tested?", "test coverage gaps"

    Args:
        release_id: Release identifier like R134
    """
    data = await _api_get("/api/testrail/untested-by-owner", {"release": release_id})

    owners = data.get("owners", data.get("byOwner", []))
    total = data.get("totalUntested", sum(o.get("count", 0) for o in owners if isinstance(o, dict)))

    if not owners:
        return "## ✅ Test Coverage\n\nAll test cases have been executed!"

    lines = [f"## ⏳ Untested Cases - {total} total", ""]

    for owner in owners[:10]:
        if isinstance(owner, dict):
            name = owner.get("owner", owner.get("name", "Unknown"))
            count = owner.get("count", 0)
            lines.append(f"- **{name}:** {count} cases")

    return "\n".join(lines)


# =============================================================================
# CI/CD TOOLS
# =============================================================================


async def get_code_commits(release_id: str = "R134", repo: Optional[str] = None) -> str:
    """
    Git/code commits for a release - shows commits before and after branch cut.

    Use when asked: "commits", "git commits", "commits before/after branch cut", "flagged commits"

    Args:
        release_id: Release identifier like R134
        repo: Optional repo filter (client, service, enrollment-service, device-classification)
    """
    data = await _api_get("/api/github/commits", {"release": release_id})
    return _utils.format_code_commits(data, repo)


# =============================================================================
# TOOL REGISTRY
# =============================================================================

ALL_TOOLS = [
    # Release Health
    calculate_release_readiness_score,
    explain_release_readiness_score,
    get_resolution_progress,
    # Milestones
    get_irr_status,
    get_branch_cut_status,
    get_final_build_status,
    calendar_get_release_dates,
    # Bugs & Issues
    jira_get_critical_bugs,
    jira_get_regression_bugs,
    jira_get_moreinfo_items,
    jira_get_escalations_summary,
    # Work & Assignments
    jira_get_action_items,
    # Testing
    get_test_execution,
    get_untested_cases,
    # CI/CD
    get_code_commits,
]


def get_all_tools():
    """Return all available tools for the agent."""
    return ALL_TOOLS

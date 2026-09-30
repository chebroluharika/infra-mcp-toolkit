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
JIRA MCP Server
Exposes JIRA API as MCP tools for AI agents

Usage:
    uv run server.py

Environment Variables:
    JIRA_URL - JIRA server URL (e.g., https://company.atlassian.net)
    JIRA_USERNAME - JIRA username/email
    JIRA_API_TOKEN - JIRA API token
"""

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("jira-mcp-server")

# Default release from environment variable (single source of truth - REQUIRED)
DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
if not DEFAULT_RELEASE:
    raise EnvironmentError(
        "CURRENT_RELEASE environment variable is required! "
        "Set it in your .env file or docker-compose.yml (e.g., CURRENT_RELEASE=R134)"
    )


# =============================================================================
# Status Constants (matching JIRA workflow)
# =============================================================================

OPEN_STATUSES = ["Open", "In Progress", "In Development", "In Review", "Code Review", "To Do", "Backlog", "Reopened"]

RESOLVED_STATUSES = ["Resolved", "Fixed", "Done"]

CLOSED_STATUSES = ["Closed", "Verified", "Released"]

REGRESSION_CLASSIFICATION_VALUES = [
    "Regression",
    "Regression (A previously working feature is broken)",
    "External Regression",
]

FEATURE_CLASSIFICATION_VALUES = ["Feature", "Feature Issue (Feature never known to have worked)"]

ESCALATION_STATUS_CATEGORIES = {
    "open": ["Open", "Re-Open"],
    "in_progress": ["In Progress"],
    "more_info": ["More Info"],
    "pending_resolution": ["Pending Resolution"],
    "resolved": ["Resolved"],
    "closed": ["Closed"],
}


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool()
async def jira_search_issues(
    jql: str, max_results: int = 50, fetch_all: bool = False  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """
    FLEXIBLE SEARCH - Use JQL to find issues matching any criteria.

    Construct JQL from user's natural language query:
    - "bugs with no assignee" → jql='fixVersion = "135.0" AND issuetype = Bug AND assignee IS EMPTY'
    - "P0 bugs for R135" → jql='fixVersion = "135.0" AND priority = P0 AND issuetype = Bug'
    - "open stories assigned to John" → jql='fixVersion = "135.0" AND issuetype = Story AND assignee = "John"'
    - "items in Code Review" → jql='fixVersion = "135.0" AND status = "Code Review"'

    JQL patterns:
    - Unassigned: assignee IS EMPTY
    - By status: status = "In Progress"
    - By priority: priority = P0 or priority IN (P0, P1)
    - By type: issuetype = Bug or issuetype = Story
    - Open items: status NOT IN (Resolved, Closed, Done)

    Args:
        jql: JQL query string constructed from user's intent
        max_results: Maximum results (default 50)

    Returns:
        Matching issues with formatted display
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jira/search", params={"jql": jql, "max_results": max_results})

            if response.status_code != 200:
                return {
                    "count": 0,
                    "issues": [],
                    "error": f"Backend returned {response.status_code}",
                    "display": f"**Error:** Search failed with status {response.status_code}",
                }

            data = response.json()
            issues = data.get("issues", [])
            count = data.get("count", len(issues))

            # Build display
            lines = [
                "## 🔍 Search Results",
                "",
                f"**Query:** `{jql}`",
                f"**Found:** {count} issue(s)",
                "",
            ]

            if issues:
                lines.extend(
                    [
                        "| Key | Type | Priority | Assignee | Status | Summary |",
                        "|-----|------|----------|----------|--------|---------|",
                    ]
                )
                for issue in issues[:25]:
                    summary = issue.get("summary", "")[:35]
                    if len(issue.get("summary", "")) > 35:
                        summary += "..."
                    assignee = issue.get("assignee") or "Unassigned"
                    lines.append(
                        f"| {issue.get('key', '')} | {issue.get('issuetype', '')} | "
                        f"{issue.get('priority', '')} | {assignee} | "
                        f"{issue.get('status', '')} | {summary} |"
                    )
                if count > 25:
                    lines.append(f"\n*Showing 25 of {count} results*")
            else:
                lines.append("*No issues found matching this query.*")

            return {
                "count": count,
                "jql": jql,
                "issues": [
                    {
                        "key": i.get("key"),
                        "type": i.get("issuetype"),
                        "priority": i.get("priority"),
                        "assignee": i.get("assignee") or "Unassigned",
                        "status": i.get("status"),
                        "summary": i.get("summary", "")[:60],
                    }
                    for i in issues[:30]
                ],
                "display": "\n".join(lines),
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {
                "count": 0,
                "issues": [],
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def jira_get_bugs(
    project_key: str, status: str = None, priority: str = None, fix_version: str = None, max_results: int = 100
) -> Dict[str, Any]:
    """
    Get bugs from JIRA with optional filters by status, priority, or version.

    Use this tool when the user asks about:
    - "list all bugs" or "show bugs"
    - "bugs for R135" or "bugs in release 135"
    - "open bugs" or "resolved bugs" (use status filter)
    - "P1 bugs" or "high priority bugs" (use priority filter)
    - "how many bugs do we have?"

    Version extraction: "R135" → fix_version="135.0"

    Args:
        project_key: JIRA project key (default "ENG")
        status: Filter by status (e.g., "Open", "In Progress", "Resolved")
        priority: Filter by priority (e.g., "P0", "P1", "P2")
        fix_version: Filter by fix version (e.g., "135.0" from R135)
        max_results: Maximum bugs to return (default 100)

    Returns:
        Dict with bugs list and count
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            params = {"project_key": project_key}
            if status:
                params["status"] = status
            if priority:
                params["priority"] = priority
            if fix_version:
                params["fix_version"] = fix_version

            response = await client.get(f"{api_base}/api/jira/bugs", params=params)
            if response.status_code == 200:
                data = response.json()
                bugs = data.get("bugs", [])[:max_results]
                return {"count": len(bugs), "bugs": bugs}
            return {"count": 0, "bugs": [], "error": f"Backend returned {response.status_code}"}
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"count": 0, "bugs": [], "error": str(err)}


@mcp.tool()
async def jira_get_bugs_summary(fix_version: str = "135.0") -> Dict[str, Any]:
    """
    Get bug summary statistics - counts by status and priority.

    Use this tool when the user asks about:
    - "bug summary" or "bugs overview"
    - "how many bugs by status?" or "bug counts"
    - "bug breakdown for R135"
    - "total open vs resolved bugs"

    Version extraction: "R135" → fix_version="135.0"

    Args:
        fix_version: Fix version filter (e.g., "135.0" from R135)

    Returns:
        Summary with total, bugs, stories counts and breakdown by status/priority
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Convert fix_version to release format (135.0 -> R135)
    if fix_version and fix_version not in ("None", "null", ""):
        version_num = fix_version.split(".")[0].replace("R", "")
        release = f"R{version_num}"
    else:
        release = "R135"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            url = f"{api_base}/api/jira/release-data/summary"
            response = await client.get(url, params={"release": release})

            if response.status_code != 200:
                err_msg = f"Backend returned {response.status_code}"
                return {
                    "total": 0,
                    "error": err_msg,
                    "display": f"**Error:** {err_msg}",
                }

            data = response.json()
            summary = data.get("summary", {})
            metrics = data.get("metrics", {})

            # Build display
            total = summary.get("total", 0)
            bugs = summary.get("bugs", 0)
            stories = summary.get("stories", 0)
            by_status = summary.get("by_status", {})
            by_priority = summary.get("by_priority", {})

            lines = [
                f"## 🐛 Bug Summary: {release}",
                "",
                f"**Total Open Items:** {total}",
                f"- Bugs: {bugs}",
                f"- Stories: {stories}",
                "",
                f"**Health Score:** {metrics.get('health_score', 'N/A')}% ({metrics.get('status', 'Unknown')})",
                "",
            ]

            if by_priority:
                lines.append("### By Priority")
                for priority, count in by_priority.items():
                    lines.append(f"- {priority}: {count}")
                lines.append("")

            if by_status:
                lines.append("### By Status")
                for status, count in by_status.items():
                    lines.append(f"- {status}: {count}")

            return {
                "release": release,
                "total": total,
                "bugs": bugs,
                "stories": stories,
                "by_status": by_status,
                "by_priority": by_priority,
                "health_score": metrics.get("health_score"),
                "status": metrics.get("status"),
                "display": "\n".join(lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {
                "total": 0,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def jira_get_resolution_progress(release: str = "R135") -> Dict[str, Any]:
    """
    Get day-wise resolution progress for bugs and stories from IRR till now.

    Use this tool when the user asks about:
    - "resolution progress" or "resolution analysis"
    - "bugs resolved from IRR till now"
    - "stories resolution from IRR"
    - "daily resolution progress"
    - "how many bugs/stories resolved since IRR?"
    - "resolution chart" or "resolution trend"

    Args:
        release: Release ID like "R135"

    Returns:
        Day-wise resolution progress with totals and chart data
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize release format: "135.0" → "R135", "R135.0" → "R135"
    if release:
        release = release.upper().strip()
        # Remove R prefix if present for processing
        if release.startswith("R"):
            release = release[1:]
        # Extract just the major version number
        release_num = release.split(".")[0]
        release = f"R{release_num}"
    else:
        release = "R135"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            url = f"{api_base}/api/jira/resolution-progress"
            response = await client.get(url, params={"release": release})

            if response.status_code != 200:
                return {
                    "release": release,
                    "error": f"Backend returned {response.status_code}",
                    "display": f"**Error:** Backend returned {response.status_code}",
                }

            data = response.json()
            timeline = data.get("timeline", {})
            summary = data.get("summary", {})
            chart_data = data.get("chartData", [])

            # Extract metrics
            irr_date = timeline.get("irr_date", "N/A")
            final_build = timeline.get("final_build_date", "N/A")
            days_elapsed = timeline.get("days_elapsed", 0)
            days_remaining = timeline.get("days_remaining", 0)

            total_resolved = summary.get("totalResolved", 0)
            total_stories = summary.get("totalStories", 0)
            total_bugs = summary.get("totalBugs", 0)
            resolved_before_irr = summary.get("resolvedBeforeIRR", 0)
            resolved_after_irr = summary.get("resolvedAfterIRR", 0)
            avg_per_day = summary.get("avgPerDay", 0)

            # === TREND ANALYSIS ===
            analysis_lines = []
            trend_emoji = "📊"
            trend_status = "Stable"

            if len(chart_data) >= 5:
                # Calculate recent velocity (last 3 days) vs earlier velocity
                last_3_days = chart_data[-3:]
                earlier_days = chart_data[-7:-3] if len(chart_data) >= 7 else chart_data[:-3]

                recent_resolved = sum(d.get("dailyTotal", 0) for d in last_3_days)
                earlier_resolved = sum(d.get("dailyTotal", 0) for d in earlier_days)

                recent_avg = recent_resolved / len(last_3_days) if last_3_days else 0
                earlier_avg = earlier_resolved / len(earlier_days) if earlier_days else 0

                # Determine trend
                if recent_avg > earlier_avg * 1.2:
                    trend_emoji = "📈"
                    trend_status = "Improving"
                    trend_desc = (
                        f"Resolution velocity is **increasing** ({recent_avg:.1f}/day vs {earlier_avg:.1f}/day earlier)"
                    )
                elif recent_avg < earlier_avg * 0.8:
                    trend_emoji = "📉"
                    trend_status = "Declining"
                    trend_desc = f"Resolution velocity is **slowing down** ({recent_avg:.1f}/day vs {earlier_avg:.1f}/day earlier)"
                else:
                    trend_emoji = "➡️"
                    trend_status = "Stable"
                    trend_desc = f"Resolution velocity is **stable** (~{avg_per_day}/day)"

                analysis_lines.append(f"**Trend:** {trend_emoji} {trend_desc}")

                # Calculate if on track
                if days_remaining > 0 and days_elapsed > 0:
                    # Get current open items (from release-data endpoint if available)
                    still_open = 90 - total_resolved  # Approximate based on IRR total
                    projected_at_current_rate = still_open / avg_per_day if avg_per_day > 0 else float("inf")

                    if projected_at_current_rate <= days_remaining:
                        analysis_lines.append(
                            f"**Projection:** ✅ On track to complete in ~{projected_at_current_rate:.0f} days (have {days_remaining} days)"
                        )
                    else:
                        analysis_lines.append(
                            f"**Projection:** ⚠️ Need to increase velocity - {still_open} items remaining, {days_remaining} days left"
                        )

            # Story vs Bug analysis
            story_pct = (total_stories / total_resolved * 100) if total_resolved > 0 else 0
            bug_pct = (total_bugs / total_resolved * 100) if total_resolved > 0 else 0
            before_irr_pct = (resolved_before_irr / total_resolved * 100) if total_resolved > 0 else 0

            if before_irr_pct >= 70:
                analysis_lines.append(
                    f"**IRR Readiness:** ✅ {before_irr_pct:.0f}% resolved before IRR (good preparation)"
                )
            elif before_irr_pct >= 50:
                analysis_lines.append(f"**IRR Readiness:** 🟡 {before_irr_pct:.0f}% resolved before IRR (moderate)")
            else:
                analysis_lines.append(
                    f"**IRR Readiness:** 🔴 Only {before_irr_pct:.0f}% resolved before IRR (late start)"
                )

            # Build display
            lines = [
                f"## {trend_emoji} Resolution Progress: {release}",
                "",
                f"**Timeline:** IRR ({irr_date}) → Final Build ({final_build})",
                f"**Progress:** {days_elapsed} days elapsed, {days_remaining} days remaining",
                "",
                "### 📊 Analysis",
                "",
            ]
            lines.extend(analysis_lines)
            lines.append("")

            lines.extend(
                [
                    "### Summary",
                    "",
                    "| Metric | Count |",
                    "|--------|-------|",
                    f"| Total Resolved | {total_resolved} |",
                    f"| Stories | {total_stories} ({story_pct:.0f}%) |",
                    f"| Bugs | {total_bugs} ({bug_pct:.0f}%) |",
                    f"| Resolved Before IRR | {resolved_before_irr} |",
                    f"| Resolved After IRR | {resolved_after_irr} |",
                    f"| Avg Per Day | {avg_per_day} |",
                    "",
                ]
            )

            # Add recent chart data (last 5 days)
            if chart_data:
                lines.extend(
                    [
                        "### Recent Daily Progress",
                        "",
                        "| Date | Stories | Bugs | Cumulative |",
                        "|------|---------|------|------------|",
                    ]
                )
                for day in chart_data[-5:]:
                    lines.append(
                        f"| {day.get('displayDate', '')} | {day.get('dailyStories', 0)} | "
                        f"{day.get('dailyBugs', 0)} | {day.get('cumulativeTotal', 0)} |"
                    )

            return {
                "release": release,
                "timeline": timeline,
                "summary": summary,
                "trend": trend_status,
                "chart_data": chart_data[-10:],  # Last 10 days
                "display": "\n".join(lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {
                "release": release,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def jira_get_critical_bugs(  # pylint: disable=too-many-locals
    fix_version: str = "135.0.0", max_results: int = 20
) -> Dict[str, Any]:
    """
    Get open critical and blocker priority bugs (P0/P1).

    Use this tool when the user asks about:
    - "critical bugs" or "blocker bugs"
    - "P0 bugs" or "P1 bugs" or "high priority bugs"
    - "show me the blockers" or "urgent bugs"
    - "what critical issues do we have?"
    - "any showstopper bugs?"

    Version extraction: "R135" → fix_version="135.0.0"

    Args:
        fix_version: Release version like "135.0.0" (extract from R135)
        max_results: Maximum bugs to return (default 20)

    Returns:
        Dict with count, breakdown by priority/assignee, and formatted bugs table
    """
    # Call backend API - use the blockers endpoint
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Extract release from fix_version (e.g., "135.0.0" -> "R135")
    version_num = fix_version.split(".")[0] if fix_version else "135"
    version_num = version_num.replace("R", "")
    release = f"R{version_num}"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        url = f"{api_base}/api/jira/release-data/blockers"
        params = {"release": release}

        response = await client.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            blockers = data.get("blockers", [])[:max_results]

            # Count by priority
            by_priority = {}
            by_assignee = {}
            by_status = {}

            for bug in blockers:
                priority = bug.get("priority", "Unknown")
                assignee = bug.get("assignee", "Unassigned")
                status = bug.get("status", "Unknown")

                by_priority[priority] = by_priority.get(priority, 0) + 1
                by_assignee[assignee] = by_assignee.get(assignee, 0) + 1
                by_status[status] = by_status.get(status, 0) + 1

            # Format bugs for table display
            bugs_table = []
            for bug in blockers:
                bug_summary = bug.get("summary", "")
                if len(bug_summary) > 50:
                    bug_summary = bug_summary[:50] + "..."
                bugs_table.append(
                    {
                        "key": bug.get("key", ""),
                        "summary": bug_summary,
                        "priority": bug.get("priority", "Unknown"),
                        "assignee": bug.get("assignee", "Unassigned"),
                        "status": bug.get("status", "Unknown"),
                        "type": bug.get("type", "Bug"),
                    }
                )

            # Top assignees
            top_assignees = sorted(by_assignee.items(), key=lambda x: x[1], reverse=True)[:5]

            # Build display field
            total = data.get("count", len(blockers))
            display_lines = [
                f"## 🚨 Critical/Blocker Bugs for {release}",
                "",
                f"**Total Open:** {total}",
                "",
            ]

            if by_priority:
                display_lines.extend(
                    [
                        "### By Priority",
                        "| Priority | Count |",
                        "|----------|-------|",
                    ]
                )
                for priority, count in sorted(by_priority.items()):
                    display_lines.append(f"| {priority} | {count} |")
                display_lines.append("")

            if bugs_table:
                display_lines.extend(
                    [
                        "### Open Blockers",
                        "| Key | Summary | Priority | Assignee | Status |",
                        "|-----|---------|----------|----------|--------|",
                    ]
                )
                for bug in bugs_table[:15]:
                    display_lines.append(
                        f"| {bug['key']} | {bug['summary']} | {bug['priority']} | {bug['assignee']} | {bug['status']} |"
                    )
                if len(bugs_table) > 15:
                    display_lines.append(f"\n*... and {len(bugs_table) - 15} more bugs*")
            else:
                display_lines.append("### ✅ No Critical Blockers!")
                display_lines.append("No blocker or critical priority items found.")

            return {
                "release": release,
                "total_count": total,
                "showing": len(bugs_table),
                "by_priority": by_priority,
                "by_status": by_status,
                "top_assignees": [{"name": a[0], "count": a[1]} for a in top_assignees],
                "bugs": bugs_table,
                "message": f"Found {total} critical/blocker bugs for {release}",
                "display": "\n".join(display_lines),
            }

        return {
            "release": release,
            "total_count": 0,
            "bugs": [],
            "error": f"Backend API returned {response.status_code}",
            "display": f"## Error\n\nBackend API returned {response.status_code} for {release}",
        }


@mcp.tool()
async def jira_get_regression_bugs(
    project_key: str = "ENG", fix_version: str = None, max_results: int = 100
) -> Dict[str, Any]:
    """
    Get regression bugs - issues caused by recent code changes.

    Use this tool when the user asks about:
    - "regression bugs" or "regressions"
    - "bugs caused by recent changes"
    - "what regressions do we have for R135?"
    - "show regression issues"

    Version extraction: "R135" → fix_version="135.0"

    Args:
        project_key: JIRA project key (default "ENG")
        fix_version: Optional fix version filter (e.g., "135.0" from R135)
        max_results: Maximum bugs to return (default 100)

    Returns:
        Dict with regression bugs list and count
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            params = {"project_key": project_key}
            if fix_version:
                params["fix_version"] = fix_version

            response = await client.get(f"{api_base}/api/jira/bugs/regression", params=params)
            if response.status_code == 200:
                data = response.json()
                bugs = data.get("regression_bugs", [])[:max_results]
                return {"count": len(bugs), "regression_bugs": bugs}
            return {"count": 0, "regression_bugs": [], "error": f"Backend returned {response.status_code}"}
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"count": 0, "regression_bugs": [], "error": str(err)}


@mcp.tool()
async def jira_get_escalations_summary(release: str = "R135") -> Dict[str, Any]:
    """
    Get customer escalations summary - issues raised by customers (EHF/IMF).

    Use this tool when the user asks about:
    - "escalations" or "customer escalations"
    - "show escalations summary" or "escalation status"
    - "how many escalations do we have?"
    - "EHF" or "IMF" escalations

    Args:
        release: Release version (e.g., "R135")

    Returns:
        Summary of customer escalations
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize release format
    if release and not release.upper().startswith("R"):
        release = f"R{release.split('.')[0]}"
    else:
        release = release.upper() if release else "R135"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        # Try the release-data endpoint to get blockers which may include escalations
        url = f"{api_base}/api/jira/release-data/blockers"
        response = await client.get(url, params={"release": release})

        if response.status_code == 200:
            data = response.json()
            blockers = data.get("blockers", [])

            # Filter for escalation-related items (if any have escalation labels)
            escalations = [
                b
                for b in blockers
                if any(label in str(b.get("labels", [])).lower() for label in ["escalat", "ehf", "imf", "customer"])
            ]

            if escalations:
                lines = [
                    f"## 📢 Customer Escalations: {release}",
                    "",
                    f"**Found:** {len(escalations)} escalation(s)",
                    "",
                    "### Escalations",
                    "| Key | Summary | Priority | Status |",
                    "|-----|---------|----------|--------|",
                ]
                for esc in escalations[:10]:
                    summary = (
                        esc.get("summary", "")[:40] + "..."
                        if len(esc.get("summary", "")) > 40
                        else esc.get("summary", "")
                    )
                    lines.append(
                        f"| {esc.get('key', '')} | {summary} | {esc.get('priority', 'Unknown')} | {esc.get('status', 'Unknown')} |"
                    )

                return {
                    "release": release,
                    "total": len(escalations),
                    "escalations": escalations[:10],
                    "display": "\n".join(lines),
                }

            # No escalations found - return helpful message
            display = f"""## 📢 Customer Escalations: {release}

**No escalations found** for this release.

This is good news - no customer-reported critical issues requiring escalation.

*Note: Escalations are typically labeled with 'escalated', 'EHF', or 'IMF' in JIRA.*"""

            return {
                "release": release,
                "total": 0,
                "escalations": [],
                "message": "No escalations found",
                "display": display,
            }

        # Endpoint failed
        return {
            "release": release,
            "total": 0,
            "by_status": {},
            "by_priority": {},
            "escalations": [],
            "error": f"Backend returned {response.status_code}",
        }


@mcp.tool()
async def jira_get_customer_bugs(  # pylint: disable=too-many-nested-blocks
    project_key: str = "ENG", release_version: str = "", max_bugs: int = 100
) -> Dict[str, Any]:
    """
    Get customer-escalated bugs (issues labeled as jira_escalated).

    Use this tool when the user asks about:
    - "customer bugs" or "customer reported bugs"
    - "escalated bugs" or "bugs from customers"
    - "customer bugs for R135" or "customer issues in release 135"
    - "how many customer bugs do we have?"

    Version extraction: "R135" → release_version="135"

    Args:
        project_key: JIRA project key (default "ENG")
        release_version: Filter by release version (e.g., "135" from R135)
        max_bugs: Maximum bugs to return (default 100)

    Returns:
        Dict with customer bugs list and count
    """
    # Call backend API - use search with JQL for customer bugs
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Build JQL for customer escalated bugs
            jql = f"project = {project_key} AND issuetype = Bug AND labels = jira_escalated ORDER BY created DESC"
            params = {"jql": jql, "max_results": max_bugs}

            response = await client.get(f"{api_base}/api/jira/search", params=params)
            if response.status_code == 200:
                data = response.json()
                bugs = data.get("issues", [])

                # Filter by version if specified
                if release_version and release_version.strip():
                    pattern = f"^{release_version}"
                    filtered = []
                    for bug in bugs:
                        for version in bug.get("affects_versions", []):
                            if re.match(pattern, version):
                                filtered.append(bug)
                                break
                    bugs = filtered

                return {"count": len(bugs), "bugs": bugs[:max_bugs]}
            return {"count": 0, "bugs": [], "error": f"Backend returned {response.status_code}"}
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"count": 0, "bugs": [], "error": str(err)}


@mcp.tool()
async def jira_get_bugs_by_classification(  # pylint: disable=too-many-locals,too-many-nested-blocks
    project_key: str = "ENG", release_version: str = ""
) -> Dict[str, Any]:
    """
    Get customer bugs classified by type: Regressions, Features, Others.

    Use this tool when the user asks about:
    - "bug classification" or "bugs by type"
    - "how many regressions vs features?"
    - "bug breakdown by classification"
    - "categorize bugs for R135"

    Classification types:
    - Regressions: Issues caused by recent code changes
    - Features: New functionality issues/requests
    - Others: Infrastructure, documentation, etc.

    Version extraction: "R135" → release_version="135"

    Args:
        project_key: JIRA project key (default "ENG")
        release_version: Filter by release version (e.g., "135" from R135)

    Returns:
        Classification breakdown with counts by type and status
    """
    # Call backend API to get customer bugs, then classify
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            jql = f"project = {project_key} AND issuetype = Bug AND labels = jira_escalated ORDER BY created DESC"
            response = await client.get(f"{api_base}/api/jira/search", params={"jql": jql, "max_results": 200})

            if response.status_code != 200:
                return {"total": 0, "error": f"Backend returned {response.status_code}"}

            data = response.json()
            all_bugs = data.get("issues", [])

            # Filter by version if specified
            if release_version and release_version.strip():
                pattern = f"^{release_version}"
                filtered = []
                for bug in all_bugs:
                    for version in bug.get("affects_versions", []):
                        if re.match(pattern, version):
                            filtered.append(bug)
                            break
                all_bugs = filtered

            # Classify bugs
            regressions = []
            features = []
            others = []

            for bug in all_bugs:
                classification = bug.get("bug_classification") or ""
                if classification in REGRESSION_CLASSIFICATION_VALUES:
                    regressions.append(bug)
                elif classification in FEATURE_CLASSIFICATION_VALUES:
                    features.append(bug)
                else:
                    others.append(bug)

            # Count by status
            open_bugs = [b for b in all_bugs if b.get("status") in OPEN_STATUSES]
            resolved_bugs = [b for b in all_bugs if b.get("status") in RESOLVED_STATUSES]
            closed_bugs = [b for b in all_bugs if b.get("status") in CLOSED_STATUSES]

            return {
                "total": len(all_bugs),
                "total_open": len(open_bugs),
                "total_resolved": len(resolved_bugs),
                "total_closed": len(closed_bugs),
                "total_completed": len(resolved_bugs) + len(closed_bugs),
                "regressions": {
                    "total": len(regressions),
                    "open": len([b for b in regressions if b.get("status") in OPEN_STATUSES]),
                    "bugs": regressions[:20],
                },
                "features": {
                    "total": len(features),
                    "open": len([b for b in features if b.get("status") in OPEN_STATUSES]),
                    "bugs": features[:20],
                },
                "others": {
                    "total": len(others),
                    "open": len([b for b in others if b.get("status") in OPEN_STATUSES]),
                    "bugs": others[:20],
                },
                "all_bugs": all_bugs[:50],
                "open_bugs": open_bugs[:30],
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"total": 0, "error": str(err)}


@mcp.tool()
async def jira_get_release_comparison(  # pylint: disable=too-many-locals
    releases: List[str], project_key: str = "ENG"
) -> Dict[str, Any]:
    """
    Compare customer bugs across multiple releases - trend analysis.

    Use this tool when the user asks about:
    - "compare releases" or "release comparison"
    - "bugs trend across R133, R134, R135"
    - "how does R135 compare to R134?"
    - "release over release bug trend"
    - "are we getting better or worse?"

    Version extraction: "R133, R134, R135" → releases=["133", "134", "135"]

    Args:
        releases: List of release versions to compare (e.g., ["133", "134", "135"])
        project_key: JIRA project key (default "ENG")

    Returns:
        Comparison data with counts per release and trend analysis
    """
    # Call backend API to get customer bugs
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            jql = f"project = {project_key} AND issuetype = Bug AND labels = jira_escalated ORDER BY created DESC"
            response = await client.get(f"{api_base}/api/jira/search", params={"jql": jql, "max_results": 200})

            if response.status_code != 200:
                return {"releases": {}, "error": f"Backend returned {response.status_code}"}

            data = response.json()
            all_bugs = data.get("issues", [])

            comparison = {}
            for release in releases:
                pattern = f"^{release}"
                release_bugs = []
                for bug in all_bugs:
                    for version in bug.get("affects_versions", []):
                        if re.match(pattern, version):
                            release_bugs.append(bug)
                            break

                open_bugs = [b for b in release_bugs if b.get("status") in OPEN_STATUSES]
                regressions = [
                    b for b in release_bugs if b.get("bug_classification") in REGRESSION_CLASSIFICATION_VALUES
                ]
                features = [b for b in release_bugs if b.get("bug_classification") in FEATURE_CLASSIFICATION_VALUES]
                others = [b for b in release_bugs if b not in regressions and b not in features]

                comparison[release] = {
                    "total": len(release_bugs),
                    "open": len(open_bugs),
                    "regressions": len(regressions),
                    "features": len(features),
                    "others": len(others),
                }

            # Trend analysis
            trend_analysis = {"status": "insufficient_data", "message": "Need at least 2 releases"}
            if len(releases) >= 2:
                current = releases[-1]
                previous = releases[-2]
                current_data = comparison.get(current, {})
                previous_data = comparison.get(previous, {})

                regression_change = current_data.get("regressions", 0) - previous_data.get("regressions", 0)
                current_total = current_data.get("open", 1) or 1
                regression_ratio = (current_data.get("regressions", 0) / current_total) * 100

                if regression_change > 5 or regression_ratio > 50:
                    health = "poor"
                    message = "⚠️ High regression rate detected"
                elif regression_change > 0:
                    health = "fair"
                    message = "📈 Slight increase in regressions"
                else:
                    health = "good"
                    message = "✅ Regression rate stable or improving"

                trend_analysis = {
                    "status": health,
                    "message": message,
                    "regression_change": regression_change,
                    "regression_ratio": round(regression_ratio, 1),
                }

            return {"releases": comparison, "trend_analysis": trend_analysis}
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"releases": {}, "error": str(err)}


@mcp.tool()
# pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
async def jira_get_customer_escalations(
    project_key: str = "Engineering", release_version: str = "", open_only: bool = True
) -> Dict[str, Any]:
    """
    Get detailed customer escalations with aging analysis.

    Use this tool when the user asks about:
    - "customer escalations details" or "escalation aging"
    - "how old are our escalations?" or "aging report"
    - "escalations for R135" or "release 135 escalations"
    - "open customer escalations breakdown"

    Version extraction: "R135" → release_version="135"

    Args:
        project_key: JIRA project key (default "Engineering")
        release_version: Filter by release version (e.g., "135" from R135)
        open_only: Only return open escalations (default True)

    Returns:
        Escalation breakdown with aging analysis (0-30, 31-60, 61-90, 90+ days)
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            params = {"project_key": project_key}
            if open_only:
                params["open_only"] = "true"

            response = await client.get(f"{api_base}/api/jira/customer-escalations", params=params)

            if response.status_code != 200:
                return {"total": 0, "error": f"Backend returned {response.status_code}"}

            data = response.json()
            all_escalations = data.get("escalations", [])

            # Filter by version if specified
            if release_version and release_version.strip():
                pattern = f"^{release_version}"
                filtered = []
                for esc in all_escalations:
                    affects = esc.get("affects_versions", [])
                    if not affects:
                        filtered.append(esc)
                    else:
                        for version in affects:
                            if re.match(pattern, version):
                                filtered.append(esc)
                                break
                all_escalations = filtered

            # Calculate aging
            now = datetime.now()
            aging_counts = {"0_30_days": 0, "31_60_days": 0, "61_90_days": 0, "90_plus_days": 0}

            open_statuses = (
                ESCALATION_STATUS_CATEGORIES["open"]
                + ESCALATION_STATUS_CATEGORIES["in_progress"]
                + ESCALATION_STATUS_CATEGORIES["more_info"]
                + ESCALATION_STATUS_CATEGORIES["pending_resolution"]
            )

            for esc in all_escalations:
                status = esc.get("status", "")
                if status in open_statuses:
                    created_str = esc.get("created", "")
                    if created_str:
                        try:
                            created_date = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                            if created_date.tzinfo:
                                created_date = created_date.replace(tzinfo=None)
                            age_days = (now - created_date).days
                            esc["age_days"] = age_days

                            if age_days <= 30:
                                aging_counts["0_30_days"] += 1
                            elif age_days <= 60:
                                aging_counts["31_60_days"] += 1
                            elif age_days <= 90:
                                aging_counts["61_90_days"] += 1
                            else:
                                aging_counts["90_plus_days"] += 1
                        except (ValueError, TypeError):
                            pass

            # Status counts
            status_counts = {cat: 0 for cat in ESCALATION_STATUS_CATEGORIES}
            for esc in all_escalations:
                status = esc.get("status", "")
                for category, statuses in ESCALATION_STATUS_CATEGORIES.items():
                    if status in statuses:
                        status_counts[category] += 1
                        break

            open_count = sum(status_counts[k] for k in ["open", "in_progress", "more_info", "pending_resolution"])

            return {
                "total": len(all_escalations),
                "total_open": open_count,
                "total_completed": status_counts["resolved"] + status_counts["closed"],
                "by_status_category": status_counts,
                "aging": {"counts": aging_counts, "total_open_analyzed": sum(aging_counts.values())},
                "all_escalations": all_escalations[:50],
                "source": "backend-api",
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"total": 0, "error": str(err)}


@mcp.tool()
async def jira_get_resiliency_trend(months: int = 6) -> Dict[str, Any]:
    """
    Get NS Client resiliency dashboard trend data over time.

    Use this tool when the user asks about:
    - "resiliency trend" or "resiliency dashboard"
    - "ticket trend over time" or "monthly ticket stats"
    - "created vs resolved trend"
    - "are we improving on resiliency?"
    - "resolution rate trend"

    Args:
        months: Number of months to analyze (default 6)

    Returns:
        Trend data with created/resolved counts per month and resolution rate
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jira/resiliency-dashboard")

            if response.status_code != 200:
                return {"months_analyzed": months, "error": f"Backend returned {response.status_code}"}

            data = response.json()

            # Extract trend data from resiliency dashboard response
            ticket_trend = data.get("ticketTrend", [])

            # Limit to requested months
            if len(ticket_trend) > months:
                ticket_trend = ticket_trend[-months:]

            total_created = sum(d.get("created", 0) for d in ticket_trend)
            total_resolved = sum(d.get("resolved", 0) for d in ticket_trend)

            return {
                "months_analyzed": len(ticket_trend),
                "total_created": total_created,
                "total_resolved": total_resolved,
                "resolution_rate": round((total_resolved / total_created * 100), 1) if total_created > 0 else 0,
                "ticket_trend": ticket_trend,
                "source": "backend-api",
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"months_analyzed": months, "error": str(err)}


# =============================================================================
# Release Readiness Tools (Dashboard-specific)
# =============================================================================


@mcp.tool()
async def jira_get_release_readiness_score(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    project_key: str = "ENG",  # pylint: disable=unused-argument
    fix_version: str = "134.0.0",
    component: Optional[str] = "YOUR_PRODUCT",
) -> Dict[str, Any]:
    """
    THE TOOL FOR "GREEN/RED/YELLOW" QUESTIONS - Release Readiness Score (RRS).

    *** USE THIS TOOL WHEN USER ASKS: ***
    - "is R135 green?" ← THIS TOOL!
    - "is R134 red?" ← THIS TOOL!
    - "release status" or "release readiness" ← THIS TOOL!
    - "are we ready to release?" ← THIS TOOL!
    - "what's the release score?" ← THIS TOOL!

    *** DO NOT USE THIS FOR: ***
    - "IRR status" → use jira_get_milestone_status instead
    - "branch cut status" → use jira_get_milestone_status instead

    Score interpretation:
    - Green: ≥80% (ready to release)
    - Yellow: 70-79% (needs attention)
    - Red: <70% (not ready)

    Version extraction: "R135" → fix_version="135.0"

    Args:
        project_key: JIRA project key (default "ENG")
        fix_version: Version like "135.0" (extract from R135, R134, etc.)
        component: Component filter - defaults to "YOUR_PRODUCT" (dashboard focus)

    Returns:
        RRS score percentage with color status for the specified component
    """
    # Call backend API for consistent data
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Convert fix_version to release format (134.0 -> R134)
    # Handle None, "None", empty string passed by LLM
    if fix_version and fix_version not in ("None", "null", ""):
        version_num = fix_version.split(".")[0]
        # Remove 'R' prefix if it exists to avoid RR134
        version_num = version_num.replace("R", "")
        release = f"R{version_num}"
    else:
        release = DEFAULT_RELEASE

    # Default to YOUR_PRODUCT if not specified (dashboard focus)
    target_component = component if component and component not in ("None", "null", "") else "YOUR_PRODUCT"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        url = f"{api_base}/api/jira/release-readiness"
        params = {"release": release}

        response = await client.get(url, params=params)

        if response.status_code != 200:
            return {
                "error": f"Backend API returned {response.status_code}",
                "release": release,
                "rrs_score": 0,
                "status": "unknown",
                "status_emoji": "❓",
            }

        data = response.json()

        # Get component data - filter to target component only
        components_data = data.get("componentsData", {})
        comp_data = components_data.get(target_component, {})
        comp_summary = comp_data.get("summary", {})

        # Calculate counts for the target component only
        open_stories = comp_summary.get("bc_stories", 0)
        open_bugs = comp_summary.get("bc_bugs", 0)
        open_count = open_stories + open_bugs

        # Calculate RRS: 100 - (open_items * 3), capped at 0-100
        rrs_score = max(0, min(100, 100 - (open_count * 3)))

        # Determine status color (80% threshold for green)
        if rrs_score >= 80:
            status = "green"
            emoji = "🟢"
        elif rrs_score >= 70:
            status = "yellow"
            emoji = "🟡"
        else:
            status = "red"
            emoji = "🔴"

        # Get assignees for the target component only
        comp_issues = comp_data.get("issues", [])
        assignee_counts = {}
        for issue in comp_issues:
            assignee = issue.get("assignee") or "Unassigned"
            assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
        top_assignees = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Get timeline and phase info from releaseSummary
        release_summary = data.get("releaseSummary", {})
        timeline = data.get("timeline", {})

        # Items needed to reach green (≥80% means ≤6 open items)
        items_to_green = max(0, open_count - 6) if rrs_score < 80 else 0

        # Build formatted display for AI Assistant - filtered to target component
        phase_name = release_summary.get("phaseName", "Unknown")
        days_remaining = release_summary.get("daysRemaining", 0)
        display_lines = [
            f"## {emoji} Release {release} Status ({target_component}): **{status.upper()}** ({rrs_score}%)",
            "",
            f"**Phase:** {phase_name} | **Days Remaining:** {days_remaining}",
            "",
            f"### {target_component} Open Items",
            "",
            "| Category | Count |",
            "|----------|-------|",
            f"| 🐛 Open Bugs | {open_bugs} |",
            f"| 📋 Open Stories | {open_stories} |",
            f"| **Total Open** | **{open_count}** |",
            "",
        ]

        # Add top assignees if available
        if top_assignees:
            display_lines.extend(
                [
                    "### Top Assignees (Open Items)",
                    "",
                ]
            )
            for assignee, count in top_assignees[:5]:
                display_lines.append(f"- **{assignee}**: {count} items")
            display_lines.append("")

        # Add recommendation
        if items_to_green > 0:
            display_lines.append("### ⚠️ Action Required")
            display_lines.append(f"Close **{items_to_green}** more items to reach 🟢 GREEN status.")
        else:
            display_lines.append("### ✅ Release Ready!")
            display_lines.append("All criteria met for release.")

        return {
            "release": release,
            "fix_version": fix_version,
            "component": target_component,
            "rrs_score": rrs_score,
            "status": status,
            "status_emoji": emoji,
            "open_bugs": open_bugs,
            "open_stories": open_stories,
            "open_items": open_count,
            "items_to_green": items_to_green,
            "top_assignees": [{"name": a[0], "open": a[1]} for a in top_assignees],
            "phase": release_summary.get("phase", ""),
            "phase_name": release_summary.get("phaseName", ""),
            "days_remaining": release_summary.get("daysRemaining", 0),
            "dates": {
                "irr": timeline.get("irr_date", ""),
                "branch_cut": timeline.get("branch_cut_date", ""),
                "final_build": timeline.get("final_build_date", ""),
            },
            "formula": "100 - (open_items × 3%)",
            "thresholds": {"green": "≥80%", "yellow": "70-79%", "red": "<70%"},
            "recommendation": (
                f"Close {items_to_green} more items to reach green." if items_to_green > 0 else "Release is ready!"
            ),
            "display": "\n".join(display_lines),
        }


@mcp.tool()
async def jira_get_milestone_status(  # pylint: disable=too-many-locals,too-many-statements
    project_key: str = "ENG",  # pylint: disable=unused-argument
    fix_version: str = "134.0.0",
    milestone: str = "IRR",
    component: Optional[str] = None,
) -> Dict[str, Any]:
    """
    THE TOOL FOR "IRR/MILESTONE" QUESTIONS - Milestone completion status.

    *** USE THIS TOOL WHEN USER ASKS: ***
    - "IRR status" or "whats IRR?" ← THIS TOOL!
    - "branch cut status" ← THIS TOOL with milestone="BranchCut"
    - "final build status" ← THIS TOOL with milestone="FinalBuild"
    - "milestone progress" ← THIS TOOL!

    *** DO NOT USE THIS FOR: ***
    - "is R135 green?" → use jira_get_release_readiness_score instead
    - "release status" → use jira_get_release_readiness_score instead
    - "are we ready to release?" → use jira_get_release_readiness_score instead

    Available milestones: "IRR", "BranchCut", "FinalBuild"

    Version extraction: "R135" → fix_version="135.0"

    Args:
        project_key: JIRA project key (default "ENG")
        fix_version: Version like "135.0" (extract from R135, R134, etc.)
        milestone: Which milestone - "IRR", "BranchCut", or "FinalBuild"
        component: Optional component filter (e.g., "YOUR_PRODUCT")

    Returns:
        Milestone status with on-time/late/open counts and completion percentage
    """
    # Call backend API (which has JIRA credentials configured)
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    # Handle None, "None", empty string, or missing fix_version
    if fix_version and fix_version not in ("None", "null", ""):
        version_num = fix_version.split(".")[0]
        # Remove 'R' prefix if it exists to avoid RR134
        version_num = version_num.replace("R", "")
        release = f"R{version_num}"
    else:
        release = DEFAULT_RELEASE

    # Map milestone to endpoint
    milestone_endpoints = {
        "IRR": "irr",
        "irr": "irr",
        "BranchCut": "branch-cut",
        "branchcut": "branch-cut",
        "branch_cut": "branch-cut",
        "FinalBuild": "final-build",
        "finalbuild": "final-build",
        "final_build": "final-build",
    }

    endpoint = milestone_endpoints.get(milestone, "irr")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        url = f"{api_base}/api/jira/milestone/{endpoint}"
        params = {"release": release}
        if component:
            params["component"] = component

        try:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                return {
                    "error": f"Backend API returned {response.status_code}",
                    "milestone": milestone,
                    "status": "unknown",
                    "status_emoji": "❓",
                }

            data = response.json()

            # Extract key metrics from backend response structure
            summary = data.get("summary", {})
            resolved_on_time = summary.get("resolvedOnTime", 0)
            resolved_late = summary.get("resolvedAfterDeadline", 0)
            still_open = summary.get("stillOpen", 0)
            total = summary.get("totalStories", resolved_on_time + resolved_late + still_open)
            on_time_rate = summary.get("onTimePercentage", 0)

            # Determine status
            if still_open == 0:
                status = "green"
                emoji = "🟢"
            elif on_time_rate >= 80:
                status = "yellow"
                emoji = "🟡"
            else:
                status = "red"
                emoji = "🔴"

            # Format open issues for table display
            open_issues = data.get("open_issues", [])[:15]
            open_table = []
            for issue in open_issues:
                summary = issue.get("summary", "")
                if len(summary) > 50:
                    summary = summary[:50] + "..."
                open_table.append(
                    {
                        "key": issue.get("key", ""),
                        "summary": summary,
                        "priority": issue.get("priority", ""),
                        "assignee": issue.get("assignee", "Unassigned"),
                        "status": issue.get("status", ""),
                    }
                )

            # Create formatted display text for direct output
            milestone_date_str = data.get("milestoneDate", "")
            deadline_status = "Passed" if data.get("deadlinePassed") else "Upcoming"
            component_str = f" for {component}" if component else ""
            requirement = data.get("requirement", "All stories should be RESOLVED")

            display_lines = [
                f"## {emoji} {milestone} Status{component_str}: {status.upper()} ({on_time_rate:.1f}% On-Time)",
                "",
                f"**Release:** {release} | **Deadline:** {milestone_date_str} ({deadline_status})",
                f"**Requirement:** {requirement}",
                "",
                "### 📊 Resolution Breakdown",
                "",
                "| Status | Stories | % |",
                "|--------|---------|---|",
            ]

            # Add resolution breakdown rows
            if total > 0:
                on_time_pct = resolved_on_time / total * 100
                late_pct = resolved_late / total * 100
                open_pct = still_open / total * 100
                display_lines.append(f"| ✅ Resolved On-Time | {resolved_on_time} | {on_time_pct:.1f}% |")
                display_lines.append(f"| ⚠️ Resolved Late | {resolved_late} | {late_pct:.1f}% |")
                display_lines.append(f"| ❌ Still Open | {still_open} | {open_pct:.1f}% |")
            else:
                display_lines.append("| ✅ Resolved On-Time | 0 | 0% |")
                display_lines.append("| ⚠️ Resolved Late | 0 | 0% |")
                display_lines.append("| ❌ Still Open | 0 | 0% |")

            display_lines.extend(
                [
                    f"| **Total Stories** | **{total}** | 100% |",
                    "",
                ]
            )

            # Add assessment
            display_lines.append("### Assessment")
            display_lines.append("")
            if still_open > 0:
                display_lines.append(f"🔴 **Action Required:** {still_open} story/stories still need resolution.")
                display_lines.append(f"- Stories pending resolution: {still_open}")
            elif resolved_late > 0:
                display_lines.append(f"🟡 **Recovered:** All resolved. {resolved_late} completed after deadline.")
            else:
                display_lines.append(f"🟢 **Excellent!** All {total} stories were resolved on time.")

            return {
                "milestone": milestone,
                "milestone_name": data.get("milestoneName", milestone),
                "release": release,
                "fix_version": fix_version,
                "milestone_date": milestone_date_str,
                "deadline_passed": data.get("deadlinePassed", False),
                "days_to_deadline": data.get("daysToDeadline"),
                "days_since_deadline": data.get("daysSinceDeadline"),
                "status": status,
                "status_emoji": emoji,
                "on_time_rate": on_time_rate,
                "total_items": total,
                "resolved_on_time": resolved_on_time,
                "resolved_late": resolved_late,
                "still_open": still_open,
                "by_component": data.get("by_component", {}),
                "by_assignee": data.get("by_assignee", {}),
                "open_issues": open_table,
                "message": (
                    f"{milestone} is {status.upper()} with {on_time_rate}% on-time. " f"{still_open} items open."
                ),
                "display": "\n".join(display_lines),
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {
                "error": f"Failed to fetch milestone data: {str(err)}",
                "milestone": milestone,
                "status": "unknown",
                "status_emoji": "❓",
            }


@mcp.tool()
async def jira_get_moreinfo_items(project_key: str = "ENG", fix_version: str = "134.0.0") -> Dict[str, Any]:
    """
    Get bugs/items in "More Info" or "Needs Info" status - waiting for additional information.

    Use this tool when the user asks about:
    - "bugs with More Info" or "More Info bugs"
    - "items needing more information"
    - "bugs waiting for info" or "needs info bugs"
    - "stuck items" or "blocked items needing info"
    - "do we have any bugs with More Info for R135?"

    Version extraction: "R135" → fix_version="135.0"

    Args:
        project_key: JIRA project key (default "ENG")
        fix_version: Fix version like "135.0" (extract number from R135, R134, etc.)

    Returns:
        List of items in MoreInfo/Needs Info status with reporters and assignees
    """
    # Call backend API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Extract release from fix_version
    version_num = fix_version.split(".")[0] if fix_version else "135"
    version_num = version_num.replace("R", "")
    release = f"R{version_num}"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Use release-data/by-status endpoint
            response = await client.get(f"{api_base}/api/jira/release-data/by-status", params={"release": release})

            if response.status_code != 200:
                return {"release": release, "total": 0, "error": f"Backend returned {response.status_code}"}

            data = response.json()

            # Filter for More Info status items
            more_info_statuses = ["More Info", "Needs Info", "Waiting for Info", "Need More Information"]
            status_groups = data.get("statuses", [])

            items = []
            for group in status_groups:
                status_name = group.get("status", "")
                if status_name in more_info_statuses:
                    items.extend(group.get("items", []))

            # Build display
            display_lines = [
                f"## 📋 Items Needing More Info for {release}",
                "",
                f"**Total:** {len(items)}",
                "",
            ]

            if items:
                display_lines.extend(
                    [
                        "| Key | Summary | Assignee | Status |",
                        "|-----|---------|----------|--------|",
                    ]
                )
                for item in items[:20]:
                    summary = item.get("summary", "")[:40]
                    display_lines.append(
                        f"| {item.get('key', '')} | {summary} | {item.get('assignee', 'Unassigned')} | {item.get('status', '')} |"
                    )
                if len(items) > 20:
                    display_lines.append(f"\n*... and {len(items) - 20} more items*")
            else:
                display_lines.extend(
                    [
                        "### ✅ No Items Needing More Info",
                        "",
                        "All items have the information they need to proceed.",
                    ]
                )

            return {
                "release": release,
                "total": len(items),
                "items": [
                    {
                        "key": item.get("key"),
                        "summary": item.get("summary", "")[:60],
                        "assignee": item.get("assignee"),
                        "status": item.get("status"),
                        "type": item.get("type"),
                    }
                    for item in items[:30]
                ],
                "source": "backend-api",
                "display": "\n".join(display_lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"release": release, "total": 0, "error": str(err), "display": f"**Error:** {err}"}


@mcp.tool()
async def jira_get_action_items_by_assignee(  # pylint: disable=too-many-locals
    fix_version: str = "135.0.0", component: str = "YOUR_PRODUCT"
) -> Dict[str, Any]:
    """
    Get open action items (bugs, tasks) grouped by assignee - shows who owns what work.

    Use this tool when the user asks about:
    - "action items for R135" or "what are the action items?"
    - "open items for release" or "pending work items"
    - "who has work assigned?" or "assignee workload"
    - "who has the most open items?"

    Version extraction: "R135" → fix_version="135.0.0"

    Args:
        fix_version: Fix version like "135.0.0" (extract number from R135 and add .0.0)
        component: Component filter (default "YOUR_PRODUCT")

    Returns:
        Open items grouped by assignee with counts
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Extract release number (R135 -> R135, 135.0.0 -> R135)
    if fix_version.upper().startswith("R"):
        release = fix_version.upper()
    else:
        release_num = fix_version.split(".")[0]
        release = f"R{release_num}"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Use the correct backend endpoint
            url = f"{api_base}/api/jira/release-data/by-assignee"
            response = await client.get(url, params={"release": release})

            if response.status_code != 200:
                err_msg = f"Backend returned {response.status_code}"
                return {
                    "fix_version": fix_version,
                    "total_open": 0,
                    "error": err_msg,
                    "display": f"**Error:** {err_msg}",
                }

            data = response.json()
            assignees = data.get("assignees", [])

            # Filter by component if specified and data has component info
            # Build display
            total_items = sum(a.get("total", 0) for a in assignees)

            lines = [
                f"## 📋 Action Items by Assignee: {release}",
                "",
                f"**Total Open Items:** {total_items}",
                f"**Total Assignees:** {len(assignees)}",
                "",
                "### Top Assignees",
                "",
            ]

            # Show top 10 assignees
            for assignee_data in assignees[:10]:
                name = assignee_data.get("assignee", "Unknown")
                count = assignee_data.get("total", 0)
                bugs = assignee_data.get("bugs", 0)
                stories = assignee_data.get("stories", 0)
                lines.append(f"- **{name}**: {count} items ({bugs} bugs, {stories} stories)")

            if len(assignees) > 10:
                lines.append(f"\n*...and {len(assignees) - 10} more assignees*")

            return {
                "release": release,
                "fix_version": fix_version,
                "total_open": total_items,
                "total_assignees": len(assignees),
                "by_assignee": assignees[:15],
                "source": "backend-api",
                "display": "\n".join(lines),
            }
        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {
                "fix_version": fix_version,
                "total_open": 0,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def jira_get_issue(issue_key: str) -> Dict[str, Any]:
    """
    Get details of a specific JIRA issue by its key.

    Use this tool when the user asks about:
    - "what is ENG-123456?"
    - "who is the assignee for ENG-123456?"
    - "show me issue ENG-123456"
    - "details of ENG-123456"
    - Any question about a specific JIRA ticket

    Args:
        issue_key: JIRA issue key (e.g., "ENG-779012", "ENG-123456")

    Returns:
        Issue details including summary, status, assignee, priority, etc.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize issue key (ensure uppercase)
    issue_key = issue_key.upper().strip()

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            url = f"{api_base}/api/jira/issue/{issue_key}"
            response = await client.get(url)

            if response.status_code == 404:
                return {
                    "issue_key": issue_key,
                    "error": f"Issue {issue_key} not found",
                    "display": f"**Error:** Issue {issue_key} not found in JIRA.",
                }

            if response.status_code != 200:
                return {
                    "issue_key": issue_key,
                    "error": f"Backend returned {response.status_code}",
                    "display": f"**Error:** Failed to fetch issue {issue_key}.",
                }

            data = response.json()
            issue = data.get("issue", {})

            # Extract issue details
            summary = issue.get("summary", "N/A")
            status = issue.get("status", "Unknown")
            assignee = issue.get("assignee", "Unassigned")
            priority = issue.get("priority", "Unknown")
            issue_type = issue.get("issuetype", "Unknown")
            fix_versions = issue.get("fixVersions", [])
            components = issue.get("components", [])
            created = issue.get("created", "")[:10] if issue.get("created") else "N/A"
            updated = issue.get("updated", "")[:10] if issue.get("updated") else "N/A"
            resolution = issue.get("resolution") or "Unresolved"

            # Build display
            lines = [
                f"## 🎫 {issue_key}: {summary}",
                "",
                "| Field | Value |",
                "|-------|-------|",
                f"| **Type** | {issue_type} |",
                f"| **Status** | {status} |",
                f"| **Priority** | {priority} |",
                f"| **Assignee** | {assignee} |",
                f"| **Resolution** | {resolution} |",
                f"| **Created** | {created} |",
                f"| **Updated** | {updated} |",
            ]

            if fix_versions:
                lines.append(f"| **Fix Version(s)** | {', '.join(fix_versions)} |")
            if components:
                lines.append(f"| **Component(s)** | {', '.join(components)} |")

            lines.extend(
                [
                    "",
                    f"🔗 [View in JIRA](https://your-org.atlassian.net/browse/{issue_key})",
                ]
            )

            return {
                "issue_key": issue_key,
                "summary": summary,
                "status": status,
                "assignee": assignee,
                "priority": priority,
                "type": issue_type,
                "resolution": resolution,
                "fix_versions": fix_versions,
                "components": components,
                "created": created,
                "updated": updated,
                "display": "\n".join(lines),
            }

        except Exception as err:
            return {
                "issue_key": issue_key,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def jira_get_release_overview(release: str = "R135") -> Dict[str, Any]:
    """
    Get comprehensive release overview - aggregates data from multiple sources.

    Use this tool when the user asks about:
    - "release overview" or "full release status"
    - "give me everything about R135"
    - "release summary" or "release dashboard"
    - "what's the state of the release?"

    This is a COMPOSITE tool that combines:
    - Release readiness score (green/yellow/red)
    - Resolution progress (from IRR till now)
    - Current open bugs and stories
    - Critical blockers
    - Key dates

    Args:
        release: Release ID like "R135"

    Returns:
        Comprehensive release overview with all key metrics
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalize release format
    if release:
        release = release.upper().strip()
        if release.startswith("R"):
            release = release[1:]
        release_num = release.split(".")[0]
        release = f"R{release_num}"
    else:
        release = "R135"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Fetch data from multiple endpoints in parallel
            import asyncio

            results = await asyncio.gather(
                client.get(f"{api_base}/api/jira/release-readiness", params={"release": release}),
                client.get(f"{api_base}/api/jira/resolution-progress", params={"release": release}),
                client.get(f"{api_base}/api/jira/release-data/blockers", params={"release": release}),
                client.get(f"{api_base}/api/release-calendar/releases/{release}"),
                return_exceptions=True,
            )

            # Parse responses
            readiness_data = {}
            progress_data = {}
            blockers_data = {}
            calendar_data = {}

            if not isinstance(results[0], Exception) and results[0].status_code == 200:
                readiness_data = results[0].json()
            if not isinstance(results[1], Exception) and results[1].status_code == 200:
                progress_data = results[1].json()
            if not isinstance(results[2], Exception) and results[2].status_code == 200:
                blockers_data = results[2].json()
            if not isinstance(results[3], Exception) and results[3].status_code == 200:
                calendar_data = results[3].json()

            # Extract key metrics
            # From release-readiness
            components_data = readiness_data.get("componentsData", {})
            product_data = components_data.get("YOUR_PRODUCT", {})
            product_summary = product_data.get("summary", {})
            open_bugs = product_summary.get("bc_bugs", 0)
            open_stories = product_summary.get("bc_stories", 0)
            total_open = open_bugs + open_stories

            # Calculate RRS
            rrs_score = max(0, min(100, 100 - (total_open * 3)))
            if rrs_score >= 80:
                status = "GREEN"
                emoji = "🟢"
            elif rrs_score >= 70:
                status = "YELLOW"
                emoji = "🟡"
            else:
                status = "RED"
                emoji = "🔴"

            # From resolution-progress
            timeline = progress_data.get("timeline", {})
            summary = progress_data.get("summary", {})
            total_resolved = summary.get("totalResolved", 0)
            resolved_before_irr = summary.get("resolvedBeforeIRR", 0)
            resolved_after_irr = summary.get("resolvedAfterIRR", 0)
            days_remaining = timeline.get("days_remaining", 0)

            # From blockers
            blockers = blockers_data.get("blockers", [])
            blocker_count = len(blockers)

            # From calendar
            release_info = calendar_data.get("release", {})
            milestones = release_info.get("milestones", {})

            # Build comprehensive display
            lines = [
                f"## {emoji} Release Overview: {release}",
                "",
                f"### Status: **{status}** ({rrs_score}%)",
                "",
                "---",
                "",
                "### 📊 Key Metrics",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Open Items | {total_open} ({open_bugs} bugs, {open_stories} stories) |",
                f"| Critical Blockers | {blocker_count} |",
                f"| Total Resolved | {total_resolved} |",
                f"| Resolved Before IRR | {resolved_before_irr} |",
                f"| Resolved After IRR | {resolved_after_irr} |",
                f"| Days to Final Build | {days_remaining} |",
                "",
            ]

            # Add key dates
            if milestones:
                lines.extend(
                    [
                        "### 📅 Key Dates",
                        "",
                    ]
                )
                for milestone_name, milestone_date in milestones.items():
                    if milestone_date:
                        lines.append(f"- **{milestone_name}:** {milestone_date}")
                lines.append("")

            # Add blockers summary if any
            if blockers:
                lines.extend(
                    [
                        "### 🚨 Critical Blockers",
                        "",
                    ]
                )
                for blocker in blockers[:5]:
                    key = blocker.get("key", "")
                    summary_text = blocker.get("summary", "")[:50]
                    assignee = blocker.get("assignee", "Unassigned")
                    lines.append(f"- **{key}**: {summary_text}... ({assignee})")
                if len(blockers) > 5:
                    lines.append(f"- *...and {len(blockers) - 5} more*")
                lines.append("")

            # Add recommendation
            lines.extend(
                [
                    "### 💡 Recommendation",
                    "",
                ]
            )
            if status == "GREEN":
                lines.append("✅ Release is on track. Continue monitoring blockers.")
            elif status == "YELLOW":
                lines.append(f"⚠️ Release needs attention. {total_open} open items, {blocker_count} blockers.")
            else:
                lines.append(
                    f"🔴 Release at risk! Focus on resolving {blocker_count} blockers and {total_open} open items."
                )

            return {
                "release": release,
                "status": status,
                "rrs_score": rrs_score,
                "open_items": total_open,
                "blockers": blocker_count,
                "days_remaining": days_remaining,
                "total_resolved": total_resolved,
                "display": "\n".join(lines),
            }

        except Exception as err:
            return {
                "release": release,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


if __name__ == "__main__":
    # Run with stdio transport (required for subprocess communication)
    mcp.run(transport="stdio")

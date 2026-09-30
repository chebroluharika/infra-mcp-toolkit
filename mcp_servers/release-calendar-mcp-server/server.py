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
Release Calendar MCP Server

Exposes Release Calendar data as MCP tools for AI agents.
Data is sourced from the Release Calendar PDF parsed by the backend API.

Usage:
    uv run server.py
"""

import os
from datetime import datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# =============================================================================
# Configuration
# =============================================================================

mcp = FastMCP("release-calendar-mcp-server")

DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
if not DEFAULT_RELEASE:
    raise EnvironmentError(
        "CURRENT_RELEASE environment variable is required! "
        "Set it in your .env file or docker-compose.yml (e.g., CURRENT_RELEASE=R134)"
    )

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_TIMEOUT = 10.0

MILESTONE_ORDER = (
    "IRR",
    "Branch Cut - EP",
    "Final Build - EP",
    "Signoff STG/FedAlpha - ENG",
    "Deploy MP Pre PROD",
    "Deploy Prod Day 1",
    "Deploy Prod Day 2",
    "Deploy Prod Day 3",
    "Deploy Prod Day 4",
)

# Values that LLMs sometimes pass instead of actual release IDs
INVALID_RELEASE_VALUES = frozenset(
    {
        "None",
        "null",
        "",
        "BranchCut",
        "Branch Cut",
        "branch_cut",
        "IRR",
        "FinalBuild",
        "Final Build",
        "GA",
        "Day1",
        "Day2",
        "Day3",
        "Day4",
        "latest",
        "current",
        "Rcurrent",
        "default",
    }
)


# =============================================================================
# Helper Functions
# =============================================================================


def normalize_release(release: str) -> str:
    """Normalize release identifier to standard format (e.g., R134.0)."""
    if not release or release in INVALID_RELEASE_VALUES:
        release = DEFAULT_RELEASE

    # Add R prefix if missing
    if not release.startswith("R"):
        release = f"R{release}"

    # Add .0 suffix for major releases
    if "." not in release:
        release = f"{release}.0"

    return release


def get_milestone_status(date_str: str, today) -> tuple[str, int]:
    """Parse date and return (status, days_away)."""
    try:
        ms_date = datetime.strptime(date_str, "%d-%b-%Y").date()
        days_away = (ms_date - today).days

        if days_away < 0:
            return "completed", days_away
        elif days_away == 0:
            return "current", days_away
        else:
            return "upcoming", days_away
    except ValueError:
        return "unknown", 0


def format_days(days: int) -> str:
    """Format days as human-readable string."""
    if days < 0:
        return f"{abs(days)} days ago"
    elif days > 0:
        return f"in {days} days"
    return "Today"


def get_status_icon(status: str) -> str:
    """Get emoji icon for milestone status."""
    return {"completed": "✅", "current": "🔄", "upcoming": "⏳"}.get(status, "❓")


def build_milestones_list(milestones_dict: dict, today) -> tuple[list, int, dict | None]:
    """
    Build milestones list with status calculations.

    Returns: (milestones_list, completed_count, next_milestone)
    """
    milestones_list = []
    completed_count = 0
    next_milestone = None

    for ms_name in MILESTONE_ORDER:
        date_str = milestones_dict.get(ms_name, "-")
        if not date_str or date_str == "-":
            continue

        status, days_away = get_milestone_status(date_str, today)
        if status == "unknown":
            continue

        if status == "completed":
            completed_count += 1
        elif status == "upcoming" and next_milestone is None:
            next_milestone = {"name": ms_name, "date": date_str, "days_away": days_away}

        milestones_list.append(
            {
                "name": ms_name,
                "date": date_str,
                "status": status,
                "days_away": days_away,
            }
        )

    return milestones_list, completed_count, next_milestone


def build_display(
    release_name: str, milestones: list, completed: int, total: int, progress: int, next_milestone: dict | None
) -> str:
    """Build markdown display for AI assistant."""
    lines = [
        f"## 📅 Release Calendar: {release_name}",
        "",
        f"**Progress:** {completed}/{total} milestones completed ({progress}%)",
        "",
        "| Milestone | Date | Status | Days |",
        "|-----------|------|--------|------|",
    ]

    for m in milestones:
        icon = get_status_icon(m["status"])
        days_str = format_days(m["days_away"])
        lines.append(f"| 📅 {m['name']} | {m['date']} | {icon} {m['status']} | {days_str} |")

    if next_milestone:
        lines.extend(
            [
                "",
                f"**Next:** {next_milestone['name']} on {next_milestone['date']} ({next_milestone['days_away']} days)",
            ]
        )

    return "\n".join(lines)


def create_error_response(release: str, source: str, error: str) -> dict[str, Any]:
    """Create standardized error response."""
    return {
        "release": release,
        "milestones": [],
        "source": source,
        "summary": {"total": 0, "completed": 0, "progress_pct": 0, "next_milestone": None},
        "error": error,
        "display": f"Error: {error}",
    }


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool()
async def calendar_get_info() -> dict[str, Any]:
    """
    Get calendar configuration information.

    Release dates are fetched from /api/release-calendar/releases.
    Data is parsed from the Release Calendar PDF.
    """
    return {
        "configured": True,
        "source": "release-calendar-pdf",
        "current_release": DEFAULT_RELEASE,
        "api_base": API_BASE_URL,
    }


@mcp.tool()
async def calendar_get_release_dates(release: str = "") -> dict[str, Any]:
    """
    Get milestone dates for a release (IRR, Branch Cut, Final Build, Deploy dates).

    Use for: "when is branch cut?", "release dates", "when is IRR?"

    Args:
        release: Release identifier (e.g., R134, R135.0). Empty uses current release.

    Returns:
        Milestone dates with status, days remaining, and progress summary.
    """
    release_name = normalize_release(release)

    async with httpx.AsyncClient(timeout=API_TIMEOUT, verify=False) as client:
        try:
            response = await client.get(f"{API_BASE_URL}/api/release-calendar/releases/{release_name}")

            if response.status_code != 200:
                return create_error_response(release_name, "api_error", f"Backend returned {response.status_code}")

            data = response.json()
            release_data = data.get("release", {})
            milestones_dict = release_data.get("milestones", {})
            today = datetime.now().date()

            # Build milestones list
            milestones_list, completed_count, next_milestone = build_milestones_list(milestones_dict, today)

            total = len(milestones_list)
            progress = int((completed_count / total * 100) if total > 0 else 0)

            # Build display
            display = build_display(release_name, milestones_list, completed_count, total, progress, next_milestone)

            return {
                "release": release_name,
                "milestones": milestones_list,
                "source": "release-calendar",
                "summary": {
                    "total": total,
                    "completed": completed_count,
                    "progress_pct": progress,
                    "next_milestone": next_milestone,
                },
                "display": display,
            }

        except httpx.HTTPError as err:
            return create_error_response(release_name, "api_unavailable", str(err))
        except (ValueError, KeyError) as err:
            return create_error_response(release_name, "parse_error", str(err))


@mcp.tool()
async def calendar_get_upcoming_milestones(release: str = "", count: int = 5) -> dict[str, Any]:
    """
    Get upcoming milestones for a release.

    Use when asked about upcoming deadlines or what's next for a release.

    Args:
        release: Release identifier (e.g., R134). Empty uses current release.
        count: Maximum number of upcoming milestones to return (default: 5)

    Returns:
        List of upcoming milestones with days until each.
    """
    release_data = await calendar_get_release_dates(release)

    milestones = release_data.get("milestones", [])
    upcoming = [m for m in milestones if m.get("status") == "upcoming"][:count]

    return {
        "release": release_data.get("release", normalize_release(release)),
        "upcoming": upcoming,
        "source": "release-calendar",
        "count": len(upcoming),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

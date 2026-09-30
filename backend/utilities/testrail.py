"""
TestRail Utilities
==================

Utility functions for TestRail data processing, formatting, and analysis.
"""

from datetime import datetime
from typing import Dict, Optional

# =============================================================================
# Platform Detection
# =============================================================================

PLATFORM_KEYWORDS = {
    "Android": ["android"],
    "iOS": ["ios", "iphone", "ipad"],
    "Linux": ["linux"],
    "Mac": ["mac", "macos"],
    "Windows": ["windows"],
    "ChromeOS": ["chrome", "chromeos"],
    "Backend": ["backend", "api"],
    "Web": ["web"],
}


def parse_platform_from_run_name(run_name: str) -> Optional[str]:
    """
    Extract platform from test run name.

    TestRail run names typically include platform identifiers like
    'Android Smoke Test', 'iOS Regression', 'Windows Integration'.

    Args:
        run_name: Name of the test run

    Returns:
        Platform name or None if not detected
    """
    run_name_lower = run_name.lower()

    for platform, keywords in PLATFORM_KEYWORDS.items():
        if any(kw in run_name_lower for kw in keywords):
            return platform

    # Fallback: catch "win10", "win11", etc.
    if run_name_lower.startswith("win"):
        return "Windows"

    return None


# =============================================================================
# Metrics Calculation
# =============================================================================


def calculate_run_pass_rate(run: Dict) -> float:
    """
    Calculate pass rate for a test run.

    Pass rate = (passed / total) * 100

    Args:
        run: Test run dict with status counts

    Returns:
        Pass rate percentage (0-100)
    """
    run_total = run.get("total", 0)
    if run_total == 0:
        # Fallback: sum all status counts
        run_total = (
            run.get("passed", 0)
            + run.get("failed", 0)
            + run.get("blocked", 0)
            + run.get("untested", 0)
            + run.get("retest", 0)
            + run.get("custom_statuses", 0)
        )

    if run_total > 0:
        return round((run.get("passed", 0) / run_total) * 100)
    return 0


def calculate_other_count(run: Dict) -> int:
    """Calculate count of 'other' status tests (blocked, untested, retest, custom)."""
    return run.get("blocked", 0) + run.get("untested", 0) + run.get("retest", 0) + run.get("custom_statuses", 0)


def calculate_run_total(run: Dict) -> int:
    """Calculate total tests in a run from status counts."""
    run_total = run.get("total", 0)
    if run_total == 0:
        run_total = (
            run.get("passed", 0)
            + run.get("failed", 0)
            + run.get("blocked", 0)
            + run.get("untested", 0)
            + run.get("retest", 0)
            + run.get("custom_statuses", 0)
        )
    return run_total


# =============================================================================
# Response Builders
# =============================================================================


def build_empty_milestone_response() -> Dict:
    """Build empty response for milestone data when no data available."""
    return {
        "overall": {
            "totalCases": 0,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "blocked": 0,
            "untested": 0,
            "passRate": 0,
            "coveragePercent": 0,
        },
        "byPlatform": {},
        "testRuns": [],
        "activeRuns": 0,
        "dataSource": "testrail",
    }


def build_empty_untested_response() -> Dict:
    """Build empty response for untested-by-owner when no data available."""
    return {
        "summary": {"total_pending_tests": 0, "total_assigned": 0, "total_unassigned": 0, "total_assignees": 0},
        "by_assignee": [],
        "unassigned": {"total": 0, "tests": []},
    }


def build_test_run_entry(run: Dict) -> Dict:
    """Build formatted test run entry for response."""
    run_total = calculate_run_total(run)
    return {
        "id": run.get("id"),  # Include run ID for fetching test cases
        "name": run.get("name", "Unknown"),
        "passRate": calculate_run_pass_rate(run),
        "total": run_total,
        "passed": run.get("passed", 0),
        "failed": run.get("failed", 0),
        "blocked": run.get("blocked", 0),
        "untested": run.get("untested", 0),
        "retest": run.get("retest", 0),
        "skipped": run.get("custom_statuses", 0),
        "other": calculate_other_count(run),
        "url": run.get("url", ""),  # Include URL for linking to TestRail
    }


# =============================================================================
# Platform Aggregation
# =============================================================================


def initialize_platform_data() -> Dict:
    """Initialize empty platform data structure."""
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "blocked": 0,
        "untested": 0,
        "coverage": 0,
        "passRate": 0,
        "lastRun": None,
        "lastRunTimestamp": None,
    }


def aggregate_run_to_platform(platform_data: Dict, run: Dict, run_total: int):
    """Aggregate run stats into platform data."""
    platform_data["total"] += run_total
    platform_data["passed"] += run.get("passed", 0)
    platform_data["failed"] += run.get("failed", 0)
    platform_data["blocked"] += run.get("blocked", 0)
    platform_data["untested"] += run.get("untested", 0)

    # Track most recent run time
    run_completed = run.get("completed_on") or run.get("created_on")
    if run_completed:
        current_ts = platform_data["lastRunTimestamp"]
        if current_ts is None or run_completed > current_ts:
            platform_data["lastRunTimestamp"] = run_completed


def finalize_platform_stats(platform_data: Dict, format_time_fn) -> Dict:
    """Calculate final platform stats (pass rate, coverage, relative time)."""
    data = platform_data.copy()
    executed = data["passed"] + data["failed"]

    # Pass rate = passed / (passed + failed)
    data["passRate"] = round((data["passed"] / executed) * 100) if executed > 0 else 0

    # Coverage = executed / total
    data["coverage"] = round((executed / data["total"]) * 100) if data["total"] > 0 else 0

    # Format lastRun as relative time
    if data.get("lastRunTimestamp"):
        data["lastRun"] = format_time_fn(data["lastRunTimestamp"])
    else:
        data["lastRun"] = datetime.now().strftime("%H:%M")

    # Remove internal timestamp field
    data.pop("lastRunTimestamp", None)

    return data

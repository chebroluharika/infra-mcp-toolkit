"""
TestRail API Router
===================

Provides REST endpoints for TestRail integration using DIRECT API calls.

Endpoints:
    - GET /api/testrail/milestone-data - Get milestone data with platform breakdown
    - GET /api/testrail/untested-by-owner - Get pending tests by assignee
    - GET /api/testrail/run/{run_id}/tests - Get tests for a specific run

Integration:
    Uses direct TestRail API client (`services/testrail_client.py`) for all calls.
    No MCP dependency - direct HTTP calls to TestRail API.
"""

import logging

from config import get_default_release_id, get_milestone_id
from fastapi import APIRouter, HTTPException, Query
from services.testrail_client import get_testrail_client
from utilities.testrail import (
    aggregate_run_to_platform,
    build_empty_milestone_response,
    build_empty_untested_response,
    build_test_run_entry,
    calculate_run_total,
    finalize_platform_stats,
    initialize_platform_data,
    parse_platform_from_run_name,
)
from utilities.time_utils import format_relative_time

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/testrail",
    tags=["testrail"],
)


# =============================================================================
# Milestone & Status Endpoints
# =============================================================================


@router.get("/milestone-data")
async def get_milestone_data(
    project_id: int = Query(default=38, description="TestRail project ID"),
    milestone_id: int = Query(default=None, description="TestRail milestone ID (defaults to current release)"),
    release_id: str = Query(default=None, description="Release ID (e.g., R134) - alternative to milestone_id"),
):
    """
    Get comprehensive TestRail test execution data for a release milestone.

    PURPOSE:
        Returns test execution statistics for a TestRail milestone, including
        overall pass/fail rates, platform-specific breakdowns (Android, iOS,
        Windows, macOS, Linux), and individual test run details.

    WHEN TO USE:
        - Displaying test execution progress on Release Readiness page
        - Viewing test coverage by platform
        - Checking overall pass rate for a release
        - Identifying platforms with test failures

    PARAMETERS:
        - project_id (int): TestRail project ID (default: 38)
        - milestone_id (int): TestRail milestone ID (optional)
        - release_id (str): Release ID like "R135" (auto-maps to milestone_id)

    RETURNS:
        {
            "overall": {
                "totalCases": 500,
                "executed": 450,
                "passed": 400,
                "failed": 30,
                "blocked": 10,
                "untested": 50,
                "passRate": 88.9,
                "coveragePercent": 90.0
            },
            "byPlatform": {
                "Android": {
                    "total": 100,
                    "passed": 85,
                    "failed": 10,
                    "passRate": 89.5
                },
                "iOS": {...},
                "Windows": {...}
            },
            "testRuns": [...],
            "activeRuns": 5,
            "dataSource": "testrail-direct",
            "milestone_id": 84
        }

    MILESTONE MAPPING:
        Release IDs (R134, R135) are auto-mapped to milestone IDs
        via config.py RELEASE_MILESTONES configuration.

    RELATED ENDPOINTS:
        - GET /api/testrail/untested-by-owner - Pending tests by assignee
        - GET /api/testrail/run/{run_id}/tests - Details for specific run
    """
    # Resolve milestone_id from release_id if not provided
    if milestone_id is None:
        effective_release = release_id or get_default_release_id()
        milestone_id = get_milestone_id(effective_release)

    # If no milestone configured for this release, return empty response with message
    if milestone_id is None:
        logger.info(f"No TestRail milestone configured for release {effective_release}")
        response = build_empty_milestone_response()
        response["message"] = (
            f"TestRail milestone not configured for {effective_release}. Add milestone_id to RELEASE_MILESTONES in backend/config.py"
        )
        response["source"] = "testrail-not-configured"
        return response

    try:
        # Use direct TestRail client instead of MCP
        testrail_client = get_testrail_client()

        if not testrail_client.is_configured():
            logger.warning("TestRail credentials not configured")
            return build_empty_milestone_response()

        # Get comprehensive status summary from TestRail
        summary = await testrail_client.get_status_summary(project_id=project_id, milestone_id=milestone_id)

        if not summary or summary.get("total", 0) == 0:
            logger.warning("TestRail returned empty summary for milestone %s", milestone_id)
            return build_empty_milestone_response()

        # Direct client returns flat structure
        stats = summary
        runs = summary.get("runs", [])

        # Build test runs list and aggregate by platform
        test_runs = []
        by_platform = {}

        for run in runs:
            run_total = calculate_run_total(run)
            test_runs.append(build_test_run_entry(run))

            # Aggregate by platform
            platform = parse_platform_from_run_name(run.get("name", ""))
            if platform:
                if platform not in by_platform:
                    by_platform[platform] = initialize_platform_data()
                aggregate_run_to_platform(by_platform[platform], run, run_total)

        # Finalize platform stats
        for platform in by_platform:
            by_platform[platform] = finalize_platform_stats(by_platform[platform], format_relative_time)

        return {
            "overall": {
                "totalCases": stats.get("total", 0),
                "executed": stats.get("total", 0) - stats.get("untested", 0),
                "passed": stats.get("passed", 0),
                "failed": stats.get("failed", 0),
                "blocked": stats.get("blocked", 0),
                "untested": stats.get("untested", 0),
                "passRate": stats.get("pass_rate", 0),
                "coveragePercent": stats.get("pass_rate", 0),
            },
            "byPlatform": by_platform,
            "testRuns": test_runs,
            "activeRuns": summary.get("runs_count", 0),
            "newAutomatedThisWeek": 0,
            "dataSource": "testrail-direct",
            "milestone_id": milestone_id,
        }

    except Exception as e:
        import traceback

        logger.error("Error getting milestone data: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/untested-by-owner")
async def get_untested_by_owner(
    project_id: int = Query(default=38, description="TestRail project ID"),
    milestone_id: int = Query(default=None, description="TestRail milestone ID (defaults to current release)"),
    release_id: str = Query(default=None, description="Release ID (e.g., R134) - alternative to milestone_id"),
):
    """
    Get pending/untested test cases grouped by assignee.

    PURPOSE:
        Returns all untested test cases for a milestone, grouped by the
        test-level assignee. Helps identify who has pending tests and
        enables workload distribution visibility.

    WHEN TO USE:
        - Viewing "Tests by Owner" section on Release Readiness page
        - Identifying team members with pending tests
        - Tracking test execution workload
        - Following up on untested cases

    PARAMETERS:
        - project_id (int): TestRail project ID (default: 38)
        - milestone_id (int): TestRail milestone ID (optional)
        - release_id (str): Release ID like "R135" (auto-maps to milestone_id)

    RETURNS:
        {
            "byAssignee": {
                "john.doe@example.com": {
                    "count": 15,
                    "tests": [
                        {
                            "test_id": 12345,
                            "case_id": 6789,
                            "title": "Test user login flow",
                            "run_name": "Android Regression",
                            "run_id": 100
                        }
                    ]
                },
                "jane.smith@example.com": {...}
            },
            "totalUntested": 50,
            "totalAssignees": 5,
            "dataSource": "testrail-direct"
        }

    RELATED ENDPOINTS:
        - GET /api/testrail/milestone-data - Overall test statistics
        - GET /api/testrail/run/{run_id}/tests - Tests in specific run
    """
    # Resolve milestone_id from release_id if not provided
    effective_release = release_id or get_default_release_id()
    if milestone_id is None:
        milestone_id = get_milestone_id(effective_release)

    # If no milestone configured for this release, return empty response with message
    if milestone_id is None:
        logger.info(f"No TestRail milestone configured for release {effective_release}")
        response = build_empty_untested_response()
        response["message"] = f"TestRail milestone not configured for {effective_release}"
        return response

    try:
        # Use direct TestRail client instead of MCP
        testrail_client = get_testrail_client()

        if not testrail_client.is_configured():
            logger.warning("TestRail credentials not configured")
            return build_empty_untested_response()

        result = await testrail_client.get_pending_tests_by_assignee(project_id, milestone_id)

        if not result:
            return build_empty_untested_response()

        return result

    except Exception as e:
        import traceback

        logger.error("Error getting pending tests: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# Run Details Endpoint
# =============================================================================


@router.get("/run/{run_id}/tests")
async def get_testrail_run_tests(run_id: int):
    """
    Get detailed test case data for a specific TestRail test run.

    PURPOSE:
        Returns all test cases within a test run with their individual
        statuses, assignees, and results. Used when drilling down into
        a specific test run for detailed analysis.

    WHEN TO USE:
        - Viewing details of a specific test run
        - Analyzing failures within a run
        - Linking JIRA stories to TestRail runs (regression tracking)
        - Checking status of all tests in a run

    PARAMETERS:
        - run_id (int): TestRail test run ID

    RETURNS:
        {
            "run": {
                "id": 100,
                "name": "Android Regression R135",
                "description": "...",
                "url": "https://testrail.example.com/runs/100",
                "milestone_id": 84
            },
            "summary": {
                "total": 50,
                "passed": 45,
                "failed": 3,
                "blocked": 1,
                "untested": 1,
                "passRate": 93.8
            },
            "tests": [
                {
                    "id": 12345,
                    "case_id": 6789,
                    "title": "Test user login",
                    "status": "passed",
                    "assignee": "john.doe@example.com",
                    "comment": "..."
                }
            ],
            "dataSource": "testrail-direct"
        }

    RELATED ENDPOINTS:
        - GET /api/testrail/milestone-data - Overall milestone stats
        - GET /api/jira/regression-tracking/hierarchy - JIRA regression tracking
    """
    try:
        testrail_client = get_testrail_client()

        if not testrail_client.is_configured():
            raise HTTPException(status_code=503, detail="TestRail not configured")

        result = await testrail_client.get_run_summary(run_id)

        if result.get("error"):
            raise HTTPException(status_code=404, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching run tests for %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail=str(e)) from e

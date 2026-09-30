# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.0.0",
#   "httpx>=0.25.0",
#   "python-dotenv>=1.0.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
TestRail MCP Server
Exposes TestRail API as MCP tools for AI agents

Usage:
    uv run server.py

Environment Variables:
    TESTRAIL_URL - TestRail base URL (e.g., https://company.testrail.io)
    TESTRAIL_USERNAME - Your email
    TESTRAIL_API_KEY - API key from TestRail
"""

import base64
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("testrail-mcp-server")

# Default release from environment variable (single source of truth - REQUIRED)
DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
if not DEFAULT_RELEASE:
    raise EnvironmentError(
        "CURRENT_RELEASE environment variable is required! "
        "Set it in your .env file or docker-compose.yml (e.g., CURRENT_RELEASE=R134)"
    )


# ============ TestRail Client ============


class TestRailClient:
    """Client for TestRail API"""

    STATUS_MAP = {1: "passed", 2: "blocked", 3: "untested", 4: "retest", 5: "failed"}

    def __init__(self):
        self.base_url = os.getenv("TESTRAIL_URL", "").rstrip("/")
        self.username = os.getenv("TESTRAIL_USERNAME", os.getenv("TESTRAIL_EMAIL", ""))
        self.api_key = os.getenv("TESTRAIL_API_KEY", "")
        self.configured = all([self.base_url, self.username, self.api_key])

        if not self.configured:
            print(
                f"⚠️ TestRail not configured. Missing: "
                f"{'TESTRAIL_URL ' if not self.base_url else ''}"
                f"{'TESTRAIL_USERNAME/EMAIL ' if not self.username else ''}"
                f"{'TESTRAIL_API_KEY' if not self.api_key else ''}",
                file=sys.stderr,
            )

    @property
    def _headers(self) -> Dict[str, str]:
        creds = base64.b64encode(f"{self.username}:{self.api_key}".encode()).decode()
        return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    async def _get(self, endpoint: str) -> Any:
        if not self.configured:
            raise ValueError("TestRail not configured - check TESTRAIL_URL, TESTRAIL_USERNAME, TESTRAIL_API_KEY")

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            url = f"{self.base_url}/index.php?/api/v2/{endpoint}"
            response = await client.get(url, headers=self._headers)

            # Handle authentication errors with clear message
            if response.status_code == 401:
                error_msg = "Authentication failed"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", error_msg)
                except json.JSONDecodeError:
                    pass
                raise ValueError(f"TestRail authentication failed: {error_msg}")

            response.raise_for_status()
            return response.json()

    async def get_projects(self) -> List[Dict]:
        """Get all TestRail projects"""
        result = await self._get("get_projects")
        projects = result.get("projects", result) if isinstance(result, dict) else result
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "announcement": p.get("announcement", ""),
                "is_completed": p.get("is_completed", False),
                "url": f"{self.base_url}/index.php?/projects/overview/{p['id']}",
            }
            for p in projects
        ]

    async def get_runs(  # pylint: disable=too-many-locals
        self, project_id: int, is_completed: Optional[bool] = None, milestone_id: Optional[int] = None
    ) -> List[Dict]:
        """Get test runs for a project"""
        endpoint = f"get_runs/{project_id}"
        params = []
        if is_completed is not None:
            params.append(f"is_completed={1 if is_completed else 0}")
        if milestone_id:
            params.append(f"milestone_id={milestone_id}")

        if params:
            endpoint += "&" + "&".join(params)

        result = await self._get(endpoint)
        runs = result.get("runs", result) if isinstance(result, dict) else result

        processed_runs = []
        for run in runs:
            # Get all standard status counts
            passed = run.get("passed_count", 0)
            failed = run.get("failed_count", 0)
            blocked = run.get("blocked_count", 0)
            untested = run.get("untested_count", 0)
            retest = run.get("retest_count", 0)

            # Get custom status counts (TestRail supports custom_status1 through custom_status7)
            custom_statuses = {}
            custom_total = 0
            for status_idx in range(1, 8):
                count = run.get(f"custom_status{status_idx}_count", 0)
                if count > 0:
                    custom_statuses[f"custom_status{status_idx}"] = count
                    custom_total += count

            # Calculate TRUE total including all statuses
            total = passed + failed + blocked + untested + retest + custom_total

            created_on = run.get("created_on")
            created_date = None
            if created_on:
                created_date = datetime.fromtimestamp(created_on).strftime("%Y-%m-%d")

            processed_runs.append(
                {
                    "id": run["id"],
                    "name": run["name"],
                    "passed_count": passed,
                    "failed_count": failed,
                    "blocked_count": blocked,
                    "untested_count": untested,
                    "retest_count": retest,
                    "custom_status_count": custom_total,
                    "custom_statuses": custom_statuses,
                    "total_count": total,
                    "assignedto_id": run.get("assignedto_id"),
                    "created_by": run.get("created_by"),
                    "created_on": created_date,
                    "is_completed": run.get("is_completed", False),
                    "url": f"{self.base_url}/index.php?/runs/view/{run['id']}",
                }
            )

        return processed_runs

    async def get_milestones(self, project_id: int) -> List[Dict]:
        """Get milestones (releases) for a project"""
        result = await self._get(f"get_milestones/{project_id}")
        milestones = result.get("milestones", result) if isinstance(result, dict) else result
        processed = []
        for milestone in milestones:
            due_on = milestone.get("due_on")
            due_date = datetime.fromtimestamp(due_on).isoformat() if due_on else None
            processed.append(
                {
                    "id": milestone["id"],
                    "name": milestone["name"],
                    "description": milestone.get("description", ""),
                    "is_completed": milestone.get("is_completed", False),
                    "due_on": due_date,
                }
            )
        return processed

    async def get_plans(self, project_id: int, milestone_id: Optional[int] = None) -> List[Dict]:
        """Get test plans for a project (test plans contain test runs)"""
        endpoint = f"get_plans/{project_id}"
        if milestone_id:
            endpoint += f"&milestone_id={milestone_id}"

        result = await self._get(endpoint)
        plans = result.get("plans", result) if isinstance(result, dict) else result
        return plans

    async def get_plan(self, plan_id: int) -> Dict:
        """Get a specific test plan with its runs"""
        return await self._get(f"get_plan/{plan_id}")

    async def get_all_runs_for_milestone(  # pylint: disable=too-many-locals
        self, project_id: int, milestone_id: int
    ) -> List[Dict]:
        """
        Get ALL runs for a milestone, including:
        1. Standalone runs (from get_runs)
        2. Runs inside test plans (from get_plans -> get_plan)
        """
        all_runs = []

        # 1. Get standalone runs
        standalone_runs = await self.get_runs(project_id, milestone_id=milestone_id)
        print(f"[TestRail] Found {len(standalone_runs)} standalone runs for milestone {milestone_id}", file=sys.stderr)
        all_runs.extend(standalone_runs)

        # 2. Get test plans for this milestone
        try:
            plans = await self.get_plans(project_id, milestone_id=milestone_id)
            plan_count = len(plans) if plans else 0
            print(f"[TestRail] Found {plan_count} test plans for milestone {milestone_id}", file=sys.stderr)

            if not plans:
                plans = []

            for plan_summary in plans:
                # Get full plan details including runs
                plan_detail = await self.get_plan(plan_summary["id"])

                # Extract runs from plan entries
                for entry in plan_detail.get("entries", []):
                    for run in entry.get("runs", []):
                        # Process run like standalone runs
                        passed = run.get("passed_count", 0)
                        failed = run.get("failed_count", 0)
                        blocked = run.get("blocked_count", 0)
                        untested = run.get("untested_count", 0)
                        retest = run.get("retest_count", 0)

                        custom_total = sum(run.get(f"custom_status{i}_count", 0) for i in range(1, 8))
                        total = passed + failed + blocked + untested + retest + custom_total

                        all_runs.append(
                            {
                                "id": run["id"],
                                "name": run.get("name", entry.get("name", "Unknown")),
                                "plan_id": plan_summary["id"],
                                "plan_name": plan_summary.get("name", ""),
                                "passed_count": passed,
                                "failed_count": failed,
                                "blocked_count": blocked,
                                "untested_count": untested,
                                "retest_count": retest,
                                "custom_status_count": custom_total,
                                "total_count": total,
                                "is_completed": run.get("is_completed", False),
                                "url": f"{self.base_url}/index.php?/runs/view/{run['id']}",
                            }
                        )
        except (httpx.HTTPError, ValueError, KeyError) as err:
            print(f"[TestRail] Warning: Could not fetch test plans: {err}", file=sys.stderr)

        print(f"[TestRail] Total runs for milestone {milestone_id}: {len(all_runs)}", file=sys.stderr)
        return all_runs

    async def get_tests(self, run_id: int, status_id: Optional[str] = None) -> List[Dict]:
        """Get tests from a run with optional status filter"""
        endpoint = f"get_tests/{run_id}"
        if status_id:
            endpoint += f"&status_id={status_id}"

        result = await self._get(endpoint)
        tests = result.get("tests", result) if isinstance(result, dict) else result
        return tests

    async def get_cases(self, project_id: int, suite_id: Optional[int] = None) -> List[Dict]:
        """Get test cases for a project/suite"""
        endpoint = f"get_cases/{project_id}"
        if suite_id:
            endpoint += f"&suite_id={suite_id}"

        result = await self._get(endpoint)
        cases = result.get("cases", result) if isinstance(result, dict) else result
        return [
            {
                "id": c["id"],
                "title": c["title"],
                "section_id": c.get("section_id"),
                "priority_id": c.get("priority_id"),
                "type_id": c.get("type_id"),
                "created_by": c.get("created_by"),
            }
            for c in cases
        ]

    async def get_user(self, user_id: int) -> Dict:
        """Get user details by ID"""
        result = await self._get(f"get_user/{user_id}")
        return {
            "id": result.get("id"),
            "name": result.get("name"),
            "email": result.get("email"),
        }

    async def get_users(self) -> List[Dict]:
        """Get all users"""
        result = await self._get("get_users")
        users = result if isinstance(result, list) else result.get("users", [])
        return [{"id": u.get("id"), "name": u.get("name"), "email": u.get("email")} for u in users]


# Client instance (lazy singleton)
_client: TestRailClient | None = None


def get_client() -> TestRailClient:
    """Get or create the TestRail client singleton."""
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = TestRailClient()
    return _client


# ============ MCP Tools ============


@mcp.tool()
async def testrail_get_projects() -> List[Dict]:
    """
    Get all TestRail projects.

    Returns:
        List of projects with id, name, and URL
    """
    return await get_client().get_projects()


@mcp.tool()
async def testrail_get_milestones(project_id: int) -> List[Dict]:
    """
    Get milestones (releases) for a project.

    Args:
        project_id: TestRail project ID

    Returns:
        List of milestones with id, name, and due date
    """
    return await get_client().get_milestones(project_id)


@mcp.tool()
async def testrail_get_test_runs(
    project_id: int, milestone_id: Optional[int] = None, is_completed: Optional[bool] = None
) -> List[Dict]:
    """
    Get test runs for a project.

    Args:
        project_id: TestRail project ID
        milestone_id: Optional milestone ID to filter runs
        is_completed: Optional filter for completed/active runs

    Returns:
        List of test runs with status counts
    """
    return await get_client().get_runs(project_id, is_completed=is_completed, milestone_id=milestone_id)


@mcp.tool()
async def testrail_get_test_cases(project_id: int, suite_id: Optional[int] = None) -> List[Dict]:
    """
    Get test cases for a project.

    Args:
        project_id: TestRail project ID
        suite_id: Optional suite ID to filter cases

    Returns:
        List of test cases
    """
    return await get_client().get_cases(project_id, suite_id)


@mcp.tool()
async def testrail_get_testcase_status(run_id: int) -> Dict[str, Any]:
    """
    Get status summary for a specific test run.

    Args:
        run_id: TestRail run ID

    Returns:
        Status counts (passed, failed, blocked, untested, etc.)
    """
    client = get_client()
    tests = await client.get_tests(run_id)

    # Count by status
    status_counts = {"passed": 0, "failed": 0, "blocked": 0, "untested": 0, "retest": 0, "other": 0}
    for test in tests:
        status_id = test.get("status_id")
        status_name = client.STATUS_MAP.get(status_id, "other")
        status_counts[status_name] = status_counts.get(status_name, 0) + 1

    total = sum(status_counts.values())
    pass_rate = round((status_counts["passed"] / total * 100), 2) if total > 0 else 0

    return {
        "run_id": run_id,
        "total": total,
        "passed": status_counts["passed"],
        "failed": status_counts["failed"],
        "blocked": status_counts["blocked"],
        "untested": status_counts["untested"],
        "retest": status_counts["retest"],
        "pass_rate": pass_rate,
    }


@mcp.tool()
async def testrail_get_testcase_status_summary(project_id: int, milestone_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get comprehensive test execution summary across all runs for a milestone.

    This is the main tool used by the dashboard to get test execution metrics.
    Includes runs from both standalone runs AND test plans.

    Args:
        project_id: TestRail project ID
        milestone_id: Optional milestone ID to filter runs

    Returns:
        Summary with total runs, pass rates, and status breakdown
    """
    client = get_client()

    # Fetch ALL runs for the milestone (standalone + test plan runs)
    if milestone_id:
        runs = await client.get_all_runs_for_milestone(project_id, milestone_id)
    else:
        runs = await client.get_runs(project_id, is_completed=None, milestone_id=milestone_id)

    total_p = sum(r.get("passed_count", 0) for r in runs)
    total_f = sum(r.get("failed_count", 0) for r in runs)
    total_b = sum(r.get("blocked_count", 0) for r in runs)
    total_u = sum(r.get("untested_count", 0) for r in runs)
    total_r = sum(r.get("retest_count", 0) for r in runs)
    total_custom = sum(r.get("custom_status_count", 0) for r in runs)

    # TRUE total includes all statuses (standard + custom like Skipped, Need Info, etc.)
    total = total_p + total_f + total_b + total_u + total_r + total_custom

    # Separate active vs completed runs
    active_runs = [r for r in runs if not r.get("is_completed", False)]
    completed_runs = [r for r in runs if r.get("is_completed", False)]

    return {
        "project_id": project_id,
        "total_runs": len(runs),
        "active_runs": len(active_runs),
        "completed_runs": len(completed_runs),
        "summary": {
            "total": total,
            "passed": total_p,
            "failed": total_f,
            "blocked": total_b,
            "untested": total_u,
            "retest": total_r,
            "custom_statuses": total_custom,
            "pass_rate": round((total_p / total * 100), 2) if total > 0 else 0,
        },
        "runs": [
            {
                "id": r["id"],
                "name": r.get("name", "Unknown"),
                "passed": r.get("passed_count", 0),
                "failed": r.get("failed_count", 0),
                "blocked": r.get("blocked_count", 0),
                "untested": r.get("untested_count", 0),
                "retest": r.get("retest_count", 0),
                "custom_statuses": r.get("custom_status_count", 0),
                "total": r.get("total_count", 0),
                "is_completed": r.get("is_completed", False),
            }
            for r in runs
        ],
    }


@mcp.tool()
async def testrail_get_milestone_runs(project_id: int, milestone_id: int) -> Dict[str, Any]:
    """
    Get all test runs for a specific milestone with aggregated summary.
    Includes runs from both standalone runs AND test plans.

    Args:
        project_id: TestRail project ID
        milestone_id: TestRail milestone ID

    Returns:
        All runs for the milestone with summary statistics
    """
    client = get_client()
    # Get ALL runs including those inside test plans
    runs = await client.get_all_runs_for_milestone(project_id, milestone_id)

    total_p = sum(r.get("passed_count", 0) for r in runs)
    total_f = sum(r.get("failed_count", 0) for r in runs)
    total_b = sum(r.get("blocked_count", 0) for r in runs)
    total_u = sum(r.get("untested_count", 0) for r in runs)
    total = total_p + total_f + total_b + total_u

    return {
        "milestone_id": milestone_id,
        "project_id": project_id,
        "runs": runs,
        "summary": {
            "total": total,
            "passed": total_p,
            "failed": total_f,
            "blocked": total_b,
            "untested": total_u,
            "pass_rate": round((total_p / total * 100), 2) if total > 0 else 0,
        },
    }


@mcp.tool()
async def testrail_get_pending_tests_by_assignee(  # pylint: disable=too-many-locals
    project_id: int, milestone_id: int, max_tests_per_run: int = 50
) -> Dict[str, Any]:
    """
    Get pending (untested/retest) tests grouped by assignee.

    Args:
        project_id: TestRail project ID
        milestone_id: TestRail milestone ID
        max_tests_per_run: Max tests to fetch per run (for performance)

    Returns:
        Pending tests grouped by assignee email
    """
    client = get_client()

    # Get ALL runs for milestone (standalone + test plan runs), filter to active only
    all_runs = await client.get_all_runs_for_milestone(project_id, milestone_id)
    runs = [r for r in all_runs if not r.get("is_completed", False)]

    # Cache for user lookups
    user_cache: Dict[int, Dict] = {}

    async def get_user_cached(user_id: int) -> Dict:
        if user_id not in user_cache:
            try:
                user_cache[user_id] = await client.get_user(user_id)
            except (httpx.HTTPError, ValueError, KeyError):
                user_cache[user_id] = {"id": user_id, "name": "Unknown", "email": "unknown"}
        return user_cache[user_id]

    # Collect pending tests by assignee
    by_assignee: Dict[str, List[Dict]] = {}
    unassigned_tests: List[Dict] = []
    total_pending = 0

    for run in runs[:10]:  # Limit runs for performance
        # Get untested/retest tests (status_id 3=untested, 4=retest)
        tests = await client.get_tests(run["id"], status_id="3,4")

        for test in tests[:max_tests_per_run]:
            total_pending += 1
            test_info = {
                "test_id": test.get("id"),
                "case_id": test.get("case_id"),
                "title": test.get("title", "Unknown"),
                "run_name": run.get("name", "Unknown"),
                "run_id": run.get("id"),
                "status": client.STATUS_MAP.get(test.get("status_id"), "untested"),
            }

            assignee_id = test.get("assignedto_id")
            if assignee_id:
                user = await get_user_cached(assignee_id)
                email = user.get("email", "unknown")
                if email not in by_assignee:
                    by_assignee[email] = []
                by_assignee[email].append(test_info)
            else:
                unassigned_tests.append(test_info)

    # Format response
    assignee_list = [
        {"assignee": email, "count": len(tests), "tests": tests}
        for email, tests in sorted(by_assignee.items(), key=lambda x: -len(x[1]))
    ]

    return {
        "summary": {
            "total_pending_tests": total_pending,
            "total_assigned": sum(len(a["tests"]) for a in assignee_list),
            "total_unassigned": len(unassigned_tests),
            "total_assignees": len(assignee_list),
        },
        "by_assignee": assignee_list,
        "unassigned": {"total": len(unassigned_tests), "tests": unassigned_tests[:20]},
    }


# =============================================================================
# Release ID Mapping Tools (Convenience wrappers)
# =============================================================================

# Default project mapping - customize for your TestRail setup
RELEASE_MAPPING = {
    # release_id -> (project_id, milestone_id)
    # These need to be configured for your TestRail instance
    "R134": {"project_id": 1, "milestone_id": 134, "name": "Release 134"},
    "R135": {"project_id": 1, "milestone_id": 135, "name": "Release 135"},
    "R133": {"project_id": 1, "milestone_id": 133, "name": "Release 133"},
}

# Default project ID if not specified
DEFAULT_PROJECT_ID = int(os.getenv("TESTRAIL_PROJECT_ID", "1"))


@mcp.tool()
async def testrail_get_test_execution_by_release(  # pylint: disable=too-many-locals
    release_id: str = DEFAULT_RELEASE,
) -> Dict[str, Any]:
    """
    Get test execution status for a release - pass/fail rates.

    Use when asked: "test results", "pass rate", "test execution for R134"

    Args:
        release_id: Release identifier like "R134"

    Returns:
        Test execution summary with pass/fail/blocked/untested counts
    """
    client = get_client()

    # Map release to milestone
    release_num = release_id.replace("R", "").replace("r", "")

    # Try to find milestone by name
    milestones = await client.get_milestones(DEFAULT_PROJECT_ID)
    milestone_id = None

    for milestone in milestones:
        ms_name = milestone.get("name", "").lower()
        if release_num in ms_name or f"r{release_num}" in ms_name:
            milestone_id = milestone.get("id")
            break

    if not milestone_id:
        # Use release number as milestone ID directly
        try:
            milestone_id = int(release_num)
        except ValueError:
            return {
                "release_id": release_id,
                "error": f"Could not find milestone for {release_id}",
                "source": "testrail-mcp",
            }

    # Get test execution summary
    runs = await client.get_all_runs_for_milestone(DEFAULT_PROJECT_ID, milestone_id)

    total_p = sum(r.get("passed_count", 0) for r in runs)
    total_f = sum(r.get("failed_count", 0) for r in runs)
    total_b = sum(r.get("blocked_count", 0) for r in runs)
    total_u = sum(r.get("untested_count", 0) for r in runs)
    total_r = sum(r.get("retest_count", 0) for r in runs)
    total_custom = sum(r.get("custom_status_count", 0) for r in runs)

    total = total_p + total_f + total_b + total_u + total_r + total_custom
    pass_rate = round((total_p / total * 100), 1) if total > 0 else 0

    # Determine status
    if pass_rate >= 95:
        status = "green"
        emoji = "🟢"
    elif pass_rate >= 80:
        status = "yellow"
        emoji = "🟡"
    else:
        status = "red"
        emoji = "🔴"

    return {
        "release_id": release_id,
        "milestone_id": milestone_id,
        "status": status,
        "status_emoji": emoji,
        "total_runs": len(runs),
        "summary": {
            "total": total,
            "passed": total_p,
            "failed": total_f,
            "blocked": total_b,
            "untested": total_u,
            "retest": total_r,
            "pass_rate": pass_rate,
        },
        "top_runs": [
            {
                "name": r.get("name", "Unknown"),
                "passed": r.get("passed_count", 0),
                "failed": r.get("failed_count", 0),
                "total": r.get("total_count", 0),
            }
            for r in runs[:10]
        ],
        "source": "testrail-mcp",
    }


@mcp.tool()
async def testrail_get_untested_by_owner(release_id: str = DEFAULT_RELEASE, max_tests: int = 50) -> Dict[str, Any]:
    """
    Get untested test cases grouped by owner for a release.

    Use when asked: "untested cases", "what's not tested?", "test coverage gaps"

    Args:
        release_id: Release identifier like "R134"
        max_tests: Maximum tests to analyze per run

    Returns:
        Untested tests grouped by assignee
    """
    client = get_client()

    # Map release to milestone
    release_num = release_id.replace("R", "").replace("r", "")

    milestones = await client.get_milestones(DEFAULT_PROJECT_ID)
    milestone_id = None

    for milestone in milestones:
        ms_name = milestone.get("name", "").lower()
        if release_num in ms_name or f"r{release_num}" in ms_name:
            milestone_id = milestone.get("id")
            break

    if not milestone_id:
        try:
            milestone_id = int(release_num)
        except ValueError:
            return {
                "release_id": release_id,
                "error": f"Could not find milestone for {release_id}",
                "source": "testrail-mcp",
            }

    # Get pending tests
    result = await testrail_get_pending_tests_by_assignee(DEFAULT_PROJECT_ID, milestone_id, max_tests)

    return {"release_id": release_id, "milestone_id": milestone_id, **result, "source": "testrail-mcp"}


if __name__ == "__main__":
    # Run with stdio transport (required for subprocess communication)
    mcp.run(transport="stdio")

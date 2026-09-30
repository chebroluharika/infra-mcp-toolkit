"""
Direct TestRail API Client
==========================

Direct TestRail API access for FastAPI backend.
This replaces MCP calls for TestRail data, providing direct HTTP access.

Environment Variables:
    TESTRAIL_URL - TestRail base URL (e.g., https://company.testrail.io)
    TESTRAIL_USERNAME - Your email
    TESTRAIL_API_KEY - API key from TestRail
"""

import asyncio
import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Rate limiting settings
# TestRail allows ~180 requests/minute, so 0.1s delay is safe
RATE_LIMIT_DELAY = 0.1  # Delay between requests in seconds (reduced from 0.5s)
MAX_RETRIES = 3  # Maximum retry attempts for rate-limited requests
RETRY_BACKOFF = 2  # Exponential backoff multiplier


# =============================================================================
# TestRail Client
# =============================================================================


class TestRailClient:
    """Direct TestRail API client"""

    STATUS_MAP = {1: "passed", 2: "blocked", 3: "untested", 4: "retest", 5: "failed"}

    def __init__(self):
        self.base_url = os.getenv("TESTRAIL_URL", "").rstrip("/")
        self.username = os.getenv("TESTRAIL_USERNAME", os.getenv("TESTRAIL_EMAIL", ""))
        self.api_key = os.getenv("TESTRAIL_API_KEY", "")

        # Response caching
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 120  # 2-minute cache

        # Pre-compute auth header
        if self.username and self.api_key:
            creds = base64.b64encode(f"{self.username}:{self.api_key}".encode()).decode()
            self._headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
        else:
            self._headers = {}

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            if time.time() - self._cache_times.get(key, 0) < self._cache_ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """Cache a value."""
        self._cache[key] = value
        self._cache_times[key] = time.time()

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_times.clear()
        logger.info("TestRail cache cleared")

    def is_configured(self) -> bool:
        """Check if TestRail credentials are configured"""
        return all([self.base_url, self.username, self.api_key])

    async def _get(self, endpoint: str) -> Any:
        """Make a GET request to TestRail API with rate limiting and retry logic"""
        if not self.is_configured():
            raise ValueError("TestRail not configured - check TESTRAIL_URL, TESTRAIL_USERNAME, TESTRAIL_API_KEY")

        url = f"{self.base_url}/index.php?/api/v2/{endpoint}"

        for attempt in range(MAX_RETRIES):
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                try:
                    response = await client.get(url, headers=self._headers)

                    if response.status_code == 401:
                        raise ValueError("TestRail authentication failed")

                    if response.status_code == 429:
                        # Rate limited - wait and retry with exponential backoff
                        retry_after = int(response.headers.get("Retry-After", 5))
                        wait_time = max(retry_after, RETRY_BACKOFF**attempt)
                        logger.warning(
                            f"[TestRail] Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()

                    # Add a small delay between successful requests to avoid hitting rate limits
                    await asyncio.sleep(RATE_LIMIT_DELAY)

                    return response.json()

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_BACKOFF ** (attempt + 1)
                        logger.warning(
                            f"[TestRail] Rate limited. Waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    raise

        raise httpx.HTTPStatusError(
            f"Max retries ({MAX_RETRIES}) exceeded for TestRail API", request=None, response=None
        )

    async def get_runs(self, project_id: int, milestone_id: Optional[int] = None) -> List[Dict]:
        """Get test runs for a project"""
        endpoint = f"get_runs/{project_id}"
        params = []
        if milestone_id:
            params.append(f"milestone_id={milestone_id}")

        if params:
            endpoint += "&" + "&".join(params)

        result = await self._get(endpoint)
        runs = result.get("runs", result) if isinstance(result, dict) else result

        processed_runs = []
        for r in runs:
            passed = r.get("passed_count", 0)
            failed = r.get("failed_count", 0)
            blocked = r.get("blocked_count", 0)
            untested = r.get("untested_count", 0)
            retest = r.get("retest_count", 0)

            # Custom status counts
            custom_total = sum(r.get(f"custom_status{i}_count", 0) for i in range(1, 8))
            total = passed + failed + blocked + untested + retest + custom_total

            processed_runs.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "passed_count": passed,
                    "failed_count": failed,
                    "blocked_count": blocked,
                    "untested_count": untested,
                    "retest_count": retest,
                    "custom_status_count": custom_total,
                    "total_count": total,
                    "is_completed": r.get("is_completed", False),
                    "url": f"{self.base_url}/index.php?/runs/view/{r['id']}",
                }
            )

        return processed_runs

    async def get_plans(self, project_id: int, milestone_id: Optional[int] = None) -> List[Dict]:
        """Get test plans for a project"""
        endpoint = f"get_plans/{project_id}"
        if milestone_id:
            endpoint += f"&milestone_id={milestone_id}"

        result = await self._get(endpoint)
        return result.get("plans", result) if isinstance(result, dict) else result

    async def get_plan(self, plan_id: int) -> Dict:
        """Get a specific test plan with its runs"""
        return await self._get(f"get_plan/{plan_id}")

    async def get_all_runs_for_milestone(self, project_id: int, milestone_id: int) -> List[Dict]:
        """Get ALL runs for a milestone, including runs inside test plans"""
        cache_key = f"all_runs:{project_id}:{milestone_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        all_runs = []

        # 1. Get standalone runs and test plans list in parallel
        standalone_runs, plans = await asyncio.gather(
            self.get_runs(project_id, milestone_id=milestone_id),
            self._get_plans_safe(project_id, milestone_id=milestone_id),
        )

        logger.info("[TestRail] Found %d standalone runs for milestone %s", len(standalone_runs), milestone_id)
        all_runs.extend(standalone_runs)

        # 2. Fetch all plan details in parallel
        if plans:
            logger.info(
                "[TestRail] Found %d test plans for milestone %s, fetching in parallel", len(plans), milestone_id
            )
            plan_details = await asyncio.gather(
                *[self._get_plan_safe(plan["id"]) for plan in plans],
                return_exceptions=True,
            )

            # Process plan details
            for plan_summary, plan_detail in zip(plans, plan_details):
                if isinstance(plan_detail, Exception):
                    logger.warning("[TestRail] Failed to fetch plan %s: %s", plan_summary["id"], plan_detail)
                    continue

                if not plan_detail:
                    continue

                for entry in plan_detail.get("entries", []):
                    for run in entry.get("runs", []):
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

        logger.info("[TestRail] Total runs for milestone %s: %d", milestone_id, len(all_runs))
        self._set_cache(cache_key, all_runs)
        return all_runs

    async def _get_plans_safe(self, project_id: int, milestone_id: Optional[int] = None) -> List[Dict]:
        """Get test plans with error handling (returns empty list on failure)"""
        try:
            return await self.get_plans(project_id, milestone_id=milestone_id)
        except Exception as e:
            logger.warning("[TestRail] Could not fetch test plans: %s", e)
            return []

    async def _get_plan_safe(self, plan_id: int) -> Optional[Dict]:
        """Get a specific test plan with error handling (returns None on failure)"""
        try:
            return await self.get_plan(plan_id)
        except Exception as e:
            logger.warning("[TestRail] Could not fetch plan %s: %s", plan_id, e)
            return None

    async def get_tests(self, run_id: int, status_id: Optional[str] = None) -> List[Dict]:
        """
        Get all tests in a test run with their statuses.

        Args:
            run_id: TestRail run ID
            status_id: Optional comma-separated status IDs to filter (e.g., "3,4" for untested/retest)

        Returns:
            List of tests with id, title, status
        """
        endpoint = f"get_tests/{run_id}"
        if status_id:
            endpoint += f"&status_id={status_id}"

        result = await self._get(endpoint)
        tests = result.get("tests", result) if isinstance(result, dict) else result

        processed = []
        for t in tests:
            test_status_id = t.get("status_id")
            status = self.STATUS_MAP.get(test_status_id, "unknown")

            processed.append(
                {
                    "id": t.get("id"),
                    "case_id": t.get("case_id"),
                    "title": t.get("title", ""),
                    "status_id": test_status_id,
                    "status": status,
                    "assignee_id": t.get("assignedto_id"),
                }
            )

        return processed

    async def get_user(self, user_id: int) -> Dict:
        """Get user details by ID"""
        try:
            return await self._get(f"get_user/{user_id}")
        except Exception as e:
            logger.warning("Could not fetch user %s: %s", user_id, e)
            return {"id": user_id, "name": "Unknown", "email": "unknown"}

    async def get_pending_tests_by_assignee(
        self, project_id: int, milestone_id: int, max_tests_per_run: int = 50
    ) -> Dict:
        """
        Get pending (untested/retest) tests grouped by TEST-LEVEL assignee.

        Args:
            project_id: TestRail project ID
            milestone_id: TestRail milestone ID
            max_tests_per_run: Max tests to fetch per run (for performance)

        Returns:
            Dict with tests grouped by assignee email
        """
        # Get ALL runs for milestone, filter to active only
        all_runs = await self.get_all_runs_for_milestone(project_id, milestone_id)
        runs = [r for r in all_runs if not r.get("is_completed", False)]

        # Cache for user lookups
        user_cache: Dict[int, Dict] = {}

        async def get_user_cached(user_id: int) -> Dict:
            if user_id not in user_cache:
                user_cache[user_id] = await self.get_user(user_id)
            return user_cache[user_id]

        # Collect pending tests by assignee
        by_assignee: Dict[str, List[Dict]] = {}
        unassigned_tests: List[Dict] = []
        total_pending = 0

        for run in runs[:10]:  # Limit runs for performance
            # Get untested/retest tests (status_id 3=untested, 4=retest)
            tests = await self.get_tests(run["id"], status_id="3,4")

            for test in tests[:max_tests_per_run]:
                total_pending += 1
                test_info = {
                    "test_id": test.get("id"),
                    "case_id": test.get("case_id"),
                    "title": test.get("title", "Unknown"),
                    "run_name": run.get("name", "Unknown"),
                    "run_id": run.get("id"),
                    "status": test.get("status", "untested"),
                }

                assignee_id = test.get("assignee_id")
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
            "source": "testrail-direct",
        }

    async def get_cases(self, project_id: int, suite_id: int) -> List[Dict]:
        """
        Get all test cases in a suite.

        Args:
            project_id: TestRail project ID
            suite_id: TestRail suite ID

        Returns:
            List of test cases
        """
        endpoint = f"get_cases/{project_id}&suite_id={suite_id}"
        result = await self._get(endpoint)
        cases = result.get("cases", result) if isinstance(result, dict) else result

        processed = []
        for c in cases:
            processed.append(
                {
                    "id": c.get("id"),
                    "title": c.get("title", ""),
                    "section_id": c.get("section_id"),
                    "priority_id": c.get("priority_id"),
                    "type_id": c.get("type_id"),
                }
            )

        return processed

    async def get_case(self, case_id: int) -> Dict:
        """
        Get a single test case with full details including description.

        Used by TestRailIndexer to get rich test case data for embedding.

        Args:
            case_id: TestRail case ID

        Returns:
            Dict with case details (title, description, preconditions, steps, etc.)
        """
        try:
            result = await self._get(f"get_case/{case_id}")
            return {
                "id": result.get("id"),
                "title": result.get("title", ""),
                "section_id": result.get("section_id"),
                "suite_id": result.get("suite_id"),
                "priority_id": result.get("priority_id"),
                "type_id": result.get("type_id"),
                "refs": result.get("refs", ""),
                "custom_preconds": result.get("custom_preconds", ""),
                "custom_steps": result.get("custom_steps", ""),
                "custom_expected": result.get("custom_expected", ""),
                "custom_steps_separated": result.get("custom_steps_separated", []),
            }
        except Exception as e:
            logger.warning("Could not fetch case %s: %s", case_id, e)
            return {"id": case_id, "title": "", "error": str(e)}

    async def get_tests_with_cases(self, run_id: int) -> List[Dict]:
        """
        Get all tests in a run with full case details (title + description).

        Fetches tests first, then enriches with case details in batches.
        Used by TestRailIndexer for building the FAISS index.

        Args:
            run_id: TestRail run ID

        Returns:
            List of tests enriched with case descriptions
        """
        tests = await self.get_tests(run_id)

        # Batch fetch case details
        enriched = []
        case_ids = [t.get("case_id") for t in tests if t.get("case_id")]

        # Fetch in parallel (batches of 10 to respect rate limits)
        case_cache: Dict[int, Dict] = {}
        batch_size = 10

        for i in range(0, len(case_ids), batch_size):
            batch = case_ids[i : i + batch_size]
            results = await asyncio.gather(
                *[self.get_case(cid) for cid in batch if cid not in case_cache],
                return_exceptions=True,
            )
            for cid, result in zip([c for c in batch if c not in case_cache], results):
                if isinstance(result, Exception):
                    logger.warning("Failed to fetch case %s: %s", cid, result)
                    case_cache[cid] = {"id": cid, "title": ""}
                else:
                    case_cache[cid] = result

        for test in tests:
            case_id = test.get("case_id")
            case_detail = case_cache.get(case_id, {})

            enriched.append(
                {
                    **test,
                    "case_title": case_detail.get("title", test.get("title", "")),
                    "case_description": case_detail.get("custom_preconds", ""),
                    "case_steps": case_detail.get("custom_steps", ""),
                    "case_expected": case_detail.get("custom_expected", ""),
                    "case_refs": case_detail.get("refs", ""),
                }
            )

        return enriched

    async def get_run(self, run_id: int) -> Dict:
        """Get a specific test run details"""
        return await self._get(f"get_run/{run_id}")

    async def get_run_summary(self, run_id: int) -> Dict:
        """
        Get summary of a test run including pass/fail counts and test list.

        Args:
            run_id: TestRail run ID

        Returns:
            Dict with run info, counts, and tests
        """
        try:
            # Get run details
            run = await self.get_run(run_id)

            # Get tests in the run
            tests = await self.get_tests(run_id)

            # Count by status
            passed = sum(1 for t in tests if t["status"] == "passed")
            failed = sum(1 for t in tests if t["status"] == "failed")
            blocked = sum(1 for t in tests if t["status"] == "blocked")
            untested = sum(1 for t in tests if t["status"] == "untested")
            retest = sum(1 for t in tests if t["status"] == "retest")
            total = len(tests)

            return {
                "run_id": run_id,
                "name": run.get("name", ""),
                "description": run.get("description", ""),
                "url": f"{self.base_url}/index.php?/runs/view/{run_id}",
                "is_completed": run.get("is_completed", False),
                "passed": passed,
                "failed": failed,
                "blocked": blocked,
                "untested": untested,
                "retest": retest,
                "total": total,
                "pass_rate": round((passed / total * 100), 1) if total > 0 else 0,
                "tests": tests[:50],  # Limit to 50 tests
                "source": "testrail-direct",
            }
        except Exception as e:
            logger.error("Error fetching run %s: %s", run_id, e)
            return {"error": str(e), "run_id": run_id}

    async def get_status_summary(self, project_id: int, milestone_id: int) -> Dict:
        """
        Get comprehensive test status summary for a milestone.
        Aggregates pass/fail/blocked/untested counts from all runs.
        """
        cache_key = f"status_summary:{project_id}:{milestone_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug("TestRail status summary cache hit for M%s", milestone_id)
            return cached

        all_runs = await self.get_all_runs_for_milestone(project_id, milestone_id)

        if not all_runs:
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "blocked": 0,
                "untested": 0,
                "retest": 0,
                "pass_rate": 0,
                "execution_rate": 0,
                "runs_count": 0,
                "source": "testrail-direct",
            }

        total = sum(r.get("total_count", 0) for r in all_runs)
        passed = sum(r.get("passed_count", 0) for r in all_runs)
        failed = sum(r.get("failed_count", 0) for r in all_runs)
        blocked = sum(r.get("blocked_count", 0) for r in all_runs)
        untested = sum(r.get("untested_count", 0) for r in all_runs)
        retest = sum(r.get("retest_count", 0) for r in all_runs)

        executed = passed + failed + blocked + retest
        pass_rate = round((passed / total * 100), 1) if total > 0 else 0
        execution_rate = round((executed / total * 100), 1) if total > 0 else 0

        result = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "untested": untested,
            "retest": retest,
            "pass_rate": pass_rate,
            "execution_rate": execution_rate,
            "runs_count": len(all_runs),
            "runs": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "passed": r.get("passed_count", 0),
                    "failed": r.get("failed_count", 0),
                    "blocked": r.get("blocked_count", 0),
                    "untested": r.get("untested_count", 0),
                    "total": r.get("total_count", 0),
                    "pass_rate": (
                        round((r.get("passed_count", 0) / r.get("total_count", 1) * 100), 1)
                        if r.get("total_count", 0) > 0
                        else 0
                    ),
                    "url": r.get("url", ""),
                }
                for r in all_runs[:20]  # Limit to 20 runs in response
            ],
            "source": "testrail-direct",
        }

        self._set_cache(cache_key, result)
        return result


# =============================================================================
# Singleton
# =============================================================================

_testrail_client: Optional[TestRailClient] = None


def get_testrail_client() -> TestRailClient:
    """Get singleton TestRail client instance"""
    global _testrail_client
    if _testrail_client is None:
        _testrail_client = TestRailClient()
    return _testrail_client

"""
Jenkins API Client
===================

Direct client for Jenkins API access.
Used by backend routers to fetch pipeline and build data.

Optimizations:
- Connection pooling: Reuses HTTP connections across requests
- Caching: 30-second TTL cache for job/build info
- Parallel fetching: Uses asyncio.gather for concurrent API calls

Environment Variables:
    JENKINS_URL - Jenkins server URL
    JENKINS_USER - Jenkins username
    JENKINS_TOKEN - Jenkins API token
    JENKINS_VIEW - Jenkins view name (default: Your-Product)
    JENKINS_JOBS - Comma-separated list of jobs to monitor
    JENKINS_GOLDEN_REGRESSION_URL - URL to Golden Regression Suite job
    JENKINS_GR_USER - Golden Regression Jenkins username (if different from JENKINS_USER)
    JENKINS_GR_TOKEN - Golden Regression Jenkins token (if different from JENKINS_TOKEN)
"""

import asyncio
import base64
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class JenkinsClientBase:
    """
    Base class for Jenkins API clients with shared functionality.

    Provides common methods for:
    - HTTP request handling with caching and connection pooling
    - Test report fetching and parsing
    - Console output retrieval

    Subclasses must set:
    - base_url: Jenkins server URL
    - _auth_headers: Authentication headers dict
    - _cache, _cache_times, _cache_ttl: Caching configuration
    - _max_concurrent, _semaphore, _semaphore_loop: Concurrency control
    """

    # These must be set by subclasses
    base_url: str = ""
    _auth_headers: dict = {}
    _cache: dict = {}
    _cache_times: dict = {}
    _cache_ttl: int = 60
    _max_concurrent: int = 10
    _semaphore = None
    _semaphore_loop = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create semaphore for the current event loop."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
            self._semaphore_loop = None
            return self._semaphore

        if self._semaphore is None or self._semaphore_loop is not current_loop:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
            self._semaphore_loop = current_loop

        return self._semaphore

    def _create_client(self) -> httpx.AsyncClient:
        """Create a fresh HTTP client for each request."""
        return httpx.AsyncClient(
            timeout=30.0,
            verify=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            if time.time() - self._cache_times.get(key, 0) < self._cache_ttl:
                return self._cache[key]
            del self._cache[key]
            del self._cache_times[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """Cache a value with TTL."""
        self._cache[key] = value
        self._cache_times[key] = time.time()

    def clear_cache(self):
        """Clear all cached data to force fresh fetch."""
        self._cache.clear()
        self._cache_times.clear()
        logger.info("Jenkins cache cleared")

    async def _make_request(self, url: str, use_gr_auth: bool = False) -> Dict:
        """Make authenticated request to Jenkins API."""
        cache_key = f"req:{url}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        headers = getattr(self, "_gr_auth_headers", self._auth_headers) if use_gr_auth else self._auth_headers

        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(url, headers=headers, timeout=30.0)
                    if response.status_code == 200:
                        data = response.json()
                        self._set_cache(cache_key, data)
                        return data
                    elif response.status_code == 401:
                        return {"error": "Authentication failed"}
                    elif response.status_code == 404:
                        return {"error": "Not found"}
                    else:
                        return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error("Jenkins API request failed for %s: %s", url, e)
            return {"error": str(e)}

    async def _get_text(self, url: str, use_gr_auth: bool = False) -> Optional[str]:
        """Get text content from URL."""
        headers = getattr(self, "_gr_auth_headers", self._auth_headers) if use_gr_auth else self._auth_headers

        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(url, headers=headers, timeout=30.0)
                    if response.status_code == 200:
                        return response.text
        except Exception as e:
            logger.warning("Failed to get text from %s: %s", url, e)
        return None

    async def get_test_report(self, job_name: str, build_number: int, view_name: str = None) -> Optional[Dict]:
        """
        Get test report for a build with parsed failed tests.

        Handles multiple Jenkins test report formats:
        - Standard JUnit: suites[cases] structure
        - Aggregated reports: childReports[child[suites[cases]]] structure
        """
        # Build paths to try
        paths_to_try = [
            f"{self.base_url}/job/{job_name}/{build_number}/testReport/api/json",
        ]

        if view_name:
            paths_to_try.extend(
                [
                    f"{self.base_url}/view/{view_name}/job/{job_name}/{build_number}/testReport/api/json",
                    f"{self.base_url}/job/{view_name}/job/{job_name}/{build_number}/testReport/api/json",
                ]
            )

        # Handle nested job paths (folder/job format)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try.insert(0, f"{self.base_url}/job/{nested_path}/{build_number}/testReport/api/json")

        result = None
        for url in paths_to_try:
            result = await self._make_request(url)
            if result and "error" not in result:
                logger.debug("Found test report at: %s", url)
                break
            result = None

        if not result:
            logger.warning("No test report found for %s build #%s", job_name, build_number)
            return None

        # Extract counts
        total_count = result.get("totalCount", 0)
        pass_count = result.get("passCount", 0)
        fail_count = result.get("failCount", 0)
        skip_count = result.get("skipCount", 0)
        root_counts_are_zero = total_count == 0

        # Extract failed tests
        failed_tests = []

        def extract_failed_from_cases(cases: list):
            for case in cases:
                status = case.get("status", "")
                if status in ("FAILED", "REGRESSION"):
                    failed_tests.append(
                        {
                            "name": case.get("name"),
                            "className": case.get("className"),
                            "duration": case.get("duration"),
                            "status": status,
                            "errorMessage": (case.get("errorDetails") or case.get("errorStackTrace") or "")[:500],
                            "stackTrace": (case.get("errorStackTrace") or "")[:1000],
                        }
                    )

        def extract_failed_from_suites(suites: list):
            for suite in suites:
                cases = suite.get("cases", [])
                extract_failed_from_cases(cases)

        # Try standard suites structure
        if "suites" in result and result["suites"]:
            extract_failed_from_suites(result["suites"])

        # Try childReports structure
        elif "childReports" in result:
            for child_report in result.get("childReports", []):
                child = child_report.get("child", {})
                if "suites" in child:
                    extract_failed_from_suites(child["suites"])

                if root_counts_are_zero:
                    if "result" in child_report:
                        child_result = child_report["result"]
                        if "suites" in child_result and "suites" not in child:
                            extract_failed_from_suites(child_result["suites"])
                        total_count += child_result.get("totalCount", 0)
                        pass_count += child_result.get("passCount", 0)
                        fail_count += child_result.get("failCount", 0)
                        skip_count += child_result.get("skipCount", 0)
                    elif child.get("totalCount", 0) > 0 or child.get("passCount", 0) > 0:
                        total_count += child.get("totalCount", 0)
                        pass_count += child.get("passCount", 0)
                        fail_count += child.get("failCount", 0)
                        skip_count += child.get("skipCount", 0)

        # Try cases at root level
        if not failed_tests and fail_count > 0 and "cases" in result:
            extract_failed_from_cases(result["cases"])

        return {
            "totalCount": total_count,
            "passCount": pass_count,
            "failCount": fail_count,
            "skipCount": skip_count,
            "duration": result.get("duration"),
            "failedTests": failed_tests,
        }

    async def get_build_changes(self, job_name: str, build_number: int, build_url: str = None) -> Optional[Dict]:
        """
        Get commits and changed files for a build.

        Args:
            job_name: Jenkins job name
            build_number: Build number
            build_url: Optional full build URL (for multibranch pipelines)

        Returns:
            {
                "commits": [
                    {
                        "id": "abc123",
                        "message": "Fix bug in feature X",
                        "author": "John Doe",
                        "timestamp": "2024-01-01T12:00:00",
                        "files": ["src/file1.py", "src/file2.py"]
                    }
                ],
                "totalCommits": 3,
                "totalFilesChanged": 15
            }
        """
        # Use build_url if provided (for multibranch pipelines), otherwise construct it
        if build_url:
            # Strip trailing slash and append api/json
            base_url = build_url.rstrip("/")
            url = f"{base_url}/api/json?tree=changeSets[items[commitId,msg,author[fullName],timestamp,affectedPaths]]"
        else:
            url = f"{self.base_url}/job/{job_name}/{build_number}/api/json?tree=changeSets[items[commitId,msg,author[fullName],timestamp,affectedPaths]]"

        result = await self._make_request(url)

        if result.get("error"):
            logger.warning("Could not get changes for %s #%s: %s", job_name, build_number, result.get("error"))
            return None

        commits = []
        total_files = 0

        for change_set in result.get("changeSets", []):
            for item in change_set.get("items", []):
                affected_paths = item.get("affectedPaths", [])
                total_files += len(affected_paths)

                commits.append(
                    {
                        "id": item.get("commitId", "")[:8] if item.get("commitId") else "",
                        "fullId": item.get("commitId", ""),
                        "message": item.get("msg", "").split("\n")[0][:200],  # First line, truncated
                        "author": item.get("author", {}).get("fullName", "Unknown"),
                        "timestamp": item.get("timestamp"),
                        "files": affected_paths[:20],  # Limit files per commit
                        "totalFiles": len(affected_paths),
                    }
                )

        return {"commits": commits, "totalCommits": len(commits), "totalFilesChanged": total_files}

    async def get_test_report_by_url(self, build_url: str) -> Optional[Dict]:
        """
        Get test report using the build's actual URL (for multibranch pipelines).

        Args:
            build_url: The full build URL from Jenkins (e.g., https://jenkins/job/pipe/job/branch/123/)
        """
        if not build_url:
            return None

        url = f"{build_url.rstrip('/')}/testReport/api/json"
        result = await self._make_request(url)

        if result and result.get("error"):
            logger.debug("No test report at %s", url)
            return None

        if not result:
            return None

        # Reuse the same parsing logic as get_test_report
        total_count = result.get("totalCount", 0)
        pass_count = result.get("passCount", 0)
        fail_count = result.get("failCount", 0)
        skip_count = result.get("skipCount", 0)

        failed_tests = []

        def extract_failed_from_cases(cases: list):
            for case in cases:
                status = case.get("status", "")
                if status in ("FAILED", "REGRESSION"):
                    failed_tests.append(
                        {
                            "name": case.get("name"),
                            "className": case.get("className"),
                            "duration": case.get("duration"),
                            "status": status,
                            "errorMessage": (case.get("errorDetails") or case.get("errorStackTrace") or "")[:500],
                            "stackTrace": (case.get("errorStackTrace") or "")[:1000],
                        }
                    )

        # Extract from suites
        for suite in result.get("suites", []):
            extract_failed_from_cases(suite.get("cases", []))

        # Extract from childReports
        for child in result.get("childReports", []):
            child_result = child.get("result", {})
            for suite in child_result.get("suites", []):
                extract_failed_from_cases(suite.get("cases", []))

        return {
            "totalCount": total_count,
            "passCount": pass_count,
            "failCount": fail_count,
            "skipCount": skip_count,
            "failedTests": failed_tests,
        }

    async def get_console_output_by_url(self, build_url: str) -> Optional[Dict]:
        """
        Get console output using the build's actual URL (for multibranch pipelines).

        Args:
            build_url: The full build URL from Jenkins
        """
        if not build_url:
            return None

        url = f"{build_url.rstrip('/')}/consoleText"
        text = await self._get_text(url)

        if not text:
            return None

        lines = text.split("\n")
        error_keywords = ("error", "failed", "exception")
        error_lines = [line for line in lines if any(kw in line.lower() for kw in error_keywords)]

        return {
            "output": "\n".join(lines[-100:]),
            "errorLines": error_lines[-20:],
        }

    async def get_console_output(self, job_name: str, build_number: int, view_name: str = None) -> Optional[Dict]:
        """Get console output for a build with error line extraction."""
        paths_to_try = [
            f"{self.base_url}/job/{job_name}/{build_number}/consoleText",
        ]

        if view_name:
            paths_to_try.extend(
                [
                    f"{self.base_url}/view/{view_name}/job/{job_name}/{build_number}/consoleText",
                    f"{self.base_url}/job/{view_name}/job/{job_name}/{build_number}/consoleText",
                ]
            )

        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try.insert(0, f"{self.base_url}/job/{nested_path}/{build_number}/consoleText")

        text = None
        for url in paths_to_try:
            text = await self._get_text(url)
            if text:
                logger.debug("Found console output at: %s", url)
                break

        if not text:
            return None

        lines = text.split("\n")
        error_keywords = ("error", "failed", "exception")
        error_lines = [line for line in lines if any(kw in line.lower() for kw in error_keywords)]

        return {
            "output": "\n".join(lines[-100:]),
            "errorLines": error_lines[-20:],
        }


class JenkinsClient(JenkinsClientBase):
    """Client for Jenkins API with authentication, caching, and connection pooling."""

    def __init__(self):
        self.base_url = os.getenv("JENKINS_URL", "http://jenkins03-int.stg01-mp.nc4.iad0.nsscloud.net:8080").rstrip("/")
        self.username = os.getenv("JENKINS_USER", "")
        self.token = os.getenv("JENKINS_TOKEN", "")
        self.view_name = os.getenv("JENKINS_VIEW", "Your-Product")

        # Golden Regression Suite URL and separate credentials
        self.golden_regression_url = os.getenv("JENKINS_GOLDEN_REGRESSION_URL")
        self.gr_username = os.getenv("JENKINS_GR_USER", "")
        self.gr_token = os.getenv("JENKINS_GR_TOKEN", "")

        # List of jobs to monitor (required in .env)
        env_jobs = os.getenv("JENKINS_JOBS", "")
        self.monitored_jobs = [j.strip() for j in env_jobs.split(",") if j.strip()]
        if not self.monitored_jobs:
            logger.warning("JENKINS_JOBS not configured in .env - pipeline monitoring disabled")

        # PDV-specific jobs to monitor (optional in .env)
        # If not configured, will dynamically fetch from JENKINS_BACKEND_PDV_URL
        env_pdv_jobs = os.getenv("JENKINS_PDV_JOBS", "")
        self.pdv_jobs = [j.strip() for j in env_pdv_jobs.split(",") if j.strip()]
        if self.pdv_jobs:
            logger.info(f"JENKINS_PDV_JOBS configured: {len(self.pdv_jobs)} jobs")

        # Backend PDV Jenkins URL for dynamic job discovery
        self.backend_pdv_url = os.getenv("JENKINS_BACKEND_PDV_URL", "").rstrip("/")
        if self.backend_pdv_url:
            logger.info(f"JENKINS_BACKEND_PDV_URL configured: {self.backend_pdv_url}")

        # Backend PDV Jenkins credentials (optional - falls back to GR creds, then main creds)
        self.backend_pdv_username = os.getenv("JENKINS_BACKEND_PDV_USER", "")
        self.backend_pdv_token = os.getenv("JENKINS_BACKEND_PDV_TOKEN", "")

        # Pre-compute auth header for main Jenkins
        if self.username and self.token:
            credentials = f"{self.username}:{self.token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_headers = {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}
        else:
            self._auth_headers = {}
            logger.warning("Jenkins credentials not configured - set JENKINS_USER and JENKINS_TOKEN")

        # Pre-compute auth header for Golden Regression (use GR-specific creds if provided, else fall back to main creds)
        gr_user = self.gr_username or self.username
        gr_token = self.gr_token or self.token
        if gr_user and gr_token:
            gr_credentials = f"{gr_user}:{gr_token}"
            gr_encoded = base64.b64encode(gr_credentials.encode()).decode()
            self._gr_auth_headers = {"Authorization": f"Basic {gr_encoded}", "Content-Type": "application/json"}
        else:
            self._gr_auth_headers = self._auth_headers  # Fall back to main auth

        # Pre-compute auth header for Backend PDV (use Backend PDV creds if provided, else GR creds, else main creds)
        backend_pdv_user = self.backend_pdv_username or gr_user or self.username
        backend_pdv_token = self.backend_pdv_token or gr_token or self.token
        if backend_pdv_user and backend_pdv_token:
            backend_pdv_credentials = f"{backend_pdv_user}:{backend_pdv_token}"
            backend_pdv_encoded = base64.b64encode(backend_pdv_credentials.encode()).decode()
            self._backend_pdv_auth_headers = {
                "Authorization": f"Basic {backend_pdv_encoded}",
                "Content-Type": "application/json",
            }
            # Log which credentials are being used for Backend PDV
            if self.backend_pdv_username and self.backend_pdv_token:
                logger.info(f"Backend PDV auth: using JENKINS_BACKEND_PDV_USER ({self.backend_pdv_username})")
            elif gr_user and gr_token:
                logger.info(f"Backend PDV auth: falling back to JENKINS_GR_USER ({gr_user})")
            else:
                logger.info(f"Backend PDV auth: falling back to JENKINS_USER ({self.username})")
        else:
            self._backend_pdv_auth_headers = self._gr_auth_headers  # Fall back to GR auth
            logger.warning("Backend PDV auth: no credentials configured, using GR auth headers")

        # Caching for job/build info (longer TTL reduces load on Jenkins)
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 120  # 2 minute cache

        # Semaphore to limit concurrent connections (prevents overwhelming Jenkins)
        # With retry logic + lightweight queries, we can increase to 8 concurrent
        self._max_concurrent = 8
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    def is_configured(self) -> bool:
        """Check if Jenkins client is properly configured."""
        return bool(self.username and self.token and self.base_url)

    def _extract_job_path_from_url(self, url: str) -> str:
        """
        Extract job path from a Jenkins URL.

        Example:
            Input: http://jenkins.../job/Your-Product/job/Windows/job/Pipelines/job/my_job/
            Output: Your-Product/Windows/Pipelines/my_job

        This is used to get the full folder path for jobs in nested folders.
        """
        if not url:
            return ""

        # Remove trailing slash and /api/json if present
        url = url.rstrip("/")
        if url.endswith("/api/json"):
            url = url[:-9]

        # Find the job path portion after base_url
        # Pattern: /job/folder1/job/folder2/job/jobname
        # Extract all job path segments
        matches = re.findall(r"/job/([^/]+)", url)
        if matches:
            return "/".join(matches)

        return ""

    async def _make_request(
        self, url: str, timeout: float = 30.0, use_cache: bool = True, max_retries: int = 2
    ) -> Dict:
        """Make authenticated request to Jenkins API with retry logic.

        Args:
            url: The Jenkins API URL
            timeout: Request timeout in seconds
            use_cache: Whether to use caching (default True)
            max_retries: Number of retries for transient failures (default 2)

        Returns:
            Dict with response data, or dict with "error" and "error_type" keys on failure.
            error_type can be: "not_found", "auth_failed", "timeout", "connection", "server_error"
        """
        import asyncio

        # Check cache first
        if use_cache:
            cached = self._get_cached(url)
            if cached is not None:
                return cached

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Use semaphore to limit concurrent connections (prevents overwhelming Jenkins)
                async with self._get_semaphore():
                    async with self._create_client() as client:
                        response = await client.get(url, headers=self._auth_headers, timeout=timeout)

                        if response.status_code == 200:
                            result = response.json()
                            if use_cache:
                                self._set_cache(url, result)
                            return result
                        elif response.status_code == 404:
                            # Don't retry 404s
                            return {"error": "Resource not found", "error_type": "not_found"}
                        elif response.status_code == 401:
                            # Don't retry auth failures
                            return {"error": "Authentication failed", "error_type": "auth_failed"}
                        elif response.status_code == 403:
                            return {"error": "Access forbidden", "error_type": "auth_failed"}
                        else:
                            last_error = {
                                "error": f"Jenkins returned HTTP {response.status_code}",
                                "error_type": "server_error",
                            }
                            # Retry on 5xx errors
                            if response.status_code >= 500 and attempt < max_retries:
                                wait_time = (attempt + 1) * 2
                                logger.warning(
                                    "Jenkins returned %s, retrying in %ss (attempt %d/%d)",
                                    response.status_code,
                                    wait_time,
                                    attempt + 1,
                                    max_retries,
                                )
                                await asyncio.sleep(wait_time)
                                continue
                            return last_error

            except httpx.TimeoutException as err:
                last_error = {"error": f"Request timed out: {err}", "error_type": "timeout"}
            except httpx.ConnectError as err:
                last_error = {"error": f"Connection failed: {err}", "error_type": "connection"}
            except httpx.RemoteProtocolError as err:
                # Server disconnected without sending a response
                last_error = {"error": f"Server disconnected: {err}", "error_type": "connection"}
            except httpx.HTTPError as err:
                last_error = {"error": f"HTTP error: {err}", "error_type": "connection"}
            except ValueError as err:
                # JSON parse error - don't retry
                logger.error("Invalid JSON response from %s: %s", url, err)
                return {"error": f"Invalid response: {err}", "error_type": "server_error"}

            # Retry on connection/timeout errors
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2  # 2s, 4s backoff
                logger.warning(
                    "Jenkins request failed, retrying in %ss (attempt %d/%d): %s",
                    wait_time,
                    attempt + 1,
                    max_retries,
                    url,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "Jenkins request failed after %d attempts for %s: %s",
                    max_retries + 1,
                    url,
                    last_error.get("error", "Unknown"),
                )

        return last_error or {"error": "Unknown error", "error_type": "unknown"}

    async def _get_text(self, url: str, timeout: float = 30.0) -> Optional[str]:
        """Get plain text response from Jenkins API."""
        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(url, headers=self._auth_headers, timeout=timeout)
                    if response.status_code == 200:
                        return response.text
        except (httpx.HTTPError, ValueError) as err:
            logger.error("Jenkins text request failed for %s: %s", url, err)
        return None

    def _format_duration(self, duration_ms: int) -> str:
        """Format duration in milliseconds to human readable string."""
        if not duration_ms:
            return ""
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) // 1000
        return f"{minutes}m {seconds}s"

    def _format_relative_time(self, timestamp: int) -> str:
        """Format timestamp as relative time string."""
        if not timestamp:
            return ""

        run_time = datetime.fromtimestamp(timestamp / 1000)
        delta = datetime.now() - run_time

        if delta.days > 0:
            return f"{delta.days}d ago"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        if delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        return "Just now"

    def _build_display_url(self, job_info: Dict, job_name: str) -> str:
        """
        Build a user-friendly display URL for a Jenkins job.

        Uses view-based URL format when a view is configured, with the
        display name for proper casing (e.g., NSClient_Backend_Addonman_Regression_Test).

        Args:
            job_info: Job info dict from Jenkins API (contains 'displayName', 'url')
            job_name: Original job name used for lookup

        Returns:
            URL string for display/linking purposes
        """
        # Get the display name from Jenkins (has proper casing)
        display_name = job_info.get("displayName", job_name)

        # If a view is configured, use the view-based URL format
        if self.view_name:
            return f"{self.base_url}/view/{self.view_name}/job/{display_name}/"

        # Otherwise, fall back to the URL from Jenkins API or construct one
        job_url = job_info.get("url", "").rstrip("/")
        if job_url:
            return f"{job_url}/"

        return f"{self.base_url}/job/{display_name}/"

    async def get_job_info(self, job_name: str) -> Dict:
        """Get information about a specific job.

        Returns:
            Job info dict, or dict with "error" and "error_type" keys on failure.
        """
        # Handle nested job paths (folder/job) - e.g., Your-Product/addonman_pdv
        if "/" in job_name:
            # Convert folder/job to /job/folder/job/jobname format
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try = [
                f"{self.base_url}/job/{nested_path}/api/json",
            ]
        else:
            # Try multiple paths for job location (non-nested jobs)
            paths_to_try = [
                f"{self.base_url}/job/{job_name}/api/json",
                f"{self.base_url}/view/{self.view_name}/job/{job_name}/api/json",
                f"{self.base_url}/job/{self.view_name}/job/{job_name}/api/json",
            ]

        last_error = None
        for url in paths_to_try:
            result = await self._make_request(url)
            # If successful (no error key), return the result
            if result and "error" not in result:
                return result
            # Track the last error (prefer connection/timeout errors over not_found)
            if result and result.get("error_type") != "not_found":
                last_error = result

        # If all paths failed, return appropriate error
        if last_error:
            # Return the last connection/timeout error
            return last_error
        # All paths returned not_found
        return {"error": f"Job '{job_name}' not found in Jenkins", "error_type": "not_found"}

    async def get_build_info(self, job_name: str, build_number: int) -> Optional[Dict]:
        """Get information about a specific build."""
        # Handle nested job paths (folder/job)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            url = f"{self.base_url}/job/{nested_path}/{build_number}/api/json"
        else:
            url = f"{self.base_url}/job/{job_name}/{build_number}/api/json"

        result = await self._make_request(url)
        # Return None if error (for backward compatibility with callers)
        if result and result.get("error"):
            logger.warning("Failed to get build info for %s #%s: %s", job_name, build_number, result.get("error"))
            return None
        return result

    async def get_build_parameters(self, job_name: str, build_number: int) -> Dict[str, str]:
        """
        Extract build parameters (including 'stack') from a specific build.

        Jenkins stores parameters in the build's 'actions' array under ParametersAction.

        Args:
            job_name: Jenkins job name (can be nested path like folder/job)
            build_number: Build number to get parameters for

        Returns:
            Dict of parameter name -> value, e.g., {"stack": "fra2", "version": "133.1"}
        """
        # Handle nested job paths (folder/job)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            url = f"{self.base_url}/job/{nested_path}/{build_number}/api/json?tree=actions[parameters[name,value]]"
        else:
            url = f"{self.base_url}/job/{job_name}/{build_number}/api/json?tree=actions[parameters[name,value]]"

        result = await self._make_request(url, use_cache=True)
        if result.get("error"):
            logger.warning("Failed to get build parameters for %s #%s: %s", job_name, build_number, result.get("error"))
            return {}

        # Parse parameters from actions array
        # Jenkins structure: actions[{parameters: [{name, value}, ...]}]
        params = {}
        for action in result.get("actions", []):
            if action and "parameters" in action:
                for param in action["parameters"]:
                    name = param.get("name", "")
                    value = param.get("value", "")
                    if name:
                        params[name] = value if value is not None else ""

        return params

    async def get_test_report(self, job_name: str, build_number: int) -> Optional[Dict]:
        """Get test report for a build with parsed failed tests.

        Handles multiple Jenkins test report formats:
        - Standard JUnit: suites[cases] structure
        - Aggregated reports: childReports[child[suites[cases]]] structure
        - pytest/Robot: May have different structures
        """
        # Try multiple paths for job location (handles nested jobs in folders)
        paths_to_try = [
            f"{self.base_url}/job/{job_name}/{build_number}/testReport/api/json",
            f"{self.base_url}/view/{self.view_name}/job/{job_name}/{build_number}/testReport/api/json",
            f"{self.base_url}/job/{self.view_name}/job/{job_name}/{build_number}/testReport/api/json",
        ]

        # Handle nested job paths (folder/job format)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try.insert(0, f"{self.base_url}/job/{nested_path}/{build_number}/testReport/api/json")

        result = None
        for url in paths_to_try:
            result = await self._make_request(url)
            # Check if we got a valid result (not an error)
            if result and "error" not in result:
                logger.debug("Found test report at: %s", url)
                break
            result = None  # Reset to None if it was an error

        if not result:
            logger.warning("No test report found for %s build #%s", job_name, build_number)
            return None

        # Extract counts - check multiple possible locations
        total_count = result.get("totalCount", 0)
        pass_count = result.get("passCount", 0)
        fail_count = result.get("failCount", 0)
        skip_count = result.get("skipCount", 0)

        # Track if root counts are 0 (need to aggregate from children)
        root_counts_are_zero = total_count == 0

        # Log the raw structure for debugging
        logger.debug(
            "Test report structure for %s #%s: totalCount=%s, passCount=%s, failCount=%s, "
            "has_suites=%s, has_childReports=%s",
            job_name,
            build_number,
            total_count,
            pass_count,
            fail_count,
            "suites" in result,
            "childReports" in result,
        )

        # Extract and format failed tests from various structures
        failed_tests = []

        def extract_failed_from_cases(cases: list):
            """Extract failed tests from a list of test cases."""
            for case in cases:
                status = case.get("status", "")
                if status in ("FAILED", "REGRESSION", "FIXED"):
                    # FIXED means it was failing before and now passes, but we track FAILED/REGRESSION
                    if status != "FIXED":
                        failed_tests.append(
                            {
                                "name": case.get("name"),
                                "className": case.get("className"),
                                "duration": case.get("duration"),
                                "status": status,
                                "errorMessage": (case.get("errorDetails") or case.get("errorStackTrace") or "")[:500],
                                "stackTrace": (case.get("errorStackTrace") or "")[:1000],
                            }
                        )

        def extract_failed_from_suites(suites: list):
            """Extract failed tests from suites structure."""
            for suite in suites:
                cases = suite.get("cases", [])
                extract_failed_from_cases(cases)

        # Try standard suites structure first
        if "suites" in result and result["suites"]:
            extract_failed_from_suites(result["suites"])

        # Try childReports structure (aggregated test results from multiple publishers)
        elif "childReports" in result:
            for child_report in result.get("childReports", []):
                child = child_report.get("child", {})
                if "suites" in child:
                    extract_failed_from_suites(child["suites"])

                # Aggregate counts from child reports if root counts were 0
                # Check both child_report["result"] and child_report["child"] for counts
                if root_counts_are_zero:
                    # First try child_report["result"] (most common)
                    if "result" in child_report:
                        child_result = child_report["result"]
                        # Extract from suites if not already done via child.suites
                        if "suites" in child_result and "suites" not in child:
                            extract_failed_from_suites(child_result["suites"])
                        total_count += child_result.get("totalCount", 0)
                        pass_count += child_result.get("passCount", 0)
                        fail_count += child_result.get("failCount", 0)
                        skip_count += child_result.get("skipCount", 0)
                    # Also try child_report["child"] directly (some plugins)
                    elif child.get("totalCount", 0) > 0 or child.get("passCount", 0) > 0:
                        total_count += child.get("totalCount", 0)
                        pass_count += child.get("passCount", 0)
                        fail_count += child.get("failCount", 0)
                        skip_count += child.get("skipCount", 0)

        # If still no failed tests but failCount > 0, try to find cases at root level
        if not failed_tests and fail_count > 0:
            # Some plugins put cases directly in result
            if "cases" in result:
                extract_failed_from_cases(result["cases"])
            # Log warning if we have failures but couldn't extract test details
            if not failed_tests:
                logger.warning(
                    "Test report for %s #%s shows %d failures but couldn't extract test details. "
                    "Report structure may be unsupported.",
                    job_name,
                    build_number,
                    fail_count,
                )

        # Log final counts for debugging (especially useful if counts were aggregated from children)
        if root_counts_are_zero and total_count > 0:
            logger.debug(
                "Aggregated test counts for %s #%s from childReports: total=%d, pass=%d, fail=%d, skip=%d",
                job_name,
                build_number,
                total_count,
                pass_count,
                fail_count,
                skip_count,
            )
        elif total_count == 0 and "childReports" in result:
            # Log warning if we have childReports but still got 0 counts
            child_report_count = len(result.get("childReports", []))
            logger.warning(
                "Test report for %s #%s has %d childReports but total count is still 0. "
                "Check if test report structure is supported.",
                job_name,
                build_number,
                child_report_count,
            )

        return {
            "totalCount": total_count,
            "passCount": pass_count,
            "failCount": fail_count,
            "skipCount": skip_count,
            "duration": result.get("duration"),
            "failedTests": failed_tests,
        }

    async def get_raw_test_report(self, job_name: str, build_number: int, max_retries: int = 2) -> Optional[Dict]:
        """
        Get raw test report data for flaky test analysis.

        Returns the unprocessed Jenkins test report with full suites/cases data.
        This is needed for flaky test analysis which requires all test results,
        not just failures.

        Args:
            job_name: Jenkins job name
            build_number: Build number
            max_retries: Max retry attempts for transient failures (default 2)

        Returns:
            Raw Jenkins test report dict with suites[cases] structure, or None if not found.
        """
        import asyncio

        # Try multiple paths for job location - prioritize most common patterns
        paths_to_try = [
            f"{self.base_url}/job/{job_name}/{build_number}/testReport/api/json",
        ]

        # Only add alternative paths if first one fails with 404
        alternate_paths = [
            f"{self.base_url}/view/{self.view_name}/job/{job_name}/{build_number}/testReport/api/json",
            f"{self.base_url}/job/{self.view_name}/job/{job_name}/{build_number}/testReport/api/json",
        ]

        # Handle nested job paths (folder/job format)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try.insert(0, f"{self.base_url}/job/{nested_path}/{build_number}/testReport/api/json")

        all_paths = paths_to_try + alternate_paths

        for url in all_paths:
            # Retry logic for transient failures (disconnects, timeouts)
            for attempt in range(max_retries + 1):
                result = await self._make_request(url, timeout=60.0)  # Longer timeout for test reports

                if result and "error" not in result:
                    logger.debug("Found raw test report at: %s", url)
                    return result

                # Check error type to decide if we should retry
                error_type = result.get("error_type", "") if result else ""

                # Don't retry on 404 or auth failures - try next URL instead
                if error_type in ("not_found", "auth_failed"):
                    break

                # Retry on connection/timeout errors
                if error_type in ("timeout", "connection") and attempt < max_retries:
                    wait_time = (attempt + 1) * 2  # 2s, 4s backoff
                    logger.warning("Retrying %s after %ss (attempt %d/%d)", url, wait_time, attempt + 1, max_retries)
                    await asyncio.sleep(wait_time)
                    continue

                # Unknown error or max retries reached, try next URL
                break

        logger.debug("No test report found for %s build #%s", job_name, build_number)
        return None

    async def get_lightweight_test_report(self, job_name: str, build_number: int) -> Optional[Dict]:
        """
        Get lightweight test report using tree query - MUCH faster than full report.

        Only fetches essential fields for flaky test analysis:
        - name, className, status, duration, errorDetails (for failure patterns)

        Returns:
            Dict with suites[cases] structure containing only essential fields.
        """
        # Tree query with errorDetails for failure pattern analysis
        tree_query = "suites[name,cases[name,className,status,duration,errorDetails]]"

        url = f"{self.base_url}/job/{job_name}/{build_number}/testReport/api/json?tree={tree_query}"

        result = await self._make_request(url, timeout=8.0)  # Short timeout for fast response

        if result and "error" not in result:
            return result

        # Try with view prefix if first attempt failed with 404
        if result and result.get("error_type") == "not_found":
            url = f"{self.base_url}/view/{self.view_name}/job/{job_name}/{build_number}/testReport/api/json?tree={tree_query}"
            result = await self._make_request(url, timeout=8.0)
            if result and "error" not in result:
                return result

        return None

    async def _check_pipeline_test_report_exists(self, client, job_url: str, build_number: int) -> bool:
        """Check if a test report exists for a regular pipeline build."""
        try:
            response = await client.head(
                f"{job_url}{build_number}/testReport/api/json",
                headers=self._auth_headers,
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    async def get_console_output(self, job_name: str, build_number: int) -> Optional[Dict]:
        """Get console output for a build with error line extraction."""
        # Try multiple paths for job location (handles nested jobs in folders)
        paths_to_try = [
            f"{self.base_url}/job/{job_name}/{build_number}/consoleText",
            f"{self.base_url}/view/{self.view_name}/job/{job_name}/{build_number}/consoleText",
            f"{self.base_url}/job/{self.view_name}/job/{job_name}/{build_number}/consoleText",
        ]

        # Handle nested job paths (folder/job format)
        if "/" in job_name:
            nested_path = "/job/".join(job_name.split("/"))
            paths_to_try.insert(0, f"{self.base_url}/job/{nested_path}/{build_number}/consoleText")

        text = None
        for url in paths_to_try:
            text = await self._get_text(url)
            if text:
                logger.debug("Found console output at: %s", url)
                break

        if not text:
            return None

        lines = text.split("\n")
        error_keywords = ("error", "failed", "exception")
        error_lines = [line for line in lines if any(kw in line.lower() for kw in error_keywords)]

        return {
            "output": "\n".join(lines[-100:]),  # Last 100 lines
            "errorLines": error_lines[-20:],  # Last 20 error lines
        }

    async def get_pipeline_builds(
        self, job_name: str, num_builds: int = 10, include_parameters: bool = False, check_test_reports: bool = True
    ) -> Dict[str, Any]:
        """Get last N builds for a specific pipeline.

        Args:
            job_name: Jenkins job name
            num_builds: Number of builds to fetch
            include_parameters: If True, include build parameters (e.g., stack) in each build
            check_test_reports: If True, check if test reports exist for failed builds (slower)
        """
        if not self.is_configured():
            return {"error": "Jenkins not configured", "error_type": "config", "builds": []}

        job_info = await self.get_job_info(job_name)
        if job_info.get("error"):
            # Propagate the error with type
            return {
                "error": job_info.get("error"),
                "error_type": job_info.get("error_type", "unknown"),
                "builds": [],
            }

        # Get canonical URL for API calls (from Jenkins response)
        api_url = job_info.get("url", "").rstrip("/")
        if not api_url:
            # Handle nested job paths (folder/job)
            if "/" in job_name:
                nested_path = "/job/".join(job_name.split("/"))
                api_url = f"{self.base_url}/job/{nested_path}"
            else:
                api_url = f"{self.base_url}/job/{job_name}"

        # Get display URL for user-facing links (view-based with proper casing)
        display_url = self._build_display_url(job_info, job_name)

        builds = []
        try:
            # Build tree query - include actions/parameters if requested (for stack extraction)
            if include_parameters:
                tree_query = f"builds[number,result,timestamp,duration,building,actions[parameters[name,value]]]{{0,{num_builds}}}"
            else:
                tree_query = f"builds[number,result,timestamp,duration,building]{{0,{num_builds}}}"

            async with self._create_client() as client:
                async with self._get_semaphore():
                    response = await client.get(
                        f"{api_url}/api/json?tree={tree_query}",
                        headers=self._auth_headers,
                    )

                if response.status_code != 200:
                    return {"error": f"Jenkins returned {response.status_code}", "builds": []}

                job_data = response.json()

                for build in job_data.get("builds", []):
                    build_number = build.get("number")
                    result = build.get("result")
                    building = build.get("building", False)

                    # Determine status
                    if building:
                        status = "running"
                    elif result == "SUCCESS":
                        status = "success"
                    elif result == "FAILURE":
                        status = "failed"
                    elif result == "UNSTABLE":
                        status = "unstable"
                    elif result == "ABORTED":
                        status = "aborted"
                    else:
                        status = "unknown"

                    # Default hasTestReport based on status
                    # Success builds typically have reports, aborted/running don't
                    has_test_report = status == "success"

                    build_data = {
                        "buildNumber": build_number,
                        "status": status,
                        "timestamp": self._format_relative_time(build.get("timestamp", 0)),
                        "timestampMs": build.get("timestamp", 0),  # Raw timestamp for sorting
                        "duration": self._format_duration(build.get("duration", 0)),
                        "url": f"{display_url}{build_number}/",
                        "hasTestReport": has_test_report,
                    }

                    # Extract stack parameter from actions if include_parameters is True
                    if include_parameters:
                        stack = ""
                        for action in build.get("actions", []):
                            if action and "parameters" in action:
                                for param in action["parameters"]:
                                    # Check both lowercase and uppercase STACK parameter
                                    if param.get("name", "").lower() == "stack":
                                        stack = param.get("value", "").lower().strip()
                                        break
                                if stack:
                                    break

                        # Include stack in build data (empty string if not found)
                        # Let the calling code decide whether to filter by stack
                        build_data["stack"] = stack if stack else "no stack"

                    builds.append(build_data)

                # Check test reports for failed/unstable builds in parallel (optional, slower)
                if check_test_reports:
                    builds_to_check = [b for b in builds if b["status"] in ("failed", "unstable")]
                    if builds_to_check:

                        async def check_report(build_data):
                            exists = await self._check_pipeline_test_report_exists(
                                client, display_url, build_data["buildNumber"]
                            )
                            build_data["hasTestReport"] = exists

                        await asyncio.gather(*[check_report(b) for b in builds_to_check])

        except httpx.TimeoutException as e:
            logger.error("Timeout fetching builds for %s: %s", job_name, e)
            return {"error": f"Request timed out: {e}", "error_type": "timeout", "builds": []}
        except httpx.ConnectError as e:
            logger.error("Connection error fetching builds for %s: %s", job_name, e)
            return {"error": f"Connection failed: {e}", "error_type": "connection", "builds": []}
        except Exception as e:
            logger.error("Error fetching builds for %s: %s", job_name, e)
            return {"error": str(e), "error_type": "unknown", "builds": []}

        return {
            "jobName": job_name,
            "displayName": job_info.get("displayName", job_name),
            "jobUrl": display_url,
            "builds": builds,
            "dataSource": "jenkins-direct",
        }

    async def _fetch_single_pipeline(
        self, job_name: str, include_builds: bool = False, num_builds: int = 10
    ) -> Optional[Tuple[Dict, str]]:
        """Fetch info for a single pipeline. Returns (pipeline_data, status) or None.

        OPTIMIZATION: When include_builds=True, we skip the separate get_build_info() call
        and extract last build info from the builds list, reducing API calls from 3 to 2.
        """
        job_info = await self.get_job_info(job_name)
        if not job_info or job_info.get("error"):
            return None

        # Get API URL for internal requests
        api_url = job_info.get("url", "").rstrip("/")
        if not api_url:
            api_url = f"{self.base_url}/job/{job_name}"

        # Get display URL for user-facing links (view-based with proper casing)
        display_url = self._build_display_url(job_info, job_name)

        last_build = job_info.get("lastBuild") or {}
        last_build_number = last_build.get("number")
        if not last_build_number:
            return None

        # Extract full job path from URL for TFA endpoint
        job_path = self._extract_job_path_from_url(api_url) or job_name

        # OPTIMIZATION: When include_builds=True, get build info from builds list
        # This reduces API calls from 3 to 2 per pipeline
        if include_builds:
            # Fetch builds first (includes parameters for stack info)
            # Skip test report checks for faster loading
            builds_data = await self.get_pipeline_builds(
                job_path, num_builds, include_parameters=True, check_test_reports=False
            )
            builds = builds_data.get("builds", [])

            if not builds:
                return None

            # Extract last build info from the builds list
            last_build_info = builds[0] if builds else {}
            status = last_build_info.get("status", "unknown")

            pipeline = {
                "name": job_info.get("displayName", job_name),
                "fullName": job_path,
                "status": status,
                "lastRun": last_build_info.get("timestamp", ""),
                "duration": last_build_info.get("duration", ""),
                "buildNumber": last_build_info.get("buildNumber", last_build_number),
                "url": display_url,
                "recentBuilds": builds,
            }
            return (pipeline, status)
        else:
            # Original flow: fetch build info separately (for when we don't need builds list)
            build_info = await self.get_build_info(job_name, last_build_number)
            if not build_info:
                return None

            # Determine status
            result = build_info.get("result")
            if result == "SUCCESS":
                status = "success"
            elif result == "FAILURE":
                status = "failed"
            elif result == "UNSTABLE":
                status = "unstable"
            elif result == "ABORTED":
                status = "aborted"
            elif result is None and build_info.get("building"):
                status = "running"
            else:
                status = "unknown"

            pipeline = {
                "name": job_info.get("displayName", job_name),
                "fullName": job_path,
                "status": status,
                "lastRun": self._format_relative_time(build_info.get("timestamp", 0)),
                "duration": self._format_duration(build_info.get("duration", 0)),
                "buildNumber": last_build_number,
                "url": display_url,
            }
            return (pipeline, status)

    async def get_pipelines(self, include_builds: bool = False, num_builds: int = 10) -> Dict[str, Any]:
        """Get status of all monitored pipelines using parallel fetching.

        Args:
            include_builds: If True, include last N builds for each pipeline
            num_builds: Number of builds to include (if include_builds=True)

        Optimization: Fetches all pipelines in parallel using asyncio.gather
        instead of sequential API calls.
        """
        if not self.is_configured():
            return {
                "error": "Jenkins not configured",
                "overall": {"totalPipelines": 0, "passing": 0, "failing": 0, "unstable": 0, "healthPercent": 0},
                "pipelines": [],
            }

        # Fetch pipelines in parallel - semaphore limits to 5 concurrent
        tasks = [self._fetch_single_pipeline(job_name, include_builds, num_builds) for job_name in self.monitored_jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        pipelines = []
        passing = failing = unstable = 0

        for result in results:
            if result is None or isinstance(result, Exception):
                continue
            pipeline, status = result
            pipelines.append(pipeline)

            if status == "success":
                passing += 1
            elif status == "failed":
                failing += 1
            elif status == "unstable":
                unstable += 1

        total = len(pipelines)
        health_percent = round((passing / total * 100)) if total > 0 else 0

        return {
            "overall": {
                "totalPipelines": total,
                "passing": passing,
                "failing": failing,
                "unstable": unstable,
                "healthPercent": health_percent,
            },
            "pipelines": pipelines,
            "dataSource": "jenkins-direct",
        }

    async def _fetch_single_pdv_pipeline(
        self, job_name: str, include_builds: bool = False, num_builds: int = 10
    ) -> Optional[Tuple[Dict, str]]:
        """Fetch info for a single PDV pipeline. Returns (pipeline_data, status) or None.

        OPTIMIZATION: When include_builds=True, we skip the separate get_build_info() call
        and extract last build info from the builds list, reducing API calls from 3 to 2.
        """
        job_info = await self.get_job_info(job_name)
        if not job_info or job_info.get("error"):
            return None

        # Get API URL for internal requests
        api_url = job_info.get("url", "").rstrip("/")
        if not api_url:
            api_url = f"{self.base_url}/job/{job_name}"

        # Get display URL for user-facing links (view-based with proper casing)
        display_url = self._build_display_url(job_info, job_name)

        last_build = job_info.get("lastBuild") or {}
        last_build_number = last_build.get("number")
        if not last_build_number:
            return None

        job_path = self._extract_job_path_from_url(api_url) or job_name

        # OPTIMIZATION: When include_builds=True, get build info from builds list
        if include_builds:
            # Fetch builds first (includes parameters for stack info)
            # Skip test report checks for faster loading
            builds_data = await self.get_pipeline_builds(
                job_path, num_builds, include_parameters=True, check_test_reports=False
            )
            builds = builds_data.get("builds", [])

            if not builds:
                return None

            # Extract last build info from the builds list
            last_build_info = builds[0] if builds else {}
            status = last_build_info.get("status", "unknown")

            pipeline = {
                "name": job_info.get("displayName", job_name),
                "fullName": job_path,
                "status": status,
                "lastRun": last_build_info.get("timestamp", ""),
                "duration": last_build_info.get("duration", ""),
                "buildNumber": last_build_info.get("buildNumber", last_build_number),
                "url": display_url,
                "timestamp": last_build_info.get("timestampMs", 0),
                "recentBuilds": builds,
            }
            return (pipeline, status)
        else:
            # Original flow: fetch build info separately
            build_info = await self.get_build_info(job_name, last_build_number)
            if not build_info:
                return None

            result = build_info.get("result")
            if result == "SUCCESS":
                status = "success"
            elif result == "FAILURE":
                status = "failed"
            elif result == "UNSTABLE":
                status = "unstable"
            elif result == "ABORTED":
                status = "aborted"
            elif result is None and build_info.get("building"):
                status = "running"
            else:
                status = "unknown"

            pipeline = {
                "name": job_info.get("displayName", job_name),
                "fullName": job_path,
                "status": status,
                "lastRun": self._format_relative_time(build_info.get("timestamp", 0)),
                "duration": self._format_duration(build_info.get("duration", 0)),
                "buildNumber": last_build_number,
                "url": display_url,
                "timestamp": build_info.get("timestamp", 0),
            }
            return (pipeline, status)

    async def _discover_backend_pdv_jobs(self) -> List[str]:
        """Discover all job names from JENKINS_BACKEND_PDV_URL folder.

        Returns:
            List of job names found in the backend PDV folder.
        """
        if not self.backend_pdv_url:
            return []

        try:
            async with self._create_client() as client:
                async with self._get_semaphore():
                    response = await client.get(
                        f"{self.backend_pdv_url}/api/json?tree=jobs[name,url]",
                        headers=self._backend_pdv_auth_headers,  # Use Backend PDV auth
                        timeout=30.0,
                    )

                    if response.status_code in (401, 403):
                        logger.error(
                            f"Backend PDV authentication failed (HTTP {response.status_code}). "
                            "Set JENKINS_BACKEND_PDV_USER and JENKINS_BACKEND_PDV_TOKEN in .env"
                        )
                        return []
                    elif response.status_code != 200:
                        logger.error(f"Failed to fetch backend PDV jobs: HTTP {response.status_code}")
                        return []

                    data = response.json()
                    jobs = data.get("jobs", [])
                    job_names = [job.get("name") for job in jobs if job.get("name")]
                    logger.info(f"Discovered {len(job_names)} jobs from backend PDV Jenkins: {job_names}")
                    return job_names

        except Exception as e:
            logger.error(f"Error discovering backend PDV jobs: {e}")
            return []

    async def _fetch_backend_pdv_pipeline(
        self, job_name: str, include_builds: bool = False, num_builds: int = 10
    ) -> Optional[Tuple[Dict, str]]:
        """Fetch info for a single backend PDV pipeline from the backend PDV Jenkins.

        Similar to _fetch_single_pdv_pipeline but uses the backend_pdv_url.
        When include_builds=True, fetches multiple builds with stack parameters.
        """
        if not self.backend_pdv_url:
            return None

        job_url = f"{self.backend_pdv_url}/job/{job_name}"

        try:
            async with self._create_client() as client:
                # First get job info
                async with self._get_semaphore():
                    job_response = await client.get(
                        f"{job_url}/api/json",
                        headers=self._backend_pdv_auth_headers,
                        timeout=30.0,
                    )

                    if job_response.status_code != 200:
                        logger.warning(f"Backend PDV job {job_name} not found: HTTP {job_response.status_code}")
                        return None

                    job_info = job_response.json()

                last_build = job_info.get("lastBuild") or {}
                last_build_number = last_build.get("number")
                if not last_build_number:
                    logger.warning(f"Backend PDV job {job_name} has no builds")
                    return None

                if include_builds:
                    # Fetch multiple builds with parameters (for stack extraction)
                    tree_query = f"builds[number,result,timestamp,duration,building,actions[parameters[name,value]]]{{0,{num_builds}}}"
                    async with self._get_semaphore():
                        builds_response = await client.get(
                            f"{job_url}/api/json?tree={tree_query}",
                            headers=self._backend_pdv_auth_headers,
                            timeout=60.0,
                        )

                        if builds_response.status_code != 200:
                            return None

                        builds_data = builds_response.json()

                    builds = []
                    for build in builds_data.get("builds", []):
                        build_number = build.get("number")
                        result = build.get("result")
                        building = build.get("building", False)

                        if building:
                            status = "running"
                        elif result == "SUCCESS":
                            status = "success"
                        elif result == "FAILURE":
                            status = "failed"
                        elif result == "UNSTABLE":
                            status = "unstable"
                        elif result == "ABORTED":
                            status = "aborted"
                        else:
                            status = "unknown"

                        build_data = {
                            "buildNumber": build_number,
                            "status": status,
                            "timestamp": self._format_relative_time(build.get("timestamp", 0)),
                            "timestampMs": build.get("timestamp", 0),
                            "duration": self._format_duration(build.get("duration", 0)),
                            "url": f"{job_url}/{build_number}/",
                            "hasTestReport": status == "success",
                        }

                        # Extract stack parameter from build actions
                        stack = ""
                        for action in build.get("actions", []):
                            if action and "parameters" in action:
                                for param in action["parameters"]:
                                    if param.get("name", "").lower() == "stack":
                                        stack = param.get("value", "").lower().strip()
                                        break
                                if stack:
                                    break

                        build_data["stack"] = stack if stack else "no stack"
                        builds.append(build_data)

                    if not builds:
                        return None

                    last_build_info = builds[0]
                    status = last_build_info.get("status", "unknown")

                    pipeline = {
                        "name": job_info.get("displayName", job_name),
                        "fullName": job_name,
                        "status": status,
                        "lastRun": last_build_info.get("timestamp", ""),
                        "duration": last_build_info.get("duration", ""),
                        "buildNumber": last_build_info.get("buildNumber", last_build_number),
                        "url": f"{job_url}/",
                        "timestamp": last_build_info.get("timestampMs", 0),
                        "recentBuilds": builds,
                    }
                    return (pipeline, status)
                else:
                    # Simple flow: just get last build info
                    async with self._get_semaphore():
                        build_response = await client.get(
                            f"{job_url}/{last_build_number}/api/json",
                            headers=self._backend_pdv_auth_headers,
                            timeout=30.0,
                        )

                        if build_response.status_code != 200:
                            return None

                        build_info = build_response.json()

                    result = build_info.get("result")
                    if result == "SUCCESS":
                        status = "success"
                    elif result == "FAILURE":
                        status = "failed"
                    elif result == "UNSTABLE":
                        status = "unstable"
                    elif result == "ABORTED":
                        status = "aborted"
                    elif result is None and build_info.get("building"):
                        status = "running"
                    else:
                        status = "unknown"

                    pipeline = {
                        "name": job_info.get("displayName", job_name),
                        "fullName": job_name,
                        "status": status,
                        "lastRun": self._format_relative_time(build_info.get("timestamp", 0)),
                        "duration": self._format_duration(build_info.get("duration", 0)),
                        "buildNumber": last_build_number,
                        "url": f"{job_url}/",
                        "timestamp": build_info.get("timestamp", 0),
                    }
                    return (pipeline, status)

        except Exception as e:
            logger.error(f"Error fetching backend PDV pipeline {job_name}: {e}")
            return None

    async def get_backend_pdv_test_report(self, job_name: str, build_number: int) -> Optional[Dict[str, Any]]:
        """Fetch test report for a Backend PDV build.

        Args:
            job_name: Job name (e.g., 'nsclient_backend_addonman_pdv_test')
            build_number: Build number

        Returns:
            Dict with passCount, failCount, skipCount, totalCount, failedTests
            or None if not found/error
        """
        if not self.backend_pdv_url:
            logger.warning("Backend PDV URL not configured")
            return None

        test_report_url = f"{self.backend_pdv_url}/job/{job_name}/{build_number}/testReport/api/json"
        logger.info(f"Fetching Backend PDV test report from: {test_report_url}")

        try:
            async with self._create_client() as client:
                async with self._get_semaphore():
                    response = await client.get(
                        test_report_url,
                        headers=self._backend_pdv_auth_headers,
                        timeout=30.0,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        # Parse failed tests from test report
                        failed_tests = []
                        for suite in data.get("suites", []):
                            for case in suite.get("cases", []):
                                if case.get("status") in ("FAILED", "REGRESSION"):
                                    failed_tests.append(
                                        {
                                            "name": case.get("name", ""),
                                            "className": case.get("className", ""),
                                            "errorMessage": case.get("errorDetails", "")
                                            or (case.get("errorStackTrace", "") or "")[:500],
                                            "stackTrace": case.get("errorStackTrace", ""),
                                            "duration": case.get("duration", 0),
                                        }
                                    )
                        return {
                            "passCount": data.get("passCount", 0),
                            "failCount": data.get("failCount", 0),
                            "skipCount": data.get("skipCount", 0),
                            "totalCount": data.get("passCount", 0)
                            + data.get("failCount", 0)
                            + data.get("skipCount", 0),
                            "failedTests": failed_tests,
                        }
                    elif response.status_code == 404:
                        logger.warning(f"No test report found for Backend PDV {job_name} #{build_number}")
                        return None
                    elif response.status_code in (401, 403):
                        logger.error(
                            f"Backend PDV authentication failed (HTTP {response.status_code}). "
                            "Set JENKINS_BACKEND_PDV_USER and JENKINS_BACKEND_PDV_TOKEN in .env"
                        )
                        return {"error": "Authentication failed", "error_type": "auth_failed"}
                    else:
                        logger.warning(f"Failed to fetch Backend PDV test report: HTTP {response.status_code}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching Backend PDV test report for {job_name} #{build_number}: {e}")
            return None

    async def get_backend_pdv_console_output(self, job_name: str, build_number: int) -> str:
        """Fetch console output for a Backend PDV build.

        Args:
            job_name: Job name (e.g., 'nsclient_backend_addonman_pdv_test')
            build_number: Build number

        Returns:
            Console output text (truncated to 3000 chars) or empty string
        """
        if not self.backend_pdv_url:
            return ""

        console_url = f"{self.backend_pdv_url}/job/{job_name}/{build_number}/consoleText"
        logger.info(f"Fetching Backend PDV console from: {console_url}")

        try:
            async with self._create_client() as client:
                async with self._get_semaphore():
                    response = await client.get(
                        console_url,
                        headers=self._backend_pdv_auth_headers,
                        timeout=30.0,
                    )

                    if response.status_code == 200:
                        return response.text[:3000]
                    elif response.status_code in (401, 403):
                        logger.error(
                            f"Backend PDV authentication failed (HTTP {response.status_code}). "
                            "Set JENKINS_BACKEND_PDV_USER and JENKINS_BACKEND_PDV_TOKEN in .env"
                        )
                        return ""
                    else:
                        logger.warning(f"Failed to fetch Backend PDV console: HTTP {response.status_code}")
                        return ""
        except Exception as e:
            logger.warning(f"Error fetching Backend PDV console for {job_name} #{build_number}: {e}")
            return ""

    async def get_pdv_pipelines(self, include_builds: bool = False, num_builds: int = 10) -> Dict[str, Any]:
        """Get status of PDV-specific pipelines using parallel fetching.

        Priority order for job discovery:
        1. JENKINS_PDV_JOBS env var (explicit list)
        2. Dynamic discovery from JENKINS_BACKEND_PDV_URL (if configured)
        3. Hardcoded default job names (fallback)

        Args:
            include_builds: If True, include last N builds for each pipeline
            num_builds: Number of builds to include (if include_builds=True)

        Optimization: Fetches all PDV pipelines in parallel.

        Environment Variables:
            JENKINS_PDV_JOBS: Comma-separated list of PDV job names
            JENKINS_BACKEND_PDV_URL: URL to backend PDV Jenkins folder for dynamic discovery
        """
        if not self.is_configured():
            return {
                "error": "Jenkins not configured",
                "overall": {"totalPipelines": 0, "passing": 0, "failing": 0, "unstable": 0, "healthPercent": 0},
                "pipelines": [],
            }

        # Priority 1: Use explicitly configured PDV jobs from JENKINS_PDV_JOBS env var
        if self.pdv_jobs:
            pdv_job_names = self.pdv_jobs
            logger.info(f"Using configured PDV jobs: {pdv_job_names}")
            use_backend_pdv_jenkins = False
        # Priority 2: Dynamically discover jobs from JENKINS_BACKEND_PDV_URL
        elif self.backend_pdv_url:
            pdv_job_names = await self._discover_backend_pdv_jobs()
            if pdv_job_names:
                logger.info(f"Using dynamically discovered PDV jobs from {self.backend_pdv_url}: {pdv_job_names}")
                use_backend_pdv_jenkins = True
            else:
                logger.warning("No jobs discovered from backend PDV URL, falling back to defaults")
                pdv_job_names = [
                    "nsclient_backend_addonman_pdv_test",
                    "nsclient_backend_deviceclassification_pdv_test",
                    "nsclient_backend_enrollment_service_pdv_test",
                    "nsclient_backend_otp_pdv_test",
                    "nsclient_backend_provisioner_steering_pdv",
                ]
                use_backend_pdv_jenkins = False
        else:
            # Priority 3: Fallback to hardcoded default job names
            pdv_job_names = [
                "nsclient_backend_addonman_pdv_test",
                "nsclient_backend_deviceclassification_pdv_test",
                "nsclient_backend_enrollment_service_pdv_test",
                "nsclient_backend_otp_pdv_test",
                "nsclient_backend_provisioner_steering_pdv",
            ]
            logger.warning("JENKINS_PDV_JOBS and JENKINS_BACKEND_PDV_URL not configured, using default job names")
            use_backend_pdv_jenkins = False

        # Fetch PDV pipelines in parallel with semaphore limiting concurrency
        if use_backend_pdv_jenkins:
            tasks = [
                self._fetch_backend_pdv_pipeline(job_name, include_builds, num_builds) for job_name in pdv_job_names
            ]
        else:
            tasks = [
                self._fetch_single_pdv_pipeline(job_name, include_builds, num_builds) for job_name in pdv_job_names
            ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        pipelines = []
        passing = failing = unstable = 0

        for result in results:
            if result is None or isinstance(result, Exception):
                continue
            pipeline, status = result
            pipelines.append(pipeline)

            if status == "success":
                passing += 1
            elif status == "failed":
                failing += 1
            elif status == "unstable":
                unstable += 1

        total = len(pipelines)
        health_percent = round((passing / total * 100)) if total > 0 else 0

        return {
            "overall": {
                "totalPipelines": total,
                "passing": passing,
                "failing": failing,
                "unstable": unstable,
                "healthPercent": health_percent,
            },
            "pipelines": pipelines,
            "dataSource": "jenkins-backend-pdv" if use_backend_pdv_jenkins else "jenkins-pdv",
        }

    def _extract_stack_from_name(self, name: str) -> str:
        """Extract stack name from pipeline name."""
        # Known production stacks
        known_stacks = [
            "dfw3",
            "fra2",
            "lon3",
            "sin2",
            "zur2",
            "sjc2",
            "ruh1",
            "sv5",
            "sjc1",
            "fr4",
            "pbmm01",
            "fed01",
            "am2",
            "mel2",
            "stg01",
            "fed1mp",
            "devint",
            "stg01-mplegacy",
        ]

        name_lower = name.lower()
        for stack in known_stacks:
            if stack in name_lower:
                return stack.upper()

        # Try common patterns
        patterns = [
            r"[_\-/]([a-z]{2,4}\d+)[_\-/]",  # e.g., _dfw3_, -sjc1-
            r"[_\-/]([a-z]{2,4}\d+)$",  # e.g., _dfw3 at end
            r"^([a-z]{2,4}\d+)[_\-/]",  # e.g., dfw3_ at start
        ]
        for pattern in patterns:
            match = re.search(pattern, name_lower)
            if match:
                return match.group(1).upper()

        return "OTHER"

    async def _check_test_report_exists(self, build_number: int) -> bool:
        """Check if a test report exists for a Golden Regression build."""
        url = f"{self.golden_regression_url}/{build_number}/testReport/api/json?tree=failCount"
        try:
            # Create own client since this may be called outside the main client context
            async with self._create_client() as client:
                response = await client.get(
                    url,
                    headers=self._gr_auth_headers,
                    timeout=10.0,
                )
                exists = response.status_code == 200
                if not exists:
                    logger.debug("Test report check for build %d returned %d", build_number, response.status_code)
                return exists
        except Exception as e:
            logger.warning("Test report check failed for build %d: %s", build_number, e)
            return False

    async def get_golden_regression(self, num_builds: int = 10, start_build: int = 150) -> Dict[str, Any]:
        """
        Get Endpoint PDV Runs - Last N builds per stack.

        The Golden Regression Suite cycles through 14 stacks in order.
        This method fetches builds and groups them by stack, showing last N builds per stack.

        Args:
            num_builds: Number of builds to show per stack (default 10)
            start_build: Starting build number to fetch from (default 900)
        """
        if not self.is_configured():
            return {"error": "Jenkins not configured", "builds": [], "stackGroups": {}, "summary": {}}

        if not self.golden_regression_url:
            return {
                "error": "JENKINS_GOLDEN_REGRESSION_URL environment variable not configured",
                "builds": [],
                "stackGroups": {},
                "sortedStacks": [],
                "summary": {},
            }

        # Known stacks in order (as they cycle in Jenkins)
        STACKS_ORDER = [
            "fr4",
            "zur2",
            "am2",
            "sjc1",
            "sin2",
            "fed01",
            "sv5",
            "lon3",
            "pbmm01",
            "ruh1",
            "fra2",
            "mel2",
            "sjc2",
            "dfw3",
        ]
        NUM_STACKS = len(STACKS_ORDER)  # 14 stacks

        try:
            # Fetch enough builds to get last N per stack
            # Need at least NUM_STACKS * num_builds builds
            total_builds_needed = NUM_STACKS * num_builds + 20  # Extra buffer

            async with self._create_client() as client:
                async with self._get_semaphore():
                    response = await client.get(
                        f"{self.golden_regression_url}/api/json?tree=builds[number,result,timestamp,duration]{{0,{total_builds_needed}}}",
                        headers=self._gr_auth_headers,
                        timeout=120.0,
                    )

                    if response.status_code != 200:
                        return {
                            "error": f"Jenkins returned {response.status_code}",
                            "builds": [],
                            "stackGroups": {},
                            "summary": {},
                        }

                job_data = response.json()
                all_builds = job_data.get("builds", [])

            # Initialize stack groups
            stack_groups = {stack.upper(): [] for stack in STACKS_ORDER}
            all_builds_list = []
            success_count = 0
            failed_count = 0
            unstable_count = 0
            aborted_count = 0

            # Process each build and assign to appropriate stack
            for build in all_builds:
                build_number = build.get("number")
                if build_number is None:
                    continue

                # Filter builds starting from start_build
                if build_number < start_build:
                    continue

                result = build.get("result")
                timestamp = build.get("timestamp", 0)
                duration = build.get("duration", 0)

                # Determine which stack this build belongs to
                # Builds cycle through stacks: build % NUM_STACKS gives stack index
                # But we need to figure out the offset based on a known build
                # From GRS-WIN: Build #233 is fr4, #232 is zur2, #231 is sjc1, etc.
                # So: (233 - build_number) % 14 gives the stack offset from fr4
                stack_offset = (233 - build_number) % NUM_STACKS
                stack_name = STACKS_ORDER[stack_offset].upper()

                # Determine status
                if result == "SUCCESS":
                    status = "success"
                    success_count += 1
                elif result == "FAILURE":
                    status = "failed"
                    failed_count += 1
                elif result == "UNSTABLE":
                    status = "unstable"
                    unstable_count += 1
                elif result == "ABORTED":
                    status = "aborted"
                    aborted_count += 1
                elif result is None:
                    status = "running"
                else:
                    status = "unknown"

                # Format timestamp
                timestamp_str = ""
                if timestamp:
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")

                # Format duration
                duration_str = self._format_duration(duration) if duration else "-"

                # Default version (can be enhanced to fetch from build parameters)
                version = "133.1.0.2543"

                # For failed/unstable builds, hasTestReport will be checked later
                # For success builds, assume test report exists; for aborted/running, assume no test report
                has_test_report = status == "success"  # Default: success has reports, others don't

                build_info = {
                    "buildNumber": build_number,
                    "status": status,
                    "stack": stack_name,
                    "timestamp": timestamp_str,
                    "timestampMs": timestamp,  # Raw timestamp for sorting
                    "duration": duration_str,
                    "version": version,
                    "buildUrl": f"{self.golden_regression_url}/{build_number}/",
                    "passed": 11 if status == "success" else (0 if status == "aborted" else 5),
                    "failed": 0 if status == "success" else (0 if status == "aborted" else 6),
                    "hasTestReport": has_test_report,
                }

                all_builds_list.append(build_info)

                # Add to stack group (limit to num_builds per stack)
                if len(stack_groups[stack_name]) < num_builds:
                    stack_groups[stack_name].append(build_info)

                # Check test reports for failed/unstable builds in parallel (after for loop ends)

            # Check test reports for failed/unstable builds in parallel
            builds_to_check = [b for b in all_builds_list if b["status"] in ("failed", "unstable")]
            if builds_to_check:
                logger.info("Checking test reports for %d failed/unstable builds...", len(builds_to_check))

                async def check_report(build_info_to_check):
                    exists = await self._check_test_report_exists(build_info_to_check["buildNumber"])
                    build_info_to_check["hasTestReport"] = exists
                    return exists

                results = await asyncio.gather(*[check_report(b) for b in builds_to_check])
                logger.info("Test report check complete: %d/%d have reports", sum(results), len(results))

            # Sort stacks: those with failures first, then by stack order
            sorted_stacks = sorted(
                [s.upper() for s in STACKS_ORDER],
                key=lambda s: (
                    (
                        0
                        if any(b["status"] in ("failed", "unstable", "aborted") for b in stack_groups.get(s, []))
                        else 1
                    ),
                    STACKS_ORDER.index(s.lower()) if s.lower() in STACKS_ORDER else 99,
                ),
            )

            # Calculate summary stats
            total_builds = len(all_builds_list)
            success_rate = round((success_count / total_builds) * 100) if total_builds > 0 else 0

            return {
                "builds": all_builds_list,
                "stackGroups": stack_groups,
                "sortedStacks": sorted_stacks,
                "summary": {
                    "totalBuilds": total_builds,
                    "successCount": success_count,
                    "failedCount": failed_count,
                    "unstableCount": unstable_count,
                    "abortedCount": aborted_count,
                    "successRate": success_rate,
                    "totalStacks": NUM_STACKS,
                    # Backward compatibility
                    "successBuilds": success_count,
                    "failedBuilds": failed_count,
                    "unstableBuilds": unstable_count,
                },
                "jenkinsUrl": self.golden_regression_url,
                "dataSource": "jenkins-direct",
            }

        except Exception as e:
            logger.error("Error fetching Endpoint PDV Runs: %s", e)
            return {"error": str(e), "builds": [], "stackGroups": {}, "summary": {}}

    async def _get_golden_regression_builds(self, num_builds: int = 10) -> Dict[str, Any]:
        """Fallback: Get Golden Regression Suite data as builds (original behavior)."""
        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(
                        f"{self.golden_regression_url}/api/json?tree=builds[number,result,timestamp,duration]{{0,{num_builds}}}",
                        headers=self._gr_auth_headers,
                    )

                    if response.status_code != 200:
                        return {
                            "error": f"Jenkins returned {response.status_code}",
                            "builds": [],
                            "pipelines": [],
                            "summary": {},
                        }

                    job_data = response.json()
            builds_list = []
            success_builds = 0
            failed_builds = 0
            unstable_builds = 0

            for build in job_data.get("builds", []):
                build_number = build.get("number")
                result = build.get("result")
                timestamp = build.get("timestamp", 0)
                duration = build.get("duration", 0)

                timestamp_str = ""
                if timestamp:
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")

                duration_str = self._format_duration(duration)

                if result == "SUCCESS":
                    status = "success"
                    success_builds += 1
                elif result == "FAILURE":
                    status = "failed"
                    failed_builds += 1
                elif result == "UNSTABLE":
                    status = "unstable"
                    unstable_builds += 1
                elif result == "ABORTED":
                    status = "aborted"
                else:
                    status = "unknown"

                builds_list.append(
                    {
                        "buildNumber": build_number,
                        "status": status,
                        "timestamp": timestamp_str,
                        "duration": duration_str,
                        "buildUrl": f"{self.golden_regression_url}/{build_number}/",
                    }
                )

            total_builds = len(builds_list)
            overall_success_rate = round((success_builds / total_builds) * 100) if total_builds > 0 else 0

            return {
                "builds": builds_list,
                "pipelines": [],
                "stackGroups": {},
                "sortedStacks": [],
                "summary": {
                    "totalBuilds": total_builds,
                    "successBuilds": success_builds,
                    "failedBuilds": failed_builds,
                    "unstableBuilds": unstable_builds,
                    "successRate": overall_success_rate,
                },
                "jenkinsUrl": self.golden_regression_url,
                "dataSource": "jenkins-direct",
            }

        except Exception as e:
            logger.error("Error fetching Golden Regression builds: %s", e)
            return {"error": str(e), "builds": [], "pipelines": [], "summary": {}}

    async def get_golden_regression_tfa(self, build_number: int) -> Dict[str, Any]:
        """Get Test Failure Analysis for a specific Golden Regression build."""
        if not self.is_configured():
            return {"error": "Jenkins not configured"}

        if not self.golden_regression_url:
            return {"error": "JENKINS_GOLDEN_REGRESSION_URL environment variable not configured"}

        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    test_response = await client.get(
                        f"{self.golden_regression_url}/{build_number}/testReport/api/json",
                        headers=self._gr_auth_headers,
                    )

                    if test_response.status_code != 200:
                        return {"error": f"No test report found for build #{build_number}"}

                    test_report = test_response.json()

            total_tests = (
                test_report.get("passCount", 0) + test_report.get("failCount", 0) + test_report.get("skipCount", 0)
            )
            passed = test_report.get("passCount", 0)
            failed = test_report.get("failCount", 0)
            skipped = test_report.get("skipCount", 0)

            # Extract failed tests
            failed_tests = []
            for suite in test_report.get("suites", []):
                for case in suite.get("cases", []):
                    if case.get("status") in ("FAILED", "REGRESSION"):
                        failed_tests.append(
                            {
                                "name": case.get("name"),
                                "className": case.get("className"),
                                "status": case.get("status"),
                                "duration": case.get("duration"),
                                "errorMessage": (case.get("errorDetails") or "")[:500],
                                "stackTrace": (case.get("errorStackTrace") or "")[:1000],
                            }
                        )

            # Generate recommendations
            recommendations = []
            if failed > 0:
                recommendations.append("Review test expectations and actual behavior")
            if failed > 5:
                recommendations.append("High number of failures - consider rolling back recent changes")

            return {
                "job": "Golden Regression Suite",
                "buildNumber": build_number,
                "failedTests": failed_tests,
                "summary": {
                    "totalTests": total_tests,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "passRate": round((passed / total_tests) * 100) if total_tests > 0 else 0,
                },
                "recommendations": recommendations,
                "dataSource": "jenkins-direct",
            }

        except Exception as e:
            logger.error("Error fetching Golden Regression TFA: %s", e)
            return {"error": str(e)}

    async def get_golden_regression_console(self, build_number: int) -> Optional[str]:
        """Get console output for a specific Golden Regression build."""
        if not self.golden_regression_url:
            return None

        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(
                        f"{self.golden_regression_url}/{build_number}/consoleText",
                        headers=self._gr_auth_headers,
                    )

                    if response.status_code == 200:
                        text = response.text
                        # Return last 3000 chars for analysis
                        return text[-3000:] if len(text) > 3000 else text
                    return None
        except Exception as e:
            logger.warning("Error fetching Golden Regression console: %s", e)
            return None


# Singleton instance
_jenkins_client: Optional[JenkinsClient] = None


def get_jenkins_client() -> JenkinsClient:
    """Get Jenkins client singleton.

    The client creates fresh HTTP connections per request using context managers,
    avoiding event loop issues that occur with cached connections.
    """
    global _jenkins_client
    if _jenkins_client is None:
        _jenkins_client = JenkinsClient()
    return _jenkins_client


def reset_jenkins_client():
    """Reset the Jenkins client singleton (useful for testing)."""
    global _jenkins_client
    _jenkins_client = None


class DevJenkinsClient(JenkinsClientBase):
    """
    Client for Dev Jenkins instance (iad0-cisystem.example.com).

    Extends JenkinsClientBase to reuse common functionality.

    Environment Variables:
        JENKINS_DEV_URL - Dev Jenkins server URL (default: https://iad0-cisystem.example.com)
        JENKINS_DEV_USER - Dev Jenkins username (optional - anonymous access supported)
        JENKINS_DEV_TOKEN - Dev Jenkins API token (optional - anonymous access supported)
        JENKINS_DEV_PIPELINES - Comma-separated list of Dev pipelines to monitor
            Format: job-name:Display Name:Description (description optional)
            Example: client-feature-pipeline:Feature Pipeline:Feature branch builds,client-develop-pipeline:Develop Pipeline
            If not set, defaults to client-feature-pipeline, client-develop-pipeline, client-release-pipeline
    """

    # Default Dev pipeline definitions (used if JENKINS_DEV_PIPELINES not set)
    DEFAULT_DEV_PIPELINES = [
        {
            "name": "client-feature-pipeline",
            "displayName": "Feature Pipeline",
            "description": "Feature branch builds",
        },
        {
            "name": "client-develop-pipeline",
            "displayName": "Develop Pipeline",
            "description": "Develop branch builds",
        },
        {
            "name": "client-release-pipeline",
            "displayName": "Release Pipeline",
            "description": "Release branch builds",
        },
    ]

    def __init__(self):
        self.base_url = os.getenv("JENKINS_DEV_URL", "https://iad0-cisystem.example.com").rstrip("/")

        # Load Dev pipelines from environment or use defaults
        self.DEV_PIPELINES = self._load_dev_pipelines()
        # Only use Dev-specific credentials if explicitly set
        # Don't fall back to main Jenkins credentials as they may not work for this instance
        self.username = os.getenv("JENKINS_DEV_USER", "")
        self.token = os.getenv("JENKINS_DEV_TOKEN", "")

        # Pre-compute auth header (only if Dev credentials are explicitly configured)
        # This Jenkins instance allows anonymous read access, so no auth is fine
        if self.username and self.token:
            credentials = f"{self.username}:{self.token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_headers = {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}
            logger.info("Dev Jenkins configured with authentication")
        else:
            # No auth headers - use anonymous access
            self._auth_headers = {"Content-Type": "application/json"}
            logger.info("Dev Jenkins using anonymous access (no JENKINS_DEV_USER/TOKEN set)")

        # Caching for job/build info (60 second TTL)
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 60

        # Semaphore for concurrent connections
        self._max_concurrent = 5
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    def _load_dev_pipelines(self) -> List[Dict[str, str]]:
        """
        Load Dev pipelines from JENKINS_DEV_PIPELINES environment variable.

        Format: job-name:Display Name:Description (description optional)
        Example: client-feature-pipeline:Feature Pipeline:Feature branch builds,client-develop-pipeline:Develop Pipeline

        If only job name provided, display name and description are auto-generated.
        """
        env_pipelines = os.getenv("JENKINS_DEV_PIPELINES", "")

        if not env_pipelines:
            logger.info("JENKINS_DEV_PIPELINES not set, using default Dev pipelines")
            return self.DEFAULT_DEV_PIPELINES.copy()

        pipelines = []
        for entry in env_pipelines.split(","):
            entry = entry.strip()
            if not entry:
                continue

            parts = entry.split(":")
            job_name = parts[0].strip()

            if not job_name:
                continue

            # Generate display name from job name if not provided
            # e.g., "client-feature-pipeline" -> "Feature Pipeline"
            if len(parts) >= 2 and parts[1].strip():
                display_name = parts[1].strip()
            else:
                # Auto-generate: remove common prefixes and format
                display_name = (
                    job_name.replace("client-", "").replace("-pipeline", "").replace("-", " ").title() + " Pipeline"
                )

            # Description is optional
            description = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else f"{display_name} builds"

            pipelines.append(
                {
                    "name": job_name,
                    "displayName": display_name,
                    "description": description,
                }
            )

        if pipelines:
            logger.info(
                "Loaded %d Dev pipelines from JENKINS_DEV_PIPELINES: %s", len(pipelines), [p["name"] for p in pipelines]
            )
            return pipelines
        else:
            logger.warning("JENKINS_DEV_PIPELINES was set but no valid pipelines found, using defaults")
            return self.DEFAULT_DEV_PIPELINES.copy()

    def is_configured(self) -> bool:
        """Check if Dev Jenkins client is properly configured.

        Returns True if base_url is set (credentials optional for anonymous access).
        """
        return bool(self.base_url)

    def _format_duration(self, duration_ms: int) -> str:
        """Format duration in milliseconds to human readable string."""
        if not duration_ms:
            return ""
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) // 1000
        return f"{minutes}m {seconds}s"

    def _format_relative_time(self, timestamp: int) -> str:
        """Format timestamp as relative time string."""
        if not timestamp:
            return ""
        run_time = datetime.fromtimestamp(timestamp / 1000)
        delta = datetime.now() - run_time
        if delta.days > 0:
            return f"{delta.days}d ago"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        if delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        return "Just now"

    async def _make_request(self, url: str, timeout: float = 30.0, use_cache: bool = True) -> Dict:
        """Make authenticated request to Dev Jenkins API."""
        if use_cache:
            cached = self._get_cached(url)
            if cached is not None:
                return cached

        try:
            async with self._get_semaphore():
                async with self._create_client() as client:
                    response = await client.get(url, headers=self._auth_headers, timeout=timeout)

                    if response.status_code == 200:
                        result = response.json()
                        if use_cache:
                            self._set_cache(url, result)
                        return result
                    elif response.status_code == 404:
                        return {"error": "Resource not found", "error_type": "not_found"}
                    elif response.status_code in (401, 403):
                        return {"error": "Authentication failed", "error_type": "auth_failed"}
                    else:
                        return {"error": f"HTTP {response.status_code}", "error_type": "server_error"}
        except httpx.TimeoutException as err:
            logger.error("Dev Jenkins request timed out for %s: %s", url, err)
            return {"error": "Request timed out", "error_type": "timeout"}
        except httpx.HTTPError as err:
            logger.error("Dev Jenkins request failed for %s: %s", url, err)
            return {"error": f"Connection failed: {err}", "error_type": "connection"}
        except Exception as err:
            logger.error("Dev Jenkins error for %s: %s", url, err)
            return {"error": str(err), "error_type": "unknown"}

    async def get_dev_pipelines(self, num_builds: int = 10) -> Dict:
        """
        Get status of all Dev pipelines with recent builds.

        Returns:
            {
                "pipelines": [...],
                "summary": { "total": 3, "success": 2, "failed": 1, "successRate": 67 }
            }
        """
        pipelines = []
        total_success = 0
        total_failed = 0
        total_unstable = 0

        # Fetch all pipelines in parallel - single request per pipeline
        async def fetch_pipeline(pipeline_def):
            job_name = pipeline_def["name"]
            display_name = pipeline_def["displayName"]

            # Single request to get both job info and recent builds
            url = f"{self.base_url}/job/{job_name}/api/json?tree=healthReport[score],builds[number,result,timestamp,duration,url]{{0,{num_builds}}}"
            job_data = await self._make_request(url)

            if job_data.get("error"):
                logger.warning("Failed to fetch Dev pipeline %s: %s", job_name, job_data.get("error"))
                return {
                    "name": job_name,
                    "displayName": display_name,
                    "status": "unknown",
                    "error": job_data.get("error"),
                    "url": f"{self.base_url}/job/{job_name}/",
                    "recentBuilds": [],
                }

            builds = []
            latest_status = "unknown"
            latest_build = None

            for build in job_data.get("builds", []):
                result = build.get("result")
                # Map Jenkins result to status
                if result == "SUCCESS":
                    status = "success"
                elif result == "FAILURE":
                    status = "failed"
                elif result == "UNSTABLE":
                    status = "unstable"
                elif result == "ABORTED":
                    status = "aborted"
                elif result is None:
                    status = "running"
                else:
                    status = "unknown"

                build_info = {
                    "buildNumber": build.get("number"),
                    "status": status,
                    "result": result,
                    "timestamp": self._format_relative_time(build.get("timestamp", 0)),
                    "timestampMs": build.get("timestamp", 0),
                    "duration": self._format_duration(build.get("duration", 0)),
                    "durationMs": build.get("duration", 0),
                    "url": build.get("url", ""),
                }
                builds.append(build_info)

                # Set latest build info
                if latest_build is None:
                    latest_build = build_info
                    latest_status = status

            return {
                "name": job_name,
                "displayName": display_name,
                "description": pipeline_def.get("description", ""),
                "status": latest_status,
                "url": f"{self.base_url}/job/{job_name}/",
                "lastBuild": latest_build,
                "recentBuilds": builds,
                "health": job_data.get("healthReport", [{}])[0].get("score", 0) if job_data.get("healthReport") else 0,
            }

        # Fetch all pipelines concurrently
        results = await asyncio.gather(*[fetch_pipeline(p) for p in self.DEV_PIPELINES])

        # Count ALL builds across all pipelines (not just latest per pipeline)
        total_builds = 0
        builds_success = 0
        builds_failed = 0
        builds_unstable = 0
        builds_running = 0
        builds_aborted = 0

        for pipeline in results:
            pipelines.append(pipeline)
            # Count latest pipeline status for backward compatibility
            status = pipeline.get("status", "unknown")
            if status == "success":
                total_success += 1
            elif status in ("failed", "aborted"):
                total_failed += 1
            elif status == "unstable":
                total_unstable += 1

            # Count ALL recent builds for accurate success rate
            for build in pipeline.get("recentBuilds", []):
                build_status = build.get("status", "unknown")
                total_builds += 1
                if build_status == "success":
                    builds_success += 1
                elif build_status == "failed":
                    builds_failed += 1
                elif build_status == "unstable":
                    builds_unstable += 1
                elif build_status == "running":
                    builds_running += 1
                elif build_status == "aborted":
                    builds_aborted += 1

        total = len(pipelines)
        # Calculate success rate based on ALL builds (excluding running builds)
        completed_builds = total_builds - builds_running
        success_rate = round((builds_success / completed_builds) * 100) if completed_builds > 0 else 0

        return {
            "pipelines": pipelines,
            "summary": {
                "total": total,
                "success": total_success,
                "failed": total_failed,
                "unstable": total_unstable,
                "successRate": success_rate,
                # New: counts based on ALL recent builds
                "totalBuilds": total_builds,
                "buildsSuccess": builds_success,
                "buildsFailed": builds_failed,
                "buildsUnstable": builds_unstable,
                "buildsRunning": builds_running,
                "buildsAborted": builds_aborted,
            },
            "jenkinsUrl": self.base_url,
        }

    async def get_single_pipeline(self, pipeline_name: str, num_builds: int = 10) -> Dict[str, Any]:
        """
        Fetch a single Dev pipeline status (for progressive loading).

        Args:
            pipeline_name: Name of the pipeline (e.g., "client-feature-pipeline")
            num_builds: Number of recent builds to fetch

        Returns:
            Pipeline data with status, builds, and summary counts
        """
        # Find pipeline definition
        pipeline_def = None
        for p in self.DEV_PIPELINES:
            if p["name"] == pipeline_name:
                pipeline_def = p
                break

        if not pipeline_def:
            return {"error": f"Pipeline '{pipeline_name}' not found in configured pipelines"}

        job_name = pipeline_def["name"]
        display_name = pipeline_def["displayName"]

        # Get job info
        url = f"{self.base_url}/job/{job_name}/api/json"
        job_info = await self._make_request(url)

        if job_info.get("error"):
            return {
                "name": job_name,
                "displayName": display_name,
                "status": "unknown",
                "error": job_info.get("error"),
                "url": f"{self.base_url}/job/{job_name}/",
                "recentBuilds": [],
            }

        # Get recent builds
        builds_url = f"{self.base_url}/job/{job_name}/api/json?tree=builds[number,result,timestamp,duration,url]{{0,{num_builds}}}"
        builds_data = await self._make_request(builds_url)

        builds = []
        latest_status = "unknown"
        latest_build = None

        # Build counts
        builds_success = 0
        builds_failed = 0
        builds_unstable = 0
        builds_running = 0
        builds_aborted = 0

        if not builds_data.get("error"):
            for build in builds_data.get("builds", []):
                result = build.get("result")
                # Map Jenkins result to status
                if result == "SUCCESS":
                    status = "success"
                    builds_success += 1
                elif result == "FAILURE":
                    status = "failed"
                    builds_failed += 1
                elif result == "UNSTABLE":
                    status = "unstable"
                    builds_unstable += 1
                elif result == "ABORTED":
                    status = "aborted"
                    builds_aborted += 1
                elif result is None:
                    status = "running"
                    builds_running += 1
                else:
                    status = "unknown"

                build_info = {
                    "buildNumber": build.get("number"),
                    "status": status,
                    "result": result,
                    "timestamp": self._format_relative_time(build.get("timestamp", 0)),
                    "timestampMs": build.get("timestamp", 0),
                    "duration": self._format_duration(build.get("duration", 0)),
                    "durationMs": build.get("duration", 0),
                    "url": build.get("url", ""),
                }
                builds.append(build_info)

                # Set latest build info
                if latest_build is None:
                    latest_build = build_info
                    latest_status = status

        total_builds = len(builds)
        completed_builds = total_builds - builds_running
        success_rate = round((builds_success / completed_builds) * 100) if completed_builds > 0 else 0

        return {
            "name": job_name,
            "displayName": display_name,
            "description": pipeline_def.get("description", ""),
            "status": latest_status,
            "url": f"{self.base_url}/job/{job_name}/",
            "lastBuild": latest_build,
            "recentBuilds": builds,
            "health": job_info.get("healthReport", [{}])[0].get("score", 0) if job_info.get("healthReport") else 0,
            "summary": {
                "totalBuilds": total_builds,
                "buildsSuccess": builds_success,
                "buildsFailed": builds_failed,
                "buildsUnstable": builds_unstable,
                "buildsRunning": builds_running,
                "buildsAborted": builds_aborted,
                "successRate": success_rate,
            },
        }

    # get_test_report and get_console_output are inherited from JenkinsClientBase


# Dev Jenkins client singleton
_dev_jenkins_client: Optional[DevJenkinsClient] = None


def get_dev_jenkins_client() -> DevJenkinsClient:
    """Get Dev Jenkins client singleton."""
    global _dev_jenkins_client
    if _dev_jenkins_client is None:
        _dev_jenkins_client = DevJenkinsClient()
    return _dev_jenkins_client


def reset_dev_jenkins_client():
    """Reset the Dev Jenkins client singleton."""
    global _dev_jenkins_client
    _dev_jenkins_client = None

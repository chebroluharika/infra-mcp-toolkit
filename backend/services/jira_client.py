"""
Direct JIRA API Client
======================

Direct JIRA API access for FastAPI backend.
This replaces MCP calls for JIRA data, providing direct HTTP access.

Optimizations:
- Caching: 60-second TTL cache for search results
- Parallel queries: Uses asyncio.gather for concurrent JQL queries

Environment Variables:
    JIRA_URL - JIRA server URL (e.g., https://company.atlassian.net)
    JIRA_USERNAME - JIRA username/email
    JIRA_API_TOKEN - JIRA API token
"""

import asyncio
import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Status Constants
# =============================================================================

OPEN_STATUSES = [
    "Open",
    "In Progress",
    "In Development",
    "In Review",
    "Code Review",
    "To Do",
    "Backlog",
    "Reopened",
    "Blocked",
    "Ready for QA",
    "QA In Progress",
]

RESOLVED_STATUSES = ["Resolved", "Fixed", "Done", "Verified"]

CLOSED_STATUSES = ["Closed", "Won't Fix", "Duplicate", "Cannot Reproduce"]


# =============================================================================
# JIRA Client
# =============================================================================


class JiraAuthError(Exception):
    """Raised when JIRA authentication fails (expired token, invalid credentials)"""

    pass


class JiraClient:
    """Direct JIRA API client with caching"""

    def __init__(self):
        self.base_url = os.getenv("JIRA_URL", "").rstrip("/")
        self.username = os.getenv("JIRA_USERNAME", "")
        self.api_token = os.getenv("JIRA_API_TOKEN", "")

        # Caching
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 60  # 60 second cache

        # Rate limiting - limit concurrent requests to avoid 429 errors
        self._semaphore = asyncio.Semaphore(20)  # Max 20 concurrent requests

        # Track last auth error
        self._last_auth_error: Optional[str] = None
        self._auth_error_time: Optional[float] = None

        # Shared HTTP client — reused across all requests to avoid file descriptor exhaustion
        self._http_client: Optional[httpx.AsyncClient] = None

        # Pre-compute auth header
        if self.username and self.api_token:
            creds = base64.b64encode(f"{self.username}:{self.api_token}".encode()).decode()
            self._headers = {
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            self._headers = {}

    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0, verify=False)
        return self._http_client

    def is_configured(self) -> bool:
        """Check if JIRA credentials are configured"""
        return all([self.base_url, self.username, self.api_token])

    def get_auth_status(self) -> Dict[str, Any]:
        """Get current authentication status"""
        if self._last_auth_error and self._auth_error_time:
            error_age = time.time() - self._auth_error_time
            return {
                "status": "error",
                "error": self._last_auth_error,
                "error_age_seconds": round(error_age),
                "configured": self.is_configured(),
            }
        return {
            "status": "ok" if self.is_configured() else "not_configured",
            "configured": self.is_configured(),
        }

    def clear_auth_error(self):
        """Clear the auth error status"""
        self._last_auth_error = None
        self._auth_error_time = None

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if not expired"""
        if key in self._cache:
            if time.time() - self._cache_times.get(key, 0) < self._cache_ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """Cache a value"""
        self._cache[key] = value
        self._cache_times[key] = time.time()

    def clear_cache(self):
        """Clear all cached data to force fresh fetch from JIRA."""
        self._cache.clear()
        self._cache_times.clear()
        logger.info("JIRA cache cleared")

    async def discover_custom_field_id(self, field_name: str) -> Optional[str]:
        """
        Discover the custom field ID for a given field name.

        Queries Jira's /rest/api/3/field endpoint and searches for fields
        matching the given name (case-insensitive partial match).

        Args:
            field_name: The field name to search for (e.g., "Release Note")

        Returns:
            The custom field ID (e.g., "customfield_12345") or None if not found
        """
        if not self.is_configured():
            logger.warning("JIRA not configured - cannot discover field ID")
            return None

        cache_key = f"field_discovery:{field_name.lower()}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/rest/api/3/field"

        try:
            client = self._get_http_client()
            response = await client.get(url, headers=self._headers)

            if response.status_code != 200:
                logger.error("Failed to fetch Jira fields: %s", response.status_code)
                return None

            fields = response.json()
            search_term = field_name.lower()

            for field in fields:
                name = (field.get("name") or "").lower()
                field_id = field.get("id") or field.get("key")

                if search_term in name:
                    logger.info("Discovered field '%s' with ID: %s", field.get("name"), field_id)
                    self._set_cache(cache_key, field_id)
                    return field_id

            logger.warning("Field '%s' not found in Jira", field_name)
            return None

        except Exception as e:
            logger.error("Error discovering field ID for '%s': %s", field_name, e)
            return None

    async def get_release_note_field_id(self) -> Optional[str]:
        """
        Get the custom field ID for 'Release Note' field.

        This field is under 'Product Details' in Jira and indicates
        whether documentation needs to be updated for customers.

        Returns:
            The custom field ID or None if not found
        """
        return await self.discover_custom_field_id("Release Note")

    async def search_issues(
        self,
        jql: str,
        max_results: int = 100,
        fetch_all: bool = False,
        fields: List[str] = None,
        include_links: bool = False,
    ) -> List[Dict]:
        """
        Search JIRA issues with JQL.

        Args:
            jql: JQL query string
            max_results: Maximum results to return
            fetch_all: If True, paginate to get all results
            fields: List of fields to return

        Returns:
            List of issue dictionaries
        """
        if not self.is_configured():
            logger.warning("JIRA not configured - missing credentials")
            return []

        url = f"{self.base_url}/rest/api/3/search/jql"

        if fields is None:
            fields = [
                "summary",
                "status",
                "priority",
                "created",
                "updated",
                "assignee",
                "reporter",
                "labels",
                "versions",
                "fixVersions",
                "components",
                "issuetype",
                "resolution",
                "resolutiondate",
                "description",
                "parent",
                "subtasks",
                "customfield_10014",  # Epic Link (common custom field ID)
                "customfield_18029",
                "customfield_17527",
                "customfield_16637",
                "customfield_10200",  # QA field
                "customfield_26828",  # Salesforce Account Name (customer) - list of dicts
                "customfield_15000",  # Sub-Component (correct field ID)
                "customfield_14205",  # Release Note (Product Details) - for Bugs documentation update tracking
                "customfield_24133",  # Release Note for NPLANs - documentation update tracking
                "customfield_18128",  # Delivery Target (Beta) - for NPLAN release targeting
                "customfield_18130",  # Delivery Target (GA) - for NPLAN release targeting
                "customfield_18401",  # Writer - assigned technical writer for documentation
                "customfield_24135",  # TOI Highlight Date - when TOI is scheduled
                "customfield_24134",  # TOI Highlight Completed - Yes/No
                "customfield_16130",  # Release Note Description - the actual release note content
                "customfield_24136",  # Documentation Required - Yes/No
            ]

        if include_links and "issuelinks" not in fields:
            fields.append("issuelinks")

        # Check cache - after fields are determined so cache key is accurate
        fields_key = ",".join(sorted(fields)) if fields else "default"
        cache_key = f"search:{jql}:{max_results}:{fetch_all}:{fields_key}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        all_issues = []
        next_page_token = None

        try:
            async with self._semaphore:  # Rate limit concurrent requests
                client = self._get_http_client()
                while True:
                    body = {"jql": jql, "maxResults": min(max_results, 100), "fields": fields}
                    if next_page_token:
                        body["nextPageToken"] = next_page_token

                    response = await client.post(url, headers=self._headers, json=body)

                    if response.status_code == 400 and next_page_token:
                        break

                    if response.status_code == 429:
                        logger.warning("JIRA rate limited (429) on search, waiting...")
                        await asyncio.sleep(2)
                        continue

                    if response.status_code == 401:
                        error_msg = "JIRA API token expired or invalid. Please update JIRA_API_TOKEN in .env"
                        logger.error("JIRA Auth Error (401): %s", response.text[:200])
                        self._last_auth_error = error_msg
                        self._auth_error_time = time.time()
                        raise JiraAuthError(error_msg)

                    if response.status_code == 403:
                        error_msg = "JIRA access forbidden. Check API token permissions."
                        logger.error("JIRA Auth Error (403): %s", response.text[:200])
                        self._last_auth_error = error_msg
                        self._auth_error_time = time.time()
                        raise JiraAuthError(error_msg)

                    if response.status_code != 200:
                        logger.error("JIRA API error: %s - %s", response.status_code, response.text[:200])
                        break

                    data = response.json()
                    issues = data.get("issues", [])

                    for issue in issues:
                        parsed = self._parse_issue(issue)
                        if include_links:
                            raw_links = issue.get("fields", {}).get("issuelinks", [])
                            parsed["linked_issues"] = self._parse_issue_links(raw_links)
                        all_issues.append(parsed)

                    # Pagination
                    if not fetch_all or len(all_issues) >= max_results:
                        break

                    next_page_token = data.get("nextPageToken")
                    if not next_page_token:
                        break

                    if len(all_issues) >= 1000:  # Safety limit
                        break

                self._set_cache(cache_key, all_issues)
                return all_issues

        except Exception as e:
            logger.error("JIRA search error: %s", e)
            return []

    async def get_issue_count(self, jql: str) -> int:
        """
        Get the count of issues matching a JQL query without fetching all data.

        Args:
            jql: JQL query string

        Returns:
            Integer count of matching issues
        """
        if not self.is_configured():
            logger.warning("JIRA not configured - missing credentials")
            return 0

        url = f"{self.base_url}/rest/api/3/search/jql"

        try:
            async with self._semaphore:
                client = self._get_http_client()
                body = {"jql": jql, "maxResults": 0, "fields": ["key"]}
                response = await client.post(url, headers=self._headers, json=body)

                if response.status_code != 200:
                    logger.error("JIRA count query error: %s - %s", response.status_code, response.text[:200])
                    return 0

                data = response.json()
                total = data.get("total", 0)
                logger.debug(f"JIRA count query returned {total} issues")
                return total

        except Exception as e:
            logger.error("JIRA count query error: %s", e)
            return 0

    def _parse_issue(self, issue: Dict) -> Dict:
        """Parse raw JIRA issue into simplified format"""
        f = issue.get("fields", {})

        # Extract assignee
        assignee_field = f.get("assignee")
        if isinstance(assignee_field, dict):
            assignee = assignee_field.get("displayName") or assignee_field.get("name") or "Unassigned"
            assignee_email = assignee_field.get("emailAddress") or ""
        else:
            assignee = "Unassigned"
            assignee_email = ""

        # Extract reporter
        reporter_field = f.get("reporter")
        if isinstance(reporter_field, dict):
            reporter = reporter_field.get("displayName") or reporter_field.get("name") or "Unknown"
        else:
            reporter = "Unknown"

        # Extract status
        status_field = f.get("status")
        if isinstance(status_field, dict):
            status = status_field.get("name", "Unknown")
        else:
            status = str(status_field) if status_field else "Unknown"

        # Extract priority
        priority_field = f.get("priority")
        if isinstance(priority_field, dict):
            priority = priority_field.get("name", "Medium")
        else:
            priority = str(priority_field) if priority_field else "Medium"

        # Extract issue type
        issuetype_field = f.get("issuetype")
        if isinstance(issuetype_field, dict):
            issuetype = issuetype_field.get("name", "Task")
        else:
            issuetype = str(issuetype_field) if issuetype_field else "Task"

        # Extract components
        components = []
        for comp in f.get("components", []):
            if isinstance(comp, dict):
                components.append(comp.get("name", ""))

        # Extract fix versions
        fix_versions = []
        for ver in f.get("fixVersions", []):
            if isinstance(ver, dict):
                fix_versions.append(ver.get("name", ""))

        # Extract affected versions (versions field in Jira API)
        affected_versions = []
        for ver in f.get("versions", []):
            if isinstance(ver, dict):
                affected_versions.append(ver.get("name", ""))

        # Extract QA field (customfield_10200 is the confirmed field ID)
        qa = None
        qa_email = None
        qa_field = f.get("customfield_10200")
        if qa_field:
            if isinstance(qa_field, dict):
                qa = qa_field.get("displayName") or qa_field.get("name")
                qa_email = qa_field.get("emailAddress") or ""
            elif isinstance(qa_field, list) and len(qa_field) > 0:
                first_qa = qa_field[0]
                if isinstance(first_qa, dict):
                    qa = first_qa.get("displayName") or first_qa.get("name")
                    qa_email = first_qa.get("emailAddress") or ""
            elif isinstance(qa_field, str):
                qa = qa_field

        # Extract Salesforce Account Name (customer) - customfield_26828
        # This is a list of dicts like [{'value': 'Deloitte Global Sell To', ...}]
        salesforce_account = None
        sf_field = f.get("customfield_26828")
        if sf_field:
            if isinstance(sf_field, list) and len(sf_field) > 0:
                first_sf = sf_field[0]
                if isinstance(first_sf, dict):
                    salesforce_account = first_sf.get("value") or first_sf.get("name")
                elif isinstance(first_sf, str):
                    salesforce_account = first_sf
            elif isinstance(sf_field, dict):
                salesforce_account = sf_field.get("value") or sf_field.get("name")
            elif isinstance(sf_field, str):
                salesforce_account = sf_field

        # Extract Sub-Component - customfield_15000
        # This is a list field: [{'value': 'NSC-MacOS', 'id': '...', ...}]
        sub_component = None
        subcomp_field = f.get("customfield_15000")

        if subcomp_field:
            if isinstance(subcomp_field, list) and len(subcomp_field) > 0:
                first_sub = subcomp_field[0]
                if isinstance(first_sub, dict):
                    sub_component = first_sub.get("value") or first_sub.get("name")
                elif isinstance(first_sub, str):
                    sub_component = first_sub
            elif isinstance(subcomp_field, dict):
                sub_component = subcomp_field.get("value") or subcomp_field.get("name")
            elif isinstance(subcomp_field, str):
                sub_component = subcomp_field

        # Extract Release Note - customfield_14205 (Product Details) for Bugs
        # Used to identify escalations needing documentation updates
        # Value "For Customer" indicates customer-facing documentation is needed
        release_note = None
        release_note_field = f.get("customfield_14205")

        if release_note_field:
            if isinstance(release_note_field, dict):
                release_note = release_note_field.get("value") or release_note_field.get("name")
            elif isinstance(release_note_field, list) and len(release_note_field) > 0:
                first_rn = release_note_field[0]
                if isinstance(first_rn, dict):
                    release_note = first_rn.get("value") or first_rn.get("name")
                elif isinstance(first_rn, str):
                    release_note = first_rn
            elif isinstance(release_note_field, str):
                release_note = release_note_field

        # Extract Release Note for NPLANs - customfield_24133
        # This is a different field than the one used for Bugs
        release_note_nplan = None
        release_note_nplan_field = f.get("customfield_24133")

        if release_note_nplan_field:
            if isinstance(release_note_nplan_field, dict):
                release_note_nplan = release_note_nplan_field.get("value") or release_note_nplan_field.get("name")
            elif isinstance(release_note_nplan_field, str):
                release_note_nplan = release_note_nplan_field

        # Use NPLAN release note if Bug release note is not set
        if not release_note and release_note_nplan:
            release_note = release_note_nplan

        # Extract Delivery Target (Beta) - customfield_18128
        # Used for NPLANs to track when feature goes to Beta
        delivery_target_beta = None
        dt_beta_field = f.get("customfield_18128")

        if dt_beta_field:
            if isinstance(dt_beta_field, dict):
                delivery_target_beta = dt_beta_field.get("value") or dt_beta_field.get("name")
            elif isinstance(dt_beta_field, str):
                delivery_target_beta = dt_beta_field

        # Extract Delivery Target (GA) - customfield_18130
        # Used for NPLANs to track when feature goes to GA
        delivery_target_ga = None
        dt_ga_field = f.get("customfield_18130")

        if dt_ga_field:
            if isinstance(dt_ga_field, dict):
                delivery_target_ga = dt_ga_field.get("value") or dt_ga_field.get("name")
            elif isinstance(dt_ga_field, str):
                delivery_target_ga = dt_ga_field

        # Extract Writer (technical writer assigned) - customfield_18401
        writer = None
        writer_field = f.get("customfield_18401")
        if writer_field:
            if isinstance(writer_field, dict):
                writer = writer_field.get("displayName") or writer_field.get("name")
            elif isinstance(writer_field, str):
                writer = writer_field

        # Extract TOI Highlight Date - customfield_24135
        toi_date = f.get("customfield_24135")

        # Extract TOI Highlight Completed - customfield_24134
        toi_completed = None
        toi_completed_field = f.get("customfield_24134")
        if toi_completed_field:
            if isinstance(toi_completed_field, dict):
                toi_completed = toi_completed_field.get("value") or toi_completed_field.get("name")
            elif isinstance(toi_completed_field, str):
                toi_completed = toi_completed_field

        # Extract Release Note Description - customfield_16130
        # This is ADF (Atlassian Document Format) content
        release_note_description = None
        rn_desc_field = f.get("customfield_16130")
        if rn_desc_field:
            if isinstance(rn_desc_field, dict):
                release_note_description = self._extract_adf_text(rn_desc_field)
            elif isinstance(rn_desc_field, str):
                release_note_description = rn_desc_field

        # Extract Documentation Required - customfield_24136
        documentation_required = None
        docs_req_field = f.get("customfield_24136")
        if docs_req_field:
            if isinstance(docs_req_field, dict):
                documentation_required = docs_req_field.get("value") or docs_req_field.get("name")
            elif isinstance(docs_req_field, str):
                documentation_required = docs_req_field

        # Extract parent (for hierarchy child issues)
        parent_field = f.get("parent")
        parent = None
        if isinstance(parent_field, dict):
            parent = {
                "key": parent_field.get("key", ""),
                "summary": (parent_field.get("fields", {}).get("summary", "")),
            }

        # Build URL
        key = issue.get("key", "")
        url = f"{self.base_url}/browse/{key}" if key else ""

        # Extract description (may be ADF dict or plain string)
        description_raw = f.get("description")
        if isinstance(description_raw, dict):
            description = self._extract_adf_text(description_raw)
        elif description_raw:
            description = str(description_raw)
        else:
            description = ""

        return {
            "key": key,
            "summary": f.get("summary", ""),
            "status": status,
            "priority": priority,
            "assignee": assignee,
            "assignee_email": assignee_email,
            "reporter": reporter,
            "issuetype": issuetype,
            "components": components,
            "fixVersions": fix_versions,
            "affectedVersions": affected_versions,
            "created": f.get("created"),
            "updated": f.get("updated"),
            "resolutiondate": f.get("resolutiondate"),
            "labels": f.get("labels", []),
            "url": url,
            "qa": qa,
            "qa_email": qa_email,
            "description": description,
            "description_raw": description_raw,
            "salesforce_account": salesforce_account,
            "sub_component": sub_component,
            "release_note": release_note,
            "delivery_target_beta": delivery_target_beta,
            "delivery_target_ga": delivery_target_ga,
            "writer": writer,
            "toi_date": toi_date,
            "toi_completed": toi_completed,
            "release_note_description": release_note_description,
            "documentation_required": documentation_required,
            "parent": parent,
        }

    async def get_milestone_data(
        self,
        fix_version: str,
        next_fix_version: str,
        milestone_date: str,
        component_filter: str = None,
        include_bugs: bool = True,
        final_build_date: str = None,
    ) -> Dict:
        """
        Get milestone data with proper date-based categorization for YOUR_PRODUCT only.

        Tracks Stories and Bugs separately, categorized by:
        - Resolved On Time: Resolved on or before milestone date
        - Resolved Late: Resolved after milestone date (up to final build)
        - Still Open: Not yet resolved

        Optimization: Uses asyncio.gather to run all 3 JQL queries in parallel.

        Args:
            fix_version: Fix version (e.g., "135.0.0")
            next_fix_version: Next fix version to exclude (e.g., "136.0.0")
            milestone_date: Milestone date in YYYY-MM-DD format
            component_filter: Optional component JQL filter
            include_bugs: Whether to include bugs (True for all milestones)
            final_build_date: Final build date to limit "resolved late" items (YYYY-MM-DD)

        Returns:
            Dict with resolved_on_time, resolved_late, still_open counts and breakdowns
        """
        # Always query NS Client component only
        component_clause = '(component = "NS Client (NSC)")'

        # Base JQL - includes both Stories and Bugs, excludes EPICs, Sub-tasks, Tasks, Escalations
        # Only major release (X.0.0) and ENG project
        base_jql = (
            f'(fixVersion = "{fix_version}") AND '
            f"(project = ENG AND {component_clause} AND "
            f"type not in (EPIC, Sub-task, task, Escalation))"
        )

        # Build JQL queries
        # Use status-based query for resolved items (consistent with Resolution Progress)
        # Then filter by resolution date in Python
        jql_resolved = f'{base_jql} AND status IN (resolved, closed, "Pending Close") ORDER BY resolved DESC'
        jql_open = f'{base_jql} AND status NOT IN (resolved, closed, "Pending Close") ORDER BY priority DESC'

        # Run queries in parallel for better performance
        resolved_issues, open_issues = await asyncio.gather(
            self.search_issues(jql_resolved, max_results=1000, fetch_all=True),
            self.search_issues(jql_open, max_results=500, fetch_all=True),
        )

        # Filter resolved issues by date (using resolutiondate or updated as fallback)
        # This matches Resolution Progress logic exactly
        on_time_issues = []
        late_issues = []

        for issue in resolved_issues:
            resolved_date = issue.get("resolutiondate") or issue.get("updated")
            if resolved_date:
                resolved_date_str = resolved_date[:10]  # Extract YYYY-MM-DD
                if resolved_date_str <= milestone_date:
                    on_time_issues.append(issue)
                elif final_build_date and resolved_date_str <= final_build_date:
                    late_issues.append(issue)
                elif not final_build_date:
                    late_issues.append(issue)
                # Items resolved after final_build_date are excluded

        # Helper to count stories vs bugs
        def count_by_type(issues):
            stories = [i for i in issues if i.get("issuetype") == "Story"]
            bugs = [i for i in issues if i.get("issuetype") == "Bug"]
            return {"total": len(issues), "stories": len(stories), "bugs": len(bugs)}

        on_time_counts = count_by_type(on_time_issues)
        late_counts = count_by_type(late_issues)
        open_counts = count_by_type(open_issues)

        # Group open issues by assignee with type breakdown
        by_assignee = {}
        for issue in open_issues:
            assignee = issue.get("assignee", "Unassigned")
            issue_type = issue.get("issuetype", "Story")
            if assignee not in by_assignee:
                by_assignee[assignee] = {"count": 0, "stories": 0, "bugs": 0, "tickets": []}
            by_assignee[assignee]["count"] += 1
            if issue_type == "Bug":
                by_assignee[assignee]["bugs"] += 1
            else:
                by_assignee[assignee]["stories"] += 1
            by_assignee[assignee]["tickets"].append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary", "")[:60],
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "type": issue_type,
                }
            )

        # Group late issues by assignee
        late_by_assignee = {}
        for issue in late_issues:
            assignee = issue.get("assignee", "Unassigned")
            issue_type = issue.get("issuetype", "Story")
            if assignee not in late_by_assignee:
                late_by_assignee[assignee] = {"count": 0, "stories": 0, "bugs": 0, "tickets": []}
            late_by_assignee[assignee]["count"] += 1
            if issue_type == "Bug":
                late_by_assignee[assignee]["bugs"] += 1
            else:
                late_by_assignee[assignee]["stories"] += 1
            late_by_assignee[assignee]["tickets"].append(
                {
                    "key": issue.get("key"),
                    "summary": issue.get("summary", "")[:60],
                    "priority": issue.get("priority"),
                    "status": issue.get("status"),
                    "type": issue_type,
                }
            )

        total = on_time_counts["total"] + late_counts["total"] + open_counts["total"]
        on_time_rate = round((on_time_counts["total"] / total * 100), 1) if total > 0 else 0

        # Build component data for YOUR_PRODUCT
        by_component = {
            "NS Client (NSC)": {
                "resolved_on_time": on_time_counts["total"],
                "resolved_late": late_counts["total"],
                "still_open": open_counts["total"],
                "total": total,
                "stories": {
                    "on_time": on_time_counts["stories"],
                    "late": late_counts["stories"],
                    "open": open_counts["stories"],
                },
                "bugs": {
                    "on_time": on_time_counts["bugs"],
                    "late": late_counts["bugs"],
                    "open": open_counts["bugs"],
                },
            }
        }

        return {
            "total_items": total,
            "resolved_on_time": on_time_counts["total"],
            "resolved_late": late_counts["total"],
            "still_open": open_counts["total"],
            "on_time_rate": on_time_rate,
            # Breakdown by type
            "stories": {
                "total": on_time_counts["stories"] + late_counts["stories"] + open_counts["stories"],
                "on_time": on_time_counts["stories"],
                "late": late_counts["stories"],
                "open": open_counts["stories"],
            },
            "bugs": {
                "total": on_time_counts["bugs"] + late_counts["bugs"] + open_counts["bugs"],
                "on_time": on_time_counts["bugs"],
                "late": late_counts["bugs"],
                "open": open_counts["bugs"],
            },
            "by_component": by_component,
            "by_assignee": by_assignee,
            "late_by_assignee": late_by_assignee,
            "open_issues": open_issues[:30],
            "late_issues": late_issues[:30],
            "source": "jira-direct",
            # JQL queries for transparency (displayed in info tooltips)
            "jql": {
                "all_items": f'{base_jql} AND status IN (resolved, closed, "Pending Close")',
                "resolved_on_time": f'{base_jql} AND status IN (resolved, closed, "Pending Close") (filtered: resolved <= {milestone_date})',
                "resolved_late": f'{base_jql} AND status IN (resolved, closed, "Pending Close") (filtered: resolved > {milestone_date}{f" AND <= {final_build_date}" if final_build_date else ""})',
                "still_open": jql_open.replace(" ORDER BY priority DESC", ""),
            },
        }

    async def get_issue(self, issue_key: str, include_links: bool = False) -> Optional[Dict]:
        """
        Get a single JIRA issue by key.

        Args:
            issue_key: JIRA issue key (e.g., "ENG-12345")
            include_links: Also fetch issuelinks and description

        Returns:
            Parsed issue dictionary or None if not found
        """
        if not self.is_configured():
            logger.warning("JIRA not configured - missing credentials")
            return None

        # Check cache
        cache_key = f"issue:{issue_key}:{include_links}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        fields = [
            "summary",
            "status",
            "priority",
            "created",
            "updated",
            "assignee",
            "reporter",
            "labels",
            "components",
            "issuetype",
            "resolution",
            "resolutiondate",
            "fixVersions",
            "parent",
            "subtasks",
            "customfield_10200",  # QA field
            "customfield_26828",  # Salesforce Account Name (customer)
            "customfield_15000",  # Sub-Component (correct field ID)
        ]
        if include_links:
            fields.extend(["issuelinks", "description"])

        try:
            async with self._semaphore:  # Rate limit concurrent requests
                client = self._get_http_client()
                response = await client.get(url, headers=self._headers, params={"fields": ",".join(fields)})

                if response.status_code == 404:
                    logger.warning("Issue %s not found", issue_key)
                    return None

                if response.status_code == 429:
                    logger.warning("JIRA rate limited (429) for %s, waiting...", issue_key)
                    await asyncio.sleep(2)  # Wait and let caller retry
                    return None

                if response.status_code == 401:
                    error_msg = "JIRA API token expired or invalid"
                    logger.error("JIRA Auth Error (401): %s", response.text[:200])
                    self._last_auth_error = error_msg
                    self._auth_error_time = time.time()
                    raise JiraAuthError(error_msg)

                if response.status_code != 200:
                    logger.error("JIRA API error fetching %s: %s", issue_key, response.status_code)
                    return None

                data = response.json()
                parsed = self._parse_issue(data)

                # Parse linked issues if requested
                if include_links:
                    raw_fields = data.get("fields", {})
                    parsed["linked_issues"] = self._parse_issue_links(raw_fields.get("issuelinks", []))
                    parsed["description_raw"] = raw_fields.get("description")

                self._set_cache(cache_key, parsed)
                return parsed

        except JiraAuthError:
            raise
        except Exception as e:
            logger.error("Error fetching issue %s: %s", issue_key, e)
            return None

    def _parse_issue_links(self, issuelinks: List) -> List[Dict]:
        """Parse issuelinks field into a clean list of linked issues."""
        links = []
        for link in issuelinks or []:
            link_type = link.get("type", {})
            link_name = link_type.get("name", "")

            # Linked issue can be inward or outward
            if "outwardIssue" in link:
                target = link["outwardIssue"]
                direction = link_type.get("outward", link_name)
            elif "inwardIssue" in link:
                target = link["inwardIssue"]
                direction = link_type.get("inward", link_name)
            else:
                continue

            target_fields = target.get("fields", {})
            status_obj = target_fields.get("status", {})
            priority_obj = target_fields.get("priority", {})
            issuetype_obj = target_fields.get("issuetype", {})
            assignee_obj = target_fields.get("assignee")
            assignee_name = None
            if isinstance(assignee_obj, dict):
                assignee_name = assignee_obj.get("displayName") or assignee_obj.get("name")
            elif isinstance(assignee_obj, str):
                assignee_name = assignee_obj

            links.append(
                {
                    "key": target.get("key", ""),
                    "summary": target_fields.get("summary", ""),
                    "status": status_obj.get("name", "") if isinstance(status_obj, dict) else str(status_obj),
                    "priority": priority_obj.get("name", "") if isinstance(priority_obj, dict) else str(priority_obj),
                    "issuetype": (
                        issuetype_obj.get("name", "") if isinstance(issuetype_obj, dict) else str(issuetype_obj)
                    ),
                    "assignee": assignee_name,
                    "link_type": link_name,
                    "direction": direction,
                    "url": f"{self.base_url}/browse/{target.get('key', '')}",
                }
            )
        return links

    async def get_issue_dev_status(self, issue_key: str) -> Dict[str, Any]:
        """
        Fetch development status (PRs, branches, commits) from Jira's Development panel.

        Uses the /rest/dev-status/1.0/issue/detail endpoint which reads data
        from the GitHub integration in Jira.

        Args:
            issue_key: JIRA issue key (e.g., "ENG-12345")

        Returns:
            Dict with pull_requests, branches, and commits lists.
        """
        if not self.is_configured():
            return {"pull_requests": [], "error": "JIRA not configured"}

        cache_key = f"dev-status:{issue_key}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {"pull_requests": [], "branches": [], "commits": []}

        try:
            async with self._semaphore:  # Rate limit concurrent requests
                # First get the issue's internal ID (dev-status API needs numeric ID)
                issue_id = await self._get_issue_id(issue_key)
                if not issue_id:
                    return {"pull_requests": [], "commits": [], "error": f"Could not resolve ID for {issue_key}"}

                client = self._get_http_client()

                async def _dev_status_request(client, issue_id, data_type, max_retries=2):
                    """Make a dev-status API call with retry on 429."""
                    for app_type in ["GitHub", "stash", "github"]:
                        url = f"{self.base_url}/rest/dev-status/1.0/issue/detail"
                        params = {
                            "issueId": issue_id,
                            "applicationType": app_type,
                            "dataType": data_type,
                        }
                        response = None
                        for attempt in range(max_retries + 1):
                            try:
                                response = await client.get(url, headers=self._headers, params=params)
                            except Exception:
                                break  # Network error, try next app_type
                            if response.status_code == 429:
                                wait = min(2 ** (attempt + 1), 8)
                                logger.warning(
                                    "JIRA 429 for %s %s (attempt %d), waiting %ds",
                                    issue_key,
                                    data_type,
                                    attempt + 1,
                                    wait,
                                )
                                await asyncio.sleep(wait)
                                continue
                            break  # Got a non-429 response
                        if response is not None and response.status_code == 200:
                            return response.json()
                    return None

                # Fetch PRs
                pr_data = await _dev_status_request(client, issue_id, "pullrequest")
                if pr_data:
                    for provider in pr_data.get("detail", []):
                        for pr in provider.get("pullRequests", []):
                            result["pull_requests"].append(
                                {
                                    "id": pr.get("id", ""),
                                    "name": pr.get("name", ""),
                                    "url": pr.get("url", ""),
                                    "status": pr.get("status", ""),
                                    "source_branch": pr.get("source", {}).get("name", ""),
                                    "destination_branch": pr.get("destination", {}).get("name", ""),
                                    "author": pr.get("author", {}).get("name", ""),
                                    "reviewers": [r.get("name", "") for r in pr.get("reviewers", [])],
                                    "last_update": pr.get("lastUpdate", ""),
                                }
                            )

                # Fetch commits
                repo_data = await _dev_status_request(client, issue_id, "repository")
                if repo_data:
                    for provider in repo_data.get("detail", []):
                        for repo in provider.get("repositories", []):
                            for commit in repo.get("commits", []):
                                merge_val = commit.get("merge", [])
                                branches = [b.get("name", "") for b in merge_val] if isinstance(merge_val, list) else []
                                result["commits"].append(
                                    {
                                        "id": commit.get("id", ""),
                                        "message": commit.get("message", ""),
                                        "url": commit.get("url", ""),
                                        "author": commit.get("author", {}).get("name", ""),
                                        "timestamp": commit.get("authorTimestamp", ""),
                                        "merge_branches": branches,
                                    }
                                )

                self._set_cache(cache_key, result)
                return result

        except Exception as e:
            error_str = str(e) if str(e) else type(e).__name__
            logger.warning("Error fetching dev-status for %s: %s", issue_key, error_str)
            return {"pull_requests": [], "commits": [], "error": error_str}

    async def _get_issue_id(self, issue_key: str) -> Optional[str]:
        """Get the internal numeric ID for a Jira issue key."""
        cache_key = f"issue-id:{issue_key}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
            # Note: No semaphore here - called from get_issue_dev_status which already has it
            client = self._get_http_client()
            response = await client.get(url, headers=self._headers, params={"fields": "summary"})
            if response.status_code == 429:
                logger.warning("JIRA rate limited (429) getting issue ID for %s", issue_key)
                await asyncio.sleep(2)
                return None
            if response.status_code == 200:
                issue_id = response.json().get("id")
                self._set_cache(cache_key, issue_id)
                return issue_id
        except Exception as e:
            logger.error("Error getting issue ID for %s: %s", issue_key, e)
        return None

    async def get_issue_comments(self, issue_key: str, max_results: int = 10) -> List[Dict]:
        """
        Get comments for a JIRA issue.

        Args:
            issue_key: JIRA issue key (e.g., "ENG-12345")
            max_results: Maximum number of comments to return

        Returns:
            List of comment dictionaries with body, author, created
        """
        if not self.is_configured():
            logger.warning("JIRA not configured - missing credentials")
            return []

        # Check cache
        cache_key = f"comments:{issue_key}:{max_results}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"

        try:
            client = self._get_http_client()
            response = await client.get(
                url, headers=self._headers, params={"maxResults": max_results, "orderBy": "-created"}
            )

            if response.status_code == 404:
                logger.warning("Issue %s not found for comments", issue_key)
                return []

            if response.status_code == 401:
                error_msg = "JIRA API token expired or invalid"
                logger.error("JIRA Auth Error (401)")
                self._last_auth_error = error_msg
                self._auth_error_time = time.time()
                raise JiraAuthError(error_msg)

            if response.status_code != 200:
                logger.error("JIRA API error fetching comments for %s: %s", issue_key, response.status_code)
                return []

            data = response.json()
            comments = []

            for comment in data.get("comments", []):
                # Extract author
                author_field = comment.get("author", {})
                author = author_field.get("displayName") or author_field.get("name") or "Unknown"

                # Extract body - handle Atlassian Document Format (ADF)
                body_field = comment.get("body", {})
                if isinstance(body_field, dict):
                    # ADF format - extract text content
                    body = self._extract_adf_text(body_field)
                else:
                    body = str(body_field) if body_field else ""

                comments.append(
                    {
                        "id": comment.get("id"),
                        "body": body,
                        "author": author,
                        "created": comment.get("created"),
                        "updated": comment.get("updated"),
                    }
                )

            self._set_cache(cache_key, comments)
            return comments

        except JiraAuthError:
            raise
        except Exception as e:
            logger.error("Error fetching comments for %s: %s", issue_key, e)
            return []

    async def search_bugs_by_nplan_labels(
        self, nplan_ids: List[str], include_closed: bool = True, fix_version: str = None
    ) -> Dict[str, Any]:
        """
        Search for bugs linked to NPLANs via labels.

        Args:
            nplan_ids: List of NPLAN IDs (e.g., ["NPLAN-5417", "NPLAN-6021"])
            include_closed: If True, include all bugs; if False, exclude Closed status
            fix_version: If provided, filter bugs by fixVersion (e.g., "137.0.0")

        Returns:
            Dictionary with bugs grouped by NPLAN ID and summary statistics
        """
        if not nplan_ids:
            return {
                "nplan_bugs": {},
                "summary": {
                    "total_nplans": 0,
                    "nplans_with_bugs": 0,
                    "total_bugs": 0,
                    "open_bugs": 0,
                    "by_priority": {},
                    "by_status": {},
                },
            }

        # Convert NPLAN IDs to label format (e.g., NPLAN-5417 -> nplan-5417)
        labels = []
        nplan_to_label = {}
        for nplan_id in nplan_ids:
            # Extract just the number part and create lowercase label
            label = nplan_id.lower().replace("_", "-")
            labels.append(label)
            nplan_to_label[label] = nplan_id

        # Build JQL query for all NPLAN labels
        # Format: (labels = nplan-5417 OR labels = nplan-6021) AND project = ENG AND fixVersion = "137.0.0"
        label_conditions = " OR ".join([f'labels = "{label}"' for label in labels])

        status_filter = ""
        if not include_closed:
            status_filter = " AND status != Closed"

        # Add fixVersion filter if provided
        fix_version_filter = ""
        if fix_version:
            fix_version_filter = f' AND fixVersion = "{fix_version}"'

        jql = f"({label_conditions}) AND project = ENG{fix_version_filter}{status_filter} ORDER BY priority DESC, created DESC"

        logger.info(f"Searching NPLAN bugs with JQL: {jql[:200]}...")

        # Fetch bugs from JIRA
        bugs = await self.search_issues(jql, max_results=500, fetch_all=True)

        # Group bugs by NPLAN ID
        nplan_bugs = {
            nplan_id: {"nplan_id": nplan_id, "bugs": [], "total": 0, "open": 0, "by_priority": {}, "by_status": {}}
            for nplan_id in nplan_ids
        }

        total_bugs = 0
        open_bugs = 0
        overall_by_priority = {}
        overall_by_status = {}

        for bug in bugs:
            bug_labels = bug.get("labels", [])
            status = bug.get("status", "Unknown")
            priority = bug.get("priority", "Medium")

            # Determine which NPLAN(s) this bug belongs to
            for label in bug_labels:
                label_lower = label.lower()
                if label_lower in nplan_to_label:
                    nplan_id = nplan_to_label[label_lower]

                    # Add bug to this NPLAN
                    bug_entry = {
                        "key": bug.get("key"),
                        "summary": bug.get("summary"),
                        "status": status,
                        "priority": priority,
                        "assignee": bug.get("assignee", "Unassigned"),
                        "issuetype": bug.get("issuetype", "Bug"),
                        "created": bug.get("created"),
                        "updated": bug.get("updated"),
                        "url": f"{self.base_url}/browse/{bug.get('key')}",
                    }

                    nplan_bugs[nplan_id]["bugs"].append(bug_entry)
                    nplan_bugs[nplan_id]["total"] += 1

                    # Count by priority for this NPLAN
                    nplan_bugs[nplan_id]["by_priority"][priority] = (
                        nplan_bugs[nplan_id]["by_priority"].get(priority, 0) + 1
                    )

                    # Count by status for this NPLAN
                    nplan_bugs[nplan_id]["by_status"][status] = nplan_bugs[nplan_id]["by_status"].get(status, 0) + 1

                    # Track open bugs
                    if status not in CLOSED_STATUSES + RESOLVED_STATUSES:
                        nplan_bugs[nplan_id]["open"] += 1

            # Overall counts (count each bug once)
            total_bugs += 1
            overall_by_priority[priority] = overall_by_priority.get(priority, 0) + 1
            overall_by_status[status] = overall_by_status.get(status, 0) + 1

            if status not in CLOSED_STATUSES + RESOLVED_STATUSES:
                open_bugs += 1

        # Count NPLANs with bugs
        nplans_with_bugs = sum(1 for data in nplan_bugs.values() if data["total"] > 0)

        logger.info(f"Found {total_bugs} bugs across {nplans_with_bugs} NPLANs")

        return {
            "nplan_bugs": nplan_bugs,
            "summary": {
                "total_nplans": len(nplan_ids),
                "nplans_with_bugs": nplans_with_bugs,
                "total_bugs": total_bugs,
                "open_bugs": open_bugs,
                "by_priority": overall_by_priority,
                "by_status": overall_by_status,
            },
        }

    async def search_nplan_workitems(self, nplan_ids: List[str], include_closed: bool = True) -> Dict[str, Any]:
        """
        Search for all work items (Stories, Bugs, Tasks, Epics) under NPLANs.

        Uses JQL: parent = NPLAN-XXXX OR issueKey IN portfolioChildIssuesOf("NPLAN-XXXX")

        Args:
            nplan_ids: List of NPLAN IDs (e.g., ["NPLAN-5196", "NPLAN-6364"])
            include_closed: If True, include all items; if False, exclude Closed status

        Returns:
            Dictionary with work items grouped by NPLAN ID and summary statistics
        """
        if not nplan_ids:
            return {
                "nplan_workitems": {},
                "summary": {
                    "total_nplans": 0,
                    "total_items": 0,
                    "open_items": 0,
                    "closed_items": 0,
                    "by_type": {},
                    "by_status": {},
                    "by_assignee": {},
                },
            }

        # Build JQL query for all NPLANs
        # Format: (parent = NPLAN-5196 OR issueKey IN portfolioChildIssuesOf("NPLAN-5196")) OR (parent = NPLAN-6364 OR ...)
        nplan_conditions = []
        for nplan_id in nplan_ids:
            nplan_conditions.append(f'(parent = {nplan_id} OR issueKey IN portfolioChildIssuesOf("{nplan_id}"))')

        combined_conditions = " OR ".join(nplan_conditions)

        status_filter = ""
        if not include_closed:
            status_filter = " AND status != Closed"

        jql = f"({combined_conditions}){status_filter} ORDER BY created DESC"

        logger.info(f"Searching NPLAN work items with JQL: {jql[:300]}...")

        # Fetch work items from JIRA
        items = await self.search_issues(jql, max_results=1000, fetch_all=True)

        # Initialize result structure for each NPLAN
        nplan_workitems = {
            nplan_id: {
                "nplan_id": nplan_id,
                "items": [],
                "total": 0,
                "open": 0,
                "closed": 0,
                "by_type": {},
                "by_status": {},
                "by_assignee": {},
            }
            for nplan_id in nplan_ids
        }

        # Overall statistics
        total_items = 0
        open_items = 0
        closed_items = 0
        overall_by_type = {}
        overall_by_status = {}
        overall_by_assignee = {}

        for item in items:
            status = item.get("status", "Unknown")
            issue_type = item.get("issuetype", "Task")
            assignee = item.get("assignee", "Unassigned")
            parent_key = (
                item.get("parent_key") or item.get("parent", {}).get("key")
                if isinstance(item.get("parent"), dict)
                else None
            )

            # Determine which NPLAN this item belongs to
            # Check if parent matches any NPLAN ID
            matched_nplan = None
            for nplan_id in nplan_ids:
                if parent_key == nplan_id:
                    matched_nplan = nplan_id
                    break

            # If no direct parent match, try to find via labels or other means
            if not matched_nplan:
                # Check labels for nplan reference
                labels = item.get("labels", [])
                for label in labels:
                    label_upper = label.upper().replace("-", "-")
                    for nplan_id in nplan_ids:
                        if (
                            nplan_id.replace("-", "-").upper() in label_upper
                            or label_upper in nplan_id.replace("-", "-").upper()
                        ):
                            matched_nplan = nplan_id
                            break
                    if matched_nplan:
                        break

            # If still no match, assign to first NPLAN (fallback for portfolioChildIssuesOf results)
            if not matched_nplan and nplan_ids:
                # Try to match based on epic link or other parent fields
                epic_link = item.get("epic_link") or item.get("customfield_10014")
                if epic_link:
                    for nplan_id in nplan_ids:
                        if epic_link == nplan_id:
                            matched_nplan = nplan_id
                            break

            # Skip items that don't match any NPLAN
            if not matched_nplan:
                continue

            # Create work item entry
            item_entry = {
                "key": item.get("key"),
                "summary": item.get("summary"),
                "status": status,
                "priority": item.get("priority", "Medium"),
                "assignee": assignee,
                "issuetype": issue_type,
                "created": item.get("created"),
                "updated": item.get("updated"),
                "url": f"{self.base_url}/browse/{item.get('key')}",
            }

            # Add to NPLAN's items
            nplan_workitems[matched_nplan]["items"].append(item_entry)
            nplan_workitems[matched_nplan]["total"] += 1

            # Count by type for this NPLAN
            nplan_workitems[matched_nplan]["by_type"][issue_type] = (
                nplan_workitems[matched_nplan]["by_type"].get(issue_type, 0) + 1
            )

            # Count by status for this NPLAN
            nplan_workitems[matched_nplan]["by_status"][status] = (
                nplan_workitems[matched_nplan]["by_status"].get(status, 0) + 1
            )

            # Count by assignee for this NPLAN
            nplan_workitems[matched_nplan]["by_assignee"][assignee] = (
                nplan_workitems[matched_nplan]["by_assignee"].get(assignee, 0) + 1
            )

            # Track open/closed for this NPLAN
            if status in CLOSED_STATUSES + RESOLVED_STATUSES:
                nplan_workitems[matched_nplan]["closed"] += 1
                closed_items += 1
            else:
                nplan_workitems[matched_nplan]["open"] += 1
                open_items += 1

            # Overall counts
            total_items += 1
            overall_by_type[issue_type] = overall_by_type.get(issue_type, 0) + 1
            overall_by_status[status] = overall_by_status.get(status, 0) + 1
            overall_by_assignee[assignee] = overall_by_assignee.get(assignee, 0) + 1

        # Calculate completion percentage for each NPLAN
        for nplan_id in nplan_ids:
            total = nplan_workitems[nplan_id]["total"]
            closed = nplan_workitems[nplan_id]["closed"]
            nplan_workitems[nplan_id]["completion_pct"] = round((closed / total * 100) if total > 0 else 0, 1)

        nplans_with_items = sum(1 for data in nplan_workitems.values() if data["total"] > 0)

        # Create sorted list of unique assignees for filtering
        unique_assignees = sorted([a for a in overall_by_assignee.keys() if a and a != "Unassigned"], key=str.lower)
        # Add Unassigned at the end if present
        if "Unassigned" in overall_by_assignee:
            unique_assignees.append("Unassigned")

        logger.info(
            f"Found {total_items} work items across {nplans_with_items} NPLANs with {len(unique_assignees)} unique assignees"
        )

        return {
            "nplan_workitems": nplan_workitems,
            "assignees": unique_assignees,
            "summary": {
                "total_nplans": len(nplan_ids),
                "nplans_with_items": nplans_with_items,
                "total_items": total_items,
                "open_items": open_items,
                "closed_items": closed_items,
                "completion_pct": round((closed_items / total_items * 100) if total_items > 0 else 0, 1),
                "by_type": overall_by_type,
                "by_status": overall_by_status,
                "by_assignee": overall_by_assignee,
            },
        }

    def _extract_adf_text(self, adf_doc: Dict) -> str:
        """
        Extract plain text from Atlassian Document Format (ADF).

        ADF is a JSON structure used by JIRA for rich text content.
        This recursively extracts text from the document.
        """
        if not isinstance(adf_doc, dict):
            return str(adf_doc) if adf_doc else ""

        text_parts = []

        # Handle text nodes
        if adf_doc.get("type") == "text":
            return adf_doc.get("text", "")

        # Recursively process content
        content = adf_doc.get("content", [])
        if isinstance(content, list):
            for item in content:
                extracted = self._extract_adf_text(item)
                if extracted:
                    text_parts.append(extracted)

        # Add newlines for paragraph/heading breaks
        doc_type = adf_doc.get("type", "")
        if doc_type in ("paragraph", "heading", "bulletList", "orderedList", "listItem"):
            return " ".join(text_parts) + "\n"

        return " ".join(text_parts)


# =============================================================================
# Singleton
# =============================================================================

_jira_client: Optional[JiraClient] = None


def get_jira_client() -> JiraClient:
    """Get singleton JIRA client instance"""
    global _jira_client
    if _jira_client is None:
        _jira_client = JiraClient()
    return _jira_client

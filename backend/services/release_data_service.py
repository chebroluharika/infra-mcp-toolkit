"""
Centralized Release Data Service
================================

Single source of truth for release readiness data.
Fetches all data with ONE JQL query, then applies filters for different views.

Benefits:
- Reduces JIRA API calls from 15+ to 1-2 per page load
- Ensures consistent counts across all tiles
- Improves performance significantly
- Single JQL = single source of truth

Usage:
    from services.release_data_service import get_release_data_service

    service = get_release_data_service()
    data = await service.get_release_data("R135")

    # Filter for specific views
    product_items = service.filter_by_component(data, "YOUR_PRODUCT")
    stories_only = service.filter_by_type(data, "Story")
    by_assignee = service.group_by_assignee(data)
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.jira_client import get_jira_client

logger = logging.getLogger(__name__)


# =============================================================================
# Component Mapping
# =============================================================================

COMPONENT_MAP = {
    "YOUR_PRODUCT": "NS Client (NSC)",
}

TRACKED_COMPONENTS = list(COMPONENT_MAP.keys())


# =============================================================================
# Generic Base Filter (from JIRA saved filter "generic-base-filter")
# =============================================================================
# This filter excludes non-code items, QA automation, and non-Your-Product components.
# Used across multiple JQL queries for consistent filtering.

GENERIC_BASE_FILTER_JQL = (
    "project in (ENG) AND "
    "(labels not in (no-code, no_code, QA_NA, QE_NA, XRAY_AUTO_CLOSED_OBSOLETE_ISSUE, dlp-on-demand, ngweb) OR labels is EMPTY) AND "
    'component not in ("AI Red Teaming (AIRT)", "Advanced Analytics (AA)", "Clickhouse (CH)", '
    '"Mongo Cluster Mapper (MCM)", "Query Service (QS)", "Trans. Event Manager-Forwarder (TEMF)", '
    '"QA automation", "Cloud Firewall (CFW)", "Advanced Analytics (NAA)", Observability, Phoenix, '
    '"Event Pipeline (EvP)", "Product Security", "Digital Rights Management (DRM)", "Unified CASB (UCASB)", '
    '"Cloud Tap (CT)", CSPM, "Web Security", "Digital Experience Management (DEM)", "Introspection (API)", '
    '"Yet Another Pipeline (YAP)", "Enhanced Reports", "Enterprise Browser (EB)", DSPM, '
    '"Inhouse Malware Detection (nsmal)", "Survey Tool", "Control Plane Core Services (CPCS)", '
    '"AI Security (AIS)", "Workflow Engine (WE)", NA, "AI Gateway (AIG)", "Log Streaming", '
    '"Event Streaming Client (ESC)", VPE-Platform) AND '
    "issuetype != Escalation"
)


# =============================================================================
# Release Data Service
# =============================================================================


class ReleaseDataService:
    """
    Centralized service for fetching and filtering release data.

    Fetches ALL release items with a single JQL query, then provides
    utility methods to filter/slice the data for different tiles.
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 120  # 2 minute cache

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get cached data if not expired."""
        if key in self._cache:
            if time.time() - self._cache_times.get(key, 0) < self._cache_ttl:
                logger.debug(f"Cache hit for {key}")
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Dict):
        """Cache data."""
        self._cache[key] = value
        self._cache_times[key] = time.time()

    def clear_cache(self, release_id: str = None):
        """Clear cache for a specific release or all releases."""
        if release_id:
            key = f"release:{release_id}"
            self._cache.pop(key, None)
            self._cache_times.pop(key, None)
        else:
            self._cache.clear()
            self._cache_times.clear()

    async def get_release_data(self, release_id: str, force_refresh: bool = False, phase: str = None) -> Dict[str, Any]:
        """
        Fetch ALL release data with phase-appropriate JQL query.

        Args:
            release_id: Release ID (e.g., "R135")
            force_refresh: Bypass cache and fetch fresh data
            phase: Release phase - affects JQL filtering:
                   - "branch_cut" or earlier: Stricter filtering (excludes Resolved bugs, 48h filter)
                   - "final_build" or later: Simpler filtering (includes all open items)
                   - None: Defaults to branch_cut behavior

        Returns:
            Dict with:
                - items: List of all JIRA items
                - metadata: Query metadata (timestamp, JQL used, etc.)
                - summary: Pre-calculated summary stats
        """
        # Include phase in cache key so different phases have separate caches
        cache_key = f"release:{release_id}:{phase or 'default'}"

        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        else:
            # Clear this service's cache entry
            self._cache.pop(cache_key, None)
            self._cache_times.pop(cache_key, None)

        jira = get_jira_client()

        # If force refresh, also clear JIRA client cache
        if force_refresh:
            jira.clear_cache()
        if not jira.is_configured():
            logger.warning("JIRA not configured")
            return self._empty_result(release_id)

        # Parse version from release ID (e.g., "R134" -> "134", "134.0.0")
        version_num = release_id.replace("R", "")
        fix_version = f"{version_num}.0.0"
        next_fix_version = f"{int(version_num) + 1}.0.0"

        # Determine if we're in Final Build phase or later
        phase_lower = (phase or "").lower()
        is_final_build_or_later = phase_lower in [
            "final_build",
            "branch_cut_to_final_build",
            "post_final_build",
            "day1_deploy",
            "day2_deploy",
            "day3_deploy",
            "day4_deploy",
            "deployment",
            "completed",
            "post_day4_deploy",
        ]

        if is_final_build_or_later:
            # Final Build JQL: Simpler, includes all Stories and Bugs not fully closed
            # Includes Resolved bugs (awaiting verification) and all bugs regardless of age
            jql_combined = (
                f'component = "NS Client (NSC)" AND '
                f'fixVersion = "{fix_version}" AND fixVersion not in ("{next_fix_version}") AND '
                f"({GENERIC_BASE_FILTER_JQL}) AND "
                f'type in (Story, Bug) AND status not in ("Pending Close", Closed, Completed)'
            )

            logger.info(f"Fetching release data for {release_id} (Final Build phase)")
            logger.info(f"  Combined JQL: {jql_combined}")
            start_time = time.time()

            try:
                import asyncio

                items = await jira.search_issues(jql_combined, max_results=500, fetch_all=True)
                fetch_time = time.time() - start_time

                # Count stories and bugs
                stories_count = sum(1 for i in items if i.get("issuetype", "").lower() == "story")
                bugs_count = len(items) - stories_count

                logger.info(
                    f"Fetched {stories_count} stories + {bugs_count} bugs = {len(items)} total for {release_id} (Final Build) in {fetch_time:.2f}s"
                )

                result = {
                    "release_id": release_id,
                    "fix_version": fix_version,
                    "phase": phase,
                    "items": items,
                    "metadata": {
                        "jql": jql_combined,
                        "jql_type": "final_build",
                        "fetched_at": datetime.now().isoformat(),
                        "fetch_time_seconds": round(fetch_time, 2),
                        "total_items": len(items),
                        "stories_count": stories_count,
                        "bugs_count": bugs_count,
                        "cached": False,
                    },
                    "summary": self._calculate_summary(items),
                }

                self._set_cache(cache_key, result)
                return result

            except Exception as e:
                logger.error(f"Error fetching release data for {release_id}: {e}")
                return self._empty_result(release_id, error=str(e))
        else:
            # Branch Cut JQL (Pre-IRR, IRR, Branch Cut phases): Stricter filtering
            # Stories: status not in ("Pending Close", Closed, Completed) - INCLUDES Resolved
            # Bugs: status not in (Resolved, "Pending Close", Closed, Completed) AND createdDate <= -48h

            jql_stories = (
                f'component = "NS Client (NSC)" AND '
                f'fixVersion = "{fix_version}" AND fixVersion not in ("{next_fix_version}") AND '
                f"({GENERIC_BASE_FILTER_JQL}) AND "
                f'type = Story AND status not in ("Pending Close", Closed, Completed)'
            )

            jql_bugs = (
                f'component = "NS Client (NSC)" AND '
                f'fixVersion = "{fix_version}" AND fixVersion not in ("{next_fix_version}") AND '
                f"({GENERIC_BASE_FILTER_JQL}) AND "
                f'type = Bug AND status not in (Resolved, "Pending Close", Closed, Completed) AND '
                f'createdDate <= -48h AND NOT (status changed TO "Reopened" AFTER -48h)'
            )

            logger.info(f"Fetching release data for {release_id} (Branch Cut phase)")
            logger.info(f"  Stories JQL: {jql_stories}")
            logger.info(f"  Bugs JQL: {jql_bugs}")
            start_time = time.time()

            try:
                # Fetch stories and bugs in parallel
                import asyncio

                stories_items, bugs_items = await asyncio.gather(
                    jira.search_issues(jql_stories, max_results=500, fetch_all=True),
                    jira.search_issues(jql_bugs, max_results=500, fetch_all=True),
                )

                # Combine all items
                items = stories_items + bugs_items
                fetch_time = time.time() - start_time

                logger.info(
                    f"Fetched {len(stories_items)} stories + {len(bugs_items)} bugs = {len(items)} total for {release_id} (Branch Cut) in {fetch_time:.2f}s"
                )

                # Build result with metadata
                result = {
                    "release_id": release_id,
                    "fix_version": fix_version,
                    "phase": phase,
                    "items": items,
                    "metadata": {
                        "jql_stories": jql_stories,
                        "jql_bugs": jql_bugs,
                        "jql_type": "branch_cut",
                        "fetched_at": datetime.now().isoformat(),
                        "fetch_time_seconds": round(fetch_time, 2),
                        "total_items": len(items),
                        "stories_count": len(stories_items),
                        "bugs_count": len(bugs_items),
                        "cached": False,
                    },
                    "summary": self._calculate_summary(items),
                }

                self._set_cache(cache_key, result)
                return result

            except Exception as e:
                logger.error(f"Error fetching release data for {release_id}: {e}")
                return self._empty_result(release_id, error=str(e))

    def _empty_result(self, release_id: str, error: str = None) -> Dict:
        """Return empty result structure."""
        return {
            "release_id": release_id,
            "fix_version": "",
            "items": [],
            "metadata": {
                "jql": "",
                "fetched_at": datetime.now().isoformat(),
                "fetch_time_seconds": 0,
                "total_items": 0,
                "cached": False,
                "error": error,
            },
            "summary": {
                "total": 0,
                "stories": 0,
                "bugs": 0,
                "by_status": {},
                "by_priority": {},
                "by_assignee": {},
            },
        }

    def _calculate_summary(self, items: List[Dict]) -> Dict:
        """
        Calculate summary statistics from items.

        Returns both full counts (for Developer Workload, QA Backlog) and
        filtered counts (for dashboard summary - excludes bugs < 48h old).
        """
        stories = 0
        bugs = 0
        by_status = {}
        by_priority = {}
        by_assignee = {}
        code_review_count = 0

        for item in items:
            item_type = item.get("issuetype", "Story")
            status = item.get("status", "Unknown")
            priority = item.get("priority", "Medium")
            assignee = item.get("assignee", "Unassigned")

            # Count by type
            if item_type == "Story":
                stories += 1
            else:
                bugs += 1

            # Count by status
            by_status[status] = by_status.get(status, 0) + 1

            # Track code review specifically
            if status.lower() == "code review":
                code_review_count += 1

            # Count by priority
            by_priority[priority] = by_priority.get(priority, 0) + 1

            # Count by assignee
            if assignee not in by_assignee:
                by_assignee[assignee] = {"total": 0, "stories": 0, "bugs": 0}
            by_assignee[assignee]["total"] += 1
            if item_type == "Story":
                by_assignee[assignee]["stories"] += 1
            else:
                by_assignee[assignee]["bugs"] += 1

        return {
            # Full counts (for Developer Workload, QA Backlog - includes all items)
            "total": len(items),
            "stories": stories,
            "bugs": bugs,
            "code_review": code_review_count,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_assignee": by_assignee,
        }

    # =========================================================================
    # Filter Utilities
    # =========================================================================

    def filter_by_component(self, data: Dict, component: str) -> List[Dict]:
        """
        Filter items by component.

        Args:
            data: Result from get_release_data()
            component: Component key (e.g., "YOUR_PRODUCT") or name (e.g., "NS Client (NSC)")
        """
        component_name = COMPONENT_MAP.get(component, component)
        return [item for item in data.get("items", []) if component_name in item.get("components", [])]

    def filter_by_type(self, data: Dict, issue_type: str) -> List[Dict]:
        """Filter items by issue type (Story, Bug)."""
        return [item for item in data.get("items", []) if item.get("issuetype", "").lower() == issue_type.lower()]

    def filter_by_status(self, data: Dict, statuses: List[str]) -> List[Dict]:
        """Filter items by status."""
        status_lower = [s.lower() for s in statuses]
        return [item for item in data.get("items", []) if item.get("status", "").lower() in status_lower]

    def filter_by_priority(self, data: Dict, priorities: List[str]) -> List[Dict]:
        """Filter items by priority."""
        priority_lower = [p.lower() for p in priorities]
        return [item for item in data.get("items", []) if item.get("priority", "").lower() in priority_lower]

    def filter_by_assignee(self, data: Dict, assignee: str) -> List[Dict]:
        """Filter items by assignee."""
        return [item for item in data.get("items", []) if item.get("assignee", "Unassigned") == assignee]

    # =========================================================================
    # Grouping Utilities
    # =========================================================================

    def group_by_assignee(self, data: Dict) -> Dict[str, Dict]:
        """
        Group items by assignee with detailed breakdown.

        Returns:
            Dict[assignee_name] = {
                "total": int,
                "stories": int,
                "bugs": int,
                "code_review": int,
                "tickets": List[Dict]
            }
        """
        by_assignee = {}

        for item in data.get("items", []):
            assignee = item.get("assignee", "Unassigned")
            status = item.get("status", "")
            item_type = item.get("issuetype", "Story")

            if assignee not in by_assignee:
                by_assignee[assignee] = {
                    "total": 0,
                    "stories": 0,
                    "bugs": 0,
                    "code_review": 0,
                    "tickets": [],
                }

            by_assignee[assignee]["total"] += 1

            if item_type == "Story":
                by_assignee[assignee]["stories"] += 1
            else:
                by_assignee[assignee]["bugs"] += 1

            if status.lower() == "code review":
                by_assignee[assignee]["code_review"] += 1

            by_assignee[assignee]["tickets"].append(
                {
                    "key": item.get("key"),
                    "summary": item.get("summary"),
                    "status": status,
                    "priority": item.get("priority"),
                    "type": item_type,
                    "url": item.get("url"),
                    "reporter": item.get("reporter"),
                    "component": "YOUR_PRODUCT",  # All items from centralized JQL are YOUR_PRODUCT
                }
            )

        return by_assignee

    def group_by_status(self, data: Dict) -> Dict[str, List[Dict]]:
        """Group items by status."""
        by_status = {}

        for item in data.get("items", []):
            status = item.get("status", "Unknown")
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(item)

        return by_status

    def group_by_priority(self, data: Dict) -> Dict[str, List[Dict]]:
        """Group items by priority."""
        by_priority = {}

        for item in data.get("items", []):
            priority = item.get("priority", "Medium")
            if priority not in by_priority:
                by_priority[priority] = []
            by_priority[priority].append(item)

        return by_priority

    # =========================================================================
    # Analysis Utilities
    # =========================================================================

    def get_blockers(self, data: Dict) -> List[Dict]:
        """Get all blocker/critical priority items (P0 + P1 combined)."""
        return self.filter_by_priority(data, ["Highest", "Blocker", "Critical"])

    def get_p0_blockers(self, data: Dict) -> List[Dict]:
        """Get P0/Blocker priority items only (Highest, Blocker)."""
        return self.filter_by_priority(data, ["Highest", "Blocker"])

    def get_p1_critical(self, data: Dict) -> List[Dict]:
        """Get P1/Critical priority items only."""
        return self.filter_by_priority(data, ["Critical"])

    def get_code_review_items(self, data: Dict) -> List[Dict]:
        """Get items in Code Review status."""
        return self.filter_by_status(data, ["Code Review"])

    def get_stuck_items(self, data: Dict) -> List[Dict]:
        """Get items in Open/To Do/Reopened status (not started)."""
        return self.filter_by_status(data, ["Open", "To Do", "Reopened"])

    def get_in_progress_items(self, data: Dict) -> List[Dict]:
        """Get items actively being worked on."""
        return self.filter_by_status(data, ["In Progress", "In Development"])

    def calculate_readiness_metrics(self, data: Dict) -> Dict:
        """
        Calculate release readiness metrics from data.

        Returns:
            Dict with:
                - health_score: 0-100 score
                - status: "Ready", "At Risk", "Blocked"
                - blockers_count: Critical/Blocker items count
                - code_review_count: Items in code review
                - recommendation: Text recommendation
        """
        summary = data.get("summary", {})
        total = summary.get("total", 0)
        stories = summary.get("stories", 0)
        bugs = summary.get("bugs", 0)
        code_review = summary.get("code_review", 0)

        # Get blocker count
        blockers = self.get_blockers(data)
        blocker_count = len(blockers)

        # Calculate health score
        health_score = 100
        health_score -= min(blocker_count * 10, 40)  # -10 per blocker, max -40
        health_score -= min(total * 0.5, 30)  # -0.5 per open item, max -30
        health_score -= min(code_review * 2, 20)  # -2 per code review, max -20
        health_score = max(0, min(100, health_score))

        # Determine status with reason
        status_reason = ""
        if blocker_count >= 3:
            status = "Blocked"
            status_reason = f"{blocker_count} blocker/critical items need immediate attention"
        elif total > 20 or code_review > 5 or health_score < 70:
            status = "At Risk"
            if blocker_count > 0:
                status_reason = f"{blocker_count} blocker/critical item(s)"
            elif total > 20:
                status_reason = f"{total} open items remaining"
            elif code_review > 5:
                status_reason = f"{code_review} items pending code review"
            else:
                status_reason = f"Health score is {health_score}%"
        elif total == 0:
            status = "Ready"
            status_reason = "All items resolved"
        else:
            status = "On Track"
            status_reason = f"{total} open items, progressing well"

        # Generate recommendation
        if total == 0:
            recommendation = "Release is ready. All items resolved."
        elif blocker_count > 0:
            recommendation = f"⚠️ {blocker_count} blocker(s) need immediate attention."
        elif code_review > 3:
            recommendation = f"📝 {code_review} items in Code Review need review."
        elif total > 10:
            recommendation = f"📋 {total} open items ({stories} stories, {bugs} bugs)."
        else:
            recommendation = "On track for release."

        return {
            "health_score": round(health_score),
            "status": status,
            "status_reason": status_reason,
            "total_open": total,
            "stories": stories,
            "bugs": bugs,
            "blockers_count": blocker_count,
            "code_review_count": code_review,
            "recommendation": recommendation,
        }


# =============================================================================
# Singleton
# =============================================================================

_service: Optional[ReleaseDataService] = None


def get_release_data_service() -> ReleaseDataService:
    """Get singleton ReleaseDataService instance."""
    global _service
    if _service is None:
        _service = ReleaseDataService()
    return _service

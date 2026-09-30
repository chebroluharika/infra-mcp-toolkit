"""
Overview & Config API Router
============================

Handles overview page data and release configuration endpoints.

Endpoints:
    - GET /api/overview - Overview page data (releases, PDV, insights)
    - GET /api/releases - Available releases list
    - GET /api/config/releases - Detailed release configuration

Author: QE Agentic Dashboard Team
"""

import asyncio
import logging
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional

from config import DEFAULT_RELEASE_ID, RELEASE_MILESTONES, get_current_release, get_release_dates, is_release_completed
from fastapi import APIRouter, Query
from services.release_data_service import get_release_data_service
from utilities.jira import calculate_rrs_score, determine_phase, parse_date_safe

logger = logging.getLogger(__name__)

# =============================================================================
# Response Cache for Fast Page Loads
# =============================================================================


class ResponseCache:
    """Simple in-memory cache for API responses with TTL."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = 120  # 2 minutes default

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if still valid."""
        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry["timestamp"] < entry["ttl"]:
                logger.debug(f"Cache hit for {key}")
                return entry["data"]
            else:
                logger.debug(f"Cache expired for {key}")
                del self._cache[key]
        return None

    def set(self, key: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache response with TTL."""
        self._cache[key] = {"data": data, "timestamp": time.time(), "ttl": ttl or self._default_ttl}
        logger.debug(f"Cached {key} with TTL {ttl or self._default_ttl}s")

    def clear(self, key: Optional[str] = None) -> None:
        """Clear cache entry or all entries."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


# Global response cache
_response_cache = ResponseCache()

router = APIRouter(
    prefix="/api",
    tags=["dashboard"],
)


# =============================================================================
# Release Configuration Endpoints
# =============================================================================


@router.get("/releases")
async def get_releases():
    """
    Get list of all available software releases.

    PURPOSE:
        Returns a list of all configured releases for populating UI dropdowns,
        release selectors, and navigation components.

    WHEN TO USE:
        - Populating release dropdown/selector in the UI
        - Determining which release is currently active
        - Getting release display names for navigation

    RETURNS:
        {
            "releases": [
                {
                    "id": "R135",              # Release identifier
                    "name": "Release R135",    # Display name
                    "status": "active",        # "active" or "completed"
                    "is_current": true,        # Whether this is the current release
                    "display_name": "R135 (Current)"
                },
                ...
            ]
        }

    RELATED ENDPOINTS:
        - GET /api/config/releases - Detailed configuration with milestone IDs
        - GET /api/overview - Release status with RRS scores
    """
    # Build from centralized config
    current = get_current_release()
    current_id = current["id"] if current else None
    releases = []
    for r in RELEASE_MILESTONES:
        rid = r["id"]
        completed = is_release_completed(rid)
        releases.append(
            {
                "id": rid,
                "name": r.get("name", f"Release {rid}"),
                "status": "completed" if completed else "active",
                "is_current": rid == current_id,
                "display_name": rid,
            }
        )

    return {"releases": releases}


@router.get("/config/releases")
async def get_release_config():
    """
    Get detailed release configuration including milestone IDs and dates.

    PURPOSE:
        Returns comprehensive release configuration including TestRail milestone IDs,
        JIRA fix versions, and release dates. Used for debugging and verification.

    WHEN TO USE:
        - Verifying TestRail milestone ID mappings
        - Checking release dates configuration
        - Debugging release data issues
        - Understanding current vs previous releases

    RETURNS:
        {
            "releases": [...],           # Full RELEASE_MILESTONES config
            "current_release": {         # Active release details
                "id": "R135",
                "milestone_id": 84,
                "dates": {...}
            },
            "default_project_id": 38,    # TestRail project ID
            "note": "..."                 # Configuration help
        }

    RELATED ENDPOINTS:
        - GET /api/releases - Simplified list for UI
        - GET /api/release-calendar/releases - Calendar with all milestone dates
    """
    return {
        "releases": RELEASE_MILESTONES,
        "current_release": get_current_release(),
        "default_project_id": 38,
        "note": "To add new releases, update RELEASE_MILESTONES in backend/config.py",
    }


# =============================================================================
# Overview Endpoint (for Overview page)
# =============================================================================


@router.get("/overview")
async def get_overview_data(
    refresh: bool = Query(default=False, description="Force refresh cached data"),
    lite: bool = Query(default=False, description="Skip slow tasks (regression, stack health) for faster initial load"),
):
    """
    Get dashboard overview data with release health, PDV status, and AI insights.

    PURPOSE:
        Primary endpoint for the dashboard landing page. Provides a high-level
        summary of all active releases including release readiness scores (RRS),
        blocker counts, PDV test status, and AI-generated insights for quick
        decision making.

    WHEN TO USE:
        - Loading the main dashboard/overview page
        - Getting quick health status of all releases
        - Checking PDV pipeline health summary
        - Viewing AI-generated insights and recommendations

    PARAMETERS:
        - refresh (bool): Force refresh cached data (default: False)
                         Use True when user clicks "Refresh" button

    RETURNS:
        {
            "releases": [
                {
                    "id": "R135",
                    "is_current": true,
                    "phase": "Branch Cut",        # Current release phase
                    "rrs_score": 85,              # Release Readiness Score (0-100)
                    "rrs_status": "On Track",     # "Ready", "On Track", "At Risk", "Blocked"
                    "blocker_count": 2,           # Critical/Blocker bugs
                    "action_items": 15,           # Total open items
                    "days_remaining": 7,          # Days to target milestone
                    "days_remaining_label": "To Day 4 Deploy",  # Label for days countdown
                    "days_remaining_date": "2026-02-09",        # Target date (ISO format)
                    "checklist_status": "yellow"  # "green", "yellow", "red"
                }
            ],
            "pdv_summary": {
                "available": true,
                "total": 20,
                "passed": 18,
                "failed": 2,
                "status": "failing",
                "backend": {...},    # Backend PDV details
                "endpoint": {...}    # Endpoint/Golden Regression details
            },
            "ai_insights": [
                {
                    "type": "critical",
                    "message": "3 blocker bugs need immediate attention",
                    "action": "Review and prioritize",
                    "release": "R135"
                }
            ],
            "lastUpdated": "2026-02-03T10:30:00"
        }

    PERFORMANCE:
        - Uses ReleaseDataService with 2-minute cache
        - Parallel fetching of release and PDV data
        - No internal HTTP calls (direct service calls)

    RELATED ENDPOINTS:
        - GET /api/jira/release-readiness?release=R135 - Detailed release data
        - GET /api/jenkins/pdv-pipelines - Full PDV pipeline details
        - GET /api/jenkins/golden-regression - Golden regression test results
    """
    # Check cache first for fast response (unless refresh requested)
    # Lite and full modes use separate cache keys to prevent lite from poisoning full cache
    cache_key = "overview_data_lite" if lite else "overview_data"
    if refresh:
        # Clear all caches when refresh is requested
        _response_cache.clear("overview_data")
        _response_cache.clear("overview_data_lite")

        # Clear release data and JIRA caches for fresh data
        try:
            release_service = get_release_data_service()
            release_service.clear_cache()
        except Exception as e:
            logger.warning("Could not clear release data cache: %s", e)

        try:
            from services.jira_client import get_jira_client

            jira = get_jira_client()
            jira.clear_cache()
        except Exception as e:
            logger.warning("Could not clear JIRA cache: %s", e)

        logger.info("Cleared all caches on refresh request")
    else:
        cached = _response_cache.get(cache_key)
        if cached:
            logger.info("Returning cached overview data (lite=%s)", lite)
            return {**cached, "cached": True, "cache_source": "memory"}
        # Lite requests can also use the full cache (full is a superset)
        if lite:
            full_cached = _response_cache.get("overview_data")
            if full_cached:
                logger.info("Returning cached full overview data for lite request")
                return {**full_cached, "cached": True, "cache_source": "memory"}

    start_time = time.time()
    current_release = get_current_release()
    current_release_id = current_release["id"] if current_release else DEFAULT_RELEASE_ID

    releases_data = []
    ai_insights = []

    # Include all releases so user can view any release in the dropdown
    active_release_ids = [r["id"] for r in RELEASE_MILESTONES]

    # Helper function to fetch TestRail data for a specific release
    async def fetch_testrail_for_release(release_id: str) -> dict:
        """Fetch TestRail test execution summary for a specific release."""
        from config import get_milestone_id, get_project_id

        result = {
            "available": False,
            "release": release_id,
            "milestone_id": None,
        }

        try:
            from services.testrail_client import get_testrail_client

            testrail = get_testrail_client()

            if not testrail.is_configured():
                result["message"] = "TestRail credentials not configured"
                return result

            # Get milestone ID for this specific release
            milestone_id = get_milestone_id(release_id)
            project_id = get_project_id(release_id)

            if not milestone_id:
                result["message"] = f"No TestRail milestone configured for {release_id}"
                return result

            result["milestone_id"] = milestone_id

            # Fetch test execution summary from TestRail
            summary = await testrail.get_status_summary(project_id=project_id, milestone_id=milestone_id)

            if summary and not summary.get("error"):
                total = summary.get("total", 0)
                passed = summary.get("passed", 0)
                failed = summary.get("failed", 0)
                blocked = summary.get("blocked", 0)
                untested = summary.get("untested", 0)
                retest = summary.get("retest", 0)

                executed = passed + failed + blocked + retest
                pass_rate = round((passed / total * 100) if total > 0 else 0, 1)

                result = {
                    "available": True,
                    "release": release_id,
                    "milestone_id": milestone_id,
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "blocked": blocked,
                    "untested": untested,
                    "retest": retest,
                    "executed": executed,
                    "pass_rate": pass_rate,
                    "status": "healthy" if pass_rate >= 80 else ("warning" if pass_rate >= 60 else "critical"),
                }
                logger.debug(f"TestRail {release_id} (M{milestone_id}): {passed}/{total} passed ({pass_rate}%)")
            else:
                result["message"] = summary.get("error", "Failed to fetch TestRail data")

        except Exception as e:
            logger.warning(f"Could not fetch TestRail for {release_id}: {e}")
            result["error"] = str(e)

        return result

    # Helper function to fetch customer escalation count for a specific release
    async def fetch_escalation_for_release(release_id: str) -> dict:
        """Fetch open customer escalation count filtered by release fixVersion."""
        try:
            from services.jira_client import get_jira_client

            jira = get_jira_client()
            if not jira.is_configured():
                return {"available": False, "count": 0}

            release_num = release_id.replace("R", "").replace("r", "").strip()
            fix_version = f"{release_num}.0.0"
            escalation_jql = (
                f'component = "NS Client (NSC)" AND resolution = Unresolved '
                f"AND project = Engineering AND issuetype in (Escalation) "
                f'AND "Type of Escalation[Dropdown]" in (Customer) '
                f"AND fixVersion IN ({fix_version})"
            )
            esc_issues = await jira.search_issues(escalation_jql, max_results=500, fetch_all=True, fields=["key"])
            count = len(esc_issues) if esc_issues else 0
            logger.info(f"Customer escalations for {release_id}: {count} open")
            return {
                "available": True,
                "count": count,
                "jira_url": "https://your-org.atlassian.net/issues/?jql=" + urllib.parse.quote(escalation_jql),
            }
        except Exception as e:
            logger.warning(f"Could not fetch escalation count for {release_id}: {e}")
            return {"available": False, "count": 0}

    # Helper function to process a single release using ReleaseDataService directly
    # NO internal HTTP calls - uses the service directly for better performance
    async def process_release(release_id: str) -> dict:
        try:
            # Get phase info FIRST (needed for phase-appropriate JQL in get_release_data)
            release_dates = get_release_dates(release_id)
            today = datetime.now().date()
            current_phase = None  # Will be set if release_dates available

            if release_dates:
                irr_date = (parse_date_safe(release_dates.get("irr")) or datetime.now()).date()
                branch_cut_date = (parse_date_safe(release_dates.get("branch_cut")) or datetime.now()).date()
                final_build_date = (parse_date_safe(release_dates.get("final_build")) or datetime.now()).date()
                # Parse all deploy dates (Day 1-4)
                day1_deploy_date = parse_date_safe(release_dates.get("day1_deploy"))
                day1_deploy_date = day1_deploy_date.date() if day1_deploy_date else None
                day2_deploy_date = parse_date_safe(release_dates.get("day2_deploy"))
                day2_deploy_date = day2_deploy_date.date() if day2_deploy_date else None
                day3_deploy_date = parse_date_safe(release_dates.get("day3_deploy"))
                day3_deploy_date = day3_deploy_date.date() if day3_deploy_date else None
                day4_deploy_date = parse_date_safe(release_dates.get("day4_deploy"))
                day4_deploy_date = day4_deploy_date.date() if day4_deploy_date else None

                # Check if release is fully deployed before determining phase
                if is_release_completed(release_id):
                    phase = "Completed"
                    days_remaining = 0
                    days_remaining_label = "Deployed"
                    days_remaining_date = None
                else:
                    # Determine phase (shows next upcoming phase, not passed ones)
                    current_phase, deadline_name, deadline_date, _, phase_message, _ = determine_phase(
                        today,
                        irr_date,
                        branch_cut_date,
                        final_build_date,
                        day1_deploy_date,
                        day2_deploy_date,
                        day3_deploy_date,
                        day4_deploy_date,
                    )
                    phase = current_phase.replace("_", " ").title()

                    # Overview page: Calculate days remaining until Day 4 Deploy (final deployment)
                    # This differs from Release Readiness page which shows days to next milestone
                    if day4_deploy_date:
                        days_remaining = max(0, (day4_deploy_date - today).days)
                        days_remaining_label = "To Day 4 Deploy"
                        days_remaining_date = day4_deploy_date.isoformat()
                    elif final_build_date:
                        # Fallback to final build if Day 4 not configured
                        days_remaining = max(0, (final_build_date - today).days)
                        days_remaining_label = "To Final Build"
                        days_remaining_date = final_build_date.isoformat()
                    else:
                        days_remaining = 0
                        days_remaining_label = ""
                        days_remaining_date = None
            else:
                phase = "In Progress"
                days_remaining = 0
                days_remaining_label = ""
                days_remaining_date = None

            # Use ReleaseDataService directly instead of HTTP call
            # Pass current_phase to use phase-appropriate JQL (ensures consistency with Release Readiness page)
            release_service = get_release_data_service()
            release_data = await release_service.get_release_data(
                release_id, force_refresh=refresh, phase=current_phase
            )

            # Get summary from service
            summary = release_data.get("summary", {})

            # Calculate counts from centralized data
            open_stories = summary.get("stories", 0)
            open_bugs = summary.get("bugs", 0)
            code_review = summary.get("code_review", 0)
            action_items = summary.get("total", 0)

            # Get blockers using service method - separate P0 and P1
            p0_blockers = release_service.get_p0_blockers(release_data)
            p1_critical = release_service.get_p1_critical(release_data)
            p0_count = len(p0_blockers)
            p1_count = len(p1_critical)
            blocker_count = p0_count + p1_count  # Combined total for compatibility

            # Calculate RRS score using shared utility function
            # This ensures consistency with Release Readiness page
            rrs_score = calculate_rrs_score(
                open_stories=open_stories,
                open_bugs=open_bugs,
                blocker_count=blocker_count,
                code_review_count=code_review,
            )

            logger.info(
                f"Overview {release_id}: phase={phase}, items={action_items} "
                f"(stories={open_stories}, bugs={open_bugs}), blockers={blocker_count}, rrs={rrs_score}%"
            )

            # Determine status based on blocker count (3+ = Blocked)
            if blocker_count >= 3:
                rrs_status = "Blocked"
                rrs_status_reason = f"{blocker_count} blocker/critical items need immediate attention"
            elif blocker_count > 0 or action_items > 20 or rrs_score < 70:
                rrs_status = "At Risk"
                if blocker_count > 0:
                    rrs_status_reason = f"{blocker_count} blocker/critical item(s)"
                elif action_items > 20:
                    rrs_status_reason = f"{action_items} open items remaining"
                else:
                    rrs_status_reason = f"RRS score is {rrs_score}%"
            elif action_items == 0:
                rrs_status = "Ready"
                rrs_status_reason = "All items resolved"
            else:
                rrs_status = "On Track"
                rrs_status_reason = f"{action_items} open items, progressing well"

            # Determine checklist status based on action items and blockers
            if blocker_count >= 3 or action_items > 50:
                checklist_status = "red"
            elif blocker_count > 0 or action_items > 20 or rrs_score < 80:
                checklist_status = "yellow"
            else:
                checklist_status = "green"

            # Fetch TestRail + escalation count in parallel (no added latency)
            testrail_data, escalation_data = await asyncio.gather(
                fetch_testrail_for_release(release_id),
                fetch_escalation_for_release(release_id),
            )

            return {
                "success": True,
                "data": {
                    "id": release_id,
                    "is_current": release_id == current_release_id,
                    "status": "completed" if is_release_completed(release_id) else "active",
                    "phase": phase,
                    "rrs_score": rrs_score,
                    "rrs_status": rrs_status,
                    "rrs_status_reason": rrs_status_reason,
                    "blocker_count": p0_count,  # P0/Blocker priority only
                    "critical_count": p1_count,  # P1/Critical priority only
                    "critical_blocker_total": blocker_count,  # Combined P0+P1 total
                    "open_stories": open_stories,
                    "open_bugs": open_bugs,
                    "action_items": action_items,
                    "code_review": code_review,
                    "days_remaining": days_remaining,
                    "days_remaining_label": days_remaining_label,
                    "days_remaining_date": days_remaining_date,
                    "checklist_status": checklist_status,
                    "testrail": testrail_data,
                    "escalation": escalation_data,
                    "data_source": "release-data-service",
                },
                "insights": {
                    "blocker_count": blocker_count,  # Combined P0+P1 for compatibility
                    "p0_count": p0_count,
                    "p1_count": p1_count,
                    "action_items": action_items,
                    "open_stories": open_stories,
                    "open_bugs": open_bugs,
                },
            }

        except Exception as e:
            logger.error(f"Error fetching overview data for {release_id}: {e}")
            return {
                "success": False,
                "data": {
                    "id": release_id,
                    "is_current": release_id == current_release_id,
                    "status": "completed" if is_release_completed(release_id) else "active",
                    "phase": "Unknown",
                    "rrs_score": 0,
                    "rrs_status": "Error",
                    "blocker_count": 0,
                    "critical_count": 0,
                    "critical_blocker_total": 0,
                    "action_items": 0,
                    "days_remaining": 0,
                    "days_remaining_label": "",
                    "days_remaining_date": None,
                    "checklist_status": "gray",
                    "error": str(e),
                },
                "insights": None,
            }

    # Helper function to fetch PDV summary
    async def fetch_pdv_summary() -> dict:
        """
        Fetch PDV summary using shared helper from jenkins router.

        This ensures Overview shows the SAME numbers as the PDV pages
        by using the exact same calculation logic and parameters.
        """
        pdv_result = {
            "available": False,
            "placeholder": True,
            "stacks_configured": 2,
            "backend": None,
            "endpoint": None,
            "success_rate": 0,
        }

        try:
            # Import shared helper from jenkins router (uses same logic as PDV pages)
            from routers.jenkins import get_pdv_summary_for_overview

            # Get PDV summary using shared function (same params as PDV pages)
            summary = await get_pdv_summary_for_overview(force_refresh=refresh)

            if summary.get("available"):
                backend = summary.get("backend")
                endpoint = summary.get("endpoint")
                combined = summary.get("combined", {})

                # Build backend summary for Overview display
                backend_summary = None
                if backend:
                    backend_summary = {
                        "total": backend.get("total_stacks", 0),
                        "passed": backend.get("total_stacks", 0) - backend.get("failed_stacks", 0),
                        "failed": backend.get("failed_stacks", 0),
                        "status": backend.get("status", "unknown"),
                        "success_rate": backend.get("success_rate", 0),
                        "total_builds": backend.get("total_builds", 0),
                        "builds_passed": backend.get("builds_passed", 0),
                        "stacks": [],  # Populated if needed for action items
                    }

                # Build endpoint summary for Overview display
                endpoint_summary = None
                if endpoint:
                    endpoint_summary = {
                        "total": endpoint.get("total_stacks", 0),
                        "passed": endpoint.get("total_stacks", 0) - endpoint.get("failed_stacks", 0),
                        "failed": endpoint.get("failed_stacks", 0),
                        "status": endpoint.get("status", "unknown"),
                        "success_rate": endpoint.get("success_rate", 0),
                        "total_builds": endpoint.get("total_builds", 0),
                        "builds_passed": endpoint.get("builds_passed", 0),
                        "stacks": [],  # Populated if needed for action items
                    }

                # Calculate total failed stacks for action items
                backend_failed = backend.get("failed_stacks", 0) if backend else 0
                endpoint_failed = endpoint.get("failed_stacks", 0) if endpoint else 0
                total_failed_stacks = backend_failed + endpoint_failed
                total_stacks = (backend.get("total_stacks", 0) if backend else 0) + (
                    endpoint.get("total_stacks", 0) if endpoint else 0
                )

                logger.info(
                    f"PDV Summary: backend_failed={backend_failed}, endpoint_failed={endpoint_failed}, total_failed={total_failed_stacks}"
                )

                pdv_result = {
                    "available": True,
                    "placeholder": False,
                    "total": total_stacks,
                    "passed": total_stacks - total_failed_stacks,
                    "failed": total_failed_stacks,
                    "status": "healthy" if total_failed_stacks == 0 else "failing",
                    "success_rate": combined.get("success_rate", 0),
                    "total_builds": combined.get("total_builds", 0),
                    "builds_passed": combined.get("builds_passed", 0),
                    "last_run": datetime.now().isoformat(),
                    "backend": backend_summary,
                    "endpoint": endpoint_summary,
                }

        except Exception as e:
            logger.warning(f"Could not fetch PDV summary: {e}")

        return pdv_result

    # Lightweight regression summary - makes 2 JIRA calls per epic (not N+2)
    async def fetch_regression_summary() -> dict:
        """Fetch regression progress using lightweight JIRA queries."""
        # Check dedicated regression cache (avoids repeated JIRA calls)
        regression_cache_key = f"regression:{'_'.join(active_release_ids)}"
        if not refresh:
            cached_regression = _response_cache.get(regression_cache_key)
            if cached_regression:
                logger.debug("Returning cached regression summary")
                return cached_regression

        from config import get_regression_epics
        from services.jira_client import get_jira_client

        jira = get_jira_client()
        if not jira.is_configured():
            return {
                "available": False,
                "message": "JIRA not configured",
            }

        regression_data = {}

        async def fetch_epic_progress(release_id: str, epic_key: str) -> dict:
            """Fetch progress for a single epic using quick summary approach."""
            try:
                # Step 1: Get stories under epic (1 call)
                stories = []
                try:
                    parent_link_jql = f'"Parent Link" = {epic_key}'
                    stories = await jira.search_issues(parent_link_jql, max_results=500, fetch_all=True)
                except Exception:
                    try:
                        epic_link_jql = f'"Epic Link" = {epic_key}'
                        stories = await jira.search_issues(epic_link_jql, max_results=500, fetch_all=True)
                    except Exception:
                        pass

                if not stories:
                    return {"total": 0, "done": 0, "completion_percent": 0}

                # Step 2: Get all subtasks in batch (1 call per chunk)
                story_keys = [s.get("key") for s in stories if s.get("key")]
                all_subtasks = []

                # Batch query - chunk to avoid JIRA limits
                chunk_size = 50
                for i in range(0, len(story_keys), chunk_size):
                    chunk = story_keys[i : i + chunk_size]
                    keys_str = ", ".join(chunk)
                    subtasks_jql = f'"Parent Link" in ({keys_str})'

                    try:
                        subtasks = await jira.search_issues(subtasks_jql, max_results=1000, fetch_all=True)
                        all_subtasks.extend(subtasks)
                    except Exception as e:
                        logger.warning(f"Failed to fetch subtasks: {e}")

                # Count statuses
                total = len(all_subtasks)
                done = sum(1 for s in all_subtasks if get_status_category(s.get("status", "")) == "done")
                in_progress = sum(1 for s in all_subtasks if get_status_category(s.get("status", "")) == "in_progress")
                blocked = sum(1 for s in all_subtasks if get_status_category(s.get("status", "")) == "blocked")

                return {
                    "total": total,
                    "done": done,
                    "in_progress": in_progress,
                    "blocked": blocked,
                    "todo": total - done - in_progress - blocked,
                    "completion_percent": round((done / total * 100) if total > 0 else 0),
                }
            except Exception as e:
                logger.warning(f"Error fetching regression progress for {epic_key}: {e}")
                return {"total": 0, "done": 0, "completion_percent": 0, "error": str(e)}

        # Helper to get status category (matches jira.py logic)
        def get_status_category(status: str) -> str:
            status_lower = status.lower() if status else ""
            if status_lower in ("done", "closed", "resolved", "complete", "completed"):
                return "done"
            elif status_lower in ("in progress", "in review", "in development", "code review"):
                return "in_progress"
            elif status_lower in ("blocked", "on hold", "impediment"):
                return "blocked"
            return "todo"

        # Fetch progress for all configured epics in parallel
        tasks = []
        for release_id in active_release_ids:
            epics = get_regression_epics(release_id)
            if epics:
                # Use first epic for now
                tasks.append((release_id, epics[0], fetch_epic_progress(release_id, epics[0])))
            else:
                regression_data[release_id] = {
                    "configured": False,
                    "message": "No regression epic configured",
                }

        # Execute all tasks in parallel
        if tasks:
            results = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)
            for (release_id, epic_key, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    regression_data[release_id] = {
                        "configured": True,
                        "epic_key": epic_key,
                        "error": str(result),
                    }
                else:
                    regression_data[release_id] = {
                        "configured": True,
                        "epic_key": epic_key,
                        **result,
                    }

        result = {
            "available": True,
            "live": True,
            "releases": regression_data,
        }
        # Cache regression summary for 2 minutes
        _response_cache.set(regression_cache_key, result, ttl=120)
        return result

    # Helper function to fetch Jenkins Pipelines summary (Dev Pipelines)
    async def fetch_jenkins_summary() -> dict:
        """Fetch Dev Jenkins pipeline status - uses same calculation as Dev Pipelines page."""
        jenkins_result = {
            "available": False,
            "placeholder": True,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pipelines": [],
            "health_pct": 0,
        }

        try:
            from services.jenkins_client import get_dev_jenkins_client

            dev_jenkins = get_dev_jenkins_client()

            # Clear cache if refresh requested
            if refresh:
                dev_jenkins.clear_cache()

            if dev_jenkins.is_configured():
                # Fetch Dev pipelines with builds - same as Dev Pipelines page
                pipeline_data = await dev_jenkins.get_dev_pipelines(num_builds=10)

                if pipeline_data and not pipeline_data.get("error"):
                    summary = pipeline_data.get("summary", {})
                    pipelines = pipeline_data.get("pipelines", [])

                    # Use the same calculation as Dev Pipelines page
                    # These values are already calculated in get_dev_pipelines()
                    total_runs = summary.get("totalBuilds", 0)
                    total_passed = summary.get("buildsSuccess", 0)
                    total_failed = summary.get("buildsFailed", 0)
                    total_running = summary.get("buildsRunning", 0)
                    health_pct = summary.get("successRate", 0)

                    # Track passing/failing pipeline names (by latest status)
                    passed_pipelines = []
                    failed_pipelines = []
                    for p in pipelines:
                        if p.get("status") == "success":
                            passed_pipelines.append(p.get("displayName") or p.get("name", ""))
                        elif p.get("status") in ("failed", "unstable"):
                            failed_pipelines.append(p.get("displayName") or p.get("name", ""))

                    # Debug logging to compare with Dev Pipelines page
                    logger.info(
                        f"Overview DevJenkins: total_runs={total_runs}, total_passed={total_passed}, total_failed={total_failed}, health_pct={health_pct}%"
                    )

                    jenkins_result = {
                        "available": True,
                        "placeholder": False,
                        "total": summary.get("total", len(pipelines)),
                        "passed": summary.get("success", len(passed_pipelines)),
                        "failed": summary.get("failed", 0) + summary.get("unstable", 0),
                        "status": "healthy" if len(failed_pipelines) == 0 else "failing",
                        "health_pct": health_pct,
                        "total_runs": total_runs,
                        "total_passed": total_passed,
                        "total_failed": total_failed,
                        "total_running": total_running,
                        "passed_pipelines": passed_pipelines,
                        "failed_pipelines": failed_pipelines,
                    }
                    logger.info(f"Dev Pipelines: {health_pct}% ({total_passed}/{total_runs} builds)")
            else:
                jenkins_result["message"] = "Dev Jenkins not configured"

        except Exception as e:
            logger.warning(f"Could not fetch Dev Jenkins summary: {e}")
            jenkins_result["error"] = str(e)

        return jenkins_result

    # Helper function to fetch TestRail Automation summary for current release
    async def fetch_testrail_summary() -> dict:
        """Fetch TestRail test execution summary for current release (no fallback)."""
        from config import get_milestone_id, get_project_id

        testrail_result = {
            "available": False,
            "placeholder": True,
            "release": current_release_id,
            "message": "TestRail not configured",
        }

        try:
            from services.testrail_client import get_testrail_client

            testrail = get_testrail_client()

            if not testrail.is_configured():
                testrail_result["message"] = "TestRail credentials not configured"
                return testrail_result

            # Get milestone ID for current release - NO FALLBACK
            milestone_id = get_milestone_id(current_release_id)
            project_id = get_project_id(current_release_id)

            if not milestone_id:
                testrail_result["message"] = f"No TestRail milestone configured for {current_release_id}"
                return testrail_result

            # Fetch test execution summary from TestRail
            summary = await testrail.get_status_summary(project_id=project_id, milestone_id=milestone_id)

            if summary and not summary.get("error"):
                total = summary.get("total", 0)
                passed = summary.get("passed", 0)
                failed = summary.get("failed", 0)
                blocked = summary.get("blocked", 0)
                untested = summary.get("untested", 0)
                retest = summary.get("retest", 0)

                executed = passed + failed + blocked + retest
                pass_rate = round((passed / total * 100) if total > 0 else 0, 1)
                platform_breakdown = summary.get("by_platform", {})

                testrail_result = {
                    "available": True,
                    "placeholder": False,
                    "release": current_release_id,
                    "milestone_id": milestone_id,
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "blocked": blocked,
                    "untested": untested,
                    "retest": retest,
                    "executed": executed,
                    "pass_rate": pass_rate,
                    "status": "healthy" if pass_rate >= 80 else ("warning" if pass_rate >= 60 else "critical"),
                    "by_platform": platform_breakdown,
                }
                logger.info(f"TestRail {current_release_id} (M{milestone_id}): {passed}/{total} passed ({pass_rate}%)")
            else:
                testrail_result["message"] = summary.get("error", "Failed to fetch TestRail data")

        except Exception as e:
            logger.warning(f"Could not fetch TestRail summary: {e}")
            testrail_result["error"] = str(e)

        return testrail_result

    # Helper function to fetch Stack Health summary from Stack Monitoring data
    async def fetch_stack_health_summary() -> dict:
        """Read stack health summary using same formula as Stack Monitoring page.

        Formula: Score = (Healthy×100 + Warning×50 + Critical×0) / Total Stacks
        """
        from services.stack_monitoring import get_monitoring_service

        try:
            monitoring_service = get_monitoring_service()
            if not monitoring_service.master_config:
                return {"available": False, "placeholder": True}

            summary = monitoring_service.get_stack_summary()
            if not summary:
                return {"available": False, "placeholder": True}

            # Total configured stacks (from CONTEXT_MAP/config)
            total_configured_stacks = len(summary)

            # Count stacks by status (same logic as frontend calculateHealthScore)
            # Frontend logic: critical if critical>0 OR crashLoops>0
            #                 warning if warning>0 OR restarts>5
            healthy_stacks = 0
            warning_stacks = 0
            critical_stacks = 0
            initializing_stacks = 0
            unhealthy_stack_list = []

            for stack_id, counts in summary.items():
                stack_total = counts.get("total", 0)
                if stack_total == 0:
                    initializing_stacks += 1  # Stack has no data yet
                    continue

                stack_critical = counts.get("critical", 0)
                stack_warning = counts.get("warning", 0)
                stack_restarts = counts.get("restarts", 0)

                # Same logic as frontend: critical > 0 means critical stack
                # warning > 0 OR restarts > 5 means warning stack
                if stack_critical > 0:
                    critical_stacks += 1
                    unhealthy_stack_list.append({"stack": stack_id, "unhealthy": stack_critical + stack_warning})
                elif stack_warning > 0 or stack_restarts > 5:
                    warning_stacks += 1
                    unhealthy_stack_list.append({"stack": stack_id, "unhealthy": stack_warning})
                else:
                    healthy_stacks += 1

            # total_stacks = stacks with data (same as Stack Monitoring healthScore.total)
            stacks_with_data = healthy_stacks + warning_stacks + critical_stacks
            if stacks_with_data == 0:
                return {"available": False, "placeholder": True}

            # Same formula as Stack Monitoring: (Healthy×100 + Warning×50 + Critical×0) / Total
            health_score = round((healthy_stacks * 100 + warning_stacks * 50) / stacks_with_data)

            cache_age = monitoring_service.get_cache_age()
            return {
                "available": True,
                "placeholder": False,
                "total_stacks": stacks_with_data,  # Stacks with actual data (for health calc)
                "total_configured_stacks": total_configured_stacks,  # All configured stacks
                "healthy_stacks": healthy_stacks,
                "warning_stacks": warning_stacks,
                "critical_stacks": critical_stacks,
                "initializing_stacks": initializing_stacks,
                "health_pct": health_score,
                "unhealthy_stacks": unhealthy_stack_list,
                "cache_age_seconds": round(cache_age) if cache_age else None,
            }
        except Exception as e:
            logger.warning(f"Stack health summary error: {e}")
            return {"available": False, "placeholder": True, "error": str(e)}

    # Per-task timeout wrapper: prevents any single slow service from blocking the response
    TASK_TIMEOUT = 15  # seconds - each task gets max 15s before graceful fallback

    async def with_timeout(coro, label: str, fallback: dict):
        """Run a coroutine with a timeout. Returns fallback on timeout/error."""
        task_start = time.time()
        try:
            result = await asyncio.wait_for(coro, timeout=TASK_TIMEOUT)
            task_elapsed = time.time() - task_start
            logger.info(f"  ⏱ {label}: {task_elapsed:.2f}s")
            return result
        except asyncio.TimeoutError:
            task_elapsed = time.time() - task_start
            logger.warning(f"  ⏱ {label}: TIMEOUT after {task_elapsed:.2f}s (limit {TASK_TIMEOUT}s)")
            return {**fallback, "timed_out": True}
        except Exception as e:
            task_elapsed = time.time() - task_start
            logger.warning(f"  ⏱ {label}: ERROR after {task_elapsed:.2f}s - {e}")
            return {**fallback, "error": str(e)}

    # PARALLEL FETCH: Fetch all data concurrently with per-task timeouts
    # In lite mode, skip only genuinely slow tasks (regression).
    # Stack health is a pure in-memory cache read (<1ms) so it runs in both modes.
    release_coros = [
        with_timeout(
            process_release(rid),
            f"Release({rid})",
            {
                "success": False,
                "data": {
                    "id": rid,
                    "is_current": rid == current_release_id,
                    "status": "completed" if is_release_completed(rid) else "active",
                    "phase": "Unknown",
                    "rrs_score": 0,
                    "rrs_status": "Timeout",
                    "blocker_count": 0,
                    "critical_count": 0,
                    "critical_blocker_total": 0,
                    "action_items": 0,
                    "days_remaining": 0,
                    "days_remaining_label": "",
                    "days_remaining_date": None,
                    "checklist_status": "gray",
                },
                "insights": None,
            },
        )
        for rid in active_release_ids
    ]
    pdv_coro = with_timeout(
        fetch_pdv_summary(),
        "PDV Summary",
        {"available": False, "placeholder": True, "stacks_configured": 2, "backend": None, "endpoint": None},
    )
    jenkins_coro = with_timeout(
        fetch_jenkins_summary(),
        "Dev Jenkins",
        {"available": False, "placeholder": True, "total": 0, "passed": 0, "failed": 0},
    )
    testrail_coro = with_timeout(
        fetch_testrail_summary(),
        "TestRail",
        {"available": False, "placeholder": True, "message": "Failed to fetch TestRail data"},
    )
    stack_health_coro = with_timeout(
        fetch_stack_health_summary(), "Stack Health", {"available": False, "placeholder": True}
    )

    if lite:
        all_results = await asyncio.gather(
            *release_coros, pdv_coro, jenkins_coro, testrail_coro, stack_health_coro, return_exceptions=True
        )
        num_releases = len(release_coros)
        release_results = all_results[:num_releases]
        pdv_summary = (
            all_results[num_releases]
            if not isinstance(all_results[num_releases], Exception)
            else {"available": False, "placeholder": True}
        )
        jenkins_summary = (
            all_results[num_releases + 1]
            if not isinstance(all_results[num_releases + 1], Exception)
            else {"available": False, "placeholder": True}
        )
        testrail_summary = (
            all_results[num_releases + 2]
            if not isinstance(all_results[num_releases + 2], Exception)
            else {"available": False, "placeholder": True}
        )
        regression_summary = {"available": False, "placeholder": True, "message": "Skipped in lite mode"}
        stack_health_summary = (
            all_results[num_releases + 3]
            if not isinstance(all_results[num_releases + 3], Exception)
            else {"available": False, "placeholder": True}
        )
    else:
        regression_coro = with_timeout(
            fetch_regression_summary(),
            "Regression",
            {"available": False, "message": "Timed out fetching regression data"},
        )

        all_results = await asyncio.gather(
            *release_coros,
            pdv_coro,
            jenkins_coro,
            testrail_coro,
            stack_health_coro,
            regression_coro,
            return_exceptions=True,
        )
        num_releases = len(release_coros)
        release_results = all_results[:num_releases]
        pdv_summary = (
            all_results[num_releases]
            if not isinstance(all_results[num_releases], Exception)
            else {"available": False, "placeholder": True}
        )
        jenkins_summary = (
            all_results[num_releases + 1]
            if not isinstance(all_results[num_releases + 1], Exception)
            else {"available": False, "placeholder": True}
        )
        testrail_summary = (
            all_results[num_releases + 2]
            if not isinstance(all_results[num_releases + 2], Exception)
            else {"available": False, "placeholder": True}
        )
        stack_health_summary = (
            all_results[num_releases + 3]
            if not isinstance(all_results[num_releases + 3], Exception)
            else {"available": False, "placeholder": True}
        )
        regression_summary = (
            all_results[num_releases + 4]
            if not isinstance(all_results[num_releases + 4], Exception)
            else {"available": False, "placeholder": True}
        )

    # Build releases_data and ai_insights from results
    for result in release_results:
        if isinstance(result, Exception):
            continue
        releases_data.append(result["data"])

        # Add insights based on real data
        if result.get("insights"):
            insights = result["insights"]
            release_id = result["data"]["id"]
            blocker_count = insights["blocker_count"]
            action_items = insights["action_items"]
            open_stories = insights["open_stories"]
            open_bugs = insights["open_bugs"]

            if action_items > 0:
                if blocker_count > 0:
                    ai_insights.append(
                        {
                            "type": "critical",
                            "message": f"{blocker_count} blocker bugs need immediate attention in {release_id}",
                            "action": "Review and prioritize",
                            "release": release_id,
                        }
                    )
                elif action_items > 10:
                    ai_insights.append(
                        {
                            "type": "warning",
                            "message": f"{action_items} open items in {release_id} ({open_stories} stories, {open_bugs} bugs)",
                            "action": "Review progress",
                            "release": release_id,
                        }
                    )

    # Add general insights
    if not ai_insights:
        if all(r.get("checklist_status") == "green" for r in releases_data):
            ai_insights.append(
                {
                    "type": "success",
                    "message": "All releases are on track with no critical issues",
                    "action": None,
                    "release": None,
                }
            )

    # Build response and cache it
    elapsed = time.time() - start_time
    logger.info(f"Overview data fetched in {elapsed:.2f}s")

    response = {
        "releases": releases_data,
        "pdv_summary": pdv_summary,
        "regression_summary": regression_summary,
        "jenkins_summary": jenkins_summary,
        "testrail_summary": testrail_summary,
        "stack_health_summary": stack_health_summary,
        "ai_insights": ai_insights,
        "lastUpdated": datetime.now().isoformat(),
        "fetch_time_seconds": round(elapsed, 2),
    }

    # Cache the response for 5 minutes (landing page benefits from longer cache)
    _response_cache.set(cache_key, response, ttl=300)
    # When full data is cached, clear stale lite cache so lite requests use full data
    if not lite:
        _response_cache.clear("overview_data_lite")

    return response

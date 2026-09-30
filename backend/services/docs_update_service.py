"""
Documentation Updates Service
==============================
Fetches bugs and NPLANs that need documentation updates based on the Release Note
or Documentation Required fields.

Queries Jira for:
1. Bug issues with:
   - affectedVersion matching the selected release
   - labels = jira_escalated
   - Release Note[Dropdown] = "For Customer" OR Documentation Required (cf[24136]) = "Yes"

2. NPLAN issues with:
   - Delivery Target (Beta) OR Delivery Target (GA) matching the selected release
   - Release Note (cf[24133]) = "For Customer" OR Documentation Required (cf[24136]) = "Yes"

This is used by the Documentation Updates section to help the docs team
track which items require customer-facing documentation changes.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from services.jira_client import get_jira_client

logger = logging.getLogger(__name__)

# Mapping from YY-QN-Mon prefix to release number
# Delivery Target values can be either:
# - "25-Q3-Sep-R130" (with release suffix)
# - "25-Q3-Sep" (without release suffix)
# - "26-Q2-May" (without release suffix)
# This mapping helps extract release number from the prefix when suffix is missing
DELIVERY_TARGET_PREFIX_TO_RELEASE = {
    # 2026 releases
    "26-Q3-Jul": "R139",
    "26-Q2-Jun": "R138",
    "26-Q2-May": "R137",
    "26-Q2-Apr": "R136",
    "26-Q1-Mar": "R135",
    "26-Q1-Feb": "R134",
    # 2025 releases
    "25-Q4-Dec": "R133",
    "25-Q4-Nov": "R132",
    "25-Q4-Oct": "R131",
    "25-Q3-Sep": "R130",
    "25-Q3-Aug": "R129",
    "25-Q3-Jul": "R128",
    "25-Q2-Jun": "R127",
    "25-Q2-May": "R126",
    "25-Q2-Apr": "R125",
    "25-Q1-Mar": "R124",
    "25-Q1-Feb": "R123",
    "25-Q1-Jan": "R122",
    # 2024 releases
    "24-Q4-Dec": "R121",
    "24-Q4-Nov": "R120",
    "24-Q4-Oct": "R119",
}

# Reverse mapping: release -> (beta_value, ga_value)
RELEASE_TO_DELIVERY_TARGET = {
    release: (prefix, prefix) for prefix, release in DELIVERY_TARGET_PREFIX_TO_RELEASE.items()
}

# Custom field IDs for NPLAN fields
CF_RELEASE_NOTE_NPLAN = "customfield_24133"  # Release Note for NPLANs
CF_DELIVERY_TARGET_BETA = "customfield_18128"  # Delivery Target (Beta)
CF_DELIVERY_TARGET_GA = "customfield_18130"  # Delivery Target (GA)
CF_DOCUMENTATION_REQUIRED = "customfield_24136"  # Documentation Required (Yes/No)


def extract_release_from_delivery_target(delivery_target: str) -> Optional[str]:
    """
    Extract release number from a Delivery Target value.

    Handles both formats:
    - "25-Q3-Sep-R130" -> "R130"
    - "25-Q3-Sep" -> "R130" (using prefix mapping)
    - "26-Q2-May" -> "R137" (using prefix mapping)

    Returns release key like "R130" or None if not found.
    """
    if not delivery_target:
        return None

    # First, try to extract R### from the string directly
    match = re.search(r"R(\d+)", delivery_target)
    if match:
        return f"R{match.group(1)}"

    # If no R### found, try to match the prefix (YY-QN-Mon)
    # Value could be "25-Q3-Sep" or "26-Q2-May"
    prefix_match = re.match(r"(\d{2}-Q\d-[A-Za-z]{3})", delivery_target)
    if prefix_match:
        prefix = prefix_match.group(1)
        release = DELIVERY_TARGET_PREFIX_TO_RELEASE.get(prefix)
        if release:
            return release

    return None


class DocsUpdateService:
    """Service for fetching bugs that need documentation updates."""

    CACHE_TTL = 120  # 2 minutes

    def __init__(self):
        self._jira = get_jira_client()
        self._bugs_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

    def _get_cached(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached value if not expired."""
        if key in self._bugs_cache:
            ts, data = self._bugs_cache[key]
            if time.time() - ts < self.CACHE_TTL:
                return data
        return None

    def _set_cache(self, key: str, data: List[Dict[str, Any]]):
        """Cache a value."""
        self._bugs_cache[key] = (time.time(), data)

    def clear_cache(self):
        """Clear all cached data including Jira client cache."""
        self._bugs_cache.clear()
        self._jira.clear_cache()
        logger.info("Docs update service cache cleared")

    async def get_available_releases(self) -> List[Dict[str, Any]]:
        """
        Get list of releases (affected versions) that have bugs needing docs updates.

        Returns a list of releases with counts, sorted by version number descending.

        Filters for:
        - Release Note = "For Customer"
        - Documentation Required = "Yes"
        - labels = jira_escalated (customer escalated bugs)
        """
        # Query customer escalated bugs with Release Note = "For Customer" OR Documentation Required = "Yes"
        # cf[24136] = Documentation Required field
        jql = """
            issuetype = Bug
            AND labels = jira_escalated
            AND ("Release Note[Dropdown]" = "For Customer" OR cf[24136] = "Yes")
            ORDER BY created DESC
        """.strip()

        cached = self._get_cached("releases")
        if cached is not None:
            return cached

        try:
            bugs = await self._jira.search_issues(
                jql=jql,
                max_results=500,
                fetch_all=True,
            )

            logger.info("Found %d bugs with Release Note = For Customer OR Documentation Required = Yes", len(bugs))

            # Group by affectedVersions - normalize AC- prefix (treat AC-134.0.0 and 134.0.0 as same)
            # Track separate counts for release notes vs documentation required
            release_data: Dict[str, Dict[str, int]] = {}
            for bug in bugs:
                affected_versions = bug.get("affectedVersions", [])
                release_note = bug.get("release_note")
                docs_required = bug.get("documentation_required")

                if affected_versions:
                    for ver in affected_versions:
                        if ver:
                            # Normalize: remove AC- prefix for grouping
                            normalized = ver.replace("AC-", "")
                            if normalized not in release_data:
                                release_data[normalized] = {"total": 0, "release_notes": 0, "documentation": 0}
                            release_data[normalized]["total"] += 1
                            if release_note == "For Customer":
                                release_data[normalized]["release_notes"] += 1
                            if docs_required == "Yes":
                                release_data[normalized]["documentation"] += 1

            releases = [
                {
                    "id": ver,
                    "name": ver,
                    "bug_count": data["total"],
                    "release_notes_count": data["release_notes"],
                    "documentation_count": data["documentation"],
                }
                for ver, data in release_data.items()
            ]

            def version_sort_key(r):
                parts = r["id"].replace("AC-", "").split(".")
                try:
                    return tuple(int(p) for p in parts)
                except ValueError:
                    return (0,)

            releases.sort(key=version_sort_key, reverse=True)

            self._set_cache("releases", releases)
            return releases

        except Exception as e:
            logger.error("Error fetching releases for docs updates: %s", e)
            return []

    async def get_bugs_needing_docs(
        self,
        affected_version: str,
        max_results: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Fetch bugs that need documentation updates for a specific release.

        Args:
            affected_version: The affected version to filter by (e.g., "AC-134.0.0")
            max_results: Maximum number of bugs to return

        Returns:
            List of bug dicts with key fields for the docs team
        """
        cache_key = f"bugs:{affected_version}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.info("Returning %d cached bugs for %s", len(cached), affected_version)
            return cached

        # Handle "No Affected Version" special case
        # Query for both AC-prefixed and non-prefixed versions (e.g., AC-134.0.0 and 134.0.0)
        if affected_version == "No Affected Version":
            version_clause = "affectedVersion is EMPTY"
        else:
            # Remove AC- prefix if present to get the base version
            base_version = affected_version.replace("AC-", "")
            version_clause = f'(affectedVersion = "AC-{base_version}" OR affectedVersion = "{base_version}")'

        # cf[24136] = Documentation Required field
        # Show bugs that need Release Notes OR Documentation Required
        jql = f"""
            issuetype = Bug
            AND labels = jira_escalated
            AND {version_clause}
            AND ("Release Note[Dropdown]" = "For Customer" OR cf[24136] = "Yes")
            ORDER BY created DESC
        """.strip()

        try:
            bugs = await self._jira.search_issues(
                jql=jql,
                max_results=max_results,
                fetch_all=True,
            )

            logger.info("Fetched %d bugs needing docs for %s", len(bugs), affected_version)

            result = []
            for bug in bugs:
                affected_versions = bug.get("affectedVersions", [])
                affected_version_str = ", ".join(affected_versions) if affected_versions else "—"

                # Get components list
                components = bug.get("components", [])
                component_str = ", ".join(components) if components else "Unknown"

                result.append(
                    {
                        "key": bug.get("key"),
                        "summary": bug.get("summary"),
                        "status": bug.get("status"),
                        "priority": bug.get("priority"),
                        "assignee": bug.get("assignee"),
                        "component": component_str,
                        "components": components,
                        "sub_component": bug.get("sub_component") or "Unknown",
                        "affected_version_str": affected_version_str,
                        "release_note": bug.get("release_note"),
                        "documentation_required": bug.get("documentation_required"),
                        "created": bug.get("created"),
                        "resolution_date": bug.get("resolutiondate"),
                        "url": bug.get("url"),
                        "description": (bug.get("description") or "")[:500],
                    }
                )

            self._set_cache(cache_key, result)
            return result

        except Exception as e:
            logger.error("Error fetching bugs for docs update (%s): %s", affected_version, e)
            return []

    async def get_summary(self, affected_version: Optional[str] = None) -> Dict[str, Any]:
        """
        Get summary statistics for documentation updates.

        Args:
            affected_version: Optional version filter. If None, returns stats for all.

        Returns:
            Dict with total count, by_priority breakdown, by_component breakdown
        """
        if affected_version:
            bugs = await self.get_bugs_needing_docs(affected_version)
        else:
            jql = """
                issuetype = Bug
                AND labels = jira_escalated
                AND ("Release Note[Dropdown]" = "For Customer" OR cf[24136] = "Yes")
            """.strip()

            bugs = await self._jira.search_issues(
                jql=jql,
                max_results=500,
                fetch_all=True,
            )

        priority_counts: Dict[str, int] = {}
        component_counts: Dict[str, int] = {}

        for bug in bugs:
            priority = bug.get("priority", "Unknown")
            component = bug.get("sub_component") or "Unknown"

            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            component_counts[component] = component_counts.get(component, 0) + 1

        return {
            "total_bugs": len(bugs),
            "affected_version": affected_version or "all",
            "by_priority": priority_counts,
            "by_component": [
                {"component": name, "count": count}
                for name, count in sorted(component_counts.items(), key=lambda x: -x[1])
            ],
        }

    def _get_delivery_target_values(self, release: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the full Delivery Target values for a given release number.

        Args:
            release: Release number like "R135" or "135"

        Returns:
            Tuple of (beta_value, ga_value) or (None, None) if not found
        """
        # Normalize release to R### format
        if not release.startswith("R"):
            release = f"R{release}"

        # Check static mapping first
        if release in RELEASE_TO_DELIVERY_TARGET:
            return RELEASE_TO_DELIVERY_TARGET[release]

        # Try to find in cached delivery targets
        cached_targets = self._get_cached("delivery_targets")
        if cached_targets:
            for target in cached_targets:
                if release in target.get("value", ""):
                    return (target.get("value"), target.get("value"))

        return (None, None)

    async def _discover_delivery_targets(self) -> List[Dict[str, Any]]:
        """
        Discover available Delivery Target values from NPLAN issues.

        Returns list of unique Delivery Target (Beta) and (GA) values.
        """
        cached = self._get_cached("delivery_targets")
        if cached is not None:
            return cached

        try:
            # Query NPLANs to discover delivery target values
            jql = "project = NPLAN ORDER BY created DESC"

            nplans = await self._jira.search_issues(
                jql=jql,
                max_results=500,
                fetch_all=False,
                fields=[CF_DELIVERY_TARGET_BETA, CF_DELIVERY_TARGET_GA, "key"],
            )

            # Extract unique values
            beta_values = {}
            ga_values = {}

            for nplan in nplans:
                # Get raw field values (they come pre-parsed from jira_client)
                # We need to check if there's additional data in the raw response
                beta_val = nplan.get("delivery_target_beta")
                ga_val = nplan.get("delivery_target_ga")

                if beta_val and beta_val not in beta_values:
                    beta_values[beta_val] = {"value": beta_val, "field": "beta"}
                if ga_val and ga_val not in ga_values:
                    ga_values[ga_val] = {"value": ga_val, "field": "ga"}

            all_values = list(beta_values.values()) + list(ga_values.values())
            self._set_cache("delivery_targets", all_values)

            return all_values

        except Exception as e:
            logger.error("Error discovering delivery targets: %s", e)
            return []

    async def get_nplans_needing_docs(
        self,
        release: str,
        max_results: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Fetch NPLANs that need documentation updates for a specific release.

        Uses Delivery Target (Beta) OR Delivery Target (GA) to filter by release.
        Handles delivery target formats with or without R### suffix.

        Args:
            release: The release to filter by (e.g., "R135", "135", "26-Q1-Mar-R135")
            max_results: Maximum number of NPLANs to return

        Returns:
            List of NPLAN dicts with key fields for the docs team
        """
        cache_key = f"nplans:{release}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.info("Returning %d cached NPLANs for %s", len(cached), release)
            return cached

        # Extract release number from input (handle formats like "R135", "135", "26-Q1-Mar-R135")
        release_match = re.search(r"R?(\d+)", release)
        if not release_match:
            logger.warning("Could not extract release number from: %s", release)
            return []

        release_num = release_match.group(1)
        target_release = f"R{release_num}"

        # Fetch ALL NPLANs that need docs (Release Note = For Customer, Documentation Required = Yes)
        # Then filter by release in Python since delivery target format is inconsistent
        # Show NPLANs that need Release Notes OR Documentation Required
        jql = """
            project = NPLAN
            AND (cf[24133] = "For Customer" OR cf[24136] = "Yes")
            ORDER BY created DESC
        """.strip()

        logger.info("NPLAN JQL: %s (filtering for release %s in Python)", jql, target_release)

        try:
            nplans = await self._jira.search_issues(
                jql=jql,
                max_results=500,  # Fetch more to filter in Python
                fetch_all=True,
            )

            logger.info("Fetched %d total NPLANs needing docs, filtering for %s", len(nplans), target_release)

            result = []
            for nplan in nplans:
                # Get delivery target values
                beta_val = nplan.get("delivery_target_beta") or ""
                ga_val = nplan.get("delivery_target_ga") or ""

                # Extract releases from delivery targets
                beta_release = extract_release_from_delivery_target(beta_val)
                ga_release = extract_release_from_delivery_target(ga_val)

                # Check if this NPLAN belongs to the target release
                if beta_release != target_release and ga_release != target_release:
                    continue  # Skip - doesn't match target release

                fix_versions = nplan.get("fixVersions", [])
                fix_version_str = ", ".join(fix_versions) if fix_versions else "—"

                components = nplan.get("components", [])
                component_str = ", ".join(components) if components else ""

                # Documentation funnel fields
                writer = nplan.get("writer")
                toi_date = nplan.get("toi_date")
                toi_completed = nplan.get("toi_completed")
                release_note_description = nplan.get("release_note_description")
                status = nplan.get("status") or ""

                # Debug logging for first few items
                if len(result) < 3:
                    logger.info(
                        "NPLAN %s funnel fields: writer=%s, toi_date=%s, toi_completed=%s, status=%s",
                        nplan.get("key"),
                        writer,
                        toi_date,
                        toi_completed,
                        status,
                    )

                # Determine documentation stage
                is_done = status.lower() in ["done", "closed", "resolved", "complete", "ga"]
                has_writer = bool(writer)
                has_toi_scheduled = bool(toi_date)
                has_toi_completed = toi_completed and toi_completed.lower() == "yes"
                has_draft = bool(release_note_description and len(release_note_description.strip()) > 10)

                result.append(
                    {
                        "key": nplan.get("key"),
                        "summary": nplan.get("summary"),
                        "status": status,
                        "priority": nplan.get("priority"),
                        "assignee": nplan.get("assignee"),
                        "component": component_str,
                        "components": components,
                        "sub_component": nplan.get("sub_component") or "",
                        "fix_version_str": fix_version_str,
                        "release_note": nplan.get("release_note"),
                        "documentation_required": nplan.get("documentation_required"),
                        "delivery_target_beta": beta_val,
                        "delivery_target_ga": ga_val,
                        "created": nplan.get("created"),
                        "resolution_date": nplan.get("resolutiondate"),
                        "url": nplan.get("url"),
                        "description": (nplan.get("description") or "")[:500],
                        "type": "NPLAN",
                        # Documentation funnel fields
                        "writer": writer,
                        "toi_date": toi_date,
                        "toi_completed": toi_completed,
                        "has_release_note_description": has_draft,
                        # Computed funnel stages for this item
                        "doc_stage": {
                            "has_writer": has_writer,
                            "has_toi_scheduled": has_toi_scheduled,
                            "has_toi_completed": has_toi_completed,
                            "has_draft": has_draft,
                            "is_done": is_done,
                        },
                    }
                )

            logger.info("Filtered to %d NPLANs for release %s", len(result), target_release)

            if len(result) <= max_results:
                self._set_cache(cache_key, result)
            return result[:max_results]

        except Exception as e:
            logger.error("Error fetching NPLANs for docs update (%s): %s", release, e)
            return []

    async def get_nplan_releases(self) -> List[Dict[str, Any]]:
        """
        Get list of releases that have NPLANs needing documentation updates.

        Uses Delivery Target (Beta) as the primary release indicator since
        release notes need to be updated when features go to Beta.

        Returns releases with counts, sorted by release number descending.
        """
        # Query NPLANs with Release Note = "For Customer" and Documentation Required = "Yes"
        # cf[24133] = Release Note field for NPLANs
        # cf[24136] = Documentation Required field
        # Show NPLANs that need Release Notes OR Documentation Required
        jql = """
            project = NPLAN
            AND (cf[24133] = "For Customer" OR cf[24136] = "Yes")
            ORDER BY created DESC
        """.strip()

        cached = self._get_cached("nplan_releases")
        if cached is not None:
            return cached

        try:
            nplans = await self._jira.search_issues(
                jql=jql,
                max_results=500,
                fetch_all=True,
            )

            logger.info("Found %d NPLANs with Release Note = For Customer OR Documentation Required = Yes", len(nplans))

            # Group by Delivery Target - count NPLAN for each release it appears in
            # An NPLAN can appear in multiple releases (if Beta != GA)
            # This matches the behavior of get_nplans_needing_docs() which uses OR condition
            release_data: Dict[str, Dict[str, Any]] = {}

            for nplan in nplans:
                beta_val = nplan.get("delivery_target_beta") or ""
                ga_val = nplan.get("delivery_target_ga") or ""
                release_note = nplan.get("release_note")
                docs_required = nplan.get("documentation_required")

                # Track which releases this NPLAN belongs to (can be multiple)
                releases_for_nplan = set()

                # Extract release from Beta (handles both "25-Q3-Sep-R130" and "25-Q3-Sep" formats)
                beta_release = extract_release_from_delivery_target(beta_val)
                if beta_release:
                    releases_for_nplan.add((beta_release, beta_val))

                # Extract release from GA
                ga_release = extract_release_from_delivery_target(ga_val)
                if ga_release:
                    releases_for_nplan.add((ga_release, ga_val))

                # Count this NPLAN for each release it belongs to
                for release_key, delivery_value in releases_for_nplan:
                    # Extract numeric part for sorting
                    num_match = re.search(r"R(\d+)", release_key)
                    release_num = int(num_match.group(1)) if num_match else 0

                    if release_key not in release_data:
                        release_data[release_key] = {
                            "id": release_key,
                            "name": release_key,
                            "full_value": delivery_value,
                            "nplan_count": 0,
                            "release_notes_count": 0,
                            "documentation_count": 0,
                            "release_num": release_num,
                        }
                    release_data[release_key]["nplan_count"] += 1
                    if release_note == "For Customer":
                        release_data[release_key]["release_notes_count"] += 1
                    if docs_required == "Yes":
                        release_data[release_key]["documentation_count"] += 1

            releases = list(release_data.values())

            # Sort by release number descending
            releases.sort(key=lambda r: r.get("release_num", 0), reverse=True)

            # Clean up internal field
            for r in releases:
                r.pop("release_num", None)

            self._set_cache("nplan_releases", releases)
            return releases

        except Exception as e:
            logger.error("Error fetching NPLAN releases for docs updates: %s", e)
            return []

    async def get_documentation_funnel(self, release: str) -> Dict[str, Any]:
        """
        Get documentation funnel statistics for a specific release.

        The funnel tracks NPLANs through the documentation process:
        1. Needs Docs - Total items with Release Note = "For Customer"
        2. Writer Assigned - Items with a technical writer assigned
        3. TOI Scheduled - Items with a TOI Highlight Date set
        4. Draft Complete - Items with Release Note Description filled
        5. Published - Items with status Done/Closed (docs complete)

        Args:
            release: The release to get funnel stats for (e.g., "R135")

        Returns:
            Dict with funnel stages and counts
        """
        # Get NPLANs for this release (uses cached data if available)
        nplans = await self.get_nplans_needing_docs(release)

        total = len(nplans)
        if total == 0:
            return {
                "release": release,
                "total": 0,
                "stages": [],
                "completion_rate": 0,
            }

        # Count items at each stage
        with_writer = 0
        with_toi_scheduled = 0
        with_toi_completed = 0
        with_draft = 0
        published = 0

        for nplan in nplans:
            doc_stage = nplan.get("doc_stage", {})

            if doc_stage.get("has_writer"):
                with_writer += 1
            if doc_stage.get("has_toi_scheduled"):
                with_toi_scheduled += 1
            if doc_stage.get("has_toi_completed"):
                with_toi_completed += 1
            if doc_stage.get("has_draft"):
                with_draft += 1
            if doc_stage.get("is_done"):
                published += 1

        stages = [
            {
                "name": "Needs Docs",
                "count": total,
                "percentage": 100,
                "color": "#3b82f6",
                "description": "Total items requiring documentation",
            },
            {
                "name": "Writer Assigned",
                "count": with_writer,
                "percentage": round((with_writer / total) * 100, 1) if total > 0 else 0,
                "color": "#8b5cf6",
                "description": "Technical writer assigned to document",
            },
            {
                "name": "TOI Scheduled",
                "count": with_toi_scheduled,
                "percentage": round((with_toi_scheduled / total) * 100, 1) if total > 0 else 0,
                "color": "#f59e0b",
                "description": "TOI Highlight session scheduled",
            },
            {
                "name": "Draft Complete",
                "count": with_draft,
                "percentage": round((with_draft / total) * 100, 1) if total > 0 else 0,
                "color": "#06b6d4",
                "description": "Release Note Description filled",
            },
            {
                "name": "Published",
                "count": published,
                "percentage": round((published / total) * 100, 1) if total > 0 else 0,
                "color": "#10b981",
                "description": "Documentation complete (Done/Closed)",
            },
        ]

        completion_rate = round((published / total) * 100, 1) if total > 0 else 0

        return {
            "release": release,
            "total": total,
            "stages": stages,
            "completion_rate": completion_rate,
            "summary": {
                "with_writer": with_writer,
                "with_toi_scheduled": with_toi_scheduled,
                "with_toi_completed": with_toi_completed,
                "with_draft": with_draft,
                "published": published,
            },
        }


_docs_update_service: Optional[DocsUpdateService] = None


def get_docs_update_service() -> DocsUpdateService:
    """Get singleton docs update service instance."""
    global _docs_update_service
    if _docs_update_service is None:
        _docs_update_service = DocsUpdateService()
    return _docs_update_service

"""
Escalation Analysis Service
============================
Orchestrates customer escalation ticket analysis:
- Fetches escalation tickets from Jira using configurable JQL
- Filters tickets by release (fixVersion matching)
- Extracts GitHub PR links from ticket descriptions and comments
- Coordinates AI-powered PR analysis for test impact assessment

Requires:
- Jira credentials (JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)
- GitHub token (GITHUB_TOKEN) for PR data fetching
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.jira_client import get_jira_client

logger = logging.getLogger(__name__)


# =============================================================================
# Default JQL for escalation tickets
# =============================================================================

# JQL for all escalation tickets - goes back to 2023 for historical/release-wise analysis
# Fetches both open and resolved escalations; service filters by status as needed
DEFAULT_ESCALATION_JQL = """
project in (ENG)
AND (labels = jira_escalated)
AND component in ("NS Client (NSC)")
AND issuetype in (Escalation)
AND "Type of Escalation[Dropdown]" in (Customer, Security)
AND created >= "2025/01/01"
AND status in (Resolved, Closed, Done)
AND assignee in (
    605823312f7d900070734a72, 5f4df57a3e9e2e004d6767a8,
    61f7988cc224b80069c426e7, 712020:00fed923-9c44-4a40-925d-9db970917aa1,
    61b65da12900b00071b4d398, 712020:fc25d5e5-3a8d-4842-8d10-2d454e0bf12d,
    605c232e557b950068845aa4, 712020:c32aa291-ba11-4d8f-9e16-88fceab5eea6,
    60a3ed5e2009f10068a146ea, 603cc9b1c668f4006aecfb66,
    631edc3a978dae24dc062969, 712020:6fa14e0d-475e-4c26-a264-2fd9c3e384fd,
    624aa1b4ad6b7e006aa756c3, 61a53a21744c4d0069002510,
    63bbce48157d36f444841d81, 61d6c9a049f195006952666b,
    712020:4b4b105b-d4fa-4366-862f-2b2a7ee48663,
    63cf9a96f6e1b5431616503b, 712020:1ed53b9f-b255-45b7-960f-415016b0e5df,
    712020:8d2f267e-3230-426e-bcd2-a76d643e8103,
    712020:5cf81a49-6d09-4288-966d-219082cb8e5b,
    712020:65116df0-b200-4da0-9961-b18135444da3,
    63ce43a6c565900ff404afce, 712020:ead66102-7be0-419c-864d-48df88dd29a2,
    601bbd103b1af00069e96f5a, 61e74cc285a2d600704cb799,
    712020:3bc32ac3-6625-47d4-8319-e9573add7d02,
    712020:eb45e9b5-c40c-46a8-911a-ec15b9bb20ca,
    611fe7aec2f3a500690f5c2d, 712020:19b1ae0f-e9e9-4d1c-9606-097497f5c65a,
    6078a2f4c9d3a200720144d9, 62022f14ed02400069a1cf5e,
    61564aa1d9820f0070743735, 617340f6bcb5740068414d70,
    617340f8580063006935edfa, 60f888e52b56cc00697d4a80,
    712020:6797fcd3-cb3b-4fb0-8a1b-6fd4aef8628f,
    712020:feb996e5-c57a-45e4-a441-0fef0cf2c17c,
    712020:7608be8a-bdce-4dd7-bbcf-cc1dfbb9e65c,
    712020:84144ca9-8a73-4ade-82c0-16fe8beab6b6,
    712020:9694d44c-ef63-4356-b883-c39ab6ef0f96,
    712020:c2e3c3ed-5092-4d3f-bd32-505ecc4964e7,
    712020:30685435-ec84-4317-a9b7-bbc9eefab9be,
    712020:32cf2715-b6ee-4f09-9bbf-34ff1d401d7d,
    712020:dd6ec85c-9770-4eda-8173-7006371d6644,
    712020:dbc9fbff-7e43-4594-9454-ba1c20f90c56,
    712020:fe35508d-eadb-4b1b-8e4e-b7033e154a8a,
    712020:3c85d3ad-a947-41c6-9996-1cdef2ad1710
)
ORDER BY assignee ASC
""".strip()


# Regex patterns for extracting GitHub PR URLs
GITHUB_PR_PATTERNS = [
    # Standard GitHub PR URL: https://github.com/owner/repo/pull/123
    re.compile(r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+)/pull/(\d+)"),
    # GitHub short PR reference: owner/repo#123
    re.compile(r"([\w\-\.]+)/([\w\-\.]+)#(\d+)"),
]


RESOLVED_STATUSES = {"resolved", "closed", "pending close", "done"}


class EscalationAnalysisService:
    """Orchestrates escalation ticket analysis for a given release."""

    CACHE_TTL = 120  # 2 minutes

    def __init__(self):
        self._jira = get_jira_client()
        self._escalations_cache: Optional[Tuple[float, List[Dict[str, Any]]]] = None
        self._dev_status_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def _get_cached_escalations(self) -> Optional[List[Dict[str, Any]]]:
        if self._escalations_cache:
            ts, data = self._escalations_cache
            if time.time() - ts < self.CACHE_TTL:
                return data
        return None

    def _set_cached_escalations(self, data: List[Dict[str, Any]]):
        self._escalations_cache = (time.time(), data)

    async def _get_issue_dev_status_cached(self, ticket_key: str) -> Dict[str, Any]:
        """Dev-status lookup with per-key TTL cache."""
        cached = self._dev_status_cache.get(ticket_key)
        if cached:
            ts, data = cached
            if time.time() - ts < self.CACHE_TTL:
                return data
        result = await self._jira.get_issue_dev_status(ticket_key)
        self._dev_status_cache[ticket_key] = (time.time(), result)
        return result

    @staticmethod
    def _is_resolved(ticket: Dict[str, Any]) -> bool:
        """Check if a ticket is resolved based on its status."""
        status = (ticket.get("status") or "").lower()
        return status in RESOLVED_STATUSES

    @staticmethod
    def _calculate_resolution_days(created: str, resolved: str) -> Optional[float]:
        """Calculate days between created and resolved dates."""
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            resolved_dt = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
            delta = resolved_dt - created_dt
            return delta.total_seconds() / 86400  # Convert to days
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calculate_mttr_stats(resolution_times: List[float]) -> Dict[str, Any]:
        """Calculate MTTR (Mean Time To Resolution) statistics."""
        if not resolution_times:
            return {
                "avg_days": None,
                "median_days": None,
                "min_days": None,
                "max_days": None,
                "sample_size": 0,
            }

        sorted_times = sorted(resolution_times)
        n = len(sorted_times)

        avg_days = sum(sorted_times) / n
        median_days = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
        min_days = sorted_times[0]
        max_days = sorted_times[-1]

        return {
            "avg_days": round(avg_days, 1),
            "median_days": round(median_days, 1),
            "min_days": round(min_days, 1),
            "max_days": round(max_days, 1),
            "sample_size": n,
        }

    async def get_all_escalations(
        self,
        jql: Optional[str] = None,
        max_results: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all escalation tickets from Jira.

        Uses a 2-minute TTL cache to avoid redundant Jira queries when
        multiple endpoints are called in quick succession (e.g. summary + tickets).

        Args:
            jql: Custom JQL override. Uses DEFAULT_ESCALATION_JQL if not provided.
                 Custom JQL bypasses the cache.
            max_results: Maximum tickets to fetch (paginated).

        Returns:
            List of parsed Jira issue dicts.
        """
        if not jql:
            cached = self._get_cached_escalations()
            if cached is not None:
                logger.info("Returning %d cached escalation tickets", len(cached))
                return cached

        query = jql or DEFAULT_ESCALATION_JQL

        logger.info("Fetching escalation tickets with JQL (max %d)...", max_results)

        fields = [
            "summary",
            "status",
            "priority",
            "assignee",
            "reporter",
            "labels",
            "fixVersions",
            "components",
            "issuetype",
            "resolution",
            "resolutiondate",
            "created",
            "updated",
            "description",
            "customfield_10200",  # QA field
            "customfield_26828",  # Salesforce Account Name (customer)
            "customfield_15000",  # Sub-Component (correct field ID)
            "customfield_14205",  # Release Note (Product Details) - for docs update tracking
        ]

        tickets = await self._jira.search_issues(
            jql=query,
            max_results=max_results,
            fetch_all=True,
            fields=fields,
        )

        logger.info("Fetched %d escalation tickets", len(tickets))

        if not jql:
            self._set_cached_escalations(tickets)

        return tickets

    def filter_by_release(
        self,
        tickets: List[Dict[str, Any]],
        release_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Filter tickets by fixVersion matching a release.

        For R135, matches fixVersions containing: 135.0.0, 135.1.0, 135.x.x, etc.

        Args:
            tickets: List of Jira issue dicts (must include fixVersions).
            release_id: Release identifier like "R135" or "135".

        Returns:
            Filtered list of tickets whose fixVersion matches the release.
        """
        # Extract numeric part: "R135" -> "135"
        match = re.search(r"(\d+)", release_id)
        if not match:
            logger.warning("Could not extract version number from release_id: %s", release_id)
            return []

        version_prefix = match.group(1)
        pattern = re.compile(rf"^{re.escape(version_prefix)}\.\d+")

        filtered = []
        for ticket in tickets:
            fix_versions = ticket.get("fixVersions", [])
            for fv in fix_versions:
                version_name = fv if isinstance(fv, str) else fv.get("name", "")
                if pattern.match(version_name):
                    filtered.append(ticket)
                    break

        logger.info(
            "Filtered %d -> %d tickets for release %s (prefix=%s)",
            len(tickets),
            len(filtered),
            release_id,
            version_prefix,
        )
        return filtered

    def extract_pr_links(self, ticket: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Extract GitHub PR URLs from a ticket's description.

        Looks for patterns like:
        - https://github.com/owner/repo/pull/123
        - owner/repo#123

        Args:
            ticket: Parsed Jira issue dict (must include 'description' in raw fields).

        Returns:
            List of dicts with owner, repo, pr_number, and url.
        """
        pr_links = []
        seen = set()

        # Get description text — may be raw string or Atlassian Document Format
        description = ticket.get("description", "") or ""
        if isinstance(description, dict):
            description = self._extract_text_from_adf(description)

        # Search for PR links
        for pattern in GITHUB_PR_PATTERNS:
            for match in pattern.finditer(description):
                owner, repo, pr_number = match.group(1), match.group(2), match.group(3)
                url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"

                if url not in seen:
                    seen.add(url)
                    pr_links.append(
                        {
                            "owner": owner,
                            "repo": repo,
                            "pr_number": int(pr_number),
                            "url": url,
                        }
                    )

        return pr_links

    def _extract_text_from_adf(self, adf: Dict) -> str:
        """
        Recursively extract plain text from Atlassian Document Format (ADF).

        Jira Cloud returns descriptions as ADF JSON. This flattens it to
        a searchable string so regex PR extraction works.
        """
        texts = []

        if isinstance(adf, dict):
            # Text nodes
            if adf.get("type") == "text":
                texts.append(adf.get("text", ""))

            # Inline card / link nodes (common for pasted URLs)
            if adf.get("type") == "inlineCard":
                attrs = adf.get("attrs", {})
                texts.append(attrs.get("url", ""))

            # Recurse into content array
            for child in adf.get("content", []):
                texts.append(self._extract_text_from_adf(child))

            # Check marks for links
            for mark in adf.get("marks", []):
                if mark.get("type") == "link":
                    texts.append(mark.get("attrs", {}).get("href", ""))

        elif isinstance(adf, list):
            for item in adf:
                texts.append(self._extract_text_from_adf(item))

        return " ".join(texts)

    def get_available_releases(
        self,
        tickets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract unique releases from escalation tickets based on fixVersions.

        Returns a list of releases sorted by version number (descending),
        with total, resolved, and open counts.
        """
        release_data: Dict[str, Dict[str, int]] = {}

        for ticket in tickets:
            is_resolved = self._is_resolved(ticket)
            fix_versions = ticket.get("fixVersions", [])
            for fv in fix_versions:
                version_name = fv if isinstance(fv, str) else fv.get("name", "")
                match = re.match(r"(\d+)\.\d+", version_name)
                if match:
                    release_id = f"R{match.group(1)}"
                    if release_id not in release_data:
                        release_data[release_id] = {"total": 0, "resolved": 0, "open": 0}
                    release_data[release_id]["total"] += 1
                    if is_resolved:
                        release_data[release_id]["resolved"] += 1
                    else:
                        release_data[release_id]["open"] += 1

        releases = [
            {
                "id": rid,
                "ticket_count": data["total"],
                "resolved_count": data["resolved"],
                "open_count": data["open"],
            }
            for rid, data in release_data.items()
        ]
        releases.sort(key=lambda r: int(r["id"].replace("R", "")), reverse=True)

        return releases

    async def _ticket_has_prs(self, ticket: Dict[str, Any]) -> bool:
        """Check if a ticket has any PRs (from description, Development panel, or linked issues)."""
        if self.extract_pr_links(ticket):
            return True

        ticket_key = ticket.get("key", "")

        try:
            dev_status = await self._get_issue_dev_status_cached(ticket_key)
            if dev_status.get("pull_requests"):
                return True
        except Exception:
            pass

        try:
            issue = await self._jira.get_issue(ticket_key, include_links=True)
            if issue:
                for linked in issue.get("linked_issues", []):
                    linked_key = linked.get("key", "")
                    if linked_key:
                        try:
                            linked_dev = await self._get_issue_dev_status_cached(linked_key)
                            if linked_dev.get("pull_requests"):
                                return True
                        except Exception:
                            pass
        except Exception:
            pass

        return False

    async def get_release_summary(
        self,
        release_id: str,
        jql: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Quick summary for a release without full PR analysis.

        Returns ticket count, assignee breakdown, priority breakdown,
        component breakdown, customer breakdown, and MTTR stats.
        Uses fast description-only PR counting to avoid expensive
        Jira dev-status API calls per ticket.
        """
        tickets = await self.get_all_escalations(jql=jql)
        filtered = self.filter_by_release(tickets, release_id)

        assignee_counts: Dict[str, int] = {}
        priority_counts: Dict[str, int] = {}
        component_counts: Dict[str, int] = {}
        customer_counts: Dict[str, int] = {}
        resolved_count = 0
        open_count = 0
        tickets_with_prs = 0
        resolution_times: List[float] = []

        for ticket in filtered:
            assignee = ticket.get("assignee", "Unassigned")
            priority = ticket.get("priority", "Unknown")
            component = ticket.get("sub_component") or "Unknown"
            customer = ticket.get("salesforce_account") or "Unknown"

            assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            component_counts[component] = component_counts.get(component, 0) + 1
            customer_counts[customer] = customer_counts.get(customer, 0) + 1

            if self._is_resolved(ticket):
                resolved_count += 1
                created = ticket.get("created")
                resolved = ticket.get("resolutiondate")
                if created and resolved:
                    resolution_days = self._calculate_resolution_days(created, resolved)
                    if resolution_days is not None:
                        resolution_times.append(resolution_days)
            else:
                open_count += 1

            if self.extract_pr_links(ticket):
                tickets_with_prs += 1

        mttr_stats = self._calculate_mttr_stats(resolution_times)

        return {
            "release_id": release_id,
            "total_tickets": len(filtered),
            "resolved_count": resolved_count,
            "open_count": open_count,
            "tickets_with_prs": tickets_with_prs,
            "by_assignee": [
                {"assignee": name, "count": count}
                for name, count in sorted(assignee_counts.items(), key=lambda x: -x[1])
            ],
            "by_priority": priority_counts,
            "by_component": [
                {"component": name, "count": count}
                for name, count in sorted(component_counts.items(), key=lambda x: -x[1])
            ],
            "by_customer": [
                {"customer": name, "count": count}
                for name, count in sorted(customer_counts.items(), key=lambda x: -x[1])
            ],
            "mttr": mttr_stats,
        }

    def _load_impacted_features_by_customer(self) -> Dict[str, Dict[str, int]]:
        """
        Load impacted features aggregated by customer from the analysis cache.

        Returns a dict mapping customer -> {feature_name: count}
        """
        import json
        import os

        cache_file = os.path.join(os.environ.get("DATA_DIR", "/app/data"), "ticket_analysis_cache.json")

        customer_features: Dict[str, Dict[str, int]] = {}

        try:
            if os.path.exists(cache_file):
                with open(cache_file, "r") as f:
                    cache = json.load(f)

                for ticket_key, ticket_data in cache.get("tickets", {}).items():
                    customer = ticket_data.get("customer") or "Unknown"
                    features = ticket_data.get("impacted_features", [])

                    if customer not in customer_features:
                        customer_features[customer] = {}

                    for feature in features:
                        customer_features[customer][feature] = customer_features[customer].get(feature, 0) + 1
        except Exception as e:
            logger.warning("Could not load impacted features cache: %s", e)

        return customer_features

    async def get_all_summary(
        self,
        jql: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Summary for ALL escalations across all releases (no filtering).

        Returns ticket count, assignee breakdown, priority breakdown,
        component breakdown, customer breakdown, and MTTR stats.
        """
        tickets = await self.get_all_escalations(jql=jql)

        assignee_counts: Dict[str, int] = {}
        priority_counts: Dict[str, int] = {}
        component_counts: Dict[str, int] = {}
        customer_counts: Dict[str, int] = {}
        resolved_count = 0
        open_count = 0
        tickets_with_prs = 0
        resolution_times: List[float] = []

        for ticket in tickets:
            assignee = ticket.get("assignee", "Unassigned")
            priority = ticket.get("priority", "Unknown")
            component = ticket.get("sub_component") or "Unknown"
            customer = ticket.get("salesforce_account") or "Unknown"

            assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            component_counts[component] = component_counts.get(component, 0) + 1
            customer_counts[customer] = customer_counts.get(customer, 0) + 1

            if self._is_resolved(ticket):
                resolved_count += 1
                created = ticket.get("created")
                resolved = ticket.get("resolutiondate")
                if created and resolved:
                    resolution_days = self._calculate_resolution_days(created, resolved)
                    if resolution_days is not None:
                        resolution_times.append(resolution_days)
            else:
                open_count += 1

            if self.extract_pr_links(ticket):
                tickets_with_prs += 1

        mttr_stats = self._calculate_mttr_stats(resolution_times)

        # Load impacted features from AI analysis cache
        customer_features = self._load_impacted_features_by_customer()

        # Build by_customer list with impacted_features count
        by_customer = []
        for name, count in sorted(customer_counts.items(), key=lambda x: -x[1]):
            features = customer_features.get(name, {})
            total_features = sum(features.values())
            by_customer.append(
                {
                    "customer": name,
                    "count": count,
                    "impacted_features_count": total_features,
                    "impacted_features": sorted(
                        [{"name": k, "count": v} for k, v in features.items()], key=lambda x: -x["count"]
                    )[
                        :5
                    ],  # Top 5 features
                }
            )

        return {
            "release_id": "all",
            "total_tickets": len(tickets),
            "resolved_count": resolved_count,
            "open_count": open_count,
            "tickets_with_prs": tickets_with_prs,
            "by_assignee": [
                {"assignee": name, "count": count}
                for name, count in sorted(assignee_counts.items(), key=lambda x: -x[1])
            ],
            "by_priority": priority_counts,
            "by_component": [
                {"component": name, "count": count}
                for name, count in sorted(component_counts.items(), key=lambda x: -x[1])
            ],
            "by_customer": by_customer,
            "mttr": mttr_stats,
        }

    async def analyze_escalations_for_release(
        self,
        release_id: str,
        jql: Optional[str] = None,
        include_ai_analysis: bool = True,
    ) -> Dict[str, Any]:
        """
        Full analysis pipeline for a release:
        1. Fetch all escalation tickets
        2. Filter by release
        3. Extract PR links from each ticket
        4. Fetch PR details from GitHub
        5. Run AI analysis on each PR
        6. Aggregate results (file hotspots, test recommendations, risk)

        Args:
            release_id: Target release (e.g., "R135").
            jql: Optional JQL override.
            include_ai_analysis: Whether to run LLM analysis on PRs.

        Returns:
            Aggregated analysis results.
        """
        from services.commit_analyzer import get_commit_analyzer
        from utilities.github import fetch_pr_details

        # Step 1 & 2: Fetch and filter tickets
        all_tickets = await self.get_all_escalations(jql=jql)
        tickets = self.filter_by_release(all_tickets, release_id)

        # Step 3: Extract PR links from each ticket
        ticket_results = []
        all_pr_links = []

        for ticket in tickets:
            pr_links = self.extract_pr_links(ticket)
            ticket_results.append(
                {
                    "key": ticket.get("key"),
                    "summary": ticket.get("summary"),
                    "assignee": ticket.get("assignee"),
                    "priority": ticket.get("priority"),
                    "status": ticket.get("status"),
                    "url": ticket.get("url"),
                    "pr_count": len(pr_links),
                    "pr_links": pr_links,
                    "analyzed": False,
                }
            )
            all_pr_links.extend({**pr, "ticket_key": ticket.get("key")} for pr in pr_links)

        # Step 4 & 5: Fetch PR data and analyze
        file_hotspot_counts: Dict[str, int] = {}
        all_test_recommendations = []
        risk_scores = []
        analyzed_prs = 0

        analyzer = get_commit_analyzer()

        for pr_info in all_pr_links:
            try:
                pr_data = await fetch_pr_details(
                    owner=pr_info["owner"],
                    repo=pr_info["repo"],
                    pr_number=pr_info["pr_number"],
                )

                if pr_data.get("status") != "success":
                    logger.warning(
                        "Failed to fetch PR %s: %s",
                        pr_info["url"],
                        pr_data.get("error"),
                    )
                    continue

                # Count file hotspots
                for f in pr_data.get("files", []):
                    filename = f.get("filename", "")
                    file_hotspot_counts[filename] = file_hotspot_counts.get(filename, 0) + 1

                # Run AI analysis if enabled
                if include_ai_analysis:
                    analysis = await analyzer.analyze_commit(
                        commit_data={
                            "files": pr_data.get("files", []),
                            "stats": pr_data.get("stats", {}),
                            "message": pr_data.get("title", ""),
                            "sha": f"PR#{pr_info['pr_number']}",
                        },
                        include_llm_analysis=True,
                    )

                    llm = analysis.get("llm_analysis") or {}
                    if llm.get("available"):
                        risk_level = llm.get("risk_level", "unknown")
                        risk_scores.append(risk_level)
                        for rec in llm.get("testing_recommendations", []):
                            all_test_recommendations.append(
                                {
                                    "area": rec,
                                    "source_pr": pr_info["url"],
                                    "ticket": pr_info.get("ticket_key"),
                                }
                            )

                    # Merge test impact areas from pattern-based analysis
                    test_impact = analysis.get("test_impact", {})
                    for area in test_impact.get("primary_areas", []):
                        all_test_recommendations.append(
                            {
                                "area": area,
                                "source_pr": pr_info["url"],
                                "ticket": pr_info.get("ticket_key"),
                                "source": "pattern",
                            }
                        )

                analyzed_prs += 1

            except Exception as e:
                logger.error("Error analyzing PR %s: %s", pr_info["url"], e)
                continue

        # Step 6: Aggregate results
        file_hotspots = sorted(
            [{"file": f, "changes": c} for f, c in file_hotspot_counts.items()],
            key=lambda x: -x["changes"],
        )[:20]

        # Deduplicate and count test recommendations
        rec_counts: Dict[str, int] = {}
        for rec in all_test_recommendations:
            area = rec["area"]
            rec_counts[area] = rec_counts.get(area, 0) + 1

        test_recommendations = sorted(
            [{"area": a, "mentions": c, "priority": _priority_from_count(c)} for a, c in rec_counts.items()],
            key=lambda x: -x["mentions"],
        )

        # Determine overall risk
        overall_risk = _aggregate_risk(risk_scores)

        return {
            "release_id": release_id,
            "total_escalations": len(all_tickets),
            "total_tickets": len(tickets),
            "tickets_with_prs": sum(1 for t in ticket_results if t["pr_count"] > 0),
            "total_prs": len(all_pr_links),
            "analyzed_prs": analyzed_prs,
            "file_hotspots": file_hotspots,
            "test_recommendations": test_recommendations,
            "risk_summary": {
                "level": overall_risk,
                "risk_distribution": {
                    "high": risk_scores.count("high"),
                    "medium": risk_scores.count("medium"),
                    "low": risk_scores.count("low"),
                },
            },
            "tickets": ticket_results,
        }

    async def get_ticket_details(self, ticket_key: str) -> Dict[str, Any]:
        """
        Get full details for a single escalation ticket:
        - Issue fields (summary, description, status, priority, etc.)
        - Linked issues (from issuelinks field)
        - PR links from the Development panel of linked workitems
        - PR links extracted from description text

        The flow for PR discovery:
        1. Fetch the escalation ticket with issuelinks
        2. For each linked issue, fetch its Development panel (dev-status API)
        3. Also extract PR URLs from the ticket description as fallback

        Args:
            ticket_key: Jira issue key (e.g., "ENG-12345")

        Returns:
            Dict with ticket details, linked issues, and all discovered PR links.
        """
        issue = await self._jira.get_issue(ticket_key, include_links=True)
        if not issue:
            return {"error": f"Ticket {ticket_key} not found"}

        # Extract description text for display
        description_text = ""
        raw_desc = issue.get("description_raw")
        if raw_desc:
            if isinstance(raw_desc, dict):
                description_text = self._extract_text_from_adf(raw_desc)
            else:
                description_text = str(raw_desc)

        # Get linked issues
        linked_issues = issue.get("linked_issues", [])

        dev_pull_requests = []

        ticket_dev = await self._get_issue_dev_status_cached(ticket_key)
        for pr in ticket_dev.get("pull_requests", []):
            pr["source_ticket"] = ticket_key
            dev_pull_requests.append(pr)

        async def _fetch_linked_dev(linked_key: str):
            try:
                linked_dev = await self._get_issue_dev_status_cached(linked_key)
                return [(linked_key, pr) for pr in linked_dev.get("pull_requests", [])]
            except Exception as e:
                logger.warning("Error fetching dev-status for linked issue %s: %s", linked_key, e)
                return []

        linked_keys = [li.get("key", "") for li in linked_issues if li.get("key")]
        linked_results = await asyncio.gather(*[_fetch_linked_dev(k) for k in linked_keys])
        for pairs in linked_results:
            for lk, pr in pairs:
                pr["source_ticket"] = lk
                dev_pull_requests.append(pr)

        # Also extract PR links from description text
        description_prs = self.extract_pr_links({"description": description_text})

        # Deduplicate PRs by URL
        seen_urls = set()
        all_prs = []
        for pr in dev_pull_requests:
            url = pr.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_prs.append({**pr, "source": "development_panel"})
        for pr in description_prs:
            url = pr.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_prs.append({**pr, "source": "description"})

        # Fetch full details for each linked child to derive
        # fixVersion, assignee, QA, sub-component from children
        linked_full_details = []
        if linked_keys:

            async def _fetch_linked_full(key):
                try:
                    return await self._jira.get_issue(key)
                except Exception:
                    return None

            details_results = await asyncio.gather(*[_fetch_linked_full(k) for k in linked_keys])
            linked_full_details = [d for d in details_results if d]

        # Prefer linked child data, fall back to parent escalation ticket
        if linked_full_details:
            child_fix_versions = list(dict.fromkeys(fv for d in linked_full_details for fv in d.get("fixVersions", [])))
            child_assignees = list(dict.fromkeys(d.get("assignee") for d in linked_full_details if d.get("assignee")))
            child_qas = list(dict.fromkeys(d.get("qa") for d in linked_full_details if d.get("qa")))
            child_sub = next(
                (d.get("sub_component") for d in linked_full_details if d.get("sub_component")),
                None,
            )

            fix_versions = child_fix_versions or issue.get("fixVersions", [])
            assignee = child_assignees[0] if child_assignees else issue.get("assignee")
            linked_assignee_names = child_assignees[1:] if len(child_assignees) > 1 else []
            qa = child_qas[0] if child_qas else issue.get("qa")
            all_qas = child_qas
            # Sub-component: prefer parent escalation ticket, fall back to linked child
            sub_component = issue.get("sub_component") or child_sub
        else:
            fix_versions = issue.get("fixVersions", [])
            assignee = issue.get("assignee")
            linked_assignee_names = []
            qa = issue.get("qa")
            all_qas = [qa] if qa else []
            sub_component = issue.get("sub_component")

        return {
            "key": issue.get("key"),
            "summary": issue.get("summary"),
            "status": issue.get("status"),
            "priority": issue.get("priority"),
            "assignee": assignee,
            "reporter": issue.get("reporter"),
            "qa": qa,
            "all_qas": all_qas,
            "issuetype": issue.get("issuetype"),
            "components": issue.get("components", []),
            "sub_component": sub_component,
            "customer": issue.get("salesforce_account"),
            "labels": issue.get("labels", []),
            "created": issue.get("created"),
            "resolution_date": issue.get("resolutiondate"),
            "fix_version_str": ", ".join(fix_versions) or None,
            "linked_assignees": linked_assignee_names,
            "url": issue.get("url"),
            "description": description_text[:2000],
            "linked_issues": linked_issues,
            "pull_requests": all_prs,
            "total_prs": len(all_prs),
        }

    async def analyze_single_ticket_impact(self, ticket_key: str) -> Dict[str, Any]:
        """
        Analyze impacted areas for a single escalation ticket.

        Uses the existing CommitAnalyzer to analyze each linked PR and aggregates:
        - Impacted features/components (from LLM + sub-component)
        - Recommended test areas (from pattern-based mapping + LLM)

        Args:
            ticket_key: Jira issue key (e.g., "ENG-12345")

        Returns:
            Dict with impacted_features, test_areas, and analysis metadata.
        """
        import re

        from services.commit_analyzer import get_commit_analyzer
        from utilities.github import fetch_pr_details

        details = await self.get_ticket_details(ticket_key)

        if details.get("error"):
            return {"error": details["error"], "ticket_key": ticket_key}

        all_components: set = set()
        all_test_areas: set = set()
        analyzed_prs = []
        errors = []

        analyzer = get_commit_analyzer()
        pull_requests = details.get("pull_requests", [])

        for pr in pull_requests:
            pr_url = pr.get("url", "")
            match = re.match(
                r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+)/pull/(\d+)",
                pr_url,
            )
            if not match:
                continue

            owner, repo, pr_number = match.group(1), match.group(2), int(match.group(3))

            try:
                pr_data = await fetch_pr_details(owner, repo, pr_number)

                if pr_data.get("status") != "success":
                    errors.append(f"Failed to fetch PR {pr_url}: {pr_data.get('error')}")
                    continue

                analysis = await analyzer.analyze_commit(
                    commit_data={
                        "files": pr_data.get("files", []),
                        "stats": pr_data.get("stats", {}),
                        "message": pr_data.get("title", ""),
                        "sha": f"PR#{pr_number}",
                    },
                    include_llm_analysis=True,
                )

                test_impact = analysis.get("test_impact", {})
                for area in test_impact.get("primary_areas", []):
                    all_test_areas.add(area)

                for component in analysis.get("files_by_component", {}).keys():
                    if component and component != "other":
                        all_components.add(component.replace("_", " ").title())

                llm = analysis.get("llm_analysis") or {}
                if llm.get("available"):
                    for comp in llm.get("components", []):
                        all_components.add(comp)
                    for rec in llm.get("testing_recommendations", []):
                        all_test_areas.add(rec)

                analyzed_prs.append(
                    {
                        "url": pr_url,
                        "files_changed": len(pr_data.get("files", [])),
                        "risk_level": llm.get("risk_level", "unknown") if llm.get("available") else "unknown",
                    }
                )

            except Exception as e:
                logger.error("Error analyzing PR %s: %s", pr_url, e)
                errors.append(f"Error analyzing {pr_url}: {str(e)}")

        if details.get("sub_component") and details["sub_component"] != "Unknown":
            all_components.add(details["sub_component"])

        return {
            "ticket_key": ticket_key,
            "summary": details.get("summary"),
            "impacted_features": sorted(all_components),
            "test_areas": sorted(all_test_areas),
            "pr_count": len(pull_requests),
            "analyzed_prs": analyzed_prs,
            "errors": errors if errors else None,
        }

    async def get_escalation_trends(
        self,
        jql: Optional[str] = None,
        months: int = 12,
    ) -> Dict[str, Any]:
        """
        Get escalation trends over time, grouped by month and sub-component.

        Returns data suitable for a stacked area chart showing:
        - Monthly escalation counts
        - Breakdown by sub-component (top N + "Other")

        Args:
            jql: Optional JQL override
            months: Number of months to include (default: 12)

        Returns:
            Dict with:
                - months: List of month labels (e.g., ["Jan 2025", "Feb 2025", ...])
                - components: List of component names
                - series: Dict[component_name] -> List[counts per month]
                - totals: List of total counts per month
        """
        from collections import defaultdict
        from datetime import datetime

        from dateutil.relativedelta import relativedelta

        tickets = await self.get_all_escalations(jql=jql)

        # Calculate date range
        now = datetime.now()
        start_date = now - relativedelta(months=months - 1)
        start_date = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Initialize month buckets
        month_labels = []
        month_keys = []
        current = start_date
        while current <= now:
            month_key = current.strftime("%Y-%m")
            month_label = current.strftime("%b %Y")
            month_keys.append(month_key)
            month_labels.append(month_label)
            current += relativedelta(months=1)

        # Count escalations by month and component
        # Structure: {month_key: {component: count}}
        monthly_data: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        component_totals: Dict[str, int] = defaultdict(int)

        for ticket in tickets:
            # Parse created date
            created_str = ticket.get("created")
            if not created_str:
                continue

            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                month_key = created_dt.strftime("%Y-%m")
            except (ValueError, TypeError):
                continue

            # Only include if within our date range
            if month_key not in month_keys:
                continue

            # Get component (sub_component or "Unknown")
            component = ticket.get("sub_component") or "Unknown"
            if component == "Unknown":
                component = "Other"

            monthly_data[month_key][component] += 1
            component_totals[component] += 1

        # Get top N components (by total count), rest goes to "Other"
        TOP_N = 8
        sorted_components = sorted(component_totals.items(), key=lambda x: -x[1])
        top_components = [c for c, _ in sorted_components[:TOP_N] if c != "Other"]

        # If "Other" already exists, keep it; otherwise add if there are more components
        has_other = any(c not in top_components for c, _ in sorted_components)

        # Build series data
        series: Dict[str, List[int]] = {}
        totals: List[int] = []

        for component in top_components:
            series[component] = []

        if has_other:
            series["Other"] = []

        for month_key in month_keys:
            month_counts = monthly_data.get(month_key, {})
            month_total = 0

            for component in top_components:
                count = month_counts.get(component, 0)
                series[component].append(count)
                month_total += count

            # Sum up "Other" category
            if has_other:
                other_count = sum(count for comp, count in month_counts.items() if comp not in top_components)
                series["Other"].append(other_count)
                month_total += other_count

            totals.append(month_total)

        # Order components by total (descending) for chart legend
        component_order = top_components.copy()
        if has_other and "Other" in series:
            component_order.append("Other")

        return {
            "months": month_labels,
            "month_keys": month_keys,
            "components": component_order,
            "series": series,
            "totals": totals,
            "total_escalations": len(tickets),
            "date_range": {
                "start": start_date.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
            },
        }


# =============================================================================
# Helpers
# =============================================================================


def _priority_from_count(count: int) -> str:
    """Map recommendation mention count to priority level."""
    if count >= 5:
        return "critical"
    elif count >= 3:
        return "high"
    elif count >= 2:
        return "medium"
    return "low"


def _aggregate_risk(risk_scores: List[str]) -> str:
    """Determine overall risk from individual PR risk assessments."""
    if not risk_scores:
        return "unknown"

    high = risk_scores.count("high")
    medium = risk_scores.count("medium")

    if high >= 3 or (high >= 1 and medium >= 3):
        return "high"
    elif high >= 1 or medium >= 2:
        return "medium"
    return "low"


# =============================================================================
# Singleton
# =============================================================================

_escalation_service: Optional[EscalationAnalysisService] = None


def get_escalation_service() -> EscalationAnalysisService:
    """Get singleton escalation service instance."""
    global _escalation_service
    if _escalation_service is None:
        _escalation_service = EscalationAnalysisService()
    return _escalation_service

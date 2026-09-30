"""
Core Utilities
==============

Query extraction and response formatting utilities.

Usage:
    from core.utils import QueryExtractor, ResponseFormatter, get_utils

    utils = get_utils()

    # Extract from query
    release = utils.extract("What's R134 status?", "release")  # → "R134"

    # Format response
    header = utils.build_header("🐛", "Bugs", release="R134", count=5)
"""

import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

# Get default release from environment (single source of truth - REQUIRED)
DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
if not DEFAULT_RELEASE:
    raise EnvironmentError(
        "CURRENT_RELEASE environment variable is required! " "Set it in your .env file or docker-compose.yml"
    )

logger = logging.getLogger(__name__)


class CoreUtils:
    """
    Combined query extraction and response formatting utilities.

    Query Extraction:
    - extract(): Unified extraction (release, component, assignee, qualifier, etc.)
    - match_item(): Match query against available items
    - is_greeting(): Check if message is a greeting

    Response Formatting:
    - build_header(): Build markdown headers
    - format_jira_item(): Format JIRA issues
    - format_items_list(): Format lists with truncation
    - filter_by_component(): Filter items by component
    - get_status_emoji(): Get status indicator
    """

    # =========================================================================
    # Constants
    # =========================================================================

    STOP_WORDS = frozenset(
        {
            "are",
            "there",
            "any",
            "code",
            "commits",
            "before",
            "after",
            "branch",
            "cut",
            "for",
            "the",
            "a",
            "an",
            "in",
            "on",
            "to",
            "what",
            "which",
            "how",
            "many",
            "show",
            "me",
            "get",
            "list",
            "of",
            "from",
            "with",
            "is",
            "was",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "can",
            "could",
            "should",
            "may",
            "might",
            "must",
            "repo",
            "repository",
            "repositories",
            "commit",
            "flagged",
            "please",
            "status",
            "whats",
            "what's",
            "tell",
            "give",
            "each",
            "all",
            "component",
            "components",
            "bugs",
            "bug",
            "issues",
            "issue",
            "stories",
            "story",
            "items",
            "item",
            "release",
            "readiness",
            "score",
            "irr",
            "final",
            "build",
            "critical",
            "blocker",
            "regression",
            "moreinfo",
            "action",
            "assignee",
            "owner",
        }
    )

    PATTERNS = {
        "release": r"r?(\d{3})",
        "qualifier_most": r"\b(most|highest|maximum|max|biggest|largest)\b",
        "qualifier_least": r"\b(least|lowest|minimum|min|smallest|fewest)\b",
        "qualifier_top": r"\btop\s+(\d+)\b",
        "qualifier_bottom": r"\bbottom\s+(\d+)\b",
        "component_explicit": r"\b(?:in|for|of)\s+(\w+)\s+(?:component|module|area|team)\b",
        "assignee_to": r"\bassigned\s+to\s+(\w+)",
        "assignee_have": r"\bdoes\s+(\w+)\s+have\b",
        "assignee_for": r"\bfor\s+(\w+)\b(?:\s+in|\s+on|\s*$)",
        "assignee_possessive": r"\b(\w+)\'s\s+(?:bugs?|items?|tasks?|stories?)",
        "breakdown": r"\b(each component|by component|per component|each repo|by repo|per repo|breakdown|break down|all components|for each|separately|individual)\b",
        "greeting": r"^(hi|hello|hey|greetings|good morning|good afternoon|good evening|howdy|yo|sup|what\'s up|whats up|hiya)(?:\s|!|$)",
    }

    # =========================================================================
    # Query Extraction
    # =========================================================================

    def extract(self, query: str, extract_type: str, available_items: List[str] = None, fallback: Any = None) -> Any:
        """
        Extract entities from query.

        Args:
            query: User query string
            extract_type: Type of extraction:
                - "keywords": Filter keywords (list)
                - "release": Release ID (str like "R134")
                - "qualifier": Most/least/top/bottom (dict)
                - "component": Component name (str)
                - "assignee": Assignee name (str)
                - "breakdown": Wants breakdown (bool)
                - "greeting": Is greeting (bool)
                - "match": Generic match (str)
            available_items: Items to match against
            fallback: Default value if extraction fails

        Returns:
            Extracted value or fallback
        """
        query_lower = query.lower().strip()

        if extract_type == "keywords":
            words = re.findall(r"\b[a-zA-Z][\w-]*\b", query_lower)
            return [w for w in words if w not in self.STOP_WORDS and len(w) > 1]

        elif extract_type == "release":
            match = re.search(self.PATTERNS["release"], query_lower)
            return f"R{match.group(1)}" if match else fallback

        elif extract_type == "qualifier":
            if re.search(self.PATTERNS["qualifier_most"], query_lower):
                return {"sort": "desc", "limit": 1, "qualifier": "most"}
            if re.search(self.PATTERNS["qualifier_least"], query_lower):
                return {"sort": "asc", "limit": 1, "qualifier": "least"}
            match = re.search(self.PATTERNS["qualifier_top"], query_lower)
            if match:
                return {"sort": "desc", "limit": int(match.group(1)), "qualifier": "top"}
            match = re.search(self.PATTERNS["qualifier_bottom"], query_lower)
            if match:
                return {"sort": "asc", "limit": int(match.group(1)), "qualifier": "bottom"}
            return fallback or {}

        elif extract_type == "component":
            match = re.search(self.PATTERNS["component_explicit"], query, re.IGNORECASE)
            if match:
                comp = match.group(1).upper()
                if available_items and comp in [str(i).upper() for i in available_items]:
                    return comp
            return self.match_item(query, available_items) if available_items else fallback

        elif extract_type == "assignee":
            for pattern_key in ["assignee_to", "assignee_have", "assignee_for", "assignee_possessive"]:
                match = re.search(self.PATTERNS[pattern_key], query, re.IGNORECASE)
                if match:
                    name = match.group(1)
                    if name.lower() not in ["the", "this", "that", "what", "which", "how", "who", "all"]:
                        if available_items:
                            for item in available_items:
                                if name.lower() in str(item).lower():
                                    return item
                        return name
            return self.match_item(query, available_items) if available_items else fallback

        elif extract_type == "breakdown":
            return bool(re.search(self.PATTERNS["breakdown"], query_lower))

        elif extract_type == "greeting":
            clean = query_lower.rstrip("!?.,'")
            return bool(re.search(self.PATTERNS["greeting"], clean))

        elif extract_type == "match":
            return self.match_item(query, available_items) if available_items else fallback

        return fallback

    def match_item(self, query: str, items: List[str]) -> Optional[str]:
        """Match query against items using multiple strategies."""
        if not items:
            return None

        query_lower = query.lower()
        keywords = self.extract(query, "keywords")

        # Strategy 1: Direct match
        for item in items:
            if str(item).lower() in query_lower:
                return item

        # Strategy 2: Keyword match
        for keyword in keywords:
            for item in items:
                item_lower = str(item).lower()
                if keyword == item_lower or keyword in item_lower or item_lower in keyword:
                    return item

        # Strategy 3: Partial word match
        for word in query_lower.split():
            if len(word) >= 3:
                for item in items:
                    if word in str(item).lower():
                        return item

        return None

    def is_greeting(self, message: str) -> bool:
        """Check if message is a greeting."""
        return self.extract(message, "greeting", fallback=False)

    # =========================================================================
    # Data Extraction from API Responses
    # =========================================================================

    def extract_from_data(
        self, data: Dict[str, Any], keys: List[str] = None, extract_type: str = "components"
    ) -> List[str]:
        """Extract items from API response data."""
        items = set()

        if extract_type == "components":
            keys = keys or ["componentsData", "components", "byComponent"]
            for key in keys:
                if key in data:
                    val = data[key]
                    if isinstance(val, dict):
                        items.update(val.keys())
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                comp = item.get("component") or item.get("components") or ""
                                if comp:
                                    items.add(str(comp).upper())

        elif extract_type == "assignees":
            keys = keys or ["bugs", "items", "stories"]
            for key in keys:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        if isinstance(item, dict):
                            assignee = item.get("assignee")
                            if assignee and assignee != "Unassigned":
                                items.add(assignee)

        return list(items)

    def get_filters(
        self,
        data: Dict[str, Any],
        params: Dict[str, Any],
        component_keys: List[str] = None,
        items_for_assignee: List[Dict] = None,
    ) -> Dict[str, Any]:
        """Extract filters from params and user query."""
        user_query = params.get("_user_query", "")

        available_components = self.extract_from_data(data, component_keys, "components")

        component = self.extract(user_query, "component", available_components)
        if not component:
            component = params.get("component")

        assignee = None
        if items_for_assignee:
            available_assignees = list(
                {
                    item.get("assignee")
                    for item in items_for_assignee
                    if item.get("assignee") and item.get("assignee") != "Unassigned"
                }
            )
            assignee = self.extract(user_query, "assignee", available_assignees)
        if not assignee:
            assignee = params.get("assignee")

        return {
            "component": component,
            "assignee": assignee,
            "wants_breakdown": self.extract(user_query, "breakdown", fallback=False),
            "qualifier": self.extract(user_query, "qualifier", fallback={}),
            "user_query": user_query,
        }

    # =========================================================================
    # Response Formatting
    # =========================================================================

    def build_header(
        self, emoji: str, title: str, release: str = None, filter_val: str = None, count: int = None, suffix: str = None
    ) -> str:
        """Build consistent markdown header."""
        header = f"## {emoji} {title}"
        if release:
            header += f": {release}"
        if filter_val:
            header += f" ({filter_val.upper()})"
        if count is not None:
            header += f" - {count} total"
        if suffix:
            header += f" {suffix}"
        return header

    def filter_by_component(self, items: List[Dict], component: str, field: str = "component") -> List[Dict]:
        """Filter items by component."""
        if not component:
            return items
        comp_upper = component.upper()
        return [
            item
            for item in items
            if comp_upper in str(item.get(field, "")).upper()
            or comp_upper in str(item.get("components", "")).upper()
            or comp_upper in str(item.get("key", "")).upper()
        ]

    def format_items_list(
        self, items: List[Any], format_fn: Callable, limit: int = 10, empty_msg: str = None, filter_name: str = None
    ) -> List[str]:
        """Format list with consistent truncation."""
        if not items:
            if filter_name:
                return [f"✅ **No items found for {filter_name}!**"]
            return [empty_msg or "✅ **No items found!**"]

        lines = []
        for item in items[:limit]:
            result = format_fn(item)
            if isinstance(result, list):
                lines.extend(result)
            else:
                lines.append(result)

        if len(items) > limit:
            lines.append(f"\n*...and {len(items) - limit} more*")

        return lines

    def format_jira_item(self, item: Dict[str, Any], style: str = "compact", fields: List[str] = None) -> str:
        """Format a JIRA item."""
        key = item.get("key", "N/A")
        summary = (item.get("summary") or "No summary")[:50]
        priority = item.get("priority", "Unknown")
        assignee = item.get("assignee", "Unassigned")
        status = item.get("status", "")

        priority_emoji = "🔴" if priority in ["Blocker", "Critical"] else "🟠" if priority == "Major" else "🟡"

        if style == "compact":
            return f"- **{key}**: {summary} | {priority} | {assignee}"
        elif style == "detailed":
            lines = [
                f"### {priority_emoji} [{key}]",
                f"- **Summary:** {summary}",
                f"- **Priority:** {priority}",
                f"- **Assignee:** {assignee}",
            ]
            if status:
                lines.append(f"- **Status:** {status}")
            lines.append("")
            return "\n".join(lines)
        else:  # minimal
            return f"- **{key}**: {summary}"

    def get_status_emoji(self, score: float, thresholds: tuple = (80, 50)) -> tuple:
        """Get status emoji and text based on score."""
        good, warning = thresholds
        if score >= good:
            return ("✅", "On Track")
        elif score >= warning:
            return ("⚠️", "At Risk")
        else:
            return ("🔴", "Critical")

    # =========================================================================
    # Data Formatters (for API responses)
    # =========================================================================

    def format_release_readiness(self, data: Dict[str, Any], component: str = None) -> str:
        """Format release readiness score response - filtered by component."""
        release = data.get("release", DEFAULT_RELEASE)
        release_summary = data.get("releaseSummary", {})
        components_data = data.get("componentsData", {})

        # Default to YOUR_PRODUCT for dashboard focus
        target_component = component.upper() if component else "YOUR_PRODUCT"

        # Calculate score for the target component only
        if target_component and target_component in components_data:
            comp_data = components_data[target_component]
            comp_summary = comp_data.get("summary", {})
            open_stories = comp_summary.get("bc_stories", 0)
            open_bugs = comp_summary.get("bc_bugs", 0)
            total_open = open_stories + open_bugs
        else:
            # Fallback to total if component not found
            total_open = release_summary.get("totalOpen", 0)
            open_stories = release_summary.get("openStories", 0)
            open_bugs = release_summary.get("openBugs", 0)

        # Calculate RRS: 100 - (open_items × 3%)
        score = max(0, min(100, 100 - (total_open * 3)))

        # Determine status
        if score >= 80:
            emoji = "🟢"
            status_text = "GREEN - Ready"
        elif score >= 70:
            emoji = "🟡"
            status_text = "YELLOW - Attention Needed"
        else:
            emoji = "🔴"
            status_text = "RED - Not Ready"

        # Get phase info
        phase_name = release_summary.get("phaseName", release_summary.get("phase", "Unknown"))
        days_remaining = release_summary.get("daysRemaining", 0)

        lines = [
            f"## {emoji} Release {release} Status ({target_component}): **{status_text}** ({score}%)",
            "",
            f"**Phase:** {phase_name} | **Days Remaining:** {days_remaining}",
            "",
            f"### {target_component} Open Items",
            "",
            "| Category | Count |",
            "|----------|-------|",
            f"| 🐛 Open Bugs | {open_bugs} |",
            f"| 📋 Open Stories | {open_stories} |",
            f"| **Total Open** | **{total_open}** |",
            "",
        ]

        # Add top assignees from the component
        if target_component in components_data:
            comp_issues = components_data[target_component].get("issues", [])
            if comp_issues:
                assignee_counts = {}
                for issue in comp_issues:
                    assignee = issue.get("assignee") or "Unassigned"
                    assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
                top_assignees = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)[:5]

                if top_assignees:
                    lines.append("### Top Assignees (Open Items)")
                    lines.append("")
                    for assignee, count in top_assignees:
                        lines.append(f"- **{assignee}**: {count} items")
                    lines.append("")

        # Add recommendation
        items_to_green = max(0, total_open - 6) if score < 80 else 0
        if items_to_green > 0:
            lines.append("### ⚠️ Action Required")
            lines.append(f"Close **{items_to_green}** more items to reach 🟢 GREEN status.")
        else:
            lines.append("### ✅ Release Ready!")
            lines.append("All criteria met for release.")

        return "\n".join(lines)

    def format_milestone_status(self, data: Dict[str, Any], milestone_name: str, component: str = None) -> str:
        """Format milestone status (IRR, Branch Cut, Final Build)."""
        release = data.get("release", DEFAULT_RELEASE)
        milestone_date = data.get("milestoneDate", "")

        title = f"{milestone_name} Status: {release}"
        if component:
            title += f" ({component.upper()})"

        components_data = data.get("components", {})

        # Filter by component
        if component:
            filtered = {k: v for k, v in components_data.items() if component.upper() in k.upper()}
            if filtered:
                components_data = filtered

        # Calculate totals
        total_on_time, total_late, total_open = 0, 0, 0
        all_open_items = []

        for name, comp_data in components_data.items():
            if isinstance(comp_data, dict):
                total_on_time += comp_data.get("resolvedOnTime", 0)
                late = comp_data.get("resolvedAfterDeadline", [])
                total_late += len(late) if isinstance(late, list) else 0
                open_items = comp_data.get("stillOpen", [])
                if isinstance(open_items, list):
                    total_open += len(open_items)
                    all_open_items.extend(open_items)

        total = total_on_time + total_late + total_open
        on_time_rate = round((total_on_time / total * 100)) if total > 0 else 0

        emoji = "✅" if total_open == 0 else "⚠️" if on_time_rate >= 80 else "🔴"

        lines = [
            f"## {emoji} {title}",
            f"**Date:** {milestone_date}" if milestone_date else "",
            f"**On-Time Rate:** {on_time_rate}%",
            "",
            "### Summary",
            f"- ✅ Resolved on time: {total_on_time}",
            f"- ⚠️ Resolved late: {total_late}",
            f"- 🔴 Still open: {total_open}",
            "",
        ]

        if all_open_items:
            lines.append("### Still Open Items")
            for item in all_open_items[:10]:
                if isinstance(item, dict):
                    lines.append(self.format_jira_item(item, "compact"))
            if len(all_open_items) > 10:
                lines.append(f"*...and {len(all_open_items) - 10} more*")

        return "\n".join(lines)

    def format_critical_bugs(self, data: Dict[str, Any], component: str = None) -> str:
        """Format critical bugs response."""
        bugs = data.get("critical_bugs", data.get("bugs", []))

        if component:
            bugs = [
                b
                for b in bugs
                if component.upper() in str(b.get("component", "")).upper()
                or component.upper() in str(b.get("key", "")).upper()
            ]

        title = "Critical Bugs" + (f" ({component.upper()})" if component else "")

        if not bugs:
            return f"## ✅ {title}\n\nNo critical bugs found!"

        lines = [f"## 🔴 {title} - {len(bugs)} total", ""]
        lines.extend(self.format_items_list(bugs, lambda b: self.format_jira_item(b, "compact"), 15))

        return "\n".join(lines)

    def format_regression_bugs(self, data: Dict[str, Any], component: str = None) -> str:
        """Format regression bugs response."""
        bugs = data.get("regression_bugs", data.get("bugs", data.get("items", [])))

        if component:
            bugs = [
                b
                for b in bugs
                if component.upper() in str(b.get("component", "")).upper()
                or component.upper() in str(b.get("key", "")).upper()
            ]

        title = "Regression Bugs" + (f" ({component.upper()})" if component else "")

        if not bugs:
            return f"## ✅ {title}\n\nNo regression bugs found!"

        lines = [f"## 🔄 {title} - {len(bugs)} total", ""]
        lines.extend(self.format_items_list(bugs, lambda b: self.format_jira_item(b, "compact"), 15))

        return "\n".join(lines)

    def format_escalations(self, data: Dict[str, Any]) -> str:
        """Format escalations response."""
        result = data.get("result", data)
        total = result.get("total", 0)
        by_type = result.get("by_type", {})
        items = result.get("items", [])

        if total == 0:
            return "## ✅ Customer Escalations\n\nNo open escalations!"

        lines = [f"## 🚨 Customer Escalations - {total} total", "", "### By Type"]
        for type_name, count in by_type.items():
            lines.append(f"- **{type_name}:** {count}")

        if items:
            lines.extend(["", "### Recent Escalations"])
            for item in items[:10]:
                key = item.get("key", "N/A")
                summary = (item.get("summary", ""))[:40]
                lines.append(f"- **{key}**: {summary}")

        return "\n".join(lines)

    def format_code_commits(self, data: Dict[str, Any], repo: str = None) -> str:
        """Format code commits response."""
        repos_data = data.get("repos", {})
        branch_cut = data.get("branchCutDate", "")
        release = data.get("release", DEFAULT_RELEASE)

        if repo:
            filtered = {k: v for k, v in repos_data.items() if repo.lower() in k.lower()}
            if filtered:
                repos_data = filtered

        title = f"Code Commits: {release}" + (f" ({repo})" if repo else "")
        lines = [f"## 📝 {title}", f"**Branch Cut:** {branch_cut}" if branch_cut else "", ""]

        for name, repo_data in repos_data.items():
            if isinstance(repo_data, dict):
                before = repo_data.get("beforeBranchCut", 0)
                after = repo_data.get("afterBranchCut", 0)
                flagged = repo_data.get("flaggedCommits", [])

                lines.extend([f"### {name}", f"- Before: {before}", f"- After: {after}"])
                if flagged:
                    lines.append(f"- ⚠️ Flagged: {len(flagged)}")
                lines.append("")

        return "\n".join(lines)

    def format_test_execution(self, data: Dict[str, Any]) -> str:
        """Format test execution response."""
        summary = data.get("summary", data)
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        blocked = summary.get("blocked", 0)
        untested = summary.get("untested", 0)

        pass_rate = round((passed / total * 100)) if total > 0 else 0
        emoji, _ = self.get_status_emoji(pass_rate, (90, 75))

        return f"""## {emoji} Test Execution

**Pass Rate:** {pass_rate}%

| Status | Count |
|--------|-------|
| ✅ Passed | {passed} |
| ❌ Failed | {failed} |
| ⛔ Blocked | {blocked} |
| ⏳ Untested | {untested} |
| **Total** | **{total}** |
"""

    def format_release_dates(self, data: Dict[str, Any]) -> str:
        """Format release dates/milestones."""
        from datetime import datetime

        # Handle new API format: {"release": {"name": "R134.0", "milestones": {...}}}
        release_data = data.get("release", data)
        release_name = release_data.get("name", data.get("release", DEFAULT_RELEASE))
        milestones_dict = release_data.get("milestones", {})

        # If milestones is a list (old format), use it directly
        if isinstance(milestones_dict, list):
            milestones = milestones_dict
        else:
            # Convert dict to list with status calculation
            today = datetime.now().date()
            milestone_order = [
                "IRR",
                "Branch Cut - EP",
                "Final Build - EP",
                "Signoff STG/FedAlpha - ENG",
                "Deploy MP Pre PROD",
                "Deploy Prod Day 1",
                "Deploy Prod Day 2",
                "Deploy Prod Day 3",
                "Deploy Prod Day 4",
            ]

            milestones = []
            for name in milestone_order:
                date_str = milestones_dict.get(name, "-")
                if date_str and date_str != "-":
                    try:
                        ms_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                        days_away = (ms_date - today).days
                        if days_away < 0:
                            status = "completed"
                        elif days_away == 0:
                            status = "current"
                        else:
                            status = "upcoming"
                        milestones.append({"name": name, "date": date_str, "status": status})
                    except ValueError:
                        milestones.append({"name": name, "date": date_str, "status": "unknown"})

        lines = [f"## 📅 Release Timeline: {release_name}", ""]
        for m in milestones:
            name = m.get("name", "Unknown")
            date = m.get("date", "TBD")
            status = m.get("status", "")
            emoji = "✅" if status == "completed" else "🔵" if status == "current" else "⏳"
            lines.append(f"- {emoji} **{name}:** {date}")

        return "\n".join(lines)


# Singleton instance
_utils = None


def get_utils() -> CoreUtils:
    """Get singleton CoreUtils instance."""
    global _utils
    if _utils is None:
        _utils = CoreUtils()
    return _utils

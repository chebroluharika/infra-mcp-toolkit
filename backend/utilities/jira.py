"""
JIRA Utilities
==============

Utility functions for JIRA data processing, formatting, and analysis.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import DEFAULT_RELEASE_ID, get_current_release

# =============================================================================
# Status Category Constants
# =============================================================================

# Critical priority values
CRITICAL_PRIORITIES = ["Highest", "Blocker", "Critical"]


# =============================================================================
# Parsers
# =============================================================================


def parse_date_safe(date_str: str) -> Optional[datetime]:
    """Parse date string safely, supporting multiple formats."""
    if not date_str:
        return None

    # Try multiple date formats
    formats = [
        "%Y-%m-%d",  # 2026-01-08
        "%Y-%m-%dT%H:%M:%SZ",  # 2026-01-20T12:31:09Z (GitHub/ISO 8601)
        "%Y-%m-%dT%H:%M:%S%z",  # 2026-01-20T12:31:09+00:00
        "%Y-%m-%dT%H:%M:%S",  # 2026-01-20T12:31:09
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Try fromisoformat as fallback (Python 3.7+)
    try:
        # Handle 'Z' suffix for fromisoformat
        clean_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except ValueError:
        pass

    return None


def parse_version_from_release(release_id: str) -> Tuple[str, str, str]:
    """Extract version numbers from release ID (e.g., 'R134' -> ('134', '134.0.0', '134.1.0'))."""
    match = re.search(r"R?(\d+)", release_id)
    if match:
        num = match.group(1)
        return num, f"{num}.0.0", f"{num}.1.0"
    return "134", "134.0.0", "134.1.0"


def get_release_id_from_param(release: Optional[str]) -> str:
    """Get release ID from parameter or default from config."""
    if release:
        return release
    current = get_current_release()
    return current["id"] if current else DEFAULT_RELEASE_ID


# =============================================================================
# Release Readiness
# =============================================================================


def determine_phase(
    today: datetime.date,
    irr_date: datetime.date,
    branch_cut_date: datetime.date,
    final_build_date: datetime.date,
    day1_deploy_date: Optional[datetime.date],
    day2_deploy_date: Optional[datetime.date] = None,
    day3_deploy_date: Optional[datetime.date] = None,
    day4_deploy_date: Optional[datetime.date] = None,
) -> Tuple[str, str, datetime.date, bool, str, str]:
    """
    Determine current release phase based on dates.

    Shows the CURRENT/LAST COMPLETED phase (the phase we are currently in).

    Returns: (phase_name, deadline_name, deadline_date, track_bugs, phase_message, phase_requirement)
    """
    # Phase logic: milestone date is INCLUDED in the phase (until 11:59 PM PST)
    # Use <= to include the milestone date itself in the current phase
    if today < irr_date:
        return (
            "pre_irr",
            "IRR",
            irr_date,
            False,
            "Complete all feature development. Ensure Stories are code-complete.",
            "All Stories must reach RESOLVED status before IRR",
        )
    elif today <= irr_date:
        # IRR day itself - still in pre_irr/IRR phase
        return (
            "irr",
            "IRR",
            irr_date,
            False,
            "IRR is TODAY. All Stories must be RESOLVED.",
            "All Stories must reach RESOLVED status by end of day",
        )
    elif today < branch_cut_date:
        # Between IRR and BC (not including BC day)
        days_to_bc = (branch_cut_date - today).days
        if days_to_bc <= 2:
            msg = f"⚠️ Branch Cut in {days_to_bc} day(s)! Final story completion."
        else:
            msg = "Final story completion phase. All development work must be merged."
        return (
            "irr_to_branch_cut",
            "Branch Cut",
            branch_cut_date,
            False,
            msg,
            "All Stories must be RESOLVED before Branch Cut",
        )
    elif today <= branch_cut_date:
        # Branch Cut day itself - still working towards BC requirements
        return (
            "branch_cut",
            "Branch Cut",
            branch_cut_date,
            False,
            "Branch Cut is TODAY. All Stories must be RESOLVED or CLOSED.",
            "All Stories must be RESOLVED/CLOSED by end of day",
        )
    elif today < final_build_date:
        # Between BC and FB (not including FB day)
        days_to_fb = (final_build_date - today).days
        if days_to_fb <= 2:
            msg = f"⚠️ CRITICAL: Only {days_to_fb} day(s) to Final Build!"
        elif days_to_fb <= 5:
            msg = f"🔶 Final Build approaching in {days_to_fb} days."
        else:
            msg = "Bug fixing and QA verification phase."
        return (
            "branch_cut_to_final_build",
            "Final Build",
            final_build_date,
            True,
            msg,
            "All Stories & Bugs must be VERIFIED or CLOSED before Final Build",
        )
    elif today <= final_build_date:
        # Final Build day itself
        return (
            "final_build",
            "Final Build",
            final_build_date,
            True,
            "Final Build is TODAY. All items must be CLOSED.",
            "All Stories & Bugs must be CLOSED by end of day",
        )
    else:
        # Post Final Build - determine which deployment phase we're in
        # Show the CURRENT phase (the last milestone we've reached or passed)

        # Build list of deploy phases with their dates in reverse order
        deploy_phases = []
        if day4_deploy_date:
            deploy_phases.append(("day4_deploy", "Day 4 Deploy", day4_deploy_date))
        if day3_deploy_date:
            deploy_phases.append(("day3_deploy", "Day 3 Deploy", day3_deploy_date))
        if day2_deploy_date:
            deploy_phases.append(("day2_deploy", "Day 2 Deploy", day2_deploy_date))
        if day1_deploy_date:
            deploy_phases.append(("day1_deploy", "Day 1 Deploy", day1_deploy_date))

        # Find the last completed deploy phase (most recent one where date <= today)
        for phase_id, phase_name, phase_date in deploy_phases:
            if today >= phase_date:
                if phase_id == "day4_deploy":
                    return (
                        "deployed",
                        "Deployed",
                        phase_date,
                        True,
                        "Release fully deployed to production.",
                        "Release complete - monitoring for issues.",
                    )
                return (
                    phase_id,
                    phase_name,
                    phase_date,
                    True,
                    "Code freeze in effect. Only critical regression fixes allowed.",
                    "All items must be CLOSED. Critical fixes only.",
                )

        # No deploy dates reached yet - we're in Final Build phase
        return (
            "final_build",
            "Final Build",
            final_build_date,
            True,
            "Code freeze in effect. Preparing for deployment.",
            "All items must be CLOSED. Critical fixes only.",
        )


def get_phase_status(days_remaining: int, total_open: int, total_code_review: int) -> Tuple[str, str]:
    """Determine phase status and overall status."""
    if days_remaining < 0:
        phase_status = "overdue"
    elif days_remaining <= 2:
        phase_status = "critical"
    elif days_remaining <= 5:
        phase_status = "warning"
    else:
        phase_status = "on_track"

    if total_open == 0:
        overall_status = "Ready"
    elif total_code_review > 3 or total_open > 10:
        overall_status = "At Risk"
    elif phase_status in ["critical", "overdue"] and total_open > 0:
        overall_status = "At Risk"
    else:
        overall_status = "In Progress"

    return phase_status, overall_status


def get_readiness_recommendation(stories: int, bugs: int, total_open: int, code_review: int) -> str:
    """Generate readiness recommendation based on metrics."""
    if total_open == 0:
        return "Release is ready for Branch Cut. All stories and bugs are resolved."

    recs = []
    if code_review > 0:
        recs.append(f"📝 {code_review} ticket(s) in Code Review.")
    if stories > 0:
        recs.append(f"📖 {stories} story(ies) still open.")
    if bugs > 0:
        recs.append(f"🐛 {bugs} bug(s) still open.")

    return " ".join(recs) if recs else "On track for release."


def analyze_blockers(all_issues: List[Dict], issues_by_assignee: Dict, days_remaining: int) -> Dict:
    """Analyze blockers and at-risk items for leadership visibility."""
    # At-Risk Assignees
    at_risk_assignees = []
    for assignee, data in issues_by_assignee.items():
        open_count = data["open"]
        if open_count == 0:
            continue
        items_per_day = open_count / max(days_remaining, 1)
        risk_level = "high" if items_per_day > 2 else "medium" if items_per_day > 1 else "low"
        at_risk_assignees.append(
            {
                "assignee": assignee,
                "openItems": open_count,
                "bugs": data.get("bugs", 0),
                "stories": data.get("stories", 0),
                "codeReview": data["code_review"],
                "itemsPerDayNeeded": round(items_per_day, 1),
                "riskLevel": risk_level,
                "tickets": data["tickets"][:5],
            }
        )
    at_risk_assignees.sort(key=lambda x: x["openItems"], reverse=True)

    # Critical Items - include all fields including reporter
    critical_items = [
        {
            "key": i.get("key"),
            "summary": i.get("summary"),
            "assignee": i.get("assignee", "Unassigned"),
            "priority": i.get("priority"),
            "status": i.get("status"),
            "type": i.get("type"),
            "url": i.get("url"),
            "component": i.get("component"),
            "reporter": i.get("reporter"),
        }
        for i in all_issues
        if (i.get("priority") or "").lower() in ["critical", "blocker", "highest"]
    ]

    # Code Review & Stuck Items - keep all fields from all_issues (including reporter)
    code_review_items = [{**i} for i in all_issues if (i.get("status") or "").lower() == "code review"]
    stuck_items = [{**i} for i in all_issues if (i.get("status") or "").lower() in ["open", "reopened", "to do"]]

    # Action Items
    action_items = []
    if critical_items:
        action_items.append(
            {
                "priority": 1,
                "category": "critical",
                "icon": "🔴",
                "title": f"{len(critical_items)} Critical/Blocker Items",
                "action": "Immediate resolution required",
            }
        )
    if len(code_review_items) >= 3:
        action_items.append(
            {
                "priority": 2,
                "category": "review",
                "icon": "🟡",
                "title": f"{len(code_review_items)} Items in Code Review",
                "action": "Assign additional reviewers",
            }
        )
    if stuck_items:
        action_items.append(
            {
                "priority": 3,
                "category": "stuck",
                "icon": "🟠",
                "title": f"{len(stuck_items)} Items Not Started",
                "action": "Check for blockers",
            }
        )

    high_risk = [a for a in at_risk_assignees if a["riskLevel"] == "high"]
    if high_risk:
        action_items.append(
            {
                "priority": 4,
                "category": "capacity",
                "icon": "🔵",
                "title": f"{len(high_risk)} Overloaded Assignees",
                "action": "Redistribute work",
            }
        )

    return {
        "atRiskAssignees": at_risk_assignees[:10],
        "criticalItems": critical_items,
        "codeReviewBottleneck": code_review_items,
        "stuckItems": stuck_items,
        "actionItems": sorted(action_items, key=lambda x: x["priority"]),
        "summary": {
            "totalAtRisk": len([a for a in at_risk_assignees if a["riskLevel"] in ["high", "medium"]]),
            "totalCritical": len(critical_items),
            "totalInReview": len(code_review_items),
            "totalStuck": len(stuck_items),
        },
    }


# =============================================================================
# Release Readiness Score (RRS) Calculation
# =============================================================================


def calculate_rrs_score(
    open_stories: int,
    open_bugs: int,
    blocker_count: int = 0,
    code_review_count: int = 0,
) -> int:
    """
    Calculate Release Readiness Score (RRS) using a consistent formula.

    This is the SINGLE SOURCE OF TRUTH for RRS calculation.
    Used by both Overview page and Release Readiness page.

    Formula:
        - Start at 100%
        - Subtract penalties based on open items:
            - Blockers: 2 points each (critical priority)
            - Stories: 1 point each
            - Non-critical bugs: 0.5 points each
            - Code review items: 0.25 points each
        - Minimum score: 0%, Maximum: 100%

    Args:
        open_stories: Number of open stories
        open_bugs: Number of open bugs (total, including blockers)
        blocker_count: Number of blocker/critical priority items
        code_review_count: Number of items in code review status

    Returns:
        RRS score as integer (0-100)
    """
    if open_stories == 0 and open_bugs == 0:
        return 100

    # Calculate penalties
    critical_penalty = blocker_count * 2
    story_penalty = open_stories * 1
    non_critical_bugs = max(0, open_bugs - blocker_count)
    bug_penalty = non_critical_bugs * 0.5
    code_review_penalty = code_review_count * 0.25

    total_penalty = critical_penalty + story_penalty + bug_penalty + code_review_penalty
    total_penalty = min(100, total_penalty)  # Cap penalty at 100

    rrs_score = round(100 - total_penalty)
    return max(0, min(100, rrs_score))

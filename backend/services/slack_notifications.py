"""
Slack Notification Service
==========================

Sends formatted Slack notifications for:
- Release Readiness: status summary, open items by assignee, critical blockers, QA backlog
- Regression Tracking: action items, not-started/blocked items with assignees
- Regression Status: 4 category tables (Manual, NFV, Interop, Automation) to dedicated channel
- Stack Monitoring: health alerts and version mismatches

Features:
- Rich formatting with Slack Block Kit
- Native Slack table blocks for expandable table views
- JIRA-to-Slack user mention resolution via user_mapping.json
- CC recipients on all notifications
- Phase-aware release messaging (Branch Cut, Final Build, Deployment)
- Generic reusable functions for any dashboard section

Usage - Specific Notifications:
    from services.slack_notifications import send_release_readiness_notification
    await send_release_readiness_notification(release_data)

    from services.slack_notifications import send_regression_status_notification
    await send_regression_status_notification(regression_data)  # Sends to YOUR_SLACK_CHANNEL_ID

Usage - Generic Table Notifications (for any section):
    from services.slack_notifications import send_table_notification, format_jira_link

    # Single table
    await send_table_notification(
        title="R135 Test Health Report",
        headers=["Key", "Test Name", "Status", "Assignee"],
        rows=[
            [format_jira_link("ENG-123"), "Login test", "Failed", "John D."],
            [format_jira_link("ENG-124"), "API test", "Passed", "Jane S."],
        ],
        channel="YOUR_SLACK_CHANNEL_ID",
        subtitle="*Summary:* 45/50 Passed · 90%",
        cc_slack_ids=["U04J2GPMW5A", "U02NU1432CD"],
    )

    # Multiple tables (separate messages)
    from services.slack_notifications import send_multi_table_notification

    await send_multi_table_notification(
        title="Release Regression Status",
        tables=[
            {"title": "Manual (25/30)", "headers": [...], "rows": [...]},
            {"title": "Automation (40/50)", "headers": [...], "rows": [...]},
        ],
        channel="YOUR_SLACK_CHANNEL_ID",
        cc_slack_ids=["U04J2GPMW5A"],
    )
"""

import logging
import os
import ssl
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import certifi
from config import settings
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


# =============================================================================
# Slack Table Block Builder (PDV-style native table)
# =============================================================================


def build_rich_text_cell(text: str) -> Dict:
    """
    Build a rich_text cell for Slack table block.

    This is the exact format used by the working PDV bot.
    Supports:
    - Slack user mentions: <@USER_ID>
    - Slack links: <url|display_text>
    - Plain text
    """
    import re

    text_str = str(text)

    # Split on Slack special tokens: user mentions <@U...> and links <url|text>
    parts = re.split(r"(<@[A-Z0-9]+>|<[^>]+\|[^>]+>)", text_str)

    # If no special tokens found, return plain text
    if len(parts) == 1:
        return {
            "type": "rich_text",
            "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": text_str}]}],
        }

    elements = []
    for part in parts:
        if not part:
            continue
        # User mention: <@U12345ABC>
        mention = re.match(r"^<@([A-Z0-9]+)>$", part)
        if mention:
            elements.append({"type": "user", "user_id": mention.group(1)})
            continue
        # Link: <url|display_text>
        link = re.match(r"^<([^|]+)\|([^>]+)>$", part)
        if link:
            elements.append({"type": "link", "url": link.group(1), "text": link.group(2)})
            continue
        # Plain text
        elements.append({"type": "text", "text": part})

    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": elements}],
    }


def build_table_blocks(
    headers: List[str],
    rows: List[List[str]],
    title: str = None,
) -> List[Dict]:
    """
    Build native Slack table block (same format as PDV bot).

    Args:
        headers: List of column header strings
        rows: List of rows, each row is a list of cell strings
        title: Optional title for the table

    Returns:
        List of Slack blocks including the table
    """
    blocks = []

    # Add title as header block if provided
    if title:
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}})

    # Build header row - each cell is a rich_text block
    header_row = []
    for header in headers:
        header_row.append(build_rich_text_cell(header))

    # Build data rows
    data_rows = []
    for row_data in rows:
        current_row = []
        for cell in row_data:
            current_row.append(build_rich_text_cell(cell))
        data_rows.append(current_row)

    # Combine header and data rows
    all_rows = [header_row]
    for data_row in data_rows:
        all_rows.append(data_row)

    # Build the table block
    table_block = {"type": "table", "rows": all_rows}

    blocks.append(table_block)

    return blocks


# Static user mapping from user_mapping.json (JIRA name -> {slack_id, handle})
_user_mapping: Dict[str, Dict] = {}


def _load_user_mapping() -> Dict[str, Dict]:
    """
    Load static JIRA-to-Slack user mapping from user_mapping.json.

    Each entry maps a JIRA display name to {"slack_id": "U...", "handle": "..."}.
    The slack_id enables proper Slack @mentions (<@USER_ID> format).
    """
    global _user_mapping
    if _user_mapping:
        return _user_mapping

    import json

    mapping_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_mapping.json")
    try:
        with open(mapping_path, "r") as f:
            data = json.load(f)
        # Filter out metadata keys (starting with _)
        _user_mapping = {k: v for k, v in data.items() if not k.startswith("_")}
        logger.info("Loaded %d user mappings from user_mapping.json", len(_user_mapping))
    except FileNotFoundError:
        logger.warning("user_mapping.json not found at %s", mapping_path)
    except Exception as e:
        logger.warning("Failed to load user_mapping.json: %s", e)

    return _user_mapping


# =============================================================================
# CC Recipients Configuration
# =============================================================================
# Add Slack user IDs (U...) for proper @mentions, or JIRA names as fallback.
# To get a Slack user ID: click profile → three dots → Copy member ID.

NOTIFICATION_CC_RECIPIENTS = [
    {"jira_name": "Shuangjiang Li", "slack_id": "U02G6HEFZ7B"},
    {"jira_name": "Vivek Sharma", "slack_id": "U02PQBMTGJD"},
    {"jira_name": "Rajesh Narayan Bhat", "slack_id": "U04J2GPMW5A"},
    {"jira_name": "Rajesh Raman V K", "slack_id": "U08FRJXD97X"},
    {"jira_name": "Frank Hu", "slack_id": "U02M89DDYF6"},
]

# Assignees that indicate tickets need reassignment (triage queues or managers)
TRIAGE_ASSIGNEES = [
    "ns_client_eng_triage",
    "Rajesh Raman V K",
    "Rajesh Narayan Bhat",
    "Frank Hu",
    "Vivek Sharma",
    "Shuangjiang Li",
]

# QA triage assignees for QA Verification Pending message
QA_TRIAGE_ASSIGNEES = [
    "Rajesh Raman V K",
    "Rajesh Narayan Bhat",
]

# =============================================================================
# Regression Status Notification Configuration
# =============================================================================
# Dedicated channel for regression status notifications
REGRESSION_SLACK_CHANNEL = "YOUR_SLACK_CHANNEL_ID"

# CC recipients for regression status notifications
# @rbhat @Snehal @Karthic @Rajesh Raman
REGRESSION_CC_RECIPIENTS = [
    {"jira_name": "Rajesh Narayan Bhat", "slack_id": "U04J2GPMW5A"},  # @rbhat
    {"jira_name": "Snehalkumar Donga", "slack_id": "U02NU1432CD"},  # @Snehal
    {"jira_name": "Karthic Mariappan", "slack_id": "U039UFJMKEH"},  # @Karthic
    {"jira_name": "Rajesh Raman V K", "slack_id": "U08FRJXD97X"},  # @Rajesh Raman
]


def _build_regression_cc_block(slack_service) -> Dict:
    """
    Build a Slack context block with CC mentions for regression notifications.

    Args:
        slack_service: SlackNotificationService instance (for _get_slack_mention)

    Returns:
        Slack context block with CC line
    """
    mentions = []
    for recipient in REGRESSION_CC_RECIPIENTS:
        if recipient.get("slack_id"):
            mentions.append(f"<@{recipient['slack_id']}>")
        else:
            mentions.append(slack_service._get_slack_mention(recipient["jira_name"]))

    cc_text = "cc: " + "  ".join(mentions)
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": cc_text}],
    }


def _build_cc_block(slack_service) -> Dict:
    """
    Build a Slack context block with CC mentions.

    Uses Slack user IDs if available, otherwise falls back to
    _get_slack_mention() which uses user_mapping.json handles.

    Args:
        slack_service: SlackNotificationService instance (for _get_slack_mention)

    Returns:
        Slack context block with CC line
    """
    mentions = []
    for recipient in NOTIFICATION_CC_RECIPIENTS:
        if recipient.get("slack_id"):
            mentions.append(f"<@{recipient['slack_id']}>")
        else:
            mentions.append(slack_service._get_slack_mention(recipient["jira_name"]))

    cc_text = "cc: " + "  ".join(mentions)
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": cc_text}],
    }


def _build_jira_filter_url(fix_version: str, assignee: str = None, qa_name: str = None) -> str:
    """Build a JIRA issues URL with a JQL filter for assignee workload or QA verification."""
    base = "https://your-org.atlassian.net/issues/"
    if assignee:
        jql = (
            f'(assignee = "{assignee}") AND '
            f'(fixVersion = "{fix_version}") AND '
            f'(project in (ENG, OPS, CD) AND component = "NS Client (NSC)" AND '
            f'status not in (closed, "Pending Close") AND '
            f"type not in (EPIC, Sub-task, task, Escalation)) "
            f"ORDER BY status ASC, priority DESC"
        )
    elif qa_name:
        # Handle "Unassigned" specially - use EMPTY filter for unset QA field
        # Note: Use 'customfield_10200 IS EMPTY' for more reliable JQL parsing
        if qa_name == "Unassigned":
            qa_filter = "customfield_10200 IS EMPTY"
        else:
            qa_filter = f'cf[10200] = "{qa_name}"'
        jql = (
            f"({qa_filter}) AND "
            f'(fixVersion = "{fix_version}") AND '
            f'(component = "NS Client (NSC)" AND '
            f"type IN (Bug, Story, Task) AND "
            f'status IN (Resolved, "Pending Close"))'
        )
    else:
        return ""
    return f"{base}?jql={urllib.parse.quote(jql)}"


def _format_date_display(date_str: str) -> str:
    """Format ISO date string to human-readable format (e.g., 'January 8')."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%B %-d")
    except (ValueError, TypeError):
        return date_str


# Create SSL context for Slack API calls (fixes macOS certificate issues)
def get_ssl_context():
    """Get SSL context with proper certificates."""
    try:
        # Try using certifi's certificate bundle
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        return ssl_context
    except Exception:
        # Fallback: create unverified context for testing (not for production)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        logger.warning("Using unverified SSL context - not recommended for production")
        return ssl_context


class SlackNotificationService:
    """Service for sending Slack notifications about release readiness."""

    def __init__(self, bot_token: str = None, channel: str = None):
        # Priority: passed param > settings from .env > hardcoded defaults
        self.bot_token = bot_token or settings.slack_bot_token
        self.channel = channel or settings.slack_channel
        # Enable if we have a token (even from defaults)
        self.enabled = bool(self.bot_token)

        # Initialize WebClient with SSL context to fix certificate issues on macOS
        if self.bot_token:
            ssl_context = get_ssl_context()
            self.client = WebClient(token=self.bot_token, ssl=ssl_context)
        else:
            self.client = None

        if self.enabled:
            logger.info("Slack service initialized - channel: %s", self.channel)

    def _get_slack_mention(self, jira_name: str, email: str = None) -> str:
        """
        Convert a JIRA display name to a Slack mention.

        Priority:
        1. Look up in user_mapping.json for proper <@USER_ID> mentions (enables pings)
        2. If not found and email provided, extract handle from email (display only, no ping)
        3. Fall back to plain JIRA name

        Args:
            jira_name: The JIRA assignee display name (e.g., "John Doe")
            email: Optional email address to extract handle from (e.g., "nbansal@your-company.com")

        Returns:
            Slack mention "<@USER_ID>", "@handle" from email, or the original name
        """
        if not jira_name or jira_name == "Unassigned":
            return jira_name

        mapping = _load_user_mapping()
        matched_entry = None

        if mapping:
            # Exact JIRA name match
            if jira_name in mapping:
                matched_entry = mapping[jira_name]
            else:
                # Case-insensitive match
                name_stripped = jira_name.strip()
                for map_name, entry in mapping.items():
                    if map_name.lower() == name_stripped.lower():
                        matched_entry = entry
                        break

                # First+last name match (skip middle names from JIRA)
                if not matched_entry:
                    jira_parts = name_stripped.split()
                    if len(jira_parts) >= 2:
                        first_last = f"{jira_parts[0]} {jira_parts[-1]}"
                        for map_name, entry in mapping.items():
                            map_parts = map_name.split()
                            if len(map_parts) >= 2:
                                map_first_last = f"{map_parts[0]} {map_parts[-1]}"
                                if first_last.lower() == map_first_last.lower():
                                    matched_entry = entry
                                    break

        if matched_entry and isinstance(matched_entry, dict) and matched_entry.get("slack_id"):
            return f"<@{matched_entry['slack_id']}>"

        # Fallback: extract handle from email if provided (display only, no ping)
        if email and "@" in email:
            handle = email.split("@")[0]
            return f"@{handle}"

        return jira_name

    def build_release_readiness_blocks(self, data: Dict) -> List[Dict]:
        """
        Build Slack notification with PDV-style table summary.

        Format:
        - Header with release summary (like PDV: "Release Summary | 12✅ 3❌")
        - Date range and overall stats
        - Compact table with assignee/stories/bugs
        - "Open full table" button
        - Branch cut requirements (if applicable)
        - Footer with timestamp
        """
        blocks = []

        # Initialize table data storage
        self._last_table_data = None
        self._assignee_table_data = None
        self._critical_table_data = None
        self._qa_verification_table_data = None

        # Extract data
        release = data.get("release", "Unknown")
        phase_countdown = data.get("phaseCountdown", {})
        summary = data.get("summary", {})
        components_data = data.get("componentsData", {})
        current_phase = data.get("currentPhase", {})
        timeline = data.get("timeline", {})

        # Status info
        days_remaining = phase_countdown.get("days_remaining", 0)
        deadline_name = phase_countdown.get("deadline_name", "IRR")

        # Use IRR still_open count if available (more accurate for items that missed IRR)
        # This gives a complete picture vs the branch-cut filtered count
        irr_still_open = data.get("irr_still_open", 0)
        irr_issues = data.get("irr_issues", [])

        # Use IRR data for total open if available and greater than release-readiness count
        release_readiness_total = summary.get("total_fb_issues", 0)
        total_open = max(irr_still_open, release_readiness_total) if irr_still_open > 0 else release_readiness_total

        open_stories = summary.get("total_bc_stories", 0)
        open_bugs = summary.get("total_bc_bugs", 0)

        # Derive fix_version for JIRA filter URLs (R135 -> 135.0.0)
        release_num = release.replace("R", "").replace("r", "").strip()
        self._fix_version = f"{release_num}.0.0"

        # Debug logging for data validation
        logger.debug("build_release_readiness_blocks for %s:", release)
        logger.debug(
            "  summary: total_fb_issues=%d, total_bc_stories=%d, total_bc_bugs=%d", total_open, open_stories, open_bugs
        )
        logger.debug("  componentsData keys: %s", list(components_data.keys()))

        # ===== COLLECT AND GROUP ISSUES =====
        # Use assigneeSummaryIssues (broader JQL: ENG/OPS/CD, includes Resolved, no label exclusions)
        # Falls back to componentsData if not available
        assignee_summary_issues = data.get("assigneeSummaryIssues", [])
        if assignee_summary_issues:
            all_issues = assignee_summary_issues
        else:
            all_issues = []
            for comp_data in components_data.values():
                all_issues.extend(comp_data.get("issues", []))

        # Also include IRR issues that may not be in the issues list (missed deadline items)
        existing_keys = {issue.get("key") for issue in all_issues}
        for irr_issue in irr_issues:
            if irr_issue.get("key") not in existing_keys:
                all_issues.append(irr_issue)
                existing_keys.add(irr_issue.get("key"))

        by_assignee = {}
        by_status = {}  # Group issues by status

        for issue in all_issues:
            assignee = issue.get("assignee", "Unassigned")
            issue_type = (issue.get("type") or issue.get("issuetype") or "Story").lower()
            status = issue.get("status", "Unknown")
            is_resolved = status.lower() == "resolved"

            if assignee not in by_assignee:
                by_assignee[assignee] = {
                    "stories": 0,
                    "bugs": 0,
                    "unresolved_stories": 0,
                    "unresolved_bugs": 0,
                    "open": 0,
                    "resolved": 0,
                    "issues": [],
                }
            if "bug" in issue_type:
                by_assignee[assignee]["bugs"] += 1
                if not is_resolved:
                    by_assignee[assignee]["unresolved_bugs"] += 1
            else:
                by_assignee[assignee]["stories"] += 1
                if not is_resolved:
                    by_assignee[assignee]["unresolved_stories"] += 1
            if is_resolved:
                by_assignee[assignee]["resolved"] += 1
            else:
                by_assignee[assignee]["open"] += 1
            by_assignee[assignee]["issues"].append(issue)

            # Group by status
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(issue)

        total_stories = sum(a["stories"] for a in by_assignee.values())
        total_bugs = sum(a["bugs"] for a in by_assignee.values())

        # Update total_open to match the actual issue count from the broader dataset
        total_open = len(all_issues)

        # ===== PHASE-AWARE HEADER =====
        phase_lower = (current_phase.get("phase", "") or "").lower()

        # Phase detection based on phase_lower from determine_phase()
        # The phase now correctly includes the milestone date itself (until 11:59 PM PST)
        is_pre_irr = phase_lower == "pre_irr"
        is_irr_phase = phase_lower == "irr"  # IRR day itself
        is_irr_to_bc_phase = phase_lower == "irr_to_branch_cut"  # Between IRR and BC
        is_branch_cut_phase = phase_lower == "branch_cut"  # BC day itself
        is_bc_to_fb_phase = phase_lower == "branch_cut_to_final_build"  # Between BC and FB
        is_final_build_phase = phase_lower == "final_build"  # FB day itself
        is_deployment_phase = phase_lower in ["day1_deploy", "day2_deploy", "day3_deploy", "day4_deploy"]
        is_completed = phase_lower in ["deployed", "completed"]

        irr_display = _format_date_display(timeline.get("irr_date", ""))
        bc_display = _format_date_display(timeline.get("branch_cut_date", ""))
        fb_display = _format_date_display(timeline.get("final_build_date", ""))
        deploy_display = _format_date_display(
            timeline.get("day1_deploy")
            or timeline.get("day2_deploy")
            or timeline.get("day3_deploy")
            or timeline.get("day4_deploy")
            or ""
        )

        # Helper to format days remaining text
        def _format_days_remaining_text(days: int, date_display: str) -> str:
            """Format milestone date with days remaining context."""
            if days == 0:
                return f"is *today* ({date_display})"
            elif days == 1:
                return f"is *tomorrow* ({date_display})"
            else:
                return f"is in just *{days} more days* on *{date_display}*"

        # JQL for clickable total link — matches the broader assigneeSummaryIssues query
        all_tickets_jql = (
            f'(fixVersion = "{self._fix_version}") AND '
            f'(project in (ENG, OPS, CD) AND component = "NS Client (NSC)" AND '
            f'status not in (closed, "Pending Close") AND '
            f"type not in (EPIC, Sub-task, task, Escalation))"
        )

        all_tickets_url = f"https://your-org.atlassian.net/issues/?jql={urllib.parse.quote(all_tickets_jql)}"
        total_open_link = f"<{all_tickets_url}|{total_open}>"

        # ===== HEADER: Release Summary | X Stories Y Bugs =====
        header_text = f"{release} Release Summary | {total_stories} Stories {total_bugs} Bugs"
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            }
        )

        if is_completed:
            # Announcement with @here
            announce = f"<!here> :loudspeaker: {release} Release Summary - All Clear"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": announce},
                }
            )
        elif total_open == 0:
            announce = f"<!here> :loudspeaker: {release} Release Summary | All Items Resolved"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": announce},
                }
            )
        else:
            # Build announcement with @here based on phase
            # Phase names now correctly include the milestone date itself (until 11:59 PM PST)

            if is_deployment_phase:
                days_text = _format_days_remaining_text(days_remaining, deploy_display)
                announce = f"<!here> :loudspeaker: *{release} {deadline_name}* {days_text}"
            elif is_completed:
                announce = f"<!here> :loudspeaker: *{release}* has been fully deployed"
            elif is_final_build_phase:
                # FB day itself - "Final Build is today"
                days_text = _format_days_remaining_text(0, fb_display)
                announce = f"<!here> :loudspeaker: *{release} Final Build* {days_text}"
            elif is_bc_to_fb_phase:
                # Between BC and FB - show FB countdown
                days_text = _format_days_remaining_text(days_remaining, fb_display)
                announce = f"<!here> :loudspeaker: *{release} Final Build* {days_text}"
            elif is_branch_cut_phase:
                # BC day itself - "Branch Cut is today"
                days_text = _format_days_remaining_text(0, bc_display)
                announce = f"<!here> :loudspeaker: *{release} Branch Cut* {days_text}"
            elif is_irr_to_bc_phase:
                # Between IRR and BC - show BC countdown
                days_text = _format_days_remaining_text(days_remaining, bc_display)
                announce = f"<!here> :loudspeaker: *{release} Branch Cut* {days_text}"
            elif is_irr_phase:
                # IRR day itself - "IRR is today"
                days_text = _format_days_remaining_text(0, irr_display)
                announce = f"<!here> :loudspeaker: *{release} IRR* {days_text}"
            elif is_pre_irr and irr_display and bc_display:
                # Pre-IRR - show IRR countdown and BC date
                days_text = _format_days_remaining_text(days_remaining, irr_display)
                announce = f"<!here> :loudspeaker: *{release} IRR* {days_text} and *BC* is on *{bc_display}*"
            else:
                announce = f"<!here> :loudspeaker: *{release} {deadline_name}* in *{days_remaining}* days"

            # Combine announcement and tickets count in single line
            full_announce = f"{announce}. We still have *{total_open_link}* tickets in various stages"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": full_announce},
                }
            )

            # ===== STATUS BREAKDOWN =====
            # Define status display order and groupings
            status_groups = {
                "OPEN": ["Open", "To Do", "Reopened"],
                "IN PROGRESS": ["In Progress", "In Development"],
                "MORE INFO": ["More Info", "More Information", "Needs Info"],
                "CODE REVIEW": ["Code Review", "In Review"],
                "RESOLVED": ["Resolved"],
            }

            # Base JQL for status-filtered links
            base_status_jql = (
                f'(fixVersion = "{self._fix_version}") AND '
                f'(project in (ENG, OPS, CD) AND component = "NS Client (NSC)" AND '
                f"type not in (EPIC, Sub-task, task, Escalation))"
            )

            # JQL status filters for each group
            status_jql_filters = {
                "OPEN": 'status in (Open, "To Do", Reopened)',
                "IN PROGRESS": 'status in ("In Progress", "In Development")',
                "MORE INFO": 'status in ("More Info", "More Information", "Needs Info")',
                "CODE REVIEW": 'status in ("Code Review", "In Review")',
                "RESOLVED": "status = Resolved",
            }

            status_counts = {}
            for group_name, statuses in status_groups.items():
                count = 0
                for s in statuses:
                    if s in by_status:
                        count += len(by_status[s])
                status_counts[group_name] = count

            # Calculate TO BE REASSIGNED count (tickets assigned to triage accounts)
            to_be_reassigned_count = 0
            for assignee_name in by_assignee.keys():
                if assignee_name in TRIAGE_ASSIGNEES:
                    to_be_reassigned_count += by_assignee[assignee_name]["stories"] + by_assignee[assignee_name]["bugs"]

            # Build status breakdown with clickable JQL links
            status_lines = []
            for group_name in ["OPEN", "IN PROGRESS", "MORE INFO", "CODE REVIEW", "RESOLVED"]:
                count = status_counts.get(group_name, 0)
                status_filter = status_jql_filters.get(group_name, "")
                if count > 0 and status_filter:
                    status_jql = f"{base_status_jql} AND {status_filter}"
                    status_url = f"https://your-org.atlassian.net/issues/?jql={urllib.parse.quote(status_jql)}"
                    status_lines.append(f"*{group_name}:* <{status_url}|{count}>")
                else:
                    status_lines.append(f"*{group_name}:* {count}")

            # Add TO BE REASSIGNED
            status_lines.append(f"*TO BE REASSIGNED:* {to_be_reassigned_count}")

            # Add CUSTOMER ESCALATIONS (fetched via separate JQL)
            escalation_count = data.get("escalation_count", 0)
            escalation_url = data.get("escalation_jira_url", "")
            self._escalation_count = escalation_count
            self._escalation_url = escalation_url
            if escalation_url:
                status_lines.append(f"*CUSTOMER ESCALATIONS:* <{escalation_url}|{escalation_count}>")
            else:
                status_lines.append(f"*CUSTOMER ESCALATIONS:* {escalation_count}")

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(status_lines)},
                }
            )

        # ===== PHASE-SPECIFIC REQUIREMENTS MESSAGE =====
        if is_completed:
            # Release is fully deployed
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ *Release Deployed!* All production deployments completed.",
                    },
                }
            )
        elif is_deployment_phase:
            # Deployment phase (after Final Build)
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Deployment Phase:*\n"
                            "• Code freeze in effect - only critical regression fixes allowed\n"
                            "• All bugs and stories must be in `Closed` status _(no exceptions)_\n"
                            "• Monitor production deployments for any issues\n"
                            "• Any hotfixes require release lead approval"
                        ),
                    },
                }
            )
        elif is_final_build_phase:
            # Final Build requirements - show regardless of open items
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Final Build Requirements:*\n"
                            "• Regression tests 100% executed with 95% pass rate\n"
                            "• Regression test status updated on the *Release Signoff - Final Build* Confluence page\n"
                            "• Test failures all have JIRAs filed\n"
                            "• All bugs and stories for the release are in `Pending Close`/`Closed` status _(no exceptions)_\n"
                            "• All double commits are merged to both release and develop branches\n"
                            "• Any manual patches done in production for IMFs should be merged to release branch\n"
                            "• *Release Notes / TOI / Documentation* should be completed _(no exceptions)_"
                        ),
                    },
                }
            )
        elif is_bc_to_fb_phase and total_open > 0:
            # Between BC and FB - show Final Build requirements
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Final Build Requirements:*\n"
                            "• Regression tests 100% executed with 95% pass rate\n"
                            "• Regression test status updated on the *Release Signoff - Final Build* Confluence page\n"
                            "• Test failures all have JIRAs filed\n"
                            "• All bugs and stories for the release are in `Pending Close`/`Closed` status _(no exceptions)_\n"
                            "• All double commits are merged to both release and develop branches\n"
                            "• Any manual patches done in production for IMFs should be merged to release branch\n"
                            "• *Release Notes / TOI / Documentation* should be completed _(no exceptions)_"
                        ),
                    },
                }
            )
        elif (is_branch_cut_phase or is_irr_to_bc_phase) and total_open > 0:
            # BC day or between IRR and BC - show Branch Cut requirements
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Branch Cut Requirements:*\n"
                            "• All *Stories* must have status: `Pending Close` or `Closed`\n"
                            "• All *Bugs* must have status: `Resolved`, `Pending Close`, or `Closed`\n"
                            "• _Exception: Bugs created or re-opened in the last 48 hours_\n"
                            "• Ensure *Release Notes / TOI links / Documentation* fields are updated"
                        ),
                    },
                }
            )
        elif (is_irr_phase or is_pre_irr) and total_open > 0:
            # IRR day or pre-IRR - show IRR requirements
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*IRR Requirements:*\n"
                            "• All *Stories* must have status: `Resolved`, `Pending Close`, or `Closed`\n"
                            "• Feature development must be complete\n"
                            "• All code must be merged to the release branch"
                        ),
                    },
                }
            )

        # ===== ASSIGNEE TABLE (with status breakdown) =====
        self._last_table_data = None

        if total_open == 0:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ *All items resolved!* Release is ready to proceed.",
                    },
                }
            )
        else:
            # Helper to get Slack display name for an assignee
            def _assignee_display_name(assignee_name, assignee_counts):
                assignee_email = ""
                if assignee_counts.get("issues"):
                    assignee_email = assignee_counts["issues"][0].get("assignee_email", "")
                slack_name = self._get_slack_mention(assignee_name, assignee_email)
                if len(slack_name) <= 28 or slack_name.startswith("<@") or slack_name.startswith("@"):
                    return slack_name
                return slack_name[:28]

            sorted_assignees = sorted(by_assignee.items(), key=lambda x: x[1]["stories"] + x[1]["bugs"], reverse=True)

            self._last_table_data = {
                "headers": [
                    "Assignee",
                    "Unresolved Stories",
                    "Unresolved Bugs",
                    "Resolved Stories",
                    "Resolved Bugs",
                    "Total",
                ],
                "rows": [],
            }

            for assignee, counts in sorted_assignees:
                display_name = _assignee_display_name(assignee, counts)
                total = counts["stories"] + counts["bugs"]
                resolved_stories = counts["stories"] - counts["unresolved_stories"]
                resolved_bugs = counts["bugs"] - counts["unresolved_bugs"]

                jira_url = _build_jira_filter_url(self._fix_version, assignee=assignee)
                total_cell = f"<{jira_url}|{total}>" if jira_url else str(total)

                self._last_table_data["rows"].append(
                    [
                        display_name,
                        str(counts["unresolved_stories"]),
                        str(counts["unresolved_bugs"]),
                        str(resolved_stories),
                        str(resolved_bugs),
                        total_cell,
                    ]
                )

            self._assignee_table_data = self._last_table_data

            if self._assignee_table_data and self._assignee_table_data.get("rows"):
                logger.info("Built assignee table for %s with %d rows", release, len(self._assignee_table_data["rows"]))

            # ===== CRITICAL ITEMS =====
            critical_items = [
                issue
                for issue in all_issues
                if (issue.get("priority") or "").lower() in ["critical", "blocker", "highest"]
            ]

            if critical_items:
                # Count CRITICALs and BLOCKERs separately
                critical_count = sum(1 for i in critical_items if (i.get("priority") or "").lower() == "critical")
                blocker_count = sum(
                    1 for i in critical_items if (i.get("priority") or "").lower() in ["blocker", "highest"]
                )

                # Build critical items table data
                critical_headers = ["Key", "Type", "Priority", "Summary", "Status", "Assignee"]
                critical_rows = []

                for item in critical_items:
                    key = item.get("key", "")
                    url = item.get("url") or f"https://your-org.atlassian.net/browse/{key}"
                    issue_type = item.get("type") or item.get("issuetype") or "Task"
                    priority = item.get("priority") or "—"
                    summ = (item.get("summary") or "")[:40]
                    status = item.get("status") or "Open"
                    assignee_name = item.get("assignee", "Unassigned")
                    assignee_email = item.get("assignee_email", "")
                    assignee = self._get_slack_mention(assignee_name, assignee_email)

                    critical_rows.append([f"<{url}|{key}>", issue_type, priority, summ, status, assignee])

                self._critical_table_data = {
                    "headers": critical_headers,
                    "rows": critical_rows,
                    "title": f"Critical/Blocker Items ({len(critical_items)})",
                    "critical_count": critical_count,
                    "blocker_count": blocker_count,
                }
            else:
                self._critical_table_data = None

        # ===== QA VERIFICATION PENDING TABLE =====
        total_resolved_only = data.get("totalResolvedOnly", 0)
        total_pending_close = data.get("totalPendingClose", 0)
        resolved_by_qa = data.get("resolvedByQA", [])
        if resolved_by_qa:
            qa_headers = ["QA Engineer", "Stories", "Bugs", "Resolved", "Pending Close", "Total"]
            qa_rows = []

            # Collect all QA tickets to calculate priority counts
            all_qa_tickets = []
            qa_to_be_reassigned = 0

            for qa_entry in resolved_by_qa:
                raw_qa_name = qa_entry.get("qa", "Unassigned")
                qa_email = qa_entry.get("qa_email", "")
                qa_slack_name = self._get_slack_mention(raw_qa_name, qa_email)
                display_name = (
                    qa_slack_name
                    if len(qa_slack_name) <= 28 or qa_slack_name.startswith("<@") or qa_slack_name.startswith("@")
                    else qa_slack_name[:28]
                )
                stories = qa_entry.get("stories", 0)
                bugs = qa_entry.get("bugs", 0)
                resolved = qa_entry.get("resolved", 0)
                pending = qa_entry.get("pending_close", 0)
                total = qa_entry.get("total", resolved + pending)

                jira_url = _build_jira_filter_url(self._fix_version, qa_name=raw_qa_name)
                total_cell = f"<{jira_url}|{total}>" if jira_url else str(total)

                qa_rows.append([display_name, str(stories), str(bugs), str(resolved), str(pending), total_cell])

                # Collect tickets and count TO BE REASSIGNED
                tickets = qa_entry.get("tickets", [])
                all_qa_tickets.extend(tickets)

                # Check if QA name is in triage list (needs reassignment)
                if raw_qa_name in QA_TRIAGE_ASSIGNEES or raw_qa_name == "Unassigned":
                    qa_to_be_reassigned += total

            # Calculate priority counts from QA tickets
            qa_critical_count = sum(1 for t in all_qa_tickets if (t.get("priority") or "").lower() == "critical")
            qa_blocker_count = sum(
                1 for t in all_qa_tickets if (t.get("priority") or "").lower() in ["blocker", "highest"]
            )
            qa_major_count = sum(1 for t in all_qa_tickets if (t.get("priority") or "").lower() == "major")

            if qa_rows:
                self._qa_verification_table_data = {
                    "headers": qa_headers,
                    "rows": qa_rows,
                    "title": f"QA Verification Pending ({total_resolved_only + total_pending_close})",
                    "critical_count": qa_critical_count,
                    "blocker_count": qa_blocker_count,
                    "major_count": qa_major_count,
                    "to_be_reassigned": qa_to_be_reassigned,
                }

        return blocks

    async def send_notification(
        self,
        blocks: List[Dict],
        text: str = "Release Readiness Update",
        channel: str = None,
    ) -> Dict:
        """
        Send notification to Slack channel.

        Args:
            blocks: List of Slack block elements (including table blocks)
            text: Fallback text for notifications
            channel: Target channel (uses default if not specified)
        """
        if not self.enabled:
            logger.warning("Slack notifications are disabled or not configured")
            return {"success": False, "error": "Slack not configured"}

        target_channel = channel or self.channel
        if not target_channel:
            logger.error("No Slack channel configured")
            return {"success": False, "error": "No channel configured"}

        # Slack allows max 50 blocks per message
        if len(blocks) > 50:
            logger.warning("Truncating blocks from %d to 50", len(blocks))
            blocks = blocks[:49]
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "_Message truncated - view full details in JIRA_"}],
                }
            )

        # Log for debugging
        logger.info("Sending %d blocks to Slack", len(blocks))

        try:
            response = self.client.chat_postMessage(
                channel=target_channel,
                text=text,
                blocks=blocks,
                unfurl_links=False,
                unfurl_media=False,
            )

            logger.info("Slack notification sent successfully to %s", target_channel)
            return {
                "success": True,
                "channel": target_channel,
                "ts": response.get("ts"),
                "message": "Notification sent successfully",
            }

        except SlackApiError as e:
            error_detail = e.response.get("error", "unknown")
            response_meta = e.response.get("response_metadata", {})
            messages = response_meta.get("messages", [])

            logger.error("Slack API error: %s", error_detail)
            if messages:
                logger.error("Slack error details: %s", messages)

            # Log block count for debugging
            logger.error("Number of blocks sent: %d", len(blocks))

            return {
                "success": False,
                "error": error_detail,
                "details": messages,
                "message": f"Failed to send notification: {error_detail}",
            }
        except Exception as e:
            logger.error("Error sending Slack notification: %s", e)
            return {"success": False, "error": str(e), "message": f"Failed to send notification: {str(e)}"}

    async def send_release_readiness_notification(self, release_data: Dict, channel: str = None) -> Dict:
        """
        Send release readiness notification to Slack with native table blocks.

        Uses Slack's native table block which provides an expandable table view.

        Args:
            release_data: Data from /api/jira/release-readiness endpoint
            channel: Override default channel

        Returns:
            Dict with success status and details
        """
        release = release_data.get("release", "Unknown")
        summary = release_data.get("summary", {})
        total_open = summary.get("total_fb_issues", 0)
        total_stories = summary.get("total_bc_stories", 0)
        total_bugs = summary.get("total_bc_bugs", 0)

        logger.info(
            "Building notification for %s: %d stories, %d bugs, %d total open",
            release,
            total_stories,
            total_bugs,
            total_open,
        )

        # Build the message blocks (header + phase + requirements)
        blocks = self.build_release_readiness_blocks(release_data)
        text = f"Release Readiness - {release}"

        # Check which messages will be sent to determine where to put CC
        assignee_data = getattr(self, "_assignee_table_data", None)
        critical_data = getattr(self, "_critical_table_data", None)
        qa_data = getattr(self, "_qa_verification_table_data", None)

        has_critical = critical_data and critical_data.get("rows")
        has_qa = qa_data and qa_data.get("rows")

        # === MESSAGE 1: Summary + Unresolved Assignee Table ===
        if assignee_data and assignee_data.get("rows"):
            table_blocks = build_table_blocks(
                headers=assignee_data["headers"],
                rows=assignee_data["rows"],
                title=f"{release} - Assignee Summary",
            )
            blocks.extend(table_blocks)
            logger.info("Added unresolved assignee table with %d rows for %s", len(assignee_data["rows"]), release)

        blocks.append({"type": "divider"})
        # Add CC to every message
        blocks.append(_build_cc_block(self))

        result = await self.send_notification(blocks=blocks, text=text, channel=channel)

        if result.get("success"):
            result["table_included"] = True

        # === MESSAGE 2: Critical/Blocker Items (separate native table) ===
        if result.get("success") and has_critical:
            # Add priority counts before the table
            critical_count = critical_data.get("critical_count", 0)
            blocker_count = critical_data.get("blocker_count", 0)
            priority_counts_text = f"*CRITICALs:* {critical_count}\n*BLOCKERs:* {blocker_count}"

            critical_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{release} - {critical_data.get('title', 'Critical Items')}",
                        "emoji": True,
                    },
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": priority_counts_text}},
            ]

            table_blocks = build_table_blocks(
                headers=critical_data["headers"],
                rows=critical_data["rows"],
            )
            critical_blocks.extend(table_blocks)
            critical_blocks.append({"type": "divider"})
            # Add CC to every message
            critical_blocks.append(_build_cc_block(self))

            critical_result = await self.send_notification(
                blocks=critical_blocks,
                text=f"Critical Items - {release}",
                channel=channel,
            )
            if critical_result.get("success"):
                result["critical_items_sent"] = True
                result["critical_items_count"] = len(critical_data["rows"])
                logger.info("Sent critical items table with %d items", len(critical_data["rows"]))

        # === MESSAGE 3: QA Verification Pending (separate native table) ===
        if result.get("success") and has_qa:
            # Add priority counts before the table
            qa_critical_count = qa_data.get("critical_count", 0)
            qa_blocker_count = qa_data.get("blocker_count", 0)
            qa_major_count = qa_data.get("major_count", 0)
            qa_to_be_reassigned = qa_data.get("to_be_reassigned", 0)

            # Get escalation data stored during build_release_readiness_blocks
            esc_count = getattr(self, "_escalation_count", 0)
            esc_url = getattr(self, "_escalation_url", "")
            esc_display = f"<{esc_url}|{esc_count}>" if esc_url else str(esc_count)

            qa_priority_lines = [
                f"*CRITICALs:* {qa_critical_count}",
                f"*BLOCKERs:* {qa_blocker_count}",
                f"*MAJORs:* {qa_major_count}",
                f"*TO BE REASSIGNED:* {qa_to_be_reassigned}",
                f"*CUSTOMER ESCALATIONS:* {esc_display}",
            ]

            qa_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{release} - {qa_data.get('title', 'QA Verification Pending')}",
                        "emoji": True,
                    },
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(qa_priority_lines)}},
            ]

            table_blocks = build_table_blocks(
                headers=qa_data["headers"],
                rows=qa_data["rows"],
            )
            qa_blocks.extend(table_blocks)
            qa_blocks.append({"type": "divider"})

            # QA message uses shorter CC list: only @rbhat and @Rajesh Raman
            qa_cc_text = "cc: <@U04J2GPMW5A>  <@U08FRJXD97X>"  # rbhat and Rajesh Raman
            qa_blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": qa_cc_text}],
                }
            )

            qa_result = await self.send_notification(
                blocks=qa_blocks,
                text=f"QA Verification Pending - {release}",
                channel=channel,
            )
            if qa_result.get("success"):
                result["qa_verification_sent"] = True
                result["qa_verification_count"] = len(qa_data["rows"])
                logger.info("Sent QA verification table with %d rows", len(qa_data["rows"]))

        return result

    def build_stack_alert_blocks(self, alerts: List[Dict]) -> List[Dict]:
        """
        Build Slack blocks for stack monitoring alerts.

        Args:
            alerts: List of alert dicts with keys:
                - stack: Stack name (e.g., "PROD01")
                - severity: "critical", "warning", or "info"
                - message: Alert message
                - time: Timestamp string
                - region: Optional region name
                - health_percent: Optional health percentage
                - healthy_count: Optional healthy count
                - total_count: Optional total count

        Returns:
            List of Slack block elements
        """
        blocks = []

        # Severity emoji mapping
        severity_emoji = {
            "critical": "🔴",
            "warning": "⚠️",
            "info": "ℹ️",
        }

        if len(alerts) == 1:
            # Single alert format
            alert = alerts[0]
            severity = alert.get("severity", "warning").lower()
            emoji = severity_emoji.get(severity, "⚠️")
            stack = alert.get("stack", "Unknown")
            region = alert.get("region", "")
            message = alert.get("message", "Alert triggered")

            # Header
            blocks.append(
                {"type": "header", "text": {"type": "plain_text", "text": "🚨 Stack Monitoring Alert", "emoji": True}}
            )

            # Alert details
            region_text = f"  │  {region}" if region else ""
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{emoji} *{severity.upper()}*  │  {stack}{region_text}"},
                }
            )

            # Message
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": message}})

            # Health info if available
            health_pct = alert.get("health_percent")
            healthy = alert.get("healthy_count")
            total = alert.get("total_count")
            if health_pct is not None and healthy is not None and total is not None:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"Health: {health_pct}% ({healthy}/{total} healthy)"}],
                    }
                )

        else:
            # Batch alerts format
            critical_count = sum(1 for a in alerts if a.get("severity", "").lower() == "critical")
            warning_count = sum(1 for a in alerts if a.get("severity", "").lower() == "warning")
            info_count = sum(1 for a in alerts if a.get("severity", "").lower() == "info")

            # Header with count
            blocks.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 Stack Monitoring: {len(alerts)} New Alerts",
                        "emoji": True,
                    },
                }
            )

            # List each alert
            alert_lines = []
            for alert in alerts[:10]:  # Limit to 10 alerts
                severity = alert.get("severity", "warning").lower()
                emoji = severity_emoji.get(severity, "⚠️")
                stack = alert.get("stack", "Unknown")
                message = alert.get("message", "Alert")
                # Truncate message if too long
                if len(message) > 50:
                    message = message[:47] + "..."
                alert_lines.append(f"{emoji} *{severity.upper()}* │ {stack} │ {message}")

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(alert_lines)}})

            # Summary
            summary_parts = []
            if critical_count > 0:
                summary_parts.append(f"{critical_count} critical")
            if warning_count > 0:
                summary_parts.append(f"{warning_count} warning")
            if info_count > 0:
                summary_parts.append(f"{info_count} info")

            if summary_parts:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"Summary: {', '.join(summary_parts)}"}],
                    }
                )

        # Divider
        blocks.append({"type": "divider"})

        # Footer with timestamp
        now = datetime.now().strftime("%I:%M %p IST")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Stack Monitoring • {now}"}]})

        return blocks

    def build_deployment_version_report_blocks(self, data: Dict) -> List[Dict]:
        """
        Build Slack blocks for Deployment Version Report.

        Creates a table showing deployment versions across stacks with status indicators.

        Args:
            data: Dict with structure:
                {
                    "stacks": ["QA01", "STG01", ...],  # Stack names for columns
                    "deployments": [
                        {
                            "service": "addonman",
                            "deployment_container": "addonman-addonman/addonman",
                            "versions": {
                                "QA01": {"version": "136.0.0.23403", "status": "healthy"},
                                "STG01": {"version": "136.0.0.23403", "status": "unhealthy", "error": "MinimumReplicas"}
                            }
                        },
                        ...
                    ],
                    "generated_at": "2026-02-11 05:24:43 PM IST"
                }

        Returns:
            List of Slack block elements
        """
        blocks = []

        stacks = data.get("stacks", [])
        deployments = data.get("deployments", [])
        generated_at = data.get("generated_at", datetime.now().strftime("%Y-%m-%d %I:%M:%S %p IST"))

        # Header
        blocks.append(
            {"type": "header", "text": {"type": "plain_text", "text": "🚀 Deployment Version Report", "emoji": True}}
        )

        if not deployments:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "No deployment data available."}})
            return blocks

        # Build table headers: Service | DEPLOYMENT / CONTAINER | Stack1 | Stack2 | ...
        headers = ["Service", "DEPLOYMENT / CONTAINER"] + [s.upper() for s in stacks]

        # Build table rows
        rows = []
        for dep in deployments:
            service = dep.get("service", "")
            deployment_container = dep.get("deployment_container", "")
            versions = dep.get("versions", {})

            row = [service, deployment_container]

            for stack in stacks:
                stack_upper = stack.upper()
                stack_data = versions.get(stack_upper, versions.get(stack, {}))

                if not stack_data:
                    row.append("-")
                    continue

                version = stack_data.get("version", "N/A")
                status = stack_data.get("status", "unknown")
                error = stack_data.get("error", "")

                # Status indicator
                if status == "healthy" or status == "ok":
                    status_icon = "✅"
                    cell_text = f"{version} {status_icon}"
                elif status == "unhealthy" or status == "error":
                    status_icon = "❌"
                    if error:
                        cell_text = f"{version} {status_icon} ({error})"
                    else:
                        cell_text = f"{version} {status_icon}"
                else:
                    cell_text = version

                row.append(cell_text)

            rows.append(row)

        # Build table using native Slack table blocks
        table_blocks = build_table_blocks(
            headers=headers,
            rows=rows,
        )
        blocks.extend(table_blocks)

        # Footer with timestamp
        blocks.append({"type": "divider"})

        # Parse and format the generated_at timestamp
        # Input: "2026-02-11 05:24:43 PM IST"
        # Output: "2026-02-11 05:24:43 PM IST / 2026-02-11 11:54:43 AM GMT"
        try:
            # Try to add GMT equivalent
            from datetime import timedelta, timezone

            ist = timezone(timedelta(hours=5, minutes=30))
            gmt = timezone.utc

            # Parse IST time
            ist_str = generated_at.replace(" IST", "").strip()
            try:
                ist_dt = datetime.strptime(ist_str, "%Y-%m-%d %I:%M:%S %p")
            except ValueError:
                ist_dt = datetime.strptime(ist_str, "%Y-%m-%d %H:%M:%S")

            ist_dt = ist_dt.replace(tzinfo=ist)
            gmt_dt = ist_dt.astimezone(gmt)

            gmt_str = gmt_dt.strftime("%Y-%m-%d %I:%M:%S %p GMT")
            footer_text = f"Generated: {generated_at} / {gmt_str}"
        except Exception:
            footer_text = f"Generated: {generated_at}"

        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer_text}]})

        return blocks

    async def send_deployment_version_report(self, report_data: Dict, channel: str = None) -> Dict:
        """
        Send Deployment Version Report to Slack.

        Args:
            report_data: Dict with stacks, deployments, and generated_at
            channel: Override default channel

        Returns:
            Dict with success status and details
        """
        if not report_data.get("deployments"):
            return {"success": False, "error": "No deployment data to send"}

        blocks = self.build_deployment_version_report_blocks(report_data)
        text = "Deployment Version Report"

        return await self.send_notification(blocks, text, channel)

    def build_regression_action_items_blocks(self, data: Dict) -> tuple:
        """
        Build Slack blocks for regression action items notification (Message 2 layout).

        Shows not-started and blocked items with assignee names from JIRA.

        Args:
            data: Response from /api/jira/regression-tracking/hierarchy endpoint

        Returns:
            Tuple of (header_blocks, table_data_not_started, blocked_blocks)
            - header_blocks: Slack blocks for the header + action summary + blocked items
            - table_data_not_started: Dict with headers/rows for native Slack table (not-started items)
        """
        blocks = []

        parent_epic = data.get("parent_epic", {})
        categories = data.get("categories", {})
        overall_summary = data.get("overall_summary", {})
        release = data.get("release_id", parent_epic.get("key", "Unknown"))

        # Category display labels
        cat_labels = {
            "automation": "Automation",
            "manual": "Manual",
            "non_functional": "NFV",
            "other": "Interop",
        }

        # Collect not-started and blocked items across all categories
        not_started_items = []
        blocked_items = []

        for cat_key, cat_data in categories.items():
            for story in cat_data.get("stories", []):
                status_cat = story.get("status_category", "todo")
                item = {
                    "key": story.get("key", ""),
                    "summary": story.get("summary", ""),
                    "assignee": story.get("assignee") or "Unassigned",
                    "assignee_email": story.get("assignee_email", ""),
                    "category": cat_labels.get(cat_key, cat_key),
                    "status": story.get("status", ""),
                    "url": story.get("url", f"https://your-org.atlassian.net/browse/{story.get('key', '')}"),
                }
                if status_cat == "todo":
                    not_started_items.append(item)
                elif status_cat == "blocked":
                    blocked_items.append(item)

        total = overall_summary.get("total", 0)
        done = overall_summary.get("done", 0)
        in_progress = overall_summary.get("in_progress", 0)
        todo = overall_summary.get("todo", len(not_started_items))
        blocked = overall_summary.get("blocked", len(blocked_items))
        pct = overall_summary.get("completion_percent", 0)

        # ===== HEADER =====
        header_text = f"{release} Regression - Items Needing Attention"
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}})

        # ===== OVERALL CONTEXT =====
        epic_url = parent_epic.get("url", "")
        epic_link = f"<{epic_url}|{parent_epic.get('key', '')}>" if epic_url else parent_epic.get("key", "")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Epic:* {epic_link} - {parent_epic.get('summary', '')}\n"
                        f"*Overall:* {done}/{total} Done · {in_progress} In Progress · {todo} To Do · {blocked} Blocked · *{pct}%* complete"
                    ),
                },
            }
        )

        # ===== ACTION SUMMARY =====
        action_lines = []
        if todo > 0:
            action_lines.append(f":warning:  *{todo} items not started* → Assign and begin work")
        if blocked > 0:
            action_lines.append(f":red_circle:  *{blocked} items blocked* → Escalate blockers")
        if in_progress > 5:
            action_lines.append(f":large_blue_circle:  *{in_progress} items in progress* → Push for completion")
        if pct >= 90 and pct < 100:
            action_lines.append(f":white_check_mark:  *Almost complete ({pct}%)* → Final push!")
        if pct == 100:
            action_lines.append(":tada:  *All items completed!* → Verify and sign off")

        if action_lines:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Action Items:*\n" + "\n".join(action_lines),
                    },
                }
            )

        # ===== NOT STARTED TABLE DATA =====
        # Limit to 20 rows to avoid Slack block size limits
        MAX_TABLE_ROWS = 20
        not_started_table = None
        if not_started_items:
            total_not_started = len(not_started_items)
            display_items = not_started_items[:MAX_TABLE_ROWS]
            extra_count = total_not_started - len(display_items)

            title = f"Not Started ({total_not_started})"
            if extra_count > 0:
                title += f" - showing first {MAX_TABLE_ROWS}"

            not_started_table = {
                "headers": ["Key", "Summary", "Category", "Assignee"],
                "rows": [],
                "title": title,
            }

            for item in display_items:
                key = item["key"]
                url = item["url"]
                summary = item["summary"][:45] + ("..." if len(item["summary"]) > 45 else "")
                category = item["category"]
                assignee = self._get_slack_mention(item["assignee"], item.get("assignee_email", ""))

                not_started_table["rows"].append(
                    [
                        f"<{url}|{key}>",
                        summary,
                        category,
                        assignee,
                    ]
                )

        # ===== BLOCKED ITEMS TABLE DATA =====
        blocked_table = None
        if blocked_items:
            total_blocked = len(blocked_items)
            display_blocked = blocked_items[:MAX_TABLE_ROWS]
            extra_blocked = total_blocked - len(display_blocked)

            title = f"Blocked ({total_blocked})"
            if extra_blocked > 0:
                title += f" - showing first {MAX_TABLE_ROWS}"

            blocked_table = {
                "headers": ["Key", "Summary", "Category", "Assignee"],
                "rows": [],
                "title": title,
            }

            for item in display_blocked:
                key = item["key"]
                url = item["url"]
                summary = item["summary"][:45] + ("..." if len(item["summary"]) > 45 else "")
                category = item["category"]
                assignee = self._get_slack_mention(item["assignee"], item.get("assignee_email", ""))

                blocked_table["rows"].append(
                    [
                        f"<{url}|{key}>",
                        summary,
                        category,
                        assignee,
                    ]
                )

        # ===== FOOTER (CC will be added in send method based on whether blocked table follows) =====
        blocks.append({"type": "divider"})
        now = datetime.now().strftime("%I:%M %p IST · %b %d, %Y")
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Regression Tracking · {now}"}],
            }
        )

        return blocks, not_started_table, blocked_table

    async def send_regression_action_items(self, regression_data: Dict, channel: str = None) -> Dict:
        """
        Send regression action items notification to Slack.

        Sends messages with not-started and blocked items including assignee names.
        Uses native Slack tables for both lists (sent as separate messages due to Slack's
        one-table-per-message limitation).

        Args:
            regression_data: Response from /api/jira/regression-tracking/hierarchy
            channel: Override default channel

        Returns:
            Dict with success status and details
        """
        release_id = regression_data.get("release_id", "Unknown")
        logger.info("Building regression action items notification for %s", release_id)

        blocks, not_started_table, blocked_table = self.build_regression_action_items_blocks(regression_data)

        not_started_count = len(not_started_table["rows"]) if not_started_table else 0
        blocked_count = len(blocked_table["rows"]) if blocked_table else 0
        has_blocked_message = blocked_table and blocked_table.get("rows")

        # === MESSAGE 1: Main message + Not Started Table ===
        if not_started_table and not_started_table.get("rows"):
            table_blocks = build_table_blocks(
                headers=not_started_table["headers"],
                rows=not_started_table["rows"],
                title=not_started_table.get("title", "Not Started"),
            )
            blocks = blocks[:3] + table_blocks + blocks[3:]  # Insert table after action summary

        # Add CC only if this is the last message (no blocked table to follow)
        if not has_blocked_message:
            blocks.append(_build_cc_block(self))

        text = f"Regression Action Items - {release_id}"
        result = await self.send_notification(blocks=blocks, text=text, channel=channel)

        if result.get("success"):
            result["not_started_count"] = not_started_count
            logger.info(
                "Sent regression action items for %s: %d not-started items",
                release_id,
                not_started_count,
            )

            # === MESSAGE 2: Blocked Items Table (separate message with CC) ===
            if has_blocked_message:
                blocked_blocks = build_table_blocks(
                    headers=blocked_table["headers"],
                    rows=blocked_table["rows"],
                    title=f"{release_id} - {blocked_table.get('title', 'Blocked')}",
                )
                blocked_blocks.append({"type": "divider"})
                blocked_blocks.append(_build_cc_block(self))

                blocked_result = await self.send_notification(
                    blocks=blocked_blocks,
                    text=f"Blocked Items - {release_id}",
                    channel=channel,
                )
                if blocked_result.get("success"):
                    result["blocked_sent"] = True
                    result["blocked_count"] = blocked_count
                    logger.info("Sent blocked items table with %d items", blocked_count)

        return result

    def build_regression_status_tables(self, data: Dict) -> Dict:
        """
        Build grouped table data for regression status notification.

        Creates two tables:
        1. Status by Category - shows each category with status breakdown
        2. Workload by Assignee - shows each assignee with category + status breakdown

        All numbers are clickable JIRA links.

        Args:
            data: Response from /api/jira/regression-tracking/hierarchy endpoint

        Returns:
            Dict with header_info, category_table, and assignee_table
        """
        from urllib.parse import quote

        parent_epic = data.get("parent_epic", {})
        categories = data.get("categories", {})
        overall_summary = data.get("overall_summary", {})
        release = data.get("release_id", parent_epic.get("key", "Unknown"))

        # Category configuration - order and display names
        category_config = [
            ("manual", "Func Val", "Functional Validation - Manual"),
            ("non_functional", "Non-Func", "Non Functional Validation"),
            ("other", "Interop", "Interop Validation"),
            ("automation", "Auto Reg", "Automated Release Regressions"),
        ]

        # Build header info
        total = overall_summary.get("total", 0)
        done = overall_summary.get("done", 0)
        in_progress = overall_summary.get("in_progress", 0)
        todo = overall_summary.get("todo", 0)
        blocked = overall_summary.get("blocked", 0)
        pct = overall_summary.get("completion_percent", 0)

        header_info = {
            "release": release,
            "epic_key": parent_epic.get("key", ""),
            "epic_summary": parent_epic.get("summary", ""),
            "epic_url": parent_epic.get("url", ""),
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "todo": todo,
            "blocked": blocked,
            "completion_percent": pct,
        }

        # Helper to build JIRA search URL from issue keys
        def build_jira_link(keys: list, count: int) -> str:
            if count == 0 or not keys:
                return "-"
            jql = f"key in ({','.join(keys)})"
            url = f"https://your-org.atlassian.net/issues/?jql={quote(jql)}"
            return f"<{url}|{count}>"

        # =================================================================
        # TABLE 1: Status by Category
        # Columns: Category | Blocked | To Do | In Prog | Done | Total
        # =================================================================
        category_rows = []
        category_totals = {"blocked": 0, "todo": 0, "in_progress": 0, "done": 0, "total": 0}
        all_keys_by_status = {"blocked": [], "todo": [], "in_progress": [], "done": [], "all": []}

        for cat_key, cat_short, cat_full in category_config:
            cat_data = categories.get(cat_key, {})
            stories = cat_data.get("stories", [])

            if not stories:
                continue

            # Collect keys by status for this category
            cat_keys = {"blocked": [], "todo": [], "in_progress": [], "done": [], "all": []}
            for story in stories:
                key = story.get("key", "")
                status_cat = story.get("status_category", "todo")
                cat_keys[status_cat].append(key)
                cat_keys["all"].append(key)
                all_keys_by_status[status_cat].append(key)
                all_keys_by_status["all"].append(key)

            # Build row with clickable links
            category_rows.append(
                [
                    cat_full,
                    build_jira_link(cat_keys["blocked"], len(cat_keys["blocked"])),
                    build_jira_link(cat_keys["todo"], len(cat_keys["todo"])),
                    build_jira_link(cat_keys["in_progress"], len(cat_keys["in_progress"])),
                    build_jira_link(cat_keys["done"], len(cat_keys["done"])),
                    build_jira_link(cat_keys["all"], len(cat_keys["all"])),
                ]
            )

            # Update totals
            category_totals["blocked"] += len(cat_keys["blocked"])
            category_totals["todo"] += len(cat_keys["todo"])
            category_totals["in_progress"] += len(cat_keys["in_progress"])
            category_totals["done"] += len(cat_keys["done"])
            category_totals["total"] += len(cat_keys["all"])

        # Add totals row
        if category_rows:
            category_rows.append(
                [
                    "Total",
                    build_jira_link(all_keys_by_status["blocked"], category_totals["blocked"]),
                    build_jira_link(all_keys_by_status["todo"], category_totals["todo"]),
                    build_jira_link(all_keys_by_status["in_progress"], category_totals["in_progress"]),
                    build_jira_link(all_keys_by_status["done"], category_totals["done"]),
                    build_jira_link(all_keys_by_status["all"], category_totals["total"]),
                ]
            )

        category_table = {
            "title": "Status by Category",
            "headers": ["Category", "Blocked", "To Do", "In Prog", "Done", "Total"],
            "rows": category_rows,
        }

        # =================================================================
        # TABLE 2: Workload by Assignee
        # Columns: Assignee | Func Val | Non-Func | Interop | Auto Reg | Blocked | To Do | In Prog | Done | Total
        # =================================================================
        # Build assignee data structure: assignee -> {category -> keys, status -> keys}
        assignee_data = {}

        for cat_key, cat_short, cat_full in category_config:
            cat_data = categories.get(cat_key, {})
            stories = cat_data.get("stories", [])

            for story in stories:
                assignee_name = story.get("assignee") or "Unassigned"
                assignee_email = story.get("assignee_email", "")
                key = story.get("key", "")
                status_cat = story.get("status_category", "todo")

                if assignee_name not in assignee_data:
                    assignee_data[assignee_name] = {
                        "email": assignee_email,
                        "categories": {c[0]: [] for c in category_config},
                        "statuses": {"blocked": [], "todo": [], "in_progress": [], "done": []},
                        "all_keys": [],
                    }

                assignee_data[assignee_name]["categories"][cat_key].append(key)
                assignee_data[assignee_name]["statuses"][status_cat].append(key)
                assignee_data[assignee_name]["all_keys"].append(key)

        # Build assignee rows sorted by total (descending)
        assignee_rows = []
        assignee_totals = {
            "categories": {c[0]: [] for c in category_config},
            "statuses": {"blocked": [], "todo": [], "in_progress": [], "done": []},
            "all_keys": [],
        }

        sorted_assignees = sorted(assignee_data.items(), key=lambda x: len(x[1]["all_keys"]), reverse=True)

        for assignee_name, data in sorted_assignees:
            slack_mention = self._get_slack_mention(assignee_name, data.get("email", ""))

            row = [slack_mention]

            # Add category columns
            for cat_key, cat_short, cat_full in category_config:
                keys = data["categories"][cat_key]
                row.append(build_jira_link(keys, len(keys)))
                assignee_totals["categories"][cat_key].extend(keys)

            # Add status columns
            for status in ["blocked", "todo", "in_progress", "done"]:
                keys = data["statuses"][status]
                row.append(build_jira_link(keys, len(keys)))
                assignee_totals["statuses"][status].extend(keys)

            # Add total column
            row.append(build_jira_link(data["all_keys"], len(data["all_keys"])))
            assignee_totals["all_keys"].extend(data["all_keys"])

            assignee_rows.append(row)

        # Add totals row
        if assignee_rows:
            totals_row = ["Total"]

            # Category totals
            for cat_key, cat_short, cat_full in category_config:
                keys = assignee_totals["categories"][cat_key]
                totals_row.append(build_jira_link(keys, len(keys)))

            # Status totals
            for status in ["blocked", "todo", "in_progress", "done"]:
                keys = assignee_totals["statuses"][status]
                totals_row.append(build_jira_link(keys, len(keys)))

            # Grand total
            totals_row.append(build_jira_link(assignee_totals["all_keys"], len(assignee_totals["all_keys"])))

            assignee_rows.append(totals_row)

        assignee_table = {
            "title": "Workload by Assignee",
            "headers": [
                "Assignee",
                "Func Val",
                "Non-Func",
                "Interop",
                "Auto Reg",
                "Blocked",
                "To Do",
                "In Prog",
                "Done",
                "Total",
            ],
            "rows": assignee_rows,
        }

        return {
            "header_info": header_info,
            "category_table": category_table,
            "assignee_table": assignee_table,
        }

    async def send_regression_status(self, regression_data: Dict, channel: str = None) -> Dict:
        """
        Send regression status notification to Slack (2 messages).

        Message 1: Header + Status by Category table
        Message 2: Workload by Assignee table (with category + status breakdown)

        All numbers are clickable JIRA links.

        Args:
            regression_data: Response from /api/jira/regression-tracking/hierarchy
            channel: Override channel (defaults to REGRESSION_SLACK_CHANNEL)

        Returns:
            Dict with success status and message counts
        """
        # Use dedicated regression channel if not overridden
        target_channel = channel or REGRESSION_SLACK_CHANNEL

        release_id = regression_data.get("release_id", "Unknown")
        logger.info("Building regression status notification for %s", release_id)

        # Build grouped table data
        table_data = self.build_regression_status_tables(regression_data)
        header_info = table_data["header_info"]
        category_table = table_data["category_table"]
        assignee_table = table_data["assignee_table"]

        if not category_table.get("rows") and not assignee_table.get("rows"):
            return {"success": False, "error": "No regression data to send"}

        results = {
            "success": True,
            "messages_sent": 0,
            "tables": [],
        }

        # =================================================================
        # MESSAGE 1: Header + Status by Category
        # =================================================================
        blocks = []

        # Header
        today_date = datetime.now().strftime("%B %d").replace(" 0", " ")
        header_text = f"{header_info['release']} Release Regression Status as of {today_date}"
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}})

        # Epic and overall summary with emoji indicators
        epic_url = header_info.get("epic_url", "")
        epic_key = header_info.get("epic_key", "")
        epic_link = f"<{epic_url}|{epic_key}>" if epic_url else epic_key

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Epic:* {epic_link}\n"
                        f"*Overall:* {header_info['done']}/{header_info['total']} Done · "
                        f"{header_info['in_progress']} In Progress · "
                        f"{header_info['todo']} To Do · "
                        f"{header_info['blocked']} Blocked"
                    ),
                },
            }
        )
        blocks.append({"type": "divider"})

        # Category table
        if category_table.get("rows"):
            table_blocks = build_table_blocks(
                headers=category_table["headers"],
                rows=category_table["rows"],
                title=category_table["title"],
            )
            blocks.extend(table_blocks)

        text = f"{header_info['release']} - Status by Category"
        result = await self.send_notification(blocks=blocks, text=text, channel=target_channel)

        if result.get("success"):
            results["messages_sent"] += 1
            results["tables"].append(
                {
                    "title": category_table["title"],
                    "rows": len(category_table.get("rows", [])),
                }
            )
            logger.info("Sent category table: %d rows", len(category_table.get("rows", [])))
        else:
            logger.error("Failed to send category table: %s", result.get("error"))
            results["success"] = False
            results["error"] = result.get("error")
            return results

        # =================================================================
        # MESSAGE 2: Workload by Assignee
        # =================================================================
        blocks = []

        # Assignee table
        if assignee_table.get("rows"):
            table_blocks = build_table_blocks(
                headers=assignee_table["headers"],
                rows=assignee_table["rows"],
                title=assignee_table["title"],
            )
            blocks.extend(table_blocks)

        # Footer with CC and timestamp
        blocks.append({"type": "divider"})
        blocks.append(_build_regression_cc_block(self))
        now = datetime.now().strftime("%I:%M %p IST · %b %d, %Y")
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Regression Tracking · {now}"}],
            }
        )

        text = f"{header_info['release']} - Workload by Assignee"
        result = await self.send_notification(blocks=blocks, text=text, channel=target_channel)

        if result.get("success"):
            results["messages_sent"] += 1
            results["tables"].append(
                {
                    "title": assignee_table["title"],
                    "rows": len(assignee_table.get("rows", [])),
                }
            )
            logger.info("Sent assignee table: %d rows", len(assignee_table.get("rows", [])))
        else:
            logger.error("Failed to send assignee table: %s", result.get("error"))
            results["success"] = False
            results["error"] = result.get("error")

        logger.info("Regression status notification complete: %d messages sent", results["messages_sent"])

        return results

    async def send_stack_alert(self, alerts: List[Dict], channel: str = None) -> Dict:
        """
        Send stack monitoring alert to Slack.

        Args:
            alerts: List of alert dicts (see build_stack_alert_blocks for format)
            channel: Override default channel

        Returns:
            Dict with success status and details
        """
        if not alerts:
            return {"success": False, "error": "No alerts to send"}

        blocks = self.build_stack_alert_blocks(alerts)
        text = f"Stack Monitoring: {len(alerts)} Alert(s)"

        return await self.send_notification(blocks, text, channel)

    def build_pdv_milestone_blocks(self, data: Dict) -> List[Dict]:
        """
        Build Slack blocks for PDV milestone status notification.

        Args:
            data: PDV milestone status from /api/pdv/milestone-status/{release}
                {
                    "release_id": "R136",
                    "version": "136.0",
                    "milestones": {
                        "prod_day1": {"status": "SUCCESS", "completion_percent": 100, "summary": {...}},
                        "prod_day2": {"status": "IN_PROGRESS", "completion_percent": 75, ...},
                        ...
                    }
                }

        Returns:
            List of Slack block dicts
        """
        blocks = []
        release_id = data.get("release_id", "Release")
        milestones = data.get("milestones", {})

        status_emoji = {
            "SUCCESS": "white_check_mark",
            "FAILURE": "x",
            "IN_PROGRESS": "arrows_counterclockwise",
            "PENDING": "hourglass",
            "TODO": "grey_question",
            "NOT_CONFIGURED": "construction",
        }

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{release_id} PDV Milestone Status", "emoji": True},
            }
        )

        # Day order for display
        day_order = [
            ("staging", "Staging"),
            ("preprod_day1", "Pre-Prod Day 1"),
            ("preprod_day2", "Pre-Prod Day 2"),
            ("prod_day1", "Prod Day 1"),
            ("prod_day2", "Prod Day 2"),
            ("prod_day3", "Prod Day 3"),
            ("prod_day4", "Prod Day 4"),
        ]

        # Build summary table
        headers = ["Day", "Status", "Progress", "Pass", "Fail"]
        rows = []

        for key, label in day_order:
            if key in milestones:
                m = milestones[key]
                status = m.get("status", "TODO")
                pct = m.get("completion_percent", 0)
                summary = m.get("summary", {})
                success = summary.get("success", 0)
                failure = summary.get("failure", 0)

                emoji = status_emoji.get(status, "grey_question")
                status_text = f":{emoji}: {status}"

                if status == "NOT_CONFIGURED":
                    rows.append([label, ":construction: N/A", "-", "-", "-"])
                else:
                    rows.append([label, status_text, f"{pct:.0f}%", str(success), str(failure) if failure > 0 else "0"])

        # Add table
        table_block = build_table_blocks(headers, rows, f"{release_id} Deployment Status")
        blocks.extend(table_block)

        # Add failures section if any
        total_failures = sum(m.get("failures_count", 0) for m in milestones.values())
        if total_failures > 0:
            failure_text = f":warning: *{total_failures} PDV failure(s) detected.* Check Insights Platform for details."
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": failure_text}})

        # Footer
        fetched_at = data.get("fetched_at", "")
        if fetched_at:
            try:
                dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                formatted = dt.strftime("%b %d, %Y %I:%M %p UTC")
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Updated: {formatted}"}]})
            except Exception:
                pass

        return blocks

    async def send_pdv_milestone_notification(
        self,
        data: Dict,
        channel: str = None,
        notify_on_failure: bool = True,
        cc_slack_ids: List[str] = None,
    ) -> Dict:
        """
        Send PDV milestone status notification to Slack.

        Args:
            data: PDV milestone status data
            channel: Override default channel
            notify_on_failure: Include @mentions when failures detected
            cc_slack_ids: Optional list of Slack user IDs to CC

        Returns:
            Dict with success status
        """
        blocks = self.build_pdv_milestone_blocks(data)
        release_id = data.get("release_id", "Release")

        # Check for failures
        milestones = data.get("milestones", {})
        total_failures = sum(m.get("failures_count", 0) for m in milestones.values())
        has_failure_status = any(m.get("status") == "FAILURE" for m in milestones.values())

        # Add CC block if needed
        if notify_on_failure and (total_failures > 0 or has_failure_status):
            mention_ids = cc_slack_ids or []
            if mention_ids:
                mentions = " ".join(f"<@{uid}>" for uid in mention_ids)
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":rotating_light: {mentions}"}})

        text = (
            f"{release_id} PDV Status: {total_failures} failure(s)"
            if total_failures > 0
            else f"{release_id} PDV Status Update"
        )

        return await self.send_notification(blocks, text, channel)

    def build_pdv_event_blocks(self, events: List[Dict], release_id: str = None) -> List[Dict]:
        """
        Build compact Slack blocks for PDV status change events.

        Creates a simple, scannable format like:
            R136 Prod Day 1 PDV Updates
            • SJC1 - Deployment complete (v136.0.0.123)
            • SV5 - PDV in progress
            • FRA2 - PDV 2 tests failed

        Args:
            events: List of change events from PDVClient.detect_status_changes()
            release_id: Release identifier (e.g., "R136")

        Returns:
            List of Slack block dicts
        """
        blocks = []

        if not events:
            return blocks

        # Group events by day
        by_day = {}
        for event in events:
            day = event.get("day", "Unknown")
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(event)

        # Build header
        release_str = f"{release_id} " if release_id else ""
        header_text = f"{release_str}PDV Status Update"

        blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}})

        # Build event list by day
        for day, day_events in by_day.items():
            day_title = day.replace("prod ", "Prod ").replace("preprod ", "PreProd ").title()

            # Day subheader
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{day_title}*"}})

            # Build bullet list of events
            lines = []

            for event in day_events:
                msg = event.get("message", "")
                new_status = event.get("new_status", "").upper()

                # Add emoji based on status
                if new_status == "FAILURE":
                    emoji = ":x:"
                elif new_status == "SUCCESS":
                    emoji = ":white_check_mark:"
                elif new_status in ("IN_PROGRESS", "RUNNING"):
                    emoji = ":arrows_counterclockwise:"
                elif new_status == "DEPLOYED":
                    emoji = ":rocket:"
                else:
                    emoji = ":grey_question:"

                lines.append(f"{emoji} {msg}")

            if lines:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

        # Timestamp
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Updated: {datetime.now().strftime('%b %d, %I:%M %p')}"}],
            }
        )

        return blocks

    async def send_pdv_event_notification(
        self,
        events: List[Dict],
        release_id: str = None,
        channel: str = None,
    ) -> Dict:
        """
        Send compact PDV status change notification to Slack.

        Args:
            events: List of change events from PDVClient.detect_status_changes()
            release_id: Release identifier (e.g., "R136")
            channel: Slack channel (defaults to PDV_SLACK_CHANNEL or YOUR_SLACK_CHANNEL_ID)

        Returns:
            Dict with success status
        """
        if not events:
            return {"success": True, "message": "No events to send", "events_count": 0}

        blocks = self.build_pdv_event_blocks(events, release_id)

        # Check for failures
        has_failures = any(e.get("new_status", "").upper() == "FAILURE" for e in events)

        # Build text summary
        release_str = f"{release_id} " if release_id else ""
        if has_failures:
            fail_count = sum(1 for e in events if e.get("new_status", "").upper() == "FAILURE")
            text = f":x: {release_str}PDV Alert: {fail_count} failure(s)"
        else:
            text = f"{release_str}PDV Status Update ({len(events)} change(s))"

        # Default to PDV channel
        target_channel = channel or os.getenv("PDV_SLACK_CHANNEL", "YOUR_SLACK_CHANNEL_ID")

        result = await self.send_notification(blocks, text, target_channel)
        result["events_count"] = len(events)

        return result


# Singleton instance
_slack_service: Optional[SlackNotificationService] = None


def get_slack_service(bot_token: str = None, channel: str = None) -> SlackNotificationService:
    """Get or create Slack notification service instance."""
    global _slack_service

    if bot_token or channel:
        # Create new instance with custom config
        return SlackNotificationService(bot_token, channel)

    # Always create fresh instance to pick up defaults
    if _slack_service is None or not _slack_service.enabled:
        _slack_service = SlackNotificationService()

    return _slack_service


async def send_release_readiness_notification(
    release_data: Dict,
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Convenience function to send release readiness notification.

    Args:
        release_data: Data from release readiness API
        bot_token: Optional custom bot token
        channel: Optional custom channel

    Returns:
        Dict with success status
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_release_readiness_notification(release_data, channel)


async def send_stack_alert_notification(
    alerts: List[Dict],
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Convenience function to send stack monitoring alert notification.

    Args:
        alerts: List of alert dicts with keys:
            - stack: Stack name (e.g., "PROD01")
            - severity: "critical", "warning", or "info"
            - message: Alert message
            - time: Timestamp string
            - region: Optional region name
            - health_percent: Optional health percentage
        bot_token: Optional custom bot token
        channel: Optional custom channel

    Returns:
        Dict with success status
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_stack_alert(alerts, channel)


async def send_deployment_version_report_notification(
    report_data: Dict,
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Convenience function to send Deployment Version Report notification.

    Args:
        report_data: Dict with structure:
            {
                "stacks": ["QA01", "STG01", ...],
                "deployments": [
                    {
                        "service": "addonman",
                        "deployment_container": "addonman-addonman/addonman",
                        "versions": {
                            "QA01": {"version": "136.0.0.23403", "status": "healthy"},
                            ...
                        }
                    },
                    ...
                ],
                "generated_at": "2026-02-11 05:24:43 PM IST"
            }
        bot_token: Optional custom bot token
        channel: Optional custom channel

    Returns:
        Dict with success status
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_deployment_version_report(report_data, channel)


async def send_regression_action_items_notification(
    regression_data: Dict,
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Convenience function to send regression action items notification.

    Args:
        regression_data: Response from /api/jira/regression-tracking/hierarchy
        bot_token: Optional custom bot token
        channel: Optional custom channel

    Returns:
        Dict with success status
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_regression_action_items(regression_data, channel)


async def send_regression_status_notification(
    regression_data: Dict,
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Convenience function to send regression status notification (4 category tables).

    Sends 4 Slack messages to the dedicated regression channel (YOUR_SLACK_CHANNEL_ID):
    1. Functional Validation - Manual
    2. Non Functional Validation
    3. Interop Validation
    4. Automated Release Regressions (with CC and footer)

    Args:
        regression_data: Response from /api/jira/regression-tracking/hierarchy
        bot_token: Optional custom bot token
        channel: Optional custom channel (defaults to REGRESSION_SLACK_CHANNEL)

    Returns:
        Dict with success status and message counts
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_regression_status(regression_data, channel)


async def send_pdv_milestone_notification(
    pdv_data: Dict,
    bot_token: str = None,
    channel: str = None,
    notify_on_failure: bool = True,
    cc_slack_ids: List[str] = None,
) -> Dict:
    """
    Convenience function to send PDV milestone status notification.

    Args:
        pdv_data: PDV milestone status from /api/pdv/milestone-status/{release}
            {
                "release_id": "R136",
                "version": "136.0",
                "milestones": {
                    "staging": {"status": "SUCCESS", "completion_percent": 100, ...},
                    "prod_day1": {"status": "IN_PROGRESS", ...},
                    ...
                }
            }
        bot_token: Optional custom bot token
        channel: Optional custom channel
        notify_on_failure: Include @mentions when failures detected (default True)
        cc_slack_ids: Optional list of Slack user IDs to CC on failures

    Returns:
        Dict with success status

    Example:
        from services.slack_notifications import send_pdv_milestone_notification

        pdv_data = await api.get("/api/pdv/milestone-status/R136")
        await send_pdv_milestone_notification(
            pdv_data,
            channel="YOUR_SLACK_CHANNEL_ID",
            cc_slack_ids=["U04J2GPMW5A"],  # @release-team
        )
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_pdv_milestone_notification(pdv_data, channel, notify_on_failure, cc_slack_ids)


async def send_pdv_event_notification(
    events: List[Dict],
    release_id: str = None,
    bot_token: str = None,
    channel: str = None,
) -> Dict:
    """
    Send compact PDV status change notification to Slack.

    Use this for real-time event-driven notifications when PDV or deployment
    status changes. Creates simple, scannable messages like:
        • SJC1 - Deployment complete (v136.0.0.123)
        • SV5 - PDV in progress
        • FRA2 - PDV 2 tests failed

    Args:
        events: List of change events from PDVClient.detect_status_changes()
            Each event has: type, day, datacenter, old_status, new_status, message
        release_id: Release identifier (e.g., "R136")
        bot_token: Optional custom bot token
        channel: Slack channel (defaults to YOUR_SLACK_CHANNEL_ID)

    Returns:
        Dict with success status and events_count

    Example:
        from services.pdv_client import get_pdv_client
        from services.slack_notifications import send_pdv_event_notification

        client = get_pdv_client()
        events = client.detect_status_changes("136.0")
        if events:
            await send_pdv_event_notification(events, release_id="R136")
    """
    service = get_slack_service(bot_token, channel)
    return await service.send_pdv_event_notification(events, release_id, channel)


# =============================================================================
# Generic Reusable Notification Functions
# =============================================================================
# These functions can be used by any dashboard section to send Slack notifications
# without writing custom Slack code each time.


async def send_table_notification(
    title: str,
    headers: List[str],
    rows: List[List[str]],
    channel: str,
    subtitle: str = None,
    footer: str = None,
    cc_slack_ids: List[str] = None,
    bot_token: str = None,
) -> Dict:
    """
    Generic function to send a table-based Slack notification.

    This is the simplest way to send a table from any dashboard section.

    Args:
        title: Header title for the message (e.g., "R135 Test Health Report")
        headers: List of column headers (e.g., ["Key", "Summary", "Assignee", "Status"])
        rows: List of rows, each row is a list of cell values
              For links, use Slack format: "<url|text>"
        channel: Slack channel ID to send to
        subtitle: Optional subtitle/description text (markdown supported)
        footer: Optional footer text (e.g., timestamp)
        cc_slack_ids: Optional list of Slack user IDs to CC (e.g., ["U04J2GPMW5A"])
        bot_token: Optional custom bot token

    Returns:
        Dict with success status and message details

    Example:
        await send_table_notification(
            title="R135 Release Regression Status",
            headers=["Key", "Test Scenario", "Assignee", "Status"],
            rows=[
                ["<https://jira.com/ENG-123|ENG-123>", "Windows automation...", "John D.", "Done"],
                ["<https://jira.com/ENG-124|ENG-124>", "Mac validation...", "Jane S.", "In Progress"],
            ],
            channel="YOUR_SLACK_CHANNEL_ID",
            subtitle="*Overall:* 45/50 Done · 90% complete",
            cc_slack_ids=["U04J2GPMW5A", "U02NU1432CD"],
        )
    """
    service = get_slack_service(bot_token)

    blocks = []

    # Header
    blocks.append({"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}})

    # Subtitle
    if subtitle:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": subtitle}})

    # Table
    if rows:
        table_blocks = build_table_blocks(headers=headers, rows=rows)
        blocks.extend(table_blocks)

    # Divider before footer
    if footer or cc_slack_ids:
        blocks.append({"type": "divider"})

    # CC mentions
    if cc_slack_ids:
        mentions = [f"<@{uid}>" for uid in cc_slack_ids]
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "cc: " + "  ".join(mentions)}]})

    # Footer
    if footer:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    else:
        # Default timestamp footer
        now = datetime.now().strftime("%I:%M %p IST · %b %d, %Y")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": now}]})

    return await service.send_notification(blocks=blocks, text=title, channel=channel)


async def send_multi_table_notification(
    title: str,
    tables: List[Dict],
    channel: str,
    subtitle: str = None,
    cc_slack_ids: List[str] = None,
    bot_token: str = None,
) -> Dict:
    """
    Send multiple tables as separate Slack messages (due to Slack's 1 table per message limit).

    Args:
        title: Header title (shown on first message only)
        tables: List of table dicts, each with:
            - "title": Table title (e.g., "Functional Validation - Manual (25/30 Done)")
            - "headers": List of column headers
            - "rows": List of rows
        channel: Slack channel ID
        subtitle: Optional subtitle (shown on first message only)
        cc_slack_ids: Optional list of Slack user IDs to CC (shown on last message only)
        bot_token: Optional custom bot token

    Returns:
        Dict with success status and message counts

    Example:
        await send_multi_table_notification(
            title="R135 Release Regression Status",
            tables=[
                {
                    "title": "Manual Validation (25/30 Done · 83%)",
                    "headers": ["Key", "Scenario", "Assignee", "Status"],
                    "rows": [["ENG-123", "iOS test...", "John", "Done"], ...]
                },
                {
                    "title": "Automation (40/50 Done · 80%)",
                    "headers": ["Key", "Scenario", "Assignee", "Status"],
                    "rows": [["ENG-456", "Backend...", "Jane", "Progress"], ...]
                },
            ],
            channel="YOUR_SLACK_CHANNEL_ID",
            subtitle="*Overall:* 65/80 Done · 81% complete",
            cc_slack_ids=["U04J2GPMW5A", "U02NU1432CD"],
        )
    """
    service = get_slack_service(bot_token)

    if not tables:
        return {"success": False, "error": "No tables provided"}

    results = {
        "success": True,
        "messages_sent": 0,
        "tables": [],
    }

    total_tables = len(tables)

    for idx, table in enumerate(tables):
        is_first = idx == 0
        is_last = idx == total_tables - 1

        blocks = []

        # Header and subtitle on first message only
        if is_first:
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}})
            if subtitle:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": subtitle}})
                blocks.append({"type": "divider"})

        # Table
        table_blocks = build_table_blocks(
            headers=table.get("headers", []),
            rows=table.get("rows", []),
            title=table.get("title"),
        )
        blocks.extend(table_blocks)

        # CC and footer on last message only
        if is_last:
            blocks.append({"type": "divider"})
            if cc_slack_ids:
                mentions = [f"<@{uid}>" for uid in cc_slack_ids]
                blocks.append(
                    {"type": "context", "elements": [{"type": "mrkdwn", "text": "cc: " + "  ".join(mentions)}]}
                )
            now = datetime.now().strftime("%I:%M %p IST · %b %d, %Y")
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": now}]})

        # Send message
        text = f"{title} - {table.get('title', f'Table {idx + 1}')}"
        result = await service.send_notification(blocks=blocks, text=text, channel=channel)

        if result.get("success"):
            results["messages_sent"] += 1
            results["tables"].append(table.get("title", f"Table {idx + 1}"))
        else:
            results["success"] = False
            results["error"] = result.get("error")

    return results


def format_jira_link(key: str, base_url: str = "https://your-org.atlassian.net/browse") -> str:
    """
    Format a JIRA key as a Slack clickable link.

    Args:
        key: JIRA issue key (e.g., "ENG-12345")
        base_url: JIRA base URL

    Returns:
        Slack-formatted link: "<url|key>"

    Example:
        format_jira_link("ENG-12345")  # Returns "<https://your-org.atlassian.net/browse/ENG-12345|ENG-12345>"
    """
    return f"<{base_url}/{key}|{key}>"


def get_status_display(status_category: str) -> str:
    """
    Get display text for a status category.

    Args:
        status_category: One of "done", "in_progress", "todo", "blocked"

    Returns:
        Human-readable status text
    """
    return {
        "done": "Done",
        "in_progress": "In Progress",
        "todo": "To Do",
        "blocked": "Blocked",
    }.get(status_category, status_category or "To Do")

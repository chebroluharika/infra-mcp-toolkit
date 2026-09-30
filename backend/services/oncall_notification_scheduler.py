"""
On-Call Notification Scheduler
==============================

Sends Slack reminders to on-call personnel 3-4 days before their rotation starts.
This helps team members plan better for their upcoming on-call duties.

Features:
- Sends reminders to upcoming on-call engineers via direct Slack message
- Configurable reminder days (default: 4 days before rotation)
- Daily check at configurable time (default: 9:00 AM IST)
- Supports all schedule types: primary (engineers), managers, backend
- Tracks sent notifications to avoid duplicates

Configuration:
- ONCALL_REMINDER_DAYS: Number of days before rotation to send reminder (default: 4)
- ONCALL_REMINDER_TIME: Time to check and send reminders (default: "09:00")
- ONCALL_REMINDER_ENABLED: Enable/disable the scheduler (default: true)
- ONCALL_REMINDER_CHANNEL: Fallback channel for notifications (optional)
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Constants
# =============================================================================

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "oncall_notification_state.json"

DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_REMINDER_DAYS = 4  # Send reminder 4 days before rotation
DEFAULT_REMINDER_TIME = "09:00"  # 9 AM IST

REMINDER_ENABLED = os.getenv("ONCALL_REMINDER_ENABLED", "true").lower() == "true"
REMINDER_DAYS = int(os.getenv("ONCALL_REMINDER_DAYS", str(DEFAULT_REMINDER_DAYS)))
REMINDER_TIME = os.getenv("ONCALL_REMINDER_TIME", DEFAULT_REMINDER_TIME)
FALLBACK_CHANNEL = os.getenv("ONCALL_REMINDER_CHANNEL", "")

# =============================================================================
# Scheduler State (module-level)
# =============================================================================

_scheduler_running = False
_scheduler_thread: Optional[threading.Thread] = None
_sent_notifications: Dict[str, str] = {}  # key: "week_start:person_email", value: ISO timestamp
_state_loaded = False


# =============================================================================
# State Persistence
# =============================================================================


def _load_state() -> Dict[str, Any]:
    """Load scheduler state from disk."""
    global _sent_notifications, _state_loaded

    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

            _sent_notifications = state.get("sent_notifications", {})
            _state_loaded = True

            # Clean up old entries (older than 30 days)
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            _sent_notifications = {k: v for k, v in _sent_notifications.items() if v > cutoff}

            logger.info(
                "Loaded on-call notification state: %d tracked notifications",
                len(_sent_notifications),
            )
            return state
        else:
            logger.info("No on-call notification state file found - starting fresh")
    except Exception as e:
        logger.warning("Could not load on-call notification state: %s", e)

    _state_loaded = True
    return {}


def _save_state():
    """Save scheduler state to disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "sent_notifications": _sent_notifications,
            "updated_at": datetime.now().isoformat(),
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

        logger.debug("Saved on-call notification state")
    except Exception as e:
        logger.error("Could not save on-call notification state: %s", e)


def _notification_key(week_start: str, email: str, schedule_type: str) -> str:
    """Generate a unique key for tracking sent notifications."""
    return f"{schedule_type}:{week_start}:{email}"


def _was_notification_sent(week_start: str, email: str, schedule_type: str) -> bool:
    """Check if notification was already sent for this rotation."""
    key = _notification_key(week_start, email, schedule_type)
    return key in _sent_notifications


def _mark_notification_sent(week_start: str, email: str, schedule_type: str):
    """Mark notification as sent."""
    key = _notification_key(week_start, email, schedule_type)
    _sent_notifications[key] = datetime.now().isoformat()
    _save_state()


# =============================================================================
# Time Helpers
# =============================================================================


def _get_timezone() -> pytz.BaseTzInfo:
    """Get configured timezone."""
    return pytz.timezone(DEFAULT_TIMEZONE)


def _get_current_time() -> datetime:
    """Get current time in configured timezone."""
    return datetime.now(_get_timezone())


def _parse_reminder_time() -> tuple:
    """Parse reminder time string into (hour, minute) tuple."""
    try:
        parts = REMINDER_TIME.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return (hour, minute)
    except (ValueError, IndexError):
        logger.warning("Invalid ONCALL_REMINDER_TIME format: %s, using default", REMINDER_TIME)
        return (9, 0)


# =============================================================================
# On-Call Data Fetching
# =============================================================================


async def _get_upcoming_oncall(days_ahead: int = 4) -> List[Dict[str, Any]]:
    """
    Get list of people who will be on-call in the specified number of days.

    Returns list of dicts with:
    - name: Display name
    - email: Email address
    - slack: Slack username (without @)
    - week_start: Start date of their rotation
    - week_end: End date of their rotation
    - region: Region ID (IST, TW, US, ALL)
    - schedule_type: primary, managers, or backend
    - schedule_name: Display name of the schedule
    """
    from services.opsgenie_client import SCHEDULE_TYPES, get_all_schedules

    upcoming = []

    try:
        schedules_data = await get_all_schedules(weeks=4)
        schedules = schedules_data.get("schedules", {})

        for schedule_type, schedule_info in schedules.items():
            rotations = schedule_info.get("rotations", [])
            schedule_meta = SCHEDULE_TYPES.get(schedule_type, {})

            for rotation in rotations:
                week_start_str = rotation.get("week_start", "")
                week_end_str = rotation.get("week_end", "")

                if not week_start_str:
                    continue

                try:
                    week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                # Check if target date falls on or near the rotation start
                # We want to notify when rotation starts in exactly REMINDER_DAYS days
                days_until_start = (week_start - datetime.now().date()).days

                if days_until_start == days_ahead:
                    regions = rotation.get("regions", {})

                    for region_id, person_info in regions.items():
                        if not person_info:
                            continue

                        email = person_info.get("email", "")
                        name = person_info.get("name", "")
                        slack = person_info.get("slack", "").lstrip("@")

                        if not email and not slack:
                            continue

                        upcoming.append(
                            {
                                "name": name,
                                "email": email,
                                "slack": slack,
                                "week_start": week_start_str,
                                "week_end": week_end_str,
                                "region": region_id,
                                "schedule_type": schedule_type,
                                "schedule_name": schedule_meta.get("display_name", schedule_type),
                                "schedule_icon": schedule_meta.get("icon", "📅"),
                                "coverage": person_info.get("coverage", ""),
                            }
                        )

        logger.info(
            "Found %d upcoming on-call assignments starting in %d days",
            len(upcoming),
            days_ahead,
        )

    except Exception as e:
        logger.error("Error fetching upcoming on-call data: %s", e)

    return upcoming


# =============================================================================
# Slack Notification
# =============================================================================


async def _send_oncall_reminder(person: Dict[str, Any]) -> bool:
    """
    Send on-call reminder notification to a person.

    Tries to send a DM first (if Slack ID is available), falls back to channel message.
    """
    from services.slack_notifications import get_slack_service

    slack_service = get_slack_service()
    if not slack_service.enabled:
        logger.warning("Slack notifications are disabled, skipping on-call reminder")
        return False

    name = person.get("name", "Unknown")
    email = person.get("email", "")
    week_start = person.get("week_start", "")
    week_end = person.get("week_end", "")
    region = person.get("region", "")
    schedule_name = person.get("schedule_name", "On-Call")
    schedule_icon = person.get("schedule_icon", "📅")
    coverage = person.get("coverage", "")

    # Format dates nicely
    try:
        start_dt = datetime.strptime(week_start, "%Y-%m-%d")
        end_dt = datetime.strptime(week_end, "%Y-%m-%d")
        date_range = f"{start_dt.strftime('%b %d')} - {end_dt.strftime('%b %d, %Y')}"
    except ValueError:
        date_range = f"{week_start} to {week_end}"

    # Build notification blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{schedule_icon} Upcoming On-Call Reminder",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Hey *{name}*! 👋\n\n"
                    f"This is a friendly reminder that you're scheduled for *{schedule_name}* on-call duty starting soon."
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📅 Rotation Period:*\n{date_range}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*🌍 Region:*\n{region}",
                },
            ],
        },
    ]

    if coverage:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*🕐 Coverage Hours:*\n{coverage}",
                    },
                ],
            }
        )

    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "📋 *On-Call Responsibilities:*\n"
                        "• Respond to OpsGenie calls (production alerts, EIMF, IMF)\n"
                        "• Acknowledge alerts promptly - *NEVER ignore OpsGenie calls*\n"
                        "• Review alert details and understand the issue"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "🚨 *Escalation Contacts (if no context):*\n"
                        "• *US hours:* Egor, Shuangjiang, Frank\n"
                        "• *APAC hours:* Ryan, Rajesh Raman V K\n"
                        "• Find feature owners for triage ASAP"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 Plan warm hand-off with current on-call before your rotation starts",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Sent by Agentic Insights Portal • {datetime.now().strftime('%Y-%m-%d %H:%M')} IST_",
                    },
                ],
            },
        ]
    )

    # Send to channel with @mention
    target_channel = FALLBACK_CHANNEL or "C0AV3T98M9Q"
    slack_user_id = None

    # Look up Slack user ID from user_mapping.json (by display name)
    from services.slack_notifications import _load_user_mapping

    user_mapping = _load_user_mapping()

    if name in user_mapping:
        slack_user_id = user_mapping[name].get("slack_id")
        if slack_user_id:
            logger.debug("Found Slack ID %s for %s from user_mapping.json", slack_user_id, name)

    # If not found in mapping, try Slack API lookup by email
    if not slack_user_id and email:
        try:
            user_response = slack_service.client.users_lookupByEmail(email=email)
            if user_response.get("ok"):
                slack_user_id = user_response.get("user", {}).get("id")
                logger.debug("Found Slack ID %s for %s via API lookup", slack_user_id, email)
        except Exception as e:
            logger.debug("Could not find Slack user by email %s: %s", email, e)

    # Add @mention if we have the Slack user ID
    if slack_user_id:
        blocks[1]["text"]["text"] = f"<@{slack_user_id}> - " + blocks[1]["text"]["text"].replace(
            f"Hey *{name}*! 👋\n\n", ""
        )

    logger.info("Sending on-call reminder to channel %s for %s", target_channel, name)

    try:
        result = await slack_service.send_notification(
            blocks=blocks,
            text=f"On-Call Reminder: {name} - {schedule_name} ({date_range})",
            channel=target_channel,
        )
        return result.get("success", False)
    except Exception as e:
        logger.error("Failed to send on-call reminder to %s: %s", name, e)
        return False


async def _process_oncall_reminders(schedules: List[str] = None) -> Dict[str, int]:
    """
    Check for upcoming on-call rotations and send reminders.

    Args:
        schedules: List of schedule types to process (e.g., ["primary", "managers"]).
                   If None, processes all schedules.

    Returns:
        Dict with sent and skipped counts
    """
    logger.info("Checking for upcoming on-call rotations (reminder days: %d)", REMINDER_DAYS)

    sent_count = 0
    skipped_count = 0

    try:
        upcoming = await _get_upcoming_oncall(days_ahead=REMINDER_DAYS)

        for person in upcoming:
            week_start = person.get("week_start", "")
            email = person.get("email", "")
            schedule_type = person.get("schedule_type", "")

            # Filter by schedule type if specified
            if schedules and schedule_type not in schedules:
                logger.debug(
                    "Skipping %s - schedule type %s not in filter %s", person.get("name"), schedule_type, schedules
                )
                continue

            # Skip if already sent
            if _was_notification_sent(week_start, email, schedule_type):
                logger.debug(
                    "Skipping %s - notification already sent for %s rotation",
                    person.get("name"),
                    week_start,
                )
                skipped_count += 1
                continue

            # Send reminder
            success = await _send_oncall_reminder(person)

            if success:
                _mark_notification_sent(week_start, email, schedule_type)
                sent_count += 1
                logger.info(
                    "Sent on-call reminder to %s for %s (%s)",
                    person.get("name"),
                    week_start,
                    schedule_type,
                )
            else:
                logger.warning(
                    "Failed to send on-call reminder to %s",
                    person.get("name"),
                )

        logger.info(
            "On-call reminder check complete: %d sent, %d skipped",
            sent_count,
            skipped_count,
        )

    except Exception as e:
        logger.error("Error processing on-call reminders: %s", e, exc_info=True)

    return {"sent": sent_count, "skipped": skipped_count}


# =============================================================================
# Async Runner Helper
# =============================================================================


def _run_async(coro) -> Any:
    """Run an async coroutine from sync context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# =============================================================================
# Scheduler Loop
# =============================================================================


def _scheduler_loop():
    """
    Main scheduler loop - runs in background thread.

    Checks every minute for scheduled reminder time and triggers notifications.
    """
    global _scheduler_running

    reminder_hour, reminder_minute = _parse_reminder_time()
    tz_name = DEFAULT_TIMEZONE

    logger.info(
        "On-call notification scheduler started - daily at %02d:%02d %s (remind %d days before)",
        reminder_hour,
        reminder_minute,
        tz_name,
        REMINDER_DAYS,
    )

    _load_state()

    last_run_date = None

    while _scheduler_running:
        try:
            now = _get_current_time()
            current_date = now.date()
            current_hour = now.hour
            current_minute = now.minute

            # Check if it's time to run (once per day at the configured time)
            if current_hour == reminder_hour and current_minute == reminder_minute and last_run_date != current_date:
                logger.info("Scheduled time reached - checking for on-call reminders")
                _run_async(_process_oncall_reminders())
                last_run_date = current_date

            time.sleep(60)

        except Exception as e:
            logger.error("On-call notification scheduler error: %s", e)
            time.sleep(60)


# =============================================================================
# Public API
# =============================================================================


def start_oncall_notification_scheduler():
    """Start the background scheduler thread."""
    global _scheduler_running, _scheduler_thread

    if not REMINDER_ENABLED:
        logger.info("On-call notification scheduler disabled via ONCALL_REMINDER_ENABLED env var")
        return

    if _scheduler_running:
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="oncall-notification-scheduler",
    )
    _scheduler_thread.start()


def stop_oncall_notification_scheduler():
    """Stop the background scheduler."""
    global _scheduler_running
    _scheduler_running = False
    logger.info("On-call notification scheduler stopped")


def get_oncall_notification_status() -> Dict[str, Any]:
    """Get current scheduler status and configuration."""
    # Load config from slack_scheduler_config.json
    import json
    from pathlib import Path

    config_file = Path(__file__).parent.parent / "data" / "slack_scheduler_config.json"
    oncall_config = {}

    try:
        if config_file.exists():
            with open(config_file, "r") as f:
                config = json.load(f)
                oncall_config = config.get("notifications", {}).get("oncall_reminder", {})
    except Exception:
        pass

    return {
        "enabled": oncall_config.get("enabled", False),
        "config_source": "slack_scheduler_config.json",
        "timezone": DEFAULT_TIMEZONE,
        "reminder_days": oncall_config.get("reminder_days", REMINDER_DAYS),
        "schedule_times": oncall_config.get("schedule_times", ["09:00"]),
        "fallback_channel": oncall_config.get("channel", FALLBACK_CHANNEL) or "(none - DM only)",
        "schedules": oncall_config.get("schedules", ["primary", "managers", "backend"]),
        "notifications_sent": len(_sent_notifications),
        "state_file": str(STATE_FILE),
    }


async def trigger_oncall_reminders_now(
    days_ahead: int = None,
    channel: str = None,
    schedules: List[str] = None,
) -> Dict[str, Any]:
    """
    Manual trigger for on-call reminders.

    Args:
        days_ahead: Override for REMINDER_DAYS (default: use configured value)
        channel: Override fallback channel (default: use FALLBACK_CHANNEL env var)
        schedules: List of schedule types to process (default: all)

    Returns:
        Dict with success status and counts
    """
    global REMINDER_DAYS, FALLBACK_CHANNEL
    original_days = REMINDER_DAYS
    original_channel = FALLBACK_CHANNEL

    if days_ahead is not None:
        REMINDER_DAYS = days_ahead
    if channel is not None:
        FALLBACK_CHANNEL = channel

    try:
        result = await _process_oncall_reminders(schedules=schedules)
        return {
            "success": True,
            "triggered_at": _get_current_time().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "reminder_days": REMINDER_DAYS,
            "channel": FALLBACK_CHANNEL,
            "schedules": schedules or ["all"],
            "sent": result.get("sent", 0),
            "skipped": result.get("skipped", 0),
        }
    finally:
        REMINDER_DAYS = original_days
        FALLBACK_CHANNEL = original_channel


async def preview_oncall_reminders(days_ahead: int = None) -> Dict[str, Any]:
    """
    Preview upcoming on-call reminders without sending them.

    Args:
        days_ahead: Days ahead to check (default: REMINDER_DAYS)
    """
    days = days_ahead if days_ahead is not None else REMINDER_DAYS

    upcoming = await _get_upcoming_oncall(days_ahead=days)

    results = []
    for person in upcoming:
        week_start = person.get("week_start", "")
        email = person.get("email", "")
        schedule_type = person.get("schedule_type", "")

        already_sent = _was_notification_sent(week_start, email, schedule_type)

        results.append(
            {
                "name": person.get("name"),
                "email": email,
                "slack": person.get("slack"),
                "schedule_type": schedule_type,
                "schedule_name": person.get("schedule_name"),
                "region": person.get("region"),
                "week_start": week_start,
                "week_end": person.get("week_end"),
                "already_notified": already_sent,
            }
        )

    return {
        "days_ahead": days,
        "upcoming_count": len(results),
        "upcoming": results,
        "current_time": _get_current_time().strftime("%Y-%m-%d %H:%M:%S %Z"),
    }

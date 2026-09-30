"""
Slack Scheduled Notifications - Daily triggers at multiple times with persistence.

Features:
- Supports multiple schedule times per day (e.g., 9am and 9pm IST)
- Persists sent slots to disk to survive server restarts
- Catches up on missed notifications if server starts after a scheduled time
- Configurable via slack_scheduler_config.json
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx
import pytz

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Constants
# =============================================================================

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_FILE = DATA_DIR / "slack_scheduler_config.json"
STATE_FILE = DATA_DIR / "slack_scheduler_state.json"

DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_CATCHUP_WINDOW_HOURS = 3
DEFAULT_HTTP_TIMEOUT = 120
API_BASE_URL = "http://localhost:8000"

SCHEDULE_ENABLED = os.getenv("SLACK_SCHEDULE_ENABLED", "true").lower() == "true"

# =============================================================================
# Scheduler State (module-level)
# =============================================================================

_scheduler_running = False
_scheduler_thread: Optional[threading.Thread] = None
_sent_slots: set = set()
_state_date: Optional[str] = None
_state_file_loaded = False


# =============================================================================
# Configuration Loading
# =============================================================================


def _load_scheduler_config() -> Dict[str, Any]:
    """Load scheduler configuration from JSON file."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            logger.debug("Loaded scheduler config from %s", CONFIG_FILE)
            return config
    except Exception as e:
        logger.warning("Could not load scheduler config: %s. Using defaults.", e)

    return _get_default_config()


def _get_default_config() -> Dict[str, Any]:
    """Return default configuration when config file is missing."""
    return {
        "notifications": {
            "release_readiness": {
                "enabled": True,
                "schedule_times": ["09:00", "21:00"],
                "use_active_releases": True,
                "channel": None,
            },
            "regression_status": {
                "enabled": True,
                "schedule_times": ["09:00"],
                "release_id": "R136",
                "channel": "C0AFZ9T0199",
            },
        },
        "timezone": DEFAULT_TIMEZONE,
        "catch_up_window_hours": DEFAULT_CATCHUP_WINDOW_HOURS,
    }


def _get_notification_config(notif_type: str) -> Dict[str, Any]:
    """Get configuration for a specific notification type."""
    config = _load_scheduler_config()
    return config.get("notifications", {}).get(notif_type, {})


def _get_timezone() -> pytz.BaseTzInfo:
    """Get configured timezone."""
    config = _load_scheduler_config()
    tz_name = config.get("timezone", DEFAULT_TIMEZONE)
    return pytz.timezone(tz_name)


def _get_current_time() -> datetime:
    """Get current time in configured timezone."""
    return datetime.now(_get_timezone())


# =============================================================================
# Schedule Time Parsing
# =============================================================================


def _parse_schedule_times(time_strings: List[str]) -> List[tuple]:
    """Parse schedule time strings like '09:00' into (hour, minute) tuples."""
    times = []
    for ts in time_strings:
        try:
            parts = ts.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            times.append((hour, minute))
        except (ValueError, IndexError):
            logger.warning("Invalid schedule time format: %s", ts)
    return times


def _get_all_schedule_times() -> List[tuple]:
    """Get all unique schedule times from all enabled notification types."""
    config = _load_scheduler_config()
    all_times = set()

    for notif_config in config.get("notifications", {}).values():
        if notif_config.get("enabled", False):
            times = _parse_schedule_times(notif_config.get("schedule_times", []))
            all_times.update(times)

    return sorted(all_times)


def _slot_key(hour: int, minute: int) -> str:
    """Create a slot key string from hour and minute."""
    return f"{hour:02d}:{minute:02d}"


# =============================================================================
# State Persistence
# =============================================================================


def _load_state() -> Dict[str, Any]:
    """Load scheduler state from disk."""
    global _sent_slots, _state_date, _state_file_loaded

    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

            saved_date = state.get("date")
            today = _get_current_time().strftime("%Y-%m-%d")

            if saved_date == today:
                _sent_slots = set(state.get("sent_slots", []))
                _state_date = saved_date
            else:
                _sent_slots = set()
                _state_date = today

            _state_file_loaded = True
            logger.info("Loaded scheduler state: date=%s, sent_slots=%s", saved_date, _sent_slots)
            return state
        else:
            logger.info("No scheduler state file found - catch-up disabled until first successful send")
    except Exception as e:
        logger.warning("Could not load scheduler state: %s", e)

    return {}


def _save_state():
    """Save scheduler state to disk."""
    global _state_file_loaded

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        today = _get_current_time().strftime("%Y-%m-%d")
        state = {
            "date": today,
            "sent_slots": list(_sent_slots),
            "updated_at": _get_current_time().isoformat(),
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

        _state_file_loaded = True
        logger.info("Saved scheduler state: date=%s, sent_slots=%s", today, _sent_slots)
    except Exception as e:
        logger.error("Could not save scheduler state: %s", e)


def _get_catchup_slots() -> List[str]:
    """
    Get schedule slots that were missed and should be caught up.

    Only catches up if:
    - The state file was loaded successfully
    - The slot hasn't been sent today
    - Current time is past the slot's scheduled time
    - Current time is within the catch-up window
    """
    if not _state_file_loaded:
        logger.info("Skipping catch-up: state file not found")
        return []

    config = _load_scheduler_config()
    catchup_window = config.get("catch_up_window_hours", DEFAULT_CATCHUP_WINDOW_HOURS)

    now = _get_current_time()
    schedule_times = _get_all_schedule_times()
    catchup = []

    for hour, minute in schedule_times:
        key = _slot_key(hour, minute)
        if key in _sent_slots:
            continue

        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        cutoff = scheduled + timedelta(hours=catchup_window)

        if scheduled <= now <= cutoff:
            logger.info(
                "Catch-up eligible: %s (now=%s, cutoff=%s)", key, now.strftime("%H:%M"), cutoff.strftime("%H:%M")
            )
            catchup.append(key)

    return catchup


# =============================================================================
# HTTP Client Helper
# =============================================================================


async def _make_api_request(
    method: str, endpoint: str, json_data: Optional[Dict] = None, timeout: int = DEFAULT_HTTP_TIMEOUT
) -> Optional[Dict]:
    """Make an HTTP request to the local API."""
    url = f"{API_BASE_URL}{endpoint}"

    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        if method.upper() == "GET":
            response = await client.get(url)
        elif method.upper() == "POST":
            response = await client.post(url, json=json_data)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                "API request failed: %s %s -> HTTP %s: %s", method, endpoint, response.status_code, response.text[:200]
            )
            return None


# =============================================================================
# Notification Senders
# =============================================================================


async def _fetch_release_data_with_retry(release_id: str, max_retries: int = 3) -> Optional[Dict]:
    """Fetch release readiness data with retry logic."""
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("  Fetching JIRA data for %s (attempt %d/%d)...", release_id, attempt, max_retries)

            data = await _make_api_request(
                "GET", f"/api/jira/release-readiness?release={release_id}&refresh=true", timeout=90
            )

            if not data:
                last_error = "Empty response from API"
                if attempt < max_retries:
                    await asyncio.sleep(5)
                continue

            components_data = data.get("componentsData", {})
            if not components_data:
                last_error = "Empty components data - JIRA may have failed"
                logger.warning("  Attempt %d: %s", attempt, last_error)
                if attempt < max_retries:
                    await asyncio.sleep(5)
                continue

            summary = data.get("summary", {})
            logger.info(
                "  Data for %s: %d stories, %d bugs, %d total open",
                release_id,
                summary.get("total_bc_stories", 0),
                summary.get("total_bc_bugs", 0),
                summary.get("total_fb_issues", 0),
            )
            return data

        except asyncio.TimeoutError:
            last_error = "Request timeout"
            logger.warning("  Attempt %d timed out", attempt)
        except Exception as e:
            last_error = str(e)
            logger.warning("  Attempt %d error: %s", attempt, last_error)

        if attempt < max_retries:
            await asyncio.sleep(5)

    logger.error("  All %d attempts failed for %s. Last error: %s", max_retries, release_id, last_error)
    return None


async def _send_release_readiness(release_id: str, channel: str) -> bool:
    """Send release readiness notification for a specific release."""
    logger.info("Sending release readiness for %s to channel %s...", release_id, channel)

    result = await _make_api_request("POST", "/api/slack/notify", json_data={"release": release_id, "channel": channel})

    if result:
        logger.info("Release readiness sent for %s to %s", release_id, channel)
        return True
    return False


async def _send_regression_status(release_id: str, channel: str) -> bool:
    """Send regression status notification for a specific release."""
    logger.info("Sending regression status for %s to channel %s...", release_id, channel)

    result = await _make_api_request(
        "POST", "/api/slack/notify/regression-status", json_data={"release": release_id, "channel": channel}
    )

    if result:
        logger.info(
            "Regression status sent for %s: %d messages to %s", release_id, result.get("messages_sent", 0), channel
        )
        return True
    return False


async def _send_deployment_version_report(stacks: List[str], channel: str) -> bool:
    """Send deployment version report notification."""
    logger.info("Sending deployment version report for stacks %s to channel %s...", stacks, channel)

    result = await _make_api_request(
        "POST", "/api/slack/notify/deployment-version-report", json_data={"stacks": stacks, "channel": channel}
    )

    if result and result.get("success"):
        logger.info(
            "Deployment version report sent: %d deployments to %s",
            result.get("deployments_count", 0),
            channel,
        )
        return True
    return False


async def _send_oncall_reminder(reminder_days: int, channel: str, schedules: List[str]) -> bool:
    """
    Send on-call reminder notifications.

    Finds people scheduled for on-call in `reminder_days` days and sends them
    a notification (DM if possible, otherwise to the fallback channel).
    """
    logger.info(
        "Sending on-call reminders (days_ahead=%d, fallback_channel=%s, schedules=%s)...",
        reminder_days,
        channel,
        schedules,
    )

    result = await _make_api_request(
        "POST",
        "/api/slack/oncall-reminder/trigger",
        json_data={
            "days_ahead": reminder_days,
            "channel": channel,
            "schedules": schedules,
        },
        timeout=60,
    )

    if result and result.get("success"):
        logger.info(
            "On-call reminders processed: sent=%d, skipped=%d",
            result.get("sent", 0),
            result.get("skipped", 0),
        )
        return True
    return False


async def _send_active_releases_notification() -> bool:
    """Send notifications for all active releases based on timeline (legacy mode)."""
    try:
        from config import RELEASE_MILESTONES, get_active_releases
        from services.jira_client import get_jira_client

        try:
            jira = get_jira_client()
            jira.clear_cache()
            logger.info("Cleared JIRA cache before scheduled notification")
        except Exception as e:
            logger.warning("Could not clear JIRA cache: %s", e)

        active_releases = get_active_releases()
        if not active_releases:
            logger.warning("No active releases found based on timeline")
            return False

        logger.info("Found %d active release(s): %s", len(active_releases), active_releases)

        success_count = 0
        for release_id in active_releases:
            release_config = next((r for r in RELEASE_MILESTONES if r["id"] == release_id), None)

            if release_config and not release_config.get("notifications_enabled", True):
                logger.info("Skipping %s - notifications disabled", release_id)
                continue

            # Fetch data with retry
            release_data = await _fetch_release_data_with_retry(release_id)
            if not release_data:
                continue

            channel = release_config.get("slack_channel") if release_config else None
            result = await _make_api_request(
                "POST", "/api/slack/notify", json_data={"release": release_id, "channel": channel}
            )

            if result:
                success_count += 1

        logger.info("Scheduled notifications complete: %d/%d successful", success_count, len(active_releases))
        return success_count > 0

    except Exception as e:
        logger.error("Error in scheduled notification: %s", e, exc_info=True)
        return False


# =============================================================================
# Async Runner Helper
# =============================================================================


def _run_async(coro: Coroutine) -> Any:
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
# Release Configuration Helpers
# =============================================================================


def _get_releases_for_notification(notif_type: str) -> List[Dict[str, Any]]:
    """
    Get list of releases and their channels for a notification type.

    Handles both formats:
    - Dict format: {"R136": "channel1", "R135": "channel2"}
    - List format: ["R136", "R135"] with shared channel
    """
    config = _get_notification_config(notif_type)
    releases_config = config.get("releases", {})
    shared_channel = config.get("channel")

    result = []

    if isinstance(releases_config, dict):
        for release_id, channel in releases_config.items():
            result.append({"release_id": release_id, "channel": channel})
    elif isinstance(releases_config, list):
        for release_id in releases_config:
            result.append({"release_id": release_id, "channel": shared_channel})

    return result


# =============================================================================
# Notification Dispatcher
# =============================================================================

# Map of notification types to their async sender functions
# Note: deployment_version_report uses a different signature (stacks, channel) instead of (release_id, channel)
_NOTIFICATION_HANDLERS: Dict[str, Callable] = {
    "release_readiness": _send_release_readiness,
    "regression_status": _send_regression_status,
    "deployment_version_report": _send_deployment_version_report,
}


def _send_notifications_for_slot(slot: str):
    """
    Send all notifications configured for this time slot.

    Checks each notification type and sends if:
    1. The notification is enabled
    2. The current slot is in the notification's schedule_times
    """
    config = _load_scheduler_config()
    notifications = config.get("notifications", {})

    for notif_type, notif_config in notifications.items():
        if not notif_config.get("enabled", False):
            continue

        schedule_times = _parse_schedule_times(notif_config.get("schedule_times", []))
        scheduled_slots = [_slot_key(h, m) for h, m in schedule_times]

        if slot not in scheduled_slots:
            continue

        logger.info("Sending %s notification for slot %s", notif_type, slot)

        # Handle deployment_version_report separately (uses stacks instead of releases)
        if notif_type == "deployment_version_report":
            stacks = notif_config.get("stacks", ["qa01", "stg01"])
            channel = notif_config.get("channel")
            if channel:
                logger.info("Sending deployment_version_report for stacks %s to %s", stacks, channel)
                _run_async(_send_deployment_version_report(stacks, channel))
            else:
                logger.warning("No channel configured for deployment_version_report, skipping")
            continue

        # Handle oncall_reminder separately (uses reminder_days, channel, schedules)
        if notif_type == "oncall_reminder":
            reminder_days = notif_config.get("reminder_days", 4)
            channel = notif_config.get("channel")
            schedules = notif_config.get("schedules", ["primary", "managers", "backend"])
            if channel:
                logger.info("Sending oncall_reminder (days=%d, schedules=%s) to %s", reminder_days, schedules, channel)
                _run_async(_send_oncall_reminder(reminder_days, channel, schedules))
            else:
                logger.warning("No channel configured for oncall_reminder, skipping")
            continue

        releases = _get_releases_for_notification(notif_type)
        handler = _NOTIFICATION_HANDLERS.get(notif_type)

        if releases and handler:
            for release in releases:
                release_id = release["release_id"]
                channel = release["channel"]

                if not channel:
                    logger.warning("No channel for %s / %s, skipping", notif_type, release_id)
                    continue

                # For regression_status, check if we're in the regression window
                # (after branch cut, before signoff STG/FedAlpha)
                if notif_type == "regression_status":
                    from config import is_regression_notification_active

                    if not is_regression_notification_active(release_id):
                        logger.info(
                            "Skipping regression_status for %s - not in regression window "
                            "(must be after Branch Cut and before Signoff STG/FedAlpha)",
                            release_id,
                        )
                        continue

                logger.info("Sending %s for %s to %s", notif_type, release_id, channel)
                _run_async(handler(release_id, channel))

        elif notif_type == "release_readiness":
            _run_async(_send_active_releases_notification())
        else:
            logger.warning("No handler for notification type: %s", notif_type)


# =============================================================================
# Scheduler Loop
# =============================================================================


def _scheduler_loop():
    """
    Main scheduler loop - runs in background thread.

    - Checks every minute for scheduled times
    - Handles catch-up for missed notifications
    - Persists state after each send
    """
    global _scheduler_running, _sent_slots, _state_date

    schedule_times = _get_all_schedule_times()
    config = _load_scheduler_config()
    tz_name = config.get("timezone", DEFAULT_TIMEZONE)

    schedule_desc = ", ".join(_slot_key(h, m) for h, m in schedule_times)
    logger.info("Slack scheduler started - daily at %s %s", schedule_desc, tz_name)

    _load_state()

    # Handle catch-up for missed slots
    catchup_slots = _get_catchup_slots()
    if catchup_slots:
        logger.info("Catch-up: sending for missed slots %s...", catchup_slots)
        _send_notifications_for_slot(catchup_slots[0])
        for slot in catchup_slots:
            _sent_slots.add(slot)
        _save_state()

    while _scheduler_running:
        try:
            now = _get_current_time()
            today = now.strftime("%Y-%m-%d")

            # Reset slots on new day
            if _state_date != today:
                _sent_slots.clear()
                _state_date = today
                logger.info("New day detected, reset sent slots")

            current_slot = _slot_key(now.hour, now.minute)

            # Reload schedule times (config may have changed)
            schedule_times = _get_all_schedule_times()

            for hour, minute in schedule_times:
                slot = _slot_key(hour, minute)
                if current_slot == slot and slot not in _sent_slots:
                    logger.info("Scheduled time reached (%s) - triggering notifications", slot)
                    _send_notifications_for_slot(slot)
                    _sent_slots.add(slot)
                    _save_state()

            time.sleep(60)

        except Exception as e:
            logger.error("Scheduler error: %s", e)
            time.sleep(60)


# =============================================================================
# Public API
# =============================================================================


def start_slack_scheduler():
    """Start the background scheduler thread."""
    global _scheduler_running, _scheduler_thread

    if not SCHEDULE_ENABLED:
        logger.info("Slack scheduler disabled via SLACK_SCHEDULE_ENABLED env var")
        return

    if _scheduler_running:
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="slack-scheduler")
    _scheduler_thread.start()


def stop_slack_scheduler():
    """Stop the background scheduler."""
    global _scheduler_running
    _scheduler_running = False
    logger.info("Slack scheduler stopped")


def get_scheduler_status() -> Dict[str, Any]:
    """Get current scheduler status and configuration."""
    from config import get_active_releases, get_release_dates

    config = _load_scheduler_config()
    tz_name = config.get("timezone", DEFAULT_TIMEZONE)
    now = _get_current_time()
    today = now.strftime("%Y-%m-%d")

    # Get active releases info
    active_releases = get_active_releases()
    releases_info = []
    for release_id in active_releases:
        dates = get_release_dates(release_id)
        releases_info.append(
            {
                "id": release_id,
                "branch_cut": dates.get("branch_cut", "N/A"),
                "final_build": dates.get("final_build", "N/A"),
            }
        )

    # Calculate schedule info
    schedule_times = _get_all_schedule_times()
    all_slots = [_slot_key(h, m) for h, m in schedule_times]
    sent_today = _sent_slots if _state_date == today else set()

    # Find next scheduled time
    next_slot = None
    next_scheduled = None
    for hour, minute in sorted(schedule_times):
        slot_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slot = _slot_key(hour, minute)
        if slot_time > now and slot not in sent_today:
            next_slot = slot
            next_scheduled = slot_time
            break

    if next_scheduled is None and schedule_times:
        tomorrow_first = sorted(schedule_times)[0]
        next_scheduled = (now + timedelta(days=1)).replace(
            hour=tomorrow_first[0], minute=tomorrow_first[1], second=0, microsecond=0
        )
        next_slot = _slot_key(tomorrow_first[0], tomorrow_first[1])

    time_until_next = (next_scheduled - now) if next_scheduled else timedelta(0)
    hours, remainder = divmod(int(time_until_next.total_seconds()), 3600)
    minutes = remainder // 60

    # Build notifications status
    notifications_status = {}
    for notif_type, notif_config in config.get("notifications", {}).items():
        status_entry = {
            "enabled": notif_config.get("enabled", False),
            "schedule_times": notif_config.get("schedule_times", []),
            "channel": notif_config.get("channel"),
            "releases": notif_config.get("releases"),
        }

        # For regression_status, add info about whether it's currently active based on release phase
        if notif_type == "regression_status" and notif_config.get("enabled", False):
            from config import get_release_dates, is_regression_notification_active

            releases_config = notif_config.get("releases", [])
            regression_status_info = {}

            # Handle both list and dict formats
            release_ids = releases_config if isinstance(releases_config, list) else list(releases_config.keys())

            for release_id in release_ids:
                is_active = is_regression_notification_active(release_id)
                dates = get_release_dates(release_id)
                regression_status_info[release_id] = {
                    "notifications_active": is_active,
                    "branch_cut": dates.get("branch_cut", "N/A"),
                    "signoff_stg": dates.get("signoff_stg", "N/A"),
                    "reason": (
                        "In regression window (after Branch Cut, before Signoff STG)"
                        if is_active
                        else "Outside regression window"
                    ),
                }

            status_entry["regression_window_status"] = regression_status_info

        notifications_status[notif_type] = status_entry

    return {
        "enabled": SCHEDULE_ENABLED,
        "running": _scheduler_running,
        "timezone": tz_name,
        "schedule_times": [f"{s} {tz_name}" for s in all_slots],
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "sent_today": list(sent_today),
        "pending_today": [s for s in all_slots if s not in sent_today],
        "next_scheduled": (
            f"{next_slot} {tz_name} ({next_scheduled.strftime('%Y-%m-%d %H:%M:%S')})" if next_scheduled else "None"
        ),
        "time_until_next": f"{hours}h {minutes}m",
        "config_file": str(CONFIG_FILE),
        "state_file": str(STATE_FILE),
        "catchup_eligible": _get_catchup_slots(),
        "notifications": notifications_status,
        "active_releases": releases_info,
        "active_release_count": len(active_releases),
    }


async def trigger_notification_now(save_state: bool = False) -> Dict[str, Any]:
    """
    Manual trigger for testing.

    By default, does NOT save state so scheduled runs are not affected.
    """
    success = await _send_active_releases_notification()

    state_saved = False
    if success and save_state:
        now = _get_current_time()
        schedule_times = _get_all_schedule_times()

        nearest_slot = None
        min_diff = float("inf")
        for hour, minute in schedule_times:
            slot_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            diff = abs((now - slot_time).total_seconds())
            if diff < min_diff:
                min_diff = diff
                nearest_slot = _slot_key(hour, minute)

        if nearest_slot:
            _sent_slots.add(nearest_slot)
            _save_state()
            state_saved = True

    return {
        "success": success,
        "triggered_at": _get_current_time().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "state_saved": state_saved,
        "note": "Manual trigger" if not state_saved else "State saved - nearest slot marked as sent",
    }

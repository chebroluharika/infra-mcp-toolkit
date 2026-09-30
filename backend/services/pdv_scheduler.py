"""
PDV Scheduler - Automated status change notifications.

Features:
- Checks for PDV status changes every 5 minutes
- Sends Slack notifications when status changes detected
- Alerts when token is expired (manual refresh required)
- Configurable via environment variables

Note: Token refresh requires manual browser login via your-pdv-serviceauth tool.
The scheduler will alert when token expires but cannot auto-refresh.

Environment Variables:
- PDV_SCHEDULER_ENABLED: Enable/disable scheduler (default: true)
- PDV_CHECK_INTERVAL_MINUTES: Status check interval (default: 5)
- PDV_RELEASES: Comma-separated releases to monitor (default: current active release)
- PDV_SLACK_CHANNEL: Slack channel for notifications (default: YOUR_SLACK_CHANNEL_ID)
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

PDV_SCHEDULER_ENABLED = os.getenv("PDV_SCHEDULER_ENABLED", "true").lower() == "true"
PDV_CHECK_INTERVAL_MINUTES = int(os.getenv("PDV_CHECK_INTERVAL_MINUTES", "5"))
PDV_SLACK_CHANNEL = os.getenv("PDV_SLACK_CHANNEL", "YOUR_SLACK_CHANNEL_ID")

# Releases to monitor (comma-separated, e.g., "R136,R137")
PDV_RELEASES = os.getenv("PDV_RELEASES", "").strip()

API_BASE_URL = "http://localhost:8000"
HTTP_TIMEOUT = 60

# =============================================================================
# Scheduler State
# =============================================================================

_scheduler_running = False
_scheduler_thread: Optional[threading.Thread] = None
_last_status_check: Optional[datetime] = None
_token_warning_sent = False


# =============================================================================
# Helper Functions
# =============================================================================


def _get_active_releases() -> List[str]:
    """Get list of releases to monitor."""
    if PDV_RELEASES:
        return [r.strip() for r in PDV_RELEASES.split(",") if r.strip()]

    # Default: try to get from config
    try:
        from config import get_active_releases

        releases = get_active_releases()
        if releases:
            return releases
    except Exception:
        pass

    # Fallback to R136
    return ["R136"]


async def _make_api_request(method: str, endpoint: str, timeout: int = HTTP_TIMEOUT) -> dict:
    """Make HTTP request to local API."""
    url = f"{API_BASE_URL}{endpoint}"

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            if method.upper() == "GET":
                response = await client.get(url)
            else:
                response = await client.post(url)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error("API request failed: %s %s -> %d", method, endpoint, response.status_code)
                return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.error("API request error: %s %s -> %s", method, endpoint, e)
        return {"success": False, "error": str(e)}


# =============================================================================
# Token Check
# =============================================================================


async def check_token_status() -> dict:
    """Check if PDV token is valid."""
    try:
        result = await _make_api_request("GET", "/api/pdv/token-info")
        return result
    except Exception as e:
        logger.error("Error checking token status: %s", e)
        return {"success": False, "error": str(e)}


async def send_token_expiry_alert() -> bool:
    """Send Slack alert when token is expired. (Disabled - only logs warning)"""
    global _token_warning_sent

    if _token_warning_sent:
        return False

    # Disabled: Don't send Slack notification for token expiry
    # Just log the warning and set the flag to avoid repeated logs
    _token_warning_sent = True
    logger.warning("PDV token expired - status checks paused until token is refreshed")
    return False


# =============================================================================
# Status Check and Notifications
# =============================================================================


async def check_pdv_status_changes() -> dict:
    """Check for PDV status changes and send notifications."""
    global _last_status_check

    releases = _get_active_releases()
    results = {
        "checked": [],
        "changes_detected": 0,
        "notifications_sent": 0,
        "errors": [],
    }

    for release_id in releases:
        try:
            logger.debug("Checking PDV status changes for %s...", release_id)

            endpoint = f"/api/pdv/check-changes/{release_id}?channel={PDV_SLACK_CHANNEL}"
            result = await _make_api_request("POST", endpoint)

            results["checked"].append(release_id)

            if result.get("success"):
                changes = result.get("changes_detected", 0)
                results["changes_detected"] += changes

                if result.get("notification_sent"):
                    results["notifications_sent"] += 1
                    logger.info(
                        "PDV status change detected for %s: %d change(s), notification sent", release_id, changes
                    )
                elif changes > 0:
                    logger.info("PDV status change detected for %s: %d change(s)", release_id, changes)
            else:
                error = result.get("error", "Unknown error")
                results["errors"].append(f"{release_id}: {error}")
                logger.warning("PDV status check failed for %s: %s", release_id, error)

        except Exception as e:
            results["errors"].append(f"{release_id}: {str(e)}")
            logger.error("Error checking PDV status for %s: %s", release_id, e)

    _last_status_check = datetime.now(timezone.utc)
    return results


# =============================================================================
# Scheduler Loop
# =============================================================================


def _run_async(coro):
    """Run async coroutine from sync context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _scheduler_loop():
    """Main scheduler loop running in background thread."""
    global _scheduler_running, _token_warning_sent

    logger.info("PDV Scheduler started")
    logger.info("  - Status check interval: %d minutes", PDV_CHECK_INTERVAL_MINUTES)
    logger.info("  - Releases to monitor: %s", _get_active_releases())
    logger.info("  - Slack channel: %s", PDV_SLACK_CHANNEL)

    check_interval_seconds = PDV_CHECK_INTERVAL_MINUTES * 60
    last_check_time = 0

    # Wait for server to be ready
    time.sleep(10)

    while _scheduler_running:
        try:
            current_time = time.time()

            # Check token status first
            token_info = _run_async(check_token_status())

            if not token_info.get("is_valid", False):
                # Token expired or invalid - send alert and skip status check
                _run_async(send_token_expiry_alert())
                time.sleep(300)  # Check again in 5 minutes
                continue

            # Reset warning flag if token is valid again
            if _token_warning_sent and token_info.get("is_valid"):
                _token_warning_sent = False
                logger.info("PDV token is valid again - resuming status checks")

            # Status check (every PDV_CHECK_INTERVAL_MINUTES)
            if current_time - last_check_time >= check_interval_seconds:
                logger.debug("Running PDV status check...")
                result = _run_async(check_pdv_status_changes())
                last_check_time = current_time

                if result.get("changes_detected", 0) > 0:
                    logger.info(
                        "PDV check complete: %d changes, %d notifications",
                        result["changes_detected"],
                        result["notifications_sent"],
                    )

            # Sleep for 30 seconds between iterations
            time.sleep(30)

        except Exception as e:
            logger.error("PDV scheduler error: %s", e)
            time.sleep(60)  # Wait a minute before retrying

    logger.info("PDV Scheduler stopped")


# =============================================================================
# Public API
# =============================================================================


def start_pdv_scheduler():
    """Start the PDV scheduler background thread."""
    global _scheduler_running, _scheduler_thread

    if not PDV_SCHEDULER_ENABLED:
        logger.info("PDV Scheduler disabled (PDV_SCHEDULER_ENABLED=false)")
        return

    if _scheduler_running:
        logger.warning("PDV Scheduler already running")
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    logger.info("PDV Scheduler thread started")


def stop_pdv_scheduler():
    """Stop the PDV scheduler."""
    global _scheduler_running, _scheduler_thread

    if not _scheduler_running:
        return

    logger.info("Stopping PDV Scheduler...")
    _scheduler_running = False

    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)

    _scheduler_thread = None
    logger.info("PDV Scheduler stopped")


def get_pdv_scheduler_status() -> dict:
    """Get current scheduler status."""
    return {
        "enabled": PDV_SCHEDULER_ENABLED,
        "running": _scheduler_running,
        "check_interval_minutes": PDV_CHECK_INTERVAL_MINUTES,
        "releases": _get_active_releases(),
        "slack_channel": PDV_SLACK_CHANNEL,
        "last_status_check": _last_status_check.isoformat() if _last_status_check else None,
        "token_warning_sent": _token_warning_sent,
    }

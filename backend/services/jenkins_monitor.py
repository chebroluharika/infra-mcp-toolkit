"""
Jenkins Pipeline Monitor
=========================

Monitors Jenkins pipelines for stuck/long-running jobs and sends Slack alerts.

Features:
- Detects pipelines running for more than 1 hour
- Sends Slack notifications with pipeline details
- Tracks alerted pipelines to avoid duplicate notifications
- Configurable thresholds and check intervals

Usage:
    from services.jenkins_monitor import start_jenkins_monitor, stop_jenkins_monitor

    # Start at app startup
    start_jenkins_monitor()

    # Stop at app shutdown
    stop_jenkins_monitor()

Configuration (via environment variables):
    JENKINS_MONITOR_ENABLED=true
    JENKINS_MONITOR_THRESHOLD_MINUTES=60
    JENKINS_MONITOR_CHECK_INTERVAL_MINUTES=5
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Configuration from environment
MONITOR_ENABLED = os.getenv("JENKINS_MONITOR_ENABLED", "true").lower() == "true"
THRESHOLD_MINUTES = int(os.getenv("JENKINS_MONITOR_THRESHOLD_MINUTES", "60"))
CHECK_INTERVAL_MINUTES = int(os.getenv("JENKINS_MONITOR_CHECK_INTERVAL_MINUTES", "5"))

# Track state
_monitor_running = False
_monitor_thread: Optional[threading.Thread] = None
_alerted_pipelines: Set[str] = set()  # Track pipelines we've already alerted about
_last_check_time: Optional[datetime] = None


async def _fetch_running_pipelines() -> List[Dict]:
    """Fetch all currently running pipelines from Jenkins."""
    running_pipelines = []

    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()
        if not jenkins.is_configured():
            logger.warning("Jenkins not configured for pipeline monitoring")
            return []

        # Fetch all pipelines
        data = await jenkins.get_pipelines()

        if not data or data.get("error"):
            logger.warning("Failed to fetch pipelines: %s", data.get("error") if data else "No response")
            return []

        pipelines = data.get("pipelines", [])

        # Filter for running pipelines
        for pipeline in pipelines:
            status = pipeline.get("status", "").lower()
            if status in ("running", "in_progress", "building"):
                running_pipelines.append(pipeline)

        # Also check Golden Regression Suite pipelines
        golden_data = await jenkins.get_golden_regression()
        if golden_data and not golden_data.get("error"):
            for pipeline in golden_data.get("pipelines", []):
                status = pipeline.get("status", "").lower()
                if status in ("running", "in_progress", "building"):
                    running_pipelines.append(pipeline)

        logger.debug("Found %d running pipelines", len(running_pipelines))
        return running_pipelines

    except Exception as e:
        logger.error("Error fetching running pipelines: %s", e)
        return []


def _calculate_running_duration(pipeline: Dict) -> Optional[timedelta]:
    """Calculate how long a pipeline has been running."""
    try:
        # Try to get timestamp from pipeline data
        timestamp_str = pipeline.get("timestamp", "")
        start_time = pipeline.get("startTime", "")

        if timestamp_str:
            # Parse timestamp (format: "2025-01-28 10:30:00" or ISO format)
            try:
                if "T" in timestamp_str:
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                return datetime.now() - dt.replace(tzinfo=None)
            except ValueError:
                pass

        if start_time:
            try:
                if isinstance(start_time, (int, float)):
                    # Unix timestamp in milliseconds
                    dt = datetime.fromtimestamp(start_time / 1000)
                    return datetime.now() - dt
                else:
                    dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
                    return datetime.now() - dt.replace(tzinfo=None)
            except (ValueError, OSError):
                pass

        # If no timestamp available, we can't calculate duration
        return None

    except Exception as e:
        logger.debug("Error calculating duration for pipeline: %s", e)
        return None


def _build_stuck_pipeline_blocks(stuck_pipelines: List[Dict]) -> List[Dict]:
    """Build Slack message blocks for stuck pipelines."""
    blocks = []

    # Header
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"⚠️ {len(stuck_pipelines)} Jenkins Pipeline{'s' if len(stuck_pipelines) > 1 else ''} Stuck",
                "emoji": True,
            },
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"The following pipeline{'s have' if len(stuck_pipelines) > 1 else ' has'} been running for more than *{THRESHOLD_MINUTES} minutes* without progress:",
            },
        }
    )

    blocks.append({"type": "divider"})

    # Pipeline details
    for pipeline in stuck_pipelines[:10]:  # Limit to 10 to avoid message size limits
        name = pipeline.get("name") or pipeline.get("fullName") or "Unknown Pipeline"
        build_number = pipeline.get("buildNumber", "N/A")
        duration = pipeline.get("running_duration", "Unknown")
        url = pipeline.get("buildUrl") or pipeline.get("url", "#")

        # Format duration
        if isinstance(duration, timedelta):
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        else:
            duration_str = str(duration)

        pipeline_text = f"*<{url}|{name}>*\n" f"Build: #{build_number} • Running for: *{duration_str}*"

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": pipeline_text},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Jenkins", "emoji": True},
                    "url": url,
                    "action_id": f"view_pipeline_{build_number}",
                },
            }
        )

    if len(stuck_pipelines) > 10:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_...and {len(stuck_pipelines) - 10} more stuck pipelines_"}],
            }
        )

    blocks.append({"type": "divider"})

    # Action suggestion
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔧 *Recommended Actions:*\n• Check Jenkins agent connectivity\n• Review pipeline logs for errors\n• Consider restarting stuck jobs",
            },
        }
    )

    # Footer
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Jenkins Monitor • {datetime.now().strftime('%b %d, %I:%M %p')}"}],
        }
    )

    return blocks


async def _send_stuck_pipeline_alert(stuck_pipelines: List[Dict]) -> bool:
    """
    Send Slack notification about stuck pipelines.
    """
    try:
        from services.slack_notifications import get_slack_service

        service = get_slack_service()
        if not service.enabled:
            logger.warning("Slack not configured, skipping stuck pipeline alert")
            return False

        blocks = _build_stuck_pipeline_blocks(stuck_pipelines)

        # Use the default channel from Slack service (configured in .env as SLACK_CHANNEL)
        result = await service.send_notification(
            blocks=blocks, text=f"⚠️ {len(stuck_pipelines)} Jenkins pipeline(s) stuck for > {THRESHOLD_MINUTES} minutes"
        )

        if result.get("success"):
            logger.info(
                "Stuck pipeline alert sent to Slack channel %s: %d pipelines", service.channel, len(stuck_pipelines)
            )
            return True
        else:
            logger.error("Failed to send stuck pipeline alert: %s", result.get("error"))
            return False

    except Exception as e:
        logger.error("Error sending stuck pipeline alert: %s", e)
        return False


async def _check_stuck_pipelines():
    """Check for stuck pipelines and send alerts."""
    global _alerted_pipelines, _last_check_time

    _last_check_time = datetime.now()

    try:
        # Fetch running pipelines
        running_pipelines = await _fetch_running_pipelines()

        if not running_pipelines:
            # Clear alerted set if no pipelines are running
            if _alerted_pipelines:
                logger.info("No running pipelines, clearing alert tracking")
                _alerted_pipelines.clear()
            return

        stuck_pipelines = []
        current_running_keys = set()

        for pipeline in running_pipelines:
            # Create unique key for pipeline
            name = pipeline.get("name") or pipeline.get("fullName", "unknown")
            build_number = pipeline.get("buildNumber", "")
            pipeline_key = f"{name}:{build_number}"
            current_running_keys.add(pipeline_key)

            # Calculate running duration
            duration = _calculate_running_duration(pipeline)

            if duration is None:
                # Can't determine duration, skip
                continue

            # Check if stuck (running longer than threshold)
            threshold = timedelta(minutes=THRESHOLD_MINUTES)
            if duration > threshold:
                # Only alert if we haven't already alerted about this pipeline
                if pipeline_key not in _alerted_pipelines:
                    pipeline["running_duration"] = duration
                    stuck_pipelines.append(pipeline)
                    logger.info("Pipeline stuck: %s (build #%s) running for %s", name, build_number, duration)

        # Remove completed pipelines from alerted set
        completed = _alerted_pipelines - current_running_keys
        if completed:
            logger.info("Pipelines completed, removing from tracking: %s", completed)
            _alerted_pipelines -= completed

        # Send alert for newly stuck pipelines
        if stuck_pipelines:
            success = await _send_stuck_pipeline_alert(stuck_pipelines)
            if success:
                # Add to alerted set to avoid duplicate notifications
                for pipeline in stuck_pipelines:
                    name = pipeline.get("name") or pipeline.get("fullName", "unknown")
                    build_number = pipeline.get("buildNumber", "")
                    _alerted_pipelines.add(f"{name}:{build_number}")

    except Exception as e:
        logger.error("Error checking stuck pipelines: %s", e, exc_info=True)


def _monitor_loop():
    """Background monitor loop - checks periodically for stuck pipelines."""
    global _monitor_running

    logger.info(
        "Jenkins pipeline monitor started - checking every %d minutes, threshold: %d minutes",
        CHECK_INTERVAL_MINUTES,
        THRESHOLD_MINUTES,
    )

    check_interval_seconds = CHECK_INTERVAL_MINUTES * 60

    while _monitor_running:
        try:
            # Run async check in event loop
            try:
                asyncio.run(_check_stuck_pipelines())
            except RuntimeError:
                # Event loop already running - use alternative
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(_check_stuck_pipelines())
                finally:
                    loop.close()

            # Wait for next check interval
            for _ in range(check_interval_seconds):
                if not _monitor_running:
                    break
                time.sleep(1)

        except Exception as e:
            logger.error("Jenkins monitor error: %s", e, exc_info=True)
            # Sleep a bit before retrying
            time.sleep(60)


def start_jenkins_monitor():
    """Start the Jenkins pipeline monitor."""
    global _monitor_running, _monitor_thread

    if not MONITOR_ENABLED:
        logger.info("Jenkins pipeline monitor disabled (JENKINS_MONITOR_ENABLED=false)")
        return

    if _monitor_running:
        logger.info("Jenkins pipeline monitor already running")
        return

    _monitor_running = True
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="jenkins-monitor")
    _monitor_thread.start()

    logger.info(
        "Jenkins pipeline monitor started - threshold: %d min, interval: %d min",
        THRESHOLD_MINUTES,
        CHECK_INTERVAL_MINUTES,
    )


def stop_jenkins_monitor():
    """Stop the Jenkins pipeline monitor."""
    global _monitor_running

    if not _monitor_running:
        return

    _monitor_running = False
    logger.info("Jenkins pipeline monitor stopped")


def get_monitor_status() -> dict:
    """Get current monitor status."""
    # Get Slack channel from the service for status display
    slack_channel = "(not configured)"
    try:
        from services.slack_notifications import get_slack_service

        service = get_slack_service()
        if service.enabled:
            slack_channel = service.channel
    except Exception:
        pass

    return {
        "enabled": MONITOR_ENABLED,
        "running": _monitor_running,
        "threshold_minutes": THRESHOLD_MINUTES,
        "check_interval_minutes": CHECK_INTERVAL_MINUTES,
        "slack_channel": slack_channel,
        "last_check": _last_check_time.isoformat() if _last_check_time else None,
        "currently_alerted": list(_alerted_pipelines),
        "alerted_count": len(_alerted_pipelines),
    }


async def trigger_check_now() -> dict:
    """Manually trigger a stuck pipeline check (for testing)."""
    await _check_stuck_pipelines()
    return {
        "success": True,
        "message": "Check completed",
        "timestamp": datetime.now().isoformat(),
        "alerted_pipelines": list(_alerted_pipelines),
    }

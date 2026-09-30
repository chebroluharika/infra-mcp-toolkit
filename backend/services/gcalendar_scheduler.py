"""
Google Calendar Sync Scheduler

Periodically syncs release calendar data from Google Calendar to keep
the portal up-to-date with any date changes.

Usage:
    from services.gcalendar_scheduler import start_gcalendar_scheduler, stop_gcalendar_scheduler

    # Start scheduler (typically in app lifespan)
    start_gcalendar_scheduler()

    # Stop scheduler (on shutdown)
    stop_gcalendar_scheduler()
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_last_sync_result: Optional[dict] = None


def get_sync_interval() -> int:
    """Get sync interval from environment (in minutes)."""
    try:
        return int(os.getenv("GOOGLE_CALENDAR_SYNC_INTERVAL", "30"))
    except ValueError:
        return 30


async def _sync_job():
    """Background job to sync Google Calendar data."""
    global _last_sync_result

    from services.gcalendar_client import sync_release_calendar

    logger.info("Running scheduled Google Calendar sync...")

    try:
        result = await sync_release_calendar()
        _last_sync_result = {
            **result,
            "job_time": datetime.now().isoformat(),
        }

        if result.get("success"):
            logger.info(f"Google Calendar sync completed: {result.get('releases_synced', 0)} releases synced")
        else:
            logger.warning(f"Google Calendar sync failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        logger.error(f"Google Calendar sync job error: {e}")
        _last_sync_result = {
            "success": False,
            "error": str(e),
            "job_time": datetime.now().isoformat(),
        }


def start_gcalendar_scheduler():
    """Start the Google Calendar sync scheduler."""
    global _scheduler

    # Check if calendar is configured
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "")
    if not calendar_id:
        logger.info("Google Calendar not configured, skipping scheduler setup")
        return

    if _scheduler is not None:
        logger.warning("Google Calendar scheduler already running")
        return

    interval_minutes = get_sync_interval()

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _sync_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="gcalendar_sync",
        name="Google Calendar Sync",
        replace_existing=True,
    )
    _scheduler.start()

    logger.info(f"Google Calendar scheduler started (interval: {interval_minutes} minutes)")

    # Run initial sync after a short delay (don't block startup)
    async def _delayed_initial_sync():
        await asyncio.sleep(10)
        await _sync_job()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_delayed_initial_sync())
        else:
            loop.run_until_complete(_sync_job())
    except RuntimeError:
        pass


def stop_gcalendar_scheduler():
    """Stop the Google Calendar sync scheduler."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Google Calendar scheduler stopped")


def get_last_sync_result() -> Optional[dict]:
    """Get the result of the last sync operation."""
    return _last_sync_result


async def trigger_manual_sync() -> dict:
    """Manually trigger a calendar sync (for API endpoint)."""
    await _sync_job()
    return _last_sync_result or {"success": False, "error": "No sync result available"}

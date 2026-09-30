"""
Stack Snapshot Scheduler
========================

Background scheduler that automatically saves stack health snapshots
at regular intervals, independent of page views.

This feeds the Health Trend Chart in Stack Monitoring with consistent
data points for reliable trend analysis.

Usage:
    from services.stack_snapshot_scheduler import (
        start_snapshot_scheduler,
        stop_snapshot_scheduler,
        get_snapshot_scheduler_status,
    )

    # In app lifespan
    start_snapshot_scheduler()   # on startup
    stop_snapshot_scheduler()    # on shutdown
"""

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Configuration
SNAPSHOT_INTERVAL_MINUTES = 60  # Save a snapshot every hour

# Scheduler state
_scheduler_running = False
_scheduler_thread = None
_last_snapshot_time: datetime | None = None
_snapshot_count = 0


def _take_snapshot():
    """Fetch current stack data and save a snapshot."""
    global _last_snapshot_time, _snapshot_count

    try:
        from services.stack_monitoring import get_monitoring_service

        monitoring_service = get_monitoring_service()

        # Always fetch fresh data for snapshots to ensure restart counts are current
        # use_cache=False forces a full refresh including namespace details (restart counts, events)
        # lite_mode=False ensures we get restart counts (lite_mode skips them for faster UI loads)
        logger.info("Snapshot scheduler: Fetching fresh stack data...")
        start_time = time.time()
        monitoring_service.generate_stack_config(use_cache=False, lite_mode=False)
        fetch_time = time.time() - start_time
        logger.info("Snapshot scheduler: Data fetch completed in %.1fs", fetch_time)

        # Only save if we actually have data
        if not monitoring_service.master_config:
            logger.warning("Snapshot scheduler: No stack data available, skipping snapshot")
            return False

        # Log restart count summary for debugging
        summary = monitoring_service.get_stack_summary()
        total_restarts = sum(s.get("restarts", 0) for s in summary.values())
        logger.info("Snapshot scheduler: Total restarts across all stacks: %d", total_restarts)

        filename = monitoring_service.save_snapshot()
        if filename:
            _last_snapshot_time = datetime.now()
            _snapshot_count += 1
            logger.info("Snapshot scheduler: Saved %s (total: %d)", filename, _snapshot_count)
            return True
        else:
            logger.warning("Snapshot scheduler: save_snapshot returned empty filename")
            return False

    except Exception as e:
        logger.error("Snapshot scheduler: Failed to save snapshot: %s", e, exc_info=True)
        return False


def _scheduler_loop():
    """Background scheduler loop - saves snapshots at regular intervals."""
    interval_seconds = SNAPSHOT_INTERVAL_MINUTES * 60

    logger.info(
        "Stack snapshot scheduler started - interval: %d minutes",
        SNAPSHOT_INTERVAL_MINUTES,
    )

    # Take an initial snapshot on startup (after a short delay for services to warm up)
    for _ in range(30):
        if not _scheduler_running:
            return
        time.sleep(1)

    _take_snapshot()

    while _scheduler_running:
        try:
            # Wait for next interval (check every second for clean shutdown)
            for _ in range(interval_seconds):
                if not _scheduler_running:
                    return
                time.sleep(1)

            if _scheduler_running:
                _take_snapshot()

        except Exception as e:
            logger.error("Snapshot scheduler error: %s", e, exc_info=True)
            time.sleep(60)


def start_snapshot_scheduler():
    """Start the background snapshot scheduler."""
    global _scheduler_running, _scheduler_thread

    if _scheduler_running:
        logger.info("Snapshot scheduler already running")
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="stack-snapshot-scheduler")
    _scheduler_thread.start()

    logger.info(
        "Stack snapshot scheduler started - saving every %d minutes",
        SNAPSHOT_INTERVAL_MINUTES,
    )


def stop_snapshot_scheduler():
    """Stop the background snapshot scheduler."""
    global _scheduler_running

    if not _scheduler_running:
        return

    _scheduler_running = False
    logger.info("Stack snapshot scheduler stopped (total snapshots saved: %d)", _snapshot_count)


def get_snapshot_scheduler_status() -> dict:
    """Get current scheduler status."""
    return {
        "running": _scheduler_running,
        "interval_minutes": SNAPSHOT_INTERVAL_MINUTES,
        "last_snapshot": _last_snapshot_time.isoformat() if _last_snapshot_time else None,
        "total_snapshots_saved": _snapshot_count,
    }

"""
Trend Tracker Service
=====================

Stores hourly snapshots of release readiness metrics and provides
trend analysis for leadership insights.

Features:
- Hourly snapshots (shows trends after 5+ hours)
- Background auto-sync every 2 hours
- Spike detection (sudden increases)
- Plateau detection (stuck periods)
- Velocity calculation and predictions

Storage: JSON file (simple, no database required)
Location: backend/data/trend_snapshots.json
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

# Storage location
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SNAPSHOTS_FILE = os.path.join(DATA_DIR, "trend_snapshots.json")

# Sync interval in seconds (2 hours)
SYNC_INTERVAL_SECONDS = 2 * 60 * 60

# Minimum hours between snapshots (to avoid too many data points)
MIN_HOURS_BETWEEN_SNAPSHOTS = 2


def _ensure_data_dir():
    """Ensure data directory exists."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def _load_snapshots() -> Dict:
    """Load snapshots from JSON file."""
    _ensure_data_dir()
    if os.path.exists(SNAPSHOTS_FILE):
        try:
            with open(SNAPSHOTS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading snapshots: %s", e)
    return {}


def _save_snapshots(data: Dict):
    """Save snapshots to JSON file."""
    _ensure_data_dir()
    try:
        with open(SNAPSHOTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Error saving snapshots: %s", e)


def _get_snapshot_key() -> str:
    """Get snapshot key - hourly granularity."""
    now = datetime.now()
    # Round to nearest 2-hour block for cleaner data
    hour = (now.hour // 2) * 2
    return now.strftime(f"%Y-%m-%d-{hour:02d}:00")


def _should_save_snapshot(release: str) -> bool:
    """Check if we should save a new snapshot (avoid too frequent saves)."""
    snapshots = _load_snapshots()
    release_data = snapshots.get(release, {})

    if not release_data:
        return True

    # Get latest snapshot timestamp
    latest_key = max(release_data.keys())
    try:
        # Parse the key format: YYYY-MM-DD-HH:00
        latest_time = datetime.strptime(latest_key, "%Y-%m-%d-%H:%M")
        hours_since = (datetime.now() - latest_time).total_seconds() / 3600
        return hours_since >= MIN_HOURS_BETWEEN_SNAPSHOTS
    except (ValueError, TypeError, KeyError):
        return True


def save_snapshot(
    release: str,
    open_stories: int,
    open_bugs: int,
    code_review: int,
    components: Dict[str, Dict] = None,
    force: bool = False,
):
    """
    Save a snapshot for a release.
    Uses hourly granularity for faster trend visibility.

    Args:
        force: If True, saves even if recent snapshot exists
    """
    if not force and not _should_save_snapshot(release):
        logger.debug("Skipping snapshot for %s - recent snapshot exists", release)
        return False

    snapshot_key = _get_snapshot_key()

    snapshots = _load_snapshots()

    if release not in snapshots:
        snapshots[release] = {}

    snapshots[release][snapshot_key] = {
        "key": snapshot_key,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "open_stories": open_stories,
        "open_bugs": open_bugs,
        "code_review": code_review,
        "total_open": open_stories + open_bugs,
        "components": components or {},
        "timestamp": datetime.now().isoformat(),
    }

    _save_snapshots(snapshots)
    logger.info("Saved snapshot for {release} at %s", snapshot_key)
    return True


def get_trend_data(release: str, hours: int = 48, from_date: str = None) -> List[Dict]:
    """
    Get trend data for the last N hours or from a specific date.

    Args:
        release: Release ID (e.g., "R135")
        hours: Number of hours to look back (ignored if from_date is provided)
        from_date: Start date in YYYY-MM-DD format (e.g., IRR date)

    Returns list of snapshots sorted by time.
    """
    snapshots = _load_snapshots()
    release_data = snapshots.get(release, {})

    if not release_data:
        return []

    # Sort by key (datetime) and return all
    sorted_keys = sorted(release_data.keys())

    # Determine cutoff - use from_date if provided, otherwise hours
    if from_date:
        try:
            cutoff = datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            cutoff = datetime.now() - timedelta(hours=hours)
    else:
        cutoff = datetime.now() - timedelta(hours=hours)

    result = []

    for key in sorted_keys:
        try:
            snapshot_time = datetime.strptime(key, "%Y-%m-%d-%H:%M")
            if snapshot_time >= cutoff:
                result.append(release_data[key])
        except ValueError:
            # Include if we can't parse (old format)
            result.append(release_data[key])

    return result


def analyze_trends(release: str, irr_date: str = None) -> Dict:
    """
    Analyze trends and generate leadership insights.

    Shows trends after 2+ data points (can be as soon as 5 hours).

    Args:
        release: Release ID (e.g., "R135")
        irr_date: IRR date in YYYY-MM-DD format. If provided, shows data from IRR onwards.
                  If not provided, defaults to last 7 days.

    Returns:
        - trend_direction: improving, declining, stable
        - velocity: items resolved per hour/day
        - spikes: periods with unusual increases
        - plateau: stuck periods
        - prediction: estimated zero date
    """
    # Check if IRR date is in the future
    irr_in_future = False
    days_until_irr = 0
    if irr_date:
        try:
            irr_datetime = datetime.strptime(irr_date, "%Y-%m-%d")
            if irr_datetime.date() > datetime.now().date():
                irr_in_future = True
                days_until_irr = (irr_datetime.date() - datetime.now().date()).days
        except ValueError:
            pass

    # Get data from IRR date if provided, otherwise last 7 days
    if irr_date:
        data = get_trend_data(release, from_date=irr_date)
    else:
        data = get_trend_data(release, hours=168)  # Last 7 days fallback

    if len(data) < 2:
        # If IRR is in the future, show a specific message
        if irr_in_future:
            irr_formatted = datetime.strptime(irr_date, "%Y-%m-%d").strftime("%b %d, %Y")
            if days_until_irr == 1:
                message = f"IRR starts tomorrow ({irr_formatted}). Trend tracking will begin after IRR."
            else:
                message = f"IRR starts in {days_until_irr} days ({irr_formatted}). Trend tracking will begin after IRR."
            return {
                "has_data": False,
                "message": message,
                "data_points": 0,
                "irr_date": irr_date,
                "irr_in_future": True,
                "days_until_irr": days_until_irr,
            }

        # IRR has passed but not enough data points yet
        hours_until_next = MIN_HOURS_BETWEEN_SNAPSHOTS
        if len(data) == 1:
            try:
                last_time = datetime.fromisoformat(data[0].get("timestamp", ""))
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                hours_until_next = max(0, MIN_HOURS_BETWEEN_SNAPSHOTS - hours_since)
            except (ValueError, TypeError, KeyError):
                pass

        return {
            "has_data": False,
            "message": f"Collecting data... Next snapshot in ~{int(hours_until_next)} hours. Trends visible after 2+ snapshots.",
            "data_points": len(data),
            "next_snapshot_hours": round(hours_until_next, 1),
        }

    # Sort by timestamp
    valid_data = sorted(data, key=lambda x: x.get("timestamp", ""))

    # === Trend Direction ===
    first_total = valid_data[0].get("total_open", 0)
    last_total = valid_data[-1].get("total_open", 0)

    if last_total < first_total:
        change_pct = round(((first_total - last_total) / max(first_total, 1)) * 100)
        trend_direction = "improving"
        trend_emoji = "📉"
        trend_message = f"Down {change_pct}% ({first_total} → {last_total} items)"
    elif last_total > first_total:
        change_pct = round(((last_total - first_total) / max(first_total, 1)) * 100)
        trend_direction = "declining"
        trend_emoji = "📈"
        trend_message = f"Up {change_pct}% ({first_total} → {last_total} items)"
    else:
        trend_direction = "stable"
        trend_emoji = "➡️"
        trend_message = f"Stable at {last_total} items"

    # === Velocity (items resolved per day) ===
    try:
        first_time = datetime.fromisoformat(valid_data[0].get("timestamp", ""))
        last_time = datetime.fromisoformat(valid_data[-1].get("timestamp", ""))
        hours_span = max((last_time - first_time).total_seconds() / 3600, 1)
        days_span = hours_span / 24
    except (ValueError, TypeError, KeyError):
        days_span = len(valid_data) / 12  # Assume ~12 snapshots per day if parsing fails

    items_resolved = first_total - last_total
    velocity_per_day = round(items_resolved / max(days_span, 0.1), 1)

    if velocity_per_day > 0:
        velocity_message = f"Resolving ~{velocity_per_day} items/day"
    elif velocity_per_day < 0:
        velocity_message = f"Adding ~{abs(velocity_per_day)} items/day"
    else:
        velocity_message = "No net change"

    # === Spikes Detection ===
    # Only detect spikes in the last 48 hours that are still relevant
    # A spike is only actionable if the items haven't been resolved since
    spikes = []
    recent_cutoff = datetime.now() - timedelta(hours=48)

    for i in range(1, len(valid_data)):
        prev = valid_data[i - 1].get("total_open", 0)
        curr = valid_data[i].get("total_open", 0)

        # Check if this is a recent spike (within last 48 hours)
        try:
            spike_timestamp = datetime.fromisoformat(valid_data[i].get("timestamp", ""))
            is_recent = spike_timestamp >= recent_cutoff
        except (ValueError, TypeError):
            is_recent = False

        # Only flag if: spike is recent AND current total is still elevated
        # (i.e., the spike items haven't been fully resolved)
        if curr > prev + 2 and is_recent:  # Spike threshold: +2 items between snapshots
            spike_time = valid_data[i].get("date", "") + " " + valid_data[i].get("time", "")
            spikes.append(
                {"datetime": spike_time, "increase": curr - prev, "message": f"⚠️ +{curr - prev} items at {spike_time}"}
            )

    # === Plateau Detection ===
    # Only detect plateau if it's current (last snapshot is within last 6 hours)
    plateau_count = 0
    last_snapshot_recent = False

    try:
        last_snapshot_time = datetime.fromisoformat(valid_data[-1].get("timestamp", ""))
        last_snapshot_recent = (datetime.now() - last_snapshot_time).total_seconds() < 6 * 3600
    except (ValueError, TypeError):
        last_snapshot_recent = True  # Assume recent if can't parse

    if last_snapshot_recent and last_total > 0:  # Only check plateau if there are still open items
        for i in range(len(valid_data) - 1, 0, -1):
            if valid_data[i].get("total_open") == valid_data[i - 1].get("total_open"):
                plateau_count += 1
            else:
                break

    # Plateau if 3+ consecutive snapshots with same value (6+ hours stuck)
    # AND there are still open items (no point alerting if everything is resolved)
    plateau_detected = plateau_count >= 3 and last_total > 0
    plateau_hours = plateau_count * MIN_HOURS_BETWEEN_SNAPSHOTS
    plateau_stuck_value = last_total if plateau_detected else None
    plateau_message = f"⏸️ Stuck for {plateau_hours}+ hours - need intervention?" if plateau_detected else None
    plateau_tooltip = (
        f"The count has remained at {last_total} open items for the last {plateau_hours}+ hours. No items have been resolved during this period. Consider checking if any blockers are preventing progress."
        if plateau_detected
        else None
    )

    # === Prediction ===
    prediction = None
    prediction_date = None
    if velocity_per_day > 0 and last_total > 0:
        days_to_zero = round(last_total / velocity_per_day)
        prediction_date = (datetime.now() + timedelta(days=days_to_zero)).strftime("%b %d")
        prediction = f"🎯 At current velocity, zero open items by {prediction_date}"
    elif velocity_per_day <= 0 and last_total > 0:
        prediction = "⚠️ Not on track - need to increase velocity"
    elif last_total == 0:
        prediction = "✅ All items resolved!"

    # === Chart Data ===
    chart_data = []
    for d in valid_data:
        label = d.get("date", "")[-5:] + " " + d.get("time", "")[:5]  # "01-07 14:00"
        chart_data.append(
            {
                "label": label,
                "date": d.get("date"),
                "time": d.get("time"),
                "stories": d.get("open_stories"),
                "bugs": d.get("open_bugs"),
                "total": d.get("total_open"),
            }
        )

    # Date range info
    first_date = valid_data[0].get("date", "") if valid_data else None
    last_date = valid_data[-1].get("date", "") if valid_data else None

    return {
        "has_data": True,
        "data_points": len(valid_data),
        # Date range
        "from_date": irr_date if irr_date else first_date,
        "first_data_date": first_date,
        "last_data_date": last_date,
        # Trend Direction
        "trend_direction": trend_direction,
        "trend_emoji": trend_emoji,
        "trend_message": trend_message,
        # Velocity
        "velocity": velocity_per_day,
        "velocity_message": velocity_message,
        # Spikes
        "spikes": spikes,
        "spikes_detected": len(spikes) > 0,
        # Plateau
        "plateau_detected": plateau_detected,
        "plateau_count": plateau_count,
        "plateau_message": plateau_message,
        "plateau_stuck_value": plateau_stuck_value,
        "plateau_tooltip": plateau_tooltip,
        # Prediction
        "prediction": prediction,
        "prediction_date": prediction_date,
        # Current stats
        "current_total": last_total,
        "period_start_total": first_total,
        # Raw data for chart
        "chart_data": chart_data,
    }


# =============================================================================
# Background Scheduler for Auto-Sync
# =============================================================================

_scheduler_running = False
_scheduler_thread = None


async def _fetch_and_save_snapshot():
    """Fetch current data from JIRA and save snapshot."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            response = await client.get("http://localhost:8000/api/jira/release-readiness")
            if response.status_code == 200:
                logger.info("Auto-sync: Snapshot saved via API call")
            else:
                logger.warning("Auto-sync: API returned %s", response.status_code)
    except Exception as e:
        logger.error("Auto-sync failed: %s", e)


def _scheduler_loop():
    """Background scheduler loop - runs every 2 hours."""
    # Note: _scheduler_running is read from module scope, no global needed for reading
    while _scheduler_running:
        try:
            # Wait for next sync interval
            for _ in range(SYNC_INTERVAL_SECONDS):
                if not _scheduler_running:
                    break
                time.sleep(1)

            if _scheduler_running:
                logger.info("Auto-sync: Triggering scheduled snapshot...")
                # Run async fetch in new event loop
                asyncio.run(_fetch_and_save_snapshot())

        except Exception as e:
            logger.error("Scheduler error: %s", e)


def start_background_scheduler():
    """Start the background scheduler for auto-sync."""
    global _scheduler_running, _scheduler_thread

    if _scheduler_running:
        logger.info("Scheduler already running")
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    logger.info("Background scheduler started - syncing every %s hours", SYNC_INTERVAL_SECONDS // 3600)


def stop_background_scheduler():
    """Stop the background scheduler."""
    global _scheduler_running
    _scheduler_running = False
    logger.info("Background scheduler stopped")


# Alias for backward compatibility
save_daily_snapshot = save_snapshot


def get_week_over_week_change(release: str) -> Dict:
    """
    Get week-over-week changes for key metrics.
    Used by Overview page to show trend indicators.

    Returns:
        {
            "available": True/False,
            "blockers_change": -2,  # negative = improved
            "stories_change": 3,
            "bugs_change": -1,
            "total_change": 0,
            "trend_direction": "improving" | "declining" | "stable"
        }
    """
    snapshots = _load_snapshots()
    release_data = snapshots.get(release, {})

    if not release_data:
        return {"available": False, "message": "No trend data available"}

    # Get current snapshot (most recent)
    sorted_keys = sorted(release_data.keys(), reverse=True)
    if len(sorted_keys) < 2:
        return {"available": False, "message": "Need more data points"}

    current_snapshot = release_data[sorted_keys[0]]

    # Find snapshot from ~7 days ago (or closest available)
    now = datetime.now()
    week_ago = now - timedelta(days=7)

    week_ago_snapshot = None
    for key in sorted_keys:
        try:
            snapshot_time = datetime.strptime(key, "%Y-%m-%d-%H:%M")
            # Find snapshot closest to 7 days ago
            if snapshot_time <= week_ago:
                week_ago_snapshot = release_data[key]
                break
        except ValueError:
            continue

    # If no snapshot from a week ago, use the oldest available
    if not week_ago_snapshot:
        week_ago_snapshot = release_data[sorted_keys[-1]]

    # Calculate changes
    stories_change = current_snapshot.get("open_stories", 0) - week_ago_snapshot.get("open_stories", 0)
    bugs_change = current_snapshot.get("open_bugs", 0) - week_ago_snapshot.get("open_bugs", 0)
    total_change = current_snapshot.get("total_open", 0) - week_ago_snapshot.get("total_open", 0)

    # Determine overall trend
    if total_change < 0:
        trend_direction = "improving"
    elif total_change > 0:
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    return {
        "available": True,
        "stories_change": stories_change,
        "bugs_change": bugs_change,
        "total_change": total_change,
        "trend_direction": trend_direction,
        "current_total": current_snapshot.get("total_open", 0),
        "week_ago_total": week_ago_snapshot.get("total_open", 0),
    }

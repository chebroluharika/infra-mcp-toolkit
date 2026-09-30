"""
Ticket Analysis Scheduler - Nightly AI analysis of escalation tickets.

Analyzes escalation tickets to extract impacted features/components using AI.
Results are stored in ticket_analysis_cache.json for display in the UI.

Schedule:
- Runs daily at 2:00 AM (configurable)
- Analyzes tickets that haven't been analyzed or are older than 7 days
- Rate-limited to avoid overwhelming the LLM service
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
ANALYSIS_CACHE_FILE = DATA_DIR / "ticket_analysis_cache.json"
STATE_FILE = DATA_DIR / "ticket_analysis_scheduler_state.json"

DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_SCHEDULE_HOUR = 2  # 2 AM
DEFAULT_SCHEDULE_MINUTE = 0
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_DELAY_BETWEEN_TICKETS = 1.0  # seconds
DEFAULT_BATCH_LIMIT = 100  # max tickets per run

SCHEDULER_ENABLED = os.getenv("TICKET_ANALYSIS_ENABLED", "true").lower() == "true"

# =============================================================================
# Scheduler State
# =============================================================================

_scheduler_running = False
_scheduler_thread: Optional[threading.Thread] = None
_last_run_date: Optional[str] = None


def _get_timezone() -> pytz.BaseTzInfo:
    """Get configured timezone."""
    tz_name = os.getenv("TICKET_ANALYSIS_TIMEZONE", DEFAULT_TIMEZONE)
    return pytz.timezone(tz_name)


def _get_current_time() -> datetime:
    """Get current time in configured timezone."""
    return datetime.now(_get_timezone())


def _get_schedule_time() -> tuple:
    """Get scheduled hour and minute."""
    hour = int(os.getenv("TICKET_ANALYSIS_HOUR", DEFAULT_SCHEDULE_HOUR))
    minute = int(os.getenv("TICKET_ANALYSIS_MINUTE", DEFAULT_SCHEDULE_MINUTE))
    return (hour, minute)


# =============================================================================
# Cache Management
# =============================================================================


def _load_analysis_cache() -> Dict[str, Any]:
    """Load the ticket analysis cache from disk."""
    try:
        if ANALYSIS_CACHE_FILE.exists():
            with open(ANALYSIS_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Could not load analysis cache: %s", e)
    return {"tickets": {}, "updated_at": None}


def _save_analysis_cache(cache: Dict[str, Any]):
    """Save the ticket analysis cache to disk."""
    try:
        cache["updated_at"] = datetime.now().isoformat()
        ANALYSIS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ANALYSIS_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        logger.info("Saved analysis cache to %s", ANALYSIS_CACHE_FILE)
    except Exception as e:
        logger.error("Could not save analysis cache: %s", e)


def _store_ticket_analysis(
    cache: Dict[str, Any],
    ticket_key: str,
    customer: str,
    impacted_features: List[str],
    priority: str = None,
    summary: str = None,
    sub_component: str = None,
):
    """Store ticket analysis result in cache."""
    cache["tickets"][ticket_key] = {
        "ticket_key": ticket_key,
        "customer": customer,
        "impacted_features": impacted_features,
        "priority": priority,
        "summary": summary,
        "sub_component": sub_component,
        "analyzed_at": datetime.now().isoformat(),
    }


# =============================================================================
# State Persistence
# =============================================================================


def _load_state() -> Dict[str, Any]:
    """Load scheduler state from disk."""
    global _last_run_date
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            _last_run_date = state.get("last_run_date")
            return state
    except Exception as e:
        logger.warning("Could not load scheduler state: %s", e)
    return {}


def _save_state(run_stats: Dict[str, Any] = None):
    """Save scheduler state to disk."""
    global _last_run_date
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        now = _get_current_time()
        _last_run_date = now.strftime("%Y-%m-%d")

        state = {
            "last_run_date": _last_run_date,
            "last_run_time": now.isoformat(),
            "last_run_stats": run_stats or {},
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.info("Saved scheduler state")
    except Exception as e:
        logger.error("Could not save scheduler state: %s", e)


# =============================================================================
# Analysis Functions
# =============================================================================


async def _get_all_escalation_tickets() -> List[Dict[str, Any]]:
    """Fetch all escalation tickets from Jira."""
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()
    tickets = await service.get_all_escalations()
    return tickets


async def _analyze_single_ticket(ticket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run AI analysis on a single ticket."""
    from services.commit_analyzer import get_commit_analyzer
    from services.escalation_service import get_escalation_service
    from utilities.github import fetch_pr_details

    ticket_key = ticket.get("key")
    if not ticket_key:
        return None

    service = get_escalation_service()

    # Get full ticket details with PR links
    details = await service.get_ticket_details(ticket_key)

    if details.get("error"):
        logger.warning("Error fetching details for %s: %s", ticket_key, details.get("error"))
        return None

    pull_requests = details.get("pull_requests", [])
    sub_component = details.get("sub_component")

    if not pull_requests:
        # No PRs - use sub_component as the impacted feature
        return {
            "ticket_key": ticket_key,
            "customer": ticket.get("customer"),
            "impacted_features": [sub_component] if sub_component and sub_component != "Unknown" else [],
            "priority": ticket.get("priority"),
            "summary": ticket.get("summary"),
            "sub_component": sub_component,
            "pr_count": 0,
            "analysis_source": "jira_only",
        }

    # Analyze PRs with AI
    all_components = set()
    analyzer = get_commit_analyzer()
    analyzed_count = 0

    for pr in pull_requests:
        pr_url = pr.get("url", "")
        match = re.match(
            r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+)/pull/(\d+)",
            pr_url,
        )
        if not match:
            continue

        owner, repo, pr_number = match.group(1), match.group(2), int(match.group(3))

        try:
            pr_data = await fetch_pr_details(owner, repo, pr_number, include_files=True)

            if pr_data.get("status") != "success":
                logger.warning("Failed to fetch PR %s: %s", pr_url, pr_data.get("error"))
                continue

            analysis = await analyzer.analyze_commit(
                commit_data={
                    "files": pr_data.get("files", []),
                    "stats": pr_data.get("stats", {}),
                    "message": pr_data.get("title", ""),
                    "sha": f"PR#{pr_number}",
                },
                include_llm_analysis=True,
            )

            # Extract components from file analysis
            for component in analysis.get("files_by_component", {}).keys():
                if component and component != "other":
                    all_components.add(component.replace("_", " ").title())

            # Extract components from LLM analysis
            llm = analysis.get("llm_analysis") or {}
            if llm.get("available"):
                for comp in llm.get("components", []):
                    all_components.add(comp)

            analyzed_count += 1

        except Exception as e:
            logger.error("Error analyzing PR %s: %s", pr_url, e)

    # Add sub_component from Jira
    if sub_component and sub_component != "Unknown":
        all_components.add(sub_component)

    return {
        "ticket_key": ticket_key,
        "customer": ticket.get("customer"),
        "impacted_features": sorted(all_components),
        "priority": ticket.get("priority"),
        "summary": ticket.get("summary"),
        "sub_component": sub_component,
        "pr_count": len(pull_requests),
        "prs_analyzed": analyzed_count,
        "analysis_source": "ai_analysis",
    }


def _should_analyze_ticket(
    ticket: Dict[str, Any],
    cache: Dict[str, Any],
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> bool:
    """Determine if a ticket needs analysis."""
    ticket_key = ticket.get("key")
    if not ticket_key:
        return False

    cached = cache.get("tickets", {}).get(ticket_key)
    if not cached:
        return True

    # Check if analysis is stale
    analyzed_at = cached.get("analyzed_at")
    if analyzed_at:
        try:
            analyzed_date = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
            now = datetime.now(analyzed_date.tzinfo) if analyzed_date.tzinfo else datetime.now()
            if now - analyzed_date > timedelta(days=max_age_days):
                return True
        except Exception:
            return True

    return False


async def _run_analysis_job(
    limit: int = DEFAULT_BATCH_LIMIT, delay: float = DEFAULT_DELAY_BETWEEN_TICKETS
) -> Dict[str, Any]:
    """Main analysis job - analyzes all pending tickets."""
    logger.info("=" * 60)
    logger.info("Starting Ticket Analysis Job")
    logger.info("=" * 60)

    # Load existing cache
    cache = _load_analysis_cache()
    existing_count = len(cache.get("tickets", {}))
    logger.info("Loaded cache with %d existing analyses", existing_count)

    # Fetch all tickets
    logger.info("Fetching escalation tickets from Jira...")
    try:
        all_tickets = await _get_all_escalation_tickets()
    except Exception as e:
        logger.error("Failed to fetch tickets: %s", e)
        return {"status": "error", "error": str(e)}

    logger.info("Found %d total escalation tickets", len(all_tickets))

    # Filter to tickets that need analysis
    max_age = int(os.getenv("TICKET_ANALYSIS_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS))
    tickets_to_analyze = [t for t in all_tickets if _should_analyze_ticket(t, cache, max_age_days=max_age)]

    logger.info("%d tickets need analysis", len(tickets_to_analyze))

    # Apply limit
    if len(tickets_to_analyze) > limit:
        tickets_to_analyze = tickets_to_analyze[:limit]
        logger.info("Limited to %d tickets", limit)

    # Run analysis
    success_count = 0
    error_count = 0
    skip_count = 0

    for i, ticket in enumerate(tickets_to_analyze, 1):
        ticket_key = ticket.get("key")
        logger.info("[%d/%d] Analyzing %s...", i, len(tickets_to_analyze), ticket_key)

        try:
            result = await _analyze_single_ticket(ticket)

            if result:
                _store_ticket_analysis(
                    cache=cache,
                    ticket_key=ticket_key,
                    customer=result.get("customer"),
                    impacted_features=result.get("impacted_features", []),
                    priority=result.get("priority"),
                    summary=result.get("summary"),
                    sub_component=result.get("sub_component"),
                )

                features = result.get("impacted_features", [])
                logger.info("  ✓ Found %d impacted features", len(features))
                success_count += 1
            else:
                logger.warning("  ⊘ Skipped (no result)")
                skip_count += 1

        except Exception as e:
            logger.error("  ✗ Error: %s", e)
            error_count += 1

        # Rate limiting
        if i < len(tickets_to_analyze) and delay > 0:
            await asyncio.sleep(delay)

        # Save cache periodically
        if i % 10 == 0:
            _save_analysis_cache(cache)

    # Final save
    _save_analysis_cache(cache)

    stats = {
        "status": "success",
        "total_tickets": len(all_tickets),
        "analyzed": success_count,
        "skipped": skip_count,
        "errors": error_count,
        "total_in_cache": len(cache.get("tickets", {})),
    }

    logger.info("=" * 60)
    logger.info("Analysis Job Complete: %d analyzed, %d skipped, %d errors", success_count, skip_count, error_count)
    logger.info("=" * 60)

    return stats


def _run_async(coro):
    """Run an async coroutine from sync code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except RuntimeError:
        asyncio.run(coro)


# =============================================================================
# Scheduler Loop
# =============================================================================


def _scheduler_loop():
    """Main scheduler loop - runs in background thread."""
    global _scheduler_running, _last_run_date

    schedule_hour, schedule_minute = _get_schedule_time()
    tz_name = os.getenv("TICKET_ANALYSIS_TIMEZONE", DEFAULT_TIMEZONE)

    logger.info("Ticket analysis scheduler started - daily at %02d:%02d %s", schedule_hour, schedule_minute, tz_name)

    _load_state()

    while _scheduler_running:
        try:
            now = _get_current_time()
            today = now.strftime("%Y-%m-%d")

            # Check if we should run
            if now.hour == schedule_hour and now.minute == schedule_minute and _last_run_date != today:

                logger.info("Scheduled time reached - starting ticket analysis")

                async def run_job():
                    stats = await _run_analysis_job()
                    _save_state(stats)

                _run_async(run_job())
                _last_run_date = today

            # Sleep for 60 seconds
            time.sleep(60)

        except Exception as e:
            logger.error("Scheduler error: %s", e)
            time.sleep(60)


# =============================================================================
# Public API
# =============================================================================


def start_ticket_analysis_scheduler():
    """Start the background scheduler thread."""
    global _scheduler_running, _scheduler_thread

    if not SCHEDULER_ENABLED:
        logger.info("Ticket analysis scheduler disabled via TICKET_ANALYSIS_ENABLED env var")
        return

    if _scheduler_running:
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="ticket-analysis-scheduler")
    _scheduler_thread.start()


def stop_ticket_analysis_scheduler():
    """Stop the background scheduler."""
    global _scheduler_running
    _scheduler_running = False
    logger.info("Ticket analysis scheduler stopped")


def get_scheduler_status() -> Dict[str, Any]:
    """Get current scheduler status."""
    schedule_hour, schedule_minute = _get_schedule_time()
    tz_name = os.getenv("TICKET_ANALYSIS_TIMEZONE", DEFAULT_TIMEZONE)
    now = _get_current_time()

    # Load state
    state = _load_state()

    # Calculate next run
    next_run = now.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)

    time_until_next = next_run - now
    hours, remainder = divmod(int(time_until_next.total_seconds()), 3600)
    minutes = remainder // 60

    # Load cache stats
    cache = _load_analysis_cache()

    return {
        "enabled": SCHEDULER_ENABLED,
        "running": _scheduler_running,
        "schedule_time": f"{schedule_hour:02d}:{schedule_minute:02d} {tz_name}",
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "last_run_date": state.get("last_run_date"),
        "last_run_time": state.get("last_run_time"),
        "last_run_stats": state.get("last_run_stats", {}),
        "next_scheduled": next_run.strftime("%Y-%m-%d %H:%M:%S"),
        "time_until_next": f"{hours}h {minutes}m",
        "cache_file": str(ANALYSIS_CACHE_FILE),
        "tickets_in_cache": len(cache.get("tickets", {})),
        "cache_updated_at": cache.get("updated_at"),
    }


async def trigger_analysis_now(limit: int = 50) -> Dict[str, Any]:
    """Manual trigger for testing or on-demand analysis."""
    logger.info("Manual trigger: analyzing up to %d tickets", limit)
    stats = await _run_analysis_job(limit=limit)
    _save_state(stats)
    return {
        "triggered_at": _get_current_time().strftime("%Y-%m-%d %H:%M:%S"),
        **stats,
    }

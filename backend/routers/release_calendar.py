"""
Release Calendar API Router

Provides endpoints for release calendar data from Google Calendar or PDF files.
Supports automatic sync from Google Calendar for live date updates.

Data Sources:
1. Google Calendar (preferred) - auto-syncs periodically
2. PDF file (fallback) - manual updates

Milestones:
- IRR
- Branch Cut - EP
- Final Build - EP
- Signoff STG/FedAlpha - ENG
- Deploy MP Pre PROD
- Deploy Prod Day 1-4
"""

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from services.release_calendar_parser import get_release_calendar_data, get_release_calendar_data_async

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/release-calendar",
    tags=["release-calendar"],
)

# Default PDF path (can be configured via environment)
DEFAULT_PDF_PATH = os.environ.get(
    "RELEASE_CALENDAR_PDF_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "release_calendar.pdf"),
)


@router.get("/releases")
async def get_releases() -> dict[str, Any]:
    """
    Get all releases with their complete milestone calendar dates.

    PURPOSE:
        Returns the full release calendar showing all releases with their
        milestone dates (IRR, Branch Cut, Final Build, Deploy Days 1-4).
        Used to display the Release Calendar page.

    WHEN TO USE:
        - Displaying Release Calendar page
        - Looking up milestone dates for any release
        - Planning around release timelines
        - Viewing upcoming deployment dates

    RETURNS:
        {
            "releases": [
                {
                    "id": 1,
                    "name": "R135.0",
                    "type": "Major Release",
                    "status": "In Progress",
                    "milestones": {
                        "IRR": "10-Jan-2026",
                        "Branch Cut - EP": "17-Jan-2026",
                        "Final Build - EP": "24-Jan-2026",
                        "Signoff STG/FedAlpha - ENG": "25-Jan-2026",
                        "Deploy MP Pre PROD": "27-Jan-2026",
                        "Deploy Prod Day 1": "28-Jan-2026",
                        "Deploy Prod Day 2": "29-Jan-2026",
                        "Deploy Prod Day 3": "30-Jan-2026",
                        "Deploy Prod Day 4": "31-Jan-2026"
                    }
                }
            ],
            "milestones": ["IRR", "Branch Cut - EP", ...],
            "source": "pdf+gsheets",
            "total_count": 10
        }

    DATA SOURCES:
        - PDF file (backend/data/release_calendar.pdf): Core dates
        - Google Sheets: Deploy day dates
        - Calculated: STG signoff, Pre-PROD dates

    RELATED ENDPOINTS:
        - GET /api/release-calendar/releases/{name} - Single release
        - GET /api/release-calendar/milestones - Milestone definitions
        - GET /api/config/releases - Release configuration
    """
    try:
        data = await get_release_calendar_data_async(DEFAULT_PDF_PATH)
        return data
    except Exception as e:
        logger.error(f"Error getting release calendar data: {e}")
        # Return empty data on error
        return {
            "releases": [],
            "milestones": [
                "IRR",
                "Branch Cut - EP",
                "Final Build - EP",
                "Signoff STG/FedAlpha - ENG",
                "Deploy MP Pre PROD",
                "Deploy Prod Day 1",
                "Deploy Prod Day 2",
                "Deploy Prod Day 3",
                "Deploy Prod Day 4",
            ],
            "source": "error",
            "error": str(e),
            "total_count": 0,
        }


@router.get("/releases/{release_name}")
async def get_release_by_name(release_name: str) -> dict[str, Any]:
    """
    Get a specific release by name (e.g., R133.0, R134.1).
    """
    data = get_release_calendar_data(DEFAULT_PDF_PATH)

    for release in data.get("releases", []):
        if release["name"].upper() == release_name.upper():
            return {
                "release": release,
                "milestones": data.get("milestones", []),
                "source": data.get("source"),
            }

    raise HTTPException(status_code=404, detail=f"Release {release_name} not found")


@router.get("/milestones")
async def get_milestones() -> dict[str, Any]:
    """
    Get list of all milestone types.
    """
    return {
        "milestones": [
            {"id": 1, "name": "IRR", "description": "Internal Release Review"},
            {"id": 2, "name": "Branch Cut - EP", "description": "Branch Cut for EP"},
            {"id": 3, "name": "Final Build - EP", "description": "Final Build for EP"},
            {"id": 4, "name": "Signoff STG/FedAlpha - ENG", "description": "Staging/FedAlpha Signoff"},
            {"id": 5, "name": "Deploy MP Pre PROD", "description": "Deploy to MP Pre-Production"},
            {"id": 6, "name": "Deploy Prod Day 1", "description": "Production Deployment Day 1"},
            {"id": 7, "name": "Deploy Prod Day 2", "description": "Production Deployment Day 2"},
            {"id": 8, "name": "Deploy Prod Day 3", "description": "Production Deployment Day 3"},
            {"id": 9, "name": "Deploy Prod Day 4", "description": "Production Deployment Day 4"},
        ]
    }


@router.get("/summary")
async def get_release_summary() -> dict[str, Any]:
    """
    Get summary statistics for releases.
    """
    data = get_release_calendar_data(DEFAULT_PDF_PATH)
    releases = data.get("releases", [])

    total = len(releases)
    completed = sum(1 for r in releases if r.get("status") == "Completed")
    in_progress = sum(1 for r in releases if r.get("status") == "In Progress")
    planned = sum(1 for r in releases if r.get("status") == "Planned")

    major_releases = sum(1 for r in releases if r.get("type") == "Major Release")
    minor_releases = sum(1 for r in releases if r.get("type") == "Minor Release")

    return {
        "total": total,
        "by_status": {
            "completed": completed,
            "in_progress": in_progress,
            "planned": planned,
        },
        "by_type": {
            "major": major_releases,
            "minor": minor_releases,
        },
        "source": data.get("source"),
    }


@router.get("/filter")
async def filter_releases(
    release_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """
    Filter releases by type, status, or search term.

    Args:
        release_type: "Major Release" or "Minor Release"
        status: "Completed", "In Progress", or "Planned"
        search: Search term for release name
    """
    data = get_release_calendar_data(DEFAULT_PDF_PATH)
    releases = data.get("releases", [])

    # Apply filters
    if release_type:
        releases = [r for r in releases if r.get("type") == release_type]

    if status:
        releases = [r for r in releases if r.get("status") == status]

    if search:
        search_lower = search.lower()
        releases = [r for r in releases if search_lower in r.get("name", "").lower()]

    return {
        "releases": releases,
        "milestones": data.get("milestones", []),
        "total_count": len(releases),
        "filters": {
            "release_type": release_type,
            "status": status,
            "search": search,
        },
        "source": data.get("source"),
    }


# ============ Google Calendar Sync Endpoints ============


@router.post("/sync")
async def sync_from_google_calendar() -> dict[str, Any]:
    """
    Manually trigger a sync from Google Calendar.

    PURPOSE:
        Forces an immediate refresh of release calendar data from Google Calendar.
        Use this when you know dates have changed and don't want to wait for
        the automatic sync interval.

    WHEN TO USE:
        - After release dates are updated in Google Calendar
        - When the automatic sync hasn't picked up recent changes
        - To verify Google Calendar integration is working

    RETURNS:
        {
            "success": true,
            "releases_synced": 12,
            "timestamp": "2026-03-26T10:30:00",
            "source": "google_calendar"
        }

    REQUIRES:
        GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_API_KEY environment variables

    NOTE:
        If Google Calendar is not configured, falls back to PDF data.
    """
    try:
        from services.gcalendar_scheduler import trigger_manual_sync

        result = await trigger_manual_sync()
        return result
    except ImportError:
        return {
            "success": False,
            "error": "Google Calendar sync not available",
            "hint": "Set GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_API_KEY in environment",
        }
    except Exception as e:
        logger.error(f"Error triggering calendar sync: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@router.get("/sync/status")
async def get_sync_status() -> dict[str, Any]:
    """
    Get the status of Google Calendar sync.

    RETURNS:
        {
            "configured": true,
            "calendar_id": "abc...@group.calendar.google.com",
            "sync_interval_minutes": 30,
            "last_sync": {
                "success": true,
                "releases_synced": 12,
                "timestamp": "2026-03-26T10:30:00"
            },
            "current_source": "google_calendar"
        }
    """
    import os

    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "")
    sync_interval = os.environ.get("GOOGLE_CALENDAR_SYNC_INTERVAL", "30")

    result = {
        "configured": bool(calendar_id),
        "calendar_id": calendar_id[:20] + "..." if len(calendar_id) > 20 else calendar_id,
        "sync_interval_minutes": int(sync_interval) if sync_interval.isdigit() else 30,
    }

    try:
        from services.gcalendar_scheduler import get_last_sync_result

        last_sync = get_last_sync_result()
        result["last_sync"] = last_sync
    except ImportError:
        result["last_sync"] = None

    # Get current data source
    data = get_release_calendar_data(DEFAULT_PDF_PATH)
    result["current_source"] = data.get("source", "unknown")
    result["releases_loaded"] = data.get("total_count", 0)

    return result


@router.delete("/sync/cache")
async def clear_calendar_cache() -> dict[str, Any]:
    """
    Clear the Google Calendar cache to force a fresh sync.

    Use this if you suspect the cache is stale or corrupted.
    The next request will trigger a fresh sync from Google Calendar.
    """
    try:
        from services.gcalendar_client import clear_calendar_cache

        clear_calendar_cache()
        return {
            "success": True,
            "message": "Calendar cache cleared. Next request will fetch fresh data.",
        }
    except ImportError:
        return {
            "success": False,
            "error": "Google Calendar client not available",
        }
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return {
            "success": False,
            "error": str(e),
        }

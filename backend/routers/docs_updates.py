"""
Documentation Updates Router
=============================

REST endpoints for the Documentation Updates section.
Provides data for bugs that need customer-facing documentation updates.

Endpoints:
    GET /api/docs-updates/releases      - Available releases with docs update bugs
    GET /api/docs-updates/bugs          - Bugs needing docs for a release
    GET /api/docs-updates/summary       - Summary statistics
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/docs-updates",
    tags=["Documentation Updates"],
)


@router.get("/releases")
async def get_available_releases():
    """
    Get list of releases that have bugs needing documentation updates.

    Returns releases sorted by version number (newest first) with bug counts.
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        releases = await service.get_available_releases()

        return {
            "releases": releases,
            "total_releases": len(releases),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching docs update releases: %s", e)
        return {
            "releases": [],
            "total_releases": 0,
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/bugs")
async def get_bugs_needing_docs(
    affected_version: str = Query(..., description="Affected version to filter by (e.g., 'AC-134.0.0')"),
):
    """
    Get bugs that need documentation updates for a specific release.

    Returns bugs where Release Note = "For Customer" and affectedVersion matches.
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        bugs = await service.get_bugs_needing_docs(affected_version)

        return {
            "affected_version": affected_version,
            "total_bugs": len(bugs),
            "bugs": bugs,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching bugs for docs update (%s): %s", affected_version, e)
        return {
            "affected_version": affected_version,
            "total_bugs": 0,
            "bugs": [],
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/summary")
async def get_docs_update_summary(
    affected_version: Optional[str] = Query(None, description="Optional version filter"),
):
    """
    Get summary statistics for documentation updates.

    Returns total count, priority breakdown, and component breakdown.
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        summary = await service.get_summary(affected_version)
        summary["generated_at"] = datetime.now().isoformat()
        return summary

    except Exception as e:
        logger.error("Error getting docs update summary: %s", e)
        return {
            "total_bugs": 0,
            "affected_version": affected_version or "all",
            "by_priority": {},
            "by_component": [],
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/nplan-releases")
async def get_nplan_releases():
    """
    Get list of releases that have NPLANs needing documentation updates.

    Returns releases sorted by version number (newest first) with NPLAN counts.
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        releases = await service.get_nplan_releases()

        return {
            "releases": releases,
            "total_releases": len(releases),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching NPLAN releases: %s", e)
        return {
            "releases": [],
            "total_releases": 0,
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/nplans")
async def get_nplans_needing_docs(
    release: str = Query(..., description="Release to filter by (e.g., 'R135', '135', '26-Q1-Mar-R135')"),
):
    """
    Get NPLANs that need documentation updates for a specific release.

    Filters by Delivery Target (Beta) OR Delivery Target (GA) matching the release.
    Release notes need to be updated when features go to Beta.

    Returns NPLANs where:
    - Release Note (cf[24133]) = "For Customer"
    - Delivery Target (Beta) OR Delivery Target (GA) matches the release
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        nplans = await service.get_nplans_needing_docs(release)

        return {
            "release": release,
            "total_nplans": len(nplans),
            "nplans": nplans,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching NPLANs for docs update (%s): %s", release, e)
        return {
            "release": release,
            "total_nplans": 0,
            "nplans": [],
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/funnel")
async def get_documentation_funnel(
    release: str = Query(..., description="Release to get funnel stats for (e.g., 'R135')"),
):
    """
    Get documentation funnel statistics for a specific release.

    The funnel tracks NPLANs through the documentation process:
    1. Needs Docs - Total items with Release Note = "For Customer"
    2. Writer Assigned - Items with a technical writer assigned
    3. TOI Scheduled - Items with a TOI Highlight Date set
    4. Draft Complete - Items with Release Note Description filled
    5. Published - Items with status Done/Closed (docs complete)
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()

    try:
        funnel = await service.get_documentation_funnel(release)
        funnel["generated_at"] = datetime.now().isoformat()
        return funnel

    except Exception as e:
        logger.error("Error fetching documentation funnel (%s): %s", release, e)
        return {
            "release": release,
            "total": 0,
            "stages": [],
            "completion_rate": 0,
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.post("/refresh")
async def refresh_cache():
    """
    Clear the docs update service cache to force fresh data fetch.
    """
    from services.docs_update_service import get_docs_update_service

    service = get_docs_update_service()
    service.clear_cache()

    return {
        "status": "ok",
        "message": "Cache cleared",
        "generated_at": datetime.now().isoformat(),
    }

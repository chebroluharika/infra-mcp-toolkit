"""
Dev Insights Router
===================

REST API endpoints for developer-focused AI insights:
- Knowledge Gap analysis (bus factor risks)
- Personalized Daily Digest (per-developer summary)
- Workload Anomaly detection (overloaded/underutilized)
- Cross-Concern Links (connected items across data sources)
"""

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev-insights", tags=["Dev Insights"])


@router.get("/knowledge-gaps")
async def get_knowledge_gaps(
    release: str = Query(None, description="Release ID (e.g. R135)"),
):
    """
    Analyze knowledge gaps and bus factor risks.

    Identifies components/areas where only one developer has expertise,
    creating a single-point-of-failure risk.
    """
    try:
        from services.dev_insights_service import analyze_knowledge_gaps

        result = await analyze_knowledge_gaps(release=release)
        return result
    except Exception as e:
        logger.error("Knowledge gap analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/daily-digest")
async def get_daily_digest(
    developer: str = Query(..., description="Developer name or username"),
    release: str = Query(None, description="Release ID (e.g. R135)"),
):
    """
    Generate a personalized daily digest for a developer.

    Aggregates all action items across JIRA, GitHub, and escalations
    into a prioritized to-do list.
    """
    if not developer or not developer.strip():
        raise HTTPException(status_code=400, detail="Developer name is required")

    try:
        from services.dev_insights_service import generate_daily_digest

        result = await generate_daily_digest(developer=developer.strip(), release=release)
        return result
    except Exception as e:
        logger.error("Daily digest generation failed for %s: %s", developer, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Digest generation failed: {str(e)}")


@router.get("/workload-anomalies")
async def get_workload_anomalies(
    release: str = Query(None, description="Release ID (e.g. R135)"),
):
    """
    Detect workload anomalies across the team.

    Identifies overloaded developers (too many high-priority items)
    and underutilized developers who could take on more work.
    """
    try:
        from services.dev_insights_service import detect_workload_anomalies

        result = await detect_workload_anomalies(release=release)
        return result
    except Exception as e:
        logger.error("Workload anomaly detection failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {str(e)}")


@router.get("/cross-concern-links")
async def get_cross_concern_links(
    release: str = Query(None, description="Release ID (e.g. R135)"),
):
    """
    Find cross-concern links between items.

    Discovers connections between escalations, PRs, bugs, components,
    and builds that might not be obvious from individual views.
    """
    try:
        from services.dev_insights_service import find_cross_concern_links

        result = await find_cross_concern_links(release=release)
        return result
    except Exception as e:
        logger.error("Cross-concern link analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Link analysis failed: {str(e)}")

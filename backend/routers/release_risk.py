"""
Release Risk Router
===================

API endpoints for release risk prediction using multi-agentic AI analysis.

Architecture:
    Dashboard/UI → GET /api/release-risk/{release_id} → Reads from cache (fast)
    Agent → POST /api/release-risk/analyze/{release_id} → Runs agent analysis → Saves to cache

Endpoints:
- GET /api/release-risk/status - Check if risk predictor is available
- GET /api/release-risk/releases/all - Get all releases with history
- GET /api/release-risk/{release_id} - Get cached risk prediction (fast, for dashboard)
- POST /api/release-risk/analyze/{release_id} - Run agent analysis (slow, updates cache)
- GET /api/release-risk/history/{release_id} - Get historical data for a release
- POST /api/release-risk/snapshot/{release_id} - Save a snapshot of current metrics
- POST /api/release-risk/outcome/{release_id} - Record release outcome
- GET /api/release-risk/cache/status - Get cache status for all releases
"""

import logging
from datetime import datetime
from typing import Optional

from config import get_current_release, get_release_dates
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from services.release_history import get_all_releases, get_release_history, save_release_outcome, save_release_snapshot
from services.risk_cache import get_all_cached_releases, get_cached_risk_analysis, invalidate_cache, save_risk_analysis
from services.risk_predictor import RiskPredictorError, get_risk_predictor
from services.trend_tracker import analyze_trends

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/release-risk", tags=["Release Risk"])


async def _get_current_metrics(release_id: str) -> dict:
    """
    Fetch current metrics for a release from various sources.

    Aggregates data from:
    - Overview API (bugs, stories, code review, RRS score)
    - Trend tracker (velocity)
    - TestRail (test pass rate) - optional
    - Jenkins (build success rate) - optional
    """
    metrics = {
        "p0_bugs": 0,
        "p1_bugs": 0,
        "p2_bugs": 0,
        "total_open": 0,
        "open_stories": 0,
        "open_bugs": 0,
        "code_review": 0,
        "velocity_per_day": 0.0,
        "test_pass_rate": None,
        "build_success_rate": None,
        "blockers_unassigned": 0,
        "rrs_score": None,
        "rrs_status": None,
        "critical_blocker_total": 0,
    }

    try:
        from routers.overview import get_overview_data

        overview_data = await get_overview_data()

        release_data = None
        for release in overview_data.get("releases", []):
            if release.get("id") == release_id:
                release_data = release
                break

        if release_data:
            metrics["open_stories"] = release_data.get("open_stories", 0)
            metrics["open_bugs"] = release_data.get("open_bugs", 0)
            metrics["code_review"] = release_data.get("code_review", 0)
            metrics["total_open"] = release_data.get("action_items", 0)

            metrics["p0_bugs"] = release_data.get("blocker_count", 0)
            metrics["p1_bugs"] = release_data.get("critical_count", 0)
            metrics["critical_blocker_total"] = release_data.get("critical_blocker_total", 0)

            metrics["rrs_score"] = release_data.get("rrs_score")
            metrics["rrs_status"] = release_data.get("rrs_status")

            testrail = release_data.get("testrail", {})
            if testrail.get("available"):
                metrics["test_pass_rate"] = testrail.get("pass_rate")

            logger.info(
                "Risk metrics for %s: blockers=%d, critical=%d, bugs=%d, stories=%d, rrs=%s",
                release_id,
                metrics["p0_bugs"],
                metrics["p1_bugs"],
                metrics["open_bugs"],
                metrics["open_stories"],
                metrics["rrs_score"],
            )
    except Exception as e:
        logger.warning("Failed to get overview data for %s: %s", release_id, e)

    try:
        dates = get_release_dates(release_id)
        irr_date = dates.get("irr") if dates else None
        trend_data = analyze_trends(release_id, irr_date=irr_date)

        if trend_data.get("has_data"):
            metrics["velocity_per_day"] = trend_data.get("velocity", 0.0)
    except Exception as e:
        logger.warning("Failed to get trend data for %s: %s", release_id, e)

    try:
        from config import get_milestone_id
        from services.testrail_client import get_testrail_client

        testrail = get_testrail_client()
        milestone_id = get_milestone_id(release_id)

        if milestone_id:
            status_summary = await testrail.get_status_summary(milestone_id)
            if status_summary:
                metrics["test_pass_rate"] = status_summary.get("pass_rate")
    except Exception as e:
        logger.debug("Failed to get TestRail data for %s: %s", release_id, e)

    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()
        pdv_pipelines = await jenkins.get_pdv_pipelines()

        if pdv_pipelines:
            total_builds = 0
            successful_builds = 0
            for pipeline in pdv_pipelines:
                builds = pipeline.get("builds", [])[:5]
                for build in builds:
                    total_builds += 1
                    if build.get("status") == "success":
                        successful_builds += 1

            if total_builds > 0:
                metrics["build_success_rate"] = round((successful_builds / total_builds) * 100, 1)
    except Exception as e:
        logger.debug("Failed to get Jenkins data for %s: %s", release_id, e)

    return metrics


def _calculate_days_to_milestone(release_id: str) -> tuple:
    """Calculate days to next milestone and identify which milestone."""
    try:
        dates = get_release_dates(release_id)
        if not dates:
            return 0, "Unknown"

        today = datetime.now().date()

        milestones = [
            ("IRR", dates.get("irr")),
            ("Branch Cut", dates.get("branch_cut")),
            ("Final Build", dates.get("final_build")),
            ("Day 1 Deploy", dates.get("day1_deploy")),
        ]

        for milestone_name, milestone_date in milestones:
            if milestone_date:
                try:
                    if isinstance(milestone_date, str):
                        m_date = datetime.strptime(milestone_date, "%Y-%m-%d").date()
                    else:
                        m_date = milestone_date

                    days = (m_date - today).days
                    if days >= 0:
                        return days, milestone_name
                except (ValueError, TypeError):
                    continue

        return 0, "Post-Release"
    except Exception as e:
        logger.warning("Failed to calculate days to milestone: %s", e)
        return 0, "Unknown"


# ============================================================
# STATIC ROUTES (must come before dynamic routes)
# ============================================================


@router.get("/status")
async def get_risk_predictor_status():
    """
    Check if risk predictor is available and what features are enabled.
    """
    try:
        predictor = get_risk_predictor()
        status = await predictor.is_available()

        status["current_release"] = get_current_release()

        return status

    except Exception as e:
        logger.error("Failed to get predictor status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/releases/all")
async def get_all_risk_releases():
    """
    Get list of all releases with historical data.
    """
    try:
        releases = get_all_releases()
        return {
            "releases": releases,
            "count": len(releases),
        }
    except Exception as e:
        logger.error("Failed to get releases: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/status")
async def get_risk_cache_status():
    """
    Get cache status for all releases.

    Returns which releases have cached analysis and when they expire.
    """
    try:
        cache_status = get_all_cached_releases()
        return {
            "cached_releases": cache_status,
            "count": len(cache_status),
        }
    except Exception as e:
        logger.error("Failed to get cache status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# DYNAMIC ROUTES (with path parameters)
# ============================================================


@router.get("/history/{release_id}")
async def get_release_risk_history(release_id: str):
    """
    Get historical risk data for a release.

    Returns all snapshots and outcome data for a specific release.
    """
    try:
        history = get_release_history(release_id)
        if not history:
            return {
                "release_id": release_id,
                "has_history": False,
                "message": "No historical data available for this release",
            }

        return {
            "release_id": release_id,
            "has_history": True,
            "phases": history.get("phases", {}),
            "outcome": history.get("outcome"),
        }

    except Exception as e:
        logger.error("Failed to get risk history for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot/{release_id}")
async def save_risk_snapshot(
    release_id: str,
    phase: str = Query(..., description="Milestone phase (e.g., irr_minus_3, branch_cut)"),
    force: bool = Query(False, description="Overwrite existing snapshot"),
):
    """
    Save a snapshot of current metrics for a release at a specific phase.

    This is typically called automatically when viewing release readiness,
    but can also be triggered manually to capture state at a specific time.
    """
    try:
        metrics = await _get_current_metrics(release_id)

        days_to_milestone, milestone = _calculate_days_to_milestone(release_id)
        metrics["days_to_milestone"] = days_to_milestone

        saved = save_release_snapshot(release_id, phase, metrics, force=force)

        return {
            "success": saved,
            "release_id": release_id,
            "phase": phase,
            "message": "Snapshot saved" if saved else "Snapshot already exists (use force=true to overwrite)",
            "metrics": metrics,
        }

    except Exception as e:
        logger.error("Failed to save snapshot for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/outcome/{release_id}")
async def record_release_outcome(
    release_id: str,
    on_time: bool = Query(..., description="Whether release shipped on schedule"),
    slip_days: int = Query(0, description="Number of days slipped"),
    blockers_at_release: int = Query(0, description="Blockers remaining at release"),
    notes: str = Query("", description="Additional notes"),
):
    """
    Record the final outcome of a release.

    This should be called after a release ships to provide ground truth
    for future predictions.
    """
    try:
        saved = save_release_outcome(
            release_id=release_id,
            on_time=on_time,
            slip_days=slip_days,
            blockers_at_release=blockers_at_release,
            notes=notes,
        )

        return {
            "success": saved,
            "release_id": release_id,
            "outcome": {
                "on_time": on_time,
                "slip_days": slip_days,
                "blockers_at_release": blockers_at_release,
            },
        }

    except Exception as e:
        logger.error("Failed to record outcome for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{release_id}")
async def get_release_risk(
    release_id: str,
    refresh: bool = Query(False, description="Force refresh by running agent analysis"),
    max_age_hours: Optional[int] = Query(None, description="Max cache age in hours"),
    background_tasks: BackgroundTasks = None,
):
    """
    Get AI-powered risk prediction for a release.

    This endpoint reads from cache for fast dashboard response.
    Use POST /analyze/{release_id} to run a fresh agent analysis.

    If refresh=true, triggers background analysis and returns cached data
    (or runs synchronously if no cache exists).

    Returns:
    - probability: 0-100 chance of hitting next milestone on time
    - risk_level: HIGH/MEDIUM/LOW
    - confidence: HIGH/MEDIUM/LOW based on data quality
    - risk_signals: Detected risk signals with severity
    - action_items: Prioritized recommended actions
    - reasoning: AI-generated explanation
    - _cache: Cache metadata (when cached=true)
    """
    # Try to get cached analysis first (fast path)
    if not refresh:
        cached = get_cached_risk_analysis(release_id, max_age_hours=max_age_hours)
        if cached:
            logger.info("Returning cached risk analysis for %s", release_id)
            return cached

    # If refresh requested or no cache, try agent analysis
    # For now, fall back to the service-based approach until agent is fully integrated
    predictor = get_risk_predictor()

    if not predictor.is_configured():
        # Return cached if available, even if expired
        cached = get_cached_risk_analysis(release_id, max_age_hours=24)
        if cached:
            cached["_cache"]["stale"] = True
            cached["_cache"]["message"] = "LLM not configured, returning stale cache"
            return cached

        raise HTTPException(
            status_code=503,
            detail={
                "error": "llm_not_configured",
                "message": "Ollama LLM is not configured and no cached analysis available.",
                "action": "Set ADK_LLM_PROVIDER=ollama, ADK_OLLAMA_BASE_URL, ADK_OLLAMA_API_TOKEN, ADK_LLM_MODEL in .env",
            },
        )

    try:
        current_metrics = await _get_current_metrics(release_id)
        days_to_milestone, milestone = _calculate_days_to_milestone(release_id)

        prediction = await predictor.predict_risk(
            release_id=release_id,
            current_metrics=current_metrics,
            days_to_milestone=days_to_milestone,
            milestone=milestone,
        )

        # Cache the result
        save_risk_analysis(release_id, prediction)

        return prediction

    except RiskPredictorError as e:
        logger.error("Risk prediction LLM error for %s: %s", release_id, e)

        # Try to return cached if LLM fails
        cached = get_cached_risk_analysis(release_id, max_age_hours=24)
        if cached:
            cached["_cache"]["stale"] = True
            cached["_cache"]["error"] = str(e)
            return cached

        raise HTTPException(
            status_code=503,
            detail={"error": "llm_error", "message": str(e), "action": "Check Ollama connectivity and configuration"},
        )

    except Exception as e:
        logger.error("Failed to get risk prediction for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/{release_id}")
async def analyze_release_risk_with_agent(
    release_id: str,
    query: str = Query(None, description="Optional custom analysis query"),
):
    """
    Run multi-agentic AI analysis for release risk.

    This endpoint triggers the release_risk_agent to:
    1. Analyze JIRA blockers (P0/P1, unassigned, RRS)
    2. Analyze quality metrics (tests, builds)
    3. Analyze velocity and trends
    4. Synthesize findings into risk assessment

    The result is cached for fast dashboard reads.

    This is the SLOW path (60-120 seconds) - use GET for dashboard.
    """
    try:
        # For now, use the service-based approach
        # TODO: Integrate with actual release_risk_agent when runner is ready

        predictor = get_risk_predictor()

        if not predictor.is_configured():
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "llm_not_configured",
                    "message": "Ollama LLM is not configured. Agent analysis requires Ollama.",
                    "action": "Set ADK_LLM_PROVIDER=ollama, ADK_OLLAMA_BASE_URL, ADK_OLLAMA_API_TOKEN, ADK_LLM_MODEL in .env",
                },
            )

        current_metrics = await _get_current_metrics(release_id)
        days_to_milestone, milestone = _calculate_days_to_milestone(release_id)

        prediction = await predictor.predict_risk(
            release_id=release_id,
            current_metrics=current_metrics,
            days_to_milestone=days_to_milestone,
            milestone=milestone,
        )

        # Cache the result
        save_risk_analysis(release_id, prediction)

        logger.info("Agent analysis completed for %s, cached for dashboard", release_id)

        return {
            "success": True,
            "release_id": release_id,
            "analysis": prediction,
            "cached": True,
            "message": "Analysis completed and cached. Use GET /api/release-risk/{release_id} for fast reads.",
        }

    except RiskPredictorError as e:
        logger.error("Agent analysis failed for %s: %s", release_id, e)
        raise HTTPException(
            status_code=503, detail={"error": "agent_error", "message": str(e), "action": "Check Ollama connectivity"}
        )

    except Exception as e:
        logger.error("Agent analysis failed for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache/{release_id}")
async def invalidate_risk_cache(release_id: str):
    """
    Invalidate cached risk analysis for a release.

    Use this to force a fresh analysis on the next request.
    """
    try:
        invalidated = invalidate_cache(release_id)
        return {
            "success": invalidated,
            "release_id": release_id,
            "message": "Cache invalidated" if invalidated else "No cache to invalidate",
        }
    except Exception as e:
        logger.error("Failed to invalidate cache for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))

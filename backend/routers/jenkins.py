"""
Jenkins API Router
Handles Jenkins pipeline status and test failure analysis endpoints.

Uses JenkinsClient for direct Jenkins API access.
"""

import asyncio
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from config import settings
from fastapi import APIRouter, HTTPException, Query

# Add ai_agents to path to import TFA directly (bypasses main __init__ to avoid ADK deps)
_ai_agents_path = str(Path(__file__).resolve().parent.parent.parent / "ai_agents")
if _ai_agents_path not in sys.path:
    sys.path.insert(0, _ai_agents_path)

from tfa_agent import get_tfa_agent

logger = logging.getLogger(__name__)

# TFA Result Cache (in-memory, expires after 10 minutes)
_tfa_cache = {}
_TFA_CACHE_TTL = 600  # 10 minutes


def _get_tfa_cache(key: str):
    """Get cached TFA result if not expired."""
    if key in _tfa_cache:
        entry = _tfa_cache[key]
        if time.time() - entry["timestamp"] < _TFA_CACHE_TTL:
            logger.debug(f"TFA cache hit for {key}")
            return entry["data"]
        else:
            del _tfa_cache[key]
    return None


def _set_tfa_cache(key: str, data: dict):
    """Cache TFA result."""
    _tfa_cache[key] = {"data": data, "timestamp": time.time()}
    # Cleanup old entries (keep max 50)
    if len(_tfa_cache) > 50:
        oldest_keys = sorted(_tfa_cache.keys(), key=lambda k: _tfa_cache[k]["timestamp"])[:10]
        for k in oldest_keys:
            del _tfa_cache[k]


def _get_tfa_engine_label(analyzed_failures: list, analysis_method: str) -> str:
    """Build analysisEngine label from TFA agent response metadata."""
    if analyzed_failures and isinstance(analyzed_failures[0], dict):
        # Check for error state
        if analyzed_failures[0].get("error"):
            return "unavailable"
        backend = analyzed_failures[0].get("llm_backend", "")
        model = analyzed_failures[0].get("llm_model", "")
        if backend and model and backend not in ("none", "unavailable"):
            return f"{backend}/{model}"
    if analysis_method == "llm_rag":
        return "llm (model unknown)"
    if analysis_method == "error":
        return "unavailable"
    return "error"


def _get_tfa_engine_label_from_ai(ai_analysis: dict, analysis_engine: str) -> str:
    """Build analysisEngine label from a single AI analysis dict."""
    if ai_analysis:
        backend = ai_analysis.get("llm_backend", "")
        model = ai_analysis.get("llm_model", "")
        if backend and model and backend != "none":
            return f"{backend}/{model} ({analysis_engine})"
    return analysis_engine


def _cluster_failures(analyzed_failures: list) -> list:
    """
    Cluster test failures by error category/type.
    Groups tests with similar root causes together for better visualization.

    Returns list of clusters:
    [
        {
            "category": "connection",
            "label": "Connection Error",
            "count": 10,
            "severity": "high",
            "confidence": "high",
            "rootCause": "Service unreachable during test setup",
            "recommendations": [...],
            "tests": [{"name": "test_foo", "className": "TestClass"}, ...]
        }
    ]
    """
    if not analyzed_failures:
        return []

    # Filter out None values and non-dict items
    analyzed_failures = [af for af in analyzed_failures if af and isinstance(af, dict)]
    if not analyzed_failures:
        return []

    # Category display labels
    category_labels = {
        "connection": "Connection Error",
        "timeout": "Timeout Error",
        "assertion": "Assertion Failure",
        "configuration": "Configuration Error",
        "infrastructure": "Infrastructure Issue",
        "authentication": "Authentication Error",
        "permission": "Permission Error",
        "resource": "Resource Error",
        "dependency": "Dependency Error",
        "build_error": "Build Error",
        "test_error": "Test Error",
        "unknown": "Unknown Error",
    }

    clusters = {}

    for af in analyzed_failures:
        analysis = af.get("analysis") or {}
        category = analysis.get("category", "unknown")

        if category not in clusters:
            clusters[category] = {
                "category": category,
                "label": category_labels.get(category, category.replace("_", " ").title()),
                "count": 0,
                "severity": analysis.get("severity", "medium"),
                "confidence": analysis.get("confidence", "medium"),
                "rootCause": analysis.get("root_cause", ""),
                "recommendations": [],
                "productRecommendations": [],
                "tests": [],
                "productContext": None,
            }

        cluster = clusters[category]
        cluster["count"] += 1
        cluster["tests"].append(
            {
                "name": af.get("test_name", "unknown"),
                "className": af.get("test_class", ""),
                "errorMessage": af.get("error_message", "")[:200],
            }
        )

        # Extract product context if available
        product_ctx = af.get("product_context")
        if product_ctx and not cluster["productContext"]:
            cluster["productContext"] = {
                "component": product_ctx.get("component", {}).get("name"),
                "description": product_ctx.get("component", {}).get("description"),
                "owner": product_ctx.get("component", {}).get("owner"),
            }

        # Collect unique recommendations (separate product-specific ones)
        recs = analysis.get("recommendations", [])
        if isinstance(recs, list):
            for rec in recs:
                if not rec:
                    continue
                # Check if this is a product-specific recommendation
                if rec.startswith("[") and "]" in rec:
                    if rec not in cluster["productRecommendations"]:
                        cluster["productRecommendations"].append(rec)
                elif rec not in cluster["recommendations"]:
                    cluster["recommendations"].append(rec)

        # Keep the most severe/confident values
        if analysis.get("severity") == "high":
            cluster["severity"] = "high"
        if analysis.get("confidence") == "high":
            cluster["confidence"] = "high"

    # Sort clusters by count (descending) and limit recommendations
    result = sorted(clusters.values(), key=lambda x: x["count"], reverse=True)
    for cluster in result:
        cluster["recommendations"] = cluster["recommendations"][:4]
        cluster["productRecommendations"] = cluster["productRecommendations"][:3]

    return result


router = APIRouter(
    prefix="/api/jenkins",
    tags=["jenkins"],
)

# Get default num_builds from config (can be overridden via JENKINS_NUM_BUILDS env var)
DEFAULT_NUM_BUILDS = settings.jenkins_num_builds


@router.get("/health")
async def check_jenkins_health():
    """
    Quick health check for Jenkins connectivity.

    Makes a single lightweight request to verify Jenkins is reachable.
    Use this to diagnose connection issues before loading full data.
    """
    from services.jenkins_client import get_jenkins_client

    jenkins = get_jenkins_client()

    if not jenkins.is_configured():
        return {
            "status": "not_configured",
            "message": "Jenkins not configured (missing JENKINS_URL, JENKINS_USER, or JENKINS_TOKEN)",
        }

    try:
        # Simple API call to check connectivity
        result = await jenkins._make_request(
            f"{jenkins.base_url}/api/json?tree=mode", timeout=10.0, use_cache=False, max_retries=1
        )

        if "error" in result:
            return {
                "status": "error",
                "message": f"Jenkins unreachable: {result.get('error')}",
                "error_type": result.get("error_type"),
                "jenkins_url": jenkins.base_url,
            }

        return {
            "status": "ok",
            "message": "Jenkins is reachable",
            "jenkins_url": jenkins.base_url,
            "mode": result.get("mode", "unknown"),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to connect to Jenkins: {str(e)}",
            "jenkins_url": jenkins.base_url,
        }


@router.get("/pipelines")
async def get_jenkins_pipelines(
    include_builds: bool = Query(default=False, description="Include recent builds for each pipeline"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get current status of all monitored Jenkins CI/CD pipelines.

    PURPOSE:
        Returns the status of all configured Jenkins pipelines including
        build status (success/failure/running), last build time, and
        overall health. Used to display pipeline status cards on dashboard.

    WHEN TO USE:
        - Displaying Jenkins pipeline status on dashboard
        - Monitoring CI/CD health at a glance
        - Identifying failed or unstable pipelines
        - Checking if any builds are currently running

    PARAMETERS:
        - include_builds (bool): If true, include recent builds for each pipeline (batch loading)

    CONFIGURATION:
        - JENKINS_NUM_BUILDS env var: Number of builds per pipeline (default: 10)

    RETURNS:
        {
            "pipelines": [
                {
                    "name": "frontend-build",
                    "url": "https://jenkins.example.com/job/frontend-build",
                    "status": "success",       # "success", "failure", "unstable", "running", "aborted"
                    "lastBuild": {
                        "number": 142,
                        "result": "SUCCESS",
                        "timestamp": "2026-02-03T10:00:00",
                        "duration": 300000     # milliseconds
                    },
                    "health": 80,              # 0-100 health score
                    "recentBuilds": [...]      # Only if include_builds=true
                }
            ],
            "summary": {
                "total": 5,
                "passing": 4,
                "failing": 1
            },
            "dataSource": "jenkins-direct"
        }

    ENVIRONMENT VARIABLES:
        - JENKINS_URL: Jenkins server URL
        - JENKINS_USER: Jenkins username
        - JENKINS_TOKEN: Jenkins API token
        - JENKINS_JOBS: Comma-separated list of job names

    RELATED ENDPOINTS:
        - GET /api/jenkins/pipelines/{job_name}/builds - Build history for a job
        - GET /api/jenkins/tfa/{job_name}/{build_number} - Test failure analysis
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Jenkins not configured. " "Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN environment variables."
                ),
            )

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        # num_builds configured via JENKINS_NUM_BUILDS env var (default: 10)
        data = await jenkins.get_pipelines(include_builds=include_builds, num_builds=DEFAULT_NUM_BUILDS)

        if not data or not data.get("pipelines"):
            raise HTTPException(
                status_code=503, detail="No Jenkins pipelines found. Check JENKINS_JOBS environment variable."
            )

        # Add dataSource field
        data["dataSource"] = "jenkins-direct"
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Jenkins pipelines error: %s", e)
        raise HTTPException(status_code=500, detail=f"Jenkins error: {e}") from e


@router.get("/pipelines/{job_name}/builds")
async def get_pipeline_builds(
    job_name: str, num_builds: int = Query(default=10, description="Number of builds to return")
):
    """
    Get build history for a specific Jenkins pipeline.

    PURPOSE:
        Returns the last N builds for a Jenkins job with detailed status,
        timing, and result information. Used to display build history
        charts and identify build trends.

    WHEN TO USE:
        - Viewing build history for a specific pipeline
        - Analyzing build success/failure trends
        - Finding a specific build to analyze (for TFA)
        - Checking build duration trends

    PARAMETERS:
        - job_name (str): Jenkins job name (URL-encoded if contains special chars)
        - num_builds (int): Number of builds to return (default: 10, max: 100)

    RETURNS:
        {
            "job": "frontend-build",
            "builds": [
                {
                    "number": 142,
                    "result": "SUCCESS",        # "SUCCESS", "FAILURE", "UNSTABLE", "ABORTED"
                    "timestamp": "2026-02-03T10:00:00",
                    "duration": 300000,         # milliseconds
                    "url": "https://jenkins.example.com/job/.../142",
                    "cause": "Started by user"  # Build trigger reason
                }
            ],
            "totalBuilds": 142
        }

    ERROR RESPONSES:
        - 404: Job not found in Jenkins
        - 503: Jenkins not configured or unavailable
        - 504: Request timeout (Jenkins slow)

    RELATED ENDPOINTS:
        - GET /api/jenkins/pipelines - All pipeline statuses
        - GET /api/jenkins/tfa/{job_name}/{build_number} - Analyze failures
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503, detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN."
            )

        data = await jenkins.get_pipeline_builds(job_name, num_builds)

        if data.get("error"):
            error_type = data.get("error_type", "unknown")
            error_msg = data.get("error")

            # Return appropriate status code based on error type
            if error_type == "not_found":
                raise HTTPException(status_code=404, detail=f"Job '{job_name}' not found in Jenkins.")
            elif error_type == "timeout":
                raise HTTPException(
                    status_code=504,
                    detail=f"Jenkins request timed out for {job_name}. Jenkins may be slow or overloaded.",
                )
            elif error_type == "connection":
                raise HTTPException(
                    status_code=503,
                    detail=f"Cannot connect to Jenkins for {job_name}. Check Jenkins availability: {error_msg}",
                )
            elif error_type == "auth_failed":
                raise HTTPException(
                    status_code=503,
                    detail="Jenkins authentication failed. Check JENKINS_USER and JENKINS_TOKEN.",
                )
            else:
                raise HTTPException(status_code=503, detail=f"Jenkins error for {job_name}: {error_msg}")

        return data
    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e).lower()
        logger.error("Error fetching builds for %s: %s", job_name, e)

        if "timeout" in error_str or "timed out" in error_str:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Jenkins request timed out fetching builds for {job_name}. "
                    "Try with fewer builds or check Jenkins load."
                ),
            ) from e
        if "disconnect" in error_str or "connection" in error_str:
            raise HTTPException(status_code=503, detail=f"Jenkins connection issue for {job_name}: {e}") from e
        if "404" in error_str or "not found" in error_str:
            raise HTTPException(
                status_code=404, detail=f"Job '{job_name}' not found in Jenkins. Check the job name is correct."
            ) from e
        raise HTTPException(status_code=500, detail=f"Jenkins error fetching builds: {e}") from e


@router.get("/recent-builds")
async def get_recent_builds(
    limit: int = Query(default=30, ge=1, le=100, description="Number of recent builds to return"),
    pipeline_type: str = Query(default="all", description="Pipeline type: 'all', 'regression', 'pdv', 'endpoint-pdv'"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get aggregated recent builds across all pipelines, sorted by timestamp.

    PURPOSE:
        Returns a single list of recent builds from all pipelines, aggregated
        and sorted by timestamp (most recent first). Used for displaying
        unified build history bars.

    WHEN TO USE:
        - Displaying recent build history across all pipelines
        - Showing a unified timeline of build activity
        - Quick overview of recent CI/CD activity

    PARAMETERS:
        - limit (int): Maximum number of builds to return (default: 30, max: 100)
        - pipeline_type (str): Filter by pipeline type:
            - 'all': All pipelines (regression + pdv + endpoint-pdv)
            - 'regression': Only regression test pipelines
            - 'pdv': Only backend PDV pipelines
            - 'endpoint-pdv': Only endpoint PDV pipelines
        - force_refresh (bool): Bypass cache (default: False)

    RETURNS:
        {
            "builds": [
                {
                    "buildNumber": 142,
                    "status": "success",
                    "timestamp": "2h ago",
                    "timestampMs": 1706976000000,
                    "duration": "5m 30s",
                    "url": "https://jenkins.example.com/job/.../142",
                    "jobName": "backend-regression",
                    "pipelineType": "regression"
                }
            ],
            "total": 30,
            "pipelineType": "all"
        }

    RELATED ENDPOINTS:
        - GET /api/jenkins/pipelines?include_builds=true - Full pipeline data
        - GET /api/jenkins/pipelines/{job_name}/builds - Single pipeline builds
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503, detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN."
            )

        all_builds = []

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        # Fetch based on pipeline type
        if pipeline_type in ("all", "regression"):
            # Get regression pipelines with builds
            pipelines_data = await jenkins.get_pipelines(num_builds=10, include_builds=True)
            for pipeline in pipelines_data.get("pipelines", []):
                for build in pipeline.get("recentBuilds", []):
                    all_builds.append(
                        {
                            **build,
                            "jobName": pipeline.get("name", "Unknown"),
                            "fullName": pipeline.get("fullName", ""),
                            "pipelineType": "regression",
                        }
                    )

        if pipeline_type in ("all", "pdv"):
            # Get backend PDV pipelines with builds
            pdv_data = await jenkins.get_pdv_pipelines(num_builds=10, include_builds=True)
            for pipeline in pdv_data.get("pipelines", []):
                for build in pipeline.get("recentBuilds", []):
                    all_builds.append(
                        {
                            **build,
                            "jobName": pipeline.get("name", "Unknown"),
                            "fullName": pipeline.get("fullName", ""),
                            "pipelineType": "pdv",
                        }
                    )

        if pipeline_type in ("all", "endpoint-pdv"):
            # Get endpoint PDV builds (Golden Regression)
            endpoint_data = await jenkins.get_golden_regression(num_builds=10)
            for build in endpoint_data.get("builds", []):
                all_builds.append({**build, "jobName": build.get("stack", "Unknown"), "pipelineType": "endpoint-pdv"})

        # Sort by timestamp (most recent first)
        all_builds.sort(key=lambda b: b.get("timestampMs", 0), reverse=True)

        # Limit results
        all_builds = all_builds[:limit]

        return {"builds": all_builds, "total": len(all_builds), "pipelineType": pipeline_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching recent builds: %s", e)
        raise HTTPException(status_code=500, detail=f"Error fetching recent builds: {e}") from e


@router.get("/tfa/{job_name}/{build_number}")
async def get_test_failure_analysis(job_name: str, build_number: int, source: str = "main", quick: bool = False):
    """
    Get AI-powered Test Failure Analysis (TFA) for a Jenkins build.

    PURPOSE:
        Analyzes failed test cases from a Jenkins build using RAG (Retrieval
        Augmented Generation) with LLM via Ollama Gateway. Identifies root causes, finds
        similar historical failures, and provides actionable recommendations.

    WHEN TO USE:
        - Investigating why a build failed
        - Understanding root cause of test failures
        - Finding similar past failures and their resolutions
        - Getting AI recommendations for fixing issues

    PARAMETERS:
        - job_name (str): Jenkins job name
        - build_number (int): Build number to analyze
        - source (str): Jenkins source - "main" (default), "dev" for Dev pipelines, or "backend-pdv" for Backend PDV pipelines

    RETURNS:
        {
            "job": "frontend-build",
            "buildNumber": 142,
            "summary": {
                "totalTests": 100,
                "passed": 95,
                "failed": 5,
                "skipped": 0
            },
            "rootCauses": [
                {
                    "type": "api_error",
                    "description": "Backend API returning 500 errors",
                    "count": 3,
                    "severity": "high",
                    "confidence": "medium"
                }
            ],
            "recommendations": [
                "Check backend service health",
                "Review recent API changes"
            ],
            "failedTests": [
                {
                    "name": "test_user_login",
                    "className": "AuthTests",
                    "errorMessage": "Connection refused",
                    "analysis": {...},
                    "similarFailures": [...]
                }
            ],
            "analysisType": "llm_rag",    # "llm_rag" or "pattern_based"
            "analysisEngine": "ollama/sgl/llama-3.2-11B-vision-instruct",  # or "pattern_based"
            "knowledgeBaseStats": {...}
        }

    AI ANALYSIS FEATURES:
        - Semantic search for similar historical failures
        - LLM-powered root cause analysis (via Ollama Gateway)
        - Pattern-based fallback if no LLM available
        - Knowledge base learning from past resolutions

    RELATED ENDPOINTS:
        - GET /api/jenkins/pipelines/{job_name}/builds - Get build list
        - GET /api/jenkins/golden-regression/{build}/tfa - Golden regression TFA
    """
    # Auto-detect Backend PDV jobs when source is not specified
    # Backend PDV jobs have patterns like: your-product-backend_*_pdv_test, your-product-backend_new_*_pdv_test
    if source == "main" and "_pdv_" in job_name.lower() and "your-product-backend" in job_name.lower():
        source = "backend-pdv"
        logger.info(f"TFA auto-detected Backend PDV job: {job_name}, switching source to backend-pdv")

    # Check cache first for fast response
    cache_key = f"tfa:{source}:{job_name}:{build_number}{'_quick' if quick else ''}"
    cached_result = _get_tfa_cache(cache_key)
    if cached_result:
        logger.info(f"TFA cache hit for {job_name} #{build_number} (quick={quick})")
        return {**cached_result, "cached": True}

    try:
        from services.jenkins_client import get_dev_jenkins_client, get_jenkins_client

        # Select the appropriate Jenkins client and base URL based on source
        jenkins = get_jenkins_client()  # Always use main client (has backend_pdv_url configured)

        if source == "dev":
            jenkins = get_dev_jenkins_client()
            data_source_prefix = "dev-jenkins"
            if not jenkins.is_configured():
                raise HTTPException(status_code=503, detail="Dev Jenkins not configured.")
        elif source == "backend-pdv":
            # Use Backend PDV Jenkins URL (different server)
            data_source_prefix = "backend-pdv-jenkins"
            if not jenkins.backend_pdv_url:
                raise HTTPException(
                    status_code=503, detail="Backend PDV Jenkins not configured. Set JENKINS_BACKEND_PDV_URL."
                )
            # Note: base_url and auth_headers not needed for backend-pdv
            # The JenkinsClient.get_backend_pdv_* methods handle URL and auth
            logger.info(f"TFA using Backend PDV Jenkins: {jenkins.backend_pdv_url}")
        else:
            data_source_prefix = "jenkins"
            if not jenkins.is_configured():
                raise HTTPException(
                    status_code=503, detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN."
                )

        tfa_agent = get_tfa_agent()

        # For Dev pipelines: Skip test report (they're build pipelines, not test pipelines)
        # Only fetch console output and build changes
        if source == "dev":
            # First, get the build info to get the actual build URL (needed for multibranch pipelines)
            build_url = None
            try:
                build_info_url = f"{jenkins.base_url}/job/{job_name}/{build_number}/api/json?tree=url"
                build_info = await jenkins._make_request(build_info_url)
                if build_info and not build_info.get("error"):
                    build_url = build_info.get("url", "")
                    logger.info(f"Dev TFA: Got build URL for {job_name} #{build_number}: {build_url}")
            except Exception as e:
                logger.warning(f"Could not get build URL for {job_name} #{build_number}: {e}")

            async def fetch_console_output_dev():
                try:
                    if build_url:
                        console_data = await jenkins.get_console_output_by_url(build_url)
                    else:
                        console_data = await jenkins.get_console_output(job_name, build_number)
                    if console_data:
                        output = console_data.get("output", "") if isinstance(console_data, dict) else str(console_data)
                        return output[:3000]
                except Exception as e:
                    logger.warning("Could not get console output: %s", e)
                return ""

            async def fetch_build_changes_dev():
                try:
                    result = await jenkins.get_build_changes(job_name, build_number, build_url=build_url)
                    logger.info(f"build_changes result for {job_name} #{build_number}: {result}")
                    return result
                except Exception as e:
                    logger.warning("Could not get build changes: %s", e)
                return None

            # Fetch console output and build changes in parallel (no test report for Dev)
            console_output, build_changes = await asyncio.gather(fetch_console_output_dev(), fetch_build_changes_dev())

            # Extract error lines from console
            error_lines = []
            if console_output:
                lines = console_output.split("\n")
                error_keywords = ("error", "failed", "exception", "fatal", "cannot", "unable")
                error_lines = [
                    line.strip()
                    for line in lines
                    if any(kw in line.lower() for kw in error_keywords) and len(line.strip()) > 10
                ][-10:]

            commits = build_changes.get("commits", []) if build_changes else []
            logger.info(f"TFA Dev: build_changes={build_changes}, commits count={len(commits)}")

            # Use LLM to analyze build errors (via Ollama Gateway)
            ai_analysis = None
            analysis_engine = "pattern_based"
            try:
                ai_analysis = await tfa_agent.analyze_build_error(
                    job_name=job_name,
                    build_number=build_number,
                    console_output=console_output,
                    error_lines=error_lines,
                    commits=commits,
                )
                analysis_engine = ai_analysis.get("analysis_type", "pattern_based")
                logger.info(f"Dev TFA AI analysis completed: {analysis_engine}")
            except Exception as e:
                logger.warning(f"Dev TFA AI analysis failed, using fallback: {e}")

            # Build recommendations - use AI recommendations if available
            recommendations = []
            if ai_analysis and ai_analysis.get("recommendations"):
                recommendations = ai_analysis.get("recommendations", [])
            else:
                # Fallback recommendations
                if commits:
                    recommendations.append(f"Review the {len(commits)} commit(s) that triggered this build")
                    all_files = []
                    for commit in commits:
                        all_files.extend(commit.get("files", []))
                    if all_files:
                        recommendations.append(f"Check the {len(set(all_files))} changed file(s) for potential issues")
                if error_lines:
                    recommendations.append("Review the error messages in the console output below")
                recommendations.append("Check the full build console in Jenkins for more details")

            # Build root cause from AI analysis
            root_causes = []
            if ai_analysis:
                root_causes.append(
                    {
                        "type": ai_analysis.get("category", "build_error"),
                        "description": ai_analysis.get("root_cause", "Build failed - review console output"),
                        "severity": ai_analysis.get("severity", "high"),
                        "confidence": ai_analysis.get("confidence", "medium"),
                        "count": 1,
                    }
                )
            else:
                # Fallback root cause
                if not commits:
                    root_causes.append(
                        {
                            "type": "build_failure",
                            "description": "Build failed - review recent commits and console output.",
                            "severity": "high",
                            "count": 1,
                        }
                    )
                else:
                    root_causes.append(
                        {
                            "type": "code_change",
                            "description": f"Build failed after {len(commits)} commit(s) with {build_changes.get('totalFilesChanged', 0)} file(s) changed",
                            "severity": "high",
                            "count": 1,
                        }
                    )

            result = {
                "job": job_name,
                "buildNumber": build_number,
                "summary": {
                    "totalTests": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                },
                "analysisType": "build_changes",
                "analysisEngine": _get_tfa_engine_label_from_ai(ai_analysis, analysis_engine),
                "buildChanges": {
                    "commits": commits,
                    "totalCommits": build_changes.get("totalCommits", 0) if build_changes else 0,
                    "totalFilesChanged": build_changes.get("totalFilesChanged", 0) if build_changes else 0,
                },
                "errorLines": error_lines,
                "rootCauses": root_causes,
                "recommendations": recommendations,
                "failedTests": [],
                "dataSource": f"{data_source_prefix}-build-changes + tfa_agent (LLM)",
                "aiAnalysis": ai_analysis.get("raw_analysis", "") if ai_analysis else None,
            }

            # Cache the result
            _set_tfa_cache(cache_key, result)
            logger.info(f"Dev TFA cached for {job_name} #{build_number}")
            return result

        # For non-Dev pipelines: Fetch test report and console output in parallel
        async def fetch_test_report():
            if source == "backend-pdv":
                # Use JenkinsClient method for Backend PDV (handles auth correctly)
                return await jenkins.get_backend_pdv_test_report(job_name, build_number)
            else:
                return await jenkins.get_test_report(job_name, build_number)

        async def fetch_console_output():
            try:
                if source == "backend-pdv":
                    # Use JenkinsClient method for Backend PDV (handles auth correctly)
                    return await jenkins.get_backend_pdv_console_output(job_name, build_number)
                else:
                    console_data = await jenkins.get_console_output(job_name, build_number)
                    if console_data:
                        output = console_data.get("output", "") if isinstance(console_data, dict) else str(console_data)
                        return output[:3000]
            except Exception as e:
                logger.warning("Could not get console output: %s", e)
            return ""

        test_report, console_output = await asyncio.gather(fetch_test_report(), fetch_console_output())
        build_changes = None

        # Check for authentication failure
        if isinstance(test_report, dict) and test_report.get("error_type") == "auth_failed":
            raise HTTPException(
                status_code=401,
                detail="Backend PDV authentication failed. Set JENKINS_BACKEND_PDV_USER and JENKINS_BACKEND_PDV_TOKEN in .env",
            )

        # Handle case when no test report available (Dev pipelines already handled above)
        if not test_report:
            logger.warning(f"No test report found for {job_name} build #{build_number}")

            # For Backend PDV: Try to analyze console output (same as Endpoint PDV fallback)
            if source == "backend-pdv" and console_output:
                logger.info(f"No test report for Backend PDV {job_name} #{build_number}, analyzing console output")
                try:
                    # Extract error lines from console
                    error_lines = []
                    lines = console_output.split("\n")
                    error_keywords = ("error", "failed", "exception", "fatal", "cannot", "unable", "failure")
                    error_lines = [
                        line.strip()
                        for line in lines
                        if any(kw in line.lower() for kw in error_keywords) and len(line.strip()) > 10
                    ][-15:]

                    # Try AI analysis of console output
                    ai_analysis = None
                    analysis_engine = "pattern_based"
                    try:
                        ai_analysis = await tfa_agent.analyze_failure(
                            job_name=job_name,
                            build_number=build_number,
                            test_name="Build Failure",
                            test_class="",
                            error_message="No test report available - analyzing console output",
                            stack_trace="\n".join(error_lines),
                            console_output=console_output,
                        )
                        if ai_analysis and ai_analysis.get("analysis"):
                            analysis_engine = ai_analysis.get("analysis_method", "llm_rag")
                    except Exception as e:
                        logger.warning(f"Backend PDV console AI analysis failed: {e}")

                    # Build root causes from AI or pattern-based analysis
                    root_causes = []
                    recommendations = []

                    if ai_analysis and ai_analysis.get("analysis"):
                        result_analysis = ai_analysis.get("analysis", {})
                        root_causes.append(
                            {
                                "type": result_analysis.get("category", "build_failure"),
                                "description": result_analysis.get("root_cause", "Build failed before tests could run"),
                                "count": 1,
                                "severity": result_analysis.get("severity", "high"),
                                "confidence": result_analysis.get("confidence", "medium"),
                            }
                        )
                        recommendations = result_analysis.get("recommendations", [])
                    else:
                        # Pattern-based fallback
                        error_text = "\n".join(error_lines).lower()
                        if "timeout" in error_text or "timed out" in error_text:
                            root_causes.append(
                                {
                                    "type": "timeout",
                                    "description": "Build or test timed out - possible infrastructure or performance issue",
                                    "count": 1,
                                    "severity": "high",
                                }
                            )
                        elif "connection" in error_text or "refused" in error_text:
                            root_causes.append(
                                {
                                    "type": "network",
                                    "description": "Connection error - service may be down or unreachable",
                                    "count": 1,
                                    "severity": "high",
                                }
                            )
                        elif "permission" in error_text or "unauthorized" in error_text:
                            root_causes.append(
                                {
                                    "type": "permission",
                                    "description": "Permission or authorization error",
                                    "count": 1,
                                    "severity": "high",
                                }
                            )
                        else:
                            root_causes.append(
                                {
                                    "type": "build_failure",
                                    "description": "Build failed before tests could run - review console output",
                                    "count": 1,
                                    "severity": "high",
                                }
                            )

                    if not recommendations:
                        recommendations = [
                            "Check the console output for build errors",
                            "Verify the build configuration and dependencies",
                            "Check if the stack/environment is healthy",
                        ]

                    return {
                        "job": job_name,
                        "buildNumber": build_number,
                        "summary": {"totalTests": 0, "passed": 0, "failed": 0, "skipped": 0},
                        "rootCauses": root_causes,
                        "recommendations": recommendations[:5],
                        "failedTests": [],
                        "errorLines": error_lines,
                        "analysisType": "console_analysis",
                        "analysisEngine": _get_tfa_engine_label([], analysis_engine),
                        "dataSource": f"{data_source_prefix}-console",
                    }
                except Exception as e:
                    logger.warning(f"Backend PDV console analysis failed for {job_name} #{build_number}: {e}")

            # No test report and no console analysis - return 404
            raise HTTPException(status_code=404, detail=f"No test report found for {job_name} build #{build_number}")

        # Get failed tests from test report
        failed_tests = test_report.get("failedTests", [])

        # If test report exists but no failed tests, still show the summary
        if not failed_tests:
            passed = test_report.get("passCount", 0)
            failed = test_report.get("failCount", 0)
            skipped = test_report.get("skipCount", 0)
            # Calculate total from individual counts (Jenkins doesn't always return totalCount)
            total = test_report.get("totalCount") or (passed + failed + skipped)
            return {
                "job": job_name,
                "buildNumber": build_number,
                "summary": {
                    "totalTests": total,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                },
                "rootCauses": [],
                "recommendations": ["All tests passed - no failures to analyze"],
                "failedTests": [],
                "analysisType": "none",
                "dataSource": f"{data_source_prefix}-direct",
            }

        analyzed_failures = []

        # Quick mode: Skip LLM analysis, use pattern-based only
        if quick:
            logger.info(f"TFA quick mode for {job_name} #{build_number} - skipping LLM analysis")
            for test in failed_tests[:10]:
                error_msg = test.get("errorMessage", "")
                stack_trace = test.get("stackTrace", "")

                # Simple pattern-based categorization
                category = "unknown"
                root_cause = "Test failure detected"
                severity = "medium"

                error_lower = (error_msg + stack_trace).lower()
                if "timeout" in error_lower or "timed out" in error_lower:
                    category = "timeout"
                    root_cause = "Test timed out - possible performance issue or hanging operation"
                    severity = "high"
                elif "connection" in error_lower or "refused" in error_lower or "network" in error_lower:
                    category = "network"
                    root_cause = "Network/connection error - service may be down or unreachable"
                    severity = "high"
                elif "assert" in error_lower or "expected" in error_lower:
                    category = "assertion"
                    root_cause = "Assertion failed - expected value doesn't match actual"
                    severity = "medium"
                elif "null" in error_lower or "undefined" in error_lower or "none" in error_lower:
                    category = "null_reference"
                    root_cause = "Null/undefined reference - missing data or object"
                    severity = "medium"
                elif "permission" in error_lower or "unauthorized" in error_lower or "403" in error_lower:
                    category = "permission"
                    root_cause = "Permission/authorization error"
                    severity = "high"
                elif "not found" in error_lower or "404" in error_lower:
                    category = "not_found"
                    root_cause = "Resource not found - missing endpoint or data"
                    severity = "medium"

                analyzed_failures.append(
                    {
                        "test_name": test.get("name", "unknown"),
                        "test_class": test.get("className", ""),
                        "error_message": error_msg[:500],
                        "analysis": {
                            "category": category,
                            "root_cause": root_cause,
                            "severity": severity,
                            "confidence": "low",
                            "recommendations": [
                                "Review the error message and stack trace",
                                "Check recent code changes that may have caused this failure",
                            ],
                        },
                        "analysis_method": "pattern_based_quick",
                    }
                )
        else:
            # Full mode: Analyze failed tests with RAG + LLM IN PARALLEL for better performance
            async def analyze_single_test(test):
                try:
                    return await tfa_agent.analyze_failure(
                        job_name=job_name,
                        build_number=build_number,
                        test_name=test.get("name", "unknown"),
                        test_class=test.get("className", ""),
                        error_message=test.get("errorMessage", ""),
                        stack_trace=test.get("stackTrace", ""),
                        console_output=console_output,
                    )
                except Exception as e:
                    logger.warning("TFA analysis failed for test %s: %s", test.get("name", "unknown"), e)
                    return None

            # Run all analyses in parallel (limit to 10 tests max)
            analysis_results = await asyncio.gather(
                *[analyze_single_test(test) for test in failed_tests[:10]], return_exceptions=True
            )

            # Filter successful results
            for result in analysis_results:
                if result and not isinstance(result, Exception):
                    analyzed_failures.append(result)

        # Aggregate analysis
        categories = {}
        all_recommendations = []
        root_causes = []

        # Filter out None/invalid entries from analyzed_failures
        analyzed_failures = [af for af in analyzed_failures if af and isinstance(af, dict)]

        for af in analyzed_failures:
            analysis = af.get("analysis") or {}
            cat = analysis.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

            if analysis.get("root_cause"):
                root_causes.append(
                    {
                        "type": cat,
                        "description": analysis.get("root_cause"),
                        "count": 1,
                        "severity": analysis.get("severity", "medium"),
                        "confidence": analysis.get("confidence", "medium"),
                    }
                )

            recs = analysis.get("recommendations", [])
            if isinstance(recs, list):
                all_recommendations.extend(recs)

        # Deduplicate recommendations
        unique_recs = list(dict.fromkeys(all_recommendations))[:5]

        # Determine analysis method used
        analysis_method = "pattern_based"
        if analyzed_failures and isinstance(analyzed_failures[0], dict):
            analysis_method = analyzed_failures[0].get("analysis_method", "pattern_based")

        # Build summary from test report if available, otherwise use defaults
        summary = {
            "totalTests": 0,
            "passed": 0,
            "failed": len(failed_tests),
            "skipped": 0,
        }
        if test_report and isinstance(test_report, dict):
            passed = test_report.get("passCount", 0)
            failed = test_report.get("failCount", len(failed_tests))
            skipped = test_report.get("skipCount", 0)
            # Calculate total from individual counts (Jenkins doesn't always return totalCount)
            total = test_report.get("totalCount") or (passed + failed + skipped)
            summary = {
                "totalTests": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
            }

        # Build failure clusters for grouped view
        failure_clusters = _cluster_failures(analyzed_failures)

        result = {
            "job": job_name,
            "buildNumber": build_number,
            "summary": summary,
            "failureClusters": failure_clusters,
            "rootCauses": root_causes[:5],
            "recommendations": unique_recs,
            "failedTests": [
                {
                    "name": af.get("test_name"),
                    "className": af.get("test_class"),
                    "errorMessage": (af.get("analysis") or {}).get("root_cause", ""),
                    "stackTrace": "",  # Omit for brevity
                    "status": "FAILED",
                    "analysis": af.get("analysis"),
                    "similarFailures": af.get("similar_failures", []),
                }
                for af in analyzed_failures
                if af and isinstance(af, dict)
            ],
            "analysisType": analysis_method,
            "analysisEngine": _get_tfa_engine_label(analyzed_failures, analysis_method),
            "knowledgeBaseStats": tfa_agent.get_statistics(),
            "dataSource": f"{data_source_prefix} + tfa_agent (RAG)",
        }

        # Cache the result for future requests
        _set_tfa_cache(cache_key, result)
        logger.info(f"TFA analysis complete for {job_name} #{build_number}, cached for {_TFA_CACHE_TTL}s")

        return result
    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e).lower()
        logger.error("TFA error for %s #%s: %s", job_name, build_number, e)

        # Provide more specific error messages
        if "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            raise HTTPException(
                status_code=503,
                detail="Jenkins authentication failed. Check JENKINS_USER and JENKINS_TOKEN environment variables.",
            ) from e
        if "404" in error_str or "not found" in error_str:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Job '{job_name}' or build #{build_number} not found in Jenkins. " "Check the job name is correct."
                ),
            ) from e
        if "timeout" in error_str or "timed out" in error_str:
            raise HTTPException(
                status_code=504,
                detail=f"Jenkins request timed out for {job_name} #{build_number}. Jenkins may be slow or overloaded.",
            ) from e
        if "connection" in error_str or "refused" in error_str:
            raise HTTPException(
                status_code=503, detail="Cannot connect to Jenkins. Check JENKINS_URL and network connectivity."
            ) from e
        raise HTTPException(
            status_code=500, detail=f"TFA analysis failed for {job_name} #{build_number}: {str(e)}"
        ) from e


@router.get("/pdv-pipelines")
async def get_pdv_pipelines(
    include_builds: bool = Query(default=False, description="Include build history"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get status of Backend PDV (Post-Deployment Validation) pipelines.

    PURPOSE:
        Returns the status of backend service PDV test pipelines that validate
        services after deployment. These tests run against specific backend
        services like AddonMan, Device Classification, Enrollment, OTP, etc.

    WHEN TO USE:
        - Monitoring backend service health after deployments
        - Checking PDV test pass/fail status
        - Viewing PDV section on Monitoring page
        - Getting backend health for Overview page

    PARAMETERS:
        - include_builds (bool): Include recent build history (default: False)

    RETURNS:
        {
            "overall": {
                "totalPipelines": 5,
                "passing": 4,
                "failing": 1,
                "unstable": 0,
                "healthPercent": 80
            },
            "pipelines": [
                {
                    "name": "addonman-pdv",
                    "status": "success",
                    "lastBuild": {...},
                    "builds": [...]        # Only if include_builds=true
                }
            ],
            "dataSource": "jenkins-pdv"
        }

    PDV SERVICES MONITORED:
        - addonman pdv
        - deviceclassification pdv
        - enrollment service pdv
        - otp pdv
        - provisioner steering pdv

    RELATED ENDPOINTS:
        - GET /api/jenkins/golden-regression - Endpoint/E2E PDV tests
        - GET /api/overview - Includes PDV summary in overview
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Jenkins not configured. " "Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN environment variables."
                ),
            )

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        data = await jenkins.get_pdv_pipelines(include_builds=include_builds)

        if not data or data.get("error"):
            # Return empty result instead of error for better UX
            return {
                "overall": {"totalPipelines": 0, "passing": 0, "failing": 0, "unstable": 0, "healthPercent": 0},
                "pipelines": [],
                "dataSource": "jenkins-pdv",
                "message": "No PDV pipelines found. Check Jenkins job names.",
            }

        data["dataSource"] = "jenkins-pdv"
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDV pipelines error: %s", e)
        raise HTTPException(status_code=500, detail=f"Jenkins error: {e}") from e


@router.get("/golden-regression")
async def get_golden_regression_data(
    num_builds: int = Query(default=10, description="Number of builds to return"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get Golden Regression Suite (Endpoint PDV) test results.

    PURPOSE:
        Returns test results from the Golden Regression Suite which runs
        end-to-end tests across multiple stacks (regions/environments).
        This is the primary endpoint PDV (Post-Deployment Validation) data.

    WHEN TO USE:
        - Viewing Endpoint PDV / Golden Regression section on Monitoring page
        - Checking E2E test health across stacks
        - Identifying which stacks have failing tests
        - Viewing test pass rates per stack/region

    PARAMETERS:
        - num_builds (int): Number of recent builds to return (default: 10)

    RETURNS:
        {
            "builds": [...],               # Raw build data
            "pipelines": [...],            # Individual test pipelines
            "stackGroups": {
                "us-east-1": [
                    {
                        "buildNumber": 100,
                        "status": "success",
                        "passRate": 98.5,
                        "timestamp": "..."
                    }
                ],
                "eu-west-1": [...]
            },
            "sortedStacks": ["us-east-1", "eu-west-1", ...],
            "summary": {
                "totalStacks": 14,
                "successRate": 92.5,
                "totalTests": 500,
                "passedTests": 463
            },
            "jenkinsUrl": "https://jenkins.example.com/job/golden-regression",
            "dataSource": "jenkins-direct"
        }

    RELATED ENDPOINTS:
        - GET /api/jenkins/golden-regression/{build}/tfa - Test failure analysis
        - GET /api/jenkins/pdv-pipelines - Backend service PDV tests
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Jenkins not configured. Set JENKINS_URL, JENKINS_USER, "
                    "JENKINS_TOKEN, and JENKINS_GOLDEN_REGRESSION_URL."
                ),
            )

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        data = await jenkins.get_golden_regression(num_builds=num_builds)

        if not data or data.get("error"):
            error_msg = data.get("error", "Unknown error") if data else "No response"
            logger.error("Golden Regression error: %s", error_msg)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Failed to fetch Golden Regression data: {error_msg}. "
                    "Check JENKINS_GOLDEN_REGRESSION_URL environment variable."
                ),
            )

        # Return full response with pipelines and stack groups
        return {
            "builds": data.get("builds", []),
            "pipelines": data.get("pipelines", []),
            "stackGroups": data.get("stackGroups", {}),
            "sortedStacks": data.get("sortedStacks", []),
            "summary": data.get("summary", {}),
            "overallStats": data.get("summary", {}),  # Backward compatibility
            "jenkinsUrl": data.get("jenkinsUrl", ""),
            "dataSource": "jenkins-direct",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Golden Regression data: %s", e)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Failed to connect to Jenkins: {str(e)}. "
                "Check JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN environment variables."
            ),
        ) from e


@router.get("/golden-regression/{build_number}/tfa")
async def get_golden_regression_tfa(build_number: int):
    """
    Get AI-powered Test Failure Analysis for Golden Regression build.

    PURPOSE:
        Analyzes failed tests from a Golden Regression Suite build using
        the same RAG + LLM analysis as regular pipeline TFA. Identifies
        patterns across stacks and provides stack-specific recommendations.

    WHEN TO USE:
        - Investigating Golden Regression failures
        - Understanding why E2E tests failed across stacks
        - Finding common failure patterns
        - Getting AI recommendations for fixes

    PARAMETERS:
        - build_number (int): Golden Regression build number

    RETURNS:
        Same structure as /api/jenkins/tfa/{job}/{build}:
        {
            "job": "Golden Regression Suite",
            "buildNumber": 100,
            "summary": {...},
            "rootCauses": [...],
            "recommendations": [...],
            "failedTests": [...],
            "analysisType": "llm_rag",
            "dataSource": "jenkins-direct + tfa_agent (RAG)"
        }

    RELATED ENDPOINTS:
        - GET /api/jenkins/golden-regression - Get build list
        - GET /api/jenkins/tfa/{job}/{build} - Regular pipeline TFA
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()
        tfa_agent = get_tfa_agent()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503, detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN."
            )

        job_name = "Golden Regression Suite"
        console_output = ""

        # Try to get console output first (always needed for analysis)
        try:
            console_output = await jenkins.get_golden_regression_console(build_number) or ""
        except Exception as e:
            logger.warning("Could not get Golden Regression console output: %s", e)

        # Try to get test report data
        data = await jenkins.get_golden_regression_tfa(build_number)

        # Handle case when no test report available
        if not data or data.get("error"):
            error_msg = data.get("error", "Unknown error") if data else "No response"

            # Return 503 for configuration issues
            if "not configured" in error_msg.lower() or "environment variable" in error_msg.lower():
                raise HTTPException(status_code=503, detail=f"Jenkins Golden Regression not configured: {error_msg}")

            # If we have console output, try to analyze it even without test report
            if console_output:
                logger.info("No test report for build #%s, analyzing console output", build_number)
                try:
                    analysis = await tfa_agent.analyze_failure(
                        job_name=job_name,
                        build_number=build_number,
                        test_name="Build Failure",
                        test_class="",
                        error_message="No test report available - analyzing console output",
                        stack_trace="",
                        console_output=console_output,
                    )
                    if analysis and analysis.get("analysis"):
                        result_analysis = analysis.get("analysis", {})
                        return {
                            "job": job_name,
                            "buildNumber": build_number,
                            "summary": {"totalTests": 0, "passed": 0, "failed": 0, "skipped": 0},
                            "rootCauses": [
                                {
                                    "type": result_analysis.get("category", "build_failure"),
                                    "description": result_analysis.get(
                                        "root_cause", "Build failed before tests could run"
                                    ),
                                    "count": 1,
                                    "severity": result_analysis.get("severity", "high"),
                                }
                            ],
                            "recommendations": result_analysis.get(
                                "recommendations",
                                [
                                    "Check the console output for build errors",
                                    "Verify the build configuration and dependencies",
                                ],
                            ),
                            "failedTests": [],
                            "analysisType": "console_analysis",
                            "dataSource": "jenkins-console",
                        }
                except Exception as e:
                    logger.warning("Console analysis failed for build #%s: %s", build_number, e)

            # No test report and no console output (or analysis failed)
            # Return a valid response with helpful info (no error field so UI shows root causes)
            return {
                "job": job_name,
                "buildNumber": build_number,
                "summary": {"totalTests": 0, "passed": 0, "failed": 0, "skipped": 0},
                "rootCauses": [
                    {
                        "type": "no_data",
                        "description": f"No test report available: {error_msg}",
                        "count": 1,
                        "severity": "unknown",
                    }
                ],
                "recommendations": [
                    "This build may have been aborted or is still running",
                    "Check the build status directly in Jenkins",
                    "Verify the build produced test results",
                ],
                "failedTests": [],
                "analysisType": "none",
                "dataSource": "unavailable",
            }

        # Get failed tests for analysis
        failed_tests = data.get("failedTests", [])
        job_name = data.get("job", job_name)

        # If test report exists but no failed tests, return summary
        if not failed_tests:
            return {
                "job": job_name,
                "buildNumber": build_number,
                "summary": data.get("summary", {"totalTests": 0, "passed": 0, "failed": 0, "skipped": 0}),
                "rootCauses": [],
                "recommendations": ["All tests passed - no failures to analyze"],
                "failedTests": [],
                "analysisType": "none",
                "dataSource": "jenkins-direct",
            }

        # Use TFA agent to analyze each failed test (same as regular pipeline TFA)
        analyzed_failures = []
        for test in failed_tests[:10]:  # Limit to 10 tests for performance
            try:
                analysis = await tfa_agent.analyze_failure(
                    job_name=job_name,
                    build_number=build_number,
                    test_name=test.get("name", "unknown"),
                    test_class=test.get("className", ""),
                    error_message=test.get("errorMessage", ""),
                    stack_trace=test.get("stackTrace", ""),
                    console_output=console_output,
                )
                if analysis:
                    analyzed_failures.append(analysis)
            except Exception as e:
                logger.warning("TFA analysis failed for test %s: %s", test.get("name", "unknown"), e)

        # Aggregate analysis (same logic as regular TFA)
        categories = {}
        all_recommendations = []
        root_causes = []

        # Filter out None/invalid entries from analyzed_failures
        analyzed_failures = [af for af in analyzed_failures if af and isinstance(af, dict)]

        for af in analyzed_failures:
            analysis = af.get("analysis") or {}
            cat = analysis.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

            if analysis.get("root_cause"):
                root_causes.append(
                    {
                        "type": cat,
                        "description": analysis.get("root_cause"),
                        "count": 1,
                        "severity": analysis.get("severity", "medium"),
                        "confidence": analysis.get("confidence", "medium"),
                    }
                )

            recs = analysis.get("recommendations", [])
            if isinstance(recs, list):
                all_recommendations.extend(recs)

        # Deduplicate recommendations
        unique_recs = list(dict.fromkeys(all_recommendations))[:5]

        # Fallback to basic pattern matching if no AI analysis available
        if not root_causes:
            timeout_count = sum(1 for t in failed_tests if "timeout" in (t.get("errorMessage") or "").lower())
            api_error_count = sum(
                1
                for t in failed_tests
                if any(kw in (t.get("errorMessage") or "").lower() for kw in ["api", "connection"])
            )
            assertion_count = sum(1 for t in failed_tests if "assert" in (t.get("errorMessage") or "").lower())

            if timeout_count > 0:
                root_causes.append(
                    {
                        "type": "timeout",
                        "count": timeout_count,
                        "description": "Tests are timing out - may indicate slow services or network issues",
                    }
                )
            if api_error_count > 0:
                root_causes.append(
                    {
                        "type": "api_error",
                        "count": api_error_count,
                        "description": "API/Connection errors - backend services may be failing",
                    }
                )
            if assertion_count > 0:
                root_causes.append(
                    {
                        "type": "assertion",
                        "count": assertion_count,
                        "description": "Assertion failures - test expectations not met",
                    }
                )

        # Fallback recommendations if none from AI
        if not unique_recs and failed_tests:
            unique_recs = [
                "Review test expectations and actual behavior",
                "Check for recent code changes that may have caused regressions",
            ]
            if len(failed_tests) > 5:
                unique_recs.append("High number of failures - consider rolling back recent changes")

        # Determine analysis method used
        analysis_method = "pattern_based"
        if analyzed_failures:
            analysis_method = analyzed_failures[0].get("analysis_method", "pattern_based")

        # Build failure clusters for grouped view
        failure_clusters = _cluster_failures(analyzed_failures)

        return {
            "job": job_name,
            "buildNumber": build_number,
            "summary": data.get("summary", {}),
            "failureClusters": failure_clusters,
            "rootCauses": root_causes[:5],
            "recommendations": unique_recs,
            "failedTests": (
                [
                    {
                        "name": af.get("test_name"),
                        "className": af.get("test_class"),
                        "errorMessage": (af.get("analysis") or {}).get("root_cause", ""),
                        "stackTrace": "",  # Omit for brevity
                        "status": "FAILED",
                        "analysis": af.get("analysis"),
                        "similarFailures": af.get("similar_failures", []),
                    }
                    for af in analyzed_failures
                    if af and isinstance(af, dict)
                ]
                if analyzed_failures
                else failed_tests
            ),
            "analysisType": analysis_method,
            "analysisEngine": _get_tfa_engine_label(analyzed_failures, analysis_method),
            "knowledgeBaseStats": tfa_agent.get_statistics(),
            "dataSource": "jenkins-direct + tfa_agent (RAG)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Golden Regression TFA for build %s: %s", build_number, e)
        raise HTTPException(
            status_code=503, detail=f"Failed to fetch test failure analysis: {str(e)}. Check Jenkins connection."
        ) from e


# ============ Backend PDV Endpoints ============


@router.get("/backend-pdv-jobs")
async def list_backend_pdv_jobs():
    """
    List all available jobs on the Backend PDV Jenkins server.

    PURPOSE:
        Discovers what jobs are available on the Backend PDV Jenkins server
        at http://10.136.208.148:8080/job/BACKEND/

    RETURNS:
        {
            "jobs": [{"name": "job_name", "url": "...", "status": "blue"}],
            "total": 5,
            "jenkinsUrl": "http://10.136.208.148:8080/job/BACKEND"
        }
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()
        result = await jenkins.list_backend_pdv_jobs()

        if result.get("error"):
            raise HTTPException(status_code=503, detail=result.get("error"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing Backend PDV jobs: %s", e)
        raise HTTPException(status_code=503, detail=f"Failed to list Backend PDV jobs: {str(e)}") from e


@router.get("/backend-pdv-by-stack")
async def get_backend_pdv_by_stack(
    num_builds: int = Query(
        default=30,
        ge=1,
        le=100,
        description="Number of recent builds per pipeline (more = better stack coverage for infrequent pipelines)",
    ),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get Backend PDV pipelines grouped by stack and by pipeline.

    PURPOSE:
        Returns Backend PDV test results organized in two views:
        1. By Stack - See all pipeline results for each stack (fra2, stg01, etc.)
        2. By Pipeline - See all stack results for each pipeline (addonman, enrollment, etc.)

    WHEN TO USE:
        - Viewing Backend PDV section with stack-based grouping
        - Analyzing which stacks have failing tests
        - Comparing pipeline health across different stacks
        - Identifying patterns in failures per stack or pipeline

    PARAMETERS:
        - num_builds (int): Number of recent builds per pipeline (default: 5, max: 20)
        - force_refresh (bool): Bypass cache (default: False)

    RETURNS:
        {
            "byStack": {
                "fra2": {
                    "pipelines": [...],
                    "summary": { "total": 5, "passed": 4, "failed": 1, "passRate": 80 }
                }
            },
            "byPipeline": {
                "addonman": {
                    "stacks": { "fra2": {...}, "stg01": {...} },
                    "summary": { "totalStacks": 5, "passingStacks": 4, "passRate": 80 }
                }
            },
            "stackMatrix": {
                "stacks": ["fra2", "stg01"],
                "pipelines": ["addonman", "enrollment"],
                "matrix": { "fra2": { "addonman": "success" } }
            },
            "summary": {
                "totalRuns": 25,
                "totalStacks": 5,
                "totalPipelines": 5,
                "overallPassRate": 85
            }
        }

    RELATED ENDPOINTS:
        - GET /api/jenkins/pdv-pipelines - Original flat PDV pipeline list
        - GET /api/jenkins/golden-regression - Endpoint PDV tests
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN.",
            )

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        # Get PDV pipelines with builds
        pdv_data = await jenkins.get_pdv_pipelines(include_builds=True, num_builds=num_builds)

        if pdv_data.get("error"):
            raise HTTPException(status_code=503, detail=pdv_data.get("error"))

        # Data structures for grouping
        by_stack = {}  # stack -> {pipelines: [...], summary: {...}}
        by_pipeline = {}  # pipeline_key -> {stacks: {...}, summary: {...}}
        stack_matrix = {}  # stack -> {pipeline_key: status}
        all_stacks = set()
        all_pipeline_keys = set()
        total_runs = 0
        total_passed = 0
        total_failed = 0

        # Pipeline key mapping for cleaner names - dynamically handles all jobs from Backend PDV Jenkins
        def get_pipeline_key(name):
            """Extract short pipeline key from full name."""
            # Remove common prefixes/suffixes to get a clean key
            key = name.lower()
            key = key.replace("your-product-backend_", "")
            key = key.replace("_pdv_test", "")
            key = key.replace("_pdv", "")
            key = key.replace("_test", "")
            key = key.replace("new_", "")
            key = key.replace("-", "_")
            return key

        def get_pipeline_display_name(key, original_name=""):
            """Get display name for pipeline key."""
            # Format the key into a readable display name
            display = key.replace("_", " ").title()
            # Add appropriate suffix based on original name
            if original_name:
                name_lower = original_name.lower()
                if "pdv" in name_lower:
                    if not display.lower().endswith("pdv"):
                        display += " PDV"
                elif "regression" in name_lower:
                    if not display.lower().endswith("regression"):
                        display += " Regression"
                else:
                    if not display.lower().endswith("test"):
                        display += " Test"
            return display

        # Process PDV pipelines (only jobs with _pdv_ in name)
        for pipeline in pdv_data.get("pipelines", []):
            pipeline_name = pipeline.get("fullName") or pipeline.get("name")

            # Skip jobs that don't have _pdv_ in their name
            if "_pdv_" not in pipeline_name.lower():
                continue

            pipeline_display = pipeline.get("name", pipeline_name)
            pipeline_key = get_pipeline_key(pipeline_name)

            all_pipeline_keys.add(pipeline_key)

            # Initialize pipeline entry
            if pipeline_key not in by_pipeline:
                by_pipeline[pipeline_key] = {
                    "name": pipeline_name,
                    "displayName": get_pipeline_display_name(pipeline_key, pipeline_name),
                    "stacks": {},
                    "allBuilds": [],
                    "summary": {"totalStacks": 0, "passingStacks": 0, "failingStacks": 0, "passRate": 0},
                }

            # Track failure counts per stack for this pipeline
            pipeline_stack_failures = {}

            # Process each build in the pipeline
            for build in pipeline.get("recentBuilds", []):
                build_number = build.get("buildNumber")
                if not build_number:
                    continue

                # Stack is now pre-fetched in the build data (optimized - no separate API call needed)
                # Skip builds with no stack value
                stack = build.get("stack", "")
                if not stack or stack.lower().strip() in ("", "no stack"):
                    continue
                stack = stack.lower().strip()
                all_stacks.add(stack)

                status = build.get("status", "unknown")
                is_passed = status == "success"
                is_failed = status in ("failed", "unstable", "aborted")

                total_runs += 1
                if is_passed:
                    total_passed += 1
                elif is_failed:
                    total_failed += 1

                # Track failures per stack for hotspot detection
                if is_failed:
                    pipeline_stack_failures[stack] = pipeline_stack_failures.get(stack, 0) + 1

                build_data = {
                    "buildNumber": build_number,
                    "status": status,
                    "stack": stack,
                    "timestamp": build.get("timestamp"),
                    "timestampMs": build.get("timestampMs", 0),
                    "duration": build.get("duration"),
                    "url": build.get("url"),
                    "pipelineName": pipeline_display,
                    "pipelineKey": pipeline_key,
                }

                # Add to by_stack grouping
                if stack not in by_stack:
                    by_stack[stack] = {
                        "name": stack,
                        "displayName": stack.upper(),
                        "pipelines": {},
                        "allBuilds": [],
                        "summary": {"total": 0, "passed": 0, "failed": 0, "passRate": 0},
                    }

                if pipeline_key not in by_stack[stack]["pipelines"]:
                    by_stack[stack]["pipelines"][pipeline_key] = {
                        "name": pipeline_name,
                        "displayName": get_pipeline_display_name(pipeline_key, pipeline_name),
                        "builds": [],
                        "latestStatus": None,
                        "latestBuild": None,
                    }

                by_stack[stack]["pipelines"][pipeline_key]["builds"].append(build_data)
                by_stack[stack]["allBuilds"].append(build_data)

                # Add to by_pipeline grouping
                if stack not in by_pipeline[pipeline_key]["stacks"]:
                    by_pipeline[pipeline_key]["stacks"][stack] = {
                        "name": stack,
                        "displayName": stack.upper(),
                        "builds": [],
                        "latestStatus": None,
                        "latestBuild": None,
                    }

                by_pipeline[pipeline_key]["stacks"][stack]["builds"].append(build_data)
                by_pipeline[pipeline_key]["allBuilds"].append(build_data)

                # Update stack matrix
                if stack not in stack_matrix:
                    stack_matrix[stack] = {}

        # Calculate summaries and set latest status for each grouping
        sorted_stacks = sorted(list(all_stacks))
        sorted_pipelines = sorted(list(all_pipeline_keys))

        # Process by_stack summaries
        for stack, stack_data in by_stack.items():
            passed = 0
            failed = 0
            for pipeline_key, pipeline_data in stack_data["pipelines"].items():
                # Sort builds by build number (descending) and set latest
                pipeline_data["builds"].sort(key=lambda b: b.get("buildNumber", 0), reverse=True)
                if pipeline_data["builds"]:
                    latest = pipeline_data["builds"][0]
                    pipeline_data["latestStatus"] = latest["status"]
                    pipeline_data["latestBuild"] = latest

                    # Update matrix
                    if stack not in stack_matrix:
                        stack_matrix[stack] = {}
                    stack_matrix[stack][pipeline_key] = latest["status"]

                    if latest["status"] == "success":
                        passed += 1
                    elif latest["status"] in ("failed", "unstable", "aborted"):
                        failed += 1

            total = passed + failed
            stack_data["summary"] = {
                "total": total,
                "passed": passed,
                "failed": failed,
                "passRate": round((passed / total) * 100) if total > 0 else 0,
            }

        # Process by_pipeline summaries
        for pipeline_key, pipeline_data in by_pipeline.items():
            passing_stacks = 0
            failing_stacks = 0
            for stack, stack_info in pipeline_data["stacks"].items():
                # Sort builds by build number (descending) and set latest
                stack_info["builds"].sort(key=lambda b: b.get("buildNumber", 0), reverse=True)
                if stack_info["builds"]:
                    latest = stack_info["builds"][0]
                    stack_info["latestStatus"] = latest["status"]
                    stack_info["latestBuild"] = latest

                    if latest["status"] == "success":
                        passing_stacks += 1
                    elif latest["status"] in ("failed", "unstable", "aborted"):
                        failing_stacks += 1

            total_stacks = passing_stacks + failing_stacks
            pipeline_data["summary"] = {
                "totalStacks": total_stacks,
                "passingStacks": passing_stacks,
                "failingStacks": failing_stacks,
                "passRate": round((passing_stacks / total_stacks) * 100) if total_stacks > 0 else 0,
            }

        # Overall summary
        overall_pass_rate = round((total_passed / total_runs) * 100) if total_runs > 0 else 0

        # Count stacks that have at least one failing pipeline (based on latest build)
        failed_stacks_count = 0
        for stack in sorted_stacks:
            stack_statuses = stack_matrix.get(stack, {})
            has_failure = any(status in ("failed", "unstable", "aborted") for status in stack_statuses.values())
            if has_failure:
                failed_stacks_count += 1

        return {
            "byStack": by_stack,
            "byPipeline": by_pipeline,
            "stackMatrix": {
                "stacks": sorted_stacks,
                "pipelines": sorted_pipelines,
                "pipelineDisplayNames": {k: get_pipeline_display_name(k) for k in sorted_pipelines},
                "matrix": stack_matrix,
            },
            "summary": {
                "totalRuns": total_runs,
                "totalPassed": total_passed,
                "totalFailed": total_failed,
                "totalStacks": len(all_stacks),
                "failedStacks": failed_stacks_count,
                "totalPipelines": len(all_pipeline_keys),
                "overallPassRate": overall_pass_rate,
                "stacksList": sorted_stacks,
                "pipelinesList": sorted_pipelines,
            },
            "dataSource": "jenkins-pdv-by-stack",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Backend PDV by stack: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Backend PDV by stack: {str(e)}") from e


# ============ Regression Pipelines by Stack Endpoint ============


@router.get("/regression-summary")
async def get_regression_summary(
    num_builds: int = Query(default=30, ge=1, le=100, description="Number of recent builds per pipeline"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get Regression pipelines grouped by stack and by pipeline.

    PURPOSE:
        Returns Regression test results organized in two views:
        1. By Stack - See all pipeline results for each stack (fra2, stg01, etc.)
        2. By Pipeline - See all stack results for each pipeline (addonman, otp, etc.)

    WHEN TO USE:
        - Viewing Jenkins Regression section with stack-based grouping
        - Analyzing which stacks have failing regression tests
        - Comparing pipeline health across different stacks
        - Identifying patterns in failures per stack or pipeline

    PARAMETERS:
        - num_builds (int): Number of recent builds per pipeline (default: 30, max: 100)
        - force_refresh (bool): Bypass cache (default: False)

    RETURNS:
        {
            "byStack": { "fra2": { "pipelines": [...], "summary": {...} } },
            "byPipeline": { "addonman": { "stacks": {...}, "summary": {...} } },
            "stackMatrix": { "stacks": [...], "pipelines": [...], "matrix": {...} },
            "summary": { "totalRuns": 25, "totalStacks": 5, "overallPassRate": 85 }
        }

    RELATED ENDPOINTS:
        - GET /api/jenkins/pipelines - Original flat pipeline list
        - GET /api/jenkins/backend-pdv-by-stack - Backend PDV by stack
    """
    try:
        from services.jenkins_client import get_jenkins_client

        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Jenkins not configured. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN.",
            )

        # Clear cache if force refresh requested
        if force_refresh:
            jenkins.clear_cache()

        # Get regression pipelines with builds (includes stack parameters)
        pipelines_data = await jenkins.get_pipelines(include_builds=True, num_builds=num_builds)

        if pipelines_data.get("error"):
            raise HTTPException(status_code=503, detail=pipelines_data.get("error"))

        # Data structures for grouping
        by_stack = {}  # stack -> {pipelines: [...], summary: {...}}
        by_pipeline = {}  # pipeline_key -> {stacks: {...}, summary: {...}}
        stack_matrix = {}  # stack -> {pipeline_key: status}
        all_stacks = set()
        all_pipeline_keys = set()
        total_runs = 0
        total_passed = 0
        total_failed = 0

        # Pipeline key mapping for cleaner names
        def get_pipeline_key(name):
            """Extract short pipeline key from full name."""
            name_lower = name.lower()
            if "addonman" in name_lower:
                return "addonman"
            elif "clientstatus" in name_lower:
                return "clientstatus"
            elif "deviceclassification" in name_lower or "device_classification" in name_lower:
                return "deviceclass"
            elif "downloader" in name_lower:
                return "downloader"
            elif "enforcer" in name_lower:
                return "enforcer"
            elif "enrollment" in name_lower:
                return "enrollment"
            elif "otp" in name_lower:
                return "otp"
            elif "provisioner" in name_lower or "steering" in name_lower:
                return "provisioner"
            elif "pycore" in name_lower:
                return "pycore"
            return name.replace("your-product-backend_", "").replace("_regression_test", "").replace("_regression", "")

        def get_pipeline_display_name(key, original_name=""):
            """Get display name for pipeline key."""
            display_names = {
                "addonman": "Addonman",
                "clientstatus": "Client Status",
                "deviceclass": "Device Classification",
                "downloader": "Downloader",
                "enforcer": "Enforcer",
                "enrollment": "Enrollment Service",
                "otp": "OTP",
                "provisioner": "Provisioner Steering",
                "pycore": "PyCore",
            }
            return display_names.get(key, key.replace("_", " ").title())

        # Process each pipeline
        for pipeline in pipelines_data.get("pipelines", []):
            pipeline_name = pipeline.get("fullName") or pipeline.get("name")
            pipeline_display = pipeline.get("name", pipeline_name)
            pipeline_key = get_pipeline_key(pipeline_name)
            all_pipeline_keys.add(pipeline_key)

            # Initialize pipeline entry
            if pipeline_key not in by_pipeline:
                by_pipeline[pipeline_key] = {
                    "name": pipeline_name,
                    "displayName": get_pipeline_display_name(pipeline_key, pipeline_name),
                    "stacks": {},
                    "allBuilds": [],
                    "summary": {"totalStacks": 0, "passingStacks": 0, "failingStacks": 0, "passRate": 0},
                }

            # Process each build in the pipeline
            for build in pipeline.get("recentBuilds", []):
                build_number = build.get("buildNumber")
                if not build_number:
                    continue

                # Use "default" for builds without a stack parameter
                stack = build.get("stack", "")
                if not stack or stack.lower().strip() in ("", "no stack"):
                    stack = "default"
                else:
                    stack = stack.lower().strip()
                all_stacks.add(stack)

                status = build.get("status", "unknown")
                is_passed = status == "success"
                is_failed = status in ("failed", "unstable", "aborted")

                total_runs += 1
                if is_passed:
                    total_passed += 1
                elif is_failed:
                    total_failed += 1

                # Display name for stack (special case for "default")
                stack_display = "No Stack" if stack == "default" else stack.upper()

                build_data = {
                    "buildNumber": build_number,
                    "status": status,
                    "stack": stack,
                    "timestamp": build.get("timestamp"),
                    "timestampMs": build.get("timestampMs", 0),
                    "duration": build.get("duration"),
                    "url": build.get("url"),
                    "pipelineName": pipeline_display,
                    "pipelineKey": pipeline_key,
                }

                # Add to by_stack grouping
                if stack not in by_stack:
                    by_stack[stack] = {
                        "name": stack,
                        "displayName": stack_display,
                        "pipelines": {},
                        "allBuilds": [],
                        "summary": {"total": 0, "passed": 0, "failed": 0, "passRate": 0},
                    }

                if pipeline_key not in by_stack[stack]["pipelines"]:
                    by_stack[stack]["pipelines"][pipeline_key] = {
                        "name": pipeline_name,
                        "displayName": get_pipeline_display_name(pipeline_key, pipeline_name),
                        "builds": [],
                        "latestStatus": None,
                        "latestBuild": None,
                    }

                by_stack[stack]["pipelines"][pipeline_key]["builds"].append(build_data)
                by_stack[stack]["allBuilds"].append(build_data)

                # Add to by_pipeline grouping
                if stack not in by_pipeline[pipeline_key]["stacks"]:
                    by_pipeline[pipeline_key]["stacks"][stack] = {
                        "name": stack,
                        "displayName": stack_display,
                        "builds": [],
                        "latestStatus": None,
                        "latestBuild": None,
                    }

                by_pipeline[pipeline_key]["stacks"][stack]["builds"].append(build_data)
                by_pipeline[pipeline_key]["allBuilds"].append(build_data)

                # Update stack matrix
                if stack not in stack_matrix:
                    stack_matrix[stack] = {}

        # Calculate summaries and set latest status for each grouping
        sorted_stacks = sorted(list(all_stacks))
        sorted_pipelines = sorted(list(all_pipeline_keys))

        # Process by_stack summaries
        for stack, stack_data in by_stack.items():
            passed = 0
            failed = 0
            for pipeline_key, pipeline_data in stack_data["pipelines"].items():
                # Sort builds by build number (descending) and set latest
                pipeline_data["builds"].sort(key=lambda b: b.get("buildNumber", 0), reverse=True)
                if pipeline_data["builds"]:
                    latest = pipeline_data["builds"][0]
                    pipeline_data["latestStatus"] = latest["status"]
                    pipeline_data["latestBuild"] = latest

                    # Update matrix
                    if stack not in stack_matrix:
                        stack_matrix[stack] = {}
                    stack_matrix[stack][pipeline_key] = latest["status"]

                    if latest["status"] == "success":
                        passed += 1
                    elif latest["status"] in ("failed", "unstable", "aborted"):
                        failed += 1

            total = passed + failed
            stack_data["summary"] = {
                "total": total,
                "passed": passed,
                "failed": failed,
                "passRate": round((passed / total) * 100) if total > 0 else 0,
            }

        # Process by_pipeline summaries
        for pipeline_key, pipeline_data in by_pipeline.items():
            passing_stacks = 0
            failing_stacks = 0
            for stack, stack_info in pipeline_data["stacks"].items():
                # Sort builds by build number (descending) and set latest
                stack_info["builds"].sort(key=lambda b: b.get("buildNumber", 0), reverse=True)
                if stack_info["builds"]:
                    latest = stack_info["builds"][0]
                    stack_info["latestStatus"] = latest["status"]
                    stack_info["latestBuild"] = latest

                    if latest["status"] == "success":
                        passing_stacks += 1
                    elif latest["status"] in ("failed", "unstable", "aborted"):
                        failing_stacks += 1

            total_stacks = passing_stacks + failing_stacks
            pipeline_data["summary"] = {
                "totalStacks": total_stacks,
                "passingStacks": passing_stacks,
                "failingStacks": failing_stacks,
                "passRate": round((passing_stacks / total_stacks) * 100) if total_stacks > 0 else 0,
            }

        # Overall summary
        overall_pass_rate = round((total_passed / total_runs) * 100) if total_runs > 0 else 0

        # Debug logging to compare with Overview page
        logger.info(
            f"DevPipelines: total_runs={total_runs}, total_passed={total_passed}, total_failed={total_failed}, pass_rate={overall_pass_rate}%"
        )
        logger.info(f"DevPipelines: pipelines_count={len(all_pipeline_keys)}, stacks_count={len(all_stacks)}")

        return {
            "byStack": by_stack,
            "byPipeline": by_pipeline,
            "stackMatrix": {
                "stacks": sorted_stacks,
                "pipelines": sorted_pipelines,
                "pipelineDisplayNames": {k: get_pipeline_display_name(k) for k in sorted_pipelines},
                "matrix": stack_matrix,
            },
            "summary": {
                "totalRuns": total_runs,
                "totalPassed": total_passed,
                "totalFailed": total_failed,
                "totalStacks": len(all_stacks),
                "totalPipelines": len(all_pipeline_keys),
                "overallPassRate": overall_pass_rate,
                "stacksList": sorted_stacks,
                "pipelinesList": sorted_pipelines,
            },
            "dataSource": "jenkins-regression-summary",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Regression by stack: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Regression by stack: {str(e)}") from e


# ============ Dev Pipelines Endpoint ============


@router.get("/dev-pipelines")
async def get_dev_pipelines(
    num_builds: int = Query(default=10, ge=1, le=50, description="Number of recent builds per pipeline"),
    force_refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get Dev pipelines status (Feature, Develop, Release pipelines).

    PURPOSE:
        Returns the status of Dev pipelines that track client builds:
        - client-feature-pipeline: Feature branch builds
        - client-develop-pipeline: Develop branch builds
        - client-release-pipeline: Release branch builds

    WHEN TO USE:
        - Viewing Dev Pipelines section in Pipelines group
        - Monitoring client build status across branches
        - Checking build health for feature/develop/release branches

    PARAMETERS:
        - num_builds (int): Number of recent builds per pipeline (default: 10, max: 50)
        - force_refresh (bool): Bypass cache (default: False)

    RETURNS:
        {
            "pipelines": [
                {
                    "name": "client-feature-pipeline",
                    "displayName": "Feature Pipeline",
                    "status": "success",
                    "url": "https://iad0-cisystem.example.com/job/client-feature-pipeline/",
                    "lastBuild": {...},
                    "recentBuilds": [...]
                }
            ],
            "summary": {
                "total": 3,
                "success": 2,
                "failed": 1,
                "successRate": 67
            }
        }

    ENVIRONMENT VARIABLES:
        - JENKINS_DEV_URL: Dev Jenkins server URL (default: https://iad0-cisystem.example.com)
        - JENKINS_DEV_USER: Dev Jenkins username (falls back to JENKINS_USER)
        - JENKINS_DEV_TOKEN: Dev Jenkins API token (falls back to JENKINS_TOKEN)

    RELATED ENDPOINTS:
        - GET /api/jenkins/backend-pdv-by-stack - Backend PDV pipelines
        - GET /api/jenkins/regression-summary - Regression pipelines
    """
    try:
        from services.jenkins_client import get_dev_jenkins_client

        dev_jenkins = get_dev_jenkins_client()

        if not dev_jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Dev Jenkins not configured. "
                    "Set JENKINS_DEV_URL, JENKINS_DEV_USER, and JENKINS_DEV_TOKEN environment variables "
                    "(or JENKINS_USER/JENKINS_TOKEN as fallback)."
                ),
            )

        # Clear cache if force refresh requested
        if force_refresh:
            dev_jenkins.clear_cache()

        # Get dev pipelines with builds
        data = await dev_jenkins.get_dev_pipelines(num_builds=num_builds)

        if data.get("error"):
            raise HTTPException(status_code=503, detail=data.get("error"))

        data["dataSource"] = "jenkins-dev-pipelines"
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Dev pipelines: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Dev pipelines: {str(e)}") from e


@router.get("/dev-pipelines/{pipeline_name}")
async def get_single_dev_pipeline(
    pipeline_name: str,
    num_builds: int = Query(default=10, ge=1, le=50, description="Number of recent builds"),
):
    """
    Get a single Dev pipeline status (for progressive loading).

    PURPOSE:
        Returns status for a single Dev pipeline, enabling faster initial render
        by loading pipelines one at a time instead of waiting for all.

    PARAMETERS:
        - pipeline_name (str): Pipeline name (e.g., "client-feature-pipeline")
        - num_builds (int): Number of recent builds (default: 10)

    RETURNS:
        Single pipeline object with status, builds, and health info.
    """
    try:
        from services.jenkins_client import get_dev_jenkins_client

        dev_jenkins = get_dev_jenkins_client()

        if not dev_jenkins.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Dev Jenkins not configured.",
            )

        data = await dev_jenkins.get_single_pipeline(pipeline_name, num_builds)

        if data.get("error"):
            raise HTTPException(status_code=404, detail=data.get("error"))

        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching Dev pipeline %s: %s", pipeline_name, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Dev pipeline: {str(e)}") from e


@router.get("/all-pipelines")
async def get_all_pipelines(num_builds: int = 10, force_refresh: bool = False, include: str = "dev,pdv,regression"):
    """
    Get all pipeline data in a single API call.

    PURPOSE:
        Fetches Dev, PDV, and Regression pipeline data in parallel,
        reducing the number of API calls needed when loading dashboard pages.

    PARAMETERS:
        - num_builds (int): Number of recent builds per pipeline (default: 10)
        - force_refresh (bool): Force refresh cache (default: false)
        - include (str): Comma-separated list of pipeline types to include
            Options: dev, pdv, regression (default: all)

    RETURNS:
        {
            "dev": { "pipelines": [...], "summary": {...} },
            "pdv": { "byStack": {...}, "summary": {...} },
            "regression": { "byStack": {...}, "summary": {...} },
            "fetchedAt": "2024-01-01T12:00:00Z",
            "dataSource": "jenkins-unified"
        }

    OPTIMIZATION:
        - Fetches all data in parallel using asyncio.gather
        - Single API call replaces 3 separate calls
        - Uses existing cache for each pipeline type
    """
    import asyncio
    from datetime import datetime

    from services.jenkins_client import get_dev_jenkins_client, get_jenkins_client

    include_set = set(i.strip().lower() for i in include.split(","))

    result = {"fetchedAt": datetime.utcnow().isoformat() + "Z", "dataSource": "jenkins-unified"}

    async def fetch_dev():
        """Fetch Dev pipelines."""
        try:
            dev_jenkins = get_dev_jenkins_client()
            if not dev_jenkins.is_configured():
                return {"error": "Dev Jenkins not configured", "pipelines": [], "summary": {}}
            if force_refresh:
                dev_jenkins.clear_cache()
            data = await dev_jenkins.get_dev_pipelines(num_builds=num_builds)
            data["type"] = "dev"
            return data
        except Exception as e:
            logger.warning("Failed to fetch Dev pipelines: %s", e)
            return {"error": str(e), "pipelines": [], "summary": {}}

    async def fetch_pdv():
        """Fetch PDV pipelines by stack."""
        try:
            jenkins = get_jenkins_client()
            if not jenkins.is_configured():
                return {"error": "Jenkins not configured", "byStack": {}, "summary": {}}
            if force_refresh:
                jenkins.clear_cache()
            data = await jenkins.get_backend_pdv_by_stack(num_builds=num_builds)
            data["type"] = "pdv"
            return data
        except Exception as e:
            logger.warning("Failed to fetch PDV pipelines: %s", e)
            return {"error": str(e), "byStack": {}, "summary": {}}

    async def fetch_regression():
        """Fetch Regression pipelines by stack."""
        try:
            jenkins = get_jenkins_client()
            if not jenkins.is_configured():
                return {"error": "Jenkins not configured", "byStack": {}, "summary": {}}
            if force_refresh:
                jenkins.clear_cache()
            data = await jenkins.get_regression_by_stack(num_builds=num_builds)
            data["type"] = "regression"
            return data
        except Exception as e:
            logger.warning("Failed to fetch Regression pipelines: %s", e)
            return {"error": str(e), "byStack": {}, "summary": {}}

    # Build list of tasks based on include parameter
    tasks = []
    task_keys = []

    if "dev" in include_set:
        tasks.append(fetch_dev())
        task_keys.append("dev")

    if "pdv" in include_set:
        tasks.append(fetch_pdv())
        task_keys.append("pdv")

    if "regression" in include_set:
        tasks.append(fetch_regression())
        task_keys.append("regression")

    # Execute all tasks in parallel
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for key, data in zip(task_keys, results):
            if isinstance(data, Exception):
                result[key] = {"error": str(data), "pipelines": [], "summary": {}}
            else:
                result[key] = data

    return result


# =============================================================================
# Shared Helper Functions (for use by other routers like Overview)
# =============================================================================


async def get_pdv_summary_for_overview(force_refresh: bool = False) -> dict:
    """
    Get PDV summary data for the Overview page.

    This function uses the SAME calculation logic as the PDV pages, ensuring
    consistent numbers between Overview and the individual PDV sections.

    Returns:
        {
            "available": True,
            "backend": {
                "total_builds": 62,
                "builds_passed": 55,
                "success_rate": 89,
                "total_stacks": 5,
                "failed_stacks": 1,
            },
            "endpoint": {
                "total_builds": 100,
                "builds_passed": 91,
                "success_rate": 91,
                "total_stacks": 14,
                "failed_stacks": 2,
            },
            "combined": {
                "total_builds": 162,
                "builds_passed": 146,
                "success_rate": 90,
            }
        }
    """
    from services.jenkins_client import get_jenkins_client

    result = {
        "available": False,
        "backend": None,
        "endpoint": None,
        "combined": {
            "total_builds": 0,
            "builds_passed": 0,
            "success_rate": 0,
        },
    }

    try:
        jenkins = get_jenkins_client()

        if not jenkins.is_configured():
            return result

        if force_refresh:
            jenkins.clear_cache()

        # Fetch data using SAME parameters as PDV pages (MonitoringSection.js)
        # Backend PDV: num_builds=15 (matches /api/jenkins/backend-pdv-by-stack?num_builds=15)
        # Endpoint PDV: num_builds=10 (matches /api/jenkins/golden-regression?num_builds=10)
        backend_task = jenkins.get_pdv_pipelines(include_builds=True, num_builds=15)
        endpoint_task = jenkins.get_golden_regression(num_builds=10)

        backend_data, endpoint_data = await asyncio.gather(backend_task, endpoint_task, return_exceptions=True)

        # Log if either fetch failed
        if isinstance(backend_data, Exception):
            logger.warning(f"Backend PDV fetch failed: {backend_data}")
        if isinstance(endpoint_data, Exception):
            logger.warning(f"Endpoint PDV fetch failed: {endpoint_data}")

        # Process Backend PDV using SAME logic as backend-pdv-by-stack endpoint
        backend_total_runs = 0
        backend_total_passed = 0
        backend_total_failed = 0
        backend_stacks = set()
        backend_failed_stacks = set()
        backend_recent_failures = []  # Track failures in last 24h

        # Calculate 24h ago timestamp
        import time as time_module

        now_ms = int(time_module.time() * 1000)
        day_ago_ms = now_ms - (24 * 60 * 60 * 1000)

        # Process all Backend PDV pipelines from http://10.136.208.148:8080/job/BACKEND/
        def get_pipeline_key_for_summary(name):
            """Extract short pipeline key from full name."""
            key = name.lower()
            key = key.replace("your-product-backend_", "")
            key = key.replace("_pdv_test", "")
            key = key.replace("_pdv", "")
            key = key.replace("_test", "")
            key = key.replace("new_", "")
            key = key.replace("-", "_")
            return key

        if backend_data and not isinstance(backend_data, Exception) and not backend_data.get("error"):
            for pipeline in backend_data.get("pipelines", []):
                pipeline_name = pipeline.get("name", "")

                # Only process jobs with _pdv_ in their name
                if "_pdv_" not in pipeline_name.lower():
                    continue

                stack_latest_status = {}  # Track latest status per stack for this pipeline

                for build in pipeline.get("recentBuilds", []):
                    stack = build.get("stack", "")
                    if not stack or stack.lower().strip() in ("", "no stack"):
                        continue
                    stack = stack.lower().strip()

                    status = build.get("status", "").lower()
                    build_timestamp = build.get("timestampMs", 0)
                    backend_total_runs += 1

                    if status == "success":
                        backend_total_passed += 1
                    elif status in ("failed", "unstable", "aborted"):
                        backend_total_failed += 1
                        # Track if this failure is within 24h
                        if build_timestamp >= day_ago_ms:
                            backend_recent_failures.append(
                                {
                                    "stack": stack,
                                    "pipeline": pipeline_name,
                                    "timestamp": build.get("timestamp", ""),
                                    "timestamp_ms": build_timestamp,
                                    "build_number": build.get("number"),
                                }
                            )

                    backend_stacks.add(stack)

                    # Track latest build status per stack (first seen = latest due to sort order)
                    if stack not in stack_latest_status:
                        stack_latest_status[stack] = status

                # Mark stacks as failed based on latest build
                for stack, status in stack_latest_status.items():
                    if status in ("failed", "unstable", "aborted"):
                        backend_failed_stacks.add(stack)

            backend_success_rate = round(
                (backend_total_passed / backend_total_runs * 100) if backend_total_runs > 0 else 0
            )

            result["backend"] = {
                "total_builds": backend_total_runs,
                "builds_passed": backend_total_passed,
                "builds_failed": backend_total_failed,
                "success_rate": backend_success_rate,
                "total_stacks": len(backend_stacks),
                "failed_stacks": len(backend_failed_stacks),
                "status": "healthy" if len(backend_failed_stacks) == 0 else "failing",
                "recent_failures": backend_recent_failures[:5],  # Limit to 5 most recent
                "recent_failure_count": len(backend_recent_failures),
            }
            logger.info(
                f"Overview Backend PDV: {backend_success_rate}% ({backend_total_passed}/{backend_total_runs} builds, {len(backend_recent_failures)} failures in 24h)"
            )

        # Process Endpoint PDV using SAME logic as golden-regression endpoint
        endpoint_total_runs = 0
        endpoint_total_passed = 0
        endpoint_total_failed = 0
        endpoint_failed_stacks = 0
        endpoint_total_stacks = 0
        endpoint_recent_failures = []  # Track failures in last 24h

        if endpoint_data and not isinstance(endpoint_data, Exception) and not endpoint_data.get("error"):
            stack_groups = endpoint_data.get("stackGroups", {})
            endpoint_total_stacks = len(stack_groups)

            for stack_name, builds in stack_groups.items():
                for build in builds:
                    status = build.get("status", "").lower()
                    build_timestamp = build.get("timestampMs", 0)
                    endpoint_total_runs += 1

                    if status == "success":
                        endpoint_total_passed += 1
                    elif status in ("failed", "unstable", "aborted"):
                        endpoint_total_failed += 1
                        # Track if this failure is within 24h
                        if build_timestamp >= day_ago_ms:
                            endpoint_recent_failures.append(
                                {
                                    "stack": stack_name,
                                    "timestamp": build.get("timestamp", ""),
                                    "timestamp_ms": build_timestamp,
                                    "build_number": build.get("number"),
                                }
                            )

                # Check if latest build for this stack failed (case-insensitive)
                if builds and builds[0].get("status", "").lower() in ("failed", "unstable", "aborted"):
                    endpoint_failed_stacks += 1

            endpoint_success_rate = round(
                (endpoint_total_passed / endpoint_total_runs * 100) if endpoint_total_runs > 0 else 0
            )

            result["endpoint"] = {
                "total_builds": endpoint_total_runs,
                "builds_passed": endpoint_total_passed,
                "builds_failed": endpoint_total_failed,
                "success_rate": endpoint_success_rate,
                "total_stacks": endpoint_total_stacks,
                "failed_stacks": endpoint_failed_stacks,
                "status": "healthy" if endpoint_failed_stacks == 0 else "failing",
                "recent_failures": endpoint_recent_failures[:5],  # Limit to 5 most recent
                "recent_failure_count": len(endpoint_recent_failures),
            }
            logger.info(
                f"Overview Endpoint PDV: {endpoint_success_rate}% ({endpoint_total_passed}/{endpoint_total_runs} builds, {len(endpoint_recent_failures)} failures in 24h)"
            )

        # Calculate combined summary
        if result["backend"] or result["endpoint"]:
            result["available"] = True

            total_builds = (result["backend"]["total_builds"] if result["backend"] else 0) + (
                result["endpoint"]["total_builds"] if result["endpoint"] else 0
            )
            builds_passed = (result["backend"]["builds_passed"] if result["backend"] else 0) + (
                result["endpoint"]["builds_passed"] if result["endpoint"] else 0
            )
            combined_rate = round((builds_passed / total_builds * 100) if total_builds > 0 else 0)

            # Combine recent failures from both backend and endpoint
            recent_failure_count = (result["backend"].get("recent_failure_count", 0) if result["backend"] else 0) + (
                result["endpoint"].get("recent_failure_count", 0) if result["endpoint"] else 0
            )

            result["combined"] = {
                "total_builds": total_builds,
                "builds_passed": builds_passed,
                "success_rate": combined_rate,
                "recent_failure_count": recent_failure_count,
            }
            logger.info(
                f"Overview PDV Combined: {combined_rate}% ({builds_passed}/{total_builds} builds, {recent_failure_count} failures in 24h)"
            )

    except Exception as e:
        logger.warning(f"Error in get_pdv_summary_for_overview: {e}")

    return result


# ============================================================
# FLAKY TESTS ANALYSIS
# ============================================================


class FlakyTestAnalyzer:
    """
    Analyzes test results from Jenkins to identify flaky tests.

    A test is considered flaky if it has inconsistent results
    (sometimes passes, sometimes fails) over a period of time.
    """

    def __init__(self):
        self._jenkins_client = None
        self._init_error = None

        try:
            from services.jenkins_client import get_jenkins_client

            self._jenkins_client = get_jenkins_client()
            logger.info("FlakyTestAnalyzer initialized with JenkinsClient")
        except Exception as e:
            self._init_error = str(e)
            logger.error(f"Failed to initialize JenkinsClient for flaky analysis: {e}")

    def is_configured(self) -> bool:
        """Check if Jenkins is properly configured."""
        if self._jenkins_client is None:
            return False
        return self._jenkins_client.is_configured()

    def _error_response(self, error_message: str) -> Dict:
        """Return a standardized error response."""
        return {
            "error": error_message,
            "flaky_tests": [],
            "summary": {
                "total_tests": 0,
                "flaky_count": 0,
                "critical_count": 0,
                "warning_count": 0,
                "flakiness_rate": 0,
                "quarantined_count": 0,
            },
            "metadata": {
                "generated_at": datetime.now().isoformat(),
            },
        }

    async def _get_test_report(self, job_name: str, build_number: int) -> Optional[Dict]:
        """Fetch lightweight test report from a Jenkins build (uses tree query for speed)."""
        if self._jenkins_client is None:
            return None
        try:
            # Use lightweight method - much faster than full test report
            return await self._jenkins_client.get_lightweight_test_report(job_name, build_number)
        except Exception as e:
            logger.error(f"Error fetching test report for {job_name}#{build_number}: {e}")
            return None

    async def _get_recent_builds(self, job_name: str, limit: int = 20) -> List[Dict]:
        """Get recent builds for a job."""
        if self._jenkins_client is None:
            return []
        try:
            builds_data = await self._jenkins_client.get_pipeline_builds(
                job_name, num_builds=limit, check_test_reports=False
            )
            if builds_data and "builds" in builds_data:
                builds = []
                for build in builds_data["builds"]:
                    builds.append(
                        {
                            "number": build.get("buildNumber"),
                            "timestamp": build.get("timestampMs", 0),
                            "result": build.get("status", "").upper(),
                        }
                    )
                return builds
        except Exception as e:
            logger.error(f"Error fetching builds for {job_name}: {e}")
        return []

    def _get_jobs_with_tests(self) -> List[str]:
        """Get list of Jenkins jobs configured for monitoring."""
        monitored_jobs = getattr(self._jenkins_client, "monitored_jobs", [])
        if monitored_jobs:
            logger.info(f"Using {len(monitored_jobs)} monitored jobs from JENKINS_JOBS config")
            return monitored_jobs
        logger.warning("No JENKINS_JOBS configured")
        return []

    def _parse_test_results(self, test_report: Dict, build_info: Dict) -> List[Dict]:
        """Parse test report into individual test results."""
        results = []
        build_number = build_info.get("number")
        timestamp = build_info.get("timestamp", 0)

        def parse_case(case: Dict, suite_name: str) -> Dict:
            test_name = case.get("name", "Unknown")
            class_name = case.get("className", "")
            status = case.get("status", "PASSED")
            duration = case.get("duration", 0)
            error_details = case.get("errorDetails", "")

            if status in ["PASSED", "FIXED"]:
                normalized_status = "pass"
            elif status in ["FAILED", "REGRESSION"]:
                normalized_status = "fail"
            else:
                normalized_status = "skip"

            return {
                "test_name": test_name,
                "class_name": class_name,
                "suite": suite_name,
                "full_name": f"{class_name}::{test_name}" if class_name else test_name,
                "status": normalized_status,
                "duration": duration,
                "error_message": error_details[:500] if error_details else None,
                "build_number": build_number,
                "timestamp": datetime.fromtimestamp(timestamp / 1000).isoformat() if timestamp else None,
            }

        def parse_suites(suites: List[Dict]):
            for suite in suites:
                suite_name = suite.get("name", "Unknown")
                for case in suite.get("cases", []):
                    results.append(parse_case(case, suite_name))

        if "suites" in test_report and test_report["suites"]:
            parse_suites(test_report["suites"])
        elif "childReports" in test_report:
            for child_report in test_report.get("childReports", []):
                child = child_report.get("child", {})
                if "suites" in child:
                    parse_suites(child["suites"])
                if "result" in child_report and "suites" in child_report["result"]:
                    parse_suites(child_report["result"]["suites"])
        elif "cases" in test_report:
            for case in test_report["cases"]:
                results.append(parse_case(case, "Default"))

        return results

    def _calculate_flakiness(self, test_results: List[Dict]) -> Optional[Dict]:
        """Calculate flakiness metrics for a test."""
        if not test_results:
            return None

        passes = sum(1 for r in test_results if r["status"] == "pass")
        failures = sum(1 for r in test_results if r["status"] == "fail")
        skips = sum(1 for r in test_results if r["status"] == "skip")
        total = passes + failures

        if total == 0:
            return None

        if passes == 0 or failures == 0:
            flakiness = 0
        else:
            flakiness = round((min(passes, failures) / total) * 100, 1)

        if flakiness >= 30:
            severity = "critical"
        elif flakiness >= 10:
            severity = "warning"
        else:
            severity = "low"

        mid = len(test_results) // 2
        first_failures = sum(1 for r in test_results[:mid] if r["status"] == "fail")
        second_failures = sum(1 for r in test_results[mid:] if r["status"] == "fail")

        if second_failures > first_failures:
            trend = "increasing"
        elif second_failures < first_failures:
            trend = "decreasing"
        else:
            trend = "stable"

        run_history = [r["status"] for r in test_results[-10:]]

        last_failure = None
        failure_reasons = []
        for r in reversed(test_results):
            if r["status"] == "fail":
                last_failure = r["timestamp"]
                if r.get("error_message"):
                    error = r["error_message"].lower()
                    if "timeout" in error:
                        failure_reasons.append("timeout")
                    elif "assert" in error:
                        failure_reasons.append("assertion")
                    elif "connection" in error:
                        failure_reasons.append("connection")
                    else:
                        failure_reasons.append("other")
                break

        sample = test_results[0]
        return {
            "test_name": sample["test_name"],
            "class_name": sample["class_name"],
            "suite": sample["suite"],
            "full_name": sample["full_name"],
            "flakiness_percent": flakiness,
            "severity": severity,
            "total_runs": total,
            "passes": passes,
            "failures": failures,
            "skips": skips,
            "run_history": run_history,
            "trend": trend,
            "last_failure": last_failure,
            "failure_reasons": list(set(failure_reasons)),
            "avg_duration": round(sum(r["duration"] for r in test_results) / len(test_results), 2),
            "executions": test_results[-10:],
        }

    def _analyze_failure_patterns(self, flaky_tests: List[Dict], all_results: Dict) -> Dict:
        """Analyze and categorize failure patterns across all flaky tests."""
        pattern_counts = defaultdict(int)
        pattern_tests = defaultdict(list)
        error_samples = defaultdict(list)

        # Define pattern keywords
        patterns = {
            "timeout": ["timeout", "timed out", "deadline exceeded", "took too long"],
            "connection": ["connection", "connect", "network", "socket", "refused", "unreachable", "dns"],
            "assertion": ["assert", "expected", "actual", "not equal", "should be", "mismatch"],
            "null_reference": ["null", "none", "undefined", "nil", "nullpointer", "attributeerror"],
            "permission": ["permission", "denied", "unauthorized", "forbidden", "access", "auth"],
            "resource": ["resource", "memory", "disk", "quota", "limit", "oom", "out of memory"],
            "data": ["data", "invalid", "corrupt", "parse", "json", "xml", "format"],
            "concurrency": ["race", "deadlock", "concurrent", "thread", "lock", "synchron"],
            "flaky_timing": ["timing", "delay", "slow", "wait", "sleep", "async"],
            "environment": ["env", "config", "setup", "fixture", "cleanup", "teardown"],
        }

        # Analyze each flaky test's executions
        for test in flaky_tests:
            test_name = test.get("full_name", test.get("test_name", "unknown"))
            executions = test.get("executions", [])

            for exec_data in executions:
                if exec_data.get("status") == "fail" and exec_data.get("error_message"):
                    error_msg = exec_data["error_message"].lower()
                    matched = False

                    for pattern_name, keywords in patterns.items():
                        if any(kw in error_msg for kw in keywords):
                            pattern_counts[pattern_name] += 1
                            if test_name not in pattern_tests[pattern_name]:
                                pattern_tests[pattern_name].append(test_name)
                            # Store sample error (limit to 200 chars)
                            sample = exec_data["error_message"][:200]
                            if sample not in error_samples[pattern_name]:
                                error_samples[pattern_name].append(sample)
                            matched = True
                            break

                    if not matched:
                        pattern_counts["other"] += 1
                        if test_name not in pattern_tests["other"]:
                            pattern_tests["other"].append(test_name)

        # Build result sorted by count
        result = []
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
            result.append(
                {
                    "pattern": pattern,
                    "label": pattern.replace("_", " ").title(),
                    "count": count,
                    "affected_tests": len(pattern_tests[pattern]),
                    "test_names": pattern_tests[pattern][:5],  # Top 5 tests
                    "sample_errors": error_samples.get(pattern, [])[:3],  # Top 3 samples
                }
            )

        return {
            "patterns": result,
            "total_failures_analyzed": sum(pattern_counts.values()),
        }

    async def get_flaky_tests(self, days: int = 10, min_runs: int = 3, job_filter: Optional[str] = None) -> Dict:
        """Analyze tests and identify flaky ones."""
        start_time = datetime.now()

        if self._init_error:
            return self._error_response(f"Jenkins client initialization failed: {self._init_error}")

        if not self.is_configured():
            return self._error_response(
                "Jenkins not configured. Set JENKINS_URL, JENKINS_USER, JENKINS_TOKEN, and JENKINS_JOBS environment variables."
            )

        jobs = self._get_jobs_with_tests()
        if job_filter:
            jobs = [j for j in jobs if job_filter.lower() in j.lower()]

        if not jobs:
            return self._error_response("No Jenkins jobs configured. Set JENKINS_JOBS environment variable.")

        all_results = defaultdict(list)
        cutoff_date = datetime.now() - timedelta(days=days)
        builds_analyzed = 0
        reports_found = 0
        reports_failed = 0

        # Limit builds per job for analysis
        max_builds_per_job = 10

        logger.info(
            f"Analyzing {len(jobs)} jobs for flaky tests (last {days} days, max {max_builds_per_job} builds/job)"
        )

        # Collect all build fetch tasks
        async def fetch_job_builds(job_name: str) -> List[Dict]:
            builds = await self._get_recent_builds(job_name, limit=max_builds_per_job)
            return [
                (job_name, b) for b in builds if datetime.fromtimestamp(b.get("timestamp", 0) / 1000) >= cutoff_date
            ]

        # Fetch build lists for all jobs in parallel
        job_builds_results = await asyncio.gather(*[fetch_job_builds(j) for j in jobs], return_exceptions=True)

        # Flatten to list of (job_name, build) tuples
        all_builds_to_fetch = []
        for result in job_builds_results:
            if isinstance(result, list):
                all_builds_to_fetch.extend(result)

        builds_analyzed = len(all_builds_to_fetch)
        logger.info(f"Fetching {builds_analyzed} test reports across {len(jobs)} jobs...")

        # Fetch test reports in parallel (semaphore in jenkins_client limits concurrency)
        async def fetch_test_report(job_name: str, build: Dict) -> Optional[tuple]:
            report = await self._get_test_report(job_name, build["number"])
            if report:
                return (report, build)
            return None

        report_tasks = [fetch_test_report(job, build) for job, build in all_builds_to_fetch]
        report_results = await asyncio.gather(*report_tasks, return_exceptions=True)

        # Process results
        for result in report_results:
            if result is None or isinstance(result, Exception):
                reports_failed += 1
                continue

            test_report, build = result
            reports_found += 1
            parsed_results = self._parse_test_results(test_report, build)
            for r in parsed_results:
                all_results[r["full_name"]].append(r)

        logger.info(
            f"Analysis: {builds_analyzed} builds, {reports_found} reports found, {reports_failed} failed, {len(all_results)} unique tests"
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        if not all_results:
            message = "No test reports found in recent builds."
            if reports_failed > 0:
                message = f"Failed to fetch {reports_failed} test reports from Jenkins (server disconnected). Try again later."
            return {
                "flaky_tests": [],
                "summary": {
                    "total_tests": 0,
                    "flaky_count": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "flakiness_rate": 0,
                    "quarantined_count": 0,
                },
                "filters": {"days": days, "min_runs": min_runs, "job_filter": job_filter, "jobs_analyzed": jobs},
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "analysis_time_seconds": round(elapsed, 2),
                    "builds_analyzed": builds_analyzed,
                    "reports_found": reports_found,
                    "reports_failed": reports_failed,
                    "message": message,
                },
            }

        flaky_tests = []
        total_tests = 0

        for test_key, results in all_results.items():
            if len(results) < min_runs:
                continue
            total_tests += 1
            results.sort(key=lambda x: x["timestamp"] or "")
            analysis = self._calculate_flakiness(results)
            if analysis and analysis["flakiness_percent"] > 0:
                flaky_tests.append(analysis)

        flaky_tests.sort(key=lambda x: x["flakiness_percent"], reverse=True)
        critical_count = sum(1 for t in flaky_tests if t["severity"] == "critical")
        warning_count = sum(1 for t in flaky_tests if t["severity"] == "warning")

        # Aggregate failure patterns from all flaky tests
        failure_patterns = self._analyze_failure_patterns(flaky_tests, all_results)

        logger.info(
            f"Found {len(flaky_tests)} flaky tests out of {total_tests} (critical: {critical_count}, warning: {warning_count})"
        )

        return {
            "flaky_tests": flaky_tests,
            "summary": {
                "total_tests": total_tests,
                "flaky_count": len(flaky_tests),
                "critical_count": critical_count,
                "warning_count": warning_count,
                "flakiness_rate": round((len(flaky_tests) / total_tests * 100), 2) if total_tests > 0 else 0,
                "quarantined_count": 0,
            },
            "failure_patterns": failure_patterns,
            "filters": {"days": days, "min_runs": min_runs, "job_filter": job_filter, "jobs_analyzed": jobs},
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "analysis_time_seconds": round(elapsed, 2),
                "builds_analyzed": builds_analyzed,
                "reports_found": reports_found,
                "reports_failed": reports_failed,
                "unique_tests": len(all_results),
            },
        }


# Flaky test analyzer singleton
_flaky_analyzer = None


def get_flaky_analyzer() -> FlakyTestAnalyzer:
    """Get or create the flaky test analyzer singleton."""
    global _flaky_analyzer
    if _flaky_analyzer is None:
        _flaky_analyzer = FlakyTestAnalyzer()
    return _flaky_analyzer


@router.get("/flaky-tests")
async def get_flaky_tests(
    days: int = Query(10, description="Number of days to analyze"),
    min_runs: int = Query(3, description="Minimum runs required to evaluate flakiness"),
    job: Optional[str] = Query(None, description="Filter by job name"),
):
    """
    Get flaky tests analysis.

    Analyzes test results from Jenkins to identify tests with inconsistent results.
    A test is flaky if it sometimes passes and sometimes fails.

    Returns:
        - flaky_tests: List of tests with flakiness metrics
        - summary: Overall statistics
        - filters: Applied filters
        - metadata: Analysis metadata
    """
    try:
        analyzer = get_flaky_analyzer()
        return await analyzer.get_flaky_tests(days=days, min_runs=min_runs, job_filter=job)
    except Exception as e:
        logger.error(f"Error analyzing flaky tests: {e}", exc_info=True)
        return {
            "error": str(e),
            "flaky_tests": [],
            "summary": {
                "total_tests": 0,
                "flaky_count": 0,
                "critical_count": 0,
                "warning_count": 0,
                "flakiness_rate": 0,
                "quarantined_count": 0,
            },
            "metadata": {"generated_at": datetime.now().isoformat()},
        }


@router.get("/flaky-tests/summary")
async def get_flaky_tests_summary():
    """Get quick flaky tests summary for dashboard tiles."""
    try:
        analyzer = get_flaky_analyzer()
        data = await analyzer.get_flaky_tests(days=7, min_runs=3)
        return {
            "total_tests": data["summary"]["total_tests"],
            "flaky_count": data["summary"]["flaky_count"],
            "flakiness_rate": data["summary"]["flakiness_rate"],
            "critical_count": data["summary"]["critical_count"],
            "status": (
                "healthy"
                if data["summary"]["critical_count"] == 0
                else "warning" if data["summary"]["critical_count"] < 5 else "critical"
            ),
        }
    except Exception as e:
        logger.error(f"Error getting flaky tests summary: {e}")
        return {
            "total_tests": 0,
            "flaky_count": 0,
            "flakiness_rate": 0,
            "critical_count": 0,
            "status": "unknown",
            "error": str(e),
        }

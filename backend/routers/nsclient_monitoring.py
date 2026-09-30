"""
Monitoring API Router
Handles stack monitoring endpoints for Kubernetes deployments.

Note: PDV monitoring is handled via Jenkins endpoints (/api/jenkins/pdv-pipelines, /api/jenkins/golden-regression)

ENDPOINTS:
- GET /api/monitoring/stack - Main stack monitoring data
- GET /api/monitoring/stack/details - Deployment detail view (for side panel)
- GET /api/monitoring/stack/logs - Pod logs preview
- GET /api/monitoring/stack/history - Historical snapshots for trends
- POST /api/monitoring/stack/alert - Send Slack alerts for critical issues
- GET /api/monitoring/release-compliance - Check version compliance based on release milestones
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

# Use PST timezone for milestone date comparisons
# This ensures consistent behavior regardless of server location
PST_TIMEZONE = ZoneInfo("America/Los_Angeles")
from pydantic import BaseModel
from services.slack_notifications import send_stack_alert_notification
from services.stack_monitoring import get_monitoring_service

logger = logging.getLogger(__name__)

# =============================================================================
# Response Cache for Fast Page Loads
# =============================================================================


class MonitoringCache:
    """Simple in-memory cache for stack monitoring responses."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = 300  # 5 minutes for stack data

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if still valid."""
        if key in self._cache:
            entry = self._cache[key]
            age = time.time() - entry["timestamp"]
            if age < entry["ttl"]:
                logger.debug(f"Cache hit for {key} (age: {age:.1f}s)")
                return {"data": entry["data"], "age": age}
        return None

    def set(self, key: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache response with TTL."""
        self._cache[key] = {"data": data, "timestamp": time.time(), "ttl": ttl or self._default_ttl}

    def clear(self, key: Optional[str] = None) -> None:
        """Clear cache entry or all entries."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


# Global monitoring cache
_monitoring_cache = MonitoringCache()

router = APIRouter(
    prefix="/api/monitoring",
    tags=["monitoring"],
)


def _merge_restart_data_from_snapshot(live_data: Dict, snapshot_data: Dict) -> Dict:
    """
    Merge restart counts from snapshot into live data.
    Used when live K8s fetch fails to get restart counts.
    Only fills in missing data - doesn't overwrite live data.
    """
    # Create deployment lookup from snapshot
    snapshot_deps = {}
    for dep in snapshot_data.get("deployments", []):
        key = (dep.get("namespace"), dep.get("deployment"))
        snapshot_deps[key] = dep

    # Track restarts by stack for summary update
    restarts_by_stack = {}

    # Merge restarts into live data - only fill in missing values
    total_restarts = 0
    for dep in live_data.get("deployments", []):
        key = (dep.get("namespace"), dep.get("deployment"))
        snapshot_dep = snapshot_deps.get(key, {})
        for stack, data in dep.get("stacks", {}).items():
            # Only use snapshot data if live data is missing (None)
            if data.get("restarts") is None:
                snapshot_stack_data = snapshot_dep.get("stacks", {}).get(stack, {})
                data["restarts"] = snapshot_stack_data.get("restarts", 0)
                data["crash_loop"] = snapshot_stack_data.get("crash_loop", False)
                data["from_snapshot"] = True  # Mark as snapshot data

            restarts = data.get("restarts") or 0
            total_restarts += restarts
            restarts_by_stack[stack] = restarts_by_stack.get(stack, 0) + restarts

    # Update summary with restart counts per stack
    summary = live_data.get("summary", {})
    for stack, restarts in restarts_by_stack.items():
        if stack in summary:
            summary[stack]["restarts"] = restarts

    live_data["total_restarts"] = total_restarts
    live_data["snapshot_fallback"] = True
    live_data["snapshot_timestamp"] = snapshot_data.get("timestamp")
    return live_data


# ============ Stack Monitoring Endpoints ============


@router.get("/stack")
async def get_stack_monitoring(
    stacks: Optional[str] = None, refresh: bool = False, lite: bool = False, stale_ok: bool = True
):
    """
    Get Kubernetes stack monitoring data across environments.

    PURPOSE:
        Monitors deployment versions and health status across Kubernetes
        stacks (qa01, stg01, etc.). Identifies version mismatches between
        environments and tracks deployment health.

    WHEN TO USE:
        - Viewing Stack Monitoring section on Monitoring page
        - Checking deployment versions across environments
        - Identifying version drift between stacks
        - Verifying deployment health after rollouts

    PARAMETERS:
        - stacks (str): Comma-separated stacks to monitor (e.g., "qa01,stg01")
                       Default: all configured stacks
        - refresh (bool): Force refresh cached data (default: False)
        - lite (bool): Lite mode - skip events/restarts for faster initial load (default: False)
        - stale_ok (bool): Accept stale cached data for faster response (default: True)

    RETURNS:
        {
            "stacks": {
                "qa01": {
                    "status": "healthy",
                    "deployments": [
                        {
                            "name": "frontend",
                            "version": "1.2.3",
                            "status": "Running",
                            "replicas": "3/3"
                        }
                    ]
                },
                "stg01": {...}
            },
            "summary": {
                "total_deployments": 50,
                "healthy": 48,
                "warning": 2,
                "critical": 0
            },
            "mismatches": [
                {
                    "deployment": "backend-api",
                    "qa01": "1.2.3",
                    "stg01": "1.2.2"
                }
            ],
            "cached": true,
            "cache_age_seconds": 120,
            "source": "kubernetes-live"
        }

    KUBERNETES REQUIREMENTS:
        - Valid kubeconfig with contexts for monitored clusters
        - RBAC permissions to read deployments
        - VPN connection if clusters are internal

    RELATED ENDPOINTS:
        - GET /api/jenkins/pdv-pipelines - Backend PDV tests
        - GET /api/jenkins/golden-regression - E2E tests
    """
    try:
        import main as _main_module

        still_initializing = not _main_module.rancher_setup_complete

        print(f"DEBUG: Request params: refresh={refresh}, lite={lite}, stale_ok={stale_ok}")

        # Build cache key based on parameters
        cache_key = f"stack_monitoring:{stacks or 'all'}:{lite}"

        # Check response cache first for instant response (unless refresh requested)
        if not refresh and stale_ok:
            cached = _monitoring_cache.get(cache_key)
            if cached:
                logger.info("Returning cached stack monitoring data (age: %.1fs)", cached["age"])
                return {
                    **cached["data"],
                    "source": "kubernetes-live",
                    "lite_mode": lite,
                    "cached": True,
                    "cache_age_seconds": int(cached["age"]),
                    "initializing": still_initializing,
                }

        start_time = time.time()
        monitoring_service = get_monitoring_service()

        # Parse stacks parameter
        stack_list = None
        if stacks:
            stack_list = [s.strip() for s in stacks.split(",")]

        # Get formatted data (uses cache unless refresh=True)
        logger.info(
            "Fetching stack monitoring data for: %s (refresh=%s, lite=%s, stale_ok=%s)",
            stack_list or "all stacks",
            refresh,
            lite,
            stale_ok,
        )

        # Determine if we need to regenerate data:
        # 1. refresh=True -> always fetch fresh
        # 2. no master_config yet -> first time fetch
        # 3. lite=False AND previous fetch was lite (no restart data) -> need full fetch for restarts
        # Check if we need full data but only have lite data (no restart counts merged)
        needs_full_fetch = not lite and monitoring_service.master_config and not monitoring_service._namespace_events

        # Two-phase fetch: deployments (30s) + namespace details (70s) = 100s
        # Allow 110s total before falling back to snapshot
        fetch_timeout = 110 if not lite and stale_ok else 180
        k8s_fetch_failed = False

        print(
            f"DEBUG: refresh={refresh}, master_config={bool(monitoring_service.master_config)}, needs_full_fetch={needs_full_fetch}"
        )
        if refresh or not monitoring_service.master_config or needs_full_fetch:
            print("DEBUG: Calling generate_stack_config...")
            # Run generate_stack_config in a thread with timeout to prevent hanging
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        monitoring_service.generate_stack_config,
                        stack_list,  # stacks
                        not refresh,  # use_cache
                        lite,  # lite_mode
                        stale_ok,  # background_refresh
                    ),
                    timeout=fetch_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Stack monitoring fetch timed out after %ds - checking for snapshot fallback", fetch_timeout
                )
                k8s_fetch_failed = True

        data = monitoring_service.get_formatted_data(refresh=refresh)

        # Debug logging
        deployments_count = len(data.get("deployments", []))
        print(f"DEBUG: Got {deployments_count} deployments from get_formatted_data")

        # Check how much restart data we have
        # Count deployments with/without restart data
        total_stacks = 0
        stacks_with_restarts = 0
        live_total_restarts = 0

        for dep in data.get("deployments", []):
            for stack, stack_data in dep.get("stacks", {}).items():
                if stack_data.get("status") not in ["not_found", None]:
                    total_stacks += 1
                    if stack_data.get("restarts") is not None:
                        stacks_with_restarts += 1
                        live_total_restarts += stack_data.get("restarts", 0)

        # Calculate coverage percentage
        restart_coverage = (stacks_with_restarts / total_stacks * 100) if total_stacks > 0 else 0

        # Only use snapshot fallback if we have very low coverage (<50%) or zero restarts
        # Otherwise, use the partial live data (it's more current)
        should_use_fallback = ((k8s_fetch_failed and restart_coverage < 50) or live_total_restarts == 0) and not lite

        print(
            f"DEBUG: Restart coverage: {stacks_with_restarts}/{total_stacks} stacks ({restart_coverage:.1f}%), live_restarts={live_total_restarts}, k8s_failed={k8s_fetch_failed}, fallback={should_use_fallback}"
        )

        if should_use_fallback:
            latest_snapshot = monitoring_service.get_latest_snapshot_data()
            if latest_snapshot:
                # Calculate total_restarts from snapshot deployments
                snapshot_total = 0
                for dep in latest_snapshot.get("deployments", []):
                    for stack, stack_data in dep.get("stacks", {}).items():
                        snapshot_total += stack_data.get("restarts", 0)

                if snapshot_total > 0:
                    logger.info(
                        "Using snapshot fallback - live data has missing/zero restarts, snapshot has %d", snapshot_total
                    )
                    # Merge restart data from snapshot into live response
                    data = _merge_restart_data_from_snapshot(data, latest_snapshot)
                    data["source"] = "kubernetes-snapshot-fallback"

        # Cache the response (5 minutes for full data, 2 minutes for lite)
        cache_ttl = 120 if lite else 300
        _monitoring_cache.set(cache_key, data, ttl=cache_ttl)

        elapsed = time.time() - start_time
        logger.info("Stack monitoring data fetched in %.2fs", elapsed)

        return {
            **data,
            "source": data.get("source", "kubernetes-live"),
            "lite_mode": lite,
            "fetch_time_seconds": round(elapsed, 2),
            "initializing": still_initializing,
        }

    except Exception as e:
        error_str = str(e)
        logger.error("Error fetching stack monitoring: %s", e, exc_info=True)

        # Provide helpful error messages based on the type of error
        if "401" in error_str or "Unauthorized" in error_str:
            message = "Kubernetes authentication failed. Please run 'kubectl auth refresh' or re-login with SSO."
        elif "403" in error_str or "Forbidden" in error_str:
            message = "Kubernetes access denied. Check RBAC permissions for the cluster contexts."
        elif "No configuration" in error_str or "Invalid kube-config" in error_str:
            message = "Kubeconfig not found or invalid. Ensure ~/.kube/config exists with valid contexts."
        elif "connection refused" in error_str.lower() or "timeout" in error_str.lower():
            message = "Cannot connect to Kubernetes cluster. Check VPN connection and cluster availability."
        else:
            message = "Failed to fetch Kubernetes data. Ensure k8s config is properly set up."

        return {
            "status": "error",
            "error": error_str,
            "message": message,
            "source": "error",
            "help": {
                "required_contexts": ["stork-stg01-mp-iad0-nc4", "stork-qa01-mp-npe-iad0-nc1"],
                "fix_auth": "kubectl auth refresh or kubectl oidc-login",
                "check_config": "kubectl config get-contexts",
            },
        }


@router.get("/stack/details")
async def get_deployment_details(
    namespace: str = Query(..., description="Kubernetes namespace"),
    deployment: str = Query(..., description="Deployment name"),
    stack: str = Query(..., description="Stack identifier (e.g., qa01, stg01)"),
    lite: bool = Query(False, description="If true, skip expensive calls (metrics, events) for faster response"),
):
    """
    Get detailed information for a specific deployment.
    Used by the side panel detail view.

    OPTIMIZED: Uses parallel API calls. Use lite=true for ~50% faster loading.

    PURPOSE:
        Provides comprehensive deployment details including resource metrics,
        probe status, pod information, and recent events.

    PARAMETERS:
        - namespace (str): Kubernetes namespace
        - deployment (str): Deployment name
        - stack (str): Stack identifier (qa01, stg01, etc.)
        - lite (bool): Skip metrics/events for faster response (default: false)

    RETURNS:
        {
            "namespace": "otp",
            "deployment": "otp",
            "stack": "qa01",
            "found": true,
            "replicas": {"desired": 2, "ready": 2, ...},
            "containers": [{"name": "otp", "image": "...", "version": "v1.0.0"}],
            "probes": {
                "readiness": {"configured": true, "type": "httpGet", "status": "passing"},
                "liveness": {"configured": true, "type": "httpGet", "status": "passing"}
            },
            "pods": [
                {"name": "otp-xxx", "status": "Running", "restarts": 0, ...}
            ],
            "resource_metrics": {
                "otp-xxx": {"cpu": {"usage": "50m"}, "memory": {"usage": "128Mi"}}
            },
            "events": [...],
            "load_time_ms": 5432
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        details = monitoring_service.get_deployment_details(namespace, deployment, stack, lite=lite)
        return details

    except Exception as e:
        logger.error("Error fetching deployment details: %s", e, exc_info=True)
        return {"error": str(e), "namespace": namespace, "deployment": deployment, "stack": stack, "found": False}


@router.get("/stack/logs")
async def get_pod_logs(
    namespace: str = Query(..., description="Kubernetes namespace"),
    pod: str = Query(..., description="Pod name"),
    stack: str = Query(..., description="Stack identifier"),
    container: Optional[str] = Query(None, description="Container name (optional)"),
    lines: int = Query(50, description="Number of log lines to fetch", ge=10, le=500),
):
    """
    Get the last N lines of logs from a pod.
    Used for quick debugging in the side panel.

    PURPOSE:
        Fetches recent log output from a pod for quick debugging
        without needing to use kubectl directly.

    PARAMETERS:
        - namespace (str): Kubernetes namespace
        - pod (str): Pod name
        - stack (str): Stack identifier
        - container (str, optional): Container name if pod has multiple containers
        - lines (int): Number of lines to fetch (10-500, default 50)

    RETURNS:
        {
            "pod": "otp-xxx",
            "container": "otp",
            "namespace": "otp",
            "stack": "qa01",
            "lines": 50,
            "logs": "2024-02-10T10:00:00 INFO Starting...\n...",
            "truncated": false
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        logs = monitoring_service.get_pod_logs(
            namespace=namespace, pod_name=pod, stack=stack, container=container, lines=lines
        )
        return logs

    except Exception as e:
        logger.error("Error fetching pod logs: %s", e, exc_info=True)
        return {"error": str(e), "pod": pod, "namespace": namespace, "stack": stack}


@router.get("/stack/deployment-logs")
async def get_deployment_logs(
    namespace: str = Query(..., description="Kubernetes namespace"),
    deployment: str = Query(..., description="Deployment name"),
    stack: str = Query(..., description="Stack identifier"),
    lines: int = Query(50, description="Number of log lines to fetch per pod", ge=10, le=200),
):
    """
    Get logs from a deployment by automatically finding its pods.
    Useful for viewing error logs directly from issue panels.

    PURPOSE:
        Fetches logs from all pods of a deployment without needing
        to know specific pod names. Ideal for quick error diagnosis.

    PARAMETERS:
        - namespace (str): Kubernetes namespace
        - deployment (str): Deployment name
        - stack (str): Stack identifier
        - lines (int): Number of lines to fetch per pod (10-200, default 50)

    RETURNS:
        {
            "deployment": "my-service",
            "namespace": "my-ns",
            "stack": "stg01",
            "pods": [
                {"name": "pod-1", "status": "Running", "logs": "..."},
                {"name": "pod-2", "status": "CrashLoopBackOff", "logs": "..."}
            ],
            "total_pods": 2
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        logs = monitoring_service.get_deployment_logs(
            namespace=namespace, deployment_name=deployment, stack=stack, lines=lines
        )

        # Always return 200 with error details in body if there's an error
        if logs.get("error"):
            logger.warning("Deployment logs error: %s", logs["error"])

        return logs

    except Exception as e:
        logger.error("Error fetching deployment logs: %s", e, exc_info=True)
        return {"error": str(e), "deployment": deployment, "namespace": namespace, "stack": stack}


@router.get("/stack/history")
async def get_stack_history(
    hours: int = Query(0, description="Hours of history to retrieve (0 = all available)", ge=0, le=720)
):
    """
    Get historical snapshot data for trend analysis.
    Used by the history/trend charts in the side panel.

    PURPOSE:
        Provides historical data points for visualizing trends
        in deployment health, restart counts, and version changes.

    PARAMETERS:
        - hours (int): Hours of history to retrieve (1-168, default 24)

    RETURNS:
        {
            "history": [
                {
                    "timestamp": "2024-02-10T10:00:00",
                    "summary": {...},
                    "total_restarts": 5,
                    "healthy_count": 50,
                    "unhealthy_count": 2
                },
                ...
            ],
            "hours_requested": 24,
            "data_points": 24
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        history = monitoring_service.get_historical_data(hours=hours)

        return {"history": history, "hours_requested": hours, "data_points": len(history)}

    except Exception as e:
        logger.error("Error fetching stack history: %s", e, exc_info=True)
        return {"error": str(e), "history": [], "hours_requested": hours, "data_points": 0}


@router.get("/stack/restart-timeline")
async def get_restart_timeline(
    namespace: str = Query(..., description="Namespace key (e.g., '--addonman')"),
    deployment: str = Query(..., description="Deployment name"),
    stack: str = Query(..., description="Stack identifier (e.g., 'stg01')"),
):
    """
    Get restart timeline for a specific deployment.

    Analyzes historical snapshots to show when restarts started,
    when they last increased, and whether they are ongoing.

    PURPOSE:
        Provides context for "High Restart Count" issues in the
        Needs Attention panel, helping users understand:
        - When restarts first appeared
        - Whether restarts are ongoing or have stopped
        - The restart trend over time

    PARAMETERS:
        - namespace (str): Namespace key (e.g., "--addonman")
        - deployment (str): Deployment name
        - stack (str): Stack identifier (e.g., "stg01", "qa01")

    RETURNS:
        {
            "namespace": "--addonman",
            "deployment": "addonman-addonman",
            "stack": "stg01",
            "current_restarts": 15,
            "first_seen_at": "2024-02-10T08:00:00",
            "last_increased_at": "2024-02-10T14:00:00",
            "is_ongoing": true,
            "hours_since_last_increase": 2.5,
            "restart_history": [
                {"timestamp": "...", "restarts": 0},
                {"timestamp": "...", "restarts": 5},
                ...
            ]
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        timeline = monitoring_service.get_restart_timeline(namespace, deployment, stack)
        return timeline

    except Exception as e:
        logger.error("Error fetching restart timeline: %s", e, exc_info=True)
        return {
            "error": str(e),
            "namespace": namespace,
            "deployment": deployment,
            "stack": stack,
            "current_restarts": 0,
            "first_seen_at": None,
            "last_increased_at": None,
            "is_ongoing": False,
            "restart_history": [],
        }


@router.get("/stack/deployment-history")
async def get_deployment_history(
    namespace: str = Query(..., description="Namespace key (e.g., '--provisioner-pycore')"),
    deployment: str = Query(..., description="Deployment name"),
    stack: str = Query(..., description="Stack identifier (e.g., 'am2')"),
    hours: int = Query(24, description="Hours of history to retrieve (0 = all)", ge=0, le=720),
):
    """
    Get historical data for a specific deployment on a specific stack.

    PURPOSE:
        Provides deployment-specific historical data for the History tab
        in the deployment detail panel. Shows health, restarts, and replica
        counts over time for that specific service on that specific stack.

    PARAMETERS:
        - namespace (str): Namespace key (e.g., "--provisioner-pycore")
        - deployment (str): Deployment name
        - stack (str): Stack identifier (e.g., "am2", "stg01")
        - hours (int): Hours of history (default 24, 0 = all available)

    RETURNS:
        {
            "namespace": "--provisioner-pycore",
            "deployment": "provisioner-pycore-provisioner-pycore",
            "stack": "am2",
            "history": [
                {
                    "timestamp": "2024-02-10T10:00:00",
                    "healthy_count": 3,
                    "unhealthy_count": 0,
                    "restarts": 5,
                    "status": "healthy"
                }
            ],
            "summary": {
                "data_points": 24,
                "avg_healthy": 3,
                "max_unhealthy": 1,
                "total_restarts": 150
            }
        }
    """
    try:
        monitoring_service = get_monitoring_service()
        history = monitoring_service.get_deployment_history(namespace, deployment, stack, hours)
        return history

    except Exception as e:
        logger.error("Error fetching deployment history: %s", e, exc_info=True)
        return {
            "error": str(e),
            "namespace": namespace,
            "deployment": deployment,
            "stack": stack,
            "history": [],
            "summary": {
                "data_points": 0,
                "avg_healthy": 0,
                "max_unhealthy": 0,
                "total_restarts": 0,
            },
        }


@router.get("/stack/issues")
async def get_stack_issues(
    severity: str = Query(None, description="Filter by severity: critical, high, medium, low"),
    limit: int = Query(50, description="Maximum number of issues to return", ge=1, le=200),
):
    """
    Get prioritized issues for quick dashboard view.
    Returns only problematic deployments, sorted by severity.

    This is optimized for fast initial page loads - returns only what needs attention.

    PURPOSE:
        Provides a quick view of actionable issues without loading full deployment data.
        Used by the ActionableIssuesPanel for instant feedback.

    PARAMETERS:
        - severity (str, optional): Filter by severity level (critical, high, medium, low)
        - limit (int): Maximum issues to return (default 50, max 200)

    RETURNS:
        {
            "issues": [
                {
                    "id": "crash-qa01-otp",
                    "severity": "critical",
                    "type": "crashLoop",
                    "stack": "qa01",
                    "service": "otp",
                    "namespace": "otp",
                    "message": "5 restarts",
                    "timestamp": "2024-02-10T10:00:00"
                }
            ],
            "summary": {
                "critical": 2,
                "high": 5,
                "medium": 10,
                "low": 3
            },
            "total": 20
        }
    """
    try:
        monitoring_service = get_monitoring_service()

        # Ensure we have data (use cache for speed)
        if not monitoring_service.master_config:
            monitoring_service.generate_stack_config(use_cache=True, lite_mode=True)

        issues = []
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        # Iterate through deployments to find issues
        for namespace, deployments in monitoring_service.master_config.items():
            if namespace.startswith("_"):
                continue

            for deployment, stacks in deployments.items():
                if deployment.startswith("_"):
                    continue

                for stack, data in stacks.items():
                    status = data.get("status", "unknown")
                    restarts = data.get("restarts", 0)
                    crash_loop = data.get("crash_loop", False)

                    # Skip healthy and not_found deployments
                    if status == "healthy" or status == "not_found":
                        continue

                    issue = None

                    # Priority 1: CrashLoopBackOff (Critical)
                    if crash_loop:
                        issue = {
                            "id": f"crash-{stack}-{deployment}",
                            "severity": "critical",
                            "type": "crashLoop",
                            "stack": stack,
                            "service": deployment.split("/")[0],
                            "namespace": data.get("namespace_full", namespace),
                            "message": f"{restarts} restarts",
                            "timestamp": data.get("last_updated"),
                        }
                        summary["critical"] += 1

                    # Priority 2: Unhealthy deployments (High)
                    elif "unhealthy" in status or "error" in status:
                        replicas = data.get("replicas", {})
                        issue = {
                            "id": f"unhealthy-{stack}-{deployment}",
                            "severity": "high",
                            "type": "unhealthy",
                            "stack": stack,
                            "service": deployment.split("/")[0],
                            "namespace": data.get("namespace_full", namespace),
                            "message": f"{replicas.get('ready', 0)}/{replicas.get('desired', 0)} replicas",
                            "timestamp": data.get("last_updated"),
                        }
                        summary["high"] += 1

                    # Priority 3: High restart count (Medium)
                    elif restarts > 5:
                        issue = {
                            "id": f"restarts-{stack}-{deployment}",
                            "severity": "medium",
                            "type": "restarts",
                            "stack": stack,
                            "service": deployment.split("/")[0],
                            "namespace": data.get("namespace_full", namespace),
                            "message": f"{restarts} restarts",
                            "timestamp": data.get("last_updated"),
                        }
                        summary["medium"] += 1

                    if issue:
                        # Apply severity filter if specified
                        if severity is None or issue["severity"] == severity:
                            issues.append(issue)

        # Sort by severity priority
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda x: severity_order.get(x["severity"], 99))

        return {"issues": issues[:limit], "summary": summary, "total": len(issues)}

    except Exception as e:
        logger.error("Error fetching stack issues: %s", e, exc_info=True)
        return {"issues": [], "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "total": 0, "error": str(e)}


@router.post("/stack/snapshot")
async def create_snapshot():
    """
    Manually trigger a snapshot save.
    Normally snapshots are saved automatically, but this allows manual triggering.

    RETURNS:
        {
            "success": true,
            "filename": "snapshot_20240210_100000.json"
        }
    """
    try:
        monitoring_service = get_monitoring_service()

        # Ensure we have data
        if not monitoring_service.master_config:
            monitoring_service.generate_stack_config(use_cache=True)

        filename = monitoring_service.save_snapshot()

        return {"success": bool(filename), "filename": filename}

    except Exception as e:
        logger.error("Error creating snapshot: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


class SlackAlertRequest(BaseModel):
    """Request model for Slack alert endpoint."""

    severity_filter: Optional[str] = None  # "critical", "high", "medium", "low", or None for all
    channel: Optional[str] = None  # Override default channel
    include_summary: bool = True  # Include health summary in alert


@router.post("/stack/alert")
async def send_stack_slack_alert(request: SlackAlertRequest = None):
    """
    Send Slack notification for current stack monitoring issues.

    Collects all critical issues from stack monitoring and sends them
    to the configured Slack channel using the existing notification service.

    PURPOSE:
        Allows manual or automated triggering of Slack alerts for
        stack monitoring issues. Useful for on-demand notifications
        or integration with external monitoring systems.

    PARAMETERS (in request body):
        - severity_filter (str, optional): Filter alerts by severity (critical, high, medium, low)
        - channel (str, optional): Override default Slack channel
        - include_summary (bool): Include overall health summary (default: true)

    RETURNS:
        {
            "success": true,
            "alerts_sent": 5,
            "channel": "#monitoring-alerts",
            "message": "Sent 5 alerts to Slack"
        }

    SLACK REQUIREMENTS:
        - SLACK_BOT_TOKEN must be configured in .env
        - SLACK_CHANNEL must be set (or provide channel in request)
        - Bot must have access to the target channel
    """
    try:
        # Default request if none provided
        if request is None:
            request = SlackAlertRequest()

        monitoring_service = get_monitoring_service()

        # Ensure we have data
        if not monitoring_service.master_config:
            monitoring_service.generate_stack_config(use_cache=True, lite_mode=True)

        # Collect issues to alert on
        alerts: List[Dict[str, Any]] = []
        severity_filter = request.severity_filter

        # Track summary stats
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        total_healthy = 0
        total_unhealthy = 0

        # Iterate through deployments to find issues
        for namespace, deployments in monitoring_service.master_config.items():
            if namespace.startswith("_"):
                continue

            for deployment, stacks in deployments.items():
                if deployment.startswith("_"):
                    continue

                for stack, data in stacks.items():
                    status = data.get("status", "unknown")
                    restarts = data.get("restarts", 0)
                    crash_loop = data.get("crash_loop", False)
                    replicas = data.get("replicas", {})

                    # Count healthy/unhealthy
                    if status == "healthy":
                        total_healthy += 1
                        continue
                    elif status == "not_found":
                        continue
                    else:
                        total_unhealthy += 1

                    # Priority 1: CrashLoopBackOff (Critical)
                    if crash_loop:
                        severity = "critical"
                        message = f"CrashLoopBackOff - {restarts} restarts in {deployment}"
                        summary["critical"] += 1

                        if severity_filter is None or severity_filter == severity:
                            alerts.append(
                                {
                                    "stack": stack.upper(),
                                    "severity": severity,
                                    "message": message,
                                    "time": datetime.now().isoformat(),
                                    "region": data.get("namespace_full", namespace),
                                    "health_percent": 0,
                                    "healthy_count": replicas.get("ready", 0),
                                    "total_count": replicas.get("desired", 1),
                                }
                            )

                    # Priority 2: Unhealthy deployments (High)
                    elif "unhealthy" in status or "error" in status:
                        severity = "high"
                        ready = replicas.get("ready", 0)
                        desired = replicas.get("desired", 1)
                        health_pct = round((ready / desired * 100) if desired > 0 else 0, 1)
                        message = f"Unhealthy - {ready}/{desired} replicas ready for {deployment}"
                        summary["high"] += 1

                        if severity_filter is None or severity_filter == severity:
                            alerts.append(
                                {
                                    "stack": stack.upper(),
                                    "severity": severity,
                                    "message": message,
                                    "time": datetime.now().isoformat(),
                                    "region": data.get("namespace_full", namespace),
                                    "health_percent": health_pct,
                                    "healthy_count": ready,
                                    "total_count": desired,
                                }
                            )

                    # Priority 3: High restart count (Medium)
                    elif restarts > 5:
                        severity = "medium"
                        message = f"High restarts ({restarts}) for {deployment}"
                        summary["medium"] += 1

                        if severity_filter is None or severity_filter == severity:
                            alerts.append(
                                {
                                    "stack": stack.upper(),
                                    "severity": "warning",  # Map to Slack severity
                                    "message": message,
                                    "time": datetime.now().isoformat(),
                                    "region": data.get("namespace_full", namespace),
                                }
                            )

        # If no issues to alert on
        if not alerts:
            return {
                "success": True,
                "alerts_sent": 0,
                "message": "No issues to alert on - all deployments healthy!",
                "summary": summary,
                "health": {
                    "healthy": total_healthy,
                    "unhealthy": total_unhealthy,
                    "percent": round(
                        (
                            (total_healthy / (total_healthy + total_unhealthy) * 100)
                            if (total_healthy + total_unhealthy) > 0
                            else 100
                        ),
                        1,
                    ),
                },
            }

        # Send alerts via Slack
        logger.info("Sending %d stack monitoring alerts to Slack", len(alerts))

        result = await send_stack_alert_notification(alerts=alerts, channel=request.channel)

        if result.get("success"):
            return {
                "success": True,
                "alerts_sent": len(alerts),
                "channel": result.get("channel"),
                "message": f"Sent {len(alerts)} alerts to Slack",
                "summary": summary,
                "timestamp": result.get("ts"),
            }
        else:
            return {
                "success": False,
                "alerts_sent": 0,
                "error": result.get("error", "Unknown error"),
                "message": result.get("message", "Failed to send alerts"),
                "alerts_prepared": len(alerts),
            }

    except Exception as e:
        logger.error("Error sending stack alert: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "message": f"Failed to send Slack alert: {str(e)}"}


# =============================================================================
# Release Version Compliance Endpoint
# =============================================================================

# Legacy stacks to exclude from all version comparisons
# These stacks are on older versions and don't follow the standard release cycle
LEGACY_STACKS = {"stg01-mplegacy", "stg01_mplegacy"}

# VM-based production stacks that don't have certain Kubernetes deployments
# These stacks run on VMs and don't have clientstatus pods
VM_BASED_STACKS = {"am2", "fr4", "sv5"}

# Deployments that don't exist on VM-based stacks
# These should be excluded from version compliance checks for VM-based stacks
VM_BASED_EXCLUDED_DEPLOYMENTS = {
    "clientstatus-clientstatus",
    "clientstatus-clientasyncstatus",
}

# Stack categorization for release compliance checking
# Production stacks are grouped by deployment day for accurate version drift detection
# Note: stg01-mplegacy is excluded from comparisons via LEGACY_STACKS
STACK_CATEGORIES = {
    "npe": ["npa01", "npe01", "npe02"],
    "qa": ["qa01"],
    "staging": ["stg01", "fed1mp", "stg01-mp", "fed1-mp", "betaskope"],
    "preprod": ["devint", "fed-preprod", "fedpreprod", "fed02-mp-preprod", "fed02mppreprod", "fed02"],
    # Production stacks grouped by deployment day
    "prod_day1": ["sin2", "fr4"],
    "prod_day2": ["am2", "ruh1", "zur2"],
    "prod_day3": ["fra2", "lon3", "mel2", "dfw3", "sjc2"],
    "prod_day4": ["sv5", "sjc1"],
    # FedRAMP/PBMM stacks (follow their own schedule, typically aligned with Day 4)
    "prod_fedramp": ["fedramp", "fed-prod", "pbmm", "pbmm-prod"],
}

# Milestone to stack category mapping
# Each prod day milestone maps to its corresponding stack group
# NOTE: QA is NOT included here because QA01 is always on develop branch (N+1),
# not tied to any specific milestone. QA expected version is calculated separately.
MILESTONE_TO_CATEGORY = {
    "Signoff STG/FedAlpha - ENG": "staging",
    "Deploy MP Pre PROD": "preprod",
    "Deploy Prod Day 1": "prod_day1",
    "Deploy Prod Day 2": "prod_day2",
    "Deploy Prod Day 3": "prod_day3",
    "Deploy Prod Day 4": "prod_day4",
}


def get_stack_category(stack_id: str) -> str:
    """
    Determine the category of a stack.

    Categories:
    - npe: Development environments (npa01, npe01, npe02)
    - qa: QA environments (qa01)
    - staging: Staging environments (stg01, fed1mp, etc.)
    - preprod: Pre-production (devint, fed-preprod, etc.)
    - prod_day1: Production Day 1 stacks (SIN2, FR4)
    - prod_day2: Production Day 2 stacks (AM2, RUH1, ZUR2)
    - prod_day3: Production Day 3 stacks (FRA2, LON3, MEL2, DFW3, SJC2)
    - prod_day4: Production Day 4 stacks (SV5, SJC1)
    - prod_fedramp: FedRAMP/PBMM stacks
    """
    if not stack_id:
        return "unknown"

    normalized = stack_id.lower().replace("-", "").replace("_", "")
    original = stack_id.lower()

    for category, stacks in STACK_CATEGORIES.items():
        for pattern in stacks:
            normalized_pattern = pattern.replace("-", "").replace("_", "")
            if normalized == normalized_pattern or normalized.startswith(normalized_pattern):
                return category
            if original == pattern or original.startswith(pattern):
                return category

    # Fallback: check production patterns and assign to appropriate day
    # This handles variations like "pe-sin2", "mp-prod-sin2", etc.
    prod_day1_patterns = ["sin2", "fr4"]
    prod_day2_patterns = ["am2", "ruh1", "zur2"]
    prod_day3_patterns = ["fra2", "lon3", "mel2", "dfw3", "sjc2"]
    prod_day4_patterns = ["sv5", "sjc1"]
    prod_fedramp_patterns = ["fedramp", "fed-prod", "pbmm"]

    for pattern in prod_day1_patterns:
        if pattern in original:
            return "prod_day1"
    for pattern in prod_day2_patterns:
        if pattern in original:
            return "prod_day2"
    for pattern in prod_day3_patterns:
        if pattern in original:
            return "prod_day3"
    for pattern in prod_day4_patterns:
        if pattern in original:
            return "prod_day4"
    for pattern in prod_fedramp_patterns:
        if pattern in original:
            return "prod_fedramp"

    return "unknown"


def is_vm_based_stack(stack_id: str) -> bool:
    """
    Check if a stack is VM-based (not running on Kubernetes for all services).

    VM-based stacks don't have certain Kubernetes deployments like clientstatus pods.
    """
    if not stack_id:
        return False

    normalized = stack_id.lower().replace("-", "").replace("_", "")
    for vm_stack in VM_BASED_STACKS:
        vm_normalized = vm_stack.replace("-", "").replace("_", "")
        if normalized == vm_normalized or vm_normalized in normalized:
            return True
    return False


def extract_version_number(release_name: str) -> str:
    """Extract the major.minor version from release name (e.g., R135.1 -> 135.1)."""
    if not release_name:
        return ""
    # Remove 'R' prefix and get major.minor version
    version = release_name.upper().replace("R", "").strip()
    parts = version.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0] if parts else ""


def check_version_matches_release(stack_version: str, expected_version_prefix: str) -> bool:
    """Check if a stack version matches the expected release version prefix."""
    if not stack_version or not expected_version_prefix:
        return False

    # Clean up version string
    version = stack_version.lower().strip()

    # Remove common prefixes like 'v'
    if version.startswith("v"):
        version = version[1:]

    # Check if version starts with the expected prefix
    return version.startswith(expected_version_prefix)


@router.get("/release-compliance")
async def get_release_compliance():
    """
    Check release version compliance across stacks.

    PURPOSE:
        Validates that stacks have the correct release version based on
        release calendar milestones. Generates alerts when stacks don't
        have the expected version after a milestone date has passed.

    COMPLIANCE RULES:
        - Branch Cut - EP reached → All QA stacks should have that release
        - Signoff STG/FedAlpha - ENG reached → All Staging stacks should have that release
        - Deploy MP Pre PROD reached → All Pre-Prod stacks should have that release
        - Deploy Prod Day 1 reached → All Prod stacks should have that release

    RETURNS:
        {
            "compliance_alerts": [
                {
                    "id": "compliance-qa01-135",
                    "type": "release_compliance",
                    "severity": "high",
                    "stack": "qa01",
                    "stack_category": "qa",
                    "milestone": "Branch Cut - EP",
                    "milestone_date": "01-Mar-2026",
                    "expected_version": "135",
                    "current_versions": {"service1": "134.0.5", "service2": "135.0.1"},
                    "non_compliant_services": [{"service": "service1", "version": "134.0.5"}],
                    "message": "qa01 should have version 135 (Branch Cut reached Mar 1)"
                }
            ],
            "current_release": "R135.0",
            "active_milestones": {...},
            "summary": {"total_alerts": 2, "by_category": {"qa": 0, "staging": 1, "preprod": 0, "prod": 1}}
        }
    """
    from services.release_calendar_parser import get_release_calendar_data

    try:
        # Get release calendar data
        calendar_data = get_release_calendar_data()
        releases = calendar_data.get("releases", [])
        current_release_name = calendar_data.get("current_release")

        if not releases:
            return {
                "compliance_alerts": [],
                "current_release": None,
                "active_milestones": {},
                "summary": {"total_alerts": 0, "by_category": {}},
                "message": "No release calendar data available",
            }

        # Find current/in-progress releases
        # Use PST timezone for date comparisons to ensure consistent behavior
        today = datetime.now(PST_TIMEZONE).date()
        active_milestones = {}

        # Track the latest release that has reached Branch Cut (for QA N+1 calculation)
        branch_cut_release_info = None

        for release in releases:
            if release.get("status") not in ["In Progress", "Completed"]:
                continue

            milestones = release.get("milestones", {})
            release_name = release.get("name", "")
            version_prefix = extract_version_number(release_name)

            if not version_prefix:
                continue

            # Check Branch Cut milestone to track N for QA calculation
            branch_cut_date_str = milestones.get("Branch Cut - EP", "-")
            if branch_cut_date_str != "-":
                try:
                    branch_cut_date = datetime.strptime(branch_cut_date_str, "%d-%b-%Y").date()
                    if today >= branch_cut_date:
                        # Track the latest release that has reached Branch Cut
                        if branch_cut_release_info is None or branch_cut_date > branch_cut_release_info["date"]:
                            branch_cut_release_info = {
                                "release": release_name,
                                "version_prefix": version_prefix,
                                "date": branch_cut_date,
                                "date_str": branch_cut_date_str,
                            }
                except ValueError:
                    pass

            # Check each milestone (excludes QA - handled separately below)
            for milestone_name, category in MILESTONE_TO_CATEGORY.items():
                milestone_date_str = milestones.get(milestone_name, "-")
                if milestone_date_str == "-":
                    continue

                try:
                    milestone_date = datetime.strptime(milestone_date_str, "%d-%b-%Y").date()

                    # If milestone date has passed, this category should have this version
                    if today >= milestone_date:
                        # Store the latest milestone that has passed for each category
                        if category not in active_milestones or milestone_date > active_milestones[category]["date"]:
                            active_milestones[category] = {
                                "release": release_name,
                                "version_prefix": version_prefix,
                                "milestone": milestone_name,
                                "date": milestone_date,
                                "date_str": milestone_date_str,
                            }
                except ValueError:
                    logger.warning(f"Invalid date format for {milestone_name}: {milestone_date_str}")
                    continue

        # QA stacks: Always on develop branch (N+1)
        # N = the release version that has reached Branch Cut (what STG01 should have)
        # QA01 should have N+1 (one version ahead of STG01)
        if branch_cut_release_info:
            try:
                # Extract major version from the release that reached Branch Cut
                branch_cut_version = branch_cut_release_info["version_prefix"]
                major_version = int(branch_cut_version.split(".")[0])  # e.g., 137
                develop_version = major_version + 1  # e.g., 138

                active_milestones["qa"] = {
                    "release": f"R{develop_version}.0 (develop)",
                    "version_prefix": str(develop_version),
                    "milestone": "Develop Branch (N+1)",
                    "date": branch_cut_release_info["date"],
                    "date_str": branch_cut_release_info["date_str"],
                    "note": f"QA01 runs on develop branch, N+1 from Branch Cut release R{major_version}",
                }
                logger.info(
                    f"QA expected version set to develop branch: R{develop_version} (N+1 from Branch Cut release R{major_version})"
                )
            except (ValueError, IndexError) as e:
                logger.warning(f"Could not calculate develop branch version for QA: {e}")

        logger.info(f"Release compliance: today={today}, active_milestones={active_milestones}")

        if not active_milestones:
            return {
                "compliance_alerts": [],
                "current_release": current_release_name,
                "active_milestones": {},
                "summary": {"total_alerts": 0, "by_category": {}},
                "message": "No active milestones requiring version compliance",
            }

        # Get stack monitoring data
        monitoring_service = get_monitoring_service()
        stack_data = monitoring_service.get_formatted_data()
        deployments = stack_data.get("deployments", [])

        if not deployments:
            return {
                "compliance_alerts": [],
                "current_release": current_release_name,
                "active_milestones": {
                    k: {"release": v["release"], "milestone": v["milestone"], "date": v["date_str"]}
                    for k, v in active_milestones.items()
                },
                "summary": {"total_alerts": 0, "by_category": {}},
                "message": "No stack monitoring data available",
            }

        # Check compliance for each stack
        compliance_alerts = []
        summary = {
            "total_alerts": 0,
            "by_category": {
                "qa": 0,
                "staging": 0,
                "preprod": 0,
                "prod_day1": 0,
                "prod_day2": 0,
                "prod_day3": 0,
                "prod_day4": 0,
                "prod_fedramp": 0,
            },
        }

        # Services to EXCLUDE from version mismatch checking entirely
        # These services have their own independent release cycles and don't follow the main release version
        EXCLUDED_SERVICES = {
            # enrollment-service deployments
            "enrollment-service-configuration",
            "enrollment-service-validation",
            "enrollment-service-deprovision",
            "enrollment-service-vaultrotate",
            # device-classification deployments
            "device-classification-configuration",
            "device-classification-deprovisioner",
            "device-classification-evaluator",
            "device-classification-tag",
            # otp
            "otp",
        }

        # Group deployments by stack
        stacks_versions = {}
        for deployment in deployments:
            stacks_info = deployment.get("stacks", {})
            for stack_id, stack_info in stacks_info.items():
                if stack_info.get("status") == "not_found":
                    continue

                version = stack_info.get("version", "")
                if not version or version == "latest":
                    continue

                if stack_id not in stacks_versions:
                    stacks_versions[stack_id] = {}

                deployment_name = deployment.get("deployment", "")
                stacks_versions[stack_id][deployment_name] = version

        # Check each stack against its expected version
        checked_stacks = set()
        logger.info(f"Release compliance check: active_milestones={list(active_milestones.keys())}")
        logger.info(f"Release compliance check: stacks to check={list(stacks_versions.keys())}")

        for stack_id, services in stacks_versions.items():
            # Skip legacy stacks from version compliance checking
            normalized_stack = stack_id.lower().replace("-", "").replace("_", "")
            if any(legacy.replace("-", "").replace("_", "") in normalized_stack for legacy in LEGACY_STACKS):
                logger.debug(f"Skipping legacy stack {stack_id} from compliance check")
                continue

            category = get_stack_category(stack_id)
            logger.debug(f"Stack {stack_id} categorized as: {category}")

            if category == "unknown" or category not in active_milestones:
                logger.debug(
                    f"Skipping stack {stack_id}: category={category}, in_active_milestones={category in active_milestones}"
                )
                continue

            if stack_id in checked_stacks:
                continue
            checked_stacks.add(stack_id)

            milestone_info = active_milestones[category]
            expected_version = milestone_info["version_prefix"]

            # Check each service version
            non_compliant = []
            compliant = []
            stack_is_vm_based = is_vm_based_stack(stack_id)

            for service, version in services.items():
                # Extract the actual deployment name (handle deployment/container format)
                # The service name is "deployment_name/container_name" (e.g., "enrollment-service-configuration/enrollment-service-configuration")
                service_deployment_name = service.split("/")[0] if "/" in service else service

                # Skip excluded services (enrollment-service, device-classification, otp)
                # These have their own independent release cycles
                if service_deployment_name in EXCLUDED_SERVICES:
                    continue

                # Skip VM-based excluded deployments for VM-based stacks
                # VM-based stacks (AM2, FR4, SV5) don't have clientstatus pods
                if stack_is_vm_based and service_deployment_name in VM_BASED_EXCLUDED_DEPLOYMENTS:
                    logger.debug(f"Skipping {service_deployment_name} for VM-based stack {stack_id}")
                    continue

                # Standard release version check
                if check_version_matches_release(version, expected_version):
                    compliant.append({"service": service, "version": version})
                else:
                    non_compliant.append({"service": service, "version": version})

            # Generate alert if there are non-compliant services
            if non_compliant:
                # Determine severity based on ratio
                compliance_ratio = (
                    len(compliant) / (len(compliant) + len(non_compliant))
                    if (len(compliant) + len(non_compliant)) > 0
                    else 0
                )
                severity = "critical" if compliance_ratio < 0.5 else "high"

                compliance_alerts.append(
                    {
                        "id": f"compliance-{stack_id}-{expected_version}",
                        "type": "release_compliance",
                        "severity": severity,
                        "stack": stack_id,
                        "stackName": stack_id.upper(),
                        "stack_category": category,
                        "milestone": milestone_info["milestone"],
                        "milestone_date": milestone_info["date_str"],
                        "expected_version": expected_version,
                        "release_name": milestone_info["release"],
                        "current_versions": services,
                        "non_compliant_services": non_compliant,
                        "compliant_services": compliant,
                        "compliance_ratio": round(compliance_ratio * 100, 1),
                        "message": f"{stack_id.upper()} has {len(non_compliant)} service(s) not on expected version ({milestone_info['milestone']} reached {milestone_info['date_str']})",
                    }
                )
                summary["by_category"][category] += 1
                summary["total_alerts"] += 1

        # Sort alerts by severity and category
        # Production day categories are ordered by day (Day 1 is most critical)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        category_order = {
            "prod_day1": 0,
            "prod_day2": 1,
            "prod_day3": 2,
            "prod_day4": 3,
            "prod_fedramp": 4,
            "preprod": 5,
            "staging": 6,
            "qa": 7,
        }
        compliance_alerts.sort(
            key=lambda x: (severity_order.get(x["severity"], 99), category_order.get(x["stack_category"], 99))
        )

        # Debug info for troubleshooting
        debug_info = {
            "stacks_found": list(stacks_versions.keys()),
            "stacks_checked": list(checked_stacks),
            "stack_categories": {s: get_stack_category(s) for s in stacks_versions.keys()},
        }

        return {
            "compliance_alerts": compliance_alerts,
            "current_release": current_release_name,
            "active_milestones": {
                k: {
                    "release": v["release"],
                    "milestone": v["milestone"],
                    "date": v["date_str"],
                    "expected_version": v["version_prefix"],
                }
                for k, v in active_milestones.items()
            },
            "excluded_services": list(EXCLUDED_SERVICES),
            "summary": summary,
            "debug": debug_info,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error checking release compliance: %s", e, exc_info=True)
        return {
            "compliance_alerts": [],
            "current_release": None,
            "active_milestones": {},
            "summary": {"total_alerts": 0, "by_category": {}},
            "error": str(e),
            "message": f"Failed to check release compliance: {str(e)}",
        }

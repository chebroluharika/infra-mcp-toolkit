"""
Slack Notification Router
==========================

Endpoints for sending Slack notifications.

Endpoints:
    - POST /api/slack/notify - Send release readiness notification
    - POST /api/slack/notify-all - Notify all active releases
    - POST /api/slack/notify/regression-actions - Send regression action items
    - POST /api/slack/notify/regression-status - Send regression status (4 category tables)
    - POST /api/slack/stack-alert - Send stack monitoring alert
    - GET /api/slack/status - Check Slack configuration status
    - GET /api/slack/scheduler/status - Scheduler status
    - POST /api/slack/scheduler/trigger - Manual trigger
"""

import logging
from typing import List, Optional

from config import DEFAULT_RELEASE_ID, settings
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from services.slack_notifications import (
    get_slack_service,
    send_deployment_version_report_notification,
    send_regression_action_items_notification,
    send_regression_status_notification,
    send_release_readiness_notification,
    send_stack_alert_notification,
)
from services.slack_scheduler import get_scheduler_status, trigger_notification_now

# On-call notification scheduler
try:
    from services.oncall_notification_scheduler import (
        get_oncall_notification_status,
        preview_oncall_reminders,
        trigger_oncall_reminders_now,
    )

    _oncall_scheduler_available = True
except ImportError:
    _oncall_scheduler_available = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])


class NotificationRequest(BaseModel):
    """Request model for sending notifications."""

    release: Optional[str] = None
    channel: Optional[str] = None
    bot_token: Optional[str] = None


@router.get("/status")
async def get_slack_status():
    """
    Check Slack notification service configuration and connectivity.

    PURPOSE:
        Verifies that Slack integration is properly configured with
        valid bot token and channel. Used to diagnose notification issues.

    WHEN TO USE:
        - Checking if Slack notifications are configured
        - Debugging notification delivery issues
        - Verifying bot token and channel settings

    RETURNS:
        {
            "configured": true,
            "has_token": true,
            "has_channel": true,
            "channel": "#release-readiness",
            "user_lookup": "working",
            "cached_users": 150,
            "message": "Slack is configured and ready"
        }
    """
    service = get_slack_service()

    # Check user mapping status
    from services.slack_notifications import _load_user_mapping

    user_mapping = _load_user_mapping()
    user_count = len(user_mapping)

    return {
        "configured": service.enabled,
        "has_token": bool(service.bot_token),
        "has_channel": bool(service.channel),
        "channel": service.channel if service.channel else "Not configured",
        "stack_alerts_enabled": settings.slack_stack_alerts_enabled,
        "user_mapping": f"{user_count} users loaded from user_mapping.json",
        "user_count": user_count,
        "message": (
            "Slack is configured and ready"
            if service.enabled
            else "Slack not configured - set SLACK_BOT_TOKEN and SLACK_CHANNEL"
        ),
    }


class SimpleMessageRequest(BaseModel):
    """Request model for simple Slack message."""

    channel: str
    message: str


@router.post("/send")
async def send_simple_message(request: SimpleMessageRequest):
    """
    Send a simple text message to a Slack channel.

    Used for alerts, notifications from scripts, etc.

    Args:
        channel: Slack channel ID (e.g., YOUR_SLACK_CHANNEL_ID)
        message: Text message (supports Slack markdown)
    """
    service = get_slack_service()

    if not service.enabled:
        raise HTTPException(status_code=503, detail="Slack not configured")

    try:
        result = await service.send_notification(
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": request.message}}],
            text=request.message,
            channel=request.channel,
        )
        return {
            "success": result.get("success", False),
            "channel": request.channel,
        }
    except Exception as e:
        logger.error("Failed to send Slack message: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify-all")
async def send_all_notifications():
    """
    Send release readiness notifications for ALL active releases.

    PURPOSE:
        Sends separate notifications for each currently active release.
        Active releases are determined by timeline (between IRR-7 days
        and Final Build+14 days).

    WHEN TO USE:
        - Daily scheduled notification for all releases
        - Bulk notification trigger
        - When multiple releases are in progress simultaneously

    RETURNS:
        {
            "success": true,
            "message": "Sent 2/2 notifications",
            "releases_sent": ["R135", "R134"],
            "results": [
                {"release": "R135", "success": true},
                {"release": "R134", "success": true}
            ]
        }

    ACTIVE RELEASE CRITERIA:
        - IRR date is within 7 days OR already passed
        - Final Build date is within 14 days of today

    RELATED ENDPOINTS:
        - POST /api/slack/notify - Single release notification
    """
    from config import get_active_releases

    active_releases = get_active_releases()

    if not active_releases:
        return {
            "success": False,
            "message": "No active releases found based on timeline",
            "releases_sent": [],
        }

    results = []
    for release_id in active_releases:
        try:
            release_data = await _fetch_release_readiness_data(release_id)
            if release_data:
                result = await send_release_readiness_notification(release_data=release_data)
                results.append({"release": release_id, "success": result.get("success", False)})
            else:
                results.append({"release": release_id, "success": False, "error": "Failed to fetch data"})
        except Exception as e:
            results.append({"release": release_id, "success": False, "error": str(e)})

    success_count = sum(1 for r in results if r.get("success"))

    return {
        "success": success_count == len(active_releases),
        "message": f"Sent {success_count}/{len(active_releases)} notifications",
        "releases_sent": [r["release"] for r in results if r.get("success")],
        "results": results,
    }


@router.post("/notify")
@router.post("/notify/release-readiness")  # Keep old path for backward compatibility
async def send_notification(request: NotificationRequest = Body(...)):
    """
    Send release readiness notification to Slack channel.

    PURPOSE:
        Sends a formatted release readiness notification to the configured
        Slack channel. Includes release status, open items by assignee,
        and critical blockers. Can be triggered manually or by scheduler.

    WHEN TO USE:
        - Manual trigger via "Send Notification" button
        - Scheduled daily notifications
        - Testing Slack integration
        - Alerting team about release status

    REQUEST BODY:
        {
            "release": "R135",      # Release ID (default: current)
            "channel": "#custom",   # Override channel (optional)
            "bot_token": "..."      # Override token (optional)
        }

    RETURNS:
        {
            "success": true,
            "message": "Release readiness notification sent for R135",
            "release": "R135",
            "channel": "#release-readiness",
            "timestamp": "1706961600.123456",
            "table_included": true,
            "critical_items_sent": true
        }

    NOTIFICATION CONTENT:
        - Release status summary (phase, days remaining)
        - Open items count (stories, bugs, code review)
        - Table of items by assignee
        - Critical blockers highlighted

    RELATED ENDPOINTS:
        - POST /api/slack/notify-all - Notify all active releases
        - GET /api/slack/status - Check configuration
        - GET /api/jira/release-readiness - Data source
    """
    release_id = request.release or DEFAULT_RELEASE_ID

    try:
        # Clear JIRA cache to ensure fresh data
        from services.jira_client import get_jira_client

        try:
            jira = get_jira_client()
            jira.clear_cache()
            logger.info("Cleared JIRA cache before sending notification for %s", release_id)
        except Exception as e:
            logger.warning("Could not clear JIRA cache: %s", e)

        # Fetch release readiness data
        release_data = await _fetch_release_readiness_data(release_id)

        if not release_data:
            raise HTTPException(status_code=500, detail="Failed to fetch release readiness data")

        # Send notification
        result = await send_release_readiness_notification(
            release_data=release_data, bot_token=request.bot_token, channel=request.channel
        )

        if result.get("success"):
            response = {
                "success": True,
                "message": f"Release readiness notification sent for {release_id}",
                "release": release_id,
                "channel": result.get("channel"),
                "timestamp": result.get("ts"),
            }
            if result.get("table_included"):
                response["table_included"] = True
            if result.get("critical_items_sent"):
                response["critical_items_sent"] = True
                response["critical_items_count"] = result.get("critical_items_count", 0)
            if result.get("qa_verification_sent"):
                response["qa_verification_sent"] = True
                response["qa_verification_count"] = result.get("qa_verification_count", 0)
            return response
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending Slack notification: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


class StackAlertRequest(BaseModel):
    """Request model for stack monitoring alerts."""

    alerts: list  # List of alert dicts
    channel: Optional[str] = None


@router.post("/stack-alert")
async def send_stack_alert(request: StackAlertRequest = Body(...)):
    """
    Send stack monitoring alert to Slack channel.

    PURPOSE:
        Sends alerts from Stack Monitoring section to the configured
        Slack channel. Supports single or batch alerts.

    WHEN TO USE:
        - When stack monitoring detects issues
        - Version mismatches across stacks
        - Health degradation alerts
        - Critical/warning/info notifications

    PARAMETERS:
        - alerts: List of alert objects with:
            - stack: Stack name (e.g., "PROD01", "STG03")
            - severity: "critical", "warning", or "info"
            - message: Alert description
            - time: Optional timestamp
            - region: Optional region name
            - health_percent: Optional health percentage
            - healthy_count: Optional healthy count
            - total_count: Optional total count
        - channel: Optional channel override

    RETURNS:
        {
            "success": true,
            "channel": "#monitoring-alerts",
            "alerts_count": 3,
            "message": "Stack alert sent successfully"
        }

    EXAMPLE REQUEST:
        POST /api/slack/stack-alert
        {
            "alerts": [
                {
                    "stack": "PROD01",
                    "severity": "warning",
                    "message": "API response time increased",
                    "region": "US-EAST-1"
                }
            ]
        }
    """
    if not request.alerts:
        raise HTTPException(status_code=400, detail="No alerts provided")

    # Check if stack alerts are enabled
    if not settings.slack_stack_alerts_enabled:
        logger.info(
            "Stack alerts disabled (SLACK_STACK_ALERTS_ENABLED=false), skipping %d alert(s)", len(request.alerts)
        )
        return {
            "success": True,
            "channel": None,
            "alerts_count": len(request.alerts),
            "message": "Stack alerts disabled via configuration",
            "skipped": True,
        }

    try:
        logger.info("Sending stack alert: %d alert(s)", len(request.alerts))

        result = await send_stack_alert_notification(
            alerts=request.alerts,
            channel=request.channel,
        )

        if result.get("success"):
            return {
                "success": True,
                "channel": result.get("channel"),
                "alerts_count": len(request.alerts),
                "message": "Stack alert sent successfully",
            }

        raise HTTPException(status_code=500, detail=f"Failed to send stack alert: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending stack alert: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


class DeploymentVersionReportRequest(BaseModel):
    """Request model for deployment version report notification."""

    stacks: Optional[List[str]] = None  # If None, uses default stacks
    channel: Optional[str] = None


class DeploymentVersionReportDirectRequest(BaseModel):
    """Request model for direct deployment version report (pre-formatted data)."""

    report_data: dict  # Pre-formatted report data
    channel: Optional[str] = None


@router.post("/notify/deployment-version-report/direct")
async def send_deployment_version_report_direct(request: DeploymentVersionReportDirectRequest = Body(...)):
    """
    Send Deployment Version Report to Slack channel with pre-formatted data.

    This endpoint allows sending a deployment version report without fetching
    from Kubernetes - useful for testing or when data is already available.

    REQUEST BODY:
        {
            "report_data": {
                "stacks": ["QA01", "STG01"],
                "deployments": [
                    {
                        "service": "addonman",
                        "deployment_container": "addonman/addonman",
                        "versions": {
                            "QA01": {"version": "136.0.0.23403", "status": "healthy"}
                        }
                    }
                ],
                "generated_at": "2026-02-11 05:24:43 PM IST"
            },
            "channel": "YOUR_SLACK_CHANNEL_ID"
        }
    """
    try:
        result = await send_deployment_version_report_notification(
            report_data=request.report_data, channel=request.channel
        )

        if result.get("success"):
            return {
                "success": True,
                "message": "Deployment version report sent",
                "deployments_count": len(request.report_data.get("deployments", [])),
                "channel": result.get("channel"),
            }

        raise HTTPException(status_code=500, detail=f"Failed to send report: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending deployment version report: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notify/deployment-version-report")
async def send_deployment_version_report(request: DeploymentVersionReportRequest = Body(...)):
    """
    Send Deployment Version Report to Slack channel.

    Fetches deployment version data from stack monitoring and sends a table
    showing versions across stacks with health status indicators.

    REQUEST BODY:
        {
            "stacks": ["qa01", "stg01"],  # Optional - uses defaults if not provided
            "channel": "YOUR_SLACK_CHANNEL_ID"       # Optional - uses default if not provided
        }

    RETURNS:
        {
            "success": true,
            "message": "Deployment version report sent",
            "deployments_count": 45,
            "stacks": ["QA01", "STG01"]
        }
    """
    from datetime import datetime

    from services.stack_monitoring import get_monitoring_service

    try:
        # Get stack monitoring data using the singleton (has cached data)
        monitoring_service = get_monitoring_service()

        # Use provided stacks or defaults
        stacks = request.stacks or ["qa01", "stg01"]

        # Generate data for the requested stacks (uses cache if available)
        monitoring_service.generate_stack_config(stacks=stacks, use_cache=True)

        # Get formatted data
        formatted_data = monitoring_service.get_formatted_data()

        # Transform data for the Slack message
        deployments_list = []
        stacks_upper = [s.upper() for s in stacks]

        for dep in formatted_data.get("deployments", []):
            namespace = dep.get("namespace", "")
            deployment = dep.get("deployment", "")
            stacks_data = dep.get("stacks", {})

            # Extract service name from namespace (remove leading dashes)
            service = namespace.lstrip("-").replace("--", "-")
            if not service:
                # Fallback: extract from deployment name
                service = deployment.split("/")[0].split("-")[0] if "/" in deployment else deployment.split("-")[0]

            # deployment field already contains the full path like "clientstatus-clientstatus/status-updater"
            deployment_container = deployment

            # Build versions dict - only include requested stacks
            versions = {}
            for stack in stacks:
                stack_upper = stack.upper()
                stack_info = stacks_data.get(stack, {})

                if stack_info:
                    version = stack_info.get("version", "N/A")
                    status_raw = stack_info.get("status", "unknown")

                    # Normalize status
                    if status_raw in ["Running", "running", "healthy", "ok"]:
                        status = "healthy"
                    elif status_raw in ["not_found", "N/A", ""]:
                        status = "not_found"
                    else:
                        status = "unhealthy"

                    versions[stack_upper] = {"version": version, "status": status, "error": stack_info.get("error", "")}

            # Only include deployments that have data for the requested stacks
            if versions:
                deployments_list.append(
                    {"service": service, "deployment_container": deployment_container, "versions": versions}
                )

        # Sort by service name alphabetically
        deployments_list.sort(key=lambda x: x.get("service", "").lower())

        # Build report data
        now = datetime.now()
        ist_time = now.strftime("%Y-%m-%d %I:%M:%S %p IST")

        report_data = {"stacks": stacks_upper, "deployments": deployments_list, "generated_at": ist_time}

        # Send notification
        result = await send_deployment_version_report_notification(report_data=report_data, channel=request.channel)

        if result.get("success"):
            return {
                "success": True,
                "message": "Deployment version report sent",
                "deployments_count": len(deployments_list),
                "stacks": stacks_upper,
                "channel": result.get("channel"),
            }

        raise HTTPException(status_code=500, detail=f"Failed to send report: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending deployment version report: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


class RegressionActionRequest(BaseModel):
    """Request model for regression action items notification."""

    release: Optional[str] = None
    channel: Optional[str] = None


@router.post("/notify/regression-actions")
async def send_regression_actions_notification(request: RegressionActionRequest = Body(...)):
    """
    Send regression action items notification to Slack.

    Fetches regression tracking data from JIRA and sends a Slack message
    with not-started and blocked items including assignee names.

    REQUEST BODY:
        {
            "release": "R135",      # Release ID (default: current)
            "channel": "#custom"    # Override channel (optional)
        }

    RETURNS:
        {
            "success": true,
            "message": "Regression action items sent for R135",
            "release": "R135",
            "not_started_count": 4,
            "blocked_count": 2
        }
    """
    from config import RELEASE_MILESTONES

    release_id = request.release or DEFAULT_RELEASE_ID

    # Find the regression epic for this release
    epic_key = None
    for rel in RELEASE_MILESTONES:
        if rel["id"] == release_id:
            epics = rel.get("regression_epics", [])
            if epics:
                epic_key = epics[0]
            break

    if not epic_key:
        raise HTTPException(
            status_code=400,
            detail=f"No regression epic configured for release {release_id}. "
            f"Add regression_epics to RELEASE_MILESTONES in backend/config.py",
        )

    try:
        # Fetch regression hierarchy data from the JIRA endpoint
        regression_data = await _fetch_regression_hierarchy_data(epic_key)

        if not regression_data:
            raise HTTPException(status_code=500, detail="Failed to fetch regression tracking data from JIRA")

        # Attach release_id for the notification header
        regression_data["release_id"] = release_id

        # Send the notification
        result = await send_regression_action_items_notification(
            regression_data=regression_data,
            channel=request.channel,
        )

        if result.get("success"):
            return {
                "success": True,
                "message": f"Regression action items sent for {release_id}",
                "release": release_id,
                "epic_key": epic_key,
                "channel": result.get("channel"),
                "timestamp": result.get("ts"),
                "not_started_count": result.get("not_started_count", 0),
            }

        raise HTTPException(status_code=500, detail=f"Failed to send notification: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending regression action items notification: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


class RegressionStatusRequest(BaseModel):
    """Request model for regression status notification (2 grouped tables)."""

    release: Optional[str] = None
    channel: Optional[str] = None


@router.post("/notify/regression-status")
async def send_regression_status_notification_endpoint(request: RegressionStatusRequest = Body(...)):
    """
    Send regression status notification to Slack (2 grouped messages).

    Fetches regression tracking data from JIRA and sends 2 Slack messages
    to the dedicated regression channel (YOUR_SLACK_CHANNEL_ID):

    Message 1: Status by Category
        - Header with release info and overall summary
        - Table: Category | Blocked | To Do | In Prog | Done | Total

    Message 2: Workload by Assignee
        - Table: Assignee | Func Val | Non-Func | Interop | Auto Reg | Blocked | To Do | In Prog | Done | Total
        - CC recipients and footer

    All numbers are clickable JIRA links.

    REQUEST BODY:
        {
            "release": "R135",      # Release ID (default: current)
            "channel": "YOUR_SLACK_CHANNEL_ID"  # Override channel (optional)
        }

    RETURNS:
        {
            "success": true,
            "message": "Regression status sent for R135",
            "release": "R135",
            "messages_sent": 4,
            "tables": ["Functional Validation - Manual", ...]
        }
    """
    from config import RELEASE_MILESTONES
    from services.slack_notifications import REGRESSION_SLACK_CHANNEL

    release_id = request.release or DEFAULT_RELEASE_ID

    # Find the regression epic for this release
    epic_key = None
    for rel in RELEASE_MILESTONES:
        if rel["id"] == release_id:
            epics = rel.get("regression_epics", [])
            if epics:
                epic_key = epics[0]
            break

    if not epic_key:
        raise HTTPException(
            status_code=400,
            detail=f"No regression epic configured for release {release_id}. "
            f"Add regression_epics to RELEASE_MILESTONES in backend/config.py",
        )

    try:
        # Fetch regression hierarchy data from the JIRA endpoint
        regression_data = await _fetch_regression_hierarchy_data(epic_key)

        if not regression_data:
            raise HTTPException(status_code=500, detail="Failed to fetch regression tracking data from JIRA")

        # Attach release_id for the notification header
        regression_data["release_id"] = release_id

        # Use dedicated regression channel or override
        target_channel = request.channel or REGRESSION_SLACK_CHANNEL

        # Send the notification (4 messages)
        result = await send_regression_status_notification(
            regression_data=regression_data,
            channel=target_channel,
        )

        if result.get("success"):
            return {
                "success": True,
                "message": f"Regression status sent for {release_id}",
                "release": release_id,
                "epic_key": epic_key,
                "channel": target_channel,
                "messages_sent": result.get("messages_sent", 0),
                "tables": [t for t in result.get("tables", [])],
            }

        raise HTTPException(status_code=500, detail=f"Failed to send notification: {result.get('error')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error sending regression status notification: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _fetch_regression_hierarchy_data(epic_key: str) -> dict:
    """
    Fetch regression tracking hierarchy data from the JIRA endpoint.

    Calls the regression-tracking/hierarchy API to get data consistent
    with the Regression Tracking dashboard page.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(
                f"http://localhost:8000/api/jira/regression-tracking/hierarchy?epic_key={epic_key}"
            )

            if response.status_code == 200:
                data = response.json()
                overall = data.get("overall_summary", {})
                logger.info(
                    "Fetched regression hierarchy for %s: total=%d, done=%d, in_progress=%d, blocked=%d",
                    epic_key,
                    overall.get("total", 0),
                    overall.get("done", 0),
                    overall.get("in_progress", 0),
                    overall.get("blocked", 0),
                )
                return data
            else:
                logger.error(
                    "Failed to fetch regression hierarchy: HTTP %s - %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

    except httpx.TimeoutException:
        logger.error("Timeout fetching regression hierarchy for %s", epic_key)
        return None
    except Exception as e:
        logger.error("Error fetching regression hierarchy: %s", e, exc_info=True)
        return None


async def _fetch_release_readiness_data(release_id: str) -> dict:
    """
    Fetch release readiness data for notification.

    Calls the release-readiness API endpoint to get consistent data
    with the dashboard. Also fetches customer escalation count.
    """
    import urllib.parse

    import httpx

    try:
        # Note: Using httpx.AsyncClient for local HTTP call - verify not needed for HTTP
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.get(
                f"http://localhost:8000/api/jira/release-readiness?release={release_id}&refresh=true"
            )

            if response.status_code == 200:
                data = response.json()
                summary = data.get("summary", {})
                total_stories = summary.get("total_bc_stories", 0)
                total_bugs = summary.get("total_bc_bugs", 0)
                total_open = summary.get("total_fb_issues", 0)
                components = list(data.get("componentsData", {}).keys())

                logger.info(
                    "Fetched release readiness for %s: stories=%d, bugs=%d, total_open=%d, components=%s",
                    release_id,
                    total_stories,
                    total_bugs,
                    total_open,
                    components,
                )

                # Warn if data looks empty (might indicate JIRA fetch issue)
                if total_open == 0 and not components:
                    logger.warning("Release readiness data for %s appears empty - JIRA may have failed", release_id)

                # Fetch customer escalation count for this release
                try:
                    from services.jira_client import get_jira_client

                    jira = get_jira_client()
                    if jira.is_configured():
                        release_num = release_id.replace("R", "").replace("r", "").strip()
                        fix_version = f"{release_num}.0.0"
                        escalation_jql = (
                            f'component = "NS Client (NSC)" AND resolution = Unresolved '
                            f"AND project = Engineering AND issuetype in (Escalation) "
                            f'AND "Type of Escalation[Dropdown]" in (Customer) '
                            f"AND fixVersion IN ({fix_version})"
                        )
                        esc_issues = await jira.search_issues(
                            escalation_jql, max_results=500, fetch_all=True, fields=["key"]
                        )
                        data["escalation_count"] = len(esc_issues) if esc_issues else 0
                        data["escalation_jira_url"] = (
                            "https://your-org.atlassian.net/issues/?jql=" + urllib.parse.quote(escalation_jql)
                        )
                        logger.info("Customer escalations for %s: %d open", release_id, data["escalation_count"])
                except Exception as esc_err:
                    logger.warning("Could not fetch escalation count: %s", esc_err)
                    data["escalation_count"] = 0

                # Fetch IRR milestone data for "still open" items that missed IRR deadline
                try:
                    irr_response = await client.get(
                        f"http://localhost:8000/api/jira/milestone/irr?release={release_id}"
                    )
                    if irr_response.status_code == 200:
                        irr_data = irr_response.json()
                        irr_summary = irr_data.get("summary", {})
                        data["irr_still_open"] = irr_summary.get("stillOpen", 0)
                        data["irr_total_missed"] = irr_summary.get("totalMissed", 0)
                        data["irr_on_time_rate"] = irr_summary.get("onTimePercentage", 0)
                        data["irr_issues"] = irr_data.get("issues", [])
                        logger.info(
                            "IRR milestone for %s: still_open=%d, total_missed=%d",
                            release_id,
                            data["irr_still_open"],
                            data["irr_total_missed"],
                        )
                except Exception as irr_err:
                    logger.warning("Could not fetch IRR milestone data: %s", irr_err)
                    data["irr_still_open"] = 0

                return data
            else:
                logger.error(
                    "Failed to fetch release readiness data: HTTP %s - %s", response.status_code, response.text[:200]
                )
                return None

    except httpx.TimeoutException:
        logger.error("Timeout fetching release readiness data for %s", release_id)
        return None
    except Exception as e:
        logger.error("Error fetching release readiness data: %s", e, exc_info=True)
        return None


@router.get("/scheduler/status")
async def get_slack_scheduler_status():
    """
    Get status of the scheduled Slack notification service.

    PURPOSE:
        Returns information about the automatic daily notification
        scheduler including next run time and configuration.

    WHEN TO USE:
        - Checking if scheduler is running
        - Viewing next scheduled notification time
        - Debugging scheduler issues

    RETURNS:
        {
            "enabled": true,
            "running": true,
            "schedule_time": "09:00",
            "timezone": "America/Los_Angeles",
            "next_run": "2026-02-04T09:00:00",
            "time_until_next": "12h 30m",
            "last_notification_date": "2026-02-03"
        }
    """
    return get_scheduler_status()


@router.post("/scheduler/trigger")
async def trigger_slack_notification():
    """
    Manually trigger a Slack notification (for testing).

    This sends the release readiness notification immediately,
    regardless of the schedule.

    Returns:
        - success: Whether the notification was sent
        - message: Status message
        - timestamp: When the trigger was executed
    """
    result = await trigger_notification_now()
    return result


# =============================================================================
# On-Call Notification Endpoints
# =============================================================================


@router.get("/oncall-reminder/status")
async def get_oncall_reminder_status():
    """
    Get status of the on-call reminder notification scheduler.

    PURPOSE:
        Returns information about the automatic on-call reminder
        scheduler including configuration and notification history.

    WHEN TO USE:
        - Checking if on-call reminders are enabled
        - Viewing reminder configuration (days before, time)
        - Debugging reminder issues

    RETURNS:
        {
            "enabled": true,
            "running": true,
            "reminder_days": 4,
            "reminder_time": "09:00 Asia/Kolkata",
            "timezone": "Asia/Kolkata",
            "notifications_sent": 15,
            "fallback_channel": "#oncall-reminders"
        }
    """
    if not _oncall_scheduler_available:
        return {
            "enabled": False,
            "error": "On-call notification scheduler module not available",
        }

    return get_oncall_notification_status()


class OnCallReminderPreviewRequest(BaseModel):
    """Request model for on-call reminder preview."""

    days_ahead: Optional[int] = None


@router.post("/oncall-reminder/preview")
async def preview_oncall_reminders_endpoint(request: OnCallReminderPreviewRequest = Body(default=None)):
    """
    Preview upcoming on-call reminders without sending them.

    PURPOSE:
        Shows who would receive on-call reminders based on upcoming
        rotations. Useful for testing and verification.

    WHEN TO USE:
        - Testing the on-call reminder logic
        - Checking who's up next for on-call
        - Verifying OpsGenie integration

    REQUEST BODY:
        {
            "days_ahead": 4  # Optional - days to look ahead (default: configured reminder days)
        }

    RETURNS:
        {
            "days_ahead": 4,
            "upcoming_count": 3,
            "upcoming": [
                {
                    "name": "John Doe",
                    "email": "jdoe@your-company.com",
                    "slack": "jdoe",
                    "schedule_type": "primary",
                    "schedule_name": "Engineer On-Call",
                    "region": "IST",
                    "week_start": "2026-04-28",
                    "week_end": "2026-05-04",
                    "already_notified": false
                }
            ],
            "current_time": "2026-04-24 09:00:00 IST"
        }
    """
    if not _oncall_scheduler_available:
        raise HTTPException(
            status_code=503,
            detail="On-call notification scheduler module not available",
        )

    days = request.days_ahead if request else None
    return await preview_oncall_reminders(days_ahead=days)


class OnCallReminderTriggerRequest(BaseModel):
    """Request model for triggering on-call reminders."""

    days_ahead: Optional[int] = None
    channel: Optional[str] = None
    schedules: Optional[List[str]] = None


@router.post("/oncall-reminder/trigger")
async def trigger_oncall_reminders_endpoint(request: OnCallReminderTriggerRequest = Body(default=None)):
    """
    Manually trigger on-call reminder notifications.

    PURPOSE:
        Sends on-call reminder notifications immediately, regardless
        of the schedule. Useful for testing or urgent reminders.

    WHEN TO USE:
        - Testing on-call reminder notifications
        - Sending immediate reminders before a rotation
        - Debugging notification delivery

    REQUEST BODY:
        {
            "days_ahead": 4,           # Optional - override reminder days (default: 4)
            "channel": "YOUR_SLACK_CHANNEL_ID",  # Optional - fallback channel for notifications
            "schedules": ["primary"]   # Optional - filter by schedule type (primary, managers, backend)
        }

    RETURNS:
        {
            "success": true,
            "triggered_at": "2026-04-24 09:00:00 IST",
            "reminder_days": 4,
            "channel": "YOUR_SLACK_CHANNEL_ID",
            "schedules": ["primary"],
            "sent": 2,
            "skipped": 1
        }

    NOTES:
        - Notifications are tracked to avoid duplicates
        - Same person won't receive multiple reminders for the same rotation
        - Use /oncall-reminder/preview to see what would be sent
    """
    if not _oncall_scheduler_available:
        raise HTTPException(
            status_code=503,
            detail="On-call notification scheduler module not available",
        )

    days = request.days_ahead if request else None
    channel = request.channel if request else None
    schedules = request.schedules if request else None
    return await trigger_oncall_reminders_now(days_ahead=days, channel=channel, schedules=schedules)

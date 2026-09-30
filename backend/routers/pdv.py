"""
PDV (Post-Deployment Validation) Router
========================================

Endpoints for fetching PDV status from YourCompany Insights Platform Query Service API.
Shows deployment status for staging, preprod, and prod days (Day 1-4).

API: /ip_queryservice/v1/releasemgmt/pdv_runs

Endpoints:
    - GET /api/pdv/status - Get token/connection status
    - GET /api/pdv/token-info - Get detailed token information
    - GET /api/pdv/release/{version} - Get PDV status for all days
    - GET /api/pdv/release/{version}/{day} - Get PDV status for specific day
    - GET /api/pdv/milestone-status/{release_id} - Main endpoint for frontend
    - POST /api/pdv/refresh-token - Get token refresh instructions
    - POST /api/pdv/check-changes/{release_id} - Check for changes and notify Slack
"""

import logging
from typing import Optional

from config import settings
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.pdv_client import get_pdv_client
from services.pdv_scheduler import check_pdv_status_changes, get_pdv_scheduler_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pdv", tags=["pdv"])

# Default channel for PDV notifications
PDV_SLACK_CHANNEL = getattr(settings, "pdv_slack_channel", None) or "YOUR_SLACK_CHANNEL_ID"


@router.get("/status")
async def get_pdv_status():
    """
    Check PDV connection status and token availability.

    Returns:
        Connection status and token info.
    """
    try:
        client = get_pdv_client()
        token_info = client.get_token_info()

        if token_info.get("is_valid") and token_info.get("has_token"):
            return {
                "connected": True,
                "has_token": True,
                "message": "PDV client ready",
                "token_info": {
                    "expires_at": token_info.get("expires_at"),
                    "expires_in_seconds": token_info.get("expires_in_seconds"),
                    "subject": token_info.get("subject"),
                },
            }
        else:
            return {
                "connected": False,
                "has_token": token_info.get("has_token", False),
                "message": token_info.get("message") or "No valid token. Set INSIGHTS_PLATFORM_TOKEN in .env",
                "is_expired": token_info.get("is_expired", False),
            }

    except Exception as e:
        logger.error("Error checking PDV status: %s", e)
        return {
            "connected": False,
            "has_token": False,
            "message": str(e),
        }


@router.get("/token-info")
async def get_token_info():
    """Get detailed information about the current PDV token."""
    try:
        client = get_pdv_client()
        return {
            "success": True,
            **client.get_token_info(),
        }
    except Exception as e:
        logger.error("Error getting token info: %s", e)
        return {
            "success": False,
            "error": str(e),
        }


@router.get("/release/{version}")
async def get_release_status(version: str):
    """
    Get PDV status for all days of a specific release.

    Args:
        version: Release version (e.g., "136.0")

    Returns:
        Status for each deployment day
    """
    try:
        client = get_pdv_client()
        status = client.get_release_status(version)

        return {
            "success": True,
            **status,
        }

    except Exception as e:
        logger.error("Error fetching release status for %s: %s", version, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/release/{version}/{day}")
async def get_day_status(version: str, day: str):
    """
    Get PDV status for a specific deployment day.

    Args:
        version: Release version (e.g., "136.0")
        day: Day name (e.g., "Day 1", "Day 2", "Day 3", "Day 4")

    Returns:
        Detailed status for the specific day.
    """
    try:
        client = get_pdv_client()

        # Normalize day format
        day_normalized = day.replace("_", " ").title()
        if not day_normalized.startswith("Day"):
            day_normalized = f"Day {day_normalized}"

        status = client.get_day_status(version, day_normalized)

        return {
            "success": True,
            "version": version,
            **status,
        }

    except Exception as e:
        logger.error("Error fetching day status: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/milestone-status/{release_id}")
async def get_milestone_status(release_id: str):
    """
    Get PDV milestone status for release readiness page.

    Maps release IDs (R135, R136) to versions (135.0, 136.0)
    and returns deployment day status for the dashboard.

    Args:
        release_id: Release ID (e.g., "R135", "R136")

    Returns:
        Milestone status for Day 1, Day 2, Day 3, Day 4 deployments
    """
    try:
        # Map release ID to version (R136 -> 136.0)
        version = release_id.upper().replace("R", "") + ".0"

        client = get_pdv_client()
        status = client.get_release_status(version)
        days_status = status.get("days", {})

        # Map to milestone format for dashboard
        milestone_mapping = {
            "staging": "staging",
            "prod day 1": "prod_day1",
            "prod day 2": "prod_day2",
            "prod day 3": "prod_day3",
            "prod day 4": "prod_day4",
        }

        milestones = {}
        for label, key in milestone_mapping.items():
            if label in days_status:
                day_data = days_status[label]
                milestones[key] = {
                    "label": label.replace("_", " ").title(),
                    "status": day_data.get("status", "TODO"),
                    "completion_percent": day_data.get("completion_percent", 0),
                    "summary": day_data.get("summary", {}),
                    "failures_count": len(day_data.get("failures", [])),
                    "components": day_data.get("components", []),
                }
            else:
                milestones[key] = {
                    "label": label.replace("_", " ").title(),
                    "status": "NOT_CONFIGURED",
                    "completion_percent": 0,
                    "summary": {},
                    "failures_count": 0,
                    "components": [],
                }

        return {
            "success": True,
            "release_id": release_id,
            "version": version,
            "fetched_at": status.get("fetched_at"),
            "milestones": milestones,
        }

    except Exception as e:
        logger.error("Error fetching milestone status for %s: %s", release_id, e, exc_info=True)
        return {
            "success": False,
            "release_id": release_id,
            "error": str(e),
            "milestones": {},
        }


@router.post("/refresh-token")
async def refresh_token():
    """
    Get instructions for refreshing the PDV token.

    Token refresh requires manual browser login via your-pdv-serviceauth.
    This endpoint returns instructions and current token status.

    Returns:
        Token status and refresh instructions
    """
    try:
        client = get_pdv_client()
        token_info = client.get_token_info()

        return {
            "success": True,
            "token_valid": token_info.get("is_valid", False),
            "expires_at": token_info.get("expires_at"),
            "expires_in_seconds": token_info.get("expires_in_seconds"),
            "instructions": (
                "Token refresh requires manual browser login. "
                "Run on server: ~/.local/bin/your-pdv-serviceauth or ~/Downloads/dist/your-pdv-serviceauth-darwin-amd64"
            ),
        }

    except Exception as e:
        logger.error("Error checking token: %s", e)
        return {
            "success": False,
            "error": str(e),
            "instructions": "Run your-pdv-serviceauth tool to get a new token",
        }


@router.post("/check-changes/{release_id}")
async def check_and_notify_changes(release_id: str, channel: str = None):
    """
    Check for PDV status changes and send Slack notification if any.

    Call this periodically (e.g., every 5 minutes via cron) to detect
    and notify on PDV status changes.

    Args:
        release_id: Release ID (e.g., "R136")
        channel: Optional Slack channel (defaults to YOUR_SLACK_CHANNEL_ID)

    Returns:
        Dict with changes detected and notification status
    """
    from services.slack_notifications import send_pdv_event_notification

    try:
        version = release_id.upper().replace("R", "") + ".0"
        client = get_pdv_client()

        # Detect changes
        changes = client.detect_status_changes(version)

        if not changes:
            return {
                "success": True,
                "release_id": release_id.upper(),
                "version": version,
                "changes_detected": 0,
                "notification_sent": False,
                "message": "No status changes detected",
            }

        # Send notification
        target_channel = channel or PDV_SLACK_CHANNEL
        result = await send_pdv_event_notification(
            events=changes,
            release_id=release_id.upper(),
            channel=target_channel,
        )

        return {
            "success": result.get("success", False),
            "release_id": release_id.upper(),
            "version": version,
            "changes_detected": len(changes),
            "notification_sent": result.get("success", False),
            "channel": result.get("channel"),
            "changes": changes,
            "message": f"Sent {len(changes)} change(s) to Slack" if result.get("success") else result.get("error"),
        }

    except Exception as e:
        logger.error("Error checking PDV changes for %s: %s", release_id, e, exc_info=True)
        return {
            "success": False,
            "release_id": release_id,
            "error": str(e),
            "changes_detected": 0,
            "notification_sent": False,
        }


class PDVNotifyRequest(BaseModel):
    """Request model for PDV Slack notification."""

    channel: Optional[str] = None


@router.post("/notify/{release_id}")
async def send_pdv_notification(release_id: str, request: PDVNotifyRequest = None):
    """
    Send PDV milestone status to Slack (full summary).

    Args:
        release_id: Release ID (e.g., "R136")
        channel: Optional Slack channel

    Returns:
        Dict with Slack notification result
    """
    from services.slack_notifications import send_pdv_milestone_notification

    try:
        version = release_id.upper().replace("R", "") + ".0"
        client = get_pdv_client()
        status = client.get_release_status(version)

        # Build milestone data
        milestone_mapping = {
            "staging": "staging",
            "prod day 1": "prod_day1",
            "prod day 2": "prod_day2",
            "prod day 3": "prod_day3",
            "prod day 4": "prod_day4",
        }

        milestones = {}
        for label, key in milestone_mapping.items():
            days_status = status.get("days", {})
            if label in days_status:
                day_data = days_status[label]
                milestones[key] = {
                    "label": label.replace("_", " ").title(),
                    "status": day_data.get("status", "TODO"),
                    "completion_percent": day_data.get("completion_percent", 0),
                    "summary": day_data.get("summary", {}),
                    "failures_count": len(day_data.get("failures", [])),
                }
            else:
                milestones[key] = {
                    "label": label.replace("_", " ").title(),
                    "status": "NOT_CONFIGURED",
                    "completion_percent": 0,
                    "summary": {},
                    "failures_count": 0,
                }

        pdv_data = {
            "release_id": release_id.upper(),
            "version": version,
            "milestones": milestones,
            "fetched_at": status.get("fetched_at"),
        }

        # Send notification
        req = request or PDVNotifyRequest()
        target_channel = req.channel or PDV_SLACK_CHANNEL

        result = await send_pdv_milestone_notification(
            pdv_data,
            channel=target_channel,
        )

        return {
            "success": result.get("success", False),
            "release_id": release_id.upper(),
            "message": "PDV status notification sent" if result.get("success") else result.get("error"),
            "channel": result.get("channel"),
        }

    except Exception as e:
        logger.error("Error sending PDV notification for %s: %s", release_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Scheduler Endpoints
# =============================================================================


@router.get("/scheduler/status")
async def get_scheduler_status():
    """
    Get PDV scheduler status.

    Returns current scheduler state including:
    - Whether scheduler is enabled/running
    - Check intervals
    - Monitored releases
    - Last token refresh and status check times
    """
    return get_pdv_scheduler_status()


@router.get("/scheduler/token-status")
async def get_token_status():
    """
    Get current token status for the scheduler.

    Returns whether token is valid and when it expires.
    """
    try:
        client = get_pdv_client()
        token_info = client.get_token_info()

        return {
            "success": True,
            "is_valid": token_info.get("is_valid", False),
            "expires_at": token_info.get("expires_at"),
            "expires_in_seconds": token_info.get("expires_in_seconds"),
            "subject": token_info.get("subject"),
        }
    except Exception as e:
        logger.error("Error getting token status: %s", e)
        return {
            "success": False,
            "error": str(e),
            "is_valid": False,
        }


@router.post("/scheduler/check-changes")
async def trigger_status_check():
    """
    Manually trigger PDV status check for all monitored releases.

    Useful for testing or forcing an immediate status check.
    Returns details about which releases were checked and any changes detected.
    """
    try:
        result = await check_pdv_status_changes()
        return {
            "success": True,
            "result": result,
        }
    except Exception as e:
        logger.error("Error triggering status check: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

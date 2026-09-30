"""
Configuration settings for Agentic Insights Portal Backend

RELEASE CONFIGURATION:
=====================
To add a new release (e.g., R136), update ONLY this file:
1. Add entry to RELEASE_MILESTONES list with:
   - id, name, display_name
   - milestone_id (TestRail milestone)
   - project_id (TestRail project)
   - is_current (True for active release)
   - regression_epics (list of Jira epic keys for regression tracking)
2. Set is_current=True on the new release, is_current=False on old
3. Update CURRENT_RELEASE environment variable in docker-start.sh

The rest of the dashboard will automatically use the new release.
"""

import os
from typing import Dict, List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    app_name: str = "QE Agentic Dashboard"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "your-secret-key-change-in-production"

    # TestRail Configuration
    testrail_url: str = ""
    testrail_username: str = ""
    testrail_api_key: str = ""
    testrail_project_id: int = 38  # NS Client project
    testrail_milestone_id: int = 5319  # M5319 - R135.0.0.0

    # JIRA Configuration
    jira_url: str = ""
    jira_username: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "YOUR_PRODUCT"
    jira_fix_version: str = ""  # e.g., "R 132.0.0.0"
    jira_customer_bugs_project: str = "ENG"  # Project for customer-escalated bugs

    # GitHub Configuration
    github_token: str = ""  # Personal Access Token for private repos (increases rate limit)

    # Google Sheets
    google_service_account_file: str = ""

    # Rancher Configuration - For automatic kubeconfig download
    # Two servers: NPE (your-rancher.example.com) and Prod (rancher.example.com)
    # Tokens can come from env vars or Vault (/your-product-tw/stack/rancher_secret)
    rancher_npe_key: str = ""  # Token for NPE/Staging clusters (qa01, stg01, etc.)
    rancher_prod_key: str = ""  # Token for Production clusters (sjc1, fra2, etc.)
    rancher_kubeconfig_dir: str = ""  # Directory to save kubeconfig files (default: ~/.kube/rancher)

    # Kubernetes API Timeout Configuration
    # Increase these if production clusters are timing out (especially distant regions)
    k8s_connect_timeout: int = 30  # Connection timeout in seconds (default: 30)
    k8s_read_timeout: int = 90  # Read timeout in seconds (default: 90)
    k8s_max_workers: int = 20  # Max parallel API calls (default: 20, reduce if overloading Rancher)

    # Your-Product QE Environment Configuration
    # Fetches from GitHub: your-company-qe/your-product-qe (requires GITHUB_TOKEN)
    # Configs are cached for 24 hours
    use_json_env_config: bool = True  # Use JSON files from your-product-qe for stack discovery

    # Stack Exclusion List - Stacks to exclude from monitoring dashboard
    # Comma-separated list of stack names/patterns to exclude
    excluded_stacks: str = "betaskope,perf01,npe02"

    # OpsGenie Configuration for On-Call Calendar
    opsgenie_api_key: str = ""  # OpsGenie API Key (GenieKey)
    opsgenie_api_url: str = "https://api.opsgenie.com"  # OpsGenie API Base URL
    opsgenie_schedule_name: str = "NSC-Escalation-Oncall-Primary"  # Primary on-call schedule
    opsgenie_manager_schedule_name: str = "NSC-Mangers"  # Manager on-call schedule
    opsgenie_backend_schedule_name: str = "NSC-SRE-Client-Services-schedule"  # Backend on-call schedule
    opsgenie_backend_api_key: str = ""  # Backend schedule API key (if different from main key)

    # PDV (Insights Platform) Configuration
    insights_platform_token: str = ""  # Bearer token for Insights Platform PDV API
    pdv_slack_channel: str = "YOUR_SLACK_CHANNEL_ID"  # Slack channel for PDV notifications

    # Slack Configuration for Release Readiness Notifications
    slack_bot_token: str = ""  # Slack Bot OAuth Token (xoxb-...)
    slack_channel: str = ""  # Slack Channel ID (e.g., C09S89TL917)
    slack_notifications_enabled: bool = True  # Enable/disable Slack notifications

    # Jenkins Configuration
    jenkins_num_builds: int = 10  # Default number of builds to fetch per pipeline

    # CORS Configuration
    cors_origins: str = "*"  # Comma-separated origins or "*" for all

    class Config:  # pylint: disable=too-few-public-methods
        """Pydantic config."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra environment variables


settings = Settings()


# ============ Release & Milestone Configuration ============
# This configuration maps release names to their TestRail milestone IDs
# Update this when new releases are added - no code changes needed!
#
# IMPORTANT: This is the SINGLE SOURCE OF TRUTH for milestone_id.
# No environment variable fallback - configure milestone_id here for each release.

RELEASE_MILESTONES: List[Dict[str, any]] = [
    {
        "id": "R140",
        "name": "R140",
        "display_name": "R140",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "active",
        "is_current": True,
        "description": "R140.0.0.0 Release - Current",
        "release_lead": "Shuangjiang Li",
        "regression_epics": [],  # Add your JIRA epic keys here
        # "slack_channel": "C0BDJ5B0KAL",
    },
    {   
        "id": "R139",
        "name": "R139",
        "display_name": "R139",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R139.0.0.0 Release - Completed",
        "release_lead": "Frank Hu",
        "regression_epics": [],  # Add your JIRA epic keys here
    },
    {
        "id": "R138",
        "name": "R138",
        "display_name": "R138",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R138.0.0.0 Release - Completed",
        "release_lead": "Rajesh Bhat",
        "regression_epics": [],  # Add your JIRA epic keys here
    },
    {
        "id": "R137",
        "name": "R137",
        "display_name": "R137",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R137.0.0.0 Release - Completed",
        "release_lead": "Vivek Sharma",
        "regression_epics": [],  # Add your JIRA epic keys here
        "slack_channel": "YOUR_SLACK_CHANNEL_ID",
    },
    {
        "id": "R136",
        "name": "R136",
        "display_name": "R136",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R136.0.0.0 Release - Completed",
        "release_lead": "Frank Hu",
        "regression_epics": [],  # Add your JIRA epic keys here
    },
    {
        "id": "R135",
        "name": "R135",
        "display_name": "R135",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R135.0.0.0 Release - Completed",
        "release_lead": "Rajesh Raman",
        "regression_epics": []  # Add your JIRA epic keys here,  # R135 regression tracking epic
    },
    {
        "id": "R134",
        "name": "R134",
        "display_name": "R134",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R134.0.0.0 Release",
        "release_lead": "Shuangjiang Li",
        "regression_epics": []  # Add your JIRA epic keys here,  # R134 regression tracking epic
    },
    {
        "id": "R133",
        "name": "R133",
        "display_name": "R133",
        "milestone_id": 0,  # Set to your TestRail milestone ID
        "project_id": 0,  # Set to your TestRail project ID
        "status": "completed",
        "is_current": False,
        "description": "R133.0.0.0 Release",
        "release_lead": "",
        "regression_epics": [],  # Add R133 epic keys when available
    },
]


def get_milestone_id(release_id: str) -> int | None:
    """Get TestRail milestone ID for a given release.

    Returns None if no milestone is configured for the release.
    """
    for release in RELEASE_MILESTONES:
        if release["id"] == release_id:
            return release["milestone_id"]  # May be None if not configured
    # Default to current release's milestone
    current = get_current_release()
    return current["milestone_id"] if current else None


def get_project_id(release_id: str) -> int:
    """Get TestRail project ID for a given release"""
    for release in RELEASE_MILESTONES:
        if release["id"] == release_id:
            return release["project_id"]
    # Default to NS Client
    return 38


def get_current_release() -> Dict:
    """Get the current active release"""
    for release in RELEASE_MILESTONES:
        if release.get("is_current"):
            return release
    # Fallback to first release
    return RELEASE_MILESTONES[0] if RELEASE_MILESTONES else None


def get_release_lead(release_id: str) -> str:
    """Get the release lead for a given release ID"""
    for release in RELEASE_MILESTONES:
        if release["id"] == release_id:
            return release.get("release_lead", "")
    return ""


def get_regression_epics(release_id: str) -> List[str]:
    """Get Jira regression epic keys for a given release ID"""
    for release in RELEASE_MILESTONES:
        if release["id"] == release_id:
            return release.get("regression_epics", [])
    return []


def get_slack_channel(release_id: str) -> str:
    """Get Slack channel ID for a given release ID.

    Returns the release-specific channel if configured, empty string otherwise.
    """
    for release in RELEASE_MILESTONES:
        if release["id"] == release_id:
            return release.get("slack_channel", "")
    return ""


def get_default_release_id() -> str:
    """
    Get the default release ID from environment or config.
    Use this instead of hardcoding release IDs throughout the codebase.

    Priority:
    1. CURRENT_RELEASE environment variable (runtime override)
    2. Release marked as is_current=True in RELEASE_MILESTONES
    3. First release in RELEASE_MILESTONES

    Raises:
        ValueError: If no release is configured anywhere
    """
    # 1. Check environment variable first (allows runtime override)
    env_release = os.getenv("CURRENT_RELEASE")
    if env_release:
        return env_release

    # 2. Fall back to config's current release
    current = get_current_release()
    if current:
        return current["id"]

    # 3. Fall back to first release in list
    if RELEASE_MILESTONES:
        return RELEASE_MILESTONES[0]["id"]

    raise ValueError(
        "No release configured! Set CURRENT_RELEASE environment variable "
        "or add releases to RELEASE_MILESTONES in backend/config.py"
    )


# Export the default release ID for easy imports
DEFAULT_RELEASE_ID = get_default_release_id()


# ============ Release Dates Configuration ============
# Release dates are sourced from the Release Calendar PDF
# Parsed by services/release_calendar_parser.py
#
# These dates are used by:
# - GitHub: Finding commits after branch cut
# - JIRA: Milestone tracking (stories/bugs by IRR, branch cut, final build)
# - Slack: Release notifications
# - Release Readiness: View Timeline

# Cache for release dates (loaded from PDF or fallback)
_release_dates_cache: Dict[str, Dict[str, str]] = {}


def _convert_date_format(date_str: str) -> str:
    """Convert date from DD-Mon-YYYY to YYYY-MM-DD format."""
    from datetime import datetime as dt

    if not date_str or date_str == "-":
        return ""
    try:
        parsed = dt.strptime(date_str, "%d-%b-%Y")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _calculate_irr_date(branch_cut_str: str) -> str:
    """Calculate IRR as 1 week before branch cut."""
    from datetime import datetime as dt
    from datetime import timedelta

    if not branch_cut_str:
        return ""
    try:
        bc_date = dt.strptime(branch_cut_str, "%Y-%m-%d")
        irr_date = bc_date - timedelta(days=7)
        return irr_date.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _load_release_dates_from_calendar() -> Dict[str, Dict[str, str]]:
    """
    Load release dates from the Release Calendar (parsed PDF + DATE_CORRECTIONS).

    Uses get_release_calendar_data() which:
    1. Parses the PDF at backend/data/release_calendar.pdf
    2. Applies DATE_CORRECTIONS for any corrections or missing releases
    3. Calculates derived dates (IRR, deploy dates, etc.)

    This is the single source of truth for release milestone dates.
    """
    import logging

    logger = logging.getLogger(__name__)

    global _release_dates_cache

    if _release_dates_cache:
        return _release_dates_cache

    # Load dates from release calendar (PDF + corrections)
    try:
        from services.release_calendar_parser import get_release_calendar_data

        data = get_release_calendar_data()

        for release in data.get("releases", []):
            name = release.get("name", "")
            # Extract base release ID (e.g., "R134" from "R134.0")
            base_id = name.split(".")[0] if "." in name else name

            milestones = release.get("milestones", {})

            # Only use .0 (major) releases for current release determination
            if name.endswith(".0"):
                _release_dates_cache[base_id] = {
                    "irr": _convert_date_format(milestones.get("IRR", "")),
                    "branch_cut": _convert_date_format(milestones.get("Branch Cut - EP", "")),
                    "final_build": _convert_date_format(milestones.get("Final Build - EP", "")),
                    "signoff_stg": _convert_date_format(milestones.get("Signoff STG/FedAlpha - ENG", "")),
                    "day1_deploy": _convert_date_format(milestones.get("Deploy Prod Day 1", "")),
                    "day2_deploy": _convert_date_format(milestones.get("Deploy Prod Day 2", "")),
                    "day3_deploy": _convert_date_format(milestones.get("Deploy Prod Day 3", "")),
                    "day4_deploy": _convert_date_format(milestones.get("Deploy Prod Day 4", "")),
                    # Keep "release" as alias for day4_deploy for backward compatibility
                    "release": _convert_date_format(milestones.get("Deploy Prod Day 4", "")),
                }
                logger.debug(
                    f"Loaded dates for {base_id}: final_build={milestones.get('Final Build - EP', '')}, "
                    f"day4_deploy={milestones.get('Deploy Prod Day 4', '')}"
                )

        logger.info(f"Loaded release dates for {len(_release_dates_cache)} releases from release calendar")
    except Exception as e:
        logger.error(f"Failed to load release dates from release calendar: {e}")

    return _release_dates_cache


def get_release_dates(release_id: str) -> Dict[str, str]:
    """
    Get key milestone dates for a given release.

    Data is sourced from the Release Calendar PDF.
    Used by GitHub, JIRA, Slack features for milestone tracking.

    Args:
        release_id: Release ID like "R134" or "R135"

    Returns:
        Dict with keys: irr, branch_cut, final_build, day1_deploy, day2_deploy,
        day3_deploy, day4_deploy, release (alias for day4_deploy)
        Returns empty dict if release not found.
    """
    dates = _load_release_dates_from_calendar()
    return dates.get(release_id, {})


def get_active_releases() -> List[str]:
    """
    Get list of releases that are currently in-progress based on their timeline ONLY.

    A release is considered active if:
    - Today is between (IRR - 7 days) and Day 4 Deploy date
    - Falls back to (final_build + 7 days) if Day 4 Deploy is not available

    This is purely timeline-based detection using dates from:
    1. Release Calendar PDF parser
    2. DATE_CORRECTIONS in release_calendar_parser.py

    Returns:
        List of release IDs that are currently in-progress.
    """
    import logging
    from datetime import datetime, timedelta

    logger = logging.getLogger(__name__)
    active = set()
    today = datetime.now().date()

    # Only use timeline-based detection - no is_current fallback
    all_dates = _load_release_dates_from_calendar()
    logger.info("Checking active releases based on timeline (today=%s)", today)
    logger.debug("Loaded release dates: %s", all_dates)

    for release_id, dates in all_dates.items():
        try:
            # Parse dates
            irr_str = dates.get("irr", "")
            final_build_str = dates.get("final_build", "")

            if not irr_str or not final_build_str:
                logger.debug(
                    "Skipping %s - missing dates (irr=%s, final_build=%s)", release_id, irr_str, final_build_str
                )
                continue

            irr_date = datetime.strptime(irr_str, "%Y-%m-%d").date()
            final_build_date = datetime.strptime(final_build_str, "%Y-%m-%d").date()

            # Release is active from 7 days before IRR until Day 4 Deploy
            start_date = irr_date - timedelta(days=7)

            # Use Day 4 Deploy as end date if available, otherwise fall back to final_build + 14 days
            day4_str = dates.get("day4_deploy", "") or dates.get("release", "")
            if day4_str:
                try:
                    end_date = datetime.strptime(day4_str, "%Y-%m-%d").date()
                except ValueError:
                    end_date = final_build_date + timedelta(days=14)
            else:
                # Fallback: final_build + 14 days (full deployment window when dates unavailable)
                end_date = final_build_date + timedelta(days=14)

            if start_date <= today <= end_date:
                active.add(release_id)
                logger.info(
                    "Release %s is ACTIVE (IRR=%s, End=%s, window: %s to %s)",
                    release_id,
                    irr_str,
                    day4_str or f"FB+7 ({end_date})",
                    start_date,
                    end_date,
                )
            else:
                logger.debug(
                    "Release %s is NOT active (today=%s not in %s to %s)", release_id, today, start_date, end_date
                )

        except (ValueError, TypeError) as e:
            logger.warning("Error parsing dates for %s: %s", release_id, e)
            continue

    # Convert to list and sort by release number descending (newest first)
    active_list = list(active)
    active_list.sort(key=lambda x: int(x.replace("R", "")), reverse=True)

    logger.info("Active releases (timeline-based): %s", active_list if active_list else "NONE")
    return active_list


def is_release_completed(release_id: str) -> bool:
    """
    Check if a release is completed (fully deployed to production).

    A release is considered completed if today is past the Day 4 Deploy date.
    Falls back to final_build + 7 days if Day 4 Deploy is not available.

    Args:
        release_id: Release identifier (e.g., "R134")

    Returns:
        True if the release is completed, False otherwise.
    """
    from datetime import datetime, timedelta

    today = datetime.now().date()
    dates = get_release_dates(release_id)

    if not dates:
        return False

    # Use Day 4 Deploy date if available
    day4_str = dates.get("day4_deploy", "") or dates.get("release", "")
    if day4_str:
        try:
            day4_date = datetime.strptime(day4_str, "%Y-%m-%d").date()
            return today > day4_date
        except ValueError:
            pass

    # Fallback to final_build + 14 days (full deployment window)
    final_build_str = dates.get("final_build", "")
    if not final_build_str:
        return False

    try:
        final_build_date = datetime.strptime(final_build_str, "%Y-%m-%d").date()
        completion_date = final_build_date + timedelta(days=14)
        return today > completion_date
    except (ValueError, TypeError):
        return False


def is_regression_notification_active(release_id: str) -> bool:
    """
    Check if regression notifications should be active for a release.

    Regression notifications are active when:
    - Today is >= Branch Cut date
    - Today is < Signoff STG/FedAlpha - ENG date

    This ensures regression status notifications are sent only during the
    regression testing phase of the release cycle.

    Args:
        release_id: Release identifier (e.g., "R137")

    Returns:
        True if regression notifications should be sent, False otherwise.
    """
    import logging
    from datetime import datetime

    logger = logging.getLogger(__name__)
    today = datetime.now().date()
    dates = get_release_dates(release_id)

    if not dates:
        logger.debug("No dates found for %s - regression notifications disabled", release_id)
        return False

    branch_cut_str = dates.get("branch_cut", "")
    signoff_stg_str = dates.get("signoff_stg", "")

    # Need at least branch_cut to determine start
    if not branch_cut_str:
        logger.debug("No branch_cut date for %s - regression notifications disabled", release_id)
        return False

    try:
        branch_cut_date = datetime.strptime(branch_cut_str, "%Y-%m-%d").date()

        # Check if we're past branch cut
        if today < branch_cut_date:
            logger.debug(
                "Release %s: before branch cut (%s) - regression notifications disabled",
                release_id,
                branch_cut_str,
            )
            return False

        # Check if we're before signoff (if date is available)
        if signoff_stg_str:
            signoff_date = datetime.strptime(signoff_stg_str, "%Y-%m-%d").date()
            if today >= signoff_date:
                logger.debug(
                    "Release %s: past signoff STG (%s) - regression notifications disabled",
                    release_id,
                    signoff_stg_str,
                )
                return False

        logger.info(
            "Release %s: regression notifications ACTIVE (branch_cut=%s, signoff_stg=%s, today=%s)",
            release_id,
            branch_cut_str,
            signoff_stg_str or "N/A",
            today,
        )
        return True

    except (ValueError, TypeError) as e:
        logger.warning("Error parsing dates for %s: %s", release_id, e)
        return False


# ============ Google Sheets Configuration ============
# Centralized Google Sheets spreadsheet IDs
# Update these when sheets change - no code changes needed!

GOOGLE_SHEETS_CONFIG: Dict[str, Dict[str, str]] = {
    "release_calendar": {
        "spreadsheet_id": "1FWX7bbIO800cv3B8FSc1aIH-CQGCEOnyojXP52UiBjQ",
        "sheet_name": "Release Squad Schedule",
        "description": "Release calendar with deploy dates (PROD Deploy dates)",
        "url": "https://docs.google.com/spreadsheets/d/1FWX7bbIO800cv3B8FSc1aIH-CQGCEOnyojXP52UiBjQ/edit",
    },
    "weekly_status": {
        "spreadsheet_id": "1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y",
        "sheet_name": "WEEKLY STATUS REPORT",
        "description": "Weekly QA status reports and metrics",
        "url": (  # noqa: E501
            "https://docs.google.com/spreadsheets/d/1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y"
            "/edit?gid=1674899298#gid=1674899298"
        ),
    },
    "manual_execution": {
        "spreadsheet_id": "1HjMBaR3mkcVtnEEyE5vdUDDlwZbhEGfk275MIvXD8AM",
        "sheet_name": "Manual Test Execution",
        "description": "Manual test execution tracking",
        "url": "https://docs.google.com/spreadsheets/d/1HjMBaR3mkcVtnEEyE5vdUDDlwZbhEGfk275MIvXD8AM/edit",
    },
    "feature_owners": {
        "spreadsheet_id": "1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y",
        "sheet_name": "Feature Owners",
        "description": "Feature ownership mapping",
        "url": "https://docs.google.com/spreadsheets/d/1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y/edit",
    },
    "release_tracking": {
        "spreadsheet_id": "1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y",
        "sheet_name": "Release Tracking",
        "description": "Release progress tracking",
        "url": "https://docs.google.com/spreadsheets/d/1H1mZxZXaCn60CPAFEhXy_a6rVkXyT0t-Gi0yuex2I9Y/edit",
    },
    "nplans": {
        "spreadsheet_id": "1dQAG-RZceHIZJq73mVT8w_R6mTJ2muV9zurUMNr4qrY",
        "sheet_name": "RELEASE QUALITY / REGRESSIONS",
        "sheet_gid": "1674899298",
        "description": "NPLANs/Features planned for releases - Column A has items, Column B has release",
        "url": "https://docs.google.com/spreadsheets/d/1dQAG-RZceHIZJq73mVT8w_R6mTJ2muV9zurUMNr4qrY/edit?gid=1674899298#gid=1674899298",
        "data_range": "A1:J200",  # Start from row 1 to capture headers
    },
}


def get_sheet_config(sheet_type: str) -> Dict[str, str]:
    """Get Google Sheets configuration for a specific sheet type"""
    return GOOGLE_SHEETS_CONFIG.get(sheet_type, {})


def get_sheet_id(sheet_type: str) -> str:
    """Get spreadsheet ID for a specific sheet type"""
    config = get_sheet_config(sheet_type)
    return config.get("spreadsheet_id", "")


def get_sheet_name(sheet_type: str) -> str:
    """Get sheet name for a specific sheet type"""
    config = get_sheet_config(sheet_type)
    return config.get("sheet_name", "")


# ============ GitHub Repository Configuration ============
# Repositories to track for commit history after branch cut
# {release}: release branch naming pattern (e.g., "Release134", "Release{version}")
# {version}: just the version number (e.g., "134")
# Use "master" or "develop" for repos that don't have release branches

GITHUB_REPOS: Dict[str, Dict[str, any]] = {
    "client": {
        "owner": "your-org",
        "repo": "client",
        "branch_pattern": "Release{version}",  # e.g., Release134
        "description": "NS Client Main Repository",
        "category": "core",
    },
    "service": {
        "owner": "your-org",
        "repo": "service",
        "branch_pattern": "Release{version}",  # e.g., Release134
        "description": "Backend Services Repository",
        "category": "core",
    },
    "device-classification": {
        "owner": "your-org",
        "repo": "device-classification",
        "branch_pattern": "master",  # Always master
        "description": "Device Classification Service",
        "category": "services",
    },
    "enrollment-service": {
        "owner": "your-org",
        "repo": "enrollment-service",
        "branch_pattern": "develop",  # Always develop
        "description": "Enrollment Service",
        "category": "services",
    },
    "client-oppy": {
        "owner": "your-org",
        "repo": "client-oppy",
        "branch_pattern": "develop",
        "description": "Client Oppy",
        "category": "services",
    },
    "ns-python-provisionercommon": {
        "owner": "your-org",
        "repo": "ns-python-provisionercommon",
        "branch_pattern": "develop",
        "description": "NS Python Provisioner Common",
        "category": "services",
    },
    "otp": {
        "owner": "your-org",
        "repo": "otp",
        "branch_pattern": "main",
        "description": "OTP Service",
        "category": "services",
    },
    "downloader": {
        "owner": "your-org",
        "repo": "downloader",
        "branch_pattern": "develop",
        "description": "Downloader Service",
        "category": "services",
    },
}


def get_github_repos() -> Dict[str, Dict]:
    """Get all configured GitHub repositories"""
    return GITHUB_REPOS


def get_repo_branch(repo_key: str, release_id: str) -> str:
    """
    Get the branch name for a repo based on release.

    Args:
        repo_key: Key from GITHUB_REPOS (e.g., "client")
        release_id: Release ID (e.g., "R134")

    Returns:
        Branch name (e.g., "Release134", "master", "develop")
    """
    repo = GITHUB_REPOS.get(repo_key)
    if not repo:
        return "master"

    pattern = repo.get("branch_pattern", "master")
    version = release_id.replace("R", "")  # R134 -> 134

    return pattern.replace("{version}", version).replace("{release}", release_id)


# =============================================================================
# COMPONENT TO TEST AREA MAPPING
# =============================================================================
# Maps file path patterns to likely impacted test areas
# Used by commit analyzer to predict test impact

COMPONENT_TEST_MAPPING = {
    # API and Backend
    "api/": ["API Tests", "Integration Tests", "Backend PDV"],
    "backend/": ["Backend Tests", "Integration Tests", "Backend PDV"],
    "server/": ["Server Tests", "Integration Tests", "Backend PDV"],
    "service/": ["Service Tests", "Integration Tests", "Backend PDV"],
    "controllers/": ["API Tests", "Integration Tests"],
    "routes/": ["API Tests", "E2E Tests"],
    "handlers/": ["API Tests", "Integration Tests"],
    # Authentication & Security
    "auth/": ["Authentication Tests", "Security Tests", "SSO Tests"],
    "security/": ["Security Tests", "Penetration Tests"],
    "oauth/": ["OAuth Tests", "SSO Tests", "Authentication Tests"],
    "saml/": ["SAML Tests", "SSO Tests", "Authentication Tests"],
    "login/": ["Login Tests", "Authentication Tests", "E2E Tests"],
    # UI and Frontend
    "ui/": ["UI Tests", "E2E Tests", "Visual Regression"],
    "frontend/": ["Frontend Tests", "UI Tests", "E2E Tests"],
    "components/": ["Component Tests", "UI Tests", "Snapshot Tests"],
    "views/": ["UI Tests", "E2E Tests"],
    "pages/": ["Page Tests", "E2E Tests", "UI Tests"],
    "styles/": ["Visual Regression", "UI Tests"],
    "css/": ["Visual Regression", "UI Tests"],
    # Database and Data
    "database/": ["Database Tests", "Migration Tests", "Data Integrity"],
    "db/": ["Database Tests", "Migration Tests"],
    "models/": ["Model Tests", "Database Tests", "Unit Tests"],
    "schema/": ["Schema Tests", "Migration Tests", "API Tests"],
    "migrations/": ["Migration Tests", "Database Tests"],
    "data/": ["Data Tests", "Integration Tests"],
    # Configuration
    "config/": ["Configuration Tests", "Environment Tests"],
    "settings/": ["Settings Tests", "Configuration Tests"],
    "env/": ["Environment Tests", "Configuration Tests"],
    # Core/Shared
    "core/": ["Core Tests", "Unit Tests", "Integration Tests"],
    "common/": ["Common Tests", "Unit Tests"],
    "shared/": ["Shared Tests", "Unit Tests"],
    "utils/": ["Utility Tests", "Unit Tests"],
    "helpers/": ["Helper Tests", "Unit Tests"],
    "lib/": ["Library Tests", "Unit Tests"],
    # Testing
    "test/": ["Test Infrastructure", "CI/CD"],
    "tests/": ["Test Infrastructure", "CI/CD"],
    "spec/": ["Test Infrastructure", "CI/CD"],
    "__tests__/": ["Test Infrastructure", "CI/CD"],
    # Build and Deploy
    "docker/": ["Docker Tests", "Deployment Tests", "CI/CD"],
    "kubernetes/": ["K8s Tests", "Deployment Tests", "Infrastructure"],
    "k8s/": ["K8s Tests", "Deployment Tests", "Infrastructure"],
    "ci/": ["CI/CD Pipeline", "Build Tests"],
    ".github/": ["CI/CD Pipeline", "GitHub Actions"],
    "scripts/": ["Script Tests", "Automation Tests"],
    # Networking
    "network/": ["Network Tests", "Connectivity Tests"],
    "proxy/": ["Proxy Tests", "Network Tests"],
    "tunnel/": ["Tunnel Tests", "Steering Tests", "Network Tests"],
    "steering/": ["Steering Tests", "Traffic Tests", "PDV Tests"],
    # Client-specific (Your-Product)
    "npa/": ["NPA Tests", "Private Access Tests", "Steering Tests"],
    "client/": ["Client Tests", "Agent Tests", "E2E Tests"],
    "agent/": ["Agent Tests", "Client Tests", "Installation Tests"],
    "installer/": ["Installation Tests", "Upgrade Tests", "Client Tests"],
    "provisioning/": ["Provisioning Tests", "Backend PDV", "Enrollment Tests"],
    "enrollment/": ["Enrollment Tests", "Provisioning Tests", "E2E Tests"],
}


def get_test_areas_for_file(filepath: str) -> List[str]:
    """
    Get list of test areas that might be impacted by a file change.

    Args:
        filepath: Path of the changed file

    Returns:
        List of test area names
    """
    filepath_lower = filepath.lower()
    test_areas = set()

    for pattern, areas in COMPONENT_TEST_MAPPING.items():
        if pattern in filepath_lower:
            test_areas.update(areas)

    # If no specific match, return generic areas
    if not test_areas:
        # Determine by file extension
        if filepath_lower.endswith((".py", ".go", ".java", ".cs")):
            test_areas.add("Unit Tests")
        elif filepath_lower.endswith((".js", ".ts", ".jsx", ".tsx")):
            test_areas.add("Frontend Tests")
        elif filepath_lower.endswith((".sql",)):
            test_areas.add("Database Tests")
        elif filepath_lower.endswith((".yml", ".yaml", ".json")):
            test_areas.add("Configuration Tests")
        else:
            test_areas.add("General Tests")

    return sorted(list(test_areas))


# =============================================================================
# KUBERNETES STACK MONITORING CONFIGURATION
# =============================================================================
# Stacks are auto-discovered from your-product-qe JSON files (fetched from GitHub).
#
# SOURCE: your-company-qe/your-product-qe repository
#   - your-product-qe/environment/*.json (NPE/staging stacks)
#   - your-product-qe/environment/pe/*.json (Production stacks)
#
# KUBECONFIG AUTO-DOWNLOAD:
#   - Kubeconfigs are auto-downloaded from Rancher to ~/.kube/rancher/
#   - Requires RANCHER_NPE_KEY and/or RANCHER_PROD_KEY tokens
#   - Files are matched by kubeconfig_filename from JSON configs
#
# REQUIREMENTS:
#   - GITHUB_TOKEN: Required for private repo access
#   - RANCHER_NPE_KEY/RANCHER_PROD_KEY: For kubeconfig auto-download
#   - Configs are cached for 24 hours

# Cache for discovered stacks
_kubernetes_stacks_cache: Dict[str, Dict[str, str]] = None


def _load_stacks_from_json() -> Dict[str, Dict[str, str]]:
    """
    Load Kubernetes stacks from your-product-qe JSON configuration files.

    Fetches from GitHub: your-company-qe/your-product-qe repository
    Requires GITHUB_TOKEN for private repo access.

    Returns:
        Dict of stacks discovered from JSON files
    """
    json_stacks = {}

    # Only load if enabled
    if not settings.use_json_env_config:
        return json_stacks

    try:
        from services.environment_config import get_all_environments

        for env_config in get_all_environments():
            # Skip environments without kubeconfig
            if not env_config.kubeconfig_filename:
                continue

            stack_id = env_config.stack_name

            # Handle PE stacks - use the location name (e.g., sjc1, fra2)
            if env_config.name.startswith("pe-"):
                stack_id = env_config.name.replace("pe-", "")

            # Handle naming conflicts (e.g., stg01 vs stg01-mplegacy)
            if stack_id in json_stacks and env_config.name != stack_id:
                stack_id = env_config.name.replace("-", "_")

            stack_config = env_config.to_stack_config()

            # Add kubeconfig filename for Rancher matching
            stack_config["kubeconfig_filename"] = env_config.kubeconfig_filename

            # Set kubeconfig_path to look in ~/.kube/rancher/ directory
            # This is where Rancher kubeconfigs are auto-downloaded
            rancher_kubeconfig_dir = os.path.expanduser("~/.kube/rancher")
            kubeconfig_path = os.path.join(rancher_kubeconfig_dir, env_config.kubeconfig_filename)
            if os.path.exists(kubeconfig_path):
                stack_config["kubeconfig_path"] = kubeconfig_path

            json_stacks[stack_id] = stack_config

        if json_stacks:
            import logging

            logging.getLogger(__name__).info("Loaded %d stacks from your-product-qe JSON configs", len(json_stacks))

    except ImportError:
        # environment_config module not available
        pass
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to load stacks from JSON: %s", e)

    return json_stacks


def get_excluded_stacks() -> List[str]:
    """
    Get list of stack names/patterns to exclude from monitoring.

    Returns:
        List of excluded stack names (lowercase)
    """
    excluded = settings.excluded_stacks.strip()
    if not excluded:
        return []
    return [s.strip().lower() for s in excluded.split(",") if s.strip()]


def is_stack_excluded(stack_id: str) -> bool:
    """
    Check if a stack should be excluded from monitoring.

    Args:
        stack_id: Stack identifier to check

    Returns:
        True if stack should be excluded
    """
    excluded = get_excluded_stacks()
    if not excluded:
        return False

    stack_lower = stack_id.lower()
    for pattern in excluded:
        # Match exact name or if stack_id contains the pattern
        if stack_lower == pattern or pattern in stack_lower:
            return True
    return False


def _discover_stacks_from_env() -> Dict[str, Dict[str, str]]:
    """
    Discover Kubernetes stacks from your-product-qe JSON configs.

    Stacks are auto-discovered from GitHub JSON files.
    Kubeconfigs are auto-matched from ~/.kube/rancher/ directory.
    Excluded stacks (from settings.excluded_stacks) are filtered out.

    Returns:
        Dict of discovered stacks
    """
    global _kubernetes_stacks_cache

    if _kubernetes_stacks_cache is not None:
        return _kubernetes_stacks_cache

    # Load from JSON files (primary and only source)
    stacks = _load_stacks_from_json()

    # Filter out excluded stacks
    excluded = get_excluded_stacks()
    if excluded:
        original_count = len(stacks)
        stacks = {stack_id: config for stack_id, config in stacks.items() if not is_stack_excluded(stack_id)}
        filtered_count = original_count - len(stacks)
        if filtered_count > 0:
            import logging

            logging.getLogger(__name__).info("Excluded %d stacks from monitoring: %s", filtered_count, excluded)

    _kubernetes_stacks_cache = stacks
    return stacks


def get_kubernetes_stacks() -> Dict[str, Dict[str, str]]:
    """
    Get all configured Kubernetes stacks for monitoring.

    Stacks are auto-discovered from your-product-qe JSON configs (GitHub).
    Kubeconfigs are auto-matched from ~/.kube/rancher/ directory.
    """
    return _discover_stacks_from_env()


def get_stack_config(stack_id: str) -> Dict[str, str]:
    """Get configuration for a specific stack."""
    stacks = get_kubernetes_stacks()
    return stacks.get(stack_id, {})


def refresh_stack_discovery():
    """
    Force re-discovery of stacks from environment.
    Call this after dynamically updating environment variables.
    """
    global _kubernetes_stacks_cache
    _kubernetes_stacks_cache = None
    return get_kubernetes_stacks()


def get_available_stack_ids() -> List[str]:
    """Get list of all available stack IDs."""
    return list(get_kubernetes_stacks().keys())

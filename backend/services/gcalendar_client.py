"""
Google Calendar Client Service

Fetches release calendar events from Google Calendar and syncs them to local storage.
Supports both API key access (for public calendars) and service account access (for private calendars).

Usage:
    from services.gcalendar_client import get_gcalendar_client, sync_release_calendar

    # Get events directly
    client = get_gcalendar_client()
    events = await client.get_release_events()

    # Sync to local cache/PDF replacement
    await sync_release_calendar()
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

# Cache for synced calendar data
_calendar_cache: dict[str, Any] = {}
_cache_timestamp: Optional[datetime] = None
CACHE_TTL_MINUTES = 30

# Milestone patterns to extract from event titles
MILESTONE_KEYWORDS = {
    "Branch Cut": ["branch cut", "branchcut", "bc -"],
    "Final Build": ["final build", "finalbuild", "fb -"],
    "IRR": ["irr", "internal release review"],
    "Signoff STG": ["signoff stg", "sign off stg", "stg signoff", "signoff staging"],
    "Deploy MP Pre PROD": ["deploy mp pre", "pre prod", "pre-prod", "preprod"],
    "Deploy Prod Day 1": ["deploy prod day 1", "prod day 1", "day 1 deploy", "d1 deploy"],
    "Deploy Prod Day 2": ["deploy prod day 2", "prod day 2", "day 2 deploy", "d2 deploy"],
    "Deploy Prod Day 3": ["deploy prod day 3", "prod day 3", "day 3 deploy", "d3 deploy"],
    "Deploy Prod Day 4": ["deploy prod day 4", "prod day 4", "day 4 deploy", "d4 deploy"],
}

# Release pattern: R134.0, R135.1, etc.
RELEASE_PATTERN = re.compile(r"R?(\d{3})\.(\d)", re.IGNORECASE)


class GoogleCalendarClient:
    """Client for Google Calendar API with caching and release event parsing."""

    _instance: Optional["GoogleCalendarClient"] = None

    def __init__(self):
        self._service = None
        self._initialized = False
        self._use_api_key = False
        self._calendar_id = None

    @classmethod
    def get_instance(cls) -> "GoogleCalendarClient":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _initialize(self) -> bool:
        """Initialize Google Calendar API client."""
        if self._initialized:
            return self._service is not None or self._use_api_key

        self._calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "")
        api_key = os.getenv("GOOGLE_CALENDAR_API_KEY", "")
        service_account_file = getattr(settings, "google_service_account_file", "") or os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE", ""
        )

        if not self._calendar_id:
            logger.warning("Google Calendar not configured. Set GOOGLE_CALENDAR_ID environment variable.")
            self._initialized = True
            return False

        # Try API key first (simpler, works for public calendars)
        if api_key:
            logger.info("Using Google Calendar API key authentication")
            self._use_api_key = True
            self._api_key = api_key
            self._initialized = True
            return True

        # Try service account (for private calendars)
        if service_account_file and os.path.exists(service_account_file):
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build

                SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
                credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
                self._service = build("calendar", "v3", credentials=credentials)
                self._initialized = True
                logger.info("Google Calendar client initialized with service account")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize Google Calendar with service account: {e}")

        logger.warning(
            "Google Calendar not fully configured. "
            "Set GOOGLE_CALENDAR_API_KEY (for public) or GOOGLE_SERVICE_ACCOUNT_FILE (for private)."
        )
        self._initialized = True
        return False

    async def get_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 250,
    ) -> list[dict[str, Any]]:
        """
        Fetch events from Google Calendar.

        Args:
            time_min: Start of time range (defaults to 6 months ago)
            time_max: End of time range (defaults to 12 months from now)
            max_results: Maximum number of events to return

        Returns:
            List of calendar events
        """
        if not self._initialize():
            return []

        if time_min is None:
            time_min = datetime.now() - timedelta(days=180)
        if time_max is None:
            time_max = datetime.now() + timedelta(days=365)

        time_min_str = time_min.isoformat() + "Z"
        time_max_str = time_max.isoformat() + "Z"

        try:
            if self._use_api_key:
                return await self._fetch_with_api_key(time_min_str, time_max_str, max_results)
            else:
                return await self._fetch_with_service(time_min_str, time_max_str, max_results)
        except Exception as e:
            logger.error(f"Error fetching Google Calendar events: {e}")
            return []

    async def _fetch_with_api_key(self, time_min: str, time_max: str, max_results: int) -> list[dict[str, Any]]:
        """Fetch events using API key (for public calendars)."""
        import aiohttp

        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{self._calendar_id}/events"
            f"?key={self._api_key}"
            f"&timeMin={time_min}"
            f"&timeMax={time_max}"
            f"&maxResults={max_results}"
            f"&singleEvents=true"
            f"&orderBy=startTime"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Google Calendar API error: {response.status} - {error_text}")
                    return []

                data = await response.json()
                events = data.get("items", [])
                logger.info(f"Fetched {len(events)} events from Google Calendar")
                return events

    async def _fetch_with_service(self, time_min: str, time_max: str, max_results: int) -> list[dict[str, Any]]:
        """Fetch events using service account."""
        import asyncio

        def _sync_fetch():
            result = (
                self._service.events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return result.get("items", [])

        events = await asyncio.to_thread(_sync_fetch)
        logger.info(f"Fetched {len(events)} events from Google Calendar")
        return events

    def parse_release_event(self, event: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Parse a calendar event to extract release milestone information.

        Args:
            event: Google Calendar event object

        Returns:
            Parsed milestone info or None if not a release event
        """
        summary = event.get("summary", "")
        if not summary:
            return None

        # Extract release number
        release_match = RELEASE_PATTERN.search(summary)
        if not release_match:
            return None

        release_name = f"R{release_match.group(1)}.{release_match.group(2)}"

        # Determine milestone type
        milestone_type = None
        summary_lower = summary.lower()
        for milestone, keywords in MILESTONE_KEYWORDS.items():
            if any(kw in summary_lower for kw in keywords):
                milestone_type = milestone
                break

        if not milestone_type:
            # Try to infer from common patterns
            if "ep" in summary_lower:
                if "branch" in summary_lower:
                    milestone_type = "Branch Cut - EP"
                elif "final" in summary_lower or "fb" in summary_lower:
                    milestone_type = "Final Build - EP"
            elif "deploy" in summary_lower or "prod" in summary_lower:
                # Try to extract day number
                day_match = re.search(r"day\s*(\d)", summary_lower)
                if day_match:
                    milestone_type = f"Deploy Prod Day {day_match.group(1)}"
                elif "pre" in summary_lower:
                    milestone_type = "Deploy MP Pre PROD"

        if not milestone_type:
            logger.debug(f"Could not determine milestone type for event: {summary}")
            return None

        # Extract date
        start = event.get("start", {})
        date_str = start.get("date") or start.get("dateTime", "")[:10]

        if not date_str:
            return None

        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = event_date.strftime("%d-%b-%Y")
        except ValueError:
            logger.warning(f"Could not parse date: {date_str}")
            return None

        return {
            "release": release_name,
            "milestone": milestone_type,
            "date": formatted_date,
            "raw_date": date_str,
            "summary": summary,
            "event_id": event.get("id"),
        }

    async def get_release_events(self) -> dict[str, dict[str, Any]]:
        """
        Fetch and parse all release-related events from Google Calendar.

        Returns:
            Dict mapping release names to their milestone dates
        """
        events = await self.get_events()
        releases: dict[str, dict[str, Any]] = {}

        for event in events:
            parsed = self.parse_release_event(event)
            if not parsed:
                continue

            release_name = parsed["release"]
            milestone = parsed["milestone"]

            if release_name not in releases:
                releases[release_name] = {
                    "type": "Major Release" if release_name.endswith(".0") else "Minor Release",
                    "milestones": {},
                }

            # Only store first occurrence of each milestone (in case of duplicates)
            if milestone not in releases[release_name]["milestones"]:
                releases[release_name]["milestones"][milestone] = parsed["date"]
                logger.debug(f"Found: {release_name} {milestone} = {parsed['date']}")

        logger.info(f"Parsed {len(releases)} releases from Google Calendar events")
        return releases


def get_gcalendar_client() -> GoogleCalendarClient:
    """Get Google Calendar client singleton."""
    return GoogleCalendarClient.get_instance()


async def sync_release_calendar() -> dict[str, Any]:
    """
    Sync release calendar data from Google Calendar.

    This fetches events from Google Calendar and caches them locally.
    The cached data can be used by the release calendar parser as an
    alternative to PDF parsing.

    Returns:
        Sync result with status and statistics
    """
    global _calendar_cache, _cache_timestamp

    client = get_gcalendar_client()

    try:
        releases = await client.get_release_events()

        if not releases:
            return {
                "success": False,
                "error": "No release events found or calendar not configured",
                "releases_synced": 0,
            }

        # Calculate IRR dates (1 week before Branch Cut)
        for release_name, data in releases.items():
            milestones = data.get("milestones", {})
            branch_cut = milestones.get("Branch Cut - EP") or milestones.get("Branch Cut")

            if branch_cut and "IRR" not in milestones:
                try:
                    bc_date = datetime.strptime(branch_cut, "%d-%b-%Y")
                    irr_date = bc_date - timedelta(days=7)
                    milestones["IRR"] = irr_date.strftime("%d-%b-%Y")
                except ValueError:
                    pass

        # Update cache
        _calendar_cache = releases
        _cache_timestamp = datetime.now()

        # Save to cache file for persistence across restarts
        cache_file = os.path.join(os.path.dirname(__file__), "..", "data", "gcalendar_cache.json")
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)

        cache_data = {
            "timestamp": _cache_timestamp.isoformat(),
            "releases": releases,
        }

        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

        logger.info(f"Synced {len(releases)} releases from Google Calendar")

        return {
            "success": True,
            "releases_synced": len(releases),
            "timestamp": _cache_timestamp.isoformat(),
            "source": "google_calendar",
        }

    except Exception as e:
        logger.error(f"Error syncing release calendar: {e}")
        return {
            "success": False,
            "error": str(e),
            "releases_synced": 0,
        }


def get_cached_calendar_data() -> Optional[dict[str, dict[str, Any]]]:
    """
    Get cached calendar data if available and not expired.

    Returns:
        Cached releases dict or None if cache is empty/expired
    """
    global _calendar_cache, _cache_timestamp

    # Check memory cache first
    if _calendar_cache and _cache_timestamp:
        age = datetime.now() - _cache_timestamp
        if age.total_seconds() < CACHE_TTL_MINUTES * 60:
            return _calendar_cache

    # Try loading from file cache
    cache_file = os.path.join(os.path.dirname(__file__), "..", "data", "gcalendar_cache.json")

    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cache_data = json.load(f)

            cache_time = datetime.fromisoformat(cache_data.get("timestamp", ""))
            age = datetime.now() - cache_time

            # File cache valid for longer (24 hours) as fallback
            if age.total_seconds() < 24 * 60 * 60:
                _calendar_cache = cache_data.get("releases", {})
                _cache_timestamp = cache_time
                logger.info("Loaded calendar data from file cache")
                return _calendar_cache

        except Exception as e:
            logger.warning(f"Could not load calendar cache file: {e}")

    return None


def clear_calendar_cache():
    """Clear the calendar cache to force a refresh on next access."""
    global _calendar_cache, _cache_timestamp
    _calendar_cache = {}
    _cache_timestamp = None

    cache_file = os.path.join(os.path.dirname(__file__), "..", "data", "gcalendar_cache.json")
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            logger.info("Cleared calendar cache file")
        except Exception as e:
            logger.warning(f"Could not remove cache file: {e}")

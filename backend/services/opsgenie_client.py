"""
OpsGenie API Client
====================

Fetches on-call schedule data from OpsGenie's REST API.

Uses the Timeline API to get the full rotation grid, and the
Who-is-On-Call / Next-On-Call APIs for current/next rotation info.

Supports multiple schedules:
- NSC-Escalation-Oncall-Primary: Engineer on-call rotations (IST, TW, US)
- NSC-Mangers: Manager on-call schedule

Environment Variables:
    OPSGENIE_API_KEY              - GenieKey for authentication
    OPSGENIE_API_URL              - Base URL (default: https://api.opsgenie.com)
    OPSGENIE_SCHEDULE_NAME        - Primary schedule (default: NSC-Escalation-Oncall-Primary)
    OPSGENIE_MANAGER_SCHEDULE_NAME - Manager schedule (default: NSC-Mangers)
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from config import settings

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes

_cache: dict[str, Any] = {}
_cache_times: dict[str, float] = {}

# Schedule type definitions
SCHEDULE_TYPES = {
    "primary": {
        "id": "primary",
        "name": "NSC-Escalation-Oncall-Primary",
        "display_name": "Engineer On-Call",
        "description": "Primary escalation on-call for engineers across IST, TW, and US regions",
        "icon": "👨‍💻",
        "color": "#6366f1",
    },
    "managers": {
        "id": "managers",
        "name": "NSC-Mangers",
        "display_name": "Manager On-Call",
        "description": "Manager on-call schedule for escalations",
        "icon": "👔",
        "color": "#10b981",
    },
    "backend": {
        "id": "backend",
        "name": "NSC-SRE-Client-Services-schedule",
        "display_name": "Backend Services",
        "description": "Backend Services team on-call schedule",
        "icon": "🔧",
        "color": "#ec4899",
    },
}

ROTATION_REGION_MAP = {
    "india": "IST",
    "ist": "IST",
    "us": "US",
    "ustime": "US",
    "pacific": "US",
    "taiwan": "TW",
    "tw": "TW",
    "cst": "TW",
}

REGION_META = {
    "IST": {
        "id": "IST",
        "label": "India (IST)",
        "timezone": "Asia/Kolkata",
        "utc_offset": "+05:30",
        "flag": "🇮🇳",
        "coverage": "12:30 PM – 8:30 PM IST",
        "coverage_local": "12:30 PM – 8:30 PM",
        "coverage_local_tz": "IST",
        "color": "#f97316",
        "rotation_start_day": "Tuesday",  # Rotation week: Tuesday to Monday
    },
    "TW": {
        "id": "TW",
        "label": "Taiwan (CST)",
        "timezone": "Asia/Taipei",
        "utc_offset": "+08:00",
        "flag": "🇹🇼",
        "coverage": "4:30 AM – 12:30 PM IST",
        "coverage_local": "7:00 AM – 3:00 PM",
        "coverage_local_tz": "CST",
        "color": "#06b6d4",
        "rotation_start_day": "Monday",  # Rotation week: Monday to Sunday
    },
    "US": {
        "id": "US",
        "label": "US (Pacific)",
        "timezone": "America/Los_Angeles",
        "utc_offset": "-08:00",
        "flag": "🇺🇸",
        "coverage": "8:30 PM – 4:30 AM IST",
        "coverage_local": "8:00 AM – 4:00 PM",
        "coverage_local_tz": "PST/PDT",
        "color": "#6366f1",
        "rotation_start_day": "Monday",  # Rotation week: Monday to Sunday
    },
}


def _get_cached(key: str) -> Any | None:
    if key in _cache and (time.time() - _cache_times.get(key, 0)) < CACHE_TTL:
        return _cache[key]
    return None


def _set_cache(key: str, value: Any) -> None:
    _cache[key] = value
    _cache_times[key] = time.time()


def _headers(api_key: str | None = None) -> dict[str, str]:
    key = api_key or settings.opsgenie_api_key
    return {
        "Authorization": f"GenieKey {key}",
        "Content-Type": "application/json",
    }


def _get_api_key_for_schedule(schedule_type: str) -> str | None:
    """Get the appropriate API key for a schedule type."""
    if schedule_type == "backend" and settings.opsgenie_backend_api_key:
        return settings.opsgenie_backend_api_key
    return settings.opsgenie_api_key


def _base_url() -> str:
    return settings.opsgenie_api_url.rstrip("/")


def _classify_rotation(rotation_name: str) -> str | None:
    """Map an OpsGenie rotation name to a region ID (IST / TW / US)."""
    name_lower = rotation_name.lower().replace("-", "").replace("_", "").replace(" ", "")
    for keyword, region_id in ROTATION_REGION_MAP.items():
        if keyword in name_lower:
            return region_id
    return None


def _parse_iso(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        clean = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def _get_monday(dt: datetime) -> datetime:
    """Return the Monday of the week containing dt."""
    days_since_monday = dt.weekday()
    return (dt - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)


def _get_tuesday(dt: datetime) -> datetime:
    """Return the Tuesday of the rotation week containing dt.

    For Tuesday-based weeks:
    - Tuesday is day 0 of the rotation week
    - Monday is day 6 (last day) of the rotation week
    """
    weekday = dt.weekday()  # Monday=0, Tuesday=1, ..., Sunday=6
    # Calculate days since last Tuesday
    # If today is Tuesday (1), days_since = 0
    # If today is Wednesday (2), days_since = 1
    # If today is Monday (0), days_since = 6
    days_since_tuesday = (weekday - 1) % 7
    return (dt - timedelta(days=days_since_tuesday)).replace(hour=0, minute=0, second=0, microsecond=0)


# Rotation start day per region (0=Monday, 1=Tuesday, etc.)
# Based on OpsGenie schedule configuration
REGION_ROTATION_START_DAY = {
    "IST": 1,  # Tuesday
    "TW": 0,  # Monday
    "US": 0,  # Monday
    "ALL": 0,  # Monday (default for manager schedules)
}


def _get_rotation_week_start(dt: datetime, region_id: str) -> datetime:
    """Get the start of the rotation week for a specific region.

    Different regions have different rotation start days:
    - IST (India): Tuesday
    - TW (Taiwan): Monday
    - US: Monday
    """
    start_day = REGION_ROTATION_START_DAY.get(region_id, 0)  # Default to Monday
    weekday = dt.weekday()
    days_since_start = (weekday - start_day) % 7
    return (dt - timedelta(days=days_since_start)).replace(hour=0, minute=0, second=0, microsecond=0)


# Email to full name mapping for known team members
EMAIL_TO_NAME_MAP = {
    # ─── Engineers - IST (India) ───
    "sandiyappan": "Saravana Pandiyan Andiyappan",
    "pkgovindraj": "Pavan Govindraj",
    "sps": "Sowbarani PS",
    "sdavda": "Smit Davda",
    "ksangodkar": "Kunal Sangodkar",
    "asrinivasababu": "Arvind Srinivasa Babu",
    "deepthis": "Deepthi K S",
    "kmanikandan": "Karthic Mariappan",
    "vmittal": "Vinay Mittal",
    "abhikumar": "Abhilash Kumar",
    "absharma": "Abhishek Sharma",
    "akumars": "Anand Kumar S",
    "dshirsath": "Devendra Shirsath",
    "hsinghgujral": "Harmeet Singh Gujral",
    "svinjamuru": "Suresh Vinjamuru",
    "sjulania": "Suyesh Julania",
    "shimatbhai": "Snehalkumar Donga",
    "cbalasaiharika": "Chebrolu Bala Sai Harika",
    "svenkatesh": "Somasundar Venkatesh",
    "rramanvk": "Rajesh Raman V K",
    "rbhat": "Rajesh Narayan Bhat",
    "pchitravel": "Poovarasan Chitravel",
    "jan": "Jithan A N",
    # ─── Engineers - Taiwan ───
    "acheng": "Austin Cheng",
    "klin": "Kenmin Lin",
    "seanc": "Sean Chen",
    "jkao": "Jackal Kao",
    "asu": "Andy Su",
    "charlesl": "Charles Lo",
    "clo": "Chloe Lo",
    "clarkh": "Clark Hsu",
    "ctw": "CT Wu",
    "vegel": "Vege Lin",
    "kaifuc": "Kaifu Chang",
    "ochao": "Oscar Chao",
    "jimmyc": "Jimmy Chen",
    "royw": "Roy Wang",
    "ryanc": "Ryan Chen",
    "clee": "Chuck Lee",
    "pyu": "Ping Yu",
    # ─── Engineers - US ───
    "kshaw": "Kim Shaw",
    "acastleberry": "Austin Castleberry",
    "edeng": "Eric Deng",
    "xhu": "Xin Hu",
    "bhu": "Baoyue Hu",
    "eguz": "Egor Guz",
    "apoole": "Angelina Poole",
    "tandrey": "Andrey Tverdokhleb",
    # ─── Managers ───
    "fhu": "Frank Hu",
    "sjili": "Shuangjiang Li",
    "vsharma": "Vivek Sharma",
    "jchen": "James Chen",
    "yenmingc": "Jimmy Chen",
    # ─── Product Managers ───
    "salijaffrey": "Shujaat Ali Jaffrey",
    "pd": "Phanikumar Dharmavarapu",
    # ─── Backend Services (SRE Client Services) ───
    "nbansal": "Naveen Bansal",
    "ngabhane": "Nikhil Gabhane",
    "abhishekm": "Abhishek Mallik",
    "svenumuddala": "Srinivas Venumuddala",
    "yjyin": "Yongjie Yin",
    "rnaik": "Rahul Naik",
    "sandipk": "Sandeep Kumar",
}


def _extract_display_name(raw_name: str) -> str:
    """
    Convert an OpsGenie recipient name (often an email) to a display name.

    Uses EMAIL_TO_NAME_MAP for known users, otherwise attempts to parse
    the email username into a readable name.

    Examples:
        'pkgovindraj@your-company.com' -> 'Pavan Govindraj' (from map)
        'john.doe@company.com' -> 'John Doe' (parsed)
        'John Doe' -> 'John Doe' (already a name)
    """
    if "@" in raw_name:
        local = raw_name.split("@")[0].lower()

        # 1. Check local mapping first
        if local in EMAIL_TO_NAME_MAP:
            return EMAIL_TO_NAME_MAP[local]

        # 2. Try to parse the email username
        # Handle formats: firstname.lastname, firstname_lastname
        parts = local.replace("_", ".").replace("-", ".").split(".")

        if len(parts) >= 2:
            return " ".join(p.capitalize() for p in parts if p)
        else:
            return local.capitalize()

    return raw_name


async def get_schedule_timeline(weeks: int = 8) -> dict[str, Any] | None:
    """
    Fetch the schedule timeline from OpsGenie.

    Returns the finalTimeline rotations parsed into our region-based
    weekly format, or None on failure.
    """
    schedule_name = settings.opsgenie_schedule_name
    cache_key = f"timeline:{schedule_name}:{weeks}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = (
        f"{_base_url()}/v2/schedules/{schedule_name}/timeline"
        f"?identifierType=name&interval={weeks}&intervalUnit=weeks"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"OpsGenie timeline API failed: {e}")
        return None

    timeline_data = data.get("data", {})
    final_timeline = timeline_data.get("finalTimeline", {})
    rotations_raw = final_timeline.get("rotations", [])

    # Build a mapping: week_start -> { region_id -> person_info }
    # Note: Different regions have different rotation start days (IST=Tuesday, US/TW=Monday)
    # We use a unified week key based on the rotation start for each region
    week_map: dict[str, dict[str, Any]] = {}
    team_members_by_region: dict[str, dict[str, dict]] = {
        "IST": {},
        "TW": {},
        "US": {},
    }

    # Track hours per person per week per region to determine who has the most coverage
    week_person_hours: dict[str, dict[str, dict[str, float]]] = {}  # week_key -> region -> {person: hours}
    person_info_cache: dict[str, dict[str, Any]] = {}  # person_name -> info dict

    for rotation in rotations_raw:
        rotation_name = rotation.get("name", "")
        region_id = _classify_rotation(rotation_name)
        if not region_id:
            logger.warning(f"Could not classify rotation '{rotation_name}' to a region, skipping")
            continue

        for period in rotation.get("periods", []):
            recipient = period.get("recipient", {})
            raw_name = recipient.get("name", "")
            if not raw_name or recipient.get("type") not in ("user", None, ""):
                if recipient.get("type") == "user":
                    pass
                elif recipient.get("type") in ("team", "escalation", "schedule"):
                    continue

            display_name = _extract_display_name(raw_name)
            email = raw_name if "@" in raw_name else ""
            coverage = REGION_META.get(region_id, {}).get("coverage", "")

            start_dt = _parse_iso(period.get("startDate", ""))
            end_dt = _parse_iso(period.get("endDate", ""))
            if not start_dt or not end_dt:
                continue

            # Collect team members
            if display_name and display_name not in team_members_by_region[region_id]:
                team_members_by_region[region_id][display_name] = {
                    "name": display_name,
                    "email": email,
                    "slack": f"@{raw_name.split('@')[0]}" if "@" in raw_name else "",
                }

            # Cache person info for later use
            if display_name not in person_info_cache:
                person_info_cache[display_name] = {
                    "name": display_name,
                    "email": email,
                    "slack": f"@{raw_name.split('@')[0]}" if "@" in raw_name else "",
                    "coverage": coverage,
                }

            # Accumulate hours per person per week
            current = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            while current < end_dt:
                week_start = _get_rotation_week_start(current, region_id)
                week_key = week_start.strftime("%Y-%m-%d")

                # Calculate hours on-call for this day
                day_end = current + timedelta(days=1)
                period_end_on_this_day = min(end_dt, day_end)
                period_start_on_this_day = max(start_dt, current)
                hours_on_call = (period_end_on_this_day - period_start_on_this_day).total_seconds() / 3600

                if week_key not in week_person_hours:
                    week_person_hours[week_key] = {}
                if region_id not in week_person_hours[week_key]:
                    week_person_hours[week_key][region_id] = {}
                if display_name not in week_person_hours[week_key][region_id]:
                    week_person_hours[week_key][region_id][display_name] = 0

                week_person_hours[week_key][region_id][display_name] += hours_on_call
                current += timedelta(days=1)

    # Now build week_map by selecting the person with the most hours per region per week
    for week_key, regions_data in week_person_hours.items():
        if week_key not in week_map:
            week_map[week_key] = {}

        for region_id, person_hours in regions_data.items():
            if person_hours:
                # Find person with most hours
                winner = max(person_hours.items(), key=lambda x: x[1])
                winner_name = winner[0]
                winner_info = person_info_cache.get(winner_name, {"name": winner_name})
                week_map[week_key][region_id] = {
                    "name": winner_info.get("name", winner_name),
                    "email": winner_info.get("email", ""),
                    "slack": winner_info.get("slack", ""),
                    "coverage": winner_info.get("coverage", ""),
                }

    # Sort weeks and build rotations list
    today = datetime.now().date()
    now = datetime.now()
    sorted_weeks = sorted(week_map.keys())
    rotations = []

    for idx, week_start_str in enumerate(sorted_weeks):
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
        week_end = week_start + timedelta(days=6)

        if week_start <= today <= week_end:
            status = "active"
        elif week_end < today:
            status = "completed"
        else:
            status = "upcoming"

        rotations.append(
            {
                "id": idx + 1,
                "week_start": week_start_str,
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_number": week_start.isocalendar()[1],
                "regions": week_map[week_start_str],
                "status": status,
            }
        )

    # Build team_members as lists (matching the frontend expected shape)
    team_members = {rid: list(members.values()) for rid, members in team_members_by_region.items() if members}

    # Combine all currently active regions into one current_rotation
    # and all upcoming regions into one next_rotation
    # This handles the case where different regions have different rotation start days
    current_regions: dict[str, Any] = {}
    next_regions: dict[str, Any] = {}

    # For each region, find who is currently on-call and who is next
    for region_id in ["IST", "TW", "US"]:
        region_week_start = _get_rotation_week_start(now, region_id)
        region_week_key = region_week_start.strftime("%Y-%m-%d")

        # Find current on-call for this region
        for r in rotations:
            if r["week_start"] == region_week_key and region_id in r.get("regions", {}):
                current_regions[region_id] = r["regions"][region_id]
                break

        # Find next on-call for this region (next week's rotation)
        next_week_start = region_week_start + timedelta(days=7)
        next_week_key = next_week_start.strftime("%Y-%m-%d")

        for r in rotations:
            if r["week_start"] == next_week_key and region_id in r.get("regions", {}):
                next_regions[region_id] = r["regions"][region_id]
                break

    # Build unified current and next rotation objects
    current_rotation = None
    if current_regions:
        # Use IST week boundaries for the unified view
        ist_week_start = _get_rotation_week_start(now, "IST")
        ist_week_end = ist_week_start + timedelta(days=6)
        current_rotation = {
            "id": 0,
            "week_start": ist_week_start.strftime("%Y-%m-%d"),
            "week_end": ist_week_end.strftime("%Y-%m-%d"),
            "week_number": ist_week_start.date().isocalendar()[1],
            "regions": current_regions,
            "status": "active",
        }

    next_rotation = None
    if next_regions:
        ist_next_week_start = _get_rotation_week_start(now, "IST") + timedelta(days=7)
        ist_next_week_end = ist_next_week_start + timedelta(days=6)
        next_rotation = {
            "id": 0,
            "week_start": ist_next_week_start.strftime("%Y-%m-%d"),
            "week_end": ist_next_week_end.strftime("%Y-%m-%d"),
            "week_number": ist_next_week_start.date().isocalendar()[1],
            "regions": next_regions,
            "status": "upcoming",
        }

    result = {
        "rotations": rotations,
        "regions": [REGION_META[rid] for rid in REGION_META if rid in team_members],
        "team_members": team_members,
        "current_rotation": current_rotation,
        "next_rotation": next_rotation,
        "source": "opsgenie",
        "total_count": len(rotations),
    }

    _set_cache(cache_key, result)
    return result


async def get_current_oncall() -> dict[str, Any] | None:
    """Fetch current on-call participants from OpsGenie."""
    schedule_name = settings.opsgenie_schedule_name
    cache_key = f"current:{schedule_name}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{_base_url()}/v2/schedules/{schedule_name}/on-calls" f"?scheduleIdentifierType=name&flat=true"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"OpsGenie current on-call API failed: {e}")
        return None

    result = data.get("data", {})
    _set_cache(cache_key, result)
    return result


async def get_next_oncall() -> dict[str, Any] | None:
    """Fetch next on-call participants from OpsGenie."""
    schedule_name = settings.opsgenie_schedule_name
    cache_key = f"next:{schedule_name}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{_base_url()}/v2/schedules/{schedule_name}/next-on-calls" f"?scheduleIdentifierType=name&flat=true"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"OpsGenie next on-call API failed: {e}")
        return None

    result = data.get("data", {})
    _set_cache(cache_key, result)
    return result


def is_configured() -> bool:
    """Check if OpsGenie API key is configured."""
    return bool(settings.opsgenie_api_key)


def get_schedule_name(schedule_type: str = "primary") -> str:
    """Get the schedule name for a given type."""
    if schedule_type == "managers":
        return settings.opsgenie_manager_schedule_name
    if schedule_type == "backend":
        return settings.opsgenie_backend_schedule_name
    return settings.opsgenie_schedule_name


async def get_schedule_timeline_by_name(
    schedule_name: str, weeks: int = 8, api_key: str | None = None
) -> dict[str, Any] | None:
    """
    Fetch the schedule timeline from OpsGenie for a specific schedule name.

    Args:
        schedule_name: OpsGenie schedule name
        weeks: Number of weeks to fetch
        api_key: Optional API key override (for schedules with separate keys)

    Returns the finalTimeline rotations parsed into our region-based
    weekly format, or None on failure.
    """
    cache_key = f"timeline:{schedule_name}:{weeks}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = (
        f"{_base_url()}/v2/schedules/{schedule_name}/timeline"
        f"?identifierType=name&interval={weeks}&intervalUnit=weeks"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers(api_key))
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"OpsGenie timeline API failed for {schedule_name}: {e}")
        return None

    timeline_data = data.get("data", {})
    final_timeline = timeline_data.get("finalTimeline", {})
    rotations_raw = final_timeline.get("rotations", [])

    # Build a mapping: week_start -> { region_id -> person_info }
    # Note: Different regions have different rotation start days (IST=Tuesday, US/TW=Monday)
    week_map: dict[str, dict[str, Any]] = {}
    team_members_by_region: dict[str, dict[str, dict]] = {
        "IST": {},
        "TW": {},
        "US": {},
    }

    # Track hours per person per week per region to determine who has the most coverage
    week_person_hours: dict[str, dict[str, dict[str, float]]] = {}  # week_key -> region -> {person: hours}
    person_info_cache: dict[str, dict[str, Any]] = {}  # person_name -> info dict

    # Track if this is a single-region schedule (like managers)
    is_single_region = len(rotations_raw) == 1 or not any(_classify_rotation(r.get("name", "")) for r in rotations_raw)

    for rotation in rotations_raw:
        rotation_name = rotation.get("name", "")
        region_id = _classify_rotation(rotation_name)

        # For single-region schedules (managers), use "ALL" as region
        if not region_id and is_single_region:
            region_id = "ALL"
            if "ALL" not in team_members_by_region:
                team_members_by_region["ALL"] = {}
        elif not region_id:
            logger.warning(f"Could not classify rotation '{rotation_name}' to a region, skipping")
            continue

        for period in rotation.get("periods", []):
            recipient = period.get("recipient", {})
            raw_name = recipient.get("name", "")
            if not raw_name or recipient.get("type") not in ("user", None, ""):
                if recipient.get("type") == "user":
                    pass
                elif recipient.get("type") in ("team", "escalation", "schedule"):
                    continue

            display_name = _extract_display_name(raw_name)
            email = raw_name if "@" in raw_name else ""
            coverage = REGION_META.get(region_id, {}).get("coverage", "")

            start_dt = _parse_iso(period.get("startDate", ""))
            end_dt = _parse_iso(period.get("endDate", ""))
            if not start_dt or not end_dt:
                continue

            # Collect team members
            if region_id in team_members_by_region:
                if display_name and display_name not in team_members_by_region[region_id]:
                    team_members_by_region[region_id][display_name] = {
                        "name": display_name,
                        "email": email,
                        "slack": f"@{raw_name.split('@')[0]}" if "@" in raw_name else "",
                    }

            # Cache person info for later use
            if display_name not in person_info_cache:
                person_info_cache[display_name] = {
                    "name": display_name,
                    "email": email,
                    "slack": f"@{raw_name.split('@')[0]}" if "@" in raw_name else "",
                    "coverage": coverage if coverage else "Full Week",
                }

            # Accumulate hours per person per week
            current = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            while current < end_dt:
                week_start = _get_rotation_week_start(current, region_id)
                week_key = week_start.strftime("%Y-%m-%d")

                # Calculate hours on-call for this day
                day_end = current + timedelta(days=1)
                period_end_on_this_day = min(end_dt, day_end)
                period_start_on_this_day = max(start_dt, current)
                hours_on_call = (period_end_on_this_day - period_start_on_this_day).total_seconds() / 3600

                if week_key not in week_person_hours:
                    week_person_hours[week_key] = {}
                if region_id not in week_person_hours[week_key]:
                    week_person_hours[week_key][region_id] = {}
                if display_name not in week_person_hours[week_key][region_id]:
                    week_person_hours[week_key][region_id][display_name] = 0

                week_person_hours[week_key][region_id][display_name] += hours_on_call
                current += timedelta(days=1)

    # Now build week_map by selecting the person with the most hours per region per week
    for week_key, regions_data in week_person_hours.items():
        if week_key not in week_map:
            week_map[week_key] = {}

        for region_id, person_hours in regions_data.items():
            if person_hours:
                # Find person with most hours
                winner = max(person_hours.items(), key=lambda x: x[1])
                winner_name = winner[0]
                winner_info = person_info_cache.get(winner_name, {"name": winner_name})
                week_map[week_key][region_id] = {
                    "name": winner_info.get("name", winner_name),
                    "email": winner_info.get("email", ""),
                    "slack": winner_info.get("slack", ""),
                    "coverage": winner_info.get("coverage", ""),
                }

    # Sort weeks and build rotations list
    today = datetime.now().date()
    now = datetime.now()
    sorted_weeks = sorted(week_map.keys())
    rotations = []

    for idx, week_start_str in enumerate(sorted_weeks):
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
        week_end = week_start + timedelta(days=6)

        if week_start <= today <= week_end:
            status = "active"
        elif week_end < today:
            status = "completed"
        else:
            status = "upcoming"

        rotations.append(
            {
                "id": idx + 1,
                "week_start": week_start_str,
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_number": week_start.isocalendar()[1],
                "regions": week_map[week_start_str],
                "status": status,
            }
        )

    # Build team_members as lists (matching the frontend expected shape)
    team_members = {rid: list(members.values()) for rid, members in team_members_by_region.items() if members}

    # Get region metadata
    regions = []
    for rid in team_members:
        if rid in REGION_META:
            regions.append(REGION_META[rid])
        elif rid == "ALL":
            regions.append(
                {
                    "id": "ALL",
                    "label": "All Regions",
                    "timezone": "UTC",
                    "utc_offset": "+00:00",
                    "flag": "🌐",
                    "coverage": "Full Week",
                    "color": "#10b981",
                }
            )

    # Combine all currently active regions into one current_rotation
    # and all upcoming regions into one next_rotation
    # This handles the case where different regions have different rotation start days
    current_regions: dict[str, Any] = {}
    next_regions: dict[str, Any] = {}

    # Determine which regions are in this schedule
    schedule_regions = list(team_members.keys())

    # For each region, find who is currently on-call and who is next
    for region_id in schedule_regions:
        region_week_start = _get_rotation_week_start(now, region_id)
        region_week_key = region_week_start.strftime("%Y-%m-%d")

        # Find current on-call for this region
        for r in rotations:
            if r["week_start"] == region_week_key and region_id in r.get("regions", {}):
                current_regions[region_id] = r["regions"][region_id]
                break

        # Find next on-call for this region (next week's rotation)
        next_week_start = region_week_start + timedelta(days=7)
        next_week_key = next_week_start.strftime("%Y-%m-%d")

        for r in rotations:
            if r["week_start"] == next_week_key and region_id in r.get("regions", {}):
                next_regions[region_id] = r["regions"][region_id]
                break

    # Build unified current and next rotation objects
    # Use IST week boundaries for multi-region schedules, or the first region for single-region
    primary_region = "IST" if "IST" in schedule_regions else schedule_regions[0] if schedule_regions else "IST"

    current_rotation = None
    if current_regions:
        week_start = _get_rotation_week_start(now, primary_region)
        week_end = week_start + timedelta(days=6)
        current_rotation = {
            "id": 0,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "week_number": week_start.date().isocalendar()[1],
            "regions": current_regions,
            "status": "active",
        }

    next_rotation = None
    if next_regions:
        next_week_start = _get_rotation_week_start(now, primary_region) + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=6)
        next_rotation = {
            "id": 0,
            "week_start": next_week_start.strftime("%Y-%m-%d"),
            "week_end": next_week_end.strftime("%Y-%m-%d"),
            "week_number": next_week_start.date().isocalendar()[1],
            "regions": next_regions,
            "status": "upcoming",
        }

    result = {
        "schedule_name": schedule_name,
        "rotations": rotations,
        "regions": regions,
        "team_members": team_members,
        "current_rotation": current_rotation,
        "next_rotation": next_rotation,
        "source": "opsgenie",
        "total_count": len(rotations),
    }

    _set_cache(cache_key, result)
    return result


async def get_current_oncall_by_name(schedule_name: str, api_key: str | None = None) -> dict[str, Any] | None:
    """Fetch current on-call participants from OpsGenie for a specific schedule."""
    cache_key = f"current:{schedule_name}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{_base_url()}/v2/schedules/{schedule_name}/on-calls" f"?scheduleIdentifierType=name&flat=true"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers(api_key))
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"OpsGenie current on-call API failed for {schedule_name}: {e}")
        return None

    result = data.get("data", {})
    _set_cache(cache_key, result)
    return result


async def get_all_schedules(weeks: int = 8) -> dict[str, Any]:
    """
    Fetch all configured schedules (primary, managers, and backend).

    Returns a combined result with data for all schedules.
    """
    schedules_data = {}

    # Fetch primary schedule
    primary_name = settings.opsgenie_schedule_name
    primary_data = await get_schedule_timeline_by_name(primary_name, weeks)
    if primary_data:
        schedules_data["primary"] = {
            **primary_data,
            **SCHEDULE_TYPES["primary"],
        }

    # Fetch manager schedule
    manager_name = settings.opsgenie_manager_schedule_name
    manager_data = await get_schedule_timeline_by_name(manager_name, weeks)
    if manager_data:
        schedules_data["managers"] = {
            **manager_data,
            **SCHEDULE_TYPES["managers"],
        }

    # Fetch backend schedule (only if configured, uses separate API key if configured)
    backend_name = settings.opsgenie_backend_schedule_name
    if backend_name:
        backend_api_key = _get_api_key_for_schedule("backend")
        backend_data = await get_schedule_timeline_by_name(backend_name, weeks, backend_api_key)
        if backend_data:
            schedules_data["backend"] = {
                **backend_data,
                **SCHEDULE_TYPES["backend"],
            }

    return {
        "schedules": schedules_data,
        "schedule_types": SCHEDULE_TYPES,
        "source": "opsgenie" if schedules_data else "error",
        "configured": is_configured(),
    }


async def get_all_current_oncall() -> dict[str, Any]:
    """
    Get current on-call for all schedules.

    Returns who is currently on-call for primary, manager, and backend schedules.
    """
    result = {
        "primary": None,
        "managers": None,
        "backend": None,
        "source": "opsgenie",
    }

    # Fetch primary current on-call
    primary_name = settings.opsgenie_schedule_name
    primary_current = await get_current_oncall_by_name(primary_name)
    if primary_current:
        on_call_recipients = primary_current.get("onCallRecipients", [])
        result["primary"] = {
            "schedule_name": primary_name,
            "on_call": [_extract_display_name(r) for r in on_call_recipients],
            "raw": on_call_recipients,
            **SCHEDULE_TYPES["primary"],
        }

    # Fetch manager current on-call
    manager_name = settings.opsgenie_manager_schedule_name
    manager_current = await get_current_oncall_by_name(manager_name)
    if manager_current:
        on_call_recipients = manager_current.get("onCallRecipients", [])
        result["managers"] = {
            "schedule_name": manager_name,
            "on_call": [_extract_display_name(r) for r in on_call_recipients],
            "raw": on_call_recipients,
            **SCHEDULE_TYPES["managers"],
        }

    # Fetch backend current on-call (only if configured, uses separate API key if configured)
    backend_name = settings.opsgenie_backend_schedule_name
    if backend_name:
        backend_api_key = _get_api_key_for_schedule("backend")
        backend_current = await get_current_oncall_by_name(backend_name, backend_api_key)
        if backend_current:
            on_call_recipients = backend_current.get("onCallRecipients", [])
            result["backend"] = {
                "schedule_name": backend_name,
                "on_call": [_extract_display_name(r) for r in on_call_recipients],
                "raw": on_call_recipients,
                **SCHEDULE_TYPES["backend"],
            }

    return result

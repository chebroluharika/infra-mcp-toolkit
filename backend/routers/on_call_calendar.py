"""
On-Call Calendar API Router

Provides endpoints for on-call rotation schedule data.

Supports multiple schedules:
- NSC-Escalation-Oncall-Primary: Engineer on-call (IST, TW, US regions)
- NSC-Mangers: Manager on-call schedule

All timings are defined in IST (India Standard Time) for consistency:
- India (IST):  12:30 PM – 8:30 PM IST
- US (Pacific): 8:30 PM – 4:30 AM IST (next day)
- Taiwan (CST): 4:30 AM – 12:30 PM IST

Data sources (in priority order):
1. OpsGenie API (live data from configured schedules)
2. Sample data fallback (when OPSGENIE_API_KEY is not configured)
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from services import opsgenie_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/on-call-calendar",
    tags=["on-call-calendar"],
)

# Schedule metadata for UI
SCHEDULE_METADATA = {
    "primary": {
        "id": "primary",
        "name": "NSC-Escalation-Oncall-Primary",
        "display_name": "Engineer On-Call",
        "description": "Primary escalation on-call rotations for engineers across IST, TW, and US regions",
        "icon": "👨‍💻",
        "color": "#6366f1",
        "has_regions": True,
    },
    "managers": {
        "id": "managers",
        "name": "NSC-Mangers",
        "display_name": "Manager On-Call",
        "description": "Manager on-call schedule for escalations requiring management attention",
        "icon": "👔",
        "color": "#10b981",
        "has_regions": False,
    },
    "backend": {
        "id": "backend",
        "name": "NSC-SRE-Client-Services-schedule",
        "display_name": "Backend Services",
        "description": "Backend Services team on-call schedule",
        "icon": "🔧",
        "color": "#ec4899",
        "has_regions": False,
    },
}

REGIONS = [
    {
        "id": "IST",
        "label": "India (IST)",
        "timezone": "Asia/Kolkata",
        "utc_offset": "+05:30",
        "flag": "🇮🇳",
        "coverage": "12:30 PM – 8:30 PM IST",
        "coverage_local": "12:30 PM – 8:30 PM",
        "coverage_local_tz": "IST",
        "coverage_utc_start": 7,  # 12:30 PM IST = 7:00 AM UTC
        "coverage_utc_end": 15,  # 8:30 PM IST = 3:00 PM UTC
        "color": "#f97316",
    },
    {
        "id": "TW",
        "label": "Taiwan (CST)",
        "timezone": "Asia/Taipei",
        "utc_offset": "+08:00",
        "flag": "🇹🇼",
        "coverage": "4:30 AM – 12:30 PM IST",
        "coverage_local": "7:00 AM – 3:00 PM",
        "coverage_local_tz": "CST",
        "coverage_utc_start": 23,  # 4:30 AM IST = 11:00 PM UTC (prev day)
        "coverage_utc_end": 7,  # 12:30 PM IST = 7:00 AM UTC
        "color": "#06b6d4",
    },
    {
        "id": "US",
        "label": "US (Pacific)",
        "timezone": "America/Los_Angeles",
        "utc_offset": "-08:00",
        "flag": "🇺🇸",
        "coverage": "8:30 PM – 4:30 AM IST",
        "coverage_local": "8:00 AM – 4:00 PM",
        "coverage_local_tz": "PST/PDT",
        "coverage_utc_start": 15,  # 8:30 PM IST = 3:00 PM UTC
        "coverage_utc_end": 23,  # 4:30 AM IST = 11:00 PM UTC
        "color": "#6366f1",
    },
]

# ─── Regional Holidays (2026) ─────────────────────────────────────────────────
REGIONAL_HOLIDAYS = {
    "IST": [
        {"date": "2026-01-26", "name": "Republic Day", "type": "national"},
        {"date": "2026-03-10", "name": "Holi", "type": "festival"},
        {"date": "2026-03-30", "name": "Id-ul-Fitr", "type": "festival"},
        {"date": "2026-04-02", "name": "Ram Navami", "type": "festival"},
        {"date": "2026-04-14", "name": "Ambedkar Jayanti", "type": "national"},
        {"date": "2026-05-01", "name": "May Day", "type": "national"},
        {"date": "2026-08-15", "name": "Independence Day", "type": "national"},
        {"date": "2026-10-02", "name": "Gandhi Jayanti", "type": "national"},
        {"date": "2026-10-20", "name": "Dussehra", "type": "festival"},
        {"date": "2026-11-09", "name": "Diwali", "type": "festival"},
        {"date": "2026-11-10", "name": "Diwali Holiday", "type": "festival"},
        {"date": "2026-12-25", "name": "Christmas", "type": "national"},
    ],
    "TW": [
        {"date": "2026-01-01", "name": "New Year's Day", "type": "national"},
        {"date": "2026-02-17", "name": "Chinese New Year Eve", "type": "national"},
        {"date": "2026-02-18", "name": "Chinese New Year", "type": "national"},
        {"date": "2026-02-19", "name": "Chinese New Year Holiday", "type": "national"},
        {"date": "2026-02-20", "name": "Chinese New Year Holiday", "type": "national"},
        {"date": "2026-02-28", "name": "Peace Memorial Day", "type": "national"},
        {"date": "2026-04-04", "name": "Children's Day", "type": "national"},
        {"date": "2026-04-05", "name": "Tomb Sweeping Day", "type": "national"},
        {"date": "2026-05-31", "name": "Dragon Boat Festival", "type": "national"},
        {"date": "2026-10-04", "name": "Mid-Autumn Festival", "type": "national"},
        {"date": "2026-10-10", "name": "National Day", "type": "national"},
    ],
    "US": [
        {"date": "2026-01-01", "name": "New Year's Day", "type": "national"},
        {"date": "2026-01-19", "name": "MLK Jr. Day", "type": "national"},
        {"date": "2026-02-16", "name": "Presidents' Day", "type": "national"},
        {"date": "2026-05-25", "name": "Memorial Day", "type": "national"},
        {"date": "2026-07-03", "name": "Independence Day (Observed)", "type": "national"},
        {"date": "2026-07-04", "name": "Independence Day", "type": "national"},
        {"date": "2026-09-07", "name": "Labor Day", "type": "national"},
        {"date": "2026-11-26", "name": "Thanksgiving", "type": "national"},
        {"date": "2026-11-27", "name": "Day after Thanksgiving", "type": "company"},
        {"date": "2026-12-25", "name": "Christmas", "type": "national"},
    ],
}

# ─── Hardcoded on-call data from NSC-Escalation-Oncall-Primary ───────────────
# Based on OpsGenie schedule: https://nskope.app.opsgenie.com/schedule/whoIsOnCall
# Note: This is fallback sample data. With OPSGENIE_API_KEY configured,
# live data is fetched from OpsGenie API.

# Hardcoded weekly rotations based on OpsGenie schedule (Feb-Mar 2026)
# Week starts on Monday.
HARDCODED_ROTATIONS = [
    # Week of Feb 9, 2026
    {"week_start": "2026-02-09", "IST": "Kunal Sangodkar", "TW": "Aaron", "US": "Eric"},
    # Week of Feb 16, 2026
    {"week_start": "2026-02-16", "IST": "Pavan Govindraj", "TW": "Roy Wang", "US": "Austin Castleberry"},
    # Week of Feb 23, 2026
    {"week_start": "2026-02-23", "IST": "Kunal Sangodkar", "TW": "Aaron", "US": "Eric"},
    # Week of Mar 2, 2026
    {"week_start": "2026-03-02", "IST": "Pavan Govindraj", "TW": "Roy Wang", "US": "Austin Castleberry"},
    # Week of Mar 9, 2026
    {"week_start": "2026-03-09", "IST": "Kunal Sangodkar", "TW": "Aaron", "US": "Eric"},
    # Week of Mar 16, 2026
    {"week_start": "2026-03-16", "IST": "Pavan Govindraj", "TW": "Roy Wang", "US": "Austin Castleberry"},
    # Week of Mar 23, 2026
    {"week_start": "2026-03-23", "IST": "Kunal Sangodkar", "TW": "Aaron", "US": "Eric"},
]

# ─── Hardcoded Manager On-Call Schedule ──────────────────────────────────────
# Sample data for NSC-Mangers schedule
HARDCODED_MANAGER_ROTATIONS = [
    {"week_start": "2026-02-09", "manager": "Frank Hu"},
    {"week_start": "2026-02-16", "manager": "Rajesh Raman"},
    {"week_start": "2026-02-23", "manager": "Shuangjiang Li"},
    {"week_start": "2026-03-02", "manager": "Frank Hu"},
    {"week_start": "2026-03-09", "manager": "Rajesh Raman"},
    {"week_start": "2026-03-16", "manager": "Shuangjiang Li"},
    {"week_start": "2026-03-23", "manager": "Frank Hu"},
]


def _extract_team_members_from_rotations() -> dict:
    """Extract unique team members from the rotation schedule."""
    teams = {"IST": {}, "TW": {}, "US": {}}

    for rotation in HARDCODED_ROTATIONS:
        for region_id in ["IST", "TW", "US"]:
            name = rotation.get(region_id, "")
            if name and name not in teams[region_id]:
                initial = name[0].upper()
                teams[region_id][name] = {
                    "name": name,
                    "email": f"{name.lower().replace(' ', '.')}@your-company.com",
                    "slack": f"@{name.lower().replace(' ', '.')}",
                    "initial": initial,
                }

    # Convert to lists
    return {region_id: list(members.values()) for region_id, members in teams.items()}


# Extract team members from rotations
REGION_TEAMS = _extract_team_members_from_rotations()


def _get_person_by_name(region_id: str, name: str) -> dict:
    """Find a team member by name in a region."""
    team = REGION_TEAMS.get(region_id, [])
    for person in team:
        if person["name"] == name:
            return person
    # Fallback to first person if not found
    return team[0] if team else {"name": name, "email": "", "slack": ""}


def _calculate_coverage_gaps() -> list[dict]:
    """
    Calculate time gaps between regional coverages.
    Returns list of gap periods in UTC.

    With IST-based timings (all defined in IST):
    - Taiwan: 4:30 AM – 12:30 PM IST  (23:00 – 07:00 UTC, wraps midnight)
    - India:  12:30 PM – 8:30 PM IST  (07:00 – 15:00 UTC)
    - US:     8:30 PM – 4:30 AM IST   (15:00 – 23:00 UTC)

    This provides continuous 24-hour coverage with seamless handoffs.
    """
    # Build coverage intervals, handling wrap-around
    # Convert to a flat timeline (0-48 hours for wrap handling)
    coverage_points = []
    for region in REGIONS:
        start = region["coverage_utc_start"]
        end = region["coverage_utc_end"]

        if start > end:
            # Wraps around midnight (e.g., Taiwan: 23 to 7)
            # Split into two intervals: [start, 24) and [0, end)
            coverage_points.append((start, 24, region["id"]))
            coverage_points.append((0, end, region["id"]))
        else:
            coverage_points.append((start, end, region["id"]))

    # Sort by start time
    coverage_points.sort(key=lambda x: x[0])

    gaps = []

    # Check for gaps in coverage
    # With proper handoffs (Taiwan→India→US→Taiwan), there should be no gaps
    covered_hours = set()
    for start, end, _ in coverage_points:
        for h in range(int(start), int(end)):
            covered_hours.add(h % 24)

    # Find uncovered hours
    all_hours = set(range(24))
    uncovered = sorted(all_hours - covered_hours)

    if uncovered:
        # Group consecutive uncovered hours into gap ranges
        gap_start = uncovered[0]
        prev = gap_start
        for h in uncovered[1:] + [None]:
            if h is None or h != prev + 1:
                gap_end = prev + 1
                gap_hours = gap_end - gap_start
                # Find which regions are adjacent to this gap
                from_region = "Unknown"
                to_region = "Unknown"
                for start, end, rid in coverage_points:
                    if end == gap_start:
                        from_region = rid
                    if start == gap_end:
                        to_region = rid

                gaps.append(
                    {
                        "from_region": from_region,
                        "to_region": to_region,
                        "gap_start_utc": gap_start,
                        "gap_end_utc": gap_end,
                        "gap_hours": gap_hours,
                        "description": f"{_format_utc_time(gap_start)} – {_format_utc_time(gap_end)} UTC",
                    }
                )
                if h is not None:
                    gap_start = h
                    prev = h
            else:
                prev = h

    return gaps


def _format_utc_time(hour: float) -> str:
    """Format hour as HH:MM."""
    h = int(hour) % 24
    m = int((hour % 1) * 60)
    return f"{h:02d}:{m:02d}"


def _get_holidays_for_date(date_str: str) -> list[dict]:
    """Get holidays for a specific date across all regions."""
    holidays = []
    for region_id, region_holidays in REGIONAL_HOLIDAYS.items():
        for holiday in region_holidays:
            if holiday["date"] == date_str:
                holidays.append(
                    {
                        "region": region_id,
                        "name": holiday["name"],
                        "type": holiday["type"],
                    }
                )
    return holidays


def _get_holidays_for_week(week_start: str) -> list[dict]:
    """Get all holidays in a week starting from week_start."""
    start_date = datetime.strptime(week_start, "%Y-%m-%d")
    holidays = []

    for i in range(7):
        day = start_date + timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_holidays = _get_holidays_for_date(day_str)
        for h in day_holidays:
            h["date"] = day_str
            holidays.append(h)

    return holidays


def _generate_sample_data() -> dict[str, Any]:
    """Generate on-call schedule using hardcoded rotation data from OpsGenie."""
    today = datetime.now()
    region_coverage = {r["id"]: r["coverage"] for r in REGIONS}

    rotations = []

    for idx, rotation_data in enumerate(HARDCODED_ROTATIONS):
        week_start = datetime.strptime(rotation_data["week_start"], "%Y-%m-%d")
        week_end = week_start + timedelta(days=6)

        if week_start.date() <= today.date() <= week_end.date():
            status = "active"
        elif week_end.date() < today.date():
            status = "completed"
        else:
            status = "upcoming"

        regions = {}
        for region_id in ["IST", "TW", "US"]:
            person_name = rotation_data.get(region_id, "")
            person = _get_person_by_name(region_id, person_name)
            regions[region_id] = {
                "name": person["name"],
                "email": person.get("email", ""),
                "slack": person.get("slack", ""),
                "coverage": region_coverage[region_id],
                "initial": person.get("initial", person["name"][0]),
            }

        # Get holidays for this week
        week_holidays = _get_holidays_for_week(rotation_data["week_start"])

        rotations.append(
            {
                "id": idx + 1,
                "week_start": rotation_data["week_start"],
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_number": week_start.isocalendar()[1],
                "regions": regions,
                "status": status,
                "holidays": week_holidays,
            }
        )

    current_rotation = next((r for r in rotations if r["status"] == "active"), None)
    next_rotation = next((r for r in rotations if r["status"] == "upcoming"), None)

    # Calculate coverage gaps
    coverage_gaps = _calculate_coverage_gaps()

    return {
        "rotations": rotations,
        "regions": REGIONS,
        "team_members": {rid: team for rid, team in REGION_TEAMS.items()},
        "current_rotation": current_rotation,
        "next_rotation": next_rotation,
        "coverage_gaps": coverage_gaps,
        "holidays": REGIONAL_HOLIDAYS,
        "source": "sample",
        "total_count": len(rotations),
    }


def _generate_manager_sample_data() -> dict[str, Any]:
    """Generate manager on-call schedule using hardcoded rotation data."""
    today = datetime.now()

    rotations = []
    team_members = {}

    for idx, rotation_data in enumerate(HARDCODED_MANAGER_ROTATIONS):
        week_start = datetime.strptime(rotation_data["week_start"], "%Y-%m-%d")
        week_end = week_start + timedelta(days=6)

        if week_start.date() <= today.date() <= week_end.date():
            status = "active"
        elif week_end.date() < today.date():
            status = "completed"
        else:
            status = "upcoming"

        manager_name = rotation_data.get("manager", "")
        manager_email = f"{manager_name.lower().replace(' ', '.')}@your-company.com"

        # Add to team members
        if manager_name not in team_members:
            team_members[manager_name] = {
                "name": manager_name,
                "email": manager_email,
                "slack": f"@{manager_name.lower().replace(' ', '.')}",
            }

        rotations.append(
            {
                "id": idx + 1,
                "week_start": rotation_data["week_start"],
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_number": week_start.isocalendar()[1],
                "regions": {
                    "ALL": {
                        "name": manager_name,
                        "email": manager_email,
                        "slack": f"@{manager_name.lower().replace(' ', '.')}",
                        "coverage": "Full Week",
                    }
                },
                "status": status,
            }
        )

    current_rotation = next((r for r in rotations if r["status"] == "active"), None)
    next_rotation = next((r for r in rotations if r["status"] == "upcoming"), None)

    return {
        "schedule_name": "NSC-Mangers",
        "rotations": rotations,
        "regions": [
            {
                "id": "ALL",
                "label": "All Regions",
                "timezone": "UTC",
                "utc_offset": "+00:00",
                "flag": "🌐",
                "coverage": "Full Week",
                "color": "#10b981",
            }
        ],
        "team_members": {"ALL": list(team_members.values())},
        "current_rotation": current_rotation,
        "next_rotation": next_rotation,
        "source": "sample",
        "total_count": len(rotations),
    }


def _generate_backend_sample_data() -> dict[str, Any]:
    """
    Generate backend on-call schedule placeholder for sample data mode.

    Note: This returns minimal sample data. Live data will be fetched from
    OpsGenie when OPSGENIE_BACKEND_API_KEY is configured.
    """
    return {
        "schedule_name": "NSC Backend Handle",
        "rotations": [],
        "regions": [
            {
                "id": "ALL",
                "label": "All Regions",
                "timezone": "UTC",
                "utc_offset": "+00:00",
                "flag": "🔧",
                "coverage": "Full Week",
                "color": "#ec4899",
            }
        ],
        "team_members": {"ALL": []},
        "current_rotation": None,
        "next_rotation": None,
        "source": "sample",
        "total_count": 0,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/schedules")
async def get_all_schedules() -> dict[str, Any]:
    """
    Get all on-call schedules (Primary + Managers).

    Returns data for both schedules in a unified format for the UI
    to display in a tabbed or card-based layout.
    """
    try:
        if opsgenie_client.is_configured():
            data = await opsgenie_client.get_all_schedules(weeks=8)
            if data and data.get("schedules"):
                # Add metadata and coverage info
                data["schedule_metadata"] = SCHEDULE_METADATA
                data["regions"] = REGIONS
                data["coverage_gaps"] = _calculate_coverage_gaps()
                data["holidays"] = REGIONAL_HOLIDAYS
                return data
            logger.warning("OpsGenie returned no data, falling back to sample")

        # Generate sample data for all schedules
        primary_sample = _generate_sample_data()
        manager_sample = _generate_manager_sample_data()
        backend_sample = _generate_backend_sample_data()

        return {
            "schedules": {
                "primary": {
                    **primary_sample,
                    **SCHEDULE_METADATA["primary"],
                },
                "managers": {
                    **manager_sample,
                    **SCHEDULE_METADATA["managers"],
                },
                "backend": {
                    **backend_sample,
                    **SCHEDULE_METADATA["backend"],
                },
            },
            "schedule_metadata": SCHEDULE_METADATA,
            "regions": REGIONS,
            "coverage_gaps": _calculate_coverage_gaps(),
            "holidays": REGIONAL_HOLIDAYS,
            "source": "sample",
            "configured": opsgenie_client.is_configured(),
        }
    except Exception as e:
        logger.error(f"Error getting all schedules: {e}")
        return {
            "schedules": {},
            "schedule_metadata": SCHEDULE_METADATA,
            "regions": REGIONS,
            "source": "error",
            "error": str(e),
            "configured": opsgenie_client.is_configured(),
        }


@router.get("/schedule")
async def get_on_call_schedule(schedule_type: str = "primary") -> dict[str, Any]:
    """
    Get the on-call rotation schedule for a specific schedule type.

    Args:
        schedule_type: "primary" (engineers) or "managers"

    Uses OpsGenie Timeline API when configured, falls back to sample data.
    """
    try:
        if opsgenie_client.is_configured():
            schedule_name = opsgenie_client.get_schedule_name(schedule_type)
            data = await opsgenie_client.get_schedule_timeline_by_name(schedule_name, weeks=8)
            if data:
                data["coverage_gaps"] = _calculate_coverage_gaps()
                data["holidays"] = REGIONAL_HOLIDAYS
                return data
            logger.warning(f"OpsGenie returned no data for {schedule_type}, falling back to sample")

        if schedule_type == "managers":
            return _generate_manager_sample_data()
        return _generate_sample_data()
    except Exception as e:
        logger.error(f"Error getting on-call schedule: {e}")
        return {
            "rotations": [],
            "regions": REGIONS,
            "team_members": {},
            "current_rotation": None,
            "next_rotation": None,
            "source": "error",
            "error": str(e),
            "total_count": 0,
        }


@router.get("/current")
async def get_current_on_call() -> dict[str, Any]:
    """Get the current on-call for all schedules."""
    try:
        if opsgenie_client.is_configured():
            data = await opsgenie_client.get_all_current_oncall()
            if data:
                return {
                    "primary": data.get("primary"),
                    "managers": data.get("managers"),
                    "backend": data.get("backend"),
                    "regions": REGIONS,
                    "source": "opsgenie",
                }

        # Sample data fallback
        primary_data = _generate_sample_data()
        manager_data = _generate_manager_sample_data()
        backend_data = _generate_backend_sample_data()

        return {
            "primary": {
                "current": primary_data.get("current_rotation"),
                "next": primary_data.get("next_rotation"),
                **SCHEDULE_METADATA["primary"],
            },
            "managers": {
                "current": manager_data.get("current_rotation"),
                "next": manager_data.get("next_rotation"),
                **SCHEDULE_METADATA["managers"],
            },
            "backend": {
                "current": backend_data.get("current_rotation"),
                "next": backend_data.get("next_rotation"),
                **SCHEDULE_METADATA["backend"],
            },
            "regions": REGIONS,
            "source": "sample",
        }
    except Exception as e:
        logger.error(f"Error getting current on-call: {e}")
        return {
            "primary": None,
            "managers": None,
            "backend": None,
            "regions": REGIONS,
            "source": "error",
            "error": str(e),
        }


@router.get("/team")
async def get_on_call_team() -> dict[str, Any]:
    """Get the list of team members per region in the on-call rotation."""
    try:
        if opsgenie_client.is_configured():
            data = await opsgenie_client.get_schedule_timeline(weeks=8)
            if data and data.get("team_members"):
                return {
                    "regions": data.get("regions", REGIONS),
                    "team_members": data["team_members"],
                    "totals": {rid: len(members) for rid, members in data["team_members"].items()},
                }
    except Exception as e:
        logger.warning(f"OpsGenie team fetch failed: {e}")

    return {
        "regions": REGIONS,
        "team_members": {rid: team for rid, team in REGION_TEAMS.items()},
        "totals": {rid: len(team) for rid, team in REGION_TEAMS.items()},
    }


@router.get("/summary")
async def get_on_call_summary() -> dict[str, Any]:
    """Get summary statistics for on-call rotations."""
    try:
        if opsgenie_client.is_configured():
            data = await opsgenie_client.get_schedule_timeline(weeks=8)
            if data:
                rotations = data.get("rotations", [])
                return {
                    "total_weeks": len(rotations),
                    "completed": sum(1 for r in rotations if r.get("status") == "completed"),
                    "active": sum(1 for r in rotations if r.get("status") == "active"),
                    "upcoming": sum(1 for r in rotations if r.get("status") == "upcoming"),
                    "regions": len(data.get("regions", [])),
                    "team_sizes": {rid: len(members) for rid, members in data.get("team_members", {}).items()},
                    "source": "opsgenie",
                }
    except Exception as e:
        logger.warning(f"OpsGenie summary fetch failed: {e}")

    data = _generate_sample_data()
    rotations = data.get("rotations", [])
    return {
        "total_weeks": len(rotations),
        "completed": sum(1 for r in rotations if r.get("status") == "completed"),
        "active": sum(1 for r in rotations if r.get("status") == "active"),
        "upcoming": sum(1 for r in rotations if r.get("status") == "upcoming"),
        "regions": len(REGIONS),
        "team_sizes": {rid: len(team) for rid, team in REGION_TEAMS.items()},
        "source": "sample",
    }


# ─── Coverage Gaps Endpoint ──────────────────────────────────────────────────


@router.get("/coverage-gaps")
async def get_coverage_gaps() -> dict[str, Any]:
    """Get coverage gaps between regional shifts."""
    gaps = _calculate_coverage_gaps()

    # Also provide coverage timeline
    timeline = []
    for region in sorted(REGIONS, key=lambda r: r["coverage_utc_start"]):
        start = region["coverage_utc_start"]
        end = region["coverage_utc_end"]
        if end > 24:
            end -= 24
        timeline.append(
            {
                "region": region["id"],
                "label": region["label"],
                "flag": region["flag"],
                "start_utc": _format_utc_time(start),
                "end_utc": _format_utc_time(end),
                "coverage": region["coverage"],
                "color": region["color"],
            }
        )

    return {
        "gaps": gaps,
        "timeline": timeline,
        "has_gaps": len(gaps) > 0,
        "total_gap_hours": sum(g["gap_hours"] for g in gaps),
    }


# ─── Holidays Endpoint ───────────────────────────────────────────────────────


@router.get("/holidays")
async def get_holidays(year: int = 2026) -> dict[str, Any]:
    """Get all holidays for all regions."""
    return {
        "year": year,
        "holidays": REGIONAL_HOLIDAYS,
        "totals": {region: len(holidays) for region, holidays in REGIONAL_HOLIDAYS.items()},
    }


@router.get("/holidays/{region}")
async def get_holidays_by_region(region: str, year: int = 2026) -> dict[str, Any]:
    """Get holidays for a specific region."""
    region = region.upper()
    if region not in REGIONAL_HOLIDAYS:
        raise HTTPException(status_code=404, detail=f"Region {region} not found")

    return {
        "region": region,
        "year": year,
        "holidays": REGIONAL_HOLIDAYS[region],
        "total": len(REGIONAL_HOLIDAYS[region]),
    }


@router.get("/holidays/date/{date}")
async def get_holidays_for_date(date: str) -> dict[str, Any]:
    """Get holidays for a specific date across all regions."""
    holidays = _get_holidays_for_date(date)
    return {
        "date": date,
        "holidays": holidays,
        "has_holidays": len(holidays) > 0,
    }

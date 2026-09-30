"""
Release Calendar Parser Service

Parses release schedules from multiple sources:
1. Google Calendar (preferred, auto-syncs for date changes)
2. PDF file using PyMuPDF (fallback)

Data Source Priority:
1. If GOOGLE_CALENDAR_ID is configured, uses Google Calendar data
2. Falls back to PDF parsing if calendar not configured or empty

The PDF contains multiple dates per page. Events appearing before a date
header belong to the previous date. Format:
- Events for previous date (continued from prior page)
- Date header: "Mon Feb 2, 2026"
- Events for that date
- etc.

Milestone patterns extracted:
- Branch Cut - EP
- Final Build - EP
- Signoff STG/SJC1/FedAlpha - ENG
- Deploy MP Pre PROD
- Deploy Prod Day 1-4 - CD

IRR is calculated as 1 week before Branch Cut.
"""

import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Flag to track data source
_current_source = "pdf"

# Default PDF path
DEFAULT_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "release_calendar.pdf")

# Month name to number mapping
MONTH_MAP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

# Milestone patterns to search for in PDF
# Format: {milestone_name: regex_pattern}
# The regex should capture the release number (e.g., R134.0)
MILESTONE_PATTERNS = {
    "Branch Cut - EP": r"(R\d{3}\.\d)\s+Branch\s+Cut\s*-\s*EP",
    "Final Build - EP": r"(R\d{3}\.\d)\s+Final\s+Build\s*-\s*EP",
    "Signoff STG/FedAlpha - ENG": r"(R\d{3}\.\d)\s+(?:Signoff|Sign\s+off)\s+(?:STG|SJC|Prod)[/\w]*\s*-\s*ENG",
    # Match both major releases "Deploy MP Pre PROD" and minor releases "Deploy MP / DP Pre Prod"
    "Deploy MP Pre PROD": r"(R\d{3}\.\d)\s+Deploy\s+MP\s*(?:/\s*DP)?\s+Pre\s*-?\s*Prod",
    "Deploy Prod Day 1": r"(R\d{3}\.\d)\s+Deploy\s+Prod\s+Day\s+1",
    "Deploy Prod Day 2": r"(R\d{3}\.\d)\s+Deploy\s+Prod\s+Day\s+2",
    "Deploy Prod Day 3": r"(R\d{3}\.\d)\s+Deploy\s+Prod\s+Day\s+3",
    # Match both "Deploy Prod Day 4" and "Deploy Prod 4" formats
    "Deploy Prod Day 4": r"(R\d{3}\.\d)\s+Deploy\s+Prod\s+(?:Day\s+)?4",
}

# Date header pattern
DATE_PATTERN = re.compile(
    r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})"
)


def calculate_irr_date(branch_cut_date: str) -> str:
    """Calculate IRR date as 1 week before branch cut date."""
    if not branch_cut_date or branch_cut_date == "-":
        return "-"
    try:
        bc_date = datetime.strptime(branch_cut_date, "%d-%b-%Y")
        irr_date = bc_date - timedelta(days=7)
        return irr_date.strftime("%d-%b-%Y")
    except ValueError:
        return "-"


def parse_pdf_with_pymupdf(pdf_path: str) -> dict[str, dict[str, Any]]:
    """
    Parse PDF using PyMuPDF (fitz) for text extraction.

    The PDF contains multiple dates per page. Events appearing before a date
    header belong to the previous date. We track the current date across
    lines and pages.

    Returns dict: {release_name: {"type": str, "milestones": {milestone: date}}}
    """
    releases = defaultdict(lambda: {"type": "", "milestones": {}})

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not installed. Run: pip install pymupdf")
        return {}

    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return {}

    try:
        doc = fitz.open(pdf_path)
        logger.info(f"PDF has {len(doc)} pages")

        # Track the current date across pages
        current_date = None

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            lines = text.split("\n")

            for line in lines:
                # Check if this line is a date header
                date_match = DATE_PATTERN.search(line)
                if date_match:
                    month_str = date_match.group(2)
                    day = int(date_match.group(3))
                    year = int(date_match.group(4))

                    month = MONTH_MAP.get(month_str)
                    if month:
                        try:
                            current_date = datetime(year, month, day)
                            logger.debug(f"Date changed to: {current_date.strftime('%d-%b-%Y')}")
                        except ValueError:
                            pass
                    continue

                # Skip if we don't have a current date yet
                if not current_date:
                    continue

                date_str = current_date.strftime("%d-%b-%Y")

                # Search for each milestone pattern in this line
                for milestone_name, pattern in MILESTONE_PATTERNS.items():
                    matches = re.findall(pattern, line, re.IGNORECASE)
                    for release_name in matches:
                        # Set release type
                        releases[release_name]["type"] = (
                            "Major Release" if release_name.endswith(".0") else "Minor Release"
                        )

                        # Only store the first occurrence of each milestone
                        if milestone_name not in releases[release_name]["milestones"]:
                            releases[release_name]["milestones"][milestone_name] = date_str
                            logger.debug(f"Found: {release_name} {milestone_name} = {date_str}")

        doc.close()
        logger.info(f"Parsed {len(releases)} releases from PDF")

    except Exception as e:
        logger.error(f"Error parsing PDF with PyMuPDF: {e}")
        import traceback

        traceback.print_exc()
        return {}

    return releases


def calculate_irr_dates(releases: dict[str, dict[str, Any]]) -> None:
    """
    Calculate IRR dates for all releases.
    IRR = 1 week before Branch Cut.
    """
    for release_name, data in releases.items():
        milestones = data.get("milestones", {})
        branch_cut = milestones.get("Branch Cut - EP")

        if branch_cut and branch_cut != "-" and "IRR" not in milestones:
            irr_date = calculate_irr_date(branch_cut)
            if irr_date != "-":
                milestones["IRR"] = irr_date
                logger.debug(f"Calculated IRR for {release_name}: {irr_date}")


def calculate_release_status(milestones: dict[str, str]) -> str:
    """Calculate release status based on milestone dates."""
    today = datetime.now().date()

    dates = []
    for date_str in milestones.values():
        if date_str and date_str != "-":
            try:
                parsed = datetime.strptime(date_str, "%d-%b-%Y").date()
                dates.append(parsed)
            except ValueError:
                continue

    if not dates:
        return "Planned"

    min_date = min(dates)
    max_date = max(dates)

    if today > max_date:
        return "Completed"
    elif today >= min_date:
        return "In Progress"
    else:
        return "Planned"


def determine_current_release(releases: list[dict[str, Any]]) -> str | None:
    """
    Determine which release is current based on Final Build dates.

    Logic: A release becomes "current" when the previous release's Final Build has passed.
    Only considers major releases (.0 releases).
    """
    today = datetime.now().date()

    # Filter to major releases only and sort by release number descending
    major_releases = [r for r in releases if r.get("name", "").endswith(".0")]
    major_releases.sort(key=lambda r: int(r["name"].replace("R", "").replace(".0", "")), reverse=True)

    if not major_releases:
        return None

    # Check each release from newest to oldest
    for i, release in enumerate(major_releases):
        release_name = release["name"]

        # Get the next release (previous in timeline, older release)
        if i + 1 < len(major_releases):
            prev_release = major_releases[i + 1]
            prev_final_build_str = prev_release.get("milestones", {}).get("Final Build - EP", "")

            if prev_final_build_str and prev_final_build_str != "-":
                try:
                    prev_final_build = datetime.strptime(prev_final_build_str, "%d-%b-%Y").date()

                    # If previous release's Final Build has passed, this release is current
                    if today > prev_final_build:
                        logger.info(
                            f"Release {release_name} is current "
                            f"(previous release {prev_release['name']} Final Build {prev_final_build} has passed)"
                        )
                        return release_name
                except ValueError:
                    pass
        else:
            # This is the oldest release - check if it's still in progress
            final_build_str = release.get("milestones", {}).get("Final Build - EP", "")
            if final_build_str and final_build_str != "-":
                try:
                    final_build = datetime.strptime(final_build_str, "%d-%b-%Y").date()
                    if today <= final_build:
                        return release_name
                except ValueError:
                    pass

    # Fallback to newest release
    return major_releases[0]["name"] if major_releases else None


def parse_pdf_file(pdf_path: str) -> dict[str, dict[str, Any]]:
    """
    Parse a PDF file and extract release calendar data.

    Uses PyMuPDF to extract milestone dates from the release calendar PDF.
    Calculates IRR as 1 week before Branch Cut.
    """
    # Parse PDF with PyMuPDF
    releases = parse_pdf_with_pymupdf(pdf_path)

    # Calculate IRR dates from Branch Cut
    calculate_irr_dates(releases)

    return releases


def _get_calendar_releases() -> dict[str, dict[str, Any]] | None:
    """
    Try to get release data from Google Calendar cache.

    Returns:
        Cached calendar releases or None if not available
    """
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "")
    if not calendar_id:
        return None

    try:
        from services.gcalendar_client import get_cached_calendar_data

        return get_cached_calendar_data()
    except ImportError:
        logger.debug("Google Calendar client not available")
        return None
    except Exception as e:
        logger.warning(f"Error getting calendar data: {e}")
        return None


def get_release_calendar_data(pdf_path: str | None = None) -> dict[str, Any]:
    """
    Get release calendar data from Google Calendar or PDF.

    Data Sources (in priority order):
    1. Google Calendar: If GOOGLE_CALENDAR_ID is configured and data is cached
    2. PDF: Fallback when calendar not configured or unavailable
    - Calculated: IRR (1 week before Branch Cut)

    Args:
        pdf_path: Path to PDF file. Uses default path if not provided.

    Returns:
        Dictionary with release calendar data
    """
    global _current_source

    if pdf_path is None:
        pdf_path = DEFAULT_PDF_PATH

    milestones = [
        "IRR",
        "Branch Cut - EP",
        "Final Build - EP",
        "Signoff STG/FedAlpha - ENG",
        "Deploy MP Pre PROD",
        "Deploy Prod Day 1",
        "Deploy Prod Day 2",
        "Deploy Prod Day 3",
        "Deploy Prod Day 4",
    ]

    # Try Google Calendar first
    calendar_releases = _get_calendar_releases()

    if calendar_releases:
        parsed_releases = calendar_releases
        _current_source = "google_calendar"
        logger.info(f"Using {len(parsed_releases)} releases from Google Calendar")
    else:
        # Fall back to PDF parsing
        parsed_releases = parse_pdf_file(pdf_path)
        _current_source = "pdf"
        logger.info(f"Parsed {len(parsed_releases)} releases from PDF")

    # Convert to list format with IDs
    releases_list = []
    for idx, (name, data) in enumerate(sorted(parsed_releases.items()), start=1):
        release_milestones = data.get("milestones", {})

        # Ensure all milestone keys exist
        for m in milestones:
            if m not in release_milestones:
                release_milestones[m] = "-"

        releases_list.append(
            {
                "id": idx,
                "name": name,
                "type": data.get("type", "Major Release"),
                "status": calculate_release_status(release_milestones),
                "milestones": release_milestones,
            }
        )

    # Determine and mark current release
    current_release_name = determine_current_release(releases_list)
    for release in releases_list:
        # Mark as current if it matches, or if it's the corresponding minor release
        # e.g., R135.1 is current if R135.0 is current
        release_base = release["name"].split(".")[0]  # R135.0 -> R135
        current_base = current_release_name.split(".")[0] if current_release_name else None
        release["is_current"] = release_base == current_base

    return {
        "releases": releases_list,
        "milestones": milestones,
        "source": _current_source,
        "pdf_path": pdf_path if _current_source == "pdf" and os.path.exists(pdf_path) else None,
        "total_count": len(releases_list),
        "current_release": current_release_name,
    }


async def get_release_calendar_data_async(pdf_path: str | None = None) -> dict[str, Any]:
    """
    Async version of get_release_calendar_data.

    PDF parsing is synchronous, so this just wraps the sync version.
    """
    return get_release_calendar_data(pdf_path)

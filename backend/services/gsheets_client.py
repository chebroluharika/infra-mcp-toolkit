"""
Google Sheets Client Service

Provides direct access to Google Sheets API for fetching spreadsheet data.
Used for NPLANs tracking and other Google Sheets integrations.

Usage:
    from services.gsheets_client import get_nplans_for_release
    nplans = await get_nplans_for_release("135")
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from config import get_sheet_config, settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class GoogleSheetsClient:
    """Client for Google Sheets API with caching"""

    _instance: Optional["GoogleSheetsClient"] = None

    def __init__(self):
        self._service = None
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "GoogleSheetsClient":
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _initialize(self) -> bool:
        """Initialize Google Sheets API client"""
        if self._initialized:
            return self._service is not None

        service_account_file = settings.google_service_account_file
        if not service_account_file:
            service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")

        if not service_account_file or not os.path.exists(service_account_file):
            logger.warning(
                "Google Sheets service account file not configured. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE environment variable."
            )
            self._initialized = True
            return False

        try:
            credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
            self._service = build("sheets", "v4", credentials=credentials)
            self._initialized = True
            logger.info("Google Sheets client initialized successfully")
            return True
        except Exception as e:
            logger.error("Failed to initialize Google Sheets client: %s", e)
            self._initialized = True
            return False

    def get_sheet_data(self, spreadsheet_id: str, range_notation: str, include_headers: bool = True) -> Dict[str, Any]:
        """Get data from a sheet range"""
        if not self._initialize():
            return {"error": "Google Sheets not configured", "data": [], "headers": []}

        try:
            result = (
                self._service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_notation).execute()
            )
            values = result.get("values", [])

            if not values:
                return {"range": range_notation, "headers": [], "data": [], "row_count": 0}

            if include_headers and len(values) > 0:
                headers = values[0]
                data_rows = values[1:]

                # Determine max columns needed
                max_cols = len(headers)
                if data_rows:
                    max_cols = max(max_cols, max(len(r) for r in data_rows))

                # Convert rows to dicts with header keys
                data = []
                for row in data_rows:
                    row_dict = {}
                    for i in range(max_cols):
                        key = headers[i] if i < len(headers) else f"col_{i}"
                        value = row[i] if i < len(row) else ""
                        row_dict[key] = value
                    data.append(row_dict)

                return {
                    "range": range_notation,
                    "headers": headers,
                    "data": data,
                    "row_count": len(data),
                }

            return {"range": range_notation, "headers": [], "data": values, "row_count": len(values)}

        except HttpError as e:
            logger.error("Google Sheets API error: %s", e)
            return {"error": str(e), "data": [], "headers": []}
        except Exception as e:
            logger.error("Error fetching sheet data: %s", e)
            return {"error": str(e), "data": [], "headers": []}


def get_sheets_client() -> GoogleSheetsClient:
    """Get Google Sheets client singleton"""
    return GoogleSheetsClient.get_instance()


def parse_nplan_entry(entry: str) -> Dict[str, str]:
    """
    Parse NPLAN entry from the spreadsheet.

    Examples:
        "NPLAN-5417 - NPA | Client to LBR selection Improvements (Linux regression only)"
        "ENG-697627 - Improper validation of JWT token..."
        "[NPLAN-1234] Some description"
        "NPLAN1234 - description" (no dash between letters and numbers)

    Returns:
        {"id": "NPLAN-5417", "description": "NPA | Client to LBR..."}
    """
    if not entry:
        return {"id": "", "description": ""}

    entry = entry.strip()

    # Pattern 1: Standard format "PROJ-1234 - description" or "PROJ-1234: description"
    match = re.match(r"^([A-Z]+-\d+)\s*[-:]\s*(.*)$", entry)
    if match:
        return {"id": match.group(1), "description": match.group(2).strip()}

    # Pattern 2: Bracketed format "[PROJ-1234] description"
    match = re.match(r"^\[([A-Z]+-\d+)\]\s*(.*)$", entry)
    if match:
        return {"id": match.group(1), "description": match.group(2).strip()}

    # Pattern 3: No dash between letters and numbers "PROJ1234 - description"
    match = re.match(r"^([A-Z]+)(\d+)\s*[-:]\s*(.*)$", entry)
    if match:
        # Reconstruct with dash
        jira_id = f"{match.group(1)}-{match.group(2)}"
        return {"id": jira_id, "description": match.group(3).strip()}

    # Pattern 4: Just the JIRA ID anywhere in the string (extract it)
    match = re.search(r"([A-Z]+-\d+)", entry)
    if match:
        jira_id = match.group(1)
        # Remove the ID from description
        description = entry.replace(jira_id, "").strip()
        # Clean up extra separators
        description = re.sub(r"^[-:\s]+", "", description).strip()
        return {"id": jira_id, "description": description if description else entry}

    # If no match, treat entire string as description
    return {"id": "", "description": entry}


def normalize_status(status: str) -> str:
    """Normalize QA status to consistent values"""
    if not status:
        return "TBD"

    status_upper = status.upper().strip()

    if status_upper in ("SHIPPED", "DONE", "COMPLETE", "COMPLETED"):
        return "SHIPPED"
    elif status_upper in ("ONTRACK", "ON TRACK", "IN PROGRESS", "WIP"):
        return "ONTRACK"
    elif status_upper in ("ON HOLD", "ONHOLD", "HOLD", "BLOCKED"):
        return "ON HOLD"
    elif status_upper in ("TBD", "TO BE DECIDED", "PENDING", ""):
        return "TBD"
    elif status_upper in ("MOVED", "DEFERRED"):
        return "MOVED"
    else:
        return status.strip()


def find_column_value(row: Dict, possible_keys: List[str], default: str = "") -> str:
    """Find a value from a row using multiple possible column keys."""
    for key in possible_keys:
        if key in row and row[key]:
            return str(row[key]).strip()
    return default


async def get_nplans_for_release(release: str) -> Dict[str, Any]:
    """
    Fetch NPLANs/Features for a specific release.

    Args:
        release: Release version (e.g., "135", "R135", "135.0.0")

    Returns:
        {
            "release": "135",
            "total": 12,
            "items": [...],
            "by_status": {"SHIPPED": 5, "ONTRACK": 4, "TBD": 3},
            "spreadsheet_url": "...",
        }
    """
    # Normalize release number (extract just the number)
    release_num = re.sub(r"[^\d]", "", release.split(".")[0])

    config = get_sheet_config("nplans")
    if not config:
        logger.error("NPLANs sheet not configured in config.py")
        return {
            "error": "NPLANs sheet not configured",
            "release": release_num,
            "total": 0,
            "items": [],
            "by_status": {},
        }

    spreadsheet_id = config.get("spreadsheet_id")
    sheet_name = config.get("sheet_name", "WEEKLY STATUS REPORT")
    data_range = config.get("data_range", "A3:K100")

    # Construct range notation
    range_notation = f"'{sheet_name}'!{data_range}"

    logger.info(f"Fetching NPLANs from {spreadsheet_id}, range: {range_notation}")

    client = get_sheets_client()
    result = client.get_sheet_data(spreadsheet_id, range_notation, include_headers=True)

    if "error" in result:
        logger.error("Failed to fetch NPLANs: %s", result["error"])
        return {
            "error": result["error"],
            "release": release_num,
            "total": 0,
            "items": [],
            "by_status": {},
        }

    # Log headers for debugging
    headers = result.get("headers", [])
    logger.info(f"NPLANs sheet headers: {headers}")
    logger.info(f"NPLANs sheet row count: {result.get('row_count', 0)}")

    # Parse and filter data
    items = []
    by_status = {}

    # Possible column names for each field (flexible matching)
    # Structure: Column A = NPLAN entry, Column B = Release number
    nplan_keys = ["col_0", "NPLANs / FEATURES", "NPLANS / FEATURES", "NPLANs", "NPLAN", "FEATURES", "col_1"]
    id_keys = ["ID", "JIRA ID", "JIRA", "NPLAN ID", "TICKET", "KEY"]
    release_keys = ["col_1", "RELEASE", "Release", "release", "col_7"]
    status_keys = ["col_2", "QA STATUS", "QA Status", "STATUS", "Status", "QA_STATUS", "col_8"]
    notes_keys = ["col_3", "NOTES", "Notes", "COMMENTS", "COMMENT", "col_9", "col_10"]

    # Also try to detect columns from headers
    header_to_index = {h: i for i, h in enumerate(headers)}
    logger.info(f"Header mapping: {header_to_index}")

    # Detect if there's a separate ID column
    separate_id_col = None
    for h in headers:
        if h and h.upper() in ["ID", "JIRA ID", "JIRA", "NPLAN ID", "TICKET", "KEY"]:
            separate_id_col = h
            logger.info(f"Found separate ID column: {separate_id_col}")
            break

    for idx, row in enumerate(result.get("data", [])):
        # Try to get values by column index (A=0, B=1, etc.) or by header name
        # Column A (index 0) = NPLAN entry
        nplan_entry = ""
        if headers and len(headers) > 0:
            first_header = headers[0]
            nplan_entry = row.get(first_header, "") or row.get("col_0", "")
        if not nplan_entry:
            nplan_entry = find_column_value(row, nplan_keys)

        # Skip empty rows
        if not nplan_entry or not nplan_entry.strip():
            continue

        # Column B (index 1) = Release number
        row_release = ""
        if headers and len(headers) > 1:
            second_header = headers[1]
            row_release = str(row.get(second_header, "") or row.get("col_1", "")).strip()
        if not row_release:
            row_release = find_column_value(row, release_keys)

        # Log first few rows for debugging
        if idx < 5:
            logger.info(f"Row {idx}: nplan='{nplan_entry[:60] if nplan_entry else ''}', release='{row_release}'")

        # Normalize row release for comparison
        # Extract major version only (e.g., "137" from "137", "137.0", "137.1", "R137")
        # We want to match ONLY the major release (137.0) and exclude patch releases (137.1)
        row_release_clean = row_release.upper().replace("R", "").strip() if row_release else ""

        # Check if this is a patch release (has .1, .2, etc. - anything other than .0)
        is_patch_release = False
        if "." in row_release_clean:
            parts = row_release_clean.split(".")
            if len(parts) >= 2:
                minor_version = parts[1].strip()
                # If minor version is not "0" or empty, it's a patch release
                if minor_version and minor_version != "0":
                    is_patch_release = True
                    logger.debug(f"Skipping patch release: {row_release} (minor version: {minor_version})")

        # Skip patch releases (e.g., 137.1) - only include major releases (137 or 137.0)
        if is_patch_release:
            continue

        # Extract just the major version number for matching
        row_release_num = re.sub(r"[^\d]", "", row_release_clean.split(".")[0]) if row_release_clean else ""

        # Handle "9" prefix convention: older releases (R133-R135) have "9" prepended
        # (e.g., "9133", "9134", "9135") to sort lower in the spreadsheet.
        # Match both exact release number AND release number with "9" prefix.
        release_matches = row_release_num == release_num or row_release_num == f"9{release_num}"

        # Skip if release doesn't match
        if not release_matches:
            continue

        # Log when "9" prefix matching is used
        if row_release_num == f"9{release_num}":
            logger.debug(f"Matched release {release_num} via '9' prefix convention (sheet value: {row_release_num})")

        # Parse the NPLAN entry
        parsed = parse_nplan_entry(nplan_entry)

        # Check for separate ID column if parsing didn't find an ID
        if not parsed["id"]:
            # Try to find ID in separate column
            separate_id = ""
            if separate_id_col:
                separate_id = str(row.get(separate_id_col, "")).strip()
            if not separate_id:
                separate_id = find_column_value(row, id_keys)

            if separate_id:
                # Validate it looks like a JIRA ID
                if re.match(r"^[A-Z]+-\d+$", separate_id):
                    parsed["id"] = separate_id
                    logger.debug(f"Found ID from separate column: {separate_id}")

            # Also try to extract ID from any column in the row
            if not parsed["id"]:
                for key, value in row.items():
                    if value and isinstance(value, str):
                        id_match = re.search(r"([A-Z]+-\d+)", value)
                        if id_match:
                            parsed["id"] = id_match.group(1)
                            logger.debug(f"Found ID from column '{key}': {parsed['id']}")
                            break

        # Column C (index 2) = Status (if exists)
        raw_status = ""
        if headers and len(headers) > 2:
            third_header = headers[2]
            raw_status = row.get(third_header, "") or ""
        if not raw_status:
            raw_status = find_column_value(row, status_keys)
        status = normalize_status(raw_status)

        # Column D+ = Notes (if exists)
        notes = ""
        if headers and len(headers) > 3:
            fourth_header = headers[3]
            notes = row.get(fourth_header, "") or ""
        if not notes:
            notes = find_column_value(row, notes_keys)

        item = {
            "id": parsed["id"],
            "description": parsed["description"],
            "release": row_release,
            "status": status,
            "raw_status": raw_status,
            "notes": notes,
            "jira_url": f"https://your-org.atlassian.net/browse/{parsed['id']}" if parsed["id"] else "",
            "raw_entry": nplan_entry[:200] if nplan_entry else "",  # For debugging
        }
        items.append(item)

        # Log items without ID for debugging
        if not parsed["id"]:
            logger.warning(
                f"Row {idx} has no parsed ID. Entry: '{nplan_entry[:80]}...' Row data: {list(row.items())[:4]}"
            )
        else:
            logger.debug(f"Added NPLAN: {parsed['id']} - {status}")

        # Count by status
        by_status[status] = by_status.get(status, 0) + 1

    logger.info(f"NPLANs for release {release_num}: found {len(items)} items, status breakdown: {by_status}")

    return {
        "release": release_num,
        "total": len(items),
        "items": items,
        "by_status": by_status,
        "spreadsheet_url": config.get("url", ""),
        "debug": {
            "headers_found": headers,
            "total_rows_in_sheet": result.get("row_count", 0),
        },
    }

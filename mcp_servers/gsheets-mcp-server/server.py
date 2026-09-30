# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.0.0",
#   "google-api-python-client>=2.100.0",
#   "google-auth-httplib2>=0.1.1",
#   "google-auth-oauthlib>=1.1.0",
#   "python-dotenv>=1.0.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
Google Sheets MCP Server
Exposes Google Sheets API as MCP tools for AI agents

Usage:
    uv run server.py

Environment Variables:
    GOOGLE_SERVICE_ACCOUNT_FILE - Path to service account JSON key
"""

import os
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("gsheets-mcp-server")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


# ============ Google Sheets Client ============


class SheetsClient:
    """Client for Google Sheets API with caching"""

    def __init__(self):
        self.service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not self.service_account_file or not os.path.exists(self.service_account_file):
            raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_FILE to path of service account JSON")

        credentials = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=SCOPES)
        self._service = build("sheets", "v4", credentials=credentials)

    def get_spreadsheet_info(self, spreadsheet_id: str) -> Dict[str, Any]:
        """Get spreadsheet metadata including all sheet names"""
        result = self._service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return {
            "spreadsheet_id": spreadsheet_id,
            "title": result.get("properties", {}).get("title"),
            "sheets": [
                {
                    "title": s["properties"]["title"],
                    "sheetId": s["properties"]["sheetId"],
                    "index": s["properties"]["index"],
                    "row_count": s["properties"]["gridProperties"]["rowCount"],
                }
                for s in result.get("sheets", [])
            ],
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
        }

    def get_sheet_data(self, spreadsheet_id: str, range_notation: str, include_headers: bool = True) -> Dict[str, Any]:
        """Get data from a sheet range, optionally parsing headers"""
        result = self._service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_notation).execute()
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

            return {"range": range_notation, "headers": headers, "data": data, "row_count": len(data)}

        return {"range": range_notation, "headers": [], "data": values, "row_count": len(values)}

    def query_sheet(  # pylint: disable=too-many-arguments
        self,
        spreadsheet_id: str,
        sheet_name: str,
        filters: Optional[Dict[str, str]] = None,
        columns: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Query sheet data with optional filtering and column selection"""
        data = self.get_sheet_data(spreadsheet_id, sheet_name)
        results = data["data"]

        # Apply filters (case-insensitive match)
        if filters:
            results = [
                r for r in results if all(str(r.get(k, "")).lower() == str(v).lower() for k, v in filters.items())
            ]

        total = len(results)

        # Apply limit
        if limit:
            results = results[:limit]

        # Select specific columns
        if columns:
            results = [{k: v for k, v in r.items() if k in columns} for r in results]

        return {"results": results, "total": total, "returned": len(results)}

    def get_sheet_summary(self, spreadsheet_id: str, sheet_name: str, group_by: Optional[str] = None) -> Dict[str, Any]:
        """Get summary statistics, optionally grouped by a column"""
        data = self.get_sheet_data(spreadsheet_id, sheet_name)
        summary = {"total_rows": data["row_count"], "columns": data["headers"]}

        if group_by and group_by in data["headers"]:
            counts: Dict[str, int] = {}
            for row in data["data"]:
                val = str(row.get(group_by, "Empty"))
                counts[val] = counts.get(val, 0) + 1
            summary["group_by"] = group_by
            summary["counts"] = counts

        return summary


# Client instance (lazy singleton)
_client: SheetsClient | None = None


def get_client() -> SheetsClient:
    """Get or create the sheets client singleton."""
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = SheetsClient()
    return _client


# ============ MCP Tools ============


@mcp.tool()
def gsheets_get_spreadsheet_info(spreadsheet_id: str) -> Dict[str, Any]:
    """Get spreadsheet metadata including all sheet names."""
    return get_client().get_spreadsheet_info(spreadsheet_id)


@mcp.tool()
def gsheets_get_sheet_data(spreadsheet_id: str, range_notation: str, include_headers: bool = True) -> Dict[str, Any]:
    """
    Get data from a sheet.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID
        range_notation: Sheet name or A1 notation (e.g., 'Sheet1' or 'Sheet1!A1:D10')
        include_headers: If True, first row is treated as headers
    """
    return get_client().get_sheet_data(spreadsheet_id, range_notation, include_headers)


@mcp.tool()
def gsheets_query_sheet(
    spreadsheet_id: str,
    sheet_name: str,
    filters: Optional[Dict[str, str]] = None,
    columns: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Query sheet data with filters.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID
        sheet_name: Name of the sheet to query
        filters: Optional dict of {column_name: value} to filter rows
        columns: Optional list of column names to return
        limit: Optional max number of results
    """
    return get_client().query_sheet(spreadsheet_id, sheet_name, filters, columns, limit)


@mcp.tool()
def gsheets_get_sheet_summary(spreadsheet_id: str, sheet_name: str, group_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Get summary stats for a sheet.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID
        sheet_name: Name of the sheet
        group_by: Optional column name to group and count by
    """
    return get_client().get_sheet_summary(spreadsheet_id, sheet_name, group_by)


@mcp.tool()
def gsheets_get_feature_owners(spreadsheet_id: str, sheet_name: str = "Feature Owners") -> List[Dict]:
    """Get feature owner mappings from a Feature Owners sheet."""
    return get_client().get_sheet_data(spreadsheet_id, sheet_name)["data"]


@mcp.tool()
def gsheets_get_release_data(
    spreadsheet_id: str, sheet_name: str = "Releases", release_name: Optional[str] = None
) -> Any:
    """
    Get release tracking data.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID
        sheet_name: Name of the releases sheet (default: "Releases")
        release_name: Optional specific release to filter for
    """
    data = get_client().get_sheet_data(spreadsheet_id, sheet_name)["data"]

    if release_name:
        for row in data:
            if row.get("Release") == release_name or row.get("Version") == release_name:
                return row
        return {}

    return data


if __name__ == "__main__":
    # Run with stdio transport (required for subprocess communication)
    mcp.run(transport="stdio")

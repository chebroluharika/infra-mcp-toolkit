# Google Sheets MCP Server

Model Context Protocol (MCP) server that exposes Google Sheets API as tools for AI agents.

## Tools Provided

| Tool | Description |
|------|-------------|
| `gsheets_get_spreadsheet_info` | Get spreadsheet metadata including all sheet names |
| `gsheets_get_sheet_data` | Get data from a sheet (supports A1 notation) |
| `gsheets_query_sheet` | Query sheet data with filters |
| `gsheets_get_sheet_summary` | Get summary stats with optional grouping |
| `gsheets_get_feature_owners` | Get feature owner mappings |
| `gsheets_get_release_data` | Get release tracking data |

## Environment Variables

```bash
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
```

## Running the Server

```bash
cd agents/gsheets-mcp-server
uv run server.py
```

## Usage

The server is automatically started by the backend's MCP client manager. You can also run it standalone for testing.

## Service Account Setup

1. Go to Google Cloud Console
2. Create a new project or select existing
3. Enable Google Sheets API
4. Create a Service Account
5. Download the JSON key file
6. Share your spreadsheets with the service account email

## Tool Details

### `gsheets_get_spreadsheet_info`
Get spreadsheet metadata including all sheet names, IDs, and row counts.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID

**Returns:**
- `spreadsheet_id`, `title`, `url`
- `sheets`: List of sheet metadata (title, sheetId, index, row_count)

### `gsheets_get_sheet_data`
Get data from a sheet range, optionally parsing headers.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID
- `range` (str): Sheet name or A1 notation (e.g., 'Sheet1' or 'Sheet1!A1:D10')
- `include_headers` (bool): If True, first row is treated as headers (default: True)

**Returns:**
- `range`, `headers`, `data` (list of dicts if headers, else list of lists), `row_count`

### `gsheets_query_sheet`
Query sheet data with optional filtering and column selection.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID
- `sheet_name` (str): Name of the sheet to query
- `filters` (dict, optional): Dict of {column_name: value} for filtering (case-insensitive)
- `columns` (list, optional): List of column names to return
- `limit` (int, optional): Max number of results

**Returns:**
- `results`: Filtered data rows
- `total`: Total matching rows
- `returned`: Number of rows returned (after limit)

### `gsheets_get_sheet_summary`
Get summary statistics for a sheet, optionally grouped by a column.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID
- `sheet_name` (str): Name of the sheet
- `group_by` (str, optional): Column name to group and count by

**Returns:**
- `total_rows`, `columns`
- `group_by`, `counts` (if group_by specified): Dict of value → count

### `gsheets_get_feature_owners`
Get feature owner mappings from a Feature Owners sheet.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID
- `sheet_name` (str): Sheet name (default: "Feature Owners")

### `gsheets_get_release_data`
Get release tracking data, optionally filtered by release name.

**Parameters:**
- `spreadsheet_id` (str): The Google Sheets spreadsheet ID
- `sheet_name` (str): Sheet name (default: "Releases")
- `release_name` (str, optional): Specific release to filter for

**Returns:**
- If `release_name` specified: Single row dict or empty dict
- Otherwise: All release rows

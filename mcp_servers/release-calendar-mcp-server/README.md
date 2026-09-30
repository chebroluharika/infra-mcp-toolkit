# Release Calendar MCP Server

MCP (Model Context Protocol) server for Release Calendar integration.

Data is sourced from the Release Calendar PDF parsed by the backend API.

## Features

- Get release milestone dates (IRR, Branch Cut, Final Build, Deploy dates)
- Track upcoming milestones
- Progress tracking per release
- Calculated dates follow business day rules (skip weekends)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CURRENT_RELEASE` | Yes | Current release identifier (e.g., R134) |
| `API_BASE_URL` | No | Backend API URL (default: http://localhost:8000) |

## Data Source

Release dates are parsed from `backend/data/release_calendar.pdf`:
- **From PDF**: Branch Cut - EP, Final Build - EP
- **Calculated**: IRR (1 week before Branch Cut)
- **Calculated (business days)**: Signoff, Deploy MP Pre, Deploy Prod Day 1-4

## Available Tools

### `calendar_get_info`

Get calendar configuration information.

**Parameters:** None

**Returns:**
- `configured`: Always true (PDF-based)
- `source`: "release-calendar-pdf"
- `current_release`: Current release identifier

### `calendar_get_release_dates`

Get key dates for a specific release.

**Parameters:**
- `release` (string): Release identifier (e.g., "R134")

**Returns:**
- `milestones`: List of milestones with:
  - `name`: Milestone name
  - `date`: Date string (DD-Mon-YYYY)
  - `status`: "completed", "current", or "upcoming"
  - `days_away`: Days until milestone
  - `icon`: Display icon
- `summary`:
  - `total`: Total milestones
  - `completed`: Completed count
  - `progress_pct`: Progress percentage
  - `next_milestone`: Next upcoming milestone
- `display`: Formatted markdown table for AI display

### `calendar_get_upcoming_milestones`

Get upcoming milestones for a release.

**Parameters:**
- `release` (string): Release identifier
- `count` (int): Maximum milestones to return (default: 5)

**Returns:**
- `upcoming`: List of upcoming milestones with days_away
- `source`: "release-calendar"

## Usage

### With UV

```bash
cd mcp_servers/release-calendar-mcp-server
uv run server.py
```

### With Python

```bash
cd mcp_servers/release-calendar-mcp-server
pip install mcp httpx python-dotenv pydantic
python server.py
```

## API Endpoint

This server calls the backend API:
- `GET /api/release-calendar/releases/{release_name}` - Get release milestones

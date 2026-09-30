# Google Sheets Configuration Guide

How to set up Google Sheets integration for the Agentic Insights Portal.

---

## Overview

The dashboard uses Google Sheets for:
- Manual test execution tracking
- Weekly status reports
- Feature owner mappings
- Release tracking data

---

## Setup Steps

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Enter project name: `qe-dashboard`
4. Click "Create"

### Step 2: Enable Google Sheets API

1. In Google Cloud Console, go to "APIs & Services" → "Library"
2. Search for "Google Sheets API"
3. Click on it and click "Enable"

### Step 3: Create a Service Account

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Enter details:
   - Name: `qe-dashboard-sheets`
   - Description: `Service account for Agentic Insights Portal Google Sheets access`
4. Click "Create and Continue"
5. Skip the optional steps, click "Done"

### Step 4: Generate JSON Key

1. Click on the service account you just created
2. Go to "Keys" tab
3. Click "Add Key" → "Create new key"
4. Select "JSON" format
5. Click "Create"
6. Save the downloaded file as `service-account.json`

### Step 5: Share Spreadsheets with Service Account

1. Open your Google Spreadsheet
2. Click "Share" button
3. Add the service account email (looks like: `qe-dashboard-sheets@project-id.iam.gserviceaccount.com`)
4. Give "Viewer" permission (or "Editor" if write access needed)
5. Click "Share"

---

## Environment Configuration

Set the environment variable pointing to your JSON key file:

```bash
# In backend/.env
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json

# Or for Docker
GOOGLE_SERVICE_ACCOUNT_FILE=/app/credentials/service-account.json
```

---

## Expected Spreadsheet Structure

### Manual Execution Spreadsheet

The dashboard expects sheets with test execution data:

| Column | Description |
|--------|-------------|
| Test Case ID | Unique identifier |
| Test Case Name | Name of the test |
| Status | Passed, Failed, Blocked, Not Run |
| Assignee | Tester name |
| Platform | iOS, Android, Windows, etc. |
| Category | Feature category |

**Example structure:**

```
Sheet: "iOS Execution"
┌──────────────┬─────────────────────┬─────────┬──────────┬──────────┐
│ Test Case ID │ Test Case Name      │ Status  │ Assignee │ Platform │
├──────────────┼─────────────────────┼─────────┼──────────┼──────────┤
│ TC-001       │ Login test          │ Passed  │ John     │ iOS      │
│ TC-002       │ Logout test         │ Failed  │ Jane     │ iOS      │
│ TC-003       │ Settings test       │ Not Run │ Bob      │ iOS      │
└──────────────┴─────────────────────┴─────────┴──────────┴──────────┘
```

### Weekly Status Spreadsheet

For weekly status reports:

| Column | Description |
|--------|-------------|
| Date | Week date |
| Release | Release ID (R133, R134) |
| Automation Progress | Percentage |
| Manual Progress | Percentage |
| Blockers | List of blockers |
| Notes | Additional notes |

### Feature Owners Spreadsheet

For mapping features to owners:

| Column | Description |
|--------|-------------|
| Feature | Feature name |
| Owner | Owner name |
| Team | Team name |
| Platform | Platforms covered |

---

## API Usage

### Get Spreadsheet Info

```bash
curl http://localhost:8000/api/gsheets/spreadsheet-info?spreadsheet_id=YOUR_SHEET_ID
```

### Get Sheet Data

```bash
curl http://localhost:8000/api/gsheets/data?spreadsheet_id=YOUR_SHEET_ID&sheet_name=Sheet1
```

### Get Manual Execution Status

```bash
curl http://localhost:8000/api/gsheets/manual-execution?spreadsheet_id=YOUR_SHEET_ID
```

---

## MCP Server Tools

The GSheets MCP Server provides these tools:

| Tool | Description |
|------|-------------|
| `gsheets_get_spreadsheet_info` | Get spreadsheet metadata |
| `gsheets_get_sheet_data` | Get data from a sheet |
| `gsheets_query_sheet` | Query with filters |
| `gsheets_get_sheet_summary` | Get summary stats |
| `gsheets_get_feature_owners` | Get feature owners |
| `gsheets_get_release_data` | Get release tracking |

---

## Configuration in Dashboard

Set your spreadsheet ID in the backend config:

```python
# backend/config.py
MANUAL_EXECUTION_SPREADSHEET_ID = "your-spreadsheet-id-here"
WEEKLY_STATUS_SPREADSHEET_ID = "your-spreadsheet-id-here"
FEATURE_OWNERS_SPREADSHEET_ID = "your-spreadsheet-id-here"
```

Or via environment variables:

```bash
MANUAL_EXECUTION_SHEET_ID=1ABC...xyz
WEEKLY_STATUS_SHEET_ID=1DEF...xyz
```

---

## Finding Spreadsheet ID

The spreadsheet ID is in the URL:

```
https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit
                                        ^^^^^^^^^^^^^^^^
                                        This is the ID
```

Example:
```
URL: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit
ID:  1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "The caller does not have permission" | Share spreadsheet with service account email |
| "File not found" | Check spreadsheet ID is correct |
| "Service account file not found" | Verify GOOGLE_SERVICE_ACCOUNT_FILE path |
| "API not enabled" | Enable Google Sheets API in Cloud Console |
| "Invalid credentials" | Regenerate service account JSON key |

---

## Security Best Practices

1. **Never commit** `service-account.json` to git
2. Add to `.gitignore`:
   ```
   service-account.json
   *-credentials.json
   ```
3. Use environment variables for the file path
4. Give minimum required permissions (Viewer instead of Editor)
5. Rotate service account keys periodically


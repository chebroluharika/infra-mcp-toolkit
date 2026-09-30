# JIRA MCP Server

MCP (Model Context Protocol) server for JIRA API integration. Provides AI agents with access to JIRA data through structured tools.

## Features

- **Search Issues**: Query JIRA using JQL
- **Bug Management**: Get bugs with filters, summaries, critical/regression bugs
- **Customer Bugs**: Get customer-escalated bugs with classification
- **Release Comparison**: Compare bugs across releases
- **Customer Escalations**: Get escalation board data with aging analysis
- **Resiliency Trend**: Get monthly trend data for NS Client escalations

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | Yes | JIRA instance URL (e.g., `https://company.atlassian.net`) |
| `JIRA_USERNAME` | Yes | JIRA username or email |
| `JIRA_API_TOKEN` | Yes | JIRA API token |

## Available Tools

### `jira_search_issues`

Search JIRA issues using JQL query.

**Parameters:**
- `jql` (string, required): JQL query string
- `max_results` (int): Maximum results (default: 100)
- `fetch_all` (bool): Fetch all pages (default: false)

**Returns:** List of issues with key, summary, status, priority, assignee, etc.

### `jira_get_bugs`

Get bugs from JIRA with optional filters.

**Parameters:**
- `project_key` (string, required): JIRA project key
- `status` (string): Filter by status
- `priority` (string): Filter by priority
- `fix_version` (string): Filter by fix version
- `max_results` (int): Maximum bugs to return (default: 100)

**Returns:** List of bugs matching the filters

### `jira_get_bugs_summary`

Get bug summary statistics.

**Parameters:**
- `project_key` (string, required): JIRA project key
- `fix_version` (string): Optional fix version filter

**Returns:** Summary with total, open, resolved counts and breakdowns by status/priority

### `jira_get_critical_bugs`

Get open critical/blocker bugs.

**Parameters:**
- `project_key` (string, required): JIRA project key
- `max_results` (int): Maximum bugs to return (default: 100)

**Returns:** List of critical/blocker priority bugs that are not closed

### `jira_get_regression_bugs`

Get regression bugs.

**Parameters:**
- `project_key` (string, required): JIRA project key
- `fix_version` (string): Optional fix version filter
- `max_results` (int): Maximum bugs to return (default: 100)

**Returns:** List of bugs labeled as Regression or with Regression classification

### `jira_get_escalations_summary`

Get customer escalations summary.

**Parameters:**
- `project_key` (string): JIRA project key (optional)

**Returns:** Summary of escalations by status and priority

### `jira_get_customer_bugs`

Get customer-escalated bugs (labeled `jira_escalated`).

**Parameters:**
- `project_key` (string): JIRA project key (default: "ENG")
- `release_version` (string): Filter by version (e.g., "134")
- `max_bugs` (int): Maximum bugs to return (default: 100)

**Returns:** List of customer bugs

### `jira_get_bugs_by_classification`

Get bugs classified as Regressions, Features, or Others.

**Parameters:**
- `project_key` (string): JIRA project key
- `release_version` (string): Filter by version

**Returns:** Classification breakdown with counts and bug lists

### `jira_get_release_comparison`

Compare customer bugs across multiple releases.

**Parameters:**
- `releases` (list[string]): Release versions to compare (e.g., ["133", "134", "135"])
- `project_key` (string): JIRA project key

**Returns:** Comparison data with trend analysis

### `jira_get_customer_escalations`

Get customer escalations with aging analysis.

**Parameters:**
- `project_key` (string): JIRA project key
- `release_version` (string): Filter by version
- `open_only` (bool): Only open escalations (default: true)

**Returns:** Escalation breakdown with aging buckets (0-30, 31-60, 61-90, 90+ days)

### `jira_get_resiliency_trend`

Get NS Client resiliency trend data for charts.

**Parameters:**
- `months` (int): Number of months to analyze (default: 6)

**Returns:** Monthly trend data for created, resolved, and open escalations

## Usage

### With UV

```bash
cd agents/jira-mcp-server
uv run server.py
```

### With Python

```bash
cd agents/jira-mcp-server
pip install mcp httpx python-dotenv pydantic
python server.py
```

## Performance Considerations

- **Caching**: Results are cached for 60 seconds to reduce API calls
- **Pagination**: Use `fetch_all=false` (default) for faster responses
- **Fields**: Only necessary fields are requested from JIRA API
- **Connection pooling**: HTTPX async client with connection reuse


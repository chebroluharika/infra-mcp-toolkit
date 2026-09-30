# TestRail MCP Server

Model Context Protocol (MCP) server that exposes TestRail API as tools for AI agents.

## Tools Provided

| Tool | Description |
|------|-------------|
| `testrail_get_projects` | Get all TestRail projects |
| `testrail_get_milestones` | Get milestones (releases) for a project |
| `testrail_get_test_runs` | Get test runs with optional milestone filter |
| `testrail_get_test_cases` | Get test cases for a project/suite |
| `testrail_get_testcase_status` | Get status summary for a specific test run |
| `testrail_get_testcase_status_summary` | Get comprehensive test execution summary across all runs |
| `testrail_get_milestone_runs` | Get all runs for a milestone with aggregated stats |
| `testrail_get_pending_tests_by_assignee` | Get pending tests grouped by assignee |

## Environment Variables

```bash
TESTRAIL_URL=https://your-company.testrail.io
TESTRAIL_USERNAME=your-email@company.com
TESTRAIL_API_KEY=your-api-key
```

## Running the Server

```bash
cd agents/testrail-mcp-server
uv run server.py
```

## Usage

The server is automatically started by the backend's MCP client manager. You can also run it standalone for testing.

## API Key

Get your TestRail API key:
1. Log into TestRail
2. Click your name → My Settings
3. Go to API Keys section
4. Generate a new key

## Tool Details

### `testrail_get_projects`
Returns all TestRail projects with their IDs, names, and URLs.

### `testrail_get_milestones`
Get milestones (releases) for a project. Use the milestone ID to filter test runs.

**Parameters:**
- `project_id` (int): TestRail project ID

### `testrail_get_test_runs`
Get test runs for a project with optional filters.

**Parameters:**
- `project_id` (int): TestRail project ID
- `milestone_id` (int, optional): Filter by milestone
- `is_completed` (bool, optional): Filter by completion status

### `testrail_get_testcase_status_summary`
Get comprehensive test execution summary. This is the main tool used by the dashboard.

**Parameters:**
- `project_id` (int): TestRail project ID
- `milestone_id` (int, optional): Filter by milestone

**Returns:**
- Total runs, active/completed counts
- Aggregated status counts (passed, failed, blocked, untested, retest, custom)
- Pass rate percentage
- Per-run breakdown

### `testrail_get_pending_tests_by_assignee`
Get pending (untested/retest) tests grouped by assignee email.

**Parameters:**
- `project_id` (int): TestRail project ID
- `milestone_id` (int): TestRail milestone ID
- `max_tests_per_run` (int, optional): Limit tests per run (default: 50)

**Returns:**
- Summary with counts
- Tests grouped by assignee email
- Unassigned tests list

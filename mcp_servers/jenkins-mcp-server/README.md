# Jenkins MCP Server

Model Context Protocol (MCP) server that exposes Jenkins API as tools for AI agents.

## Tools Provided

| Tool | Description |
|------|-------------|
| `jenkins_get_pipelines` | Get status of all monitored pipelines with health metrics |
| `jenkins_get_job_info` | Get detailed information about a specific job |
| `jenkins_get_build_info` | Get details of a specific build |
| `jenkins_get_test_report` | Get test results with failed test details |
| `jenkins_get_console_output` | Get console logs with error line extraction |
| `jenkins_get_golden_regression` | Get Golden Regression Suite build history |
| `jenkins_get_golden_regression_tfa` | Get Test Failure Analysis for Golden Regression build |

## Environment Variables

```bash
JENKINS_URL=http://jenkins.example.com:8080
JENKINS_USER=your-username
JENKINS_TOKEN=your-api-token
JENKINS_VIEW=Your-Product                    # Optional: Default view/folder
JENKINS_JOBS=job1,job2,job3             # Optional: Comma-separated job names
JENKINS_GOLDEN_REGRESSION_URL=...        # Optional: Golden Regression Suite job URL
```

## Running the Server

```bash
cd agents/jenkins-mcp-server
uv run server.py
```

## Usage

The server is automatically started by the backend's MCP client manager. You can also run it standalone for testing.

## API Token

Get your Jenkins API token:
1. Log into Jenkins
2. Click your username → Configure
3. Go to API Token section
4. Generate a new token

## Tool Details

### `jenkins_get_pipelines`
Get status of all monitored Jenkins pipelines. Returns overall health metrics and per-pipeline status.

**Returns:**
- `overall`: Total pipelines, passing/failing/unstable counts, health percentage
- `pipelines`: List of pipeline status objects with name, status, lastRun, duration, buildNumber, url

### `jenkins_get_job_info`
Get information about a specific Jenkins job.

**Parameters:**
- `job_name` (str): Name of the Jenkins job

**Notes:**
- Automatically tries multiple path patterns (root, view-scoped, folder-scoped)
- Supports nested job paths (e.g., "folder/job")

### `jenkins_get_build_info`
Get information about a specific build.

**Parameters:**
- `job_name` (str): Name of the Jenkins job
- `build_number` (int): Build number to fetch

### `jenkins_get_test_report`
Get test report for a build including parsed failed tests.

**Parameters:**
- `job_name` (str): Name of the Jenkins job
- `build_number` (int): Build number to fetch

**Returns:**
- Total, pass, fail, skip counts
- Duration
- `failedTests`: List of failed test details (name, className, errorMessage, stackTrace)

### `jenkins_get_console_output`
Get console output for a build with automatic error line extraction.

**Parameters:**
- `job_name` (str): Name of the Jenkins job
- `build_number` (int): Build number to fetch

**Returns:**
- `output`: Last 100 lines of console output
- `errorLines`: Extracted lines containing "error", "failed", or "exception"

### `jenkins_get_golden_regression`
Get Golden Regression Suite build history with test results.

**Parameters:**
- `num_builds` (int): Number of builds to fetch (default: 10)

**Returns:**
- `builds`: List of builds with status, timestamp, duration, test counts, healthPercent
- `summary`: Overall success rate, total/success/failed/unstable build counts

### `jenkins_get_golden_regression_tfa`
Get Test Failure Analysis for a specific Golden Regression build.

**Parameters:**
- `build_number` (int): Build number to analyze

**Returns:**
- `failedTests`: List of failed tests with name, className, errorMessage, stackTrace
- `summary`: Test counts (total, passed, failed, skipped, passRate)
- `recommendations`: AI-generated recommendations based on failures

## Default Monitored Jobs

If `JENKINS_JOBS` is not set, these default jobs are monitored:
- downloader_test
- addonman_regression
- addonman_pdv
- clientstatus_regression
- clientupgrade_regression
- enrollment_regression
- steering_regression
- tunnel_regression
- npa_regression
- casb_regression

# GitHub MCP Server

Exposes GitHub API as MCP tools for AI agents.

## Tools Available

| Tool | Description |
|------|-------------|
| `github_get_commits` | Get recent commits from a repo |
| `github_get_commits_after_branch_cut` | Find commits added after branch cut (risky) |
| `github_get_commits_before_branch_cut` | See what's included in the release |
| `github_get_branches` | List all branches |
| `github_compare_branches` | Compare two branches |
| `github_get_release_commits_summary` | Summary across all repos for a release |

## Environment Variables

```bash
GITHUB_TOKEN=ghp_xxxxxxxxxxxx  # GitHub personal access token
GITHUB_ORG=your-company            # GitHub organization (default: your-company)
```

## Usage

```bash
# Run directly
uv run server.py

# Or with Python
python server.py
```

## Example Queries

- "Do we have any commits after branch cut in device-classification?"
- "What was committed to client repo in the last week?"
- "Compare main and release/134 branches"

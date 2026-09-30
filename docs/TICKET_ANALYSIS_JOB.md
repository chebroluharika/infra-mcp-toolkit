# Automated Ticket Analysis Job

This document explains how to set up the nightly AI analysis job for escalation tickets.

## Overview

The analysis job automatically runs AI-powered analysis on all escalation tickets to extract:
- **Impacted Features** - Components affected based on PR file changes
- **Test Areas** - Recommended test areas for each ticket

Once analyzed, this data appears in:
- "AI Features" card in Key Metrics
- "Impacted Features" column in the tickets table
- Feature-to-Customer Matrix
- Escalation Patterns

## Quick Start

### Run Manually (One-time)

```bash
# Load your environment and run analysis
cd /path/to/custom-monitoring-dashboard
./scripts/run-ticket-analysis.sh

# Or with options
./scripts/run-ticket-analysis.sh --limit 10  # Analyze only 10 tickets
./scripts/run-ticket-analysis.sh --dry-run   # Preview without running
./scripts/run-ticket-analysis.sh --force     # Re-analyze all tickets
```

### Run as Cron Job (Recommended)

Add to crontab to run automatically at 2 AM daily:

```bash
# Edit crontab
crontab -e

# Add this line (adjust paths as needed)
0 2 * * * /path/to/custom-monitoring-dashboard/scripts/run-ticket-analysis.sh >> /var/log/ticket-analysis.log 2>&1
```

### Run as Systemd Timer (Alternative)

1. Create service file `/etc/systemd/system/ticket-analysis.service`:

```ini
[Unit]
Description=Escalation Ticket AI Analysis
After=network.target

[Service]
Type=oneshot
User=your-user
WorkingDirectory=/path/to/custom-monitoring-dashboard
ExecStart=/path/to/custom-monitoring-dashboard/scripts/run-ticket-analysis.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

2. Create timer file `/etc/systemd/system/ticket-analysis.timer`:

```ini
[Unit]
Description=Run ticket analysis daily at 2 AM

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

3. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ticket-analysis.timer
sudo systemctl start ticket-analysis.timer

# Check status
sudo systemctl list-timers | grep ticket
```

## Command Options

| Option | Description |
|--------|-------------|
| `--force`, `-f` | Re-analyze all tickets, ignoring cache |
| `--limit N`, `-l N` | Analyze maximum N tickets |
| `--dry-run`, `-n` | Show what would be analyzed without running |
| `--max-age-days N` | Re-analyze tickets with analysis older than N days (default: 7) |
| `--delay N` | Seconds to wait between tickets for rate limiting (default: 1.0) |

## Required Environment Variables

The job requires these environment variables (typically in `.env`):

```bash
# Jira (required)
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_USER_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-jira-api-token

# GitHub (required for PR analysis)
GITHUB_TOKEN=your-github-token

# AI/LLM (required for AI analysis)
ADK_LLM_PROVIDER=ollama
ADK_OLLAMA_BASE_URL=https://your-ollama-url
ADK_OLLAMA_API_TOKEN=your-ollama-token
ADK_LLM_MODEL=your-model-name

# Data directory (optional)
DATA_DIR=/path/to/data  # Defaults to backend/data
```

## How It Works

1. **Fetch Tickets**: Gets all escalation tickets from Jira
2. **Filter**: Identifies tickets that need analysis (new or stale)
3. **For each ticket**:
   - Fetch linked PRs
   - For each PR, fetch file changes from GitHub
   - Run LLM analysis on file changes
   - Extract impacted components/features
4. **Store Results**: Saves to `ticket_analysis_cache.json`
5. **Rate Limiting**: Waits between tickets to avoid API overload

## Output

The job stores results in `$DATA_DIR/ticket_analysis_cache.json`:

```json
{
  "tickets": {
    "ENG-12345": {
      "ticket_key": "ENG-12345",
      "customer": "Acme Corp",
      "impacted_features": ["NSC-Windows", "Authentication"],
      "priority": "High",
      "summary": "Login fails intermittently",
      "sub_component": "NSC-Windows",
      "analyzed_at": "2025-03-30T02:15:30.123456"
    }
  },
  "updated_at": "2025-03-30T02:45:00.000000"
}
```

## Troubleshooting

### Job fails with "Missing required environment variables"

Make sure your `.env` file exists and contains the required variables. The script looks for:
- `$PROJECT_DIR/.env`
- `$PROJECT_DIR/backend/.env`

### Job runs but no features are extracted

- Check if tickets have linked PRs (tickets without PRs use Jira sub_component only)
- Verify GitHub token has access to the repositories
- Check if LLM/Ollama is properly configured and responding

### View logs

```bash
# If using cron
tail -f /var/log/ticket-analysis.log

# If using systemd
journalctl -u ticket-analysis -f
```

### Force re-analysis

```bash
./scripts/run-ticket-analysis.sh --force
```

## Performance Considerations

- **First run**: May take a while if analyzing many tickets
- **Subsequent runs**: Only analyzes new/stale tickets (much faster)
- **Rate limiting**: Default 1 second between tickets prevents API overload
- **LLM calls**: Each PR analysis makes an LLM call; be mindful of costs

## Integration with Dashboard

Once the job runs, the dashboard automatically shows the data:
- Refresh the page to see updated "AI Features" count
- Impacted Features column in tickets table is populated
- Insights tab shows richer data in breakdowns and matrices

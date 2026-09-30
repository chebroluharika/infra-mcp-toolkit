# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A QE Multi-Agent Release Tracking Dashboard with AI-powered analysis. The system uses MCP (Model Context Protocol) servers as the single source of truth for all integrations (JIRA, TestRail, Jenkins, GitHub), consumed by both a React dashboard (port 3000) and an AI Assistant (Streamlit on port 8501).

**Tech Stack:**
- **Backend:** FastAPI (Python 3.10+, port 8000) with direct API clients
- **Frontend:** React 18 with recharts/d3 visualizations (port 3000)
- **AI Agents:** Streamlit + Google ADK with MCP tools (port 8501)
- **MCP Servers:** 7 separate servers in `mcp_servers/` for external integrations
- **Deployment:** Docker Compose with host networking

## Development Commands

### Quick Start (Docker - Recommended)
```bash
# First time setup
make setup          # Creates .env from template
make build         # Build Docker images
make up            # Start all services

# Daily workflow
make up            # Start services
make down          # Stop services
make logs          # View logs
make restart       # Restart services
make ps            # Show running containers
make health        # Check service health

# Development utilities
make shell-backend  # Shell into backend container
make rebuild        # Clean rebuild
make clean          # Remove all containers/images
```

### Manual Development Setup
```bash
# Backend (Terminal 1)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (Terminal 2)
npm install
npm start  # Starts on port 3000

# AI Chat (Terminal 3 - Optional)
cd ai_agents
source venv/bin/activate
streamlit run streamlit_app.py --server.port 8501
```

### Build & Deploy
```bash
# Build all Docker images
make build

# Build and start
make build && make up

# Rebuild from scratch (no cache)
make rebuild
```

### Running Tests
```bash
# Frontend tests
npm test

# Backend tests (if available)
cd backend
pytest

# Playwright E2E tests
npm run test:e2e  # (if configured)
```

## Architecture

### High-Level Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│  FastAPI    │────▶│ MCP Client  │────▶│ MCP Server  │
│  Dashboard  │◀────│  Backend    │◀────│  (in-proc)  │◀────│  (stdio)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                          ▲                                         │
                          │                                         ▼
                    ┌─────────────┐                         ┌─────────────┐
                    │  Streamlit  │                         │ External    │
                    │  AI Agent   │                         │ APIs        │
                    │  (via MCP)  │                         │ (JIRA, etc) │
                    └─────────────┘                         └─────────────┘
```

**Key Points:**
- FastAPI backend acts as the single source of truth, aggregating data from MCP servers
- Both React Dashboard and AI Assistant consume FastAPI endpoints
- MCP servers run as stdio processes, communicating via JSON-RPC
- All business logic (RRS calculation, phase detection) lives in FastAPI, not MCP servers

### MCP Servers (`mcp_servers/`)

Seven independent MCP servers provide tools for external integrations:

1. **jira-mcp-server** (15+ tools): Bugs, RRS, milestones, escalations, action items
2. **testrail-mcp-server** (10+ tools): Test execution, pass rates, pending tests
3. **jenkins-mcp-server** (7+ tools): Pipelines, builds, TFA (Test Failure Analysis)
4. **github-mcp-server** (6+ tools): Commits, PRs, branch analysis
5. **release-calendar-mcp-server** (3+ tools): Release dates, milestones from PDF
6. **release-risk-mcp-server** (5+ tools): AI-powered risk prediction
7. **gsheets-mcp-server** (6+ tools): Manual test execution tracking

**Adding a New MCP Server:**
1. Create folder: `mcp_servers/new-service-mcp-server/`
2. Add `server.py` with FastMCP tools
3. Register in `backend/services/mcp_client.py`
4. Add wrapper methods to `MCPAgentManager` class

### Backend Structure (`backend/`)

```
backend/
├── main.py                    # FastAPI app, lifespan manager, middleware
├── config.py                  # Settings (release config, env vars)
├── routers/                   # API endpoints
│   ├── overview.py           # /api/dashboard (aggregates all data)
│   ├── jira.py               # /api/jira/*
│   ├── testrail.py           # /api/testrail/*
│   ├── jenkins.py            # /api/jenkins/*
│   ├── release_calendar.py   # /api/release-calendar/*
│   ├── escalation_analysis.py # /api/escalation/*
│   └── ...
└── services/                  # Business logic & external clients
    ├── jira_client.py        # Direct JIRA API client
    ├── testrail_client.py    # Direct TestRail API client
    ├── jenkins_client.py     # Direct Jenkins API client
    ├── risk_predictor.py     # AI risk prediction (uses Ollama)
    ├── trend_tracker.py      # Scheduled RRS snapshots
    ├── slack_scheduler.py    # Scheduled Slack notifications
    └── ...
```

**Router Pattern:**
- Each router corresponds to a section in the frontend
- Routers call service clients (direct API integrations)
- `/api/dashboard` endpoint in `overview.py` aggregates data from multiple sources
- All routers are registered in `main.py` via `app.include_router()`

### AI Agents (`ai_agents/`)

Multi-agent system using Google ADK with LiteLLM for multiple LLM providers:

```
ai_agents/
├── streamlit_app.py              # Chat UI entry point
├── config.py                     # LLM provider configuration
├── core/
│   ├── base.py                   # LiteLLM integration
│   ├── runner.py                 # Agent execution engine
│   └── embeddings.py             # Embedding providers
├── root_agent/                   # Query router
│   └── agent.py                  # Routes to specialized agents
├── release_readiness_agent/      # Release status queries
│   ├── agent.py                  # LlmAgent with MCP tools
│   └── tools/mcp_tools.py        # MCP server integration
├── tfa_agent/                    # Test Failure Analysis
│   └── agent.py                  # RAG-based failure analysis
├── dev_insights_agent/           # Developer intelligence
│   └── agent.py                  # JIRA/GitHub/Jenkins insights
└── docs_agent/                   # Documentation search (RAG)
    └── agent.py
```

**LLM Provider Support:**
- Ollama (default, local): `ADK_LLM_PROVIDER=ollama` — runs `llama3.2`, `gemma2`, etc. via `ollama serve`
- OpenAI: `ADK_LLM_PROVIDER=openai`
- Google Gemini: `ADK_LLM_PROVIDER=gemini`
- Anthropic Claude: `ADK_LLM_PROVIDER=anthropic`

Configuration via environment variables (see `.env.example`).

### Frontend Structure (`src/`)

```
src/
├── App.js                        # Main app with sidebar nav
├── components/
│   ├── Sidebar.js               # Left navigation pane
│   ├── ChatWindow.js            # Right-side AI chat panel
│   ├── sections/                # Dashboard sections (one per route)
│   │   ├── OverviewSection.js
│   │   ├── ReleaseReadinessSection.js
│   │   ├── TestRailSection.js
│   │   ├── JenkinsSection.js
│   │   ├── ReleaseRegressionSection.js
│   │   ├── OnCallCalendarSection.js
│   │   └── ...
│   ├── charts/                  # Reusable chart components
│   │   ├── SunburstChart.js    # D3 sunburst visualization
│   │   └── DrillDownSunburst.js
│   └── stack-monitoring/        # Kubernetes stack health widgets
└── services/
    └── api.js                   # API client (calls FastAPI backend)
```

**Section Pattern:**
- Each section corresponds to a backend router
- Sections are lazy-loaded components
- Use `api.js` for all backend calls (proxied via package.json to port 8000)

## Release Configuration

**Single Source of Truth:** `backend/config.py`

To add a new release (e.g., R136 → R137):

1. Edit `backend/config.py`, update `RELEASE_MILESTONES` list:
   ```python
   {
       "id": "r137",
       "name": "R137",
       "display_name": "R137.0.0.0",
       "milestone_id": 0,     # Set your TestRail milestone ID
       "project_id": 1,       # Set your TestRail project ID
       "is_current": True,    # Set to True for new release
       "regression_epics": ["YOUR_PRODUCT-12345"]  # Jira epic keys
   }
   ```

2. Set `is_current=False` on the old release entry

3. Update environment variable:
   ```bash
   # In .env file
   CURRENT_RELEASE=R137
   ```

4. Rebuild and restart:
   ```bash
   make rebuild
   ```

The rest of the dashboard (frontend, AI agents, all endpoints) automatically uses the new release.

## RRS (Release Readiness Score) Calculation

**Location:** `backend/routers/overview.py` → `_calculate_rrs()`

The RRS is a weighted score (0-100) calculated from:

| Component | Weight | Source |
|-----------|--------|--------|
| Bug Score | 25% | Customer escalations & regressions (Jira) |
| Automation Coverage | 20% | Automated tests / total tests (TestRail) |
| Manual Execution | 20% | Passed / executed manual tests (GSheets) |
| Pipeline Health | 20% | Passing pipelines / total (Jenkins) |
| Escalation Impact | 15% | Critical/High/Medium escalations (Jira) |

**Status Levels:**
- 80-100: ✅ Ready (green)
- 60-79: ⚠️ At Risk (yellow)
- 0-59: 🔴 Blocked (red)

**Trend Tracking:**
- Snapshots saved every 6 hours to `backend/data/trend_snapshots.json`
- Service: `backend/services/trend_tracker.py`
- Scheduler: `start_background_scheduler()` in `main.py` lifespan

## Environment Configuration

### Required Environment Variables

See `.env.example` for full template. Critical variables:

```bash
# Application
CURRENT_RELEASE=R136
APP_ENV=development
DEBUG=true

# JIRA
JIRA_URL=https://your-org.atlassian.net
JIRA_USERNAME=your.email@your-company.com
JIRA_API_TOKEN=your-token

# TestRail
TESTRAIL_URL=https://your-org.testrail.io
TESTRAIL_USERNAME=your.email@your-company.com
TESTRAIL_API_KEY=your-key
TESTRAIL_PROJECT_ID=your-project-id
TESTRAIL_MILESTONE_ID=your-milestone-id

# Jenkins
JENKINS_URL=https://your-jenkins.example.com
JENKINS_USER=your.email
JENKINS_TOKEN=your-token

# GitHub
GITHUB_TOKEN=ghp_your-token

# AI/LLM (choose one provider)
ADK_LLM_PROVIDER=ollama          # default: local Ollama
ADK_OLLAMA_BASE_URL=http://localhost:11434
# ADK_LLM_PROVIDER=openai
# ADK_OPENAI_API_KEY=sk-your-key

# Slack
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_CHANNEL=YOUR_SLACK_CHANNEL_ID
```

### Obtaining API Tokens
- **JIRA:** [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
- **TestRail:** Account Settings → API Keys
- **Jenkins:** Profile → Configure → API Token
- **GitHub:** Settings → Developer settings → Personal access tokens

## Key Patterns & Conventions

### Background Schedulers

Multiple schedulers run in `main.py` lifespan for periodic tasks:

1. **Trend Tracker** (`trend_tracker.py`): RRS snapshots every 6 hours
2. **Slack Scheduler** (`slack_scheduler.py`): Daily notifications at 9 AM
3. **Jenkins Monitor** (`jenkins_monitor.py`): Pipeline health checks every 5 min
4. **PDV Scheduler** (`pdv_scheduler.py`): PDV status checks every 5 min
5. **Stack Snapshot** (`stack_snapshot_scheduler.py`): K8s health snapshots every 30 min
6. **GCalendar Sync** (`gcalendar_scheduler.py`): On-call calendar sync every hour
7. **Ticket Analysis** (`ticket_analysis_scheduler.py`): Nightly AI analysis of escalations

All schedulers use APScheduler and are started/stopped in the lifespan context manager.

### Rancher/Kubernetes Integration

**Setup:** Automatic kubeconfig download from Rancher for stack monitoring

1. Tokens stored in environment: `RANCHER_NPE_KEY` (staging) and `RANCHER_PROD_KEY` (production)
2. Download happens at startup in `main.py` lifespan: `_download_rancher_kubeconfigs()`
3. Configs saved to `~/.kube/rancher/` (one per cluster)
4. Stack health cached in `backend/services/stack_monitoring.py`

**Global Flag:** `rancher_setup_complete` in `main.py` indicates when initial download finishes. Before this, stacks with 0 deployments may still be initializing.

### Test Failure Analysis (TFA)

**Service:** `backend/services/jenkins_client.py` → `get_test_failure_analysis()`

AI-powered failure analysis using:
1. **Ollama** (local): DeepSeek Coder v2 for code analysis
2. **Semantic Search**: FAISS embeddings to find similar past failures
3. **Root Cause Detection**: Pattern matching + LLM analysis

**Usage:**
- API: `GET /api/jenkins/tfa/{job_name}/{build_number}`
- UI: Click on failed Jenkins build in Jenkins section

### Commit Analysis

**Service:** `backend/services/commit_analyzer.py`

Uses Ollama with DeepSeek Coder v2 to analyze commits:
- Risk level detection (high/medium/low)
- Code change summarization
- Impact assessment

**Setup:** Requires Ollama running locally:
```bash
ollama pull deepseek-coder-v2:16b
ollama serve
```

### Error Handling in Routers

Standard pattern for all routers:
```python
try:
    result = await service_client.fetch_data()
    return result
except httpx.HTTPStatusError as e:
    logger.error(f"API error: {e}")
    raise HTTPException(status_code=e.response.status_code, detail=str(e))
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise HTTPException(status_code=500, detail=str(e))
```

Always log errors before raising HTTPException. Never swallow exceptions silently.

### Frontend API Calls

**Pattern:**
```javascript
// In src/services/api.js
export const fetchReleaseReadiness = async () => {
  const response = await fetch('/api/dashboard');
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
};

// In component
useEffect(() => {
  fetchReleaseReadiness()
    .then(setData)
    .catch(console.error);
}, []);
```

All API calls proxied to `http://localhost:8000` via `package.json` proxy setting.

## Docker Configuration

**docker-compose.yml** uses `network_mode: host` for Ubuntu VM deployment:
- Backend: port 8000
- Frontend: port 8080 (Nginx)
- Streamlit: port 8501

**Health Checks:**
- Backend: `GET /api/health`
- Frontend: `GET http://localhost:8080`
- Streamlit: `GET /_stcore/health`

**Volume Mounts:**
- `./backend/data:/app/data` - Persistent data (trends, cache)
- `${HOME}/secrets/service-account.json:/app/credentials/service-account.json` - GCP credentials
- `${HOME}/.config/your-pdv-service:/root/.config/your-pdv-service` - PDV token (read-only)

## Troubleshooting

### Backend Not Starting
```bash
# Check logs
make logs

# Check environment variables
docker exec qe-dashboard-backend env | grep -E "JIRA|TESTRAIL"

# Restart backend only
docker-compose restart backend
```

### Frontend Not Connecting to Backend
```bash
# Verify backend is running
curl http://localhost:8000/api/health

# Check proxy setting in package.json
grep proxy package.json  # Should be "http://localhost:8000"
```

### MCP Servers Not Connecting
```bash
# Test MCP server standalone
cd mcp_servers/jira-mcp-server
uv run server.py

# Check environment variables in .env
cat .env | grep -E "JIRA|TESTRAIL|JENKINS"
```

### AI/LLM Not Working
```bash
# Check LLM configuration
echo $ADK_LLM_PROVIDER
echo $ADK_OLLAMA_BASE_URL

# Test local Ollama
ollama list
ollama serve  # If not running
curl http://localhost:11434/api/tags  # Verify models available
```

### Rancher/K8s Timeout Issues
```bash
# Increase timeouts in .env
K8S_CONNECT_TIMEOUT=60
K8S_READ_TIMEOUT=180
K8S_MAX_WORKERS=10

# Rebuild
make rebuild
```

## API Documentation

Interactive API docs available when backend is running:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

All endpoints documented with request/response schemas.

## Access Points

- **Dashboard:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **AI Chat:** http://localhost:8501
- **Health Check:** http://localhost:8000/api/health

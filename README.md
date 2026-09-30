# QE Agentic Dashboard

A **Multi-Agent System** for Quality Engineering release tracking with **AI-powered analysis**.

## Key Features

- **MCP Architecture**: All integrations (JIRA, TestRail, Jenkins, GitHub, Calendar) use MCP servers as the single source of truth
- **AI Assistant**: Streamlit-based chat interface using Google ADK with multiple LLM backends (Ollama, OpenAI, Gemini, Anthropic)
- **Dashboard**: React frontend with 20+ sections for visualizing release readiness data
- **Unified Data Layer**: Both Dashboard and AI Assistant consume FastAPI endpoints
- **Stack Monitoring**: Kubernetes health monitoring via Rancher integration
- **Background Schedulers**: Automated trend tracking, notifications, and health checks

---

## 🏗️ Architecture (FastAPI as Single Source of Truth)

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

### Data Flow

| Consumer | Path |
|----------|------|
| **Dashboard** | React → FastAPI → Direct API Clients → External APIs |
| **AI Assistant** | Streamlit → LLM → MCP Tools → FastAPI → External APIs |

**Key Points:**
- FastAPI backend acts as the single source of truth, aggregating data from multiple sources
- Both React Dashboard and AI Assistant consume FastAPI endpoints
- MCP servers run as stdio processes, communicating via JSON-RPC
- All business logic (RRS calculation, phase detection) lives in FastAPI

### Why This Architecture?

| Benefit | Description |
|---------|-------------|
| **Single Source of Truth** | FastAPI provides consistent data to both UI and AI |
| **Business Logic Centralization** | RRS calculation, phase detection in one place |
| **Thin AI Tools** | MCP tools are simple wrappers calling FastAPI |
| **Trend Analysis** | Centralized snapshot storage for historical data |
| **Modularity** | Each MCP server handles one integration |

---

## 📁 Project Structure

```
infra-mcp-toolkit-oss/
│
├── mcp_servers/                      # MCP Servers (7 servers)
│   ├── jira-mcp-server/              # JIRA: bugs, RRS, milestones, escalations
│   ├── testrail-mcp-server/          # TestRail: test execution, pass rates
│   ├── jenkins-mcp-server/           # Jenkins: pipelines, builds, TFA
│   ├── github-mcp-server/            # GitHub: commits, branches, PRs
│   ├── gsheets-mcp-server/           # Google Sheets: manual execution
│   ├── release-calendar-mcp-server/  # Release Calendar: dates from PDF
│   └── release-risk-mcp-server/      # Release Risk: AI risk prediction
│
├── backend/                          # FastAPI Backend
│   ├── main.py                       # FastAPI app, lifespan manager, middleware
│   ├── config.py                     # Settings (release config, env vars)
│   │
│   ├── routers/                      # API endpoints (18 routers)
│   │   ├── overview.py               # /api/dashboard (aggregates all data)
│   │   ├── jira.py                   # /api/jira/*
│   │   ├── testrail.py               # /api/testrail/*
│   │   ├── jenkins.py                # /api/jenkins/*
│   │   ├── github.py                 # /api/github/*
│   │   ├── release_calendar.py       # /api/release-calendar/*
│   │   ├── release_risk.py           # /api/release-risk/*
│   │   ├── escalation_analysis.py    # /api/escalation/*
│   │   ├── dev_insights.py           # /api/dev-insights/*
│   │   ├── on_call_calendar.py       # /api/oncall/*
│   │   ├── rancher.py                # /api/rancher/* (K8s stack health)
│   │   ├── pdv.py                    # /api/pdv/* (Pre-Deployment Verification)
│   │   ├── ai_chat.py                # /api/chat/*
│   │   ├── slack.py                  # /api/slack/*
│   │   ├── docs_updates.py           # /api/docs/*
│   │   └── ...
│   │
│   └── services/                     # Business logic & external clients (33 modules)
│       ├── jira_client.py            # Direct JIRA API client
│       ├── testrail_client.py        # Direct TestRail API client
│       ├── jenkins_client.py         # Direct Jenkins API client
│       ├── gsheets_client.py         # Google Sheets API client
│       ├── rancher_client.py         # Rancher/K8s API client
│       ├── pdv_client.py             # PDV API client
│       ├── gcalendar_client.py       # Google Calendar client
│       ├── opsgenie_client.py        # OpsGenie alerts client
│       ├── risk_predictor.py         # AI risk prediction (uses Ollama)
│       ├── commit_analyzer.py        # AI commit analysis
│       ├── stack_monitoring.py       # K8s stack health monitoring
│       ├── escalation_service.py     # Escalation analysis
│       ├── trend_tracker.py          # Scheduled RRS snapshots
│       ├── slack_scheduler.py        # Scheduled Slack notifications
│       ├── jenkins_monitor.py        # Pipeline health checks
│       ├── pdv_scheduler.py          # PDV status checks
│       ├── stack_snapshot_scheduler.py   # K8s health snapshots
│       ├── gcalendar_scheduler.py    # On-call calendar sync
│       ├── ticket_analysis_scheduler.py  # AI escalation analysis
│       ├── oncall_notification_scheduler.py  # On-call alerts
│       └── ...
│
├── ai_agents/                        # AI Assistant (Streamlit + ADK)
│   ├── streamlit_app.py              # Chat UI entry point
│   ├── config.py                     # LLM provider configuration
│   │
│   ├── core/                         # Agent infrastructure
│   │   ├── runner.py                 # AgentRunner orchestration
│   │   ├── base.py                   # LiteLLM integration
│   │   └── embeddings.py             # Embedding providers
│   │
│   ├── root_agent/                   # Query router (entry point)
│   │   └── agent.py                  # Routes to specialized agents
│   │
│   ├── release_readiness_agent/      # Release status queries
│   │   ├── agent.py                  # LlmAgent with MCP tools
│   │   └── tools/mcp_tools.py        # MCP server integration
│   │
│   ├── release_risk_agent/           # AI risk prediction
│   │   └── agent.py
│   │
│   ├── testrail_agent/               # TestRail queries
│   │   └── agent.py
│   │
│   ├── jenkins_agent/                # Jenkins/pipeline queries
│   │   └── agent.py
│   │
│   ├── github_agent/                 # GitHub/commit queries
│   │   └── agent.py
│   │
│   ├── escalation_analysis_agent/    # Escalation analysis
│   │   └── agent.py
│   │
│   ├── dev_insights_agent/           # Developer intelligence
│   │   └── agent.py                  # JIRA/GitHub/Jenkins insights
│   │
│   ├── tfa_agent/                    # Test Failure Analysis
│   │   └── agent.py                  # RAG-based failure analysis
│   │
│   └── docs_agent/                   # Documentation search (RAG)
│       └── agent.py
│
├── src/                              # React Dashboard Frontend
│   ├── App.js                        # Main app with sidebar nav
│   ├── components/
│   │   ├── Sidebar.js                # Left navigation pane
│   │   ├── ChatWindow.js             # Right-side AI chat panel
│   │   ├── sections/                 # Dashboard sections (20 sections)
│   │   │   ├── OverviewSection.js
│   │   │   ├── ReleaseReadinessSection.js
│   │   │   ├── WeeklyStatusSection.js
│   │   │   ├── TestRailSection.js
│   │   │   ├── JenkinsSection.js
│   │   │   ├── JiraSection.js
│   │   │   ├── ReleaseRegressionSection.js
│   │   │   ├── CustomerEscalationsSection.js
│   │   │   ├── ResiliencySection.js
│   │   │   ├── ReleaseCalendarSection.js
│   │   │   ├── OnCallCalendarSection.js
│   │   │   ├── StackMonitoringPage.js    # K8s stack health
│   │   │   ├── MonitoringSection.js
│   │   │   ├── DevDigestSection.js
│   │   │   ├── DevPipelinesSection.js
│   │   │   ├── TestHealthSection.js
│   │   │   ├── TestEfficacySection.js
│   │   │   ├── FeatureInsightsSection.js
│   │   │   ├── RiskPredictorCard.js      # AI Risk widget
│   │   │   └── DocumentationUpdatesSection.js
│   │   ├── charts/                   # Reusable chart components
│   │   │   ├── SunburstChart.js      # D3 sunburst visualization
│   │   │   └── DrillDownSunburst.js
│   │   └── stack-monitoring/         # Kubernetes stack health widgets
│   └── services/
│       └── api.js                    # API client (calls FastAPI backend)
│
├── docker/                           # Docker deployment
│   ├── docker-compose.yml            # Multi-service deployment
│   ├── docker-build.sh               # Build script with versioning
│   └── Dockerfile.*                  # Container definitions
│
├── .env.example                      # Environment configuration template
├── Makefile                          # Build & deployment commands
│
└── docs/
    ├── ARCHITECTURE.md               # Full architecture documentation
    └── VM_DEPLOYMENT_GUIDE.md        # Production deployment guide
```

---

## 🤖 AI Features

### LLM Provider Support

The AI system supports multiple LLM backends via LiteLLM:

| Provider | Model Examples | Best For |
|----------|---------------|----------|
| **Ollama** (Default) | `llama3.2`, `gemma2`, `gemma3:1b` | Local inference, no API costs |
| **OpenAI** | `gpt-4o`, `gpt-4-turbo` | High accuracy, cloud API |
| **Google Gemini** | `gemini-1.5-pro`, `gemini-1.5-flash` | Multimodal, long context |
| **Anthropic** | `claude-3-opus`, `claude-3-sonnet` | Complex reasoning |

### Configuration

Set via environment variables (see `.env.example`):

```bash
# Local Ollama (default — free, no API key required)
ADK_LLM_PROVIDER=ollama
ADK_LLM_MODEL=llama3.2
ADK_OLLAMA_BASE_URL=http://localhost:11434

# Or use OpenAI
ADK_LLM_PROVIDER=openai
ADK_LLM_MODEL=gpt-4o
ADK_OPENAI_API_KEY=sk-...

# Or use Google Gemini
ADK_LLM_PROVIDER=gemini
ADK_LLM_MODEL=gemini-1.5-flash
ADK_GOOGLE_API_KEY=your-key
```

### Specialized Agents (10 Agents)

| Agent | Purpose | Key Features |
|-------|---------|--------------|
| **Root Agent** | Query routing | Routes to specialized sub-agents |
| **Release Readiness** | Release status | RRS, bugs, tests, milestones |
| **Release Risk** | Risk prediction | AI-driven release risk assessment |
| **TestRail Agent** | Test queries | Test execution, pass rates, pending tests |
| **Jenkins Agent** | Pipeline queries | Build status, failures, TFA |
| **GitHub Agent** | Code queries | Commits, PRs, branch analysis |
| **Escalation Analysis** | Customer issues | Escalation patterns, root causes |
| **Dev Insights** | Team intelligence | Workload, PR status, escalation links |
| **TFA Agent** | Failure analysis | RAG-based root cause analysis |
| **Docs Agent** | Documentation | Confluence/wiki search |

### Key AI Features

- **Release Readiness Chat**: Ask questions about RRS, bugs, tests
- **AI Risk Prediction**: ML-powered release risk assessment with confidence scores
- **Test Failure Analysis (TFA)**: AI-powered root cause analysis of Jenkins failures
- **Commit Analysis**: AI-powered risk assessment of code changes (uses Ollama + DeepSeek Coder)
- **Intelligent Recommendations**: Context-aware suggestions based on current data
- **Multi-Agent Orchestration**: Specialized agents collaborate on complex queries

---

## ⏰ Background Schedulers

Multiple schedulers run in `main.py` lifespan for automated periodic tasks:

| Scheduler | Interval | Purpose |
|-----------|----------|---------|
| **Trend Tracker** | Every 6 hours | RRS snapshots to `backend/data/trend_snapshots.json` |
| **Slack Scheduler** | Daily at 9 AM | Release status notifications |
| **Jenkins Monitor** | Every 5 min | Pipeline health checks |
| **PDV Scheduler** | Every 5 min | Pre-Deployment Verification status |
| **Stack Snapshot** | Every 30 min | K8s health snapshots |
| **GCalendar Sync** | Every hour | On-call calendar sync |
| **Ticket Analysis** | Nightly | AI analysis of escalations |
| **OnCall Notifications** | Configurable | On-call rotation alerts |

All schedulers use APScheduler and are started/stopped in the lifespan context manager.

---

## 🔧 Rancher/Kubernetes Integration

**Stack Monitoring** provides real-time health monitoring of Kubernetes deployments via Rancher.

### Setup

1. Tokens stored in environment: `RANCHER_NPE_KEY` (staging) and `RANCHER_PROD_KEY` (production)
2. Kubeconfigs downloaded at startup in `main.py` lifespan: `_download_rancher_kubeconfigs()`
3. Configs saved to `~/.kube/rancher/` (one per cluster)
4. Stack health cached in `backend/services/stack_monitoring.py`

### Configuration

```bash
# In .env
RANCHER_NPE_KEY=token-xxxxx:yyyyyyyyyyyy
RANCHER_PROD_KEY=token-xxxxx:yyyyyyyyyyyy
K8S_CONNECT_TIMEOUT=30
K8S_READ_TIMEOUT=120
K8S_MAX_WORKERS=10
```

**Note:** The `rancher_setup_complete` flag in `main.py` indicates when initial download finishes. Stacks with 0 deployments may still be initializing before this flag is set

---

## 📊 RRS (Release Readiness Score) Calculation

The RRS is calculated using **customer regression data** as a key quality indicator.

### Components & Weights

| Component | Weight | Scoring Formula |
|-----------|--------|-----------------|
| **Bug Score** | 25% | Based on customer-escalated bugs & regressions |
| **Automation Coverage** | 20% | (automated tests / total tests) × 100 |
| **Manual Execution** | 20% | (passed / executed) × 100 |
| **Pipeline Health** | 20% | (passing pipelines / total) × 100 |
| **Escalations** | 15% | 100 - (critical×30 + high×15 + medium×5) |

### Overall RRS Formula

```
OVERALL RRS = (bug_score × 0.25) + 
              (automation × 0.20) + 
              (manual_execution × 0.20) + 
              (pipeline_health × 0.20) + 
              (escalation_score × 0.15)
```

### Release Status

| RRS Score | Status | Action |
|-----------|--------|--------|
| **80-100** | ✅ Ready | Release is good to go |
| **60-79** | ⚠️ At Risk | Review critical issues before release |
| **0-59** | 🔴 Blocked | Do not release - address blockers first |

---

## 🚀 Getting Started

Choose your preferred setup method:

---

### 🐳 Option 1: Docker Setup (Recommended)

**Best for:** Quick setup, team consistency, production deployment.
The Makefile auto-detects your OS — the commands below are identical on Mac, Linux and Windows.

#### Prerequisites

| Platform | Install |
|---|---|
| **macOS** | [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop) (bundles `docker` + `docker-compose` + `make`) |
| **Windows** | [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop) with WSL2; run commands from a WSL2 Ubuntu shell |
| **Linux** | `docker`, `docker-compose` (or `docker compose` v2), and `make`. On Ubuntu/Debian: `sudo apt install docker.io docker-compose make` and add yourself to the `docker` group |

#### Setup Steps (all platforms)

```bash
# 1. Clone repository
git clone <your-repo-url> infra-mcp-toolkit-oss
cd infra-mcp-toolkit-oss

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys and settings

# 3. Build and start
make build
make up
```

#### Daily commands

```bash
make up       # Start services
make down     # Stop services
make logs     # View logs (all services)
make ps       # Show running containers
make restart  # Restart services
make rebuild  # Full rebuild (no cache) and restart
make health   # Curl the health endpoints
```

#### Access

- Dashboard: http://localhost:8080  *(nginx in Docker)*
- API: http://localhost:8000
- AI Chat: http://localhost:8501
- API Docs: http://localhost:8000/docs

#### How the auto-detection works

| Your OS | What `make up` runs | Networking |
|---|---|---|
| macOS / Windows | `docker-compose -f docker/docker-compose.yml up -d` | Bridge networking with `ports:` mappings |
| Linux | `docker-compose -f docker/docker-compose.yml -f docker/docker-compose.linux.yml up -d` | `network_mode: host` (slightly lower latency, same ports) |

**Override:** `COMPOSE_MODE=portable make up` forces bridge networking anywhere — useful on a Linux box where 8000/8080/8501 are already in use, or for cross-platform parity testing.

If a port on the left side of a mapping conflicts with something already running on your host, edit `docker/docker-compose.yml` — e.g. change `"8080:8080"` to `"9090:8080"` and open http://localhost:9090.

---

### 📦 Option 2: Manual Setup

**Best for:** Local development, custom configuration

**Prerequisites:**
- Python 3.10+
- Node.js 18+
- `uv` (optional — only for running MCP servers standalone: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

**Setup Steps:**

---

**1. Clone Repository**

```bash
git clone <your-repo-url>
cd infra-mcp-toolkit-oss
```

**2. Setup Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Configure Environment**

```bash
# Copy example and edit
cp .env.example .env
# Edit .env with your settings
```

Key environment variables:
```bash
# Required
CURRENT_RELEASE=R136
JIRA_URL=https://your-org.atlassian.net
JIRA_USERNAME=your.email@your-company.com
JIRA_API_TOKEN=your-api-token

# AI Configuration (choose one provider)
ADK_LLM_PROVIDER=ollama
ADK_LLM_MODEL=llama3.2
ADK_OLLAMA_BASE_URL=http://localhost:11434
```

**API Key Resources:**
- TestRail: Settings → API Keys
- JIRA: [API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
- Jenkins: Profile → Configure → API Token

**4. Start Services**

```bash
# Terminal 1 - Backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2 - Frontend
npm install
npm start

# Terminal 3 - AI Chat (optional)
cd ai_agents
source venv/bin/activate
streamlit run streamlit_app.py --server.port 8501
```

**Access:**
- Dashboard: http://localhost:3000
- API: http://localhost:8000
- AI Chat: http://localhost:8501

---

## 🔧 MCP Servers

All integrations use MCP (Model Context Protocol) servers located in `mcp_servers/`:

| Server | Tools | Purpose |
|--------|-------|---------|
| `jira-mcp-server` | 15+ | Bugs, RRS, milestones, escalations, action items |
| `testrail-mcp-server` | 10+ | Test execution, pass rates, pending by assignee |
| `jenkins-mcp-server` | 7+ | Pipelines, builds, TFA |
| `github-mcp-server` | 6+ | Commits, PRs, branch analysis |
| `release-calendar-mcp-server` | 3+ | Release dates, milestones (from PDF) |
| `release-risk-mcp-server` | 5+ | AI risk prediction tools |
| `gsheets-mcp-server` | 6+ | Manual test execution |

### Running MCP Servers Standalone

```bash
# JIRA MCP Server
cd mcp_servers/jira-mcp-server
uv run server.py

# GitHub MCP Server
cd mcp_servers/github-mcp-server
uv run server.py

# Release Risk MCP Server
cd mcp_servers/release-risk-mcp-server
uv run server.py
```

### Adding a New MCP Server

1. Create folder in `mcp_servers/new-service-mcp-server/`
2. Add `server.py` with FastMCP tools
3. Add corresponding API client in `backend/services/`
4. Create router in `backend/routers/` for API endpoints
5. Register router in `backend/main.py`

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## 🎨 Dashboard Sections

The dashboard uses a **left sidebar navigation** layout with 20+ sections organized by category:

| Category | Sections |
|----------|----------|
| **Overview** | Overview, Release Readiness (RRS gauge, status) |
| **Release & Quality** | Weekly Status, TestRail, Jenkins, JIRA, Release Calendar |
| **Customer Issues** | Regressions, Customer Escalations, Resiliency |
| **Infrastructure** | Stack Monitoring (K8s), Monitoring, Dev Pipelines |
| **Intelligence** | Dev Digest, Test Health, Test Efficacy, Feature Insights |
| **Operations** | On-Call Calendar, Documentation Updates |
| **AI Widgets** | Risk Predictor Card (embedded in sections) |

Each section corresponds to a backend router and uses `src/services/api.js` for all backend calls.

---

## 🔍 Test Failure Analysis (TFA)

The TFA feature provides AI-powered failure analysis:

- **Root Cause Analysis**: AI-powered analysis of test failures using Ollama + DeepSeek Coder v2
- **Historical Patterns**: Matches against similar past failures using FAISS semantic embeddings
- **Actionable Recommendations**: Specific steps to fix failures
- **Trend Analysis**: Identifies recurring failure patterns

Access via:
- API: `/api/jenkins/tfa/{job_name}/{build_number}`
- UI: Click on failed Jenkins build in Jenkins section

---

## 🔬 Commit Analysis

AI-powered commit risk analysis using Ollama with DeepSeek Coder v2:

- **Risk Level Detection**: High/Medium/Low classification
- **Code Change Summarization**: Automatic summary of changes
- **Impact Assessment**: Identifies potentially risky changes

**Setup:** Requires Ollama running locally:
```bash
ollama pull deepseek-coder-v2:16b
ollama serve
```

---

## 📚 API Documentation

Interactive API docs available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🛠️ Troubleshooting

### Backend Not Starting

```bash
# Check logs
make logs

# Check environment variables
docker exec qe-dashboard-backend env | grep -E "JIRA|TESTRAIL"

# Restart backend only
make restart
```

### AI/LLM Not Working

```bash
# Check LLM configuration
echo $ADK_LLM_PROVIDER
echo $ADK_OLLAMA_BASE_URL

# Verify Ollama is running and has models
ollama list
ollama serve  # If not running

# Test Ollama API directly
curl http://localhost:11434/api/tags
```

### MCP Servers Not Connecting

```bash
# Check environment variables
cat .env | grep -E "JIRA|TESTRAIL|JENKINS"

# Test MCP servers individually
cd mcp_servers/jira-mcp-server
uv run server.py
```

### Frontend Not Connecting to Backend

```bash
# Check if backend is running on port 8000
curl http://localhost:8000/api/health

# Check proxy setting in package.json
grep proxy package.json  # Should be "http://localhost:8000"
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

### Docker Issues

```bash
# View container logs
docker logs qe-dashboard-backend
docker logs qe-dashboard-streamlit

# Restart containers
make restart

# Rebuild from scratch
make rebuild
```

---

## 📝 License

MIT

---

## 👥 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Run `pre-commit run --all-files` before committing
4. Submit a pull request

---

## 📧 Support

For issues or questions:
- Open a GitHub issue
- Check the API docs at `/docs`
- Review troubleshooting section above

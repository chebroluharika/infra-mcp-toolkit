# Agentic Insights Portal Architecture

A clear overview of the QE Agentic Dashboard architecture with **FastAPI as the single source of truth** for data and a **multi-agent AI system** for intelligent assistance.

---

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA CONSUMERS                                  │
│                                                                              │
│  ┌──────────────────────────┐        ┌──────────────────────────────────┐  │
│  │    REACT DASHBOARD       │        │       AI ASSISTANT               │  │
│  │    (localhost:3000)      │        │       (localhost:8501)           │  │
│  │                          │        │                                   │  │
│  │  ReleaseReadiness │ etc. │        │  Streamlit → Multi-Agent System  │  │
│  └───────────┬──────────────┘        └─────────────┬─────────────────────┘  │
│              │                                      │                        │
│              │ HTTP/REST                           │ HTTP/REST               │
│              │                                      │                        │
│              └──────────────────┬───────────────────┘                        │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                 FASTAPI BACKEND (Single Source of Truth)              │   │
│  │                        (localhost:8000)                               │   │
│  │                                                                       │   │
│  │   • Direct API calls to external services (JIRA, TestRail, etc.)     │   │
│  │   • Applies business logic (RRS calculation, phase detection)        │   │
│  │   • Serves both Dashboard and AI with consistent data                │   │
│  │   • MongoDB for session persistence                                  │   │
│  └──────────────────────────────┬────────────────────────────────────────┘   │
│                                 │                                            │
│                                 │ Direct HTTP/REST                           │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    EXTERNAL APIs                                      │   │
│  │                                                                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │   │
│  │  │   JIRA   │ │ TestRail │ │ Jenkins  │ │  GitHub  │ │  Slack   │   │   │
│  │  │   API    │ │   API    │ │   API    │ │   API    │ │   API    │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Agent AI Architecture

The AI Assistant uses a **multi-agent system** with specialized agents for different domains:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-AGENT SYSTEM                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ROOT AGENT (Orchestrator)                       │   │
│  │                                                                       │   │
│  │   • Routes queries to appropriate specialized agents                 │   │
│  │   • Handles general queries and agent coordination                   │   │
│  │   • Uses semantic routing for intent classification                  │   │
│  └───────────────────────────────┬───────────────────────────────────────┘   │
│                                  │                                           │
│          ┌───────────────────────┼───────────────────────┐                  │
│          │                       │                       │                  │
│          ▼                       ▼                       ▼                  │
│  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐             │
│  │ JENKINS AGENT │     │   TFA AGENT   │     │  DOCS AGENT   │             │
│  │               │     │               │     │               │             │
│  │ • Pipelines   │     │ • Test Failure│     │ • RAG-based   │             │
│  │ • Build status│     │   Analysis    │     │ • Doc search  │             │
│  │ • Job triggers│     │ • Root cause  │     │ • Embeddings  │             │
│  └───────────────┘     └───────────────┘     └───────────────┘             │
│          │                                                                   │
│          ▼                                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              RELEASE READINESS AGENT                                   │  │
│  │                                                                        │  │
│  │   • Release readiness scoring    • Phase detection                    │  │
│  │   • Bug tracking                 • Milestone analysis                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                              ↓ MCP Tools ↓                                  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         MCP SERVERS                                    │  │
│  │                                                                        │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐ │  │
│  │  │  JIRA   │ │ Jenkins │ │ GitHub  │ │TestRail │ │ Release Calendar│ │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Patterns

### Pattern 1: Dashboard Data Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  React Frontend │────▶│  FastAPI Backend │────▶│  External API   │
│  (localhost:3000)│     │  (localhost:8000)│     │  (JIRA, etc.)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘

Example: User views Release Readiness Section
1. React calls GET /api/jira/release-readiness?release=R134
2. FastAPI router uses JiraClient (direct HTTP)
3. JiraClient queries JIRA API via JQL
4. FastAPI calculates RRS → React displays
```

### Pattern 2: AI Assistant Data Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Streamlit App  │────▶│   Root Agent    │────▶│ Specialized Agent│────▶│  MCP Tools      │
│  (localhost:8501)│     │  (Orchestrator) │     │  (Domain Expert) │     │  → FastAPI      │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘

Example: User asks "Is R134 green?"
1. User query sent to Root Agent
2. Semantic router identifies query as release-readiness related
3. Root Agent delegates to Release Readiness Agent
4. Agent uses MCP tool → calls FastAPI: GET /api/jira/release-readiness
5. Agent generates response: "R134 is yellow 🟡 with 79% RRS"
```

### Pattern 3: Agent Communication

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Jenkins Agent  │────▶│ Agent Comm Bus  │────▶│   TFA Agent     │
│  (Build Failed) │     │ (Message Queue) │     │ (Analyze Failure)│
└─────────────────┘     └─────────────────┘     └─────────────────┘

Example: Cross-agent collaboration
1. Jenkins Agent detects build failure
2. Sends message via Agent Communication Bus
3. TFA Agent receives and analyzes test failures
4. Combined response returned to user
```

---

## Why This Architecture?

### FastAPI as Single Source of Truth

| Benefit | Description |
|---------|-------------|
| **Consistency** | Dashboard and AI always show the same data |
| **Business Logic** | RRS calculation, phase detection live in one place |
| **Caching** | Trend snapshots stored centrally |
| **No Duplication** | AI tools are thin wrappers, not reimplementations |

### Multi-Agent Benefits

| Benefit | Description |
|---------|-------------|
| **Specialization** | Each agent is expert in its domain |
| **Scalability** | New agents can be added independently |
| **Maintainability** | Domain logic isolated per agent |
| **Parallel Processing** | Agents can work concurrently |

### MCP Tools for AI (Thin Wrappers)

The AI's MCP tools are **thin wrappers** that call FastAPI endpoints:

```python
# mcp_servers/jira-mcp-server/server.py (AI's MCP tool)
@mcp.tool()
async def jira_get_release_readiness_score(fix_version: str = "134.0") -> Dict:
    """Get Release Readiness Score for a release version."""
    # Just call FastAPI - no direct JIRA query
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{api_base}/api/jira/release-readiness", 
                                    params={"release": f"R{fix_version.split('.')[0]}"})
        return response.json()
```

---

## Directory Structure

```
custom-monitoring-dashboard/
│
├── backend/                    # FastAPI Backend (Single Source of Truth)
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Configuration & release milestones
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Backend container
│   │
│   ├── routers/                # API endpoints
│   │   ├── overview.py         # /api/dashboard, /api/rrs
│   │   ├── jira.py             # /api/jira/* - Release readiness, bugs
│   │   ├── testrail.py         # /api/testrail/* - Test execution
│   │   ├── jenkins.py          # /api/jenkins/* - Pipelines, TFA
│   │   ├── github.py           # /api/github/* - Commits
│   │   ├── release_calendar.py # /api/release-calendar/* - Release dates
│   │   ├── slack.py            # /api/slack/* - Slack integration
│   │   ├── mpaas_signoff.py    # /api/mpaas/* - MPaaS deployment signoff
│   │   ├── stack_monitoring.py # /api/your-product/* - Your-Product monitoring
│   │   └── ai_chat.py          # /api/ai/* - AI chat endpoints
│   │
│   ├── services/               # Business logic layer
│   │   ├── jira_client.py      # JIRA API client
│   │   ├── testrail_client.py  # TestRail API client
│   │   ├── jenkins_client.py   # Jenkins API client
│   │   ├── jenkins_monitor.py  # Jenkins monitoring service
│   │   ├── ollama_client.py    # Ollama LLM client
│   │   ├── intent_classifier.py # Query intent classification
│   │   ├── release_data_service.py # Release data aggregation
│   │   ├── release_calendar_parser.py # PDF calendar parsing
│   │   ├── trend_tracker.py    # Trend tracking & snapshots
│   │   ├── slack_notifications.py # Slack message sending
│   │   ├── slack_reader.py     # Slack channel reading
│   │   ├── slack_scheduler.py  # Scheduled Slack reports
│   │   ├── stack_monitoring.py # Stack health monitoring
│   │   └── mpas_deployment.py  # MPaaS deployment service
│   │
│   ├── data/                   # Cached data
│   │   ├── trend_snapshots.json    # Historical trend data
│   │   ├── slack_scheduler_state.json # Scheduler state
│   │   ├── client_signoff.json     # Client signoff data
│   │   └── release_calendar.pdf    # Release calendar PDF
│   │
│   └── utilities/              # Helper utilities
│       ├── jira.py             # JIRA helpers (RRS calc, phase detection)
│       ├── testrail.py         # TestRail helpers
│       ├── github.py           # GitHub helpers
│       └── time_utils.py       # Time/date utilities
│
├── mcp_servers/                # MCP Servers (AI tool providers)
│   ├── jira-mcp-server/        # JIRA MCP tools
│   │   ├── server.py
│   │   └── README.md
│   ├── testrail-mcp-server/    # TestRail MCP tools
│   │   ├── server.py
│   │   └── README.md
│   ├── jenkins-mcp-server/     # Jenkins MCP tools
│   │   ├── server.py
│   │   └── README.md
│   ├── github-mcp-server/      # GitHub MCP tools
│   │   ├── server.py
│   │   └── README.md
│   ├── gsheets-mcp-server/     # Google Sheets MCP tools
│   │   ├── server.py
│   │   └── README.md
│   └── release-calendar-mcp-server/ # Release calendar MCP tools
│       ├── server.py
│       └── README.md
│
├── ai_agents/                  # AI Multi-Agent System
│   ├── streamlit_app.py        # Streamlit chat interface
│   ├── config.py               # AI agent configuration
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # AI container
│   │
│   ├── core/                   # Core agent infrastructure
│   │   ├── runner.py           # AgentRunner for orchestration
│   │   ├── base.py             # LiteLLM model setup
│   │   ├── models.py           # Data models
│   │   ├── mongodb_session.py  # Session persistence
│   │   ├── agent_communication.py # Inter-agent messaging
│   │   ├── intent_classifier.py   # Query intent classification
│   │   ├── query_processor.py     # Query preprocessing
│   │   ├── semantic_router.py     # Semantic routing logic
│   │   └── utils.py               # Utility functions
│   │
│   ├── root_agent/             # Root Agent (Orchestrator)
│   │   ├── __init__.py
│   │   └── agent.py            # Main orchestrator agent
│   │
│   ├── jenkiollama/          # Jenkins Specialist Agent
│   │   ├── __init__.py
│   │   ├── agent.py            # Jenkins domain logic
│   │   └── tools/
│   │       ├── __init__.py
│   │       └── mcp_tools.py    # Jenkins MCP tool wrappers
│   │
│   ├── release_readiness_agent/ # Release Readiness Agent
│   │   ├── __init__.py
│   │   ├── agent.py            # Release readiness logic
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── api_tools.py    # Direct API tools
│   │       └── mcp_tools.py    # MCP tool wrappers
│   │
│   ├── tfa_agent/              # Test Failure Analysis Agent
│   │   ├── __init__.py
│   │   ├── agent.py            # TFA domain logic
│   │   └── ollama_mixin.py     # Ollama integration
│   │
│   ├── docs_agent/             # Documentation Agent (RAG)
│   │   ├── __init__.py
│   │   ├── agent.py            # Documentation retrieval
│   │   ├── data/
│   │   │   └── docs_index.json # Document index
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── chunker.py      # Document chunking
│   │       ├── embeddings.py   # Text embeddings
│   │       ├── rag_pipeline.py # RAG orchestration
│   │       ├── scraper.py      # Document scraping
│   │       ├── smart_retriever.py # Semantic retrieval
│   │       └── vector_store.py # Vector database
│   │
│   ├── data/                   # Agent data files
│   │   └── tfa_knowledge_base.json # TFA knowledge base
│   │
│   └── docs/                   # Agent documentation
│       └── AGENT_COMMUNICATION.md
│
├── src/                        # React Frontend
│   ├── App.js                  # Main app component
│   ├── App.css                 # Global styles
│   ├── index.js                # Entry point
│   ├── config.js               # Frontend configuration
│   │
│   ├── components/
│   │   ├── Sidebar.js          # Navigation sidebar
│   │   ├── ChatWindow.js       # AI chat interface
│   │   │
│   │   ├── common/             # Shared components
│   │   │   └── GoogleSheetsEmbed.js
│   │   │
│   │   └── sections/           # Dashboard sections
│   │       ├── OverviewSection.js        # Main overview
│   │       ├── ReleaseReadinessSection.js # Release readiness
│   │       ├── ReleaseRegressionSection.js # Regression testing
│   │       ├── ReleaseCalendarSection.js  # Release calendar
│   │       ├── JenkinsSection.js          # Jenkins pipelines
│   │       ├── JiraSection.js             # JIRA tickets
│   │       ├── TestRailSection.js         # TestRail results
│   │       ├── MonitoringSection.js       # Stack monitoring
│   │       ├── CustomerEscalationsSection.js # Escalations
│   │       ├── ResiliencySection.js       # Resiliency testing
│   │       └── WeeklyStatusSection.js     # Weekly reports
│   │
│   ├── services/
│   │   └── api.js              # API calls to FastAPI
│   │
│   └── styles/                 # CSS styles
│       ├── variables.css       # CSS variables
│       ├── layout.css          # Layout styles
│       ├── components.css      # Component styles
│       ├── sections.css        # Section styles
│       ├── overview.css        # Overview styles
│       ├── chat.css            # Chat styles
│       └── extra-sections.css  # Additional section styles
│
├── docs/                       # Project documentation
│   ├── ARCHITECTURE.md         # This file
│   ├── GSHEETS_CONFIG.md       # Google Sheets setup
│   ├── KUBERNETES_SETUP.md     # K8s deployment guide
│   ├── MONGODB_GUIDE.md        # MongoDB configuration
│   └── PHASE2_ESCALATION_ANALYSIS.md # Phase 2 analysis
│
├── docker-compose.yml          # Multi-container orchestration
├── Dockerfile                  # Frontend container
├── nginx.conf                  # Nginx configuration
├── package.json                # Node.js dependencies
├── Makefile                    # Build automation
└── README.md                   # Project readme
```

---

## Key Endpoints

### Dashboard Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard` | GET | Full dashboard data |
| `/api/rrs` | GET | Release Readiness Score |
| `/api/health` | GET | Health check |

### JIRA
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jira/release-readiness` | GET | Release readiness tracking |
| `/api/jira/bugs/critical` | GET | Critical bugs |
| `/api/jira/escalations` | GET | Customer escalations |
| `/api/jira/milestone/irr` | GET | IRR milestone data |

### Jenkins
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jenkins/pipelines` | GET | Pipeline status |
| `/api/jenkins/jobs` | GET | Job list |
| `/api/jenkins/tfa` | GET | Test failure analysis |

### TestRail
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/testrail/milestone-data` | GET | Test execution data |
| `/api/testrail/runs` | GET | Test runs |

### Other Services
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/calendar/release-dates` | GET | Release dates |
| `/api/github/commits` | GET | Commits after branch cut |
| `/api/slack/send` | POST | Send Slack message |
| `/api/mpaas/signoff` | GET | MPaaS signoff status |
| `/api/your-product/status` | GET | Your-Product stack status |

### AI Chat
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai/chat` | POST | Send message to AI |
| `/api/ai/sessions` | GET | List chat sessions |
| `/api/ai/sessions/{id}` | GET | Get session history |

---

## Environment Variables

```bash
# =============================================================================
# Backend & MCP Server Configuration
# =============================================================================

# JIRA
JIRA_URL=https://company.atlassian.net
JIRA_USERNAME=email@company.com
JIRA_API_TOKEN=your-token

# TestRail
TESTRAIL_URL=https://company.testrail.io
TESTRAIL_USERNAME=email@company.com
TESTRAIL_API_KEY=your-key

# Jenkins
JENKINS_URL=http://jenkins:8080
JENKINS_USER=username
JENKINS_TOKEN=token

# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_ORG=your-company

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json

# Slack
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx
SLACK_CHANNEL_ID=C0123456789

# MongoDB (for session persistence)
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=agentic_insights

# =============================================================================
# AI Assistant Configuration
# =============================================================================

# Ollama (LLM)
OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen2.5:7b

# API Base (for MCP tools to call FastAPI)
API_BASE_URL=http://localhost:8000
```

---

## Running the System

### Option 1: Docker Compose (Recommended)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Option 2: Manual Setup

#### 1. Start Backend (FastAPI)

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

#### 2. Start Frontend (React)

```bash
npm start  # Runs on localhost:3000
```

#### 3. Start AI Assistant (Streamlit)

```bash
cd ai_agents
source venv/bin/activate
streamlit run streamlit_app.py  # Runs on localhost:8501
```

#### 4. Ensure Ollama is Running

```bash
ollama serve  # LLM server on localhost:11434
ollama run qwen2.5:7b  # Pull model if needed
```

---

## Architecture Benefits

1. **Single Source of Truth**: FastAPI provides consistent data to both dashboard and AI
2. **Multi-Agent System**: Specialized agents for different domains improve response quality
3. **Thin AI Tools**: MCP tools for AI are simple wrappers, not reimplementations
4. **Business Logic Centralization**: RRS calculation, phase detection in one place
5. **Trend Analysis**: Centralized snapshot storage enables historical analysis
6. **Modularity**: MCP servers and agents can be developed/tested independently
7. **AI-Ready**: Tools designed with clear docstrings for LLM understanding
8. **Scalable**: New agents and services can be added without disrupting existing ones
9. **Observable**: Comprehensive logging and monitoring across all components

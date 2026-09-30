"""
QE Dashboard - FastAPI Backend
==============================

REST API for Release Readiness tracking using direct API clients.

Architecture:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│  FastAPI    │────▶│ External    │
│  Frontend   │◀────│  Backend    │◀────│   APIs      │
└─────────────┘     └─────────────┘     └─────────────┘
                          │
                          │ Direct API clients for:
                          │ • TestRail (testrail_client.py)
                          │ • JIRA (jira_client.py)
                          │ • Jenkins (jenkins_client.py)
                          │ • Slack (slack_notifications.py)
                          │
                          │ AI Agent (Streamlit) uses MCP servers
                          │ separately for LLM tool integration.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Configure logging
logger = logging.getLogger(__name__)

# Load .env from project root (single source of truth)
import os

from dotenv import load_dotenv

_backend_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_backend_dir)
load_dotenv(os.path.join(_project_root, ".env"))

from config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from routers import (
    ai_chat,
    dev_insights,
    docs_updates,
    escalation_analysis,
    github,
    index,
    jenkins,
    jira,
    on_call_calendar,
    overview,
    pdv,
    rancher,
    release_calendar,
    release_risk,
    slack,
    testrail,
)
from services.gcalendar_scheduler import start_gcalendar_scheduler, stop_gcalendar_scheduler
from services.jenkins_monitor import start_jenkins_monitor, stop_jenkins_monitor
from services.pdv_scheduler import start_pdv_scheduler, stop_pdv_scheduler
from services.slack_scheduler import start_slack_scheduler, stop_slack_scheduler
from services.stack_snapshot_scheduler import start_snapshot_scheduler, stop_snapshot_scheduler
from services.trend_tracker import start_background_scheduler, stop_background_scheduler

# Ticket analysis scheduler (for nightly AI analysis of escalation tickets)
try:
    from services.ticket_analysis_scheduler import start_ticket_analysis_scheduler, stop_ticket_analysis_scheduler

    _ticket_analysis_available = True
except ImportError:
    _ticket_analysis_available = False

    def start_ticket_analysis_scheduler():
        pass

    def stop_ticket_analysis_scheduler():
        pass


# On-call notification scheduler (reminder 3-4 days before rotation)
try:
    from services.oncall_notification_scheduler import (
        start_oncall_notification_scheduler,
        stop_oncall_notification_scheduler,
    )

    _oncall_scheduler_available = True
except ImportError:
    _oncall_scheduler_available = False

    def start_oncall_notification_scheduler():
        pass

    def stop_oncall_notification_scheduler():
        pass


# ============ Lifespan Manager ============

# Tracks whether the background Rancher kubeconfig download + stack health
# cache warm has finished.  While False, stacks with 0 deployments are still
# initializing (not genuinely empty).
rancher_setup_complete = False


def _prefetch_environment_configs():
    """Pre-fetch environment configs from GitHub to avoid latency on first request."""
    try:
        from services.environment_config import get_all_environments, get_config_source

        envs = get_all_environments()
        source = get_config_source()
        if envs:
            print(f"   ✅ Environment Configs: {len(envs)} stacks from {source}")
        else:
            print("   ⚠️ Environment Configs: No stacks loaded (check GITHUB_TOKEN)")
    except Exception as err:
        print(f"   ⚠️ Environment config prefetch error: {err}")


async def _warm_stack_health_cache():
    """Warm the stack health monitoring cache in the background.

    This runs after startup so the first /api/overview request doesn't have to
    wait 3-15s for Kubernetes API calls. Uses lite_mode for minimal overhead.
    Has a 180s timeout to avoid hanging indefinitely.
    """
    try:
        from services.stack_monitoring import get_monitoring_service

        monitoring_service = get_monitoring_service()
        await asyncio.wait_for(
            asyncio.to_thread(
                monitoring_service.generate_stack_config,
                None,  # stacks (all)
                True,  # use_cache
                True,  # lite_mode
                False,  # background_refresh
            ),
            timeout=180,  # 3 minute timeout for all stacks
        )
        print("   ✅ Stack Health Cache: Warmed (lite mode)")
    except asyncio.TimeoutError:
        print("   ⚠️ Stack Health Cache: Timed out after 180s (partial data available)")
    except Exception as err:
        print(f"   ⚠️ Stack health cache warm error: {err}")


async def _background_rancher_setup():
    """Download kubeconfigs from Rancher and warm stack health cache in background.

    Runs as a background task so Rancher SSL/network issues don't block startup.
    Has a per-cluster timeout to avoid hanging indefinitely.
    """
    try:
        from services.rancher_client import _get_rancher_token, download_all_kubeconfigs

        has_npe = bool(_get_rancher_token("npe"))
        has_prod = bool(_get_rancher_token("prod"))
        if has_npe or has_prod:
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(download_all_kubeconfigs),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                print("   ⚠️ Rancher Kubeconfigs: Timed out after 120s")
                results = {}
            downloaded = [k for k, v in results.items() if v]
            failed = [k for k, v in results.items() if not v]
            if downloaded:
                print(f"   ✅ Rancher Kubeconfigs: {len(downloaded)} downloaded")
            if failed:
                print(f"   ⚠️ Rancher Kubeconfigs: {len(failed)} failed ({', '.join(failed[:3])}...)")
            if downloaded:
                from config import refresh_stack_discovery

                refresh_stack_discovery()
        else:
            print("   ⚠️ Rancher Kubeconfigs: No tokens (set RANCHER_NPE_KEY / RANCHER_PROD_KEY)")
    except Exception as err:
        print(f"   ⚠️ Rancher kubeconfig download error: {err}")

    await _warm_stack_health_cache()

    global rancher_setup_complete
    rancher_setup_complete = True
    print("   ✅ Background Rancher setup complete")


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pylint: disable=unused-argument
    """Manage startup and shutdown of background services."""
    print("🚀 QE Dashboard API starting...")
    print("   Architecture: Direct API clients (TestRail, Jenkins, JIRA)")

    # Pre-fetch environment configs from GitHub (avoids latency on first request)
    _prefetch_environment_configs()

    # Start background trend sync (every 2 hours)
    try:
        start_background_scheduler()
        print("   ✅ Trend Tracker: Auto-sync every 2 hours")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Trend scheduler error: {err}")

    # Start Slack notification scheduler (daily at 9am)
    try:
        start_slack_scheduler()
        print("   ✅ Slack Scheduler: Daily notifications at 9am")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Slack scheduler error: {err}")

    # Start Jenkins pipeline monitor (checks for stuck pipelines)
    try:
        start_jenkins_monitor()
        print("   ✅ Jenkins Monitor: Alerts for stuck pipelines (>1 hour)")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Jenkins monitor error: {err}")

    # Start stack snapshot scheduler (hourly snapshots for health trend chart)
    try:
        start_snapshot_scheduler()
        print("   ✅ Stack Snapshot Scheduler: Hourly snapshots for health trends")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Stack snapshot scheduler error: {err}")

    # Start PDV scheduler (token refresh + status change notifications)
    try:
        start_pdv_scheduler()
        print("   ✅ PDV Scheduler: Token refresh (12h) + status checks (5min)")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ PDV scheduler error: {err}")

    # Start Google Calendar sync scheduler (for release calendar updates)
    try:
        start_gcalendar_scheduler()
        import os

        if os.environ.get("GOOGLE_CALENDAR_ID"):
            interval = os.environ.get("GOOGLE_CALENDAR_SYNC_INTERVAL", "30")
            print(f"   ✅ Google Calendar Scheduler: Auto-sync every {interval} minutes")
        else:
            print("   ⚠️ Google Calendar: Not configured (using PDF fallback)")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Google Calendar scheduler error: {err}")

    # Start ticket analysis scheduler (nightly AI analysis of escalation tickets)
    try:
        if _ticket_analysis_available:
            start_ticket_analysis_scheduler()
            import os

            hour = os.environ.get("TICKET_ANALYSIS_HOUR", "2")
            tz = os.environ.get("TICKET_ANALYSIS_TIMEZONE", "Asia/Kolkata")
            print(f"   ✅ Ticket Analysis Scheduler: Daily at {hour}:00 {tz}")
        else:
            print("   ⚠️ Ticket Analysis: Module not available")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ Ticket analysis scheduler error: {err}")

    # On-call reminders are now handled by the main Slack scheduler (slack_scheduler_config.json)
    # Load state for tracking sent notifications
    try:
        if _oncall_scheduler_available:
            from services.oncall_notification_scheduler import _load_state

            _load_state()
            print("   ✅ On-Call Reminder: Configured via slack_scheduler_config.json")
        else:
            print("   ⚠️ On-Call Reminder: Module not available")
    except (RuntimeError, OSError) as err:
        print(f"   ⚠️ On-call notification state load error: {err}")

    # Download kubeconfigs from Rancher + warm stack health cache in background.
    # This prevents Rancher SSL/network issues from blocking server startup.
    asyncio.create_task(_background_rancher_setup())

    print(f"   Environment: {settings.app_env}")
    print("   Ready to serve requests!")

    yield  # Server runs here

    # Shutdown
    print("👋 QE Dashboard API shutting down...")
    stop_gcalendar_scheduler()
    stop_pdv_scheduler()
    stop_snapshot_scheduler()
    stop_jenkins_monitor()
    stop_slack_scheduler()
    stop_background_scheduler()
    stop_ticket_analysis_scheduler()
    # On-call reminders state is saved automatically on each notification


# ============ Initialize FastAPI ============

app = FastAPI(
    title="QE Dashboard API",
    description="""
    ## API for Release Readiness Tracking

    This API uses direct API clients for external services:
    - **TestRail**: Test cases, runs, automation coverage
    - **JIRA**: Release readiness, blockers, regression tracking
    - **Jenkins**: Pipeline status, golden regression, TFA

    AI Agent (Streamlit) uses MCP servers separately for LLM tool integration.
    """,
    version="2.1.0",
    lifespan=lifespan,
)

# CORS middleware for React frontend
# Document approach: Hardcoded allowed origins for VM deployment
# VM IP: 10.136.126.85
origins = [
    "http://10.136.126.85:8080",  # Frontend accessed from Chrome on MacBook
    "http://10.136.126.85:3000",  # Alternative frontend port
    "http://localhost:3000",  # Local development
    "http://localhost:8080",  # Local testing
    "http://127.0.0.1:3000",  # Local development
    "http://10.136.126.85:8501",  # Streamlit UI
    "http://localhost:5173",
    "http://10.136.126.85:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Request Timing Middleware ============


class TimingMiddleware(BaseHTTPMiddleware):
    """Middleware to log request timing for performance monitoring."""

    async def dispatch(self, request: Request, call_next):
        # Skip timing for static files and health checks
        path = request.url.path
        if path.startswith("/static") or path == "/favicon.ico":
            return await call_next(request)

        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        # Format duration nicely
        if duration < 1:
            duration_str = f"{duration*1000:.0f}ms"
        else:
            duration_str = f"{duration:.2f}s"

        # Log with color coding based on duration
        if duration > 5:
            log_level = logging.WARNING
            prefix = "SLOW"
        elif duration > 2:
            log_level = logging.INFO
            prefix = "WARNING"
        else:
            log_level = logging.INFO
            prefix = "FAST"

        logger.log(log_level, f"{prefix} {request.method} {path} - {response.status_code} - {duration_str}")

        return response


app.add_middleware(TimingMiddleware)


# ============ Include Routers ============

app.include_router(ai_chat.router)  # AI Chat endpoints
app.include_router(dev_insights.router)  # Dev Insights: Knowledge Gaps, Workload, Digest, Cross-Concern
app.include_router(docs_updates.router)  # Documentation Updates for docs team
app.include_router(escalation_analysis.router)  # Customer Escalation Analysis
app.include_router(github.router, prefix="/api/github", tags=["GitHub"])
app.include_router(index.router)  # FAISS Index management + Agent-based PR analysis
app.include_router(jenkins.router)
app.include_router(jira.router)
app.include_router(on_call_calendar.router)  # On-Call Calendar with rotation schedule
app.include_router(overview.router)
app.include_router(pdv.router)  # PDV (Post-Deployment Validation) from Insights Platform
app.include_router(rancher.router)  # Rancher kubeconfig management
app.include_router(release_calendar.router)  # Release Calendar with milestone dates
app.include_router(release_risk.router)  # Release Risk Prediction with AI insights
app.include_router(slack.router)
app.include_router(testrail.router)
# Flaky tests now handled by jenkins router at /api/jenkins/flaky-tests


# ============ Root & Health Endpoints ============


@app.get("/")
async def root():
    """API information endpoint"""
    return {
        "name": "QE Dashboard API",
        "version": "2.1.0",
        "architecture": "Direct API clients",
        "data_flow": "React Frontend ↔ FastAPI Backend ↔ External APIs (TestRail, JIRA, Jenkins)",
        "note": "AI Agent (Streamlit) uses MCP servers separately for LLM tool integration",
        "endpoints": {
            "overview": "/api/overview",
            "releases": "/api/releases",
            "testrail": "/api/testrail/*",
            "jira": "/api/jira/*",
            "jenkins": "/api/jenkins/*",
            "github": "/api/github/*",
            "ai_chat": "/api/ai/chat",
            "docs": "/docs",
        },
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint with container identification"""
    import platform
    import socket

    return {
        "status": "healthy",
        "version": "2.1.0",
        "container_id": socket.gethostname(),  # In Docker, hostname = container ID
        "platform": platform.system(),
        "architecture": "Direct API clients (no MCP in backend)",
    }


# ============ Main ============

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )

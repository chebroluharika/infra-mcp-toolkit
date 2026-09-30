"""
AI Chat Router
==============

REST API endpoints for AI system management.

Note: The main AI chat interface is the Streamlit app (ai_agents/streamlit_app.py)
which uses AgentRunner.run() directly. These endpoints provide system management.

Endpoints:
    - GET /api/ai/status - Get AI system status
    - DELETE /api/ai/session/{session_id} - Clear session history
    - GET /api/ai/quick-actions - Get suggested quick actions
"""

import logging
import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# AI agents path - added lazily to avoid polluting imports
_AI_AGENTS_PATH_ADDED = False


def _ensure_ai_agents_path():
    """Add ai_agents to path if not already added. Call inside functions, not at import time."""
    global _AI_AGENTS_PATH_ADDED  # pylint: disable=global-statement
    if not _AI_AGENTS_PATH_ADDED:
        ai_agents_path = os.path.join(os.path.dirname(__file__), "..", "..", "ai_agents")
        if ai_agents_path not in sys.path:
            sys.path.insert(0, ai_agents_path)
        _AI_AGENTS_PATH_ADDED = True


router = APIRouter(prefix="/api/ai", tags=["AI Chat"])


# ============ Response Models ============


class StatusResponse(BaseModel):
    """Response model for status endpoint."""

    status: str
    llm: dict
    mcp_servers: dict
    active_sessions: int


# ============ Endpoints ============


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    Get AI system status.

    Returns:
    - LLM availability and configuration
    - Agent hierarchy status
    - Active session count
    """
    try:
        _ensure_ai_agents_path()
        from config import get_settings
        from core.base import check_adk_available

        settings = get_settings()
        adk_available = check_adk_available()

        return StatusResponse(
            status="ready" if adk_available else "adk_unavailable",
            llm={
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "available": adk_available,
                "architecture": "adk_multi_agent",
            },
            mcp_servers={
                "agents": {
                    "root_agent": {"status": "active", "type": "LlmAgent"},
                    "release_readiness": {"status": "active", "type": "LlmAgent"},
                    "documentation": {"status": "pending", "type": "LlmAgent"},
                },
                "note": "ADK uses sub_agents hierarchy with transfer_to_agent",
            },
            active_sessions=0,  # ADK manages sessions internally
        )

    except ImportError:
        # Return placeholder status if AI agents not installed
        return StatusResponse(
            status="not_installed",
            llm={
                "provider": "ollama",
                "model": "unknown",
                "available": False,
            },
            mcp_servers={},
            active_sessions=0,
        )
    except Exception as e:
        logger.error("Status check error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """
    Clear chat history for a session.

    Args:
        session_id: Session ID to clear
    """
    try:
        _ensure_ai_agents_path()
        from core.runner import get_runner

        runner = get_runner()
        runner.clear_session(session_id)
        return {"message": f"Session {session_id} cleared", "success": True}

    except ImportError as exc:
        raise HTTPException(status_code=503, detail="AI agents module not available") from exc
    except Exception as e:
        logger.error("Clear session error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/quick-actions")
async def get_quick_actions():
    """
    Get suggested quick actions for the chat interface.
    """
    return {
        "actions": [
            {
                "id": "release_status",
                "label": "Release Status",
                "query": "What's the current release readiness status?",
                "icon": "trending-up",
            },
            {
                "id": "critical_blockers",
                "label": "Critical Blockers",
                "query": "Show me critical bugs blocking the release",
                "icon": "bug",
            },
            {
                "id": "key_dates",
                "label": "Key Dates",
                "query": "When is the code freeze and release date?",
                "icon": "calendar",
            },
            {
                "id": "test_status",
                "label": "Test Status",
                "query": "What's the current test pass rate?",
                "icon": "check-circle",
            },
            {
                "id": "open_items",
                "label": "Open Items by Owner",
                "query": "Show open items grouped by assignee",
                "icon": "users",
            },
        ]
    }

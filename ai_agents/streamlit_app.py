"""
Release Dashboard AI Assistant - Streamlit Interface
=====================================================

A modern chat interface for the Release Readiness AI Assistant.
Features: Real-time processing, chat memory, session persistence.

Run with:
    cd ai_agents
    streamlit run streamlit_app.py
"""

import asyncio
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

import streamlit as st

# Note: streamlit.components.v1 removed for performance (was used for copy button)

# Add paths
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, "..", "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv

# Load .env from project root (single source of truth)
_project_root = os.path.join(current_dir, "..")
load_dotenv(os.path.join(_project_root, ".env"))

# ============ Fast Startup Mode ============
# Set STREAMLIT_FAST_STARTUP=true in Docker for faster initial page load
# This disables copy buttons but keeps MongoDB for session persistence
FAST_STARTUP = os.environ.get("STREAMLIT_FAST_STARTUP", "").lower() in ("true", "1", "yes")
if FAST_STARTUP:
    # NOTE: MongoDB is kept enabled for session persistence
    os.environ.setdefault("DISABLE_COPY_BUTTONS", "true")

# Get default release from config (single source of truth - REQUIRED)
try:
    from config import get_settings as get_ai_config_settings

    _DEFAULT_RELEASE = get_ai_config_settings().default_release
except ImportError:
    _DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
    if not _DEFAULT_RELEASE:
        raise EnvironmentError(
            "CURRENT_RELEASE environment variable is required! " "Set it in your .env file or docker-compose.yml"
        )

# ============ Ollama Early Configuration ============
# Configure Ollama headers globally BEFORE any LLM calls are made
try:
    from core.base import ensure_ollama_configured

    if ensure_ollama_configured():
        print("[Startup] Ollama configured globally for LiteLLM", file=sys.stderr)
except ImportError:
    pass  # core.base not available yet

# Backend API URL - uses BACKEND_URL env var (set in docker-compose.yml)
# In Docker: http://backend:8000 (internal network)
# Local dev: http://localhost:8000
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


# ============ Non-English Text Filter ============

import re


def filter_non_english_text(text: str) -> str:
    """
    Filter out non-English text (Thai, Chinese, Japanese, Korean) from response.
    Keeps only lines that don't contain non-English characters.
    """
    if not text:
        return text

    # Patterns for non-English scripts
    non_english_patterns = [
        r"[\u0e00-\u0e7f]",  # Thai
        r"[\u4e00-\u9fff]",  # Chinese
        r"[\u3040-\u30ff]",  # Japanese (Hiragana, Katakana)
        r"[\uac00-\ud7af]",  # Korean
    ]

    # Check if text contains any non-English characters
    has_non_english = any(re.search(p, text) for p in non_english_patterns)

    if not has_non_english:
        return text

    # Split into lines and filter
    lines = text.split("\n")
    english_lines = []

    for line in lines:
        # Check if line contains non-English characters
        is_non_english = any(re.search(p, line) for p in non_english_patterns)

        if not is_non_english:
            english_lines.append(line)
        else:
            # Try to extract any English portions from mixed lines
            cleaned = line
            for pattern in non_english_patterns:
                cleaned = re.sub(pattern + "+", "", cleaned)

            # Keep if there's meaningful English content left
            cleaned = cleaned.strip()
            if len(cleaned) > 10 and re.search(r"[a-zA-Z]{3,}", cleaned):
                english_lines.append(cleaned)

    result = "\n".join(english_lines).strip()

    # If we filtered out everything, return a notice
    if not result or len(result) < 20:
        return (
            "I processed your request but the response contained non-English text which was filtered. Please try again."
        )

    return result


# ============ Global Event Loop (Single Loop for All Async Ops) ============
# Use a dedicated thread with its own event loop for all async operations
# This prevents "attached to a different loop" errors

_async_loop = None
_async_thread = None
_async_lock = threading.Lock()


def _start_async_loop(loop):
    """Run event loop in dedicated thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_async_loop():
    """Get the dedicated async event loop, creating it if needed."""
    global _async_loop, _async_thread

    with _async_lock:
        if _async_loop is None or _async_loop.is_closed():
            _async_loop = asyncio.new_event_loop()
            _async_thread = threading.Thread(target=_start_async_loop, args=(_async_loop,), daemon=True)
            _async_thread.start()

    return _async_loop


def run_async(coro, timeout=300):
    """Run async coroutine using the dedicated event loop thread."""
    loop = _get_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)  # 300 second (5 min) timeout for larger models


# ============ Constants ============

CHAT_HISTORY_DIR = Path(current_dir) / "data" / "chat_sessions"
CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# ============ URL Parameters ============

query_params = st.query_params
embed_mode = query_params.get("embed", "false").lower() == "true"
url_release = query_params.get("release", None)


# ============ Page Configuration ============

st.set_page_config(
    page_title="Release AI Assistant",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============ CSS Theme ============

MODERN_CSS = """
<style>
    /* Use system fonts instead of Google Fonts for faster load */
    :root {
        --primary: #6366f1;
        --primary-dark: #4f46e5;
        --success: #10b981;
        --warning: #f59e0b;
        --danger: #ef4444;
        --bg-primary: #fafafa;
        --bg-secondary: #ffffff;
        --bg-tertiary: #f4f4f5;
        --text-primary: #18181b;
        --text-secondary: #52525b;
        --text-muted: #a1a1aa;
        --border: #e4e4e7;
        --radius-sm: 6px;
        --radius-md: 10px;
        --radius-lg: 16px;
        --radius-full: 9999px;
        --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
        --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1);
    }

    .stApp {
        background: var(--bg-primary);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    }

    #MainMenu, footer, header {visibility: hidden;}
    .stDeployButton {display: none;}

    /* Top Status Bar - Fixed position */
    .top-status-bar {
        position: fixed;
        top: 10px;
        right: 20px;
        z-index: 9999;
        display: flex;
        align-items: center;
        gap: 10px;
        background: var(--bg-secondary);
        padding: 8px 16px;
        border-radius: var(--radius-full);
        box-shadow: var(--shadow-md);
        border: 1px solid var(--border);
    }

    .status-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
    }

    .status-dot.ready { background: var(--success); }
    .status-dot.running {
        background: var(--primary);
        animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(1.3); }
    }

    .status-text {
        font-size: 13px;
        font-weight: 600;
    }

    .status-text.ready { color: var(--success); }
    .status-text.running { color: var(--primary); }

    .stop-btn {
        background: var(--danger);
        color: white;
        border: none;
        padding: 4px 12px;
        border-radius: var(--radius-full);
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
    }

    .stop-btn:hover { opacity: 0.8; }

    /* Main container */
    .main .block-container {
        max-width: 1200px;
        padding: 2rem 2rem 6rem 2rem;
    }

    /* Sidebar - visible and collapsible */
    section[data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #e4e4e7 !important;
        z-index: 999 !important;
    }

    section[data-testid="stSidebar"] > div:first-child {
        background: #ffffff !important;
    }

    /* Sidebar toggle button - make visible */
    button[data-testid="baseButton-headerNoPadding"],
    button[kind="headerNoPadding"] {
        visibility: visible !important;
        opacity: 1 !important;
    }

    /* Hero */
    .hero-title {
        font-size: 1.75rem;
        font-weight: 700;
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }

    .hero-subtitle {
        color: var(--text-secondary);
        font-size: 0.9rem;
        margin-top: 4px;
    }

    /* Chat messages */
    .stChatMessage {
        background: transparent !important;
        padding: 0.5rem 0 !important;
    }

    [data-testid="stChatMessageContent"] {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-lg) !important;
        padding: 1rem !important;
        box-shadow: var(--shadow-sm) !important;
    }

    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
        border: none !important;
    }

    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) p {
        color: white !important;
    }

    /* Buttons */
    .stButton > button {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border) !important;
        color: var(--text-secondary) !important;
        border-radius: var(--radius-md) !important;
        font-weight: 500 !important;
        transition: all 0.2s !important;
    }

    .stButton > button:hover {
        border-color: var(--primary) !important;
        color: var(--primary) !important;
    }

    .stButton > button:disabled {
        opacity: 0.5 !important;
        cursor: not-allowed !important;
    }

    /* Processing log */
    .processing-log {
        background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
        border-left: 4px solid var(--primary);
        border-radius: 0 var(--radius-md) var(--radius-md) 0;
        padding: 1rem;
        margin-bottom: 1rem;
    }

    .processing-header {
        font-weight: 600;
        color: var(--primary);
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .processing-step {
        font-size: 0.85rem;
        color: var(--text-secondary);
        padding: 3px 0;
    }

    .processing-step.complete { color: var(--success); }
    .processing-step.error { color: var(--danger); }

    /* Welcome cards */
    .welcome-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: var(--radius-lg);
        padding: 1.25rem;
        margin-bottom: 0.75rem;
    }

    .welcome-card-icon {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-md);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
        margin-bottom: 0.75rem;
    }

    .welcome-card-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--text-primary);
        margin: 0 0 0.25rem 0;
    }

    .welcome-card-desc {
        font-size: 0.8rem;
        color: var(--text-secondary);
        margin: 0;
    }

    /* Source tags */
    .source-tag {
        display: inline-block;
        background: rgba(99, 102, 241, 0.1);
        color: var(--primary);
        padding: 2px 8px;
        border-radius: var(--radius-sm);
        font-size: 0.7rem;
        font-weight: 500;
        margin-right: 4px;
    }

    /* Markdown */
    .stMarkdown h2 {
        font-size: 1.1rem;
        margin-top: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--border);
    }

    .stMarkdown table {
        border-collapse: collapse;
        width: 100%;
        margin: 0.5rem 0;
        font-size: 0.85rem;
    }

    .stMarkdown th, .stMarkdown td {
        border: 1px solid var(--border);
        padding: 0.4rem 0.6rem;
    }

    .stMarkdown th {
        background: var(--bg-tertiary);
        font-weight: 600;
    }

    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    .animate-spin {
        animation: spin 1s linear infinite;
        display: inline-block;
    }
</style>
"""


@st.cache_data
def get_cached_css():
    """Return cached CSS to avoid re-parsing on every rerun."""
    return MODERN_CSS


# Inject CSS (cached for performance)
st.markdown(get_cached_css(), unsafe_allow_html=True)


# ============ Dynamic CSS for Running State ============


def inject_running_state_css():
    """Inject CSS to disable chat input when AI is processing."""
    if st.session_state.get("is_running", False):
        st.markdown(
            """
        <style>
            /* Disable chat input completely when running */
            .stChatInput {
                pointer-events: none !important;
                opacity: 0.5 !important;
            }
            .stChatInput textarea {
                background-color: #f0f0f0 !important;
                cursor: not-allowed !important;
            }
            .stChatInput button {
                pointer-events: none !important;
                opacity: 0.3 !important;
            }
            /* Also disable buttons */
            .stButton button:not([disabled]) {
                pointer-events: none !important;
                opacity: 0.6 !important;
            }
        </style>
        """,
            unsafe_allow_html=True,
        )


# ============ Chat Storage (MongoDB with in-memory fallback) ============
# LAZY INITIALIZATION: MongoDB connection is deferred until first use to speed up page load

_chat_storage = None
_chat_storage_type = None  # None = not initialized yet
_chat_storage_init_attempted = False
_in_memory_chats = {}  # Fallback storage


def _init_chat_storage():
    """Initialize chat storage lazily (MongoDB preferred, in-memory fallback)."""
    global _chat_storage, _chat_storage_type, _chat_storage_init_attempted

    # Only attempt once
    if _chat_storage_init_attempted:
        return

    _chat_storage_init_attempted = True

    # Skip MongoDB if DISABLE_MONGODB env var is set (fast path for Docker)
    if os.environ.get("DISABLE_MONGODB", "").lower() in ("true", "1", "yes"):
        _chat_storage_type = "memory"
        return

    # Try MongoDB with short timeout
    try:
        import socket

        from core.mongodb_session import get_mongodb_chat_history

        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(2)  # 2 second timeout (reduced from 3)
        _chat_storage = get_mongodb_chat_history(sync=True)
        _chat_storage_type = "mongodb"
        socket.setdefaulttimeout(old_timeout)
    except Exception:
        _chat_storage_type = "memory"


# DON'T initialize at module load - defer to first use


def get_chat_storage_type() -> str:
    """Get current chat storage type (initializes storage if needed)."""
    if _chat_storage_type is None:
        _init_chat_storage()
    return _chat_storage_type or "memory"


def _format_relative_time(dt) -> str:
    """Format datetime as relative time."""
    if not dt:
        return ""
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        delta = datetime.now() - dt
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        return "Just now"
    except (ValueError, TypeError, AttributeError):
        return ""


def save_chat_session():
    """Save current chat session."""
    if not st.session_state.messages:
        return

    # Lazy init storage on first save
    if _chat_storage_type is None:
        _init_chat_storage()

    session_data = {
        "session_id": st.session_state.session_id,
        "messages": st.session_state.messages,
        "release": st.session_state.selected_release,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }

    if _chat_storage_type == "mongodb" and _chat_storage:
        try:
            _chat_storage.save_chat(
                session_id=st.session_state.session_id,
                messages=st.session_state.messages,
                release=st.session_state.selected_release,
            )
            return
        except Exception as e:
            print(f"[ChatStorage] MongoDB save failed: {e}")

    # In-memory fallback
    _in_memory_chats[st.session_state.session_id] = session_data


def load_chat_sessions():
    """Load list of available chat sessions."""
    # Lazy init storage
    if _chat_storage_type is None:
        _init_chat_storage()

    sessions = []

    if _chat_storage_type == "mongodb" and _chat_storage:
        try:
            docs = _chat_storage.list_chats(limit=10)
            for doc in docs:
                messages = doc.get("messages", [])
                user_messages = [m["content"] for m in messages if m.get("role") == "user"]

                # Generate better preview based on conversation length
                if len(user_messages) == 0:
                    preview = "New chat"
                elif len(user_messages) == 1:
                    # Single message - show it
                    first_msg = user_messages[0]
                    preview = first_msg[:40] + "..." if len(first_msg) > 40 else first_msg
                else:
                    # Multi-turn conversation - show first + count
                    first_msg = user_messages[0]
                    truncated = first_msg[:35] + "..." if len(first_msg) > 35 else first_msg
                    preview = f"{truncated} (+{len(user_messages)-1} more)"

                created_at = doc.get("created_at")
                updated_at = doc.get("updated_at")

                sessions.append(
                    {
                        "id": doc.get("session_id", ""),
                        "release": doc.get("release", "Unknown"),
                        "created_at": created_at.isoformat() if created_at else "",
                        "message_count": len(messages),
                        "user_message_count": len(user_messages),
                        "preview": preview,
                        "relative_time": _format_relative_time(updated_at or created_at),
                    }
                )
            return sessions
        except Exception as e:
            print(f"[ChatStorage] MongoDB list failed: {e}")

    # In-memory fallback
    for session_id, data in sorted(
        _in_memory_chats.items(), key=lambda x: x[1].get("updated_at", datetime.min), reverse=True
    )[:10]:
        messages = data.get("messages", [])
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]

        # Generate better preview based on conversation length
        if len(user_messages) == 0:
            preview = "New chat"
        elif len(user_messages) == 1:
            # Single message - show it
            first_msg = user_messages[0]
            preview = first_msg[:40] + "..." if len(first_msg) > 40 else first_msg
        else:
            # Multi-turn conversation - show first + count
            first_msg = user_messages[0]
            truncated = first_msg[:35] + "..." if len(first_msg) > 35 else first_msg
            preview = f"{truncated} (+{len(user_messages)-1} more)"

        updated_at = data.get("updated_at")
        created_at = data.get("created_at")

        sessions.append(
            {
                "id": session_id,
                "release": data.get("release", "Unknown"),
                "created_at": created_at.isoformat() if created_at else "",
                "message_count": len(messages),
                "user_message_count": len(user_messages),
                "preview": preview,
                "relative_time": _format_relative_time(updated_at or created_at),
            }
        )

    return sessions


def load_chat_session(session_id: str):
    """Load a specific chat session."""
    # Lazy init storage
    if _chat_storage_type is None:
        _init_chat_storage()

    if _chat_storage_type == "mongodb" and _chat_storage:
        try:
            doc = _chat_storage.load_chat(session_id)
            if doc:
                st.session_state.messages = doc.get("messages", [])
                st.session_state.session_id = session_id
                st.session_state.selected_release = doc.get("release") or st.session_state.selected_release
                return True
        except Exception as e:
            print(f"[ChatStorage] MongoDB load failed: {e}")

    # In-memory fallback
    if session_id in _in_memory_chats:
        data = _in_memory_chats[session_id]
        st.session_state.messages = data.get("messages", [])
        st.session_state.session_id = session_id
        st.session_state.selected_release = data.get("release") or st.session_state.selected_release
        return True

    return False


def new_chat_session():
    """Start a new chat session."""
    save_chat_session()  # Save current first
    st.session_state.messages = []
    st.session_state.session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    st.session_state.chat_sessions = load_chat_sessions()
    st.session_state._sessions_loaded = True


# ============ Session State ============


def init_session_state():
    """Initialize all session state variables (fast, no I/O)."""
    defaults = {
        "messages": [],
        "session_id": f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "available_releases": None,
        "selected_release": url_release,
        "ai_status": None,
        "is_running": False,
        "pending_query": None,
        "chat_sessions": None,  # None = not loaded yet (lazy load)
        "_sessions_loaded": False,  # Track if sessions have been loaded
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # DON'T load chat sessions here - defer to sidebar render for faster initial load


init_session_state()

# Inject CSS to disable inputs when running
inject_running_state_css()


# ============ Background Agent Pre-warming ============
# Start loading the agent in background while user sees the UI
# This makes the first query much faster

_agent_prewarm_started = False


def _prewarm_agent_background():
    """Pre-warm the agent in a background thread (non-blocking)."""
    global _agent_prewarm_started
    if _agent_prewarm_started:
        return
    _agent_prewarm_started = True

    def _do_prewarm():
        try:
            import sys

            print("[Prewarm] Starting background agent initialization...", file=sys.stderr)
            # Import the heavy modules in background
            from release_readiness_agent.tools.mcp_tools import check_mcp_available

            if check_mcp_available():
                print("[Prewarm] MCP modules loaded, agent ready to initialize on first query", file=sys.stderr)
        except Exception as e:
            import sys

            print(f"[Prewarm] Background init failed (non-critical): {e}", file=sys.stderr)

    # Run in background thread so page loads immediately
    import threading

    thread = threading.Thread(target=_do_prewarm, daemon=True)
    thread.start()


# Start pre-warming immediately (runs while CSS/UI renders)
if not FAST_STARTUP:  # Skip in fast startup mode
    _prewarm_agent_background()


# ============ Helper Functions ============


@st.cache_resource
def _get_ai_config():
    """Get AI agent config (cached)."""
    from config import get_settings

    return get_settings()


def get_cached_root_agent():
    """
    Get root agent instance with MCP tools.

    Note: NOT cached with @st.cache_resource because MCP connections
    are bound to the event loop they were created in. Instead, we
    cache in session_state which is tied to the current session.
    """
    import sys

    # Get current loop id to detect loop changes
    current_loop = _get_async_loop()
    current_loop_id = id(current_loop)

    # Check if agent exists and is tied to the current loop
    if "root_agent" in st.session_state and st.session_state.root_agent is not None:
        # Verify the agent was created in the same loop
        if st.session_state.get("_agent_loop_id") == current_loop_id:
            return st.session_state.root_agent
        else:
            # Loop changed - invalidate cached agent and runner
            print("[Agent] Event loop changed, recreating agent...", file=sys.stderr)
            if "root_agent" in st.session_state:
                del st.session_state.root_agent
            if "runner" in st.session_state:
                del st.session_state.runner
            if "mcp_cleanup" in st.session_state:
                try:
                    # Try to cleanup old MCP connections
                    st.session_state.mcp_cleanup()
                except (OSError, RuntimeError):
                    pass
                del st.session_state.mcp_cleanup

    try:
        from release_readiness_agent.tools.mcp_tools import check_mcp_available
        from root_agent import create_root_agent_async
    except ImportError as e:
        raise RuntimeError(f"Failed to import MCP modules: {e}")

    if not check_mcp_available():
        raise RuntimeError("MCP support not available. Install with: pip install google-adk[mcp]>=0.5.0")

    print("[Agent] Initializing MCP servers for tools...", file=sys.stderr)

    try:
        # Create agent in the dedicated async loop
        agent, cleanup = run_async(create_root_agent_async())

        # Store in session state (not cache_resource)
        st.session_state.root_agent = agent
        st.session_state.mcp_cleanup = cleanup
        st.session_state._agent_loop_id = current_loop_id  # Track which loop created this agent

        print("[Agent] MCP servers initialized successfully", file=sys.stderr)
        return agent
    except BrokenPipeError as e:
        print(f"[Agent] MCP server subprocess crashed: {e}", file=sys.stderr)
        raise RuntimeError("MCP server crashed on startup. Check server logs.") from e
    except ConnectionError as e:
        print(f"[Agent] MCP connection failed: {e}", file=sys.stderr)
        raise RuntimeError(f"Failed to connect to MCP servers: {e}")
    except Exception as e:
        import traceback

        traceback.print_exc(file=sys.stderr)
        raise RuntimeError(f"Failed to initialize MCP servers: {type(e).__name__}: {e}")


# Backward compatibility alias
def get_cached_orchestrator():
    """Alias for get_cached_root_agent (backward compatibility)."""
    return get_cached_root_agent()


def get_cached_runner():
    """
    Get runner instance - stored in session_state to match agent's loop context.

    IMPORTANT: We create a NEW AgentRunner per session, not using the global singleton.
    This ensures the runner's internal caches (Runner instances, sessions) are tied
    to the current event loop where the MCP connections live.
    """
    # Get current loop id
    current_loop = _get_async_loop()
    current_loop_id = id(current_loop)

    # Check if runner exists and is tied to the current loop
    if "runner" in st.session_state and st.session_state.runner is not None:
        if st.session_state.get("_runner_loop_id") == current_loop_id:
            return st.session_state.runner
        else:
            # Loop changed - invalidate runner
            del st.session_state.runner

    # Create a NEW AgentRunner for this session (don't use global singleton)
    from core.runner import AgentRunner

    runner = AgentRunner()
    st.session_state.runner = runner
    st.session_state._runner_loop_id = current_loop_id
    return runner


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_releases_sync():
    """Fetch releases from backend API (cached, sync version for performance)."""
    try:
        import httpx

        with httpx.Client(timeout=3, verify=False) as client:  # Reduced timeout, sync
            response = client.get(f"{BACKEND_URL}/api/releases")
            if response.status_code == 200:
                data = response.json()
                releases = data.get("releases", [])
                return {
                    "releases": [r.get("display_name", r.get("id")) for r in releases],
                    "current": next((r.get("id") for r in releases if r.get("is_current")), None),
                    "mapping": {r.get("display_name", r.get("id")): r.get("id") for r in releases},
                }
    except Exception:
        pass

    # Fallback data - use config's default release (fast path if backend unavailable)
    return {
        "releases": [_DEFAULT_RELEASE, "R133"],
        "current": _DEFAULT_RELEASE,
        "mapping": {_DEFAULT_RELEASE: _DEFAULT_RELEASE, "R133": "R133"},
    }


async def fetch_releases_from_api():
    """Async wrapper for backward compatibility."""
    return fetch_releases_sync()


async def get_ai_status():
    """Get AI system status."""
    try:
        settings = _get_ai_config()
        from core.base import check_adk_available

        adk_ok = check_adk_available()
        llm_available = False

        if adk_ok and settings.is_ollama():
            try:
                import httpx

                ollama_cfg = settings.get_ollama_config()
                async with httpx.AsyncClient(timeout=5, verify=False) as client:
                    response = await client.get(
                        f"{ollama_cfg['base_url'].rstrip('/')}/models",
                        headers=ollama_cfg.get("headers", {}),
                    )
                    llm_available = response.status_code == 200
            except (httpx.HTTPError, OSError):
                pass

        return {"llm_available": llm_available, "model": settings.llm_model}
    except Exception as e:
        return {"llm_available": False, "error": str(e)}


# ============ Status Bar HTML ============


def get_status_bar_html(is_running: bool = False) -> str:
    """Get the HTML for the top-right status indicator."""
    if is_running:
        return """
        <div class="top-status-bar">
            <span class="status-dot running"></span>
            <span class="status-text running">Running</span>
            <button class="stop-btn" onclick="window.location.reload();">Stop</button>
        </div>
        """
    else:
        return """
        <div class="top-status-bar">
            <span class="status-dot ready"></span>
            <span class="status-text ready">Ready</span>
        </div>
        """


# ============ Process Query with Real-time Logs ============


def process_query_with_logs(query: str, log_placeholder, status_placeholder):
    """Process a query and show real-time logs."""
    import time

    all_logs = []

    def update_ui(logs):
        """Update UI with current logs (must be called from main thread)."""
        log_html = "".join(
            [f'<div class="processing-step {log["status"]}">{log["icon"]} {log["message"]}</div>' for log in logs]
        )

        log_placeholder.markdown(
            f"""
        <div class="processing-log">
            <div class="processing-header">
                <span class="animate-spin">⚙️</span> Processing...
            </div>
            {log_html}
        </div>
        """,
            unsafe_allow_html=True,
        )

        status_placeholder.markdown(get_status_bar_html(is_running=True), unsafe_allow_html=True)

    def add_log(message: str, status: str = "running"):
        """Add a log entry (thread-safe, no UI updates)."""
        icon = "✅" if status == "complete" else "❌" if status == "error" else "⏳"
        all_logs.append({"icon": icon, "message": message, "status": status})

    # Show initial status in main thread
    add_log("Connecting to AI orchestrator (root_agent)...")
    update_ui(all_logs)
    time.sleep(0.1)

    # Get agent and runner in main thread first (they're cached)
    try:
        root_agent = get_cached_root_agent()
        # Show sub-agents available
        sub_agent_names = (
            [sa.name for sa in getattr(root_agent, "sub_agents", [])] if hasattr(root_agent, "sub_agents") else []
        )
        if sub_agent_names:
            add_log(f"Sub-agents: {', '.join(sub_agent_names)}")
        add_log("Orchestrator connected")
        update_ui(all_logs)
    except Exception as agent_err:
        error_msg = f"Failed to initialize AI agent: {agent_err}"
        add_log(error_msg, "error")
        update_ui(all_logs)
        return {"response": error_msg, "error": True, "logs": all_logs}

    try:
        runner = get_cached_runner()
    except Exception as runner_err:
        error_msg = f"Failed to initialize runner: {runner_err}"
        add_log(error_msg, "error")
        update_ui(all_logs)
        return {"response": error_msg, "error": True, "logs": all_logs}

    add_log(f"Processing: \"{query[:50]}{'...' if len(query) > 50 else ''}\"")
    update_ui(all_logs)

    # Capture session state values before going to thread
    session_id = st.session_state.session_id
    release_context = st.session_state.selected_release

    # Run the async query in the MCP thread
    async def run_query():
        try:
            response = await runner.run(
                agent=root_agent,
                message=query,
                session_id=session_id,
                release_context=release_context,
            )
            # Determine which agent handled the query
            agent_used = (
                response.agent_name if hasattr(response, "agent_name") and response.agent_name else "root_agent"
            )
            tools_info = response.tools_used if response.tools_used else []

            return {
                "success": True,
                "response": response.content,
                "tools_used": tools_info,
                "sources": response.sources,
                "agent_used": agent_used,
            }
        except Exception as e:
            import sys
            import traceback

            traceback.print_exc(file=sys.stderr)
            return {
                "success": False,
                "error": f"{type(e).__name__}: {str(e)}",
            }

    # Execute in thread pool
    result = run_async(run_query())

    # Update UI with results (back in main thread)
    if result.get("success"):
        # Show which agent handled the query
        agent_used = result.get("agent_used", "root_agent")
        tools_used = result.get("tools_used", [])

        # Determine sub-agent from tools used
        if tools_used:
            if any("jenkins" in t.lower() for t in tools_used):
                sub_agent = "jenkiollama"
            elif any("jira" in t.lower() for t in tools_used):
                sub_agent = "release_readiness"
            elif any("calendar" in t.lower() or "github" in t.lower() for t in tools_used):
                sub_agent = "release_readiness"
            elif "transfer_to_agent" in tools_used:
                # Try to determine from other tools
                other_tools = [t for t in tools_used if t != "transfer_to_agent"]
                if other_tools:
                    if any("jenkins" in t.lower() for t in other_tools):
                        sub_agent = "jenkiollama"
                    else:
                        sub_agent = "release_readiness"
                else:
                    sub_agent = agent_used
            else:
                sub_agent = agent_used
        else:
            sub_agent = agent_used

        add_log(f"Routed to: {sub_agent}")
        if tools_used:
            # Filter out transfer_to_agent for cleaner display
            display_tools = [t for t in tools_used if t != "transfer_to_agent"]
            if display_tools:
                add_log(f"Tools: {', '.join(display_tools)}")
        add_log("Response ready!", "complete")
        update_ui(all_logs)

        # Filter non-English content from response
        filtered_response = filter_non_english_text(result["response"])

        return {
            "response": filtered_response,
            "tools_used": result.get("tools_used"),
            "sources": result.get("sources"),
            "agent_used": agent_used,
            "logs": all_logs,
        }
    else:
        error_msg = result.get("error", "Unknown error")
        add_log(f"Error: {error_msg}", "error")
        update_ui(all_logs)
        return {"response": f"Error: {error_msg}", "error": True, "logs": all_logs}


# ============ Copy Button ============
# Uses JavaScript clipboard API for browser-based copy functionality

# Global flag to control copy button rendering (can be disabled for performance)
ENABLE_COPY_BUTTONS = os.environ.get("DISABLE_COPY_BUTTONS", "").lower() not in ("true", "1", "yes")


def render_copy_button(content: str, key: str):
    """
    Render a copy button using JavaScript clipboard API.
    This works in browser context (pyperclip doesn't work in browsers).
    """
    if not ENABLE_COPY_BUTTONS:
        return

    import base64

    import streamlit.components.v1 as components

    # Encode content as base64 to avoid escaping issues
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Minimal JavaScript copy button
    copy_html = f"""
    <div style="display: flex; justify-content: flex-end; margin-top: 4px;">
        <button onclick="copyText_{key.replace('-', '_')}()" style="
            background: #f8f9fa; border: 1px solid #dee2e6; color: #495057;
            padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
        " id="btn_{key}">📋 Copy</button>
    </div>
    <script>
    function copyText_{key.replace('-', '_')}() {{
        const text = atob("{content_b64}");
        navigator.clipboard.writeText(text).then(() => {{
            document.getElementById("btn_{key}").innerText = "✓ Copied!";
            document.getElementById("btn_{key}").style.color = "#28a745";
            setTimeout(() => {{
                document.getElementById("btn_{key}").innerText = "📋 Copy";
                document.getElementById("btn_{key}").style.color = "#495057";
            }}, 2000);
        }}).catch(() => {{
            // Fallback for non-secure contexts
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            document.getElementById("btn_{key}").innerText = "✓ Copied!";
            setTimeout(() => document.getElementById("btn_{key}").innerText = "📋 Copy", 2000);
        }});
    }}
    </script>
    """
    components.html(copy_html, height=40)


# ============ Sidebar ============

with st.sidebar:
    st.markdown("## 🚀 Release AI")
    st.caption("Powered by ADK")

    # New Chat button - prominent at top
    if st.button("➕ New Chat", use_container_width=True, disabled=st.session_state.is_running, type="primary"):
        new_chat_session()
        st.rerun()

    st.divider()

    # Chat History
    st.markdown("##### 💬 Chat History")

    # Lazy load sessions (only once per session, not on every rerun)
    if not st.session_state.get("_sessions_loaded", False):
        st.session_state.chat_sessions = load_chat_sessions()
        st.session_state._sessions_loaded = True

    if st.session_state.chat_sessions:
        for session in st.session_state.chat_sessions[:8]:
            is_current = session["id"] == st.session_state.session_id

            # Create a more informative label
            preview = session.get("preview", "New chat")
            time_str = session.get("relative_time", "")

            # Style current session differently
            if is_current:
                st.markdown(
                    f"""
                <div style="background: rgba(99, 102, 241, 0.1); border-left: 3px solid #6366f1;
                            padding: 8px 12px; margin: 4px 0; border-radius: 0 8px 8px 0;">
                    <div style="font-size: 13px; font-weight: 500; color: #6366f1;">💬 {preview}</div>
                    <div style="font-size: 11px; color: #888; margin-top: 2px;">{session['release']} • {time_str}</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            else:
                # Clickable session button
                user_count = session.get("user_message_count", session["message_count"] // 2)
                if st.button(
                    f"💬 {preview}",
                    key=f"load_{session['id']}",
                    use_container_width=True,
                    disabled=st.session_state.is_running,
                    help=f"{session['release']} • {user_count} questions • {time_str}",
                ):
                    load_chat_session(session["id"])
                    st.rerun()
    else:
        st.caption("_No previous chats. Start a conversation!_")

    st.divider()

    # Release Selector (cached, no async needed)
    if st.session_state.available_releases is None:
        st.session_state.available_releases = fetch_releases_sync()

    releases_data = st.session_state.available_releases
    display_releases = releases_data.get("releases", [])
    release_mapping = releases_data.get("mapping", {})
    current_release = releases_data.get("current", _DEFAULT_RELEASE)

    if not st.session_state.selected_release:
        st.session_state.selected_release = current_release

    current_display = next(
        (disp for disp, rid in release_mapping.items() if rid == st.session_state.selected_release),
        display_releases[0] if display_releases else _DEFAULT_RELEASE,
    )

    st.markdown("##### 📦 Release")
    selected_display = st.selectbox(
        "Release",
        display_releases,
        index=display_releases.index(current_display) if current_display in display_releases else 0,
        label_visibility="collapsed",
        disabled=st.session_state.is_running,
    )
    st.session_state.selected_release = release_mapping.get(selected_display, selected_display)

    st.divider()

    # Quick Actions - collapsible
    with st.expander("⚡ Quick Actions", expanded=False):
        actions = [
            ("📊", "Release Status", "What's the release status?"),
            ("🐛", "Critical Bugs", "Show critical bugs"),
            ("📅", "Key Dates", "When is branch cut?"),
            ("👥", "Workload", "Who has most open items?"),
            ("📝", "Commits", "Any commits after branch cut?"),
            ("⚠️", "Escalations", "Show escalations"),
            ("🔧", "Pipeline Status", "What's the pipeline status?"),
        ]

        for icon, label, query in actions:
            if st.button(
                f"{icon} {label}", key=f"qa_{label}", use_container_width=True, disabled=st.session_state.is_running
            ):
                st.session_state.pending_query = query
                st.rerun()

    # Jenkins Pipelines - collapsible (lazy loaded)
    with st.expander("🔧 Jenkins Pipelines", expanded=False):
        # Initialize state
        if "jenkins_status" not in st.session_state:
            st.session_state.jenkins_status = None
        if "jenkins_fetched" not in st.session_state:
            st.session_state.jenkins_fetched = False

        if st.button("🔄 Refresh", key="refresh_jenkins", use_container_width=True):
            st.session_state.jenkins_status = None
            st.session_state.jenkins_fetched = False

        # Only fetch when expander is opened AND not yet fetched (lazy load)
        if not st.session_state.jenkins_fetched:
            st.session_state.jenkins_fetched = True
            try:
                import httpx

                with httpx.Client(timeout=3.0) as client:  # Reduced timeout
                    response = client.get(f"{BACKEND_URL}/api/jenkins/pipelines")
                    if response.status_code == 200:
                        st.session_state.jenkins_status = response.json()
                    else:
                        st.session_state.jenkins_status = {"error": f"Status {response.status_code}"}
            except Exception as e:
                st.session_state.jenkins_status = {"error": str(e)}

        jenkins_data = st.session_state.jenkins_status
        if jenkins_data and not jenkins_data.get("error"):
            overall = jenkins_data.get("overall", {})
            health = overall.get("healthPercent", 0)

            # Health indicator
            if health >= 80:
                st.success(f"✅ Health: {health}%")
            elif health >= 50:
                st.warning(f"⚠️ Health: {health}%")
            else:
                st.error(f"❌ Health: {health}%")

            # Pipeline counts
            st.caption(
                f"Total: {overall.get('totalPipelines', 0)} | ✅ {overall.get('passing', 0)} | ❌ {overall.get('failing', 0)} | ⚠️ {overall.get('unstable', 0)}"
            )

            # Quick query buttons
            if st.button(
                "📋 Show Details", key="jenkins_details", use_container_width=True, disabled=st.session_state.is_running
            ):
                st.session_state.pending_query = "Show Jenkins pipeline status with details"
                st.rerun()
        elif jenkins_data and jenkins_data.get("error"):
            st.caption(f"_Jenkins: {jenkins_data.get('error', 'Not connected')[:30]}_")
        else:
            st.caption("_Loading..._")

    # System Status - collapsible
    with st.expander("⚙️ System", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Check Status", use_container_width=True, disabled=st.session_state.is_running):
                st.session_state.ai_status = run_async(get_ai_status())
        with col2:
            if st.button("Reset AI", use_container_width=True, disabled=st.session_state.is_running):
                # Clear agent from session state
                if "root_agent" in st.session_state:
                    del st.session_state.root_agent
                if "mcp_cleanup" in st.session_state:
                    del st.session_state.mcp_cleanup
                if "runner" in st.session_state:
                    del st.session_state.runner
                st.toast("AI cache cleared!")
                st.rerun()

        if st.session_state.ai_status:
            if st.session_state.ai_status.get("llm_available"):
                st.success(f"✅ {st.session_state.ai_status.get('model', 'LLM')} Ready")
            else:
                st.error("❌ LLM Offline")

        # Storage status
        st.markdown("---")
        storage_type = get_chat_storage_type()
        storage_icon = "🍃" if storage_type == "mongodb" else "🧠"
        st.caption(f"{storage_icon} Storage: {storage_type.upper()}")


# ============ Main Content ============

# Status bar placeholder - single source of truth for status
status_placeholder = st.empty()
status_placeholder.markdown(get_status_bar_html(st.session_state.is_running), unsafe_allow_html=True)

# Header with controls (since sidebar may not be visible)
col_title, col_controls = st.columns([0.7, 0.3])

with col_title:
    st.markdown(
        f"""
    <h1 class="hero-title">Release AI Assistant</h1>
    <p class="hero-subtitle">Ask about {st.session_state.selected_release or 'the release'}</p>
    """,
        unsafe_allow_html=True,
    )

with col_controls:
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns(3)
    with ctrl_col1:
        if st.button("🔄 Reset AI", disabled=st.session_state.is_running, help="Clear AI cache"):
            # Clear agent from session state
            if "root_agent" in st.session_state:
                del st.session_state.root_agent
            if "mcp_cleanup" in st.session_state:
                del st.session_state.mcp_cleanup
            if "runner" in st.session_state:
                del st.session_state.runner
            st.toast("AI cache cleared!")
            st.rerun()
    with ctrl_col2:
        if st.button("🗑️ Clear Chat", disabled=st.session_state.is_running):
            st.session_state.messages = []
            st.rerun()
    with ctrl_col3:
        if st.button("➕ New", disabled=st.session_state.is_running):
            new_chat_session()
            st.rerun()

st.markdown("---")


# ============ Welcome Screen ============

if not st.session_state.messages:
    current_rel = st.session_state.selected_release or _DEFAULT_RELEASE

    st.markdown(
        f"""
    <div class="welcome-card" style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-color: #bae6fd;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <div class="welcome-card-icon" style="background: #0ea5e9; color: white;">👋</div>
            <div>
                <p class="welcome-card-title">Welcome! I'm your Release Readiness Assistant</p>
                <p class="welcome-card-desc">I can help you understand the status of {current_rel}</p>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            """
        <div class="welcome-card">
            <div class="welcome-card-icon" style="background: #dcfce7; color: #16a34a;">📊</div>
            <p class="welcome-card-title">Release Health</p>
            <p class="welcome-card-desc">RRS score, bugs, stories</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
        <div class="welcome-card">
            <div class="welcome-card-icon" style="background: #fef3c7; color: #d97706;">📅</div>
            <p class="welcome-card-title">Milestones</p>
            <p class="welcome-card-desc">IRR, Branch Cut, Final Build</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            """
        <div class="welcome-card">
            <div class="welcome-card-icon" style="background: #fce7f3; color: #db2777;">🐛</div>
            <p class="welcome-card-title">Bug Tracking</p>
            <p class="welcome-card-desc">Critical bugs, blockers</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### 💡 Try asking:")

    suggestions = [f"Is {current_rel} green?", "Show critical bugs", "When is branch cut?", "Who has most items?"]
    cols = st.columns(len(suggestions))
    for i, suggestion in enumerate(suggestions):
        with cols[i]:
            if st.button(suggestion, key=f"sug_{i}", use_container_width=True, disabled=st.session_state.is_running):
                st.session_state.pending_query = suggestion
                st.rerun()


# ============ Chat Messages ============

for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🤖"):
        if msg["role"] == "assistant":
            # Show logs if available
            logs = msg.get("logs", [])
            if logs:
                with st.status("Processing complete", expanded=False, state="complete"):
                    for log in logs:
                        st.write(f"{log.get('icon', '•')} {log.get('message', '')}")

            st.markdown(msg["content"])
            render_copy_button(msg["content"], f"msg_{idx}")

            if msg.get("sources"):
                source_html = " ".join([f'<span class="source-tag">{s}</span>' for s in msg["sources"]])
                st.markdown(f"<div style='margin-top: 0.5rem;'>{source_html}</div>", unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])


# ============ Handle Pending Query (from buttons or chat input) ============

if st.session_state.pending_query:
    # Set running state FIRST, then rerun to disable all inputs
    if not st.session_state.is_running:
        st.session_state.is_running = True
        st.rerun()  # Rerun immediately so all inputs show as disabled

    # Now process the query (is_running is True, inputs are disabled)
    query = st.session_state.pending_query
    st.session_state.pending_query = None

    # Add user message
    st.session_state.messages.append({"role": "user", "content": query})

    # Show user message
    with st.chat_message("user", avatar="👤"):
        st.markdown(query)

    # Process with logs
    with st.chat_message("assistant", avatar="🤖"):
        log_placeholder = st.empty()
        response = process_query_with_logs(query, log_placeholder, status_placeholder)

        log_placeholder.empty()

        # Show final logs
        if response.get("logs"):
            with st.status("✅ Complete", expanded=False, state="complete"):
                for log in response["logs"]:
                    st.write(f"{log['icon']} {log['message']}")

        st.markdown(response.get("response", "Error"))
        render_copy_button(response.get("response", ""), f"new_{len(st.session_state.messages)}")

        if response.get("sources"):
            source_html = " ".join([f'<span class="source-tag">{s}</span>' for s in response["sources"]])
            st.markdown(f"<div style='margin-top: 0.5rem;'>{source_html}</div>", unsafe_allow_html=True)

    # Save to state
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response.get("response", ""),
            "sources": response.get("sources", []),
            "tools_used": response.get("tools_used", []),
            "logs": response.get("logs", []),
        }
    )

    save_chat_session()

    # Reset running state and rerun to enable inputs again
    st.session_state.is_running = False
    st.rerun()


# ============ Chat Input ============

# Chat input - CSS disables it visually when is_running is True
placeholder_text = "Processing... Please wait" if st.session_state.is_running else "Ask about release readiness..."

if prompt := st.chat_input(placeholder_text):
    # Only process if not already running (CSS blocks input but belt-and-suspenders)
    if not st.session_state.is_running:
        st.session_state.pending_query = prompt
        st.rerun()

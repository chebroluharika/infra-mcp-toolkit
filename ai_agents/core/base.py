"""
ADK Agent Base
==============

Utilities for ADK agents with LiteLLM support.
Enables Ollama, OpenAI, Anthropic, Gemini backends.
"""

import logging
import os
import sys
from typing import Any

# Ensure ai_agents directory is in path for imports
_current_file = os.path.abspath(__file__)
_core_dir = os.path.dirname(_current_file)
_ai_agents_dir = os.path.dirname(_core_dir)

if _ai_agents_dir not in sys.path:
    sys.path.insert(0, _ai_agents_dir)

# Import config using direct path to avoid backend/config.py confusion
import importlib.util

_config_path = os.path.join(_ai_agents_dir, "config.py")
_spec = importlib.util.spec_from_file_location("ai_agents_config", _config_path)
_config_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config_module)
get_settings = _config_module.get_settings
AIAgentSettings = _config_module.AIAgentSettings

logger = logging.getLogger(__name__)

# Check ADK availability
try:
    from google.adk.models import LiteLlm
    from google.adk.sessions import InMemorySessionService

    HAS_ADK = True
    logger.info("Google ADK available")
except ImportError as e:
    HAS_ADK = False
    logger.warning("Google ADK not installed: %s. Install with: pip install google-adk>=0.5.0", e)

    # Create stub classes for type hints
    class Agent:
        pass

    class LlmAgent:
        pass

    class SequentialAgent:
        pass

    class ParallelAgent:
        pass

    class LoopAgent:
        pass

    class LiteLlm:
        pass

    class InMemorySessionService:
        pass


def get_litellm_model(use_routing_config: bool = False) -> Any:
    """
    Get LiteLLM model wrapper for ADK with optimized parameters for speed.

    Supports:
    - Ollama: OpenAI-compatible API with custom x-bf-vk header authentication
    - OpenAI: gpt-4o, gpt-4o-mini
    - Anthropic: anthropic/claude-3-sonnet
    - Gemini: gemini/gemini-2.0-flash

    Args:
        use_routing_config: If True, use lower temperature for routing decisions

    Returns:
        LiteLlm model wrapper for ADK
    """
    if not HAS_ADK:
        raise RuntimeError("Google ADK not installed")

    settings = get_settings()
    model_string = settings.get_litellm_model_string()
    api_key = settings.get_api_key()

    logger.info("Creating LiteLLM model: %s (provider: %s)", model_string, settings.llm_provider)

    # Choose temperature based on usage (routing vs tool selection)
    if use_routing_config:
        temperature = settings.routing_temperature
    else:
        temperature = settings.tool_selection_temperature

    # Optimized generation config for faster responses
    generation_config = {
        "max_tokens": 768,  # Reduced for faster generation (most responses are <500 tokens)
        "temperature": temperature,  # Configurable based on use case
        "top_p": 0.85,  # Tighter nucleus sampling for faster, more focused responses
        "request_timeout": 60,  # 60 second timeout (faster models don't need as long)
    }

    # For NS Agent Gateway (OpenAI-compatible with custom auth)
    if settings.llm_provider == "ollama":
        ollama_config = settings.get_ollama_config()
        if not ollama_config["base_url"]:
            raise RuntimeError("Ollama base URL not configured. Set ADK_OLLAMA_BASE_URL in .env")
        if not ollama_config["api_token"]:
            raise RuntimeError("Ollama API token not configured. Set ADK_OLLAMA_API_TOKEN in .env")

        auth_mode = ollama_config.get("auth_mode", "bearer")
        api_key = ollama_config.get("api_key", "ollama-dummy-key")

        logger.info("Configuring Ollama Gateway at: %s (auth_mode: %s)", ollama_config["base_url"], auth_mode)

        import json

        import litellm

        if auth_mode == "bearer":
            # Standard OpenAI-compatible Bearer auth
            # Use the token as the actual API key
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_API_BASE"] = ollama_config["base_url"]

            litellm.api_key = api_key
            litellm.api_base = ollama_config["base_url"]
            litellm.headers = {}  # No custom headers needed for bearer auth

            logger.info(
                "Ollama configured with Bearer auth (token: %s...)", api_key[:12] if len(api_key) > 12 else "***"
            )
        else:
            # Legacy Bifrost auth - use x-bf-vk header
            os.environ["OPENAI_API_KEY"] = "ollama-dummy-key"
            os.environ["OPENAI_API_BASE"] = ollama_config["base_url"]

            litellm.headers = ollama_config["headers"]
            litellm.api_base = ollama_config["base_url"]
            litellm.api_key = "ollama-dummy-key"

            # Set headers via environment variable as backup
            os.environ["LITELLM_HEADERS"] = json.dumps(ollama_config["headers"])

            # Pass extra_headers in generation_config for direct API calls
            generation_config["extra_headers"] = ollama_config["headers"]

            logger.info("Ollama configured with Bifrost auth (x-bf-vk: %s...)", ollama_config["api_token"][:12])

        return LiteLlm(
            model=model_string,
            api_base=ollama_config["base_url"],
            generation_config=generation_config,
            request_timeout=120,
        )

    # For cloud providers, set environment variables
    if api_key:
        if settings.llm_provider == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
        elif settings.llm_provider == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = api_key
        elif settings.llm_provider == "gemini":
            os.environ["GOOGLE_API_KEY"] = api_key

    return LiteLlm(model=model_string, generation_config=generation_config)


def ensure_ollama_configured():
    """
    Ensure Ollama is configured globally for LiteLLM.

    Call this early in application startup to ensure all LLM calls
    (including those made by ADK internally) have the correct auth.

    Supports two auth modes:
    - bearer: Standard OpenAI-compatible Authorization: Bearer header
    - bifrost: Legacy x-bf-vk header authentication
    """
    settings = get_settings()
    if settings.llm_provider != "ollama":
        return False

    ollama_config = settings.get_ollama_config()
    if not ollama_config["base_url"] or not ollama_config["api_token"]:
        return False

    import json

    import litellm

    auth_mode = ollama_config.get("auth_mode", "bearer")
    api_key = ollama_config.get("api_key", "ollama-dummy-key")

    if auth_mode == "bearer":
        # Standard Bearer auth - use token as API key
        litellm.api_key = api_key
        litellm.api_base = ollama_config["base_url"]
        litellm.headers = {}

        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_API_BASE"] = ollama_config["base_url"]

        logger.info("Ollama configured globally (bearer): %s", ollama_config["base_url"])
    else:
        # Legacy Bifrost auth - use x-bf-vk header
        litellm.headers = ollama_config["headers"]
        litellm.api_base = ollama_config["base_url"]
        litellm.api_key = "ollama-dummy-key"

        os.environ["OPENAI_API_KEY"] = "ollama-dummy-key"
        os.environ["OPENAI_API_BASE"] = ollama_config["base_url"]
        os.environ["LITELLM_HEADERS"] = json.dumps(ollama_config["headers"])

        logger.info("Ollama configured globally (bifrost): %s", ollama_config["base_url"])

    return True


# English enforcement system prompt
ENGLISH_SYSTEM_PROMPT = """CRITICAL INSTRUCTION: You MUST respond in English only.
- Do not use Thai (ภาษาไทย), Chinese (中文), Japanese, Korean, or any non-English language
- Do not use any non-English characters or scripts
- Do not use any non-ASCII characters for text content
- If you're unsure, default to English
- EVERY WORD must be in English - no exceptions
This is a strict requirement for all responses. Violating this will cause system failure.

"""


def get_english_system_prompt() -> str:
    """
    Get system prompt for English enforcement based on config settings.

    Returns:
        System prompt string to prepend to instructions, or empty string if disabled
    """
    settings = get_settings()

    # Check if English enforcement is enabled
    if getattr(settings, "enforce_english", True):
        return ENGLISH_SYSTEM_PROMPT

    # Fallback: Check if using a Chinese model that needs enforcement
    if getattr(settings, "enforce_english_for_qwen", True) and settings.is_chinese_model():
        return ENGLISH_SYSTEM_PROMPT

    return ""


def check_adk_available() -> bool:
    """Check if Google ADK is available."""
    return HAS_ADK


def get_session_service(persistent: bool = True, db_path: str = None) -> Any:
    """
    Get ADK session service for state management.

    Args:
        persistent: If True, use DatabaseSessionService for persistent storage
        db_path: Path to SQLite database (default: data/sessions.db)
    """
    if not HAS_ADK:
        raise RuntimeError("Google ADK not installed")

    if persistent:
        try:
            from google.adk.sessions import DatabaseSessionService

            if db_path is None:
                import pathlib

                data_dir = pathlib.Path(__file__).parent.parent / "data"
                data_dir.mkdir(exist_ok=True)
                db_path = str(data_dir / "sessions.db")
            return DatabaseSessionService(db_url=f"sqlite:///{db_path}")
        except ImportError:
            pass  # Fall back to in-memory

    return InMemorySessionService()

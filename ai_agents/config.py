"""
AI Agents Configuration
=======================

Centralized configuration for LLM models and agent settings.
All settings can be overridden via environment variables with ADK_ prefix.

Example:
    export ADK_LLM_PROVIDER=ollama
    export ADK_LLM_MODEL=llama3.2
    export OLLAMA_BASE_URL=http://gateway.example.com/v1
    export OLLAMA_API_KEY=sk-bf-...
"""

import os
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env from root folder (single source of truth)
try:
    from dotenv import load_dotenv

    # Find project root (parent of ai_agents folder)
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_current_dir)

    # Load .env from project root only
    load_dotenv(os.path.join(_project_root, ".env"))
except ImportError:
    pass  # dotenv not installed


def _get_default_release() -> str:
    """Get default release from environment - required, no hardcoded fallback."""
    release = os.getenv("CURRENT_RELEASE")
    if not release:
        raise ValueError(
            "CURRENT_RELEASE environment variable is required! " "Set it in your .env file or docker-compose.yml"
        )
    return release


class AIAgentSettings(BaseSettings):
    """Settings for AI Agent system."""

    # LLM Provider Configuration
    llm_provider: Literal["ollama", "openai", "gemini", "anthropic"] = Field(
        default="ollama", description="LLM provider to use (ollama for NS Agent Gateway)"
    )

    llm_model: str = Field(
        default="llama3.2",
        description="Model name. Override via ADK_LLM_MODEL env var. Examples: llama3.2, gpt-4o",
    )

    # NS Agent Gateway Configuration (OpenAI-compatible API with custom auth)
    ollama_base_url: str = Field(
        default="",
        description="NS Agent Gateway URL (e.g., http://internal-alb-gateway-nginx-....elb.amazonaws.com:4000/v1)",
    )
    ollama_api_token: str = Field(
        default="", description="NS Agent Gateway API token (Bearer token or x-bf-vk token depending on auth_mode)"
    )
    ollama_auth_mode: Literal["bearer", "bifrost"] = Field(
        default="bearer", description="Auth mode: 'bearer' for Authorization header, 'bifrost' for x-bf-vk header"
    )

    # Cloud Provider API Keys (optional)
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key (required if llm_provider=openai)")

    google_api_key: Optional[str] = Field(
        default=None, description="Google AI API key (required if llm_provider=gemini)"
    )

    anthropic_api_key: Optional[str] = Field(
        default=None, description="Anthropic API key (required if llm_provider=anthropic)"
    )

    # Agent Configuration
    enable_streaming: bool = Field(default=True, description="Enable streaming responses")

    max_conversation_history: int = Field(default=20, description="Maximum messages to keep in conversation history")

    agent_timeout: int = Field(default=300, description="Timeout in seconds for agent responses")

    # Natural Language Understanding Configuration
    use_nlp_routing: bool = Field(
        default=True, description="Use NLP embeddings for agent routing (fastest, no LLM call)"
    )

    use_semantic_routing: bool = Field(
        default=False,
        description="Use LLM for agent routing (slower but more accurate). Only used if use_nlp_routing=False",
    )

    use_simplified_instructions: bool = Field(
        default=True, description="Use LLM reasoning for tool selection (True) or decision tables (False)"
    )

    use_query_preprocessing: bool = Field(
        default=True, description="Preprocess queries to normalize abbreviations and entities"
    )

    use_prerouting: bool = Field(
        default=True,
        description="Enable pre-routing bypass for common queries (faster but bypasses LLM). "
        "Set to False to always use LLM for tool selection.",
    )

    enforce_english: bool = Field(default=True, description="Always add English-only enforcement in system prompts")

    enforce_english_for_qwen: bool = Field(
        default=True, description="Add extra English enforcement for Qwen/Chinese models"
    )

    use_structured_output: bool = Field(
        default=True, description="Require JSON structured output from LLM for routing/tool selection"
    )

    routing_confidence_threshold: float = Field(
        default=0.7, description="Minimum confidence to trust LLM routing (fallback to patterns if lower)"
    )

    routing_temperature: float = Field(
        default=0.1, description="Temperature for routing decisions (lower = more deterministic)"
    )

    tool_selection_temperature: float = Field(
        default=0.2, description="Temperature for tool selection (lower = more deterministic)"
    )

    # Retry Configuration
    max_routing_retries: int = Field(
        default=2, description="Max retries for routing before falling back to pattern matching"
    )

    max_tool_retries: int = Field(default=2, description="Max retries for tool selection before using fallback")

    # MCP Server Paths (relative to project root)
    mcp_servers_path: str = Field(default="mcp_servers", description="Path to MCP server directory")

    # Release Configuration
    available_releases: str = Field(
        default="R134,R135,R136,25.06,25.09", description="Comma-separated list of available releases"
    )

    default_release: str = Field(
        default_factory=_get_default_release, description="Default release to select (from CURRENT_RELEASE env var)"
    )

    def get_releases(self) -> list:
        """Get list of available releases."""
        return [r.strip() for r in self.available_releases.split(",") if r.strip()]

    model_config = {
        "env_prefix": "ADK_",
        "env_file": None,  # Don't require .env file; Docker passes env vars directly
        "extra": "ignore",
    }

    def get_litellm_model_string(self) -> str:
        """
        Get the model string in LiteLLM format.

        Returns:
            Model string like 'openai/llama3.2' or 'gpt-4o'
        """
        if self.llm_provider == "ollama":
            return f"openai/{self.llm_model}"
        if self.llm_provider == "openai":
            return self.llm_model
        if self.llm_provider == "gemini":
            return f"gemini/{self.llm_model}"
        if self.llm_provider == "anthropic":
            return f"anthropic/{self.llm_model}"
        return self.llm_model

    def get_api_key(self) -> Optional[str]:
        """Get the API key for the current provider."""
        if self.llm_provider == "ollama":
            # For bearer auth, use the token as API key; for bifrost, use dummy key
            if self.ollama_auth_mode == "bearer" and self.ollama_api_token:
                return self.ollama_api_token
            return "ollama-dummy-key"
        if self.llm_provider == "openai":
            return self.openai_api_key
        if self.llm_provider == "gemini":
            return self.google_api_key
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return None

    def get_ollama_config(self) -> dict:
        """Get NS Agent Gateway configuration for custom headers."""
        headers = {}
        api_key = "ollama-dummy-key"

        if self.ollama_api_token:
            if self.ollama_auth_mode == "bearer":
                # Standard OpenAI-compatible Bearer auth - use token as API key
                api_key = self.ollama_api_token
            else:
                # Legacy Bifrost auth - use x-bf-vk header
                headers = {"x-bf-vk": self.ollama_api_token}

        return {
            "base_url": self.ollama_base_url,
            "api_token": self.ollama_api_token,
            "api_key": api_key,
            "auth_mode": self.ollama_auth_mode,
            "headers": headers,
        }

    def is_ollama(self) -> bool:
        """Check if using NS Agent Gateway."""
        return self.llm_provider == "ollama"

    def is_qwen_model(self) -> bool:
        """Check if current model is a Qwen variant."""
        return "qwen" in self.llm_model.lower()

    def is_chinese_model(self) -> bool:
        """Check if model tends to generate Chinese text (Qwen, Baichuan, etc)."""
        chinese_models = ["qwen", "baichuan", "chatglm", "yi"]
        return any(model in self.llm_model.lower() for model in chinese_models)


# Singleton instance
_settings: Optional[AIAgentSettings] = None


def get_settings() -> AIAgentSettings:
    """Get AI Agent settings singleton."""
    global _settings  # pylint: disable=global-statement
    if _settings is None:
        _settings = AIAgentSettings()
    return _settings


def reload_settings() -> AIAgentSettings:
    """Reload settings from environment."""
    global _settings  # pylint: disable=global-statement
    _settings = AIAgentSettings()
    return _settings

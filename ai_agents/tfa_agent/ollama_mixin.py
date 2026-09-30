"""
LLM Client Mixin
=================

Foundation for all LLM agents.
Uses Ollama Gateway (OpenAI-compatible API).
Supports bearer auth (Authorization header) or bifrost auth (x-bf-vk header).
Falls back to pattern-based analysis if gateway is unavailable.
"""

import logging
import os
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


def _get_ollama_settings() -> Optional[Dict[str, str]]:
    """Read Ollama config from AIAgentSettings."""
    try:
        _ai_agents_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import importlib.util

        _config_path = os.path.join(_ai_agents_dir, "config.py")
        _spec = importlib.util.spec_from_file_location("ai_agents_config_tfa", _config_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        settings = _mod.get_settings()
        if settings.llm_provider == "ollama" and settings.ollama_base_url and settings.ollama_api_token:
            return {
                "base_url": settings.ollama_base_url.rstrip("/"),
                "api_token": settings.ollama_api_token,
                "model": settings.llm_model,
                "auth_mode": getattr(settings, "ollama_auth_mode", "bearer"),
            }
    except Exception as e:
        logger.debug("Could not load Ollama settings for TFA: %s", e)
    return None


def _get_auth_headers(api_token: str, auth_mode: str) -> Dict[str, str]:
    """Get authentication headers based on auth mode."""
    if auth_mode == "bearer":
        return {"Authorization": f"Bearer {api_token}"}
    else:
        # Legacy Bifrost auth
        return {"x-bf-vk": api_token}


class OllamaClient:
    """
    Lightweight client for Ollama Gateway (OpenAI-compatible chat/completions API).
    Supports bearer auth (Authorization header) or bifrost auth (x-bf-vk header).
    """

    def __init__(self, base_url: str, api_token: str, model: str, auth_mode: str = "bearer"):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.model = model
        self.auth_mode = auth_mode
        self._available = None

    async def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            headers = _get_auth_headers(self.api_token, self.auth_mode)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    self._available = resp.status == 200
                    return self._available
        except Exception as e:
            logger.warning("Ollama gateway not reachable: %s", e)
            self._available = False
            return False

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate via OpenAI-compatible chat/completions endpoint."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            **_get_auth_headers(self.api_token, self.auth_mode),
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.2,
        }
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        error_text = await resp.text()
                        logger.error("Ollama error %s: %s", resp.status, error_text[:200])
                        if resp.status >= 500 and attempt < max_retries - 1:
                            import asyncio

                            await asyncio.sleep(1 + attempt)
                            continue
                        return ""
            except aiohttp.ClientConnectorError:
                logger.error("Cannot connect to Ollama gateway at %s", self.base_url)
                if attempt < max_retries - 1:
                    import asyncio

                    await asyncio.sleep(1 + attempt)
                    continue
                return ""
            except Exception as e:
                logger.error("Ollama request failed: %s", e)
                if attempt < max_retries - 1:
                    import asyncio

                    await asyncio.sleep(1 + attempt)
                    continue
                return ""
        return ""


class OllamaMixin:
    """
    Mixin providing LLM client management via Ollama Gateway.

    Usage:
        class MyAgent(OllamaMixin):
            def __init__(self):
                self._init_ollama()
    """

    def _init_ollama(self, model: str = None):
        """Initialize LLM instance attributes. Call this in subclass __init__."""
        self._llm_client = None
        self._llm_available = None
        self._llm_backend = None  # "ollama" | None
        self._llm_model_name = None

    @property
    def llm_backend(self) -> Optional[str]:
        """Which LLM backend is active: 'ollama' or None."""
        return self._llm_backend

    @property
    def llm_model_name(self) -> Optional[str]:
        """The model name currently in use."""
        return self._llm_model_name

    async def _get_ollama(self):
        """
        Get Ollama LLM client. Lazy-loaded and cached.
        Returns an object with generate() and chat() methods, or None if unavailable.
        """
        if self._llm_available is not None:
            return self._llm_client if self._llm_available else None

        ollama_cfg = _get_ollama_settings()
        if ollama_cfg:
            client = OllamaClient(
                base_url=ollama_cfg["base_url"],
                api_token=ollama_cfg["api_token"],
                model=ollama_cfg["model"],
                auth_mode=ollama_cfg.get("auth_mode", "bearer"),
            )
            if await client.is_available():
                logger.info(
                    "TFA using Ollama Gateway: model=%s (auth: %s)",
                    ollama_cfg["model"],
                    ollama_cfg.get("auth_mode", "bearer"),
                )
                self._llm_client = client
                self._llm_available = True
                self._llm_backend = "ollama"
                self._llm_model_name = ollama_cfg["model"]
                return self._llm_client

        logger.info(
            "No LLM available for TFA, using pattern-based analysis. "
            "To enable LLM: set ADK_LLM_PROVIDER, ADK_OLLAMA_BASE_URL, ADK_OLLAMA_API_TOKEN in .env"
        )
        self._llm_client = None
        self._llm_available = False
        self._llm_backend = None
        self._llm_model_name = None
        return None

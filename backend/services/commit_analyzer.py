"""
Commit Analyzer Service
=======================
Analyzes git commits using LLM (via Ollama Gateway) to provide:
- Semantic understanding of code changes
- Files changed summary grouped by component
- Predicted test impact areas
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp
from config import get_test_areas_for_file

logger = logging.getLogger(__name__)


def _get_ollama_config() -> Optional[Dict[str, str]]:
    """Read Ollama config from environment (shared with ai_agents config)."""
    provider = os.getenv("ADK_LLM_PROVIDER", "")
    base_url = os.getenv("ADK_OLLAMA_BASE_URL", "").rstrip("/")
    api_token = os.getenv("ADK_OLLAMA_API_TOKEN", "")
    model = os.getenv("ADK_LLM_MODEL", "")
    auth_mode = os.getenv("ADK_OLLAMA_AUTH_MODE", "bearer")  # "bearer" or "bifrost"

    if provider == "ollama" and base_url and api_token and model:
        return {
            "base_url": base_url,
            "api_token": api_token,
            "model": model,
            "auth_mode": auth_mode,
        }

    missing = []
    if provider != "ollama":
        missing.append(f"ADK_LLM_PROVIDER={provider!r} (expected 'ollama')")
    if not base_url:
        missing.append("ADK_OLLAMA_BASE_URL (empty)")
    if not api_token:
        missing.append("ADK_OLLAMA_API_TOKEN (empty)")
    if not model:
        missing.append("ADK_LLM_MODEL (empty)")
    logger.warning("Ollama not configured for commit analysis. Missing: %s", ", ".join(missing))
    return None


def _get_auth_headers(api_token: str, auth_mode: str) -> Dict[str, str]:
    """Get authentication headers based on auth mode."""
    if auth_mode == "bearer":
        return {"Authorization": f"Bearer {api_token}"}
    else:
        # Legacy Bifrost auth
        return {"x-bf-vk": api_token}


COMMIT_ANALYSIS_PROMPT = """You are a code analysis expert. Analyze the following git commit and provide insights.

Your task is to:
1. Summarize what the commit does in 2-3 sentences (focus on the "why" not the "what")
2. Identify the main components/areas affected
3. Assess the risk level (low/medium/high) based on the scope and complexity of changes
4. Suggest what types of testing would be most important for this change

Be concise and technical. Focus on actionable insights for QA engineers.

IMPORTANT: Respond ONLY in valid JSON format with this exact structure:
{
    "summary": "Brief description of what this commit does and why",
    "components": ["component1", "component2"],
    "risk_level": "low|medium|high",
    "risk_reason": "Brief explanation of risk assessment",
    "testing_recommendations": ["Test type 1", "Test type 2"],
    "key_changes": ["Change 1", "Change 2"]
}
"""


class CommitAnalyzer:
    """Analyzes commits using LLM via Ollama Gateway."""

    def __init__(self):
        cfg = _get_ollama_config()
        if cfg:
            self._base_url = cfg["base_url"]
            self._api_token = cfg["api_token"]
            self._model = cfg["model"]
            self._auth_mode = cfg.get("auth_mode", "bearer")
            self._configured = True
        else:
            self._base_url = ""
            self._api_token = ""
            self._model = ""
            self._auth_mode = "bearer"
            self._configured = False

    async def _call_llm(self, prompt: str) -> str:
        """Call Ollama Gateway (OpenAI-compatible chat/completions)."""
        if not self._configured:
            logger.warning("Ollama not configured for commit analysis")
            return ""

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            **_get_auth_headers(self._api_token, self._auth_mode),
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": COMMIT_ANALYSIS_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info("Calling Ollama for commit analysis: model=%s", self._model)
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                            logger.info("Ollama commit analysis response: %d chars", len(content))
                            return content
                        error_text = await resp.text()
                        logger.error("Ollama commit analysis error %s: %s", resp.status, error_text[:200])
                        if resp.status >= 500 and attempt < max_retries - 1:
                            await asyncio.sleep(1 + attempt)
                            continue
                        return ""
            except aiohttp.ClientConnectorError:
                logger.error("Cannot connect to Ollama at %s", self._base_url)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 + attempt)
                    continue
                return ""
            except Exception as e:
                logger.error("Ollama commit analysis failed: %s", e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 + attempt)
                    continue
                return ""
        return ""

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON response from LLM, handling markdown code blocks."""
        if not response:
            return {}

        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response as JSON: %s", e)
            return {"summary": response[:500], "parse_error": True}

    def _aggregate_test_areas(self, files: List[Dict]) -> Dict[str, int]:
        """Aggregate test areas from all changed files."""
        test_area_counts = {}
        for file in files:
            filepath = file.get("filename", "")
            areas = get_test_areas_for_file(filepath)
            for area in areas:
                test_area_counts[area] = test_area_counts.get(area, 0) + 1
        return test_area_counts

    def _group_files_by_component(self, files: List[Dict]) -> Dict[str, List[Dict]]:
        """Group files by their top-level directory/component."""
        grouped = {}
        for file in files:
            filepath = file.get("filename", "")
            parts = filepath.split("/")
            component = parts[0] if len(parts) > 1 else "root"
            if component not in grouped:
                grouped[component] = []
            grouped[component].append(file)
        return grouped

    async def analyze_commit(self, commit_data: Dict, include_llm_analysis: bool = True) -> Dict[str, Any]:
        """
        Analyze a single commit.

        Args:
            commit_data: Commit details from GitHub API (includes files, stats, message)
            include_llm_analysis: Whether to include LLM semantic analysis

        Returns:
            Analysis result with files summary, test impact, and LLM insights
        """
        files = commit_data.get("files", [])
        stats = commit_data.get("stats", {})
        message = commit_data.get("message", "")
        sha = commit_data.get("sha", "")

        files_by_component = self._group_files_by_component(files)
        test_areas = self._aggregate_test_areas(files)

        result = {
            "sha": sha,
            "message": message.split("\n")[0][:100],
            "full_message": message,
            "stats": stats,
            "files_changed": len(files),
            "files_by_component": {
                component: {
                    "count": len(component_files),
                    "files": [
                        {
                            "filename": f["filename"],
                            "status": f["status"],
                            "additions": f["additions"],
                            "deletions": f["deletions"],
                        }
                        for f in component_files
                    ],
                }
                for component, component_files in files_by_component.items()
            },
            "test_impact": {
                "areas": test_areas,
                "primary_areas": sorted(test_areas.keys(), key=lambda x: -test_areas[x])[:5],
            },
            "llm_analysis": None,
        }

        if include_llm_analysis and files:
            if not self._configured:
                result["llm_analysis"] = {
                    "available": False,
                    "error": "Ollama not configured. Set ADK_OLLAMA_BASE_URL and ADK_OLLAMA_API_TOKEN in .env",
                }
            else:
                files_summary = "\n".join(
                    [f"- {f['filename']} ({f['status']}: +{f['additions']}/-{f['deletions']})" for f in files[:20]]
                )
                if len(files) > 20:
                    files_summary += f"\n... and {len(files) - 20} more files"

                prompt = f"""Analyze this git commit:

**Commit Message:**
{message}

**Files Changed ({len(files)} files, +{stats.get('additions', 0)}/-{stats.get('deletions', 0)}):**
{files_summary}

Provide your analysis in the JSON format specified."""

                llm_response = await self._call_llm(prompt)
                llm_analysis = self._parse_llm_response(llm_response)

                if llm_analysis:
                    result["llm_analysis"] = {
                        "summary": llm_analysis.get("summary", ""),
                        "components": llm_analysis.get("components", []),
                        "risk_level": llm_analysis.get("risk_level", "unknown"),
                        "risk_reason": llm_analysis.get("risk_reason", ""),
                        "testing_recommendations": llm_analysis.get("testing_recommendations", []),
                        "key_changes": llm_analysis.get("key_changes", []),
                        "available": True,
                        "llm_backend": "ollama",
                        "llm_model": self._model,
                    }
                else:
                    result["llm_analysis"] = {
                        "available": False,
                        "error": f"LLM call failed - Ollama at {self._base_url} may be unreachable",
                    }

        return result

    async def is_available(self) -> Dict[str, Any]:
        """Check if Ollama Gateway is available for commit analysis."""
        status = {
            "available": False,
            "backend": "ollama",
            "base_url": self._base_url,
            "model": self._model,
            "configured": self._configured,
            "gateway_reachable": False,
        }

        if not self._configured:
            status["error"] = (
                "Ollama not configured. Set ADK_LLM_PROVIDER=ollama, "
                "ADK_OLLAMA_BASE_URL, and ADK_OLLAMA_API_TOKEN in .env"
            )
            return status

        try:
            headers = _get_auth_headers(self._api_token, self._auth_mode)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        status["gateway_reachable"] = True
                        status["available"] = True
                        status["auth_mode"] = self._auth_mode
                    else:
                        status["error"] = f"Gateway returned {resp.status}"
        except aiohttp.ClientConnectorError:
            status["error"] = f"Cannot connect to Ollama at {self._base_url}"
        except Exception as e:
            status["error"] = str(e)

        return status


# Singleton instance
_commit_analyzer: Optional[CommitAnalyzer] = None


def get_commit_analyzer() -> CommitAnalyzer:
    """Get singleton commit analyzer instance."""
    global _commit_analyzer
    if _commit_analyzer is None:
        _commit_analyzer = CommitAnalyzer()
    return _commit_analyzer

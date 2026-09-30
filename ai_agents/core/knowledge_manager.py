"""
Knowledge Manager
==================

Config-driven knowledge source management for all agents.
Add new documentation sources by editing knowledge_sources.yaml.

Usage:
    from core.knowledge_manager import get_knowledge_manager

    km = get_knowledge_manager()
    docs = await km.search("how to configure steering")

    # Or filter by agent
    docs = await km.search("error message", agent="tfa")
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Path to config file (ai_agents/knowledge_sources.yaml)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge_sources.yaml")


@dataclass
class DocumentResult:
    """A document retrieved from a knowledge source."""

    title: str
    content: str
    url: str
    source_name: str
    source_type: str
    relevance: float = 1.0


class KnowledgeManager:
    """
    Manages knowledge sources for TFA.

    Reads configuration from knowledge_sources.yaml and provides
    a unified interface to search across all configured sources.
    """

    def __init__(self, config_path: str = None):
        self.config_path = config_path or CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._sources: List[Dict[str, Any]] = []
        self._loaded = False

    def _load_config(self):
        """Load configuration from YAML file."""
        if self._loaded:
            return

        try:
            with open(self.config_path, "r") as f:
                self._config = yaml.safe_load(f) or {}

            # Expand environment variables in config
            self._config = self._expand_env_vars(self._config)

            # Load sources
            self._sources = [s for s in self._config.get("sources", []) if s.get("enabled", True)]
            self._sources.sort(key=lambda x: x.get("priority", 99))

            self._loaded = True
            logger.info("Loaded %d knowledge sources", len(self._sources))

        except FileNotFoundError:
            logger.warning("Knowledge config not found: %s", self.config_path)
            self._loaded = True
        except Exception as e:
            logger.error("Error loading knowledge config: %s", e)
            self._loaded = True

    def _expand_env_vars(self, obj: Any) -> Any:
        """Recursively expand ${VAR} references in config."""
        if isinstance(obj, str):

            def replace_var(match):
                var_name = match.group(1)
                return os.getenv(var_name, "")

            return re.sub(r"\$\{(\w+)\}", replace_var, obj)
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        return obj

    def get_sources(self, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all enabled knowledge sources, optionally filtered by agent.

        Args:
            agent: Filter sources for this agent (e.g., "tfa", "docs_agent")
                   If None, returns all sources.
        """
        self._load_config()

        if not agent:
            return self._sources

        # Filter sources by agent
        return [s for s in self._sources if not s.get("agents") or agent in s.get("agents", [])]

    async def search(
        self,
        query: str,
        max_results: int = 5,
        agent: Optional[str] = None,
    ) -> List[DocumentResult]:
        """
        Search all configured knowledge sources.

        Args:
            query: Search query
            max_results: Maximum results to return
            agent: Only search sources available to this agent

        Returns:
            List of DocumentResult objects
        """
        self._load_config()
        results: List[DocumentResult] = []

        sources = self.get_sources(agent=agent)

        for source in sources:
            if len(results) >= max_results:
                break

            try:
                source_results = await self._search_source(source, query, max_results - len(results))
                results.extend(source_results)
            except Exception as e:
                logger.debug("Error searching %s: %s", source.get("name"), e)

        return results[:max_results]

    async def _search_source(self, source: Dict[str, Any], query: str, limit: int) -> List[DocumentResult]:
        """Search a single knowledge source."""
        source_type = source.get("type", "")
        source_name = source.get("name", "Unknown")
        config = source.get("config", {})

        if source_type == "confluence":
            return await self._search_confluence(source_name, config, query, limit)
        elif source_type == "web":
            return await self._search_web(source_name, config, query, limit)
        elif source_type == "static":
            return self._search_static(source_name, config, query, limit)
        else:
            logger.warning("Unknown source type: %s", source_type)
            return []

    async def _search_confluence(
        self, source_name: str, config: Dict[str, Any], query: str, limit: int
    ) -> List[DocumentResult]:
        """Search Confluence wiki."""
        try:
            from core.confluence_client import ConfluenceClient

            client = ConfluenceClient(
                base_url=config.get("base_url"),
                space_key=config.get("space_key"),
            )

            if not client.is_configured():
                return []

            pages = await client.search(query, max_results=limit)

            return [
                DocumentResult(
                    title=page.title,
                    content=page.content[:500],
                    url=page.url,
                    source_name=source_name,
                    source_type="confluence",
                )
                for page in pages
            ]
        except ImportError:
            logger.debug("Confluence client not available")
            return []
        except Exception as e:
            logger.debug("Confluence search error: %s", e)
            return []

    async def _search_web(
        self, source_name: str, config: Dict[str, Any], query: str, limit: int
    ) -> List[DocumentResult]:
        """Search web docs (via FAISS index or web scraping)."""
        try:
            # Try FAISS index first (docs_agent)
            if config.get("use_faiss_index", True):
                try:
                    from docs_agent.tools.smart_retriever import get_smart_retriever

                    retriever = await get_smart_retriever()
                    result = await retriever.retrieve(query, top_k=limit)

                    if result.chunks:
                        return [
                            DocumentResult(
                                title=chunk.source_title,
                                content=chunk.content[:500],
                                url=chunk.source_url,
                                source_name=source_name,
                                source_type="web",
                            )
                            for chunk in result.chunks
                        ]
                except Exception as e:
                    logger.debug("FAISS search failed: %s", e)

            # Fallback: no web scraping for now (would need additional implementation)
            return []

        except Exception as e:
            logger.debug("Web search error: %s", e)
            return []

    def _search_static(self, source_name: str, config: Dict[str, Any], query: str, limit: int) -> List[DocumentResult]:
        """Search static knowledge entries."""
        results = []
        entries = config.get("entries", [])
        query_lower = query.lower()

        for entry in entries:
            # Simple keyword matching
            keywords = entry.get("keywords", [])
            if any(kw.lower() in query_lower for kw in keywords):
                results.append(
                    DocumentResult(
                        title=entry.get("title", ""),
                        content=entry.get("content", ""),
                        url=entry.get("url", ""),
                        source_name=source_name,
                        source_type="static",
                    )
                )

            if len(results) >= limit:
                break

        return results

    def reload(self):
        """Reload configuration from file."""
        self._loaded = False
        self._config = {}
        self._sources = []
        self._load_config()


# Singleton instance
_knowledge_manager: Optional[KnowledgeManager] = None


def get_knowledge_manager() -> KnowledgeManager:
    """Get or create KnowledgeManager singleton."""
    global _knowledge_manager
    if _knowledge_manager is None:
        _knowledge_manager = KnowledgeManager()
    return _knowledge_manager

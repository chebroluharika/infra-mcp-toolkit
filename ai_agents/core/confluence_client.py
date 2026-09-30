"""
Confluence Client for Product Knowledge
========================================

Fetches documentation from Confluence wiki for TFA product knowledge.
Uses Confluence REST API v2 with API token authentication.

Usage:
    from core.confluence_client import ConfluenceClient

    client = ConfluenceClient()
    pages = await client.get_child_pages(parent_page_id)
    content = await client.search("addonman troubleshooting")
"""

import base64
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ConfluencePage:
    """Represents a Confluence page."""

    id: str
    title: str
    content: str
    url: str
    space_key: str
    last_modified: str
    labels: List[str]


class ConfluenceClient:
    """
    Client for fetching documentation from Confluence.

    Uses the Confluence REST API with Basic Auth (email + API token).
    Caches results to reduce API calls.
    """

    def __init__(
        self,
        base_url: str = None,
        user_email: str = None,
        api_token: str = None,
        space_key: str = None,
    ):
        self.base_url = (base_url or os.getenv("CONFLUENCE_BASE_URL", "")).rstrip("/")
        self.user_email = user_email or os.getenv("CONFLUENCE_USER_EMAIL", "")
        self.api_token = api_token or os.getenv("CONFLUENCE_API_TOKEN", "")
        self.space_key = space_key or os.getenv("CONFLUENCE_SPACE_KEY", "SRE")

        # Cache for pages (reduces API calls)
        self._cache: Dict[str, ConfluencePage] = {}
        self._cache_time: Dict[str, datetime] = {}
        self._cache_ttl = timedelta(hours=1)  # Cache pages for 1 hour

        # Full-text search index (built from cached pages)
        self._search_index: Dict[str, List[str]] = {}  # keyword -> [page_ids]

    def is_configured(self) -> bool:
        """Check if Confluence is properly configured."""
        return bool(self.base_url and self.user_email and self.api_token)

    def _get_auth_header(self) -> Dict[str, str]:
        """Generate Basic Auth header."""
        credentials = f"{self.user_email}:{self.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _clean_html(self, html: str) -> str:
        """Convert HTML to plain text."""
        if not html:
            return ""

        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Replace common HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')

        # Replace block elements with newlines
        text = re.sub(r"<(p|div|br|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)

        # Remove all remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Clean up whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r" +", " ", text)

        return text.strip()

    async def get_page(self, page_id: str, expand_body: bool = True) -> Optional[ConfluencePage]:
        """
        Fetch a single Confluence page by ID.

        Args:
            page_id: The Confluence page ID
            expand_body: Whether to fetch the page body content

        Returns:
            ConfluencePage object or None if not found
        """
        # Check cache first
        cache_key = f"page:{page_id}"
        if cache_key in self._cache:
            if datetime.now() - self._cache_time.get(cache_key, datetime.min) < self._cache_ttl:
                return self._cache[cache_key]

        if not self.is_configured():
            logger.warning("Confluence not configured - skipping page fetch")
            return None

        try:
            # Use REST API v1 (more widely supported)
            expand = "body.storage,metadata.labels,version" if expand_body else "metadata.labels,version"
            url = f"{self.base_url}/rest/api/content/{page_id}?expand={expand}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_auth_header())

                if response.status_code == 404:
                    logger.warning("Confluence page %s not found", page_id)
                    return None

                if response.status_code == 401:
                    logger.error("Confluence authentication failed - check API token")
                    return None

                if response.status_code != 200:
                    logger.error("Confluence API error: %d - %s", response.status_code, response.text[:200])
                    return None

                data = response.json()

                # Extract content
                body_html = ""
                if expand_body and "body" in data:
                    body_html = data["body"].get("storage", {}).get("value", "")

                # Extract labels
                labels = []
                if "metadata" in data and "labels" in data["metadata"]:
                    labels = [label["name"] for label in data["metadata"]["labels"].get("results", [])]

                # Build page URL
                page_url = f"{self.base_url}/spaces/{self.space_key}/pages/{page_id}"

                page = ConfluencePage(
                    id=page_id,
                    title=data.get("title", ""),
                    content=self._clean_html(body_html),
                    url=page_url,
                    space_key=data.get("space", {}).get("key", self.space_key),
                    last_modified=data.get("version", {}).get("when", ""),
                    labels=labels,
                )

                # Cache the page
                self._cache[cache_key] = page
                self._cache_time[cache_key] = datetime.now()

                # Index for search
                self._index_page(page)

                return page

        except httpx.TimeoutException:
            logger.error("Confluence request timed out for page %s", page_id)
            return None
        except Exception as e:
            logger.error("Error fetching Confluence page %s: %s", page_id, e)
            return None

    async def get_child_pages(
        self,
        parent_page_id: str,
        recursive: bool = True,
        max_depth: int = 3,
        max_pages: int = 50,
    ) -> List[ConfluencePage]:
        """
        Fetch all child pages under a parent page.

        Args:
            parent_page_id: The parent page ID
            recursive: Whether to fetch grandchildren recursively
            max_depth: Maximum recursion depth
            max_pages: Maximum total pages to fetch

        Returns:
            List of ConfluencePage objects
        """
        if not self.is_configured():
            logger.warning("Confluence not configured - skipping child pages fetch")
            return []

        pages = []
        await self._fetch_children_recursive(parent_page_id, pages, recursive, max_depth, max_pages, current_depth=0)

        logger.info("Fetched %d pages from Confluence (parent: %s)", len(pages), parent_page_id)
        return pages

    async def _fetch_children_recursive(
        self,
        page_id: str,
        pages: List[ConfluencePage],
        recursive: bool,
        max_depth: int,
        max_pages: int,
        current_depth: int,
    ):
        """Recursively fetch child pages."""
        if current_depth >= max_depth or len(pages) >= max_pages:
            return

        try:
            url = f"{self.base_url}/rest/api/content/{page_id}/child/page?limit=50&expand=metadata.labels"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_auth_header())

                if response.status_code != 200:
                    logger.warning("Failed to fetch children for page %s: %d", page_id, response.status_code)
                    return

                data = response.json()
                children = data.get("results", [])

                for child in children:
                    if len(pages) >= max_pages:
                        break

                    child_id = child.get("id")
                    if child_id:
                        # Fetch full page content
                        page = await self.get_page(child_id, expand_body=True)
                        if page:
                            pages.append(page)

                        # Recurse into children
                        if recursive:
                            await self._fetch_children_recursive(
                                child_id, pages, recursive, max_depth, max_pages, current_depth + 1
                            )

        except Exception as e:
            logger.error("Error fetching children for page %s: %s", page_id, e)

    def _index_page(self, page: ConfluencePage):
        """Add page to search index."""
        # Extract keywords from title and content
        text = f"{page.title} {page.content}".lower()
        words = re.findall(r"\b\w{3,}\b", text)

        for word in set(words):
            if word not in self._search_index:
                self._search_index[word] = []
            if page.id not in self._search_index[word]:
                self._search_index[word].append(page.id)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        use_api: bool = True,
    ) -> List[ConfluencePage]:
        """
        Search for pages matching a query.

        Args:
            query: Search query
            max_results: Maximum results to return
            use_api: Whether to use Confluence CQL search API

        Returns:
            List of matching ConfluencePage objects
        """
        if not self.is_configured():
            return []

        if use_api:
            return await self._search_api(query, max_results)
        else:
            return self._search_local(query, max_results)

    async def _search_api(self, query: str, max_results: int) -> List[ConfluencePage]:
        """Search using Confluence CQL API."""
        try:
            # Build CQL query
            cql = f'space="{self.space_key}" AND (title~"{query}" OR text~"{query}")'
            url = f"{self.base_url}/rest/api/content/search?cql={cql}&limit={max_results}&expand=body.storage,metadata.labels"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_auth_header())

                if response.status_code != 200:
                    logger.warning("Confluence search failed: %d", response.status_code)
                    return self._search_local(query, max_results)

                data = response.json()
                pages = []

                for result in data.get("results", [])[:max_results]:
                    page_id = result.get("id")
                    body_html = result.get("body", {}).get("storage", {}).get("value", "")
                    labels = [
                        label["name"] for label in result.get("metadata", {}).get("labels", {}).get("results", [])
                    ]

                    page = ConfluencePage(
                        id=page_id,
                        title=result.get("title", ""),
                        content=self._clean_html(body_html),
                        url=f"{self.base_url}/spaces/{self.space_key}/pages/{page_id}",
                        space_key=self.space_key,
                        last_modified=result.get("version", {}).get("when", ""),
                        labels=labels,
                    )
                    pages.append(page)

                    # Cache the page
                    self._cache[f"page:{page_id}"] = page
                    self._cache_time[f"page:{page_id}"] = datetime.now()

                return pages

        except Exception as e:
            logger.error("Confluence search error: %s", e)
            return self._search_local(query, max_results)

    def _search_local(self, query: str, max_results: int) -> List[ConfluencePage]:
        """Search using local index (fallback)."""
        if not self._cache:
            return []

        # Score pages by keyword matches
        query_words = set(re.findall(r"\b\w{3,}\b", query.lower()))
        page_scores: Dict[str, int] = {}

        for word in query_words:
            if word in self._search_index:
                for page_id in self._search_index[word]:
                    page_scores[page_id] = page_scores.get(page_id, 0) + 1

        # Sort by score and return top results
        sorted_pages = sorted(page_scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for page_id, _ in sorted_pages[:max_results]:
            cache_key = f"page:{page_id}"
            if cache_key in self._cache:
                results.append(self._cache[cache_key])

        return results

    def clear_cache(self):
        """Clear the page cache."""
        self._cache.clear()
        self._cache_time.clear()
        self._search_index.clear()
        logger.info("Confluence cache cleared")


# Singleton instance
_confluence_client: Optional[ConfluenceClient] = None


def get_confluence_client() -> ConfluenceClient:
    """Get or create Confluence client singleton."""
    global _confluence_client
    if _confluence_client is None:
        _confluence_client = ConfluenceClient()
    return _confluence_client


async def get_product_docs(
    component: str,
    error_context: str = "",
    max_results: int = 3,
) -> List[Dict[str, Any]]:
    """
    Get relevant product documentation for a component.

    Args:
        component: Product component name (e.g., "addonman", "steering")
        error_context: Error message or context for better search
        max_results: Maximum docs to return

    Returns:
        List of doc snippets with title, content, and url
    """
    client = get_confluence_client()

    if not client.is_configured():
        logger.debug("Confluence not configured - returning empty docs")
        return []

    # Build search query
    query = f"{component} troubleshooting"
    if error_context:
        # Extract key error terms
        error_keywords = re.findall(
            r"\b(error|fail|timeout|connection|refused|denied|exception)\b", error_context.lower()
        )
        if error_keywords:
            query = f"{component} {' '.join(error_keywords[:2])}"

    try:
        pages = await client.search(query, max_results=max_results)

        return [
            {
                "title": page.title,
                "content": page.content[:500],  # Limit content size
                "url": page.url,
                "labels": page.labels,
            }
            for page in pages
        ]
    except Exception as e:
        logger.error("Error fetching product docs: %s", e)
        return []

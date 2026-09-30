"""
Documentation Scraper
=====================

Scrapes YourCompany documentation from https://docs.your-company.com/en/your-company-client

Crawls the documentation site, extracts content, and saves for processing.



Usage:
    from .scraper import DocumentationScraper

    scraper = DocumentationScraper()
    await scraper.scrape_all()
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Try to use Playwright for JS-rendered pages
try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

logger = logging.getLogger(__name__)

# Documentation source
DOCS_BASE_URL = "https://docs.your-company.com/en/your-company-client"

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DOCS_RAW_DIR = os.path.join(DATA_DIR, "docs_raw")
DOCS_INDEX_FILE = os.path.join(DATA_DIR, "docs_index.json")


@dataclass
class ScrapedPage:
    """Represents a scraped documentation page."""

    url: str
    title: str
    content: str
    headings: List[str]
    links: List[str]
    scraped_at: str
    content_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DocumentationScraper:
    """
    Scraper for YourCompany documentation.

    Features:
    - Crawls documentation pages starting from base URL
    - Extracts main content, removes navigation/footer
    - Handles relative links
    - Caches scraped pages
    - Respects rate limiting
    """

    def __init__(
        self,
        base_url: str = DOCS_BASE_URL,
        output_dir: str = DOCS_RAW_DIR,
        max_pages: int = 100,
        rate_limit_delay: float = 1.0,
    ):
        self.base_url = base_url
        self.output_dir = output_dir
        self.max_pages = max_pages
        self.rate_limit_delay = rate_limit_delay

        # Track visited URLs
        self.visited_urls: Set[str] = set()
        self.scraped_pages: List[ScrapedPage] = []

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        # Remove fragment and trailing slash
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return normalized

    def _is_valid_doc_url(self, url: str) -> bool:
        """Check if URL is a valid documentation page to scrape."""
        parsed = urlparse(url)

        # Must be same domain
        if "your-company.com" not in parsed.netloc:
            return False

        # Must be under docs path
        if "/en/your-company-client" not in parsed.path and "/en/docs" not in parsed.path:
            # Allow your-company-client subpages
            if not parsed.path.startswith("/en/"):
                return False

        # Skip non-HTML resources
        skip_extensions = [".pdf", ".png", ".jpg", ".gif", ".css", ".js", ".zip"]
        if any(parsed.path.endswith(ext) for ext in skip_extensions):
            return False

        return True

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract main content from page, removing navigation/footer."""
        # Try to find main content area
        main_content = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"content|main|article", re.I))
            or soup.find("div", id=re.compile(r"content|main|article", re.I))
        )

        if not main_content:
            main_content = soup.body if soup.body else soup

        # Remove navigation, sidebar, footer elements
        for element in main_content.find_all(["nav", "footer", "aside", "header"]):
            element.decompose()

        # Remove script and style tags
        for element in main_content.find_all(["script", "style", "noscript"]):
            element.decompose()

        # Remove elements with common nav/menu classes
        for class_pattern in ["nav", "menu", "sidebar", "footer", "header", "breadcrumb"]:
            for element in main_content.find_all(class_=re.compile(class_pattern, re.I)):
                element.decompose()

        # Convert tables to readable text BEFORE extracting
        for table in main_content.find_all("table"):
            table_text = self._table_to_text(table)
            table.replace_with(soup.new_string(table_text))

        # Get text content
        text = main_content.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)

        return text.strip()

    def _table_to_text(self, table) -> str:
        """Convert HTML table to readable text format preserving structure."""
        rows = []

        # Extract headers
        headers = []
        header_row = table.find("thead")
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                headers.append(th.get_text(strip=True))

        # If no thead, check first tr for headers
        if not headers:
            first_row = table.find("tr")
            if first_row:
                ths = first_row.find_all("th")
                if ths:
                    headers = [th.get_text(strip=True) for th in ths]

        # Extract body rows with proper cell content extraction
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if cells:
                row_data = []
                for cell in cells:
                    # Get text with spaces between inline elements
                    cell_text = cell.get_text(separator=" ", strip=True)
                    # Clean up multiple spaces
                    cell_text = re.sub(r"\s+", " ", cell_text)
                    row_data.append(cell_text)
                # Skip if this is the header row we already captured
                if row_data == headers:
                    continue
                rows.append(row_data)

        # Format as readable text - simple list format for clarity
        output_lines = ["\n"]

        for row in rows:
            if headers and len(row) >= 2:
                # For OS table: Category is first, Versions is second
                category = row[0] if row[0] else ""
                versions = row[1] if len(row) > 1 and row[1] else ""

                if category and versions:
                    # Clean up category name
                    category = category.strip()
                    # Clean up versions - add commas if missing
                    versions = re.sub(r"(\d)\s+([A-Z])", r"\1, \2", versions)
                    versions = re.sub(r"(LTS)\s+([a-z])", r"\1, \2", versions)
                    output_lines.append(f"- **{category}**: {versions}")
            elif any(row):
                output_lines.append("- " + " | ".join([r for r in row if r]))

        output_lines.append("")
        return "\n".join(output_lines)

    def _extract_headings(self, soup: BeautifulSoup) -> List[str]:
        """Extract all headings from page."""
        headings = []
        for tag in ["h1", "h2", "h3", "h4"]:
            for heading in soup.find_all(tag):
                text = heading.get_text(strip=True)
                if text:
                    headings.append(text)
        return headings

    def _extract_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """Extract all valid documentation links from page."""
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Handle relative URLs
            full_url = urljoin(current_url, href)
            normalized = self._normalize_url(full_url)

            if self._is_valid_doc_url(normalized):
                links.append(normalized)

        return list(set(links))  # Deduplicate

    def _content_hash(self, content: str) -> str:
        """Generate hash of content for change detection."""
        return hashlib.md5(content.encode()).hexdigest()

    async def scrape_page(self, url: str, browser=None) -> Optional[ScrapedPage]:
        """Scrape a single documentation page using Playwright for JS rendering."""
        normalized_url = self._normalize_url(url)

        if normalized_url in self.visited_urls:
            return None

        self.visited_urls.add(normalized_url)

        try:
            if browser:
                # Use Playwright for JS-rendered content
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    # Wait for content to load
                    await page.wait_for_timeout(2000)
                    html = await page.content()
                finally:
                    await page.close()
            elif HAS_HTTPX:
                # Fallback to httpx for static pages
                async with httpx.AsyncClient(timeout=30, follow_redirects=True, verify=False) as client:
                    response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DocsBot/1.0)"})
                    if response.status_code != 200:
                        logger.warning("Failed to fetch %s: %s", url, response.status_code)
                        return None
                    html = response.text
            else:
                logger.error("No HTTP client available")
                return None

        except Exception as e:
            logger.error("Error fetching %s: %s", url, e)
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # Extract content
        content = self._extract_content(soup)

        if len(content) < 100:
            logger.debug("Skipping %s - insufficient content", url)
            return None

        # Extract metadata
        headings = self._extract_headings(soup)
        links = self._extract_links(soup, url)

        page = ScrapedPage(
            url=normalized_url,
            title=title,
            content=content,
            headings=headings,
            links=links,
            scraped_at=datetime.now().isoformat(),
            content_hash=self._content_hash(content),
        )

        logger.info("Scraped: %s (%d chars)", title, len(content))
        return page

    async def scrape_all(self) -> List[ScrapedPage]:
        """Scrape all documentation pages starting from base URL."""
        logger.info("Starting documentation scrape from %s", self.base_url)

        browser = None
        playwright_instance = None

        try:
            # Initialize Playwright if available
            if HAS_PLAYWRIGHT:
                playwright_instance = await async_playwright().start()
                browser = await playwright_instance.chromium.launch(headless=True)
                logger.info("Using Playwright for JavaScript rendering")
            else:
                logger.warning("Playwright not available, using httpx (may not work for JS sites)")

            # Queue of URLs to process
            queue = [self.base_url]

            while queue and len(self.scraped_pages) < self.max_pages:
                url = queue.pop(0)

                # Scrape page
                page = await self.scrape_page(url, browser)

                if page:
                    self.scraped_pages.append(page)
                    logger.info("Scraped: %s (%d chars)", page.title[:50], len(page.content))

                    # Add new links to queue
                    for link in page.links:
                        if link not in self.visited_urls and link not in queue:
                            queue.append(link)

                    # Save page
                    self._save_page(page)

                # Rate limiting
                await asyncio.sleep(self.rate_limit_delay)

        finally:
            # Cleanup
            if browser:
                await browser.close()
            if playwright_instance:
                await playwright_instance.stop()

        # Save index
        self._save_index()

        logger.info("Scraping complete: %s pages", len(self.scraped_pages))
        return self.scraped_pages

    def _save_page(self, page: ScrapedPage):
        """Save scraped page to disk."""
        # Create filename from URL hash
        url_hash = hashlib.md5(page.url.encode()).hexdigest()[:12]
        filename = f"{url_hash}.json"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(page.to_dict(), f, indent=2, ensure_ascii=False)

    def _save_index(self):
        """Save index of all scraped pages."""
        index = {
            "base_url": self.base_url,
            "scraped_at": datetime.now().isoformat(),
            "total_pages": len(self.scraped_pages),
            "pages": [
                {
                    "url": p.url,
                    "title": p.title,
                    "content_hash": p.content_hash,
                    "headings_count": len(p.headings),
                }
                for p in self.scraped_pages
            ],
        }

        os.makedirs(os.path.dirname(DOCS_INDEX_FILE), exist_ok=True)
        with open(DOCS_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

        logger.info("Saved index to %s", DOCS_INDEX_FILE)

    def load_scraped_pages(self) -> List[ScrapedPage]:
        """Load previously scraped pages from disk."""
        pages = []

        if not os.path.exists(self.output_dir):
            return pages

        for filename in os.listdir(self.output_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.output_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        pages.append(ScrapedPage(**data))
                except Exception as e:
                    logger.error("Error loading %s: %s", filepath, e)

        logger.info("Loaded %s pages from disk", len(pages))
        return pages


# CLI for running scraper
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Scrape YourCompany documentation")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum pages to scrape")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests")
    args = parser.parse_args()

    scraper = DocumentationScraper(
        max_pages=args.max_pages,
        rate_limit_delay=args.delay,
    )

    asyncio.run(scraper.scrape_all())

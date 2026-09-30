"""
Query Preprocessor
==================

Normalizes and enhances user queries before routing to agents.

Features:
- Expands abbreviations (IRR, RRS, TFA, etc.)
- Extracts and normalizes entities (release versions, bug IDs)
- Standardizes date phrases
- Lightweight regex-based (no LLM call, instant processing)

Usage:
    processor = QueryProcessor()
    normalized = processor.process("whats IRR status for R134?")
    # Returns: "what is Internal Release Readiness status for release 134.0?"
"""

import logging
import re

logger = logging.getLogger(__name__)


class QueryProcessor:
    """
    Preprocesses user queries to normalize terminology and extract entities.

    This helps LLM-based routing and tool selection by providing clearer,
    more consistent input.
    """

    def __init__(self):
        """Initialize query processor with lookup tables."""

        # Common abbreviations in release engineering domain
        self.abbreviations = {
            "irr": "Internal Release Readiness",
            "rrs": "Release Readiness Score",
            "tfa": "Test Failure Analysis",
            "ehf": "Emergency Hot Fix",
            "imf": "Incremental Maintenance Fix",
            "ci/cd": "CI/CD pipeline",
            "cicd": "CI/CD pipeline",
            "p0": "priority 0",
            "p1": "priority 1",
            "p2": "priority 2",
            "qa": "quality assurance",
            "qe": "quality engineering",
        }

        # Query pattern normalizations
        self.normalizations = [
            # Date-related
            (r"\bwhen'?s\b", "when is"),
            (r"\bwhat'?s\b", "what is"),
            (r"\bhow'?s\b", "how is"),
            (r"\bthere'?s\b", "there is"),
            # Action verbs
            (r"\bgimme\b", "give me"),
            (r"\bgonna\b", "going to"),
            (r"\bwanna\b", "want to"),
            # Common typos
            (r"\bstatus\b", "status"),
            (r"\bpipline\b", "pipeline"),
            (r"\bjenkin\b", "jenkins"),
        ]

        # Release version patterns
        self.release_patterns = [
            # R134 -> release 134.0
            (r"\br(\d{3})\b", r"release \1.0"),
            # R134.5 -> release 134.5
            (r"\br(\d{3}\.\d+)\b", r"release \1"),
        ]

        # Bug/Issue ID patterns
        self.issue_patterns = [
            # ENG-12345 or YOUR_PRODUCT-123
            (r"\b([A-Z]+)-(\d+)\b", r"\1-\2 issue"),
        ]

    def process(self, query: str, expand_abbreviations: bool = True) -> str:
        """
        Process and normalize a user query.

        Args:
            query: Raw user query
            expand_abbreviations: Whether to expand common abbreviations

        Returns:
            Normalized query string
        """
        if not query or not query.strip():
            return query

        original_query = query
        normalized = query.lower().strip()

        # Step 1: Expand abbreviations
        if expand_abbreviations:
            normalized = self._expand_abbreviations(normalized)

        # Step 2: Apply normalizations
        normalized = self._apply_normalizations(normalized)

        # Step 3: Extract and normalize entities
        normalized = self._normalize_entities(normalized)

        # Step 4: Clean up whitespace
        normalized = " ".join(normalized.split())

        if normalized != original_query.lower():
            logger.debug("Query normalized: '%s' -> '%s'", original_query, normalized)

        return normalized

    def _expand_abbreviations(self, text: str) -> str:
        """Expand known abbreviations."""
        result = text
        for abbrev, expansion in self.abbreviations.items():
            # Match whole word only, case-insensitive
            pattern = r"\b" + re.escape(abbrev) + r"\b"
            result = re.sub(pattern, expansion, result, flags=re.IGNORECASE)
        return result

    def _apply_normalizations(self, text: str) -> str:
        """Apply normalization patterns."""
        result = text
        for pattern, replacement in self.normalizations:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _normalize_entities(self, text: str) -> str:
        """Extract and normalize entities (releases, issues)."""
        result = text

        # Normalize release versions
        for pattern, replacement in self.release_patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Normalize issue IDs
        for pattern, replacement in self.issue_patterns:
            result = re.sub(pattern, replacement, result)

        return result

    def extract_release(self, query: str) -> str:
        """
        Extract release version from query.

        Args:
            query: User query

        Returns:
            Release version (e.g., "134.0") or None
        """
        # Look for R134, R134.5, 134.0, etc.
        patterns = [
            r"\br(\d{3})(?:\.\d+)?\b",  # R134 or R134.5
            r"\b(\d{3}\.\d+)\b",  # 134.0
            r"\brelease\s+(\d{3}(?:\.\d+)?)\b",  # release 134
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                version = match.group(1)
                # Ensure format is XXX.X
                if "." not in version:
                    version = f"{version}.0"
                return version

        return None

    def extract_build_number(self, query: str) -> str:
        """
        Extract build number from query.

        Args:
            query: User query

        Returns:
            Build number or None
        """
        # Look for "build 123", "build #123", "#123"
        patterns = [
            r"\bbuild\s*#?(\d+)\b",
            r"#(\d+)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def extract_assignee(self, query: str) -> str:
        """
        Extract assignee name from query.

        Args:
            query: User query

        Returns:
            Assignee name or None
        """
        # Look for "assigned to X", "by X", "for X"
        patterns = [
            r"assigned\s+to\s+(\w+)",
            r"\bby\s+(\w+)\b",
            r"\bfor\s+(\w+)\b",
            r"owner\s+(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)

        return None


# Singleton instance
_processor = None


def get_processor() -> QueryProcessor:
    """Get query processor singleton."""
    global _processor  # pylint: disable=global-statement
    if _processor is None:
        _processor = QueryProcessor()
    return _processor

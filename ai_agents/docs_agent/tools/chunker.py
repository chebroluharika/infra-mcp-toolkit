"""
Text Chunker
============

Splits documentation content into chunks suitable for embedding and retrieval.

Strategies:
- Semantic chunking (split by headings/sections)
- Fixed-size chunking with overlap
- Sentence-based chunking


"""

import hashlib
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A chunk of documentation content."""

    chunk_id: str
    source_url: str
    source_title: str
    content: str
    heading: Optional[str]
    chunk_index: int
    total_chunks: int
    char_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TextChunker:
    """
    Splits documentation into chunks for embedding.

    Uses a hybrid approach:
    1. First split by major headings (H1, H2)
    2. Then split large sections by size
    3. Maintain overlap for context
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def _generate_chunk_id(self, url: str, index: int) -> str:
        """Generate unique chunk ID."""
        content = f"{url}:{index}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _split_by_headings(self, text: str) -> List[Dict[str, str]]:
        """Split text into sections by headings."""
        sections = []
        current_heading = None
        current_content = []

        lines = text.split("\n")

        for line in lines:
            line = line.strip()

            # Check if line looks like a MAJOR heading (not just any capitalized line)
            # Must be: short, no period, starts with capital, contains multiple words
            # AND accumulated content is substantial
            is_heading = (
                len(line) < 80
                and len(line) > 10  # Must be longer than just "macOS" or "iOS"
                and not line.endswith(".")
                and not line.endswith(",")
                and (line[0].isupper() or line.startswith("#"))
                and len(line.split()) >= 3  # At least 3 words to be a real heading
                and len("\n".join(current_content)) > 300  # Only split if we have enough content
            )

            if is_heading and len(current_content) > 0:
                # Save previous section
                content = "\n".join(current_content).strip()
                if len(content) >= self.min_chunk_size:
                    sections.append(
                        {
                            "heading": current_heading,
                            "content": content,
                        }
                    )
                current_heading = line.lstrip("#").strip()
                current_content = []
            else:
                current_content.append(line)

        # Don't forget last section
        if current_content:
            content = "\n".join(current_content).strip()
            if len(content) >= self.min_chunk_size:
                sections.append(
                    {
                        "heading": current_heading,
                        "content": content,
                    }
                )

        return sections

    def _split_by_size(self, text: str, heading: Optional[str] = None) -> List[Dict[str, str]]:
        """Split text into fixed-size chunks with overlap."""
        chunks = []

        if len(text) <= self.chunk_size:
            return [{"heading": heading, "content": text}]

        # Split by sentences first
        sentences = re.split(r"(?<=[.!?])\s+", text)

        current_chunk = []
        current_size = 0

        for sentence in sentences:
            sentence_size = len(sentence)

            if current_size + sentence_size > self.chunk_size and current_chunk:
                # Save current chunk
                chunks.append(
                    {
                        "heading": heading,
                        "content": " ".join(current_chunk),
                    }
                )

                # Start new chunk with overlap
                overlap_start = max(0, len(current_chunk) - 2)
                current_chunk = current_chunk[overlap_start:]
                current_size = sum(len(s) for s in current_chunk)

            current_chunk.append(sentence)
            current_size += sentence_size

        # Don't forget last chunk
        if current_chunk:
            content = " ".join(current_chunk)
            if len(content) >= self.min_chunk_size:
                chunks.append(
                    {
                        "heading": heading,
                        "content": content,
                    }
                )

        return chunks

    def chunk_document(
        self,
        content: str,
        source_url: str,
        source_title: str,
    ) -> List[DocumentChunk]:
        """
        Chunk a document into retrievable pieces.

        Args:
            content: Full document content
            source_url: URL of the document
            source_title: Title of the document

        Returns:
            List of DocumentChunk objects
        """
        chunks = []

        # First split by headings
        sections = self._split_by_headings(content)

        if not sections:
            # No headings found, split by size directly
            sections = [{"heading": None, "content": content}]

        # Then split large sections by size
        all_chunks = []
        for section in sections:
            if len(section["content"]) > self.chunk_size:
                sub_chunks = self._split_by_size(section["content"], section["heading"])
                all_chunks.extend(sub_chunks)
            else:
                all_chunks.append(section)

        # Create DocumentChunk objects
        total_chunks = len(all_chunks)

        for i, chunk_data in enumerate(all_chunks):
            chunk = DocumentChunk(
                chunk_id=self._generate_chunk_id(source_url, i),
                source_url=source_url,
                source_title=source_title,
                content=chunk_data["content"],
                heading=chunk_data["heading"],
                chunk_index=i,
                total_chunks=total_chunks,
                char_count=len(chunk_data["content"]),
            )
            chunks.append(chunk)

        logger.debug("Created %d chunks from %s", len(chunks), source_title)
        return chunks

    def chunk_documents(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        """
        Chunk multiple documents.

        Args:
            documents: List of dicts with 'url', 'title', 'content' keys

        Returns:
            List of all DocumentChunk objects
        """
        all_chunks = []

        for doc in documents:
            chunks = self.chunk_document(
                content=doc.get("content", ""),
                source_url=doc.get("url", ""),
                source_title=doc.get("title", ""),
            )
            all_chunks.extend(chunks)

        logger.info("Created %d total chunks from %d documents", len(all_chunks), len(documents))
        return all_chunks


# Convenience function
def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> List[str]:
    """Simple function to chunk text into pieces."""
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=overlap)
    sections = chunker._split_by_size(text)
    return [s["content"] for s in sections]

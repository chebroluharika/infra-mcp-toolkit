"""
Documentation Agent (ADK)
=========================

ADK LlmAgent for handling documentation queries.
Uses RAG (Retrieval Augmented Generation) with FAISS vector store.
Tools are registered with ADK - it discovers capabilities from docstrings automatically.

Data Source: https://docs.your-company.com/en/your-company-client

Architecture:
    User Query → DocsAgent → search_documentation tool → FAISS → LLM → Response
"""

import logging
from typing import Any, Dict, List, Optional

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

# Check ADK availability
if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# =============================================================================
# Documentation Tools (RAG-based)
# =============================================================================


async def search_documentation(query: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Search documentation using all configured knowledge sources.

    Searches both public docs (FAISS index) and internal docs (Confluence).
    Configure sources in ai_agents/knowledge_sources.yaml.

    Use when asked: "how to configure...", "documentation for...", "what is...",
    "how to install...", "installation steps...", "setup guide..."

    Args:
        query: Search query (e.g., "How to install YourCompany Client", "configure proxy settings")
        top_k: Number of results to return (default: 5)

    Returns:
        Dict with relevant documentation chunks and sources, or helpful fallback info
    """
    context_parts = []
    sources = []
    seen_urls = set()
    retrieval_method = "unknown"

    # 1. Search public docs via SmartRetriever (FAISS)
    try:
        from .tools.smart_retriever import get_smart_retriever

        retriever = await get_smart_retriever()
        retrieval_result = await retriever.retrieve(query, top_k=top_k)
        retrieval_method = retrieval_result.retrieval_method

        logger.info(f"FAISS retrieval: {retrieval_result.retrieval_method}, chunks: {len(retrieval_result.chunks)}")

        for chunk in retrieval_result.chunks:
            title = chunk.source_title.replace(" - YourCompany Knowledge Portal", "").strip()

            if title:
                context_parts.append(f"**{title}**\n\n{chunk.content}")
            else:
                context_parts.append(chunk.content)

            if chunk.source_url and chunk.source_url not in seen_urls:
                seen_urls.add(chunk.source_url)
                sources.append({"url": chunk.source_url, "title": title, "source": "YourCompany Docs"})

    except Exception as e:
        logger.debug("FAISS search error: %s", e)

    # 2. Search additional sources via KnowledgeManager (Confluence, etc.)
    try:
        from core.knowledge_manager import get_knowledge_manager

        km = get_knowledge_manager()
        km_results = await km.search(query, max_results=top_k, agent="docs_agent")

        for doc in km_results:
            if doc.url not in seen_urls:
                seen_urls.add(doc.url)
                context_parts.append(f"**{doc.title}**\n\n{doc.content}")
                sources.append({"url": doc.url, "title": doc.title, "source": doc.source_name})

        if km_results:
            retrieval_method = f"{retrieval_method}+knowledge_manager"
            logger.info(f"KnowledgeManager: found {len(km_results)} additional docs")

    except Exception as e:
        logger.debug("KnowledgeManager search error: %s", e)

    # Build response
    if not context_parts:
        return {
            "success": False,
            "error": "No chunks retrieved",
            "display": "## ❌ No Results Found\n\nNo documentation was found for this query. Please try a different search term.",
        }

    context = "\n\n---\n\n".join(context_parts)

    result = {
        "context": context,
        "sources": sources,
        "chunks_used": len(context_parts),
        "retrieval_method": retrieval_method,
        "confidence": 0.8 if len(context_parts) > 2 else 0.5,
    }

    return {
        "success": True,
        "chunks_found": result.get("chunks_used", 0),
        "context": result.get("context", ""),
        "sources": result.get("sources", []),
        "source": "Documentation",
        "display": _format_documentation_response(query, result),
    }


def _format_documentation_response(query: str, result: Dict[str, Any]) -> str:
    """
    Format documentation search results for display.

    Extracts key information and presents it in a clean, scannable format.
    """
    context = result.get("context", "")
    sources = result.get("sources", [])
    query_lower = query.lower()

    # Build response
    output_lines = ["## 📚 YourCompany Documentation", ""]

    if not context:
        output_lines.append("No detailed information found for this query.")
        output_lines.append("")
        return "\n".join(output_lines)

    # Split context by section dividers
    sections = context.split("\n\n---\n\n")

    # Process and format sections
    formatted_sections = []
    seen_titles = set()

    for section in sections:
        if len(section.strip()) < 50:
            continue

        # Clean the section
        section = _clean_section_text(section)

        # Extract title and content
        title, content = _extract_title_and_content(section)

        # Skip duplicate titles
        title_key = title.lower() if title else ""
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)

        # Skip if content is too short
        if len(content) < 30:
            continue

        # Format the content based on query type
        formatted_content = _format_content_for_query(content, query_lower)

        # Build section output
        if title:
            formatted_sections.append(f"### {title}\n\n{formatted_content}")
        else:
            formatted_sections.append(formatted_content)

        # Limit to 3 sections max
        if len(formatted_sections) >= 3:
            break

    if formatted_sections:
        final_content = "\n\n".join(formatted_sections)

        # Trim if too long
        if len(final_content) > 2500:
            break_point = final_content.rfind(". ", 0, 2500)
            if break_point > 2000:
                final_content = final_content[: break_point + 1]
            else:
                final_content = final_content[:2500] + "..."

        output_lines.append(final_content)
    else:
        output_lines.append("No relevant information found for this query.")

    output_lines.append("")

    # Add sources
    if sources:
        unique_sources = _get_unique_sources(sources)
        if unique_sources:
            output_lines.append("---")
            output_lines.append("**📖 Learn More:**")
            for src in unique_sources[:3]:
                title = src.get("title", "").replace(" - YourCompany Knowledge Portal", "").strip()
                url = src["url"]
                if title:
                    output_lines.append(f"- [{title}]({url})")
                else:
                    url_title = url.split("/")[-1].replace("-", " ").title()
                    output_lines.append(f"- [{url_title}]({url})")

    return "\n".join(output_lines)


def _clean_section_text(text: str) -> str:
    """Clean up raw section text."""
    import re

    # Remove wiki-style brackets
    text = re.sub(r"\[\[.*?\]\]", "", text)

    # Reduce excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Clean up stray commas at line starts
    text = re.sub(r"^\s*,\s*", "", text, flags=re.MULTILINE)

    # Replace checkmarks with text
    text = text.replace("✓", "Yes")
    text = text.replace("×", "No")

    return text.strip()


def _extract_title_and_content(section: str) -> tuple:
    """Extract title and content from a section."""
    lines = section.split("\n")
    title = None
    content_start = 0

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # Check for **Title** pattern
        if line.startswith("**") and line.endswith("**"):
            title = line.strip("*").strip()
            content_start = i + 1
            break

        # Check for title-like line (short, doesn't end with punctuation)
        is_title = (
            len(line) < 80
            and len(line) > 10
            and not line.endswith((".", ",", ":"))
            and not line.startswith(("The ", "This ", "A ", "An ", "- ", "|", "*"))
        )

        if is_title:
            title = line
            content_start = i + 1
            break
        else:
            # First line is content, not title
            break

    content = "\n".join(lines[content_start:]).strip()

    # Remove duplicate title at content start
    if title and content.lower().startswith(title.lower()):
        content = content[len(title) :].strip()

    return title, content


def _format_content_for_query(content: str, query_lower: str) -> str:
    """Format content based on the type of query."""
    import re

    lines = content.split("\n")
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            formatted_lines.append("")
            continue

        # Format bullet points consistently
        if line.startswith("- "):
            # Clean up pipe-separated values in bullets
            if " | " in line:
                parts = line[2:].split(" | ")
                if len(parts) >= 2:
                    key = parts[0].strip()
                    value = " | ".join(parts[1:]).strip()
                    line = f"- **{key}**: {value}"
            formatted_lines.append(line)

        # Format key-value pairs (e.g., "Windows and macOS: 0 - 5 %")
        elif ":" in line and not line.startswith(("http", "https")):
            # Check if it's a simple key: value pair
            parts = line.split(":", 1)
            if len(parts) == 2 and len(parts[0]) < 50:
                key = parts[0].strip()
                value = parts[1].strip()
                # Skip if key is too long or value is empty
                if key and value and not key.startswith("-"):
                    formatted_lines.append(f"- **{key}**: {value}")
                else:
                    formatted_lines.append(line)
            else:
                formatted_lines.append(line)
        else:
            formatted_lines.append(line)

    result = "\n".join(formatted_lines)

    # Clean up multiple empty lines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def _get_unique_sources(sources: List) -> List[Dict]:
    """Get unique sources from the list."""
    seen_urls = set()
    unique = []

    for src in sources:
        url = src.get("url", src) if isinstance(src, dict) else src
        title = src.get("title", "") if isinstance(src, dict) else ""

        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append({"url": url, "title": title})

    return unique


async def get_documentation_status() -> Dict[str, Any]:
    """
    Check if documentation index is ready and get statistics.

    Use when asked: "is documentation ready?", "documentation status"

    Returns:
        Dict with index statistics
    """
    try:
        from .tools.rag_pipeline import RAGPipeline
        from .tools.vector_store import FAISSVectorStore

        _ = RAGPipeline()  # Pipeline for future use
        store = FAISSVectorStore()

        if store.load():
            return {
                "success": True,
                "status": "ready",
                "stats": store.get_stats(),
            }
        else:
            return {
                "success": True,
                "status": "not_indexed",
                "message": "Documentation has not been indexed yet.",
            }
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "error": str(e),
        }


def get_all_tools() -> List:
    """Return all available tools for the agent."""
    return [
        search_documentation,
        get_documentation_status,
    ]


# =============================================================================
# Agent Definition
# =============================================================================

# Agent instruction - clear and concise
DOCS_AGENT_INSTRUCTION = """You are a YourCompany Documentation assistant.

RESPONSE LANGUAGE: Always respond in English only.

YOUR TASK:
1. Understand the user's documentation question
2. Call the search_documentation tool with an appropriate query
3. Output the tool's response directly without modification

RULES:
- Search with the user's query directly - do not ask for clarification
- If the tool returns a "display" field, output its content verbatim
- Do not add generic advice on top of search results
- Include source links from the tool response
"""


def create_docs_agent(
    name: str = "documentation",
    description: str = "Handles YourCompany documentation search and how-to queries",
) -> Any:
    """
    Create the Documentation ADK agent.

    Tools are passed directly to LlmAgent - ADK discovers their capabilities
    from function signatures and docstrings automatically.

    Args:
        name: Agent name for identification
        description: Agent description for orchestrator routing

    Returns:
        LlmAgent configured for documentation queries
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    model = get_litellm_model()
    tools = get_all_tools()

    # Pass tools to LlmAgent - ADK handles discovery from docstrings
    agent = LlmAgent(
        name=name,
        model=model,
        instruction=DOCS_AGENT_INSTRUCTION,
        description=description,
        tools=tools,  # ADK discovers capabilities from docstrings
    )

    logger.info("Created DocsAgent with %s tools (native ADK)", len(tools))
    return agent


# Singleton for reuse
_docs_agent: Optional[Any] = None


def get_docs_adk_agent() -> Any:
    """Get or create docs ADK agent singleton."""
    global _docs_agent
    if _docs_agent is None:
        _docs_agent = create_docs_agent()
    return _docs_agent

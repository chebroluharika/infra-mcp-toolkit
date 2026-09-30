"""
Documentation Agent
===================

Handles YourCompany documentation search using RAG.
Uses FAISS vector store for semantic search.
"""

from .agent import create_docs_agent, get_docs_adk_agent

__all__ = [
    "create_docs_agent",
    "get_docs_adk_agent",
]

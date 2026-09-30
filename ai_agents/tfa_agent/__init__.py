"""
Test Failure Analysis (TFA) Agent
=================================

Analyzes CI/CD test failures using RAG with LLM.
Uses Ollama Gateway for LLM inference.
Uses a simple vector store for pattern matching and root cause analysis.

Features:
- Pattern-based error analysis
- Similar failure retrieval
- Root cause identification
- Resolution recommendations
"""

from .agent import TFAAgent, get_tfa_agent

__all__ = [
    "TFAAgent",
    "get_tfa_agent",
]

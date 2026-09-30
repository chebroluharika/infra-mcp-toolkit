"""
GitHub Agent (ADK)
==================

Code-aware GitHub analysis agent with FAISS-backed repository knowledge.

Architecture:
    GitHubAgent (LlmAgent)
        └── Tools:
            ├── fetch_pr_details: PR metadata and changed files
            ├── get_code_context: File purpose, functions, docstrings from repo index
            ├── get_file_dependencies: Import/export relationships
            └── index_repository: Re-index a GitHub repo into FAISS

This agent handles:
- PR analysis (files changed, stats, author)
- Code context retrieval (what does a file do?)
- Dependency graph queries (what depends on this file?)
- Repository indexing

Reusable: Can be used standalone or as a sub-agent of escalation_analysis_agent.
"""

from .agent import create_github_agent, create_github_agent_async

__all__ = [
    "create_github_agent",
    "create_github_agent_async",
]

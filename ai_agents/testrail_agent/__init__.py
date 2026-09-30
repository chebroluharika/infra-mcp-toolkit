"""
TestRail Agent (ADK)
====================

Test-aware TestRail analysis agent with FAISS-backed test case knowledge.

Architecture:
    TestRailAgent (LlmAgent)
        └── Tools:
            ├── search_test_cases: Semantic search for matching test cases
            ├── get_test_coverage: Check test coverage for a feature area
            ├── get_test_run_details: Get test run pass/fail/untested counts
            └── index_testrail: Re-index TestRail test cases into FAISS

This agent handles:
- Test case matching (find relevant tests for a code area)
- Test coverage analysis (identify gaps)
- Test run status queries
- TestRail indexing

Reusable: Can be used standalone or as a sub-agent of escalation_analysis_agent.
"""

from .agent import create_testrail_agent, create_testrail_agent_async

__all__ = [
    "create_testrail_agent",
    "create_testrail_agent_async",
]

"""
Escalation Analysis Agent (ADK Orchestrator)
=============================================

Multi-agent orchestrator using Google ADK's sub_agents pattern.
Coordinates github_agent and testrail_agent to analyze PRs from
customer escalations and produce categorized test recommendations.

Architecture:
    EscalationAnalysisAgent (LlmAgent)
        └── sub_agents=[github_agent, testrail_agent]

Flow:
    1. User asks: "Analyze PR #7887 in your-org/your-product"
    2. Orchestrator transfers to github_agent → gets PR details + code context
    3. Orchestrator transfers to testrail_agent → gets matching test cases
    4. Orchestrator synthesizes → MUST RUN / SHOULD RUN / MANUAL QA / TEST GAPS

Both sub-agents are standalone LlmAgents that can also be used independently.
"""

import logging
from typing import Callable, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

# ADK imports
if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# =============================================================================
# Orchestrator Instruction
# =============================================================================

ESCALATION_ANALYSIS_INSTRUCTION = """You are a QA Test Recommendation agent for customer escalation analysis. RESPOND IN ENGLISH ONLY.

## YOUR TOOLS

You have direct access to tools for analyzing PRs and finding test cases:

### GitHub Tools:
- `fetch_pr_details(owner, repo, pr_number)` — Get PR metadata, changed files, stats, and QA recommendations from PR body
- `get_code_context(file_path)` — Get file purpose, functions, docstrings from repo index
- `get_file_dependencies(file_path)` — Get import/export relationships (blast radius)

### TestRail Tools:
- `search_test_cases(query, top_k)` — Search TestRail cases by natural language description
- `search_test_code(query, top_k)` — Search test code docstrings from your-product-tests repo
- `get_test_coverage(areas)` — Check test coverage for comma-separated feature areas

## WORKFLOW

### Single PR Analysis
When asked to analyze a PR:

1. **Call `fetch_pr_details`** to get the PR files, stats, and any QA recommendations from the author
2. **For important files**, call `get_code_context` and `get_file_dependencies` to understand what changed
3. **Call `search_test_cases`** AND **`search_test_code`** with descriptions of the changed areas
4. **Synthesize** the results into categorized test recommendations

### Multi-PR Analysis
When analyzing multiple PRs for a ticket:

1. Call `fetch_pr_details` for EACH PR
2. Aggregate all changed files across all PRs
3. Call test search tools with combined context
4. Produce a single unified recommendation

## USING JIRA CONTEXT

When JIRA ticket context is provided:
- **Description**: Explains the customer problem — understand WHAT scenario they hit
- **Components**: Tells you which product area is affected
- **Comments**: May contain repro steps, environment details, urgency
- **Priority**: Helps weight MUST RUN vs SHOULD RUN

Incorporate this context. If the ticket describes a specific customer scenario, ensure at least one manual_qa_scenario matches it.

## OUTPUT FORMAT (STRICT JSON)

You MUST respond with valid JSON in this exact structure:

```json
{
  "pr_summary": {
    "number": 7887,
    "title": "Fix session timeout",
    "author": "developer",
    "files_changed": 5,
    "total_additions": 120,
    "total_deletions": 45
  },
  "jira_context_used": {
    "ticket_key": "ENG-12345",
    "components": ["NS Client (NSC)"],
    "customer_scenario": "Brief summary of the customer issue from ticket description"
  },
  "must_run": [
    {
      "case_id": "C12345",
      "title": "Verify session timeout",
      "run_name": "Authentication Tests",
      "reason": "session_manager.py modified — session expiry logic changed",
      "testrail_url": "https://..."
    }
  ],
  "should_run": [
    {
      "case_id": "C12347",
      "title": "Multi-device session",
      "run_name": "Authentication Tests",
      "reason": "depends on session_manager which was modified",
      "testrail_url": "https://..."
    }
  ],
  "manual_qa_scenarios": [
    {
      "scenario": "Session Timeout With New Config Value",
      "steps": "1. Login\\n2. Change timeout config\\n3. Wait\\n4. Verify",
      "verify": "Session expires at new timeout value",
      "reason": "No existing TestRail case tests config-driven timeout changes"
    }
  ],
  "test_gaps": [
    {
      "area": "Configuration-driven session timeout",
      "file": "config/session.yaml",
      "issue": "No TestRail test case validates config changes affect timeout",
      "suggestion": "Add test: Verify session timeout reflects config value after restart"
    }
  ]
}
```

## RULES

1. ALWAYS call `fetch_pr_details` first for each PR
2. Call `search_test_cases` and `search_test_code` with descriptions of changed areas
3. Every test case in must_run/should_run MUST have a real TestRail case_id or test function reference
4. If indexes return empty/error, leave must_run and should_run as empty arrays
5. manual_qa_scenarios are for NEW tests that DON'T exist yet
6. test_gaps highlight areas where no test case matched
7. Be specific in reasons — reference actual file names
8. If QA recommendations were in the PR body, incorporate them
9. For multi-PR analysis, use a combined pr_summary with aggregated stats
10. Include jira_context_used only when JIRA context was provided

## CRITICAL OUTPUT RULES

- DO NOT explain your reasoning or thought process
- DO NOT include phrases like "We need to...", "Let me...", "I will..."
- Output ONLY the JSON structure — nothing before or after it
- Start your response with `{` and end with `}`
- NO markdown code fences (```json) — just raw JSON
- If a tool returns an error, still output JSON with empty arrays for that section
- NEVER output your internal planning or step-by-step thinking

EXAMPLE CORRECT OUTPUT:
{"pr_summary":{"number":1234,"title":"Fix bug","author":"dev","files_changed":2,"total_additions":50,"total_deletions":10},"must_run":[],"should_run":[],"manual_qa_scenarios":[],"test_gaps":[]}

EXAMPLE INCORRECT OUTPUT (DO NOT DO THIS):
"Let me analyze this PR. First I'll call fetch_pr_details..."
"""


# =============================================================================
# Agent Factory
# =============================================================================


def create_escalation_analysis_agent(
    github_agent=None,
    testrail_agent=None,
    name: str = "escalation_analysis",
    description: str = "Analyzes PRs from customer escalations to recommend QA tests using code context and TestRail matching",
) -> "LlmAgent":
    """
    Create the Escalation Analysis agent with direct tool access.

    This agent has direct access to tools from both github_agent and testrail_agent,
    allowing it to orchestrate the full PR analysis workflow without sub-agent transfers.

    Args:
        github_agent: Pre-created github_agent LlmAgent (optional, for tool extraction)
        testrail_agent: Pre-created testrail_agent LlmAgent (optional, for tool extraction)
        name: Agent name
        description: Agent description for routing

    Returns:
        LlmAgent with combined tools from GitHub and TestRail agents
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    # Import tool functions directly from sub-agents
    from github_agent.agent import fetch_pr_details, get_code_context, get_file_dependencies
    from google.adk.tools import FunctionTool
    from testrail_agent.agent import get_test_coverage, search_test_cases, search_test_code

    model = get_litellm_model()

    # Combine tools from both agents (no sub-agent transfer needed)
    tools = [
        # GitHub tools
        FunctionTool(fetch_pr_details),
        FunctionTool(get_code_context),
        FunctionTool(get_file_dependencies),
        # TestRail tools
        FunctionTool(search_test_cases),
        FunctionTool(search_test_code),
        FunctionTool(get_test_coverage),
    ]

    # Create agent with direct tools (no sub_agents - tools are called directly)
    agent = LlmAgent(
        name=name,
        model=model,
        instruction=ESCALATION_ANALYSIS_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info(
        "Created EscalationAnalysisAgent with %d direct tools (GitHub + TestRail)",
        len(tools),
    )
    return agent


async def create_escalation_analysis_agent_async(
    name: str = "escalation_analysis",
    description: str = "Analyzes PRs from customer escalations to recommend QA tests using code context and TestRail matching",
) -> Tuple["LlmAgent", Callable]:
    """
    Async factory for EscalationAnalysisAgent (compatible with root_agent pattern).

    Creates the agent with direct tools (no sub-agents).

    Returns:
        Tuple of (LlmAgent, cleanup_function)
    """
    # Create agent with direct tools
    agent = create_escalation_analysis_agent(
        name=name,
        description=description,
    )

    async def cleanup():
        pass  # No sub-agents or MCP connections to clean up

    return agent, cleanup

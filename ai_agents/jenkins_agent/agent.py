"""
Jenkins Agent (ADK + MCP)
=========================

ADK LlmAgent connected to Jenkins MCP server for CI/CD pipeline monitoring.

Architecture:
    JenkinsAgent (LlmAgent)
        └── MCP Server:
            └── jenkins-mcp-server: Pipeline status, builds, test reports, TFA

This agent handles:
- Pipeline status and health overview
- Build information and history
- Test reports and failure analysis
- Golden Regression Suite monitoring
- Test Failure Analysis (TFA) with root cause identification
"""

import logging
from typing import Any, Callable, Optional, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

# Check ADK availability
if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# Hybrid approach: Explicit mappings + Rich tool descriptions
# Optimized for medium-sized local LLMs (7B-14B) - reliable and fast
JENKINS_AGENT_INSTRUCTION_SIMPLIFIED = """You are a Jenkins CI/CD assistant for pipeline monitoring.

### MANDATORY LANGUAGE REQUIREMENT ###
YOU MUST RESPOND IN ENGLISH ONLY.
DO NOT USE THAI, CHINESE, JAPANESE, KOREAN OR ANY OTHER NON-ENGLISH LANGUAGE.
EVERY WORD IN YOUR RESPONSE MUST BE IN ENGLISH.
IF YOU RESPOND IN ANY OTHER LANGUAGE, THE SYSTEM WILL FAIL.

TOOL MAPPING - FOLLOW EXACTLY:
| Query Keywords | Tool | Parameters |
|----------------|------|------------|
| "list pipelines", "all pipelines", "pipeline status" | jenkins_get_pipelines | - |
| "builds for X", "runs for X", "top N builds", "last N runs" | jenkins_get_job_builds | job_name, limit |
| "why did build fail", "root cause", "TFA", "test failure" | jenkins_get_test_failure_analysis | job_name, build_number |
| "golden regression", "Endpoint PDV", "PDV runs", "PDV status" | jenkins_get_golden_regression | - |
| "build info", "build details" | jenkins_get_build_info | job_name, build_number |
| "test report", "test results" | jenkins_get_test_report | job_name, build_number |

PARAMETER EXTRACTION:
- "top 10 builds for Backend Regression" → job_name="Backend Regression", limit=10
- "last 5 runs for your-product-test" → job_name="your-product-test", limit=5
- "why did build 464 fail" → build_number=464
- Default limit=10 if not specified

YOUR TASK:
1. Match query keywords to the table above
2. Extract job_name, build_number, limit from query
3. Call the specified tool with correct parameters
4. Output the tool's "display" field directly

OUTPUT RULES:
- Output the "display" field exactly as returned
- Do NOT add commentary or repeat data
- Respond in English only

ALWAYS call a tool for data queries.
"""

# Keep original for fallback
JENKINS_AGENT_INSTRUCTION_LEGACY = """### MANDATORY LANGUAGE REQUIREMENT ###
YOU MUST RESPOND IN ENGLISH ONLY.
DO NOT USE CHINESE (中文), JAPANESE, KOREAN, OR ANY OTHER NON-ENGLISH LANGUAGE.
EVERY WORD IN YOUR RESPONSE MUST BE IN ENGLISH.
IF YOU RESPOND IN ANY OTHER LANGUAGE, THE SYSTEM WILL FAIL.

You handle Jenkins/pipeline queries. Call the appropriate tool.

TOOLS (MANDATORY MAPPING - FOLLOW EXACTLY):
- jenkins_get_pipelines: "list pipelines", "show all pipelines", "pipeline status", "CI/CD status"
- jenkins_get_job_builds: "builds for X", "last 10 builds", "pipeline runs for X", "build history for job"
- jenkins_get_test_failure_analysis: "root cause", "why failed", "TFA", "test failures"
- jenkins_get_golden_regression: "golden regression", "regression suite"

EXAMPLES:
- "list top 10 pipeline runs for Backend Regression" → jenkins_get_job_builds(job_name="Backend Regression", limit=10)
- "last 5 builds for your-product-backend-test" → jenkins_get_job_builds(job_name="your-product-backend-test", limit=5)
- "show all pipelines" → jenkins_get_pipelines()

CRITICAL RESPONSE RULES:
1. Call the appropriate tool with correct parameters
2. The tool response contains a "display" field with formatted markdown
3. OUTPUT THE ENTIRE "display" FIELD VERBATIM - do NOT summarize!
4. Never output raw JSON
5. DO NOT repeat data multiple times"""

# Select instruction based on configuration
# Select instruction based on configuration
try:
    from core.base import get_settings

    _settings = get_settings()
    JENKINS_AGENT_INSTRUCTION = (
        JENKINS_AGENT_INSTRUCTION_SIMPLIFIED
        if _settings.use_simplified_instructions
        else JENKINS_AGENT_INSTRUCTION_LEGACY
    )
except Exception:
    # Fallback to simplified if config fails
    JENKINS_AGENT_INSTRUCTION = JENKINS_AGENT_INSTRUCTION_SIMPLIFIED


async def create_jenkiollama_async(
    name: str = "jenkiollama",
    description: str = "Handles Jenkins pipeline status, builds, and test failure analysis",
) -> Tuple[Any, Callable]:
    """
    Create the Jenkins ADK agent with MCP tools.

    This is an async function because MCP server connections are async.

    Args:
        name: Agent name for identification
        description: Agent description for orchestrator routing

    Returns:
        Tuple of (LlmAgent, cleanup_function)

    Example:
        agent, cleanup = await create_jenkiollama_async()

        # Use agent...

        # When done (optional)
        await cleanup()
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    # Import MCP tools
    from .tools.mcp_tools import check_mcp_available, get_jenkins_mcp_tools

    if not check_mcp_available():
        raise RuntimeError("MCP support not available. Run: pip install google-adk[mcp]>=0.5.0")

    # Connect to Jenkins MCP server only
    try:
        toolsets, cleanup = await get_jenkins_mcp_tools()
    except Exception as e:
        logger.error("Failed to get Jenkins MCP tools: %s", e)
        raise RuntimeError(f"Failed to initialize Jenkins MCP tools: {e}")

    if not toolsets:
        logger.warning("No Jenkins MCP toolsets loaded - agent will have limited functionality")

        # Create empty cleanup function
        async def cleanup():
            pass

    model = get_litellm_model()

    # Create agent with Jenkins MCP toolset
    agent = LlmAgent(
        name=name,
        model=model,
        instruction=JENKINS_AGENT_INSTRUCTION,
        description=description,
        tools=toolsets,
    )

    logger.info("Created JenkinsAgent with %s MCP toolsets", len(toolsets))
    return agent, cleanup


# Singleton for reuse
_jenkiollama: Optional[Any] = None
_cleanup_func: Optional[Callable] = None


async def get_jenkins_adk_agent() -> Tuple[Any, Callable]:
    """Get or create Jenkins ADK agent singleton."""
    global _jenkiollama, _cleanup_func
    if _jenkiollama is None:
        _jenkiollama, _cleanup_func = await create_jenkiollama_async()
    return _jenkiollama, _cleanup_func

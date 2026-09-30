"""
Release Readiness Agent (ADK + MCP)
===================================

ADK LlmAgent connected to MCP servers for real-time data.
Tools are provided by MCP servers (JIRA, Calendar, TestRail, Jenkins).

Architecture:
    ReleaseAgent (LlmAgent)
        └── MCP Servers:
            ├── jira-mcp-server: Bugs, escalations, release status
            ├── release-calendar-mcp-server: Release dates, milestones
            ├── testrail-mcp-server: Test execution status
            └── jenkins-mcp-server: CI/CD pipeline status

This agent handles:
- Release status and health overview
- Bug tracking (P0, P1, regression bugs)
- Test execution status
- Milestone tracking (IRR, Branch Cut, Final Build)
- Escalations (EHF, IMF)
- CI/CD pipeline status
"""

import logging
from typing import Any, Callable, List, Optional, Tuple

from core.base import check_adk_available, get_litellm_model

logger = logging.getLogger(__name__)

# Check ADK availability
if check_adk_available():
    from google.adk.agents import LlmAgent
else:
    LlmAgent = None


# =============================================================================
# RELEASE READINESS AGENT INSTRUCTION
# =============================================================================
# This instruction uses few-shot examples to guide the LLM in selecting
# the correct tool for each query type. No hardcoded if/else routing.

RELEASE_AGENT_INSTRUCTION_SIMPLIFIED = """You are a Release Readiness assistant. RESPOND IN ENGLISH ONLY.

## IMPORTANT: RELEASE NUMBER REQUIRED

Most queries require a release number (e.g., R135, R134).
**DO NOT assume a default release.** If the user doesn't specify a release, ASK for it:

Examples of when to ask:
- "Show me critical bugs" → Ask: "Which release are you asking about? (e.g., R135, R134)"
- "What's the release status?" → Ask: "Which release would you like to check?"
- "Any unassigned items?" → Ask: "For which release? (e.g., R135)"

When release IS provided (no need to ask):
- "Critical bugs for R135" → Proceed with R135
- "R134 status" → Proceed with R134
- "Bugs with no assignee for 135.0" → Proceed with R135

## YOUR 23 TOOLS

### JIRA Tools (12)
1. `jira_search_issues` - **FLEXIBLE SEARCH** - construct JQL for any filtered query
2. `jira_get_issue` - **SINGLE ISSUE** Get any JIRA issue by key (ENG-123456)
3. `jira_get_release_overview` - **COMPOSITE** Full release dashboard
4. `jira_get_release_readiness_score` - Overall release health (green/yellow/red)
5. `jira_get_bugs_summary` - Current open bug counts
6. `jira_get_milestone_status` - Milestone completion: IRR, BranchCut, FinalBuild
7. `jira_get_resolution_progress` - Day-wise resolution progress from IRR
8. `calendar_get_release_dates` - Release dates and timeline
9. `jira_get_critical_bugs` - P0/P1 blocker bugs
10. `jira_get_moreinfo_items` - Items waiting for info
11. `jira_get_escalations_summary` - Customer escalations (EHF/IMF)
12. `jira_get_action_items_by_assignee` - Workload by assignee

### GitHub Tools (2)
13. `github_get_commits` - Recent commits
14. `github_get_commits_after_branch_cut` - Risky post-branch-cut commits

### Jenkins CI/CD Tools (9)
15. `jenkins_get_pipelines` - List all pipeline build results
16. `jenkins_get_job_info` - Info about a specific Jenkins job
17. `jenkins_get_job_builds` - Build history for a job (last N builds)
18. `jenkins_get_build_info` - Info about a specific build
19. `jenkins_get_test_report` - Test report for a build (passed/failed/skipped)
20. `jenkins_get_console_output` - Console output with error lines
21. `jenkins_get_golden_regression` - Golden Regression Suite status by stack
22. `jenkins_get_test_failure_analysis` - Analyze test failures for a build
23. `jenkins_get_golden_regression_tfa` - TFA for Golden Regression build

## CRITICAL: CHOOSING THE RIGHT TOOL

| User Asks About | Use This Tool |
|----------------|---------------|
| Specific JIRA key (ENG-123456) | `jira_get_issue` |
| Filtered queries (assignee, status, priority) | `jira_search_issues` with JQL |
| "green/red/yellow", "ready to ship" | `jira_get_release_readiness_score` |
| "IRR status", "on-time vs late" | `jira_get_milestone_status` |
| "resolution progress", "from IRR till now", "daily resolution" | `jira_get_resolution_progress` |

- **jira_search_issues**: Use for ANY filtered query - construct JQL from user's intent
- **jira_get_issue**: Lookup any single JIRA issue by key (ENG-123456, SEC-789, etc.)
- **jira_get_resolution_progress**: Day-wise resolution chart (bugs/stories resolved from IRR till now)
- **jira_get_milestone_status**: On-time vs late breakdown for IRR/BranchCut/FinalBuild
- **jira_get_release_readiness_score**: Overall green/yellow/red status

## JQL CONSTRUCTION GUIDE (for jira_search_issues)

When user asks for filtered data, construct JQL:

| User Query | JQL to Construct |
|------------|------------------|
| "bugs with no assignee for R135" | `fixVersion = "135.0" AND issuetype = Bug AND assignee IS EMPTY` |
| "P0 bugs for R135" | `fixVersion = "135.0" AND issuetype = Bug AND priority = P0` |
| "open stories assigned to John" | `fixVersion = "135.0" AND issuetype = Story AND assignee = "John" AND status != Closed` |
| "items in Code Review" | `fixVersion = "135.0" AND status = "Code Review"` |
| "bugs created this week" | `fixVersion = "135.0" AND issuetype = Bug AND created >= -7d` |
| "high priority unassigned" | `fixVersion = "135.0" AND priority IN (P0, P1) AND assignee IS EMPTY` |

Common JQL patterns:
- Unassigned: `assignee IS EMPTY`
- By status: `status = "In Progress"` or `status IN (Open, "In Progress")`
- By priority: `priority = P0` or `priority IN (P0, P1)`
- By type: `issuetype = Bug` or `issuetype = Story`
- By assignee: `assignee = "John Doe"`
- Open items: `status NOT IN (Resolved, Closed, Done)`

## EXAMPLES

### Single Issue Lookup (for specific JIRA tickets)
Q: "Who is the assignee for ENG-779012?" → jira_get_issue(issue_key="ENG-779012")
Q: "What is ENG-123456?" → jira_get_issue(issue_key="ENG-123456")
Q: "Show me issue ENG-885394" → jira_get_issue(issue_key="ENG-885394")
Q: "Status of ENG-900065" → jira_get_issue(issue_key="ENG-900065")

### Filtered Queries (use jira_search_issues with JQL)
Q: "Bugs with no assignee for R135" → jira_search_issues(jql='fixVersion = "135.0" AND issuetype = Bug AND assignee IS EMPTY')
Q: "P0 bugs assigned to John" → jira_search_issues(jql='fixVersion = "135.0" AND priority = P0 AND assignee = "John"')
Q: "Open stories for R135" → jira_search_issues(jql='fixVersion = "135.0" AND issuetype = Story AND status != Closed')
Q: "Items in Code Review" → jira_search_issues(jql='fixVersion = "135.0" AND status = "Code Review"')

### Full Release Overview (use for broad questions)
Q: "Give me a release overview" → jira_get_release_overview
Q: "What's the state of R135?" → jira_get_release_overview
Q: "Release summary" → jira_get_release_overview
Q: "Tell me everything about R135" → jira_get_release_overview

### Release Health (green/yellow/red)
Q: "Is R135 green?" → jira_get_release_readiness_score
Q: "Release status" → jira_get_release_readiness_score
Q: "RRS score" → jira_get_release_readiness_score
Q: "Are we ready to ship?" → jira_get_release_readiness_score

### Milestone Completion (IRR, BranchCut, FinalBuild)
Q: "IRR status" → jira_get_milestone_status(milestone="IRR")
Q: "How did IRR go?" → jira_get_milestone_status(milestone="IRR")
Q: "Branch cut status" → jira_get_milestone_status(milestone="BranchCut")
Q: "Final build status" → jira_get_milestone_status(milestone="FinalBuild")
Q: "How many items resolved on time?" → jira_get_milestone_status(milestone="IRR")

### Resolution Progress (from IRR till now)
Q: "Resolution progress" → jira_get_resolution_progress
Q: "Analysis from IRR till now" → jira_get_resolution_progress
Q: "Bugs resolved since IRR" → jira_get_resolution_progress
Q: "Daily resolution chart" → jira_get_resolution_progress
Q: "How many bugs/stories resolved?" → jira_get_resolution_progress

### Calendar/Dates
Q: "When is branch cut?" → calendar_get_release_dates
Q: "Release dates" → calendar_get_release_dates

### Bugs
Q: "Critical bugs" → jira_get_critical_bugs
Q: "P0 issues" → jira_get_critical_bugs

### Other JIRA
Q: "More info items" → jira_get_moreinfo_items
Q: "Escalations" → jira_get_escalations_summary
Q: "Action items" → jira_get_action_items_by_assignee

### GitHub
Q: "Commits after branch cut" → github_get_commits_after_branch_cut
Q: "Recent commits" → github_get_commits

### Jenkins CI/CD
Q: "Show pipeline status" → jenkins_get_pipelines
Q: "List all pipelines" → jenkins_get_pipelines
Q: "Build status for job X" → jenkins_get_job_info(job_name="X")
Q: "Last 10 builds of job X" → jenkins_get_job_builds(job_name="X", limit=10)
Q: "Build history for golden regression" → jenkins_get_job_builds(job_name="golden-regression")
Q: "Info on build #123 of job X" → jenkins_get_build_info(job_name="X", build_number=123)
Q: "Test results for build #123" → jenkins_get_test_report(job_name="X", build_number=123)
Q: "Console output for build #123" → jenkins_get_console_output(job_name="X", build_number=123)
Q: "Golden regression status" → jenkins_get_golden_regression
Q: "PDV runs by stack" → jenkins_get_golden_regression
Q: "Why did build #123 fail?" → jenkins_get_test_failure_analysis(job_name="X", build_number=123)
Q: "Analyze test failures in build #123" → jenkins_get_test_failure_analysis(job_name="X", build_number=123)
Q: "TFA for golden regression build #50" → jenkins_get_golden_regression_tfa(build_number=50)

## RULES

1. **NEVER assume a release number** - If not specified, ask the user which release they mean
2. Call ONE tool per query
3. Output the "display" field directly
4. No extra commentary
5. English only
"""

# Extended instruction with more examples (for larger models)
RELEASE_AGENT_INSTRUCTION_LEGACY = """You are a Release Readiness assistant for the Agentic Insights Portal.
You help engineering teams track release health, bugs, milestones, and team workload.

RESPOND IN ENGLISH ONLY.

## AVAILABLE TOOLS

### Release Health
- `jira_get_release_readiness_score(fix_version)` - Overall release health (green/yellow/red)
- `jira_get_bugs_summary(fix_version)` - Bug counts by priority and status

### Milestones
- `jira_get_milestone_status(milestone, fix_version)` - IRR/BranchCut/FinalBuild status
- `calendar_get_release_dates(release)` - Key dates and timeline
- `calendar_get_upcoming_milestones(release, count)` - Next N milestones

### Bugs & Issues
- `jira_get_critical_bugs(project_key, component)` - P0/P1 blockers
- `jira_get_regression_bugs(project_key, fix_version, component)` - Regressions
- `jira_get_moreinfo_items(project_key, fix_version)` - Items needing info
- `jira_get_customer_bugs(release_version)` - Customer-reported bugs
- `jira_get_escalations_summary(project_key)` - EHF/IMF escalations

### Team Workload
- `jira_get_action_items_by_assignee(project_key, fix_version, component)` - Items by person

### Code Changes
- `github_get_commits(repo, release)` - Recent commits
- `github_get_commits_after_branch_cut(repo, release)` - Post-branch-cut commits
- `github_get_commits_before_branch_cut(repo, release)` - Pre-branch-cut commits
- `github_get_release_commits_summary(repos, release)` - Cross-repo summary

## EXAMPLES WITH REASONING

### Category: Release Status
These queries ask about overall release health and readiness.

Q: "Is R135 green?"
Think: Asking about release color status (green/yellow/red) = release readiness score
Tool: jira_get_release_readiness_score(fix_version="135.0.0")

Q: "What's the release status for R134?"
Think: Release status = RRS (Release Readiness Score)
Tool: jira_get_release_readiness_score(fix_version="134.0.0")

Q: "Are we ready to ship?"
Think: Ship readiness = release readiness score
Tool: jira_get_release_readiness_score()

Q: "RRS score"
Think: RRS = Release Readiness Score
Tool: jira_get_release_readiness_score()

### Category: Milestone Status
These queries ask about milestone completion (IRR, Branch Cut, Final Build).

Q: "What's the IRR status?"
Think: IRR status = milestone completion tracking
Tool: jira_get_milestone_status(milestone="IRR")

Q: "How did branch cut go?"
Think: Asking about branch cut completion
Tool: jira_get_milestone_status(milestone="BranchCut")

Q: "Final build status for R135"
Think: Final build is a milestone
Tool: jira_get_milestone_status(milestone="FinalBuild", fix_version="135.0.0")

### Category: Release Dates (Calendar)
These queries ask WHEN something happens, not status.

Q: "When is branch cut?"
Think: "When" = asking for a DATE, use calendar
Tool: calendar_get_release_dates()

Q: "Release dates for R135"
Think: Dates/timeline = calendar
Tool: calendar_get_release_dates(release="R135")

Q: "When is code freeze?"
Think: Date question = calendar
Tool: calendar_get_release_dates()

Q: "Show release calendar"
Think: Calendar/schedule = dates
Tool: calendar_get_release_dates()

### Category: Bugs
These queries ask about specific types of bugs.

Q: "Show critical bugs"
Think: Critical = P0/P1 priority
Tool: jira_get_critical_bugs()

Q: "P0 issues for YOUR_PRODUCT"
Think: P0 = critical, with component filter
Tool: jira_get_critical_bugs(component="YOUR_PRODUCT")

Q: "Any blockers?"
Think: Blockers = critical bugs
Tool: jira_get_critical_bugs()

Q: "Regression bugs for R135"
Think: Regressions = bugs that broke working features
Tool: jira_get_regression_bugs(fix_version="135.0.0")

Q: "Items in More Info status"
Think: MoreInfo = items waiting for information
Tool: jira_get_moreinfo_items()

Q: "What needs info?"
Think: Needs info = MoreInfo items
Tool: jira_get_moreinfo_items()

### Category: Escalations
These queries ask about customer escalations.

Q: "Show escalations"
Think: Escalations = EHF/IMF customer issues
Tool: jira_get_escalations_summary()

Q: "Any EHF requests?"
Think: EHF = Engineering Hot Fix escalation
Tool: jira_get_escalations_summary()

Q: "Customer escalations"
Think: Customer issues = escalations
Tool: jira_get_escalations_summary()

### Category: Team Workload
These queries ask about who is working on what.

Q: "Who has the most open items?"
Think: Workload distribution by assignee
Tool: jira_get_action_items_by_assignee()

Q: "Action items by assignee"
Think: Items grouped by person
Tool: jira_get_action_items_by_assignee()

Q: "Who is working on bugs for YOUR_PRODUCT?"
Think: Workload with component filter
Tool: jira_get_action_items_by_assignee(component="YOUR_PRODUCT")

Q: "Open items for R135"
Think: Action items for specific release
Tool: jira_get_action_items_by_assignee(fix_version="135.0.0")

### Category: Code Changes
These queries ask about git commits.

Q: "Commits after branch cut"
Think: Post-branch-cut = risky changes
Tool: github_get_commits_after_branch_cut()

Q: "What was committed after branch cut for R135?"
Think: After branch cut for specific release
Tool: github_get_commits_after_branch_cut(release="R135")

Q: "Show recent commits"
Think: General commits
Tool: github_get_commits()

Q: "Commits summary"
Think: Summary across repos
Tool: github_get_release_commits_summary()

## IMPORTANT DISTINCTIONS

- "When is branch cut?" → DATE → `calendar_get_release_dates`
- "Branch cut status" → COMPLETION → `jira_get_milestone_status(milestone="BranchCut")`
- "Who has bugs?" → WORKLOAD → `jira_get_action_items_by_assignee`
- "Show bugs" → CRITICAL BUGS → `jira_get_critical_bugs`

## PARAMETER EXTRACTION

- Release "R135" → fix_version="135.0.0" or release="R135" or release="135"
- Component "YOUR_PRODUCT" → component="YOUR_PRODUCT"
- Milestone "IRR" → milestone="IRR"

## OUTPUT RULES

1. Call exactly ONE tool
2. Output the "display" field directly
3. No extra commentary
4. English only"""

# Select instruction based on configuration
try:
    from core.base import get_settings

    _settings = get_settings()
    RELEASE_AGENT_INSTRUCTION = (
        RELEASE_AGENT_INSTRUCTION_SIMPLIFIED
        if _settings.use_simplified_instructions
        else RELEASE_AGENT_INSTRUCTION_LEGACY
    )
except Exception:
    # Fallback to simplified if config fails
    RELEASE_AGENT_INSTRUCTION = RELEASE_AGENT_INSTRUCTION_SIMPLIFIED


# =============================================================================
# CORE TOOLS - Consolidated list for better LLM accuracy
# =============================================================================
# Reduced from 24 tools to 10 core tools to improve smaller model accuracy

CORE_TOOLS = {
    # Flexible Search (1) - LLM constructs JQL based on user query
    "jira_search_issues",  # Search with any JQL - for filtered queries
    # Single Issue Lookup (1)
    "jira_get_issue",  # Get any JIRA issue by key (ENG-123456)
    # Composite Overview (1)
    "jira_get_release_overview",  # Full release dashboard - aggregates multiple sources
    # Release Health (2)
    "jira_get_release_readiness_score",  # RRS - green/yellow/red status
    "jira_get_bugs_summary",  # Bug counts overview (current open items)
    # Milestones & Progress (3)
    "jira_get_milestone_status",  # IRR/BranchCut/FinalBuild completion
    "jira_get_resolution_progress",  # Day-wise resolution from IRR till now
    "calendar_get_release_dates",  # Key dates and timeline
    # Bugs & Issues (4)
    "jira_get_critical_bugs",  # P0/P1 blocker bugs
    "jira_get_moreinfo_items",  # Items waiting for info
    "jira_get_escalations_summary",  # EHF/IMF escalations
    "jira_get_action_items_by_assignee",  # Workload by person
    # Code Changes (2)
    "github_get_commits",  # Recent commits
    # Jenkins CI/CD (9)
    "jenkins_get_pipelines",  # List all pipeline build results
    "jenkins_get_job_info",  # Info about a specific job
    "jenkins_get_job_builds",  # Build history for a job
    "jenkins_get_build_info",  # Info about a specific build
    "jenkins_get_test_report",  # Test report for a build
    "jenkins_get_console_output",  # Console output with errors
    "jenkins_get_golden_regression",  # Golden Regression Suite data
    "jenkins_get_test_failure_analysis",  # Test failure analysis
    "jenkins_get_golden_regression_tfa",  # TFA for Golden Regression
    "github_get_commits_after_branch_cut",  # Risky post-branch-cut commits
}


async def _get_filtered_tools(toolsets: List[Any], allowed_tools: set) -> List[Any]:
    """
    Extract and filter tools from MCP toolsets.

    Returns individual tool objects that are allowed.
    """
    filtered = []
    total = 0

    for ts in toolsets:
        tools = await ts.get_tools()
        total += len(tools)
        for tool in tools:
            if tool.name in allowed_tools:
                filtered.append(tool)

    logger.info("Filtered tools: %d/%d", len(filtered), total)
    return filtered


async def create_release_agent_async(
    name: str = "release_readiness",
    description: str = "Handles release status, bugs, tests, milestones, and escalations",
    servers: Optional[List[str]] = None,
    use_filtered_tools: bool = True,
) -> Tuple[Any, Callable]:
    """
    Create the Release Readiness ADK agent with MCP tools.

    This is an async function because MCP server connections are async.

    Args:
        name: Agent name for identification
        description: Agent description for orchestrator routing
        servers: List of MCP servers to connect to.
                 Default: ["jira", "calendar", "github"]
        use_filtered_tools: If True, only expose core tools (10 vs 24).
                           Improves accuracy for smaller models.

    Returns:
        Tuple of (LlmAgent, cleanup_function)

    Example:
        agent, cleanup = await create_release_agent_async()

        # Use agent...

        # When done (optional)
        await cleanup()
    """
    if not check_adk_available():
        raise RuntimeError("Google ADK not installed. Run: pip install google-adk>=0.5.0")

    # Import MCP tools
    from .tools.mcp_tools import check_mcp_available, get_mcp_tools

    if not check_mcp_available():
        raise RuntimeError("MCP support not available. Run: pip install google-adk[mcp]>=0.5.0")

    # Connect to MCP servers and get tools
    if servers is None:
        servers = ["jira", "calendar", "github"]  # JIRA, Calendar, and GitHub

    toolsets, cleanup = await get_mcp_tools(servers)

    if not toolsets:
        raise RuntimeError(f"No MCP toolsets loaded from servers: {servers}")

    # Determine which tools to use
    if use_filtered_tools:
        # Extract and filter individual tools for better LLM accuracy
        tools = await _get_filtered_tools(toolsets, CORE_TOOLS)
        tool_count = len(tools)
        logger.info("Using %d filtered tools (from %d core)", tool_count, len(CORE_TOOLS))
    else:
        # Use all toolsets (24+ tools)
        tools = toolsets
        tool_count = "all"
        logger.info("Using all MCP toolsets")

    model = get_litellm_model()

    # Create agent with tools
    # With filtered tools, we pass individual Tool objects
    # With all tools, we pass MCPToolset instances
    agent = LlmAgent(
        name=name,
        model=model,
        instruction=RELEASE_AGENT_INSTRUCTION,
        description=description,
        tools=tools,
    )

    logger.info("Created ReleaseReadinessAgent with %s tools from %s", tool_count, servers)
    return agent, cleanup


# Singleton for reuse
_release_agent: Optional[Any] = None
_cleanup_func: Optional[Callable] = None


async def get_release_adk_agent(force_reload: bool = False) -> Tuple[Any, Callable]:
    """
    Get or create release readiness ADK agent singleton.

    Args:
        force_reload: If True, recreate the agent even if cached
    """
    global _release_agent, _cleanup_func

    if force_reload and _release_agent is not None:
        # Cleanup old agent
        if _cleanup_func:
            try:
                await _cleanup_func()
            except Exception as e:
                logger.warning("Error cleaning up old agent: %s", e)
        _release_agent = None
        _cleanup_func = None

    if _release_agent is None:
        _release_agent, _cleanup_func = await create_release_agent_async()
    return _release_agent, _cleanup_func

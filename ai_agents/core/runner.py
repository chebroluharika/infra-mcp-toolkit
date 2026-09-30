"""
ADK Agent Runner
================

Runs ADK agents with session management and streaming support.
Supports multiple session backends: InMemory, SQLite, MongoDB.

Features:
- Session-based conversation history (persistent with MongoDB/SQLite)
- Streaming response support
- Error handling and fallbacks
- Release context management
- Cross-agent communication

Usage:
    from ai_agents import get_runner, create_root_agent

    root_agent = create_root_agent()
    runner = get_runner()

    # Non-streaming
    response = await runner.run(root_agent, "What's the release status?", session_id="user-123")

    # Streaming
    async for chunk in runner.run_stream(root_agent, "Show me bugs", session_id="user-123"):
        print(chunk, end="", flush=True)
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from .base import check_adk_available
from .models import AgentResponse
from .utils import get_utils

# Import config for default release (single source of truth - REQUIRED)
try:
    from .base import get_settings as get_ai_settings

    DEFAULT_RELEASE = get_ai_settings().default_release
except ImportError:
    DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE")
    if not DEFAULT_RELEASE:
        raise EnvironmentError(
            "CURRENT_RELEASE environment variable is required! " "Set it in your .env file or docker-compose.yml"
        )

# Import genai types with fallback
try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None

logger = logging.getLogger(__name__)

# Check ADK availability
if check_adk_available():
    from google.adk import Runner
else:
    Runner = None

# Check MongoDB availability
try:
    from core.mongodb_session import MongoDBSessionService

    HAS_MONGODB = True
except ImportError:
    MongoDBSessionService = None
    HAS_MONGODB = False

# Smart Router Pattern
# The router selects the appropriate agent based on query patterns (no LLM call)
# The selected agent uses its LLM to choose the right MCP tool
# This gives us: fast routing + ADK agent capabilities


class AgentRunner:
    """
    Manages ADK agent execution with session handling.

    This class wraps ADK's Runner with:
    - Session management (DatabaseSessionService for persistence, InMemorySessionService as fallback)
    - Release context handling
    - Error recovery
    - Response formatting
    """

    def __init__(self, db_path: str = None, use_mongodb: bool = None, mongo_uri: str = None):
        """
        Initialize AgentRunner with session storage.

        Args:
            db_path: Path to SQLite database (for DatabaseSessionService)
            use_mongodb: If True, use MongoDB for session storage
            mongo_uri: MongoDB connection URI (default: from MONGODB_URI env var)
        """
        if not check_adk_available():
            raise RuntimeError("Google ADK not installed")

        # Check if MongoDB is disabled via environment variable
        disable_mongodb = os.environ.get("DISABLE_MONGODB", "").lower() in ("true", "1", "yes")

        # Try MongoDB first (unless disabled), fall back to in-memory
        if HAS_MONGODB and not disable_mongodb:
            try:
                mongo_uri = mongo_uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
                self._session_service = MongoDBSessionService(mongo_uri=mongo_uri)
                self._session_type = "mongodb"
                logger.info("Using MongoDBSessionService for persistent storage")
            except Exception as e:
                logger.warning("MongoDB connection failed: %s. Using in-memory sessions.", e)
                from google.adk.sessions import InMemorySessionService

                self._session_service = InMemorySessionService()
                self._session_type = "memory"
        else:
            from google.adk.sessions import InMemorySessionService

            self._session_service = InMemorySessionService()
            self._session_type = "memory"
            if disable_mongodb:
                logger.info("Using InMemorySessionService (MongoDB disabled by env var)")
            else:
                logger.info("Using InMemorySessionService (MongoDB not available)")

        self._sessions: Dict[str, str] = {}  # session_id -> adk_session_id
        self._runners: Dict[str, Any] = {}  # agent_name -> Runner

        # Utility instance (combined extractor + formatter)
        self._utils = get_utils()

        # Load settings for configuration
        from .base import get_settings

        self.settings = get_settings()

    @property
    def session_type(self) -> str:
        """Get the current session storage type (mongodb, sqlite, memory)."""
        return self._session_type

    @property
    def session_info(self) -> Dict[str, Any]:
        """Get session service information for status display."""
        return {
            "type": self._session_type,
            "persistent": True,
            "mongodb_available": HAS_MONGODB,
        }

    async def _get_or_create_session(
        self,
        agent: Any,
        session_id: str,
        release_context: str = None,
    ) -> Any:
        """Get or create ADK session for a user session."""
        # Create a composite key for agent instance + session
        # Use id(agent) to detect agent reinitialization (new MCP connections)
        key = f"{agent.name}:{id(agent)}:{session_id}"

        # Clean up old sessions for different agent instances
        if key not in self._sessions:
            old_keys = [
                k
                for k in self._sessions
                if k.startswith(f"{agent.name}:") and k.endswith(f":{session_id}") and k != key
            ]
            for old_key in old_keys:
                del self._sessions[old_key]

        if key not in self._sessions:
            # Create new ADK session (async in newer ADK versions)
            import uuid

            adk_session_id = str(uuid.uuid4())

            try:
                # Try async create_session (ADK >= 1.0)
                adk_session = await self._session_service.create_session(
                    app_name="qe_dashboard",
                    user_id=session_id,
                    session_id=adk_session_id,
                )
            except TypeError:
                # Fallback for sync create_session (older ADK)
                adk_session = self._session_service.create_session(
                    app_name="qe_dashboard",
                    user_id=session_id,
                    session_id=adk_session_id,
                )

            self._sessions[key] = adk_session.id

            # Set release context in session state
            if release_context:
                adk_session.state["release"] = release_context
            else:
                adk_session.state["release"] = DEFAULT_RELEASE  # Default from config

            logger.debug("Created new session: %s", adk_session.id)
            return adk_session

        # Get existing session
        try:
            # Try async get_session (ADK >= 1.0)
            return await self._session_service.get_session(
                app_name="qe_dashboard",
                user_id=session_id,
                session_id=self._sessions[key],
            )
        except TypeError:
            # Fallback for sync get_session (older ADK)
            return self._session_service.get_session(
                app_name="qe_dashboard",
                user_id=session_id,
                session_id=self._sessions[key],
            )

    def _get_runner(self, agent: Any) -> Any:
        """Get or create Runner for an agent."""
        # Use agent id() to detect if the agent instance changed
        # This handles cases where agent is recreated with new MCP connections
        cache_key = f"{agent.name}:{id(agent)}"

        if cache_key not in self._runners:
            # Clear any old runners for this agent name (different instance)
            old_keys = [k for k in self._runners if k.startswith(f"{agent.name}:")]
            for old_key in old_keys:
                del self._runners[old_key]

            self._runners[cache_key] = Runner(
                agent=agent,
                app_name="qe_dashboard",
                session_service=self._session_service,
            )
            logger.info("Created new ADK Runner for %s", agent.name)

        return self._runners[cache_key]

    # =========================================================================
    # CoreUtils
    # =========================================================================

    def extract(self, query: str, extract_type: str, available_items: list = None, fallback: Any = None) -> Any:
        """Delegate to CoreUtils.extract()"""
        return self._utils.extract(query, extract_type, available_items, fallback)

    def _is_greeting(self, message: str) -> bool:
        """Check if message is a greeting."""
        return self._utils.is_greeting(message)

    def _is_data_query(self, message: str) -> bool:
        """
        Check if message is asking for data that requires a tool call.

        Returns True for queries about bugs, releases, milestones, commits, pipelines, etc.
        Returns False for greetings, general questions, or help requests.
        """
        msg_lower = message.lower().strip()

        # Data query keywords that should trigger tool usage
        data_keywords = [
            # Bug queries
            r"\b(bug|bugs|blocker|critical|regression|issue|issues)\b",
            # Release/status queries
            r"\b(release|rrs|readiness|status|green|yellow|red|score)\b",
            # Milestone queries
            r"\b(irr|branch.?cut|final.?build|milestone)\b",
            # Commit queries
            r"\b(commit|commits|github|code.?change|merge)\b",
            # Escalation queries
            r"\b(escalation|escalations|customer)\b",
            # Jenkins/Pipeline queries
            r"\b(jenkins|pipeline|pipelines|builds?|ci/?cd)\b",
            r"\b(tfa|test.?failure|root.?cause)\b",
            r"\b(golden.?regression)\b",
            r"\b(list|show|get)\s+.*(builds?|runs?|pipelines?)\b",
            # Test queries
            r"\b(test|tests|testrail|execution|coverage)\b",
            # Pipeline queries
            r"\b(pipeline|jenkins|build|ci|cd)\b",
            # General data queries
            r"\b(show|list|get|fetch|how.?many|count|what.?is|whats)\b",
        ]

        # Non-data queries (should not require tools)
        non_data_patterns = [
            r"^(hi|hello|hey|thanks|thank you|bye|goodbye)",
            r"\b(help|how do i|can you|what can you)\b",
            r"\b(explain|describe|tell me about)\b.*\b(yourself|you do)\b",
        ]

        # Check if it's a non-data query first
        for pattern in non_data_patterns:
            if re.search(pattern, msg_lower):
                return False

        # Check if it matches data query patterns
        for pattern in data_keywords:
            if re.search(pattern, msg_lower):
                return True

        return False

    def _response_contains_data(self, content: str) -> bool:
        """
        Check if response contains actual data (tables, numbers, JSON, etc.).

        Returns True if the response appears to have structured data.
        Returns False if it's just generic text.
        """
        if not content:
            return False

        # Indicators of data content
        data_indicators = [
            r"\|.*\|.*\|",  # Table rows
            r"##\s+\w+.*\d+",  # Headers with numbers
            r"🟢|🟡|🔴|✅|❌|⚠️",  # Status emojis
            r"\d+\s*(bugs?|issues?|items?|commits?|builds?)",  # Counts
            r"(ENG|YOUR_PRODUCT|NPA)-\d+",  # JIRA keys
            r"\b\d{1,3}%",  # Percentages
            r"Total:\s*\d+",  # Totals
            r"Open:\s*\d+",  # Open counts
            # Jenkins-specific indicators
            r"Build\s*#?\d+",  # Build numbers
            r"Pipeline.*Status",  # Pipeline headers
            r"Build\s*History",  # Build history headers
            r"(passed|failed|success)\s*:\s*\d+",  # Test results
            r"Health:\s*\d+%",  # Health percentage
            r"\bjenkins\b",  # Jenkins mention
            # JSON structure indicators (for agent outputs like escalation_analysis)
            r'"pr_summary"\s*:',  # PR analysis JSON
            r'"must_run"\s*:',  # Test recommendations JSON
            r'"should_run"\s*:',  # Test recommendations JSON
            r'"test_gaps"\s*:',  # Test gaps JSON
            r'"manual_qa_scenarios"\s*:',  # QA scenarios JSON
            r"```json",  # JSON code blocks
        ]

        for pattern in data_indicators:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def _is_asking_clarification(self, content: str) -> bool:
        """
        Check if LLM response is asking for clarification instead of answering.

        This happens when Qwen and similar models don't call tools and instead
        ask the user to be more specific.
        """
        if not content:
            return False

        content_lower = content.lower()

        # Patterns indicating the LLM is asking for clarification
        clarification_patterns = [
            r"could you (please )?(specify|clarify|confirm|provide)",
            r"please (specify|clarify|provide|confirm)",
            r"to proceed.*(need|require)",
            r"what (specific|exactly|precisely)",
            r"which (specific|request|information)",
            r"can you (be more specific|clarify|tell me)",
            r"i need (more|additional) (information|details|context)",
            r"please (be more specific|provide more)",
            r"what would you like (to know|me to)",
            r"how can i (help|assist) you",
        ]

        for pattern in clarification_patterns:
            if re.search(pattern, content_lower):
                return True

        return False

    async def _pre_route_query(
        self,
        agent: Any,
        message: str,
        session_id: str,
        release_context: str = None,
    ) -> Optional["AgentResponse"]:
        """
        Pre-route common queries directly to tools, bypassing the LLM.

        This is faster and more reliable for well-known query patterns.
        Returns AgentResponse if handled, None to fall through to LLM.
        """
        import sys
        import time

        _t_start = time.time()
        msg_lower = message.lower()

        # Extract release version
        release_match = re.search(r"\br?(\d{3})\b", message, re.IGNORECASE)
        release = release_match.group(1) if release_match else (release_context or DEFAULT_RELEASE).replace("R", "")
        fix_version = f"{release}.0.0"

        # Pattern matching for common queries
        # NOTE: Order matters! More specific patterns should come first
        tool_name = None
        tool_params = {}

        # Commits after branch cut
        if re.search(r"\bcommits?\s*(after|since)\s*branch.?cut\b", msg_lower):
            tool_name = "github_get_commits_after_branch_cut"
            tool_params = {"release": f"R{release}", "repo": "client"}
        # Commits before branch cut
        elif re.search(r"\bcommits?\s*before\s*branch.?cut\b", msg_lower):
            tool_name = "github_get_commits"
            tool_params = {"release": f"R{release}", "repo": "client"}
        # General commits (must come after specific commit queries)
        elif re.search(r"\b(commits?|code\s*changes?)\b", msg_lower) and not re.search(r"\bbranch.?cut\b", msg_lower):
            tool_name = "github_get_commits"
            tool_params = {"release": f"R{release}", "repo": "client"}
        # Release status queries
        elif re.search(
            r"\b(is\s+r?\d{3}\s+green|green|red|yellow|rrs|release\s*status|status\s+of|ready\s+to\s+release)\b",
            msg_lower,
        ):
            tool_name = "jira_get_release_readiness_score"
            tool_params = {"fix_version": fix_version}
        # Critical bugs queries
        elif re.search(r"\b(critical|blocker|p0|p1|high\s*priority)\s*(bug|issue)?s?\b", msg_lower):
            tool_name = "jira_get_critical_bugs"
            tool_params = {"fix_version": fix_version}
        # IRR status
        elif re.search(r"\birr\s*(status)?\b", msg_lower):
            tool_name = "jira_get_milestone_status"
            tool_params = {"milestone": "IRR", "fix_version": fix_version}
        # Branch cut STATUS (not commits) - must check it's asking about status
        elif re.search(r"\bbranch.?cut\s*(status|completion|progress)\b", msg_lower):
            tool_name = "jira_get_milestone_status"
            tool_params = {"milestone": "BranchCut", "fix_version": fix_version}
        # Release dates
        elif re.search(r"\b(when\s+is|release\s*date|calendar|schedule)\b", msg_lower):
            tool_name = "calendar_get_release_dates"
            tool_params = {}
        # More Info / Needs Info items
        elif re.search(r"\b(more\s*info|needs?\s*info|waiting\s*for\s*info)\b", msg_lower):
            tool_name = "jira_get_moreinfo_items"
            tool_params = {"fix_version": fix_version}
        # Action items / open items
        elif re.search(r"\b(action\s*items?|open\s*items?|who\s+has|assignee\s+workload)\b", msg_lower):
            tool_name = "jira_get_action_items_by_assignee"
            tool_params = {"fix_version": fix_version}
        # Jenkins pipeline runs / builds
        elif re.search(
            r"\b(pipeline\s*runs?|builds?\s*(for|of|history)|last\s*\d+\s*(builds?|runs?|pipelines?)|show\s*(me\s*)?(builds?|runs?|pipelines?))\b",
            msg_lower,
        ):
            tool_name = "jenkins_get_job_builds"
            # Try to extract job name from the query
            job_match = re.search(r"\b(?:of|for)\s+(\S+)", msg_lower)
            if job_match:
                tool_params = {"job_name": job_match.group(1)}
            else:
                tool_params = {}
        # Jenkins golden regression
        elif re.search(r"\b(golden\s*regression)\b", msg_lower):
            tool_name = "jenkins_get_golden_regression"
            tool_params = {}
        # Jenkins TFA
        elif re.search(r"\b(tfa|test\s*failure\s*analysis|why\s*(did|does)\s*.*fail)\b", msg_lower):
            tool_name = "jenkins_get_test_failure_analysis"
            tool_params = {}
        # Jenkins pipeline list
        elif re.search(r"\b(list\s*(all\s*)?pipelines?|pipeline\s*status|all\s*pipelines?)\b", msg_lower):
            tool_name = "jenkins_get_pipelines"
            tool_params = {}

        if not tool_name:
            return None  # Fall through to LLM

        print(f"[PreRoute] Matched '{tool_name}' for query: {message[:50]}", file=sys.stderr)

        try:
            # Call the tool directly
            result = await self._call_tool_directly(agent, tool_name, tool_params)
            if result:
                _t_total = round(time.time() - _t_start, 2)
                print(f"[PreRoute] Tool {tool_name} completed in {_t_total}s", file=sys.stderr)

                return AgentResponse(
                    content=result,
                    session_id=session_id,
                    agent_name=agent.name if hasattr(agent, "name") else "release_readiness",
                    tools_used=[tool_name],
                    metadata={
                        "release": f"R{release}",
                        "pre_routed": True,
                        "response_time_seconds": _t_total,
                    },
                )
        except Exception as e:
            print(f"[PreRoute] Error: {e}", file=sys.stderr)
            logger.error("[PreRoute] Error calling tool %s: %s", tool_name, e)

        return None  # Fall through to LLM

    async def _call_tool_directly(self, agent: Any, tool_name: str, tool_params: dict) -> Optional[str]:
        """Call an MCP tool directly and extract its display field."""
        import json

        if not hasattr(agent, "tools") or not agent.tools:
            return None

        # Collect all available tools from both individual Tool objects and MCPToolsets
        all_tools = []
        for item in agent.tools:
            if hasattr(item, "get_tools"):
                # MCPToolset - enumerate its tools
                tools = await item.get_tools()
                all_tools.extend(tools)
            elif hasattr(item, "name"):
                # Individual Tool object (from filtered tools)
                all_tools.append(item)

        for tool in all_tools:
            if tool.name == tool_name:
                result = await tool.run_async(args=tool_params, tool_context=None)

                # Extract display from MCP response format
                if isinstance(result, dict):
                    # MCP format: {content: [{type: "text", text: "JSON"}]}
                    if "content" in result and isinstance(result["content"], list):
                        for part in result["content"]:
                            if isinstance(part, dict) and "text" in part:
                                try:
                                    inner = json.loads(part["text"])
                                    if isinstance(inner, dict) and "display" in inner:
                                        return inner["display"]
                                    if isinstance(inner, dict):
                                        return self._format_dict_as_display(inner, tool_name)
                                except json.JSONDecodeError:
                                    return part["text"]
                    # Direct display field
                    if "display" in result:
                        return result["display"]

                return str(result)

        return None

    def _format_dict_as_display(self, data: dict, tool_name: str) -> str:
        """Format a dict response as readable display when no display field exists."""
        if "error" in data:
            return f"**Error:** {data['error']}"

        lines = []

        # Handle common response structures
        if "rrs_score" in data:  # Release readiness
            status = data.get("status", "unknown").upper()
            emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(status, "⚪")
            lines.append(
                f"## {emoji} Release {data.get('release', '')} Status: **{status}** ({data.get('rrs_score', 0)}%)"
            )
            lines.append(
                f"\n**Open Bugs:** {data.get('open_bugs', 0)} | **Open Stories:** {data.get('open_stories', 0)}"
            )
        elif "blockers" in data:  # Critical bugs
            lines.append(f"## 🚨 Critical/Blocker Bugs for {data.get('release', '')}")
            lines.append(f"\n**Total:** {data.get('count', 0)}")
            blockers = data.get("blockers", [])
            if blockers:
                lines.append("\n| Key | Summary | Priority | Assignee |")
                lines.append("|-----|---------|----------|----------|")
                for b in blockers[:10]:
                    summary = b.get("summary", "")[:50]
                    lines.append(
                        f"| {b.get('key', '')} | {summary} | {b.get('priority', '')} | {b.get('assignee', '')} |"
                    )
            else:
                lines.append("\n✅ No critical blockers found!")
        elif "commits" in data:  # GitHub commits
            total = data.get(
                "total_commits", data.get("after_branch_cut", {}).get("count", len(data.get("commits", [])))
            )
            repo = data.get("repo", "")
            release = data.get("release", "")

            # Check if it's after branch cut response
            if "after_branch_cut" in data:
                after_data = data["after_branch_cut"]
                count = after_data.get("count", 0)
                lines.append(f"## ⚠️ Commits After Branch Cut for {release}")
                lines.append(f"\n**Repo:** {repo} | **Count:** {count}")
                if count > 0:
                    lines.append("\n⚠️ These commits were made after branch cut and may need review.")
                    commits = after_data.get("commits", [])
                    if commits:
                        lines.append("\n| Date | Author | Message |")
                        lines.append("|------|--------|---------|")
                        for c in commits[:10]:
                            date = c.get("date", "")[:10]
                            msg = c.get("message", "")[:50]
                            lines.append(f"| {date} | {c.get('author', '')} | {msg} |")
                else:
                    lines.append("\n✅ No commits after branch cut - release is clean!")
            else:
                lines.append(f"## 📝 Commits for {release}")
                lines.append(f"\n**Repo:** {repo} | **Total:** {total}")
        else:
            # Generic formatting
            for key, value in list(data.items())[:5]:
                if key not in ("source", "metadata"):
                    lines.append(f"**{key}:** {value}")

        return "\n".join(lines)

    async def _auto_call_tool(
        self,
        agent: Any,
        message: str,
        session_id: str,
        release_context: str = None,
    ) -> Optional[str]:
        """
        Auto-call the appropriate tool based on query patterns.

        This is a fallback when the LLM fails to call tools directly.
        Uses pattern matching to determine which MCP tool to call.
        """
        try:
            msg_lower = message.lower()

            # Extract release version from message
            release_match = re.search(r"\br?(\d{3})\b", message, re.IGNORECASE)
            release = release_match.group(1) if release_match else (release_context or DEFAULT_RELEASE).replace("R", "")
            fix_version = f"{release}.0.0"

            # Determine which tool to call based on patterns
            tool_name = None
            tool_params = {}

            if re.search(
                r"\b(green|red|yellow|rrs|readiness|release\s*status|status\s+of\s+r?\d{3}|r?\d{3}\s+(status|doing|ready|ship))\b",
                msg_lower,
            ):
                tool_name = "jira_get_release_readiness_score"
                tool_params = {"fix_version": fix_version}
            elif re.search(r"\birr\b", msg_lower):
                tool_name = "jira_get_milestone_status"
                tool_params = {"milestone": "IRR", "fix_version": fix_version}
            elif re.search(r"\bbranch.?cut\s*(status|completion)\b", msg_lower):
                tool_name = "jira_get_milestone_status"
                tool_params = {"milestone": "BranchCut", "fix_version": fix_version}
            elif re.search(r"\b(when\s+is|date|calendar|schedule)\b", msg_lower):
                tool_name = "calendar_get_release_dates"
                tool_params = {}
            elif re.search(r"\b(critical|blocker|p0|p1)\s*(bug|issue)?\b", msg_lower):
                tool_name = "jira_get_critical_bugs"
                tool_params = {"fix_version": fix_version}
            elif re.search(r"\b(action\s*items?|open\s*items?|who\s+has|assignee)\b", msg_lower):
                tool_name = "jira_get_action_items_by_assignee"
                tool_params = {"fix_version": fix_version}
            elif re.search(r"\b(escalation|customer\s*bug)\b", msg_lower):
                tool_name = "jira_get_escalations_summary"
                tool_params = {}
            elif re.search(r"\b(commit|github)\b", msg_lower):
                tool_name = "github_get_commits"
                tool_params = {}

            if not tool_name:
                logger.warning("[AutoTool] No matching tool pattern for: %s", message[:50])
                return None

            logger.info("[AutoTool] Calling %s with params %s", tool_name, tool_params)

            # Find the tool in the agent's toolsets (handles both MCPToolsets and individual Tools)
            if hasattr(agent, "tools") and agent.tools:
                all_tools = []
                for item in agent.tools:
                    if hasattr(item, "get_tools"):
                        tools = await item.get_tools()
                        all_tools.extend(tools)
                    elif hasattr(item, "name"):
                        all_tools.append(item)

                for tool in all_tools:
                    if tool.name == tool_name:
                        result = await tool.run_async(args=tool_params, tool_context=None)

                        # MCP tools return {content, structuredContent, isError}
                        if isinstance(result, dict):
                            if "content" in result:
                                content_list = result["content"]
                                if isinstance(content_list, list) and content_list:
                                    text_parts = []
                                    for part in content_list:
                                        if isinstance(part, dict) and "text" in part:
                                            text_parts.append(part["text"])
                                        elif hasattr(part, "text"):
                                            text_parts.append(part.text)
                                    if text_parts:
                                        return "\n".join(text_parts)
                                elif isinstance(content_list, str):
                                    return content_list
                            if "display" in result:
                                return result["display"]
                            elif "result" in result:
                                return str(result["result"])
                        return str(result)

            logger.warning("[AutoTool] Tool %s not found in agent's toolsets", tool_name)
            return None

        except Exception as e:
            logger.error("[AutoTool] Error calling tool: %s", e)
            import traceback

            traceback.print_exc()
            return None

    def _get_greeting_response(self) -> str:
        """Return a friendly greeting response."""
        return """Hi! I'm your Agentic Insights Portal AI Assistant. I can help you with:

• **Release Status** - Overall health and progress
• **Bugs** - P0/P1 blockers, regressions, open issues
• **Stories** - Feature progress and status
• **Milestones** - IRR, Branch Cut, Final Build dates
• **Documentation** - Product guides and how-tos

What would you like to know?"""

    def _extract_from_data(self, data: Dict[str, Any], keys: list = None, extract_type: str = "components") -> list:
        """Delegate to CoreUtils.extract_from_data()"""
        return self._utils.extract_from_data(data, keys, extract_type)

    def _get_filters(
        self, data: Dict[str, Any], params: Dict[str, Any], component_keys: list = None, items_for_assignee: list = None
    ) -> Dict[str, Any]:
        """Delegate to CoreUtils.get_filters()"""
        return self._utils.get_filters(data, params, component_keys, items_for_assignee)

    def _build_header(
        self, emoji: str, title: str, release: str = None, filter_val: str = None, count: int = None, suffix: str = None
    ) -> str:
        """Delegate to CoreUtils.build_header()"""
        return self._utils.build_header(emoji, title, release, filter_val, count, suffix)

    def _filter_by_component(self, items: list, component: str, field: str = "component") -> list:
        """Delegate to CoreUtils.filter_by_component()"""
        return self._utils.filter_by_component(items, component, field)

    def _format_items_list(
        self, items: list, format_fn: callable, limit: int = 10, empty_msg: str = None, filter_name: str = None
    ) -> list:
        """Delegate to CoreUtils.format_items_list()"""
        return self._utils.format_items_list(items, format_fn, limit, empty_msg, filter_name)

    def _format_jira_item(self, item: Dict[str, Any], style: str = "compact", fields: list = None) -> str:
        """Delegate to CoreUtils.format_jira_item()"""
        return self._utils.format_jira_item(item, style, fields)

    def _get_status_emoji(self, score: float, thresholds: tuple = (80, 50)) -> tuple:
        """Delegate to CoreUtils.get_status_emoji()"""
        return self._utils.get_status_emoji(score, thresholds)

    def _detect_direct_intent(self, message: str, release_context: str = None) -> Optional[Dict[str, Any]]:
        """
        Detect query intents with intelligent parameter extraction.

        Uses unified extract() for:
        - Component filters ("in YOUR_PRODUCT component")
        - Qualifiers ("most", "top 5", "least")
        - Assignee filters ("assigned to John")
        - Release extraction

        Returns:
            Dict with 'tool_name', 'params', and optional 'post_process' if intent detected.
        """
        msg_lower = message.lower().strip()
        words = msg_lower.split()

        # Extract contextual parameters using unified extract()
        release = self.extract(message, "release", fallback=release_context or DEFAULT_RELEASE)

        # Extract filters and qualifiers using unified extract()
        # Available components for filtering
        available_components = ["YOUR_PRODUCT"]
        component_filter = self.extract(message, "component", available_items=available_components)
        qualifiers = self.extract(message, "qualifier", fallback={})
        assignee_filter = self.extract(message, "assignee")

        # "Why is RRS X%" questions - need to explain the score calculation
        # Also handle "why is release readiness score X%" without the percentage number
        if (
            re.search(r"\bwhy\b.*(rrs|readiness|score|health)", msg_lower)
            or re.search(r"\d+%?.*(rrs|readiness|score).*\bwhy\b", msg_lower)
            or re.search(r"(improve|increase|raise).*(rrs|readiness|score)", msg_lower)
        ):
            return {"tool_name": "explain_release_readiness_score", "params": {"release_id": release}}

        # Resolution Progress queries - we have this capability!
        resolution_patterns = [
            r"\bresolution\s*progress\b",
            r"\bbug.*story.*resolution\b",
            r"\bresolved\b.*\birr\b",
            r"\birr\b.*\bfinal\s*build\b",
            r"\bprogress\b.*\birr\b",
            r"\bhow\s+did\s+(bugs?|stories?|resolution)\b",
            r"\bresolution\s*(trend|analysis)\b",
        ]
        if any(re.search(p, msg_lower) for p in resolution_patterns):
            return {"tool_name": "get_resolution_progress", "params": {"release_id": release}}

        # ========== HIGH-PRIORITY PATTERNS (checked before word count limit) ==========
        # These patterns should be matched even for longer queries

        # Critical/blocked bugs query - with component support
        # Matches: "show critical bugs", "show me critical bugs blocking", "do we have blocker bugs", "critical/blocked bugs"
        if (
            re.search(
                r"(show|list|what\s+are|do\s+we\s+have|any)\s*(me\s+)?(the\s+)?(critical|p0|p1|blocker|blocked)\s*(bugs?|issues?)?",
                msg_lower,
            )
            or re.search(r"(critical|p0|p1|blocker|blocked)[/\s]*(bugs?|issues?)", msg_lower)
            or re.search(r"(bugs?|issues?)\s*(blocking|that\s+block)", msg_lower)
        ):
            params = {"project_key": "YOUR_PRODUCT"}
            if component_filter:
                params["component"] = component_filter
            result = {"tool_name": "jira_get_critical_bugs", "params": params}
            if qualifiers:
                result["post_process"] = qualifiers
            return result

        # MoreInfo bugs query - reuse release-readiness data and filter for MoreInfo status
        # This is more efficient than a separate JIRA query and uses the same data as the dashboard
        # Matches: "bugs with moreinfo", "do we have moreinfo bugs", "more info items"
        if re.search(r"(moreinfo|more\s*info)\s*(bugs?|items?|issues?)?", msg_lower) or re.search(
            r"(bugs?|items?|issues?)\s*(with|in|having)\s*(moreinfo|more\s*info)", msg_lower
        ):
            return {"tool_name": "jira_get_moreinfo_items", "params": {"release_id": release}}

        # Milestone/timeline/dates queries - also high priority
        # Matches: "milestone dates", "when is code freeze", "release date", "key dates"
        if (
            re.search(r"^(show|what|list)\s*(the\s+)?(timeline|dates|schedule|milestones?)", msg_lower)
            or re.search(r"\b(milestone|timeline)\s*(dates?|schedule)?", msg_lower)
            or re.search(r"dates?\s*(for|of)\s*r?\d{3}", msg_lower)
            or re.search(r"when\s+is\s+(the\s+)?(code\s*freeze|branch\s*cut|release|irr|final)", msg_lower)
            or re.search(r"(code\s*freeze|release\s*date|key\s*dates?)", msg_lower)
        ):
            return {"tool_name": "calendar_get_release_dates", "params": {"release_id": release}}

        # ========== COMPLEXITY CHECKS ==========
        # Skip direct routing for other complex queries (let LLM reason)
        # Note: "why" about RRS/readiness is handled above, so we only skip for other "why" queries
        complex_indicators = [
            r"\bcompare\b",
            r"\bover\s+time\b",
            r"\bexplain\b(?!.*readiness)",  # Skip "explain" unless about readiness
        ]
        # Don't skip if it's a "why" about RRS (already handled above)
        if not re.search(r"\bwhy\b.*(rrs|readiness|score|health)", msg_lower):
            if any(re.search(p, msg_lower) for p in complex_indicators):
                logger.info("Complex query detected, routing to LLM: %s", message[:50])
                return None

        # Only route directly for SHORT, SIMPLE queries (< 12 words for remaining patterns)
        if len(words) > 12:
            return None

        # Simple escalation query
        if re.search(r"^(show|list|what\s+are)\s*(the\s+)?(escalation|ehf|imf)", msg_lower):
            return {"tool_name": "jira_get_escalations_summary", "params": {"project_key": "YOUR_PRODUCT"}}

        # Simple RRS query
        if re.search(r"^what\s+(is|are)\s+(the\s+)?(rrs|readiness\s*score|release\s*score)", msg_lower):
            return {"tool_name": "get_rrs", "params": {"release_id": release}}

        # Release status query - matches various ways to ask about status
        # "is R134 green?", "what's the release status?", "current release status"
        if (
            re.search(r"^is\s+(release\s+)?r?\d+\s+(green|red|yellow|ready)", msg_lower)
            or re.search(r"^is\s+(the\s+)?release\s+(green|red|yellow|ready)", msg_lower)
            or re.search(r"(what.?s|show|current|release)\s*(the\s+)?(release\s+)?status", msg_lower)
        ):
            return {"tool_name": "calculate_release_readiness_score", "params": {"release_id": release}}

        # Milestone-specific status queries - with component support
        if re.search(r"\birr\b.*(status|ready|blocking)", msg_lower) or re.search(
            r"^(show|what|how)\s*(is\s+)?(the\s+)?irr", msg_lower
        ):
            params = {"release_id": release}
            if component_filter:
                params["component"] = component_filter
            return {"tool_name": "get_irr_status", "params": params}

        if re.search(r"\bbranch\s*cut\b.*(status|ready|blocking)", msg_lower) or re.search(
            r"^(show|what|how)\s*(is\s+)?(the\s+)?branch\s*cut", msg_lower
        ):
            params = {"release_id": release}
            if component_filter:
                params["component"] = component_filter
            return {"tool_name": "get_branch_cut_status", "params": params}

        if re.search(r"\bfinal\s*build\b.*(status|ready|blocking)", msg_lower) or re.search(
            r"^(show|what|how)\s*(is\s+)?(the\s+)?final\s*build", msg_lower
        ):
            params = {"release_id": release}
            if component_filter:
                params["component"] = component_filter
            return {"tool_name": "get_final_build_status", "params": params}

        # Regression bugs - with component support
        if re.search(r"\bregression\s*(bugs?|issues?)?", msg_lower):
            fix_version = release.replace("R", "") + ".0"
            params = {"project_key": "YOUR_PRODUCT", "fix_version": fix_version}
            if component_filter:
                params["component"] = component_filter
            result = {"tool_name": "jira_get_regression_bugs", "params": params}
            if qualifiers:
                result["post_process"] = qualifiers
            return result

        # Action items / workload - with component and qualifier support
        if re.search(r"\b(action\s*items?|workload|assignee|who\s+(has|is\s+working)|open\s+items?)", msg_lower):
            fix_version = release.replace("R", "") + ".0"
            params = {"project_key": "YOUR_PRODUCT", "fix_version": fix_version}

            # Add component filter if detected
            if component_filter:
                params["component"] = component_filter

            # Add assignee filter if detected
            if assignee_filter:
                params["assignee"] = assignee_filter

            result = {"tool_name": "jira_get_action_items", "params": params}

            # Add post-processing instructions for qualifiers
            if qualifiers:
                result["post_process"] = qualifiers

            return result

        # Test execution
        if re.search(r"\b(test\s*execution|test\s*results?|pass\s*rate|testrail)", msg_lower):
            return {"tool_name": "get_test_execution", "params": {"release_id": release}}

        # Untested cases
        if re.search(r"\buntested\b", msg_lower):
            return {"tool_name": "get_untested_cases", "params": {"release_id": release}}

        # Manual execution
        if re.search(r"\bmanual\s*(execution|testing|tests?)", msg_lower):
            return {"tool_name": "get_manual_execution", "params": {"release_id": release}}

        # Pipeline / CI
        if re.search(r"\b(pipeline|ci|jenkins|build\s*status)", msg_lower):
            return {"tool_name": "get_pipeline_status", "params": {}}

        # Golden regression
        if re.search(r"\bgolden\s*regression", msg_lower):
            return {"tool_name": "get_golden_regression", "params": {}}

        # Code commits - matches "commits after/before branch cut", "any commits", "code commits", "git commits"
        if (
            re.search(r"\b(code\s*commits?|git\s*commits?|github|commit\s*activity)", msg_lower)
            or re.search(r"(any\s+)?commits?\s*(after|before|since|following)", msg_lower)
            or re.search(r"commits?\s+.*(branch\s*cut|repo)", msg_lower)
        ):
            params = {"release_id": release}
            stop_words = {"the", "a", "an", "this", "that", "any", "some", "all"}

            # Extract repo name from query: "for device-classification repo"
            repo_match = re.search(r"\b(?:for|in|from)\s+([\w-]+)\s*(?:repo|repository)?", msg_lower)
            if repo_match and repo_match.group(1) not in stop_words:
                params["repo"] = repo_match.group(1)

            # Also try: "device-classification repo" pattern
            if "repo" not in params:
                repo_match2 = re.search(r"\b([\w-]+)\s+repo(?:sitory)?", msg_lower)
                if repo_match2 and repo_match2.group(1) not in stop_words:
                    params["repo"] = repo_match2.group(1)

            return {"tool_name": "get_code_commits", "params": params}

        # No simple pattern - let the LLM decide
        return None

    def _detect_unsupported_query(self, message: str, release_context: str = None) -> Optional[str]:
        """
        Detect queries that require capabilities we don't have.
        Returns a helpful response explaining what we can do instead.

        Note: We support a wide range of queries now. Only flag truly unsupported ones.
        """
        msg_lower = message.lower()
        release = release_context or DEFAULT_RELEASE

        # Cross-release comparison queries
        if re.search(r"\bcompare\b.*\breleases?\b|\bvs\.?\b|\bversus\b", msg_lower):
            return f"""## 📊 Cross-Release Comparison

I can show data for one release at a time. For comparisons:
1. Ask about one release, then
2. Ask about the other release

Currently selected: **{release}**

What would you like to know about it?"""

        # Very vague queries
        if re.search(r"^(help|what can you do|capabilities)$", msg_lower.strip()):
            return f"""## 🤖 Release Readiness Assistant

I can help you with:

**📊 Release Health**
- Release Readiness Score (RRS)
- Bug/Story status
- Resolution progress

**📅 Milestones**
- IRR, Branch Cut, Final Build status
- Timeline and dates

**🐛 Issues**
- Critical bugs (P0/P1)
- Regressions
- Customer escalations (EHF/IMF)

**✅ Testing**
- Test execution status
- Untested cases
- Manual execution

**🔧 CI/CD**
- Pipeline health
- Golden regression results

**💻 Code**
- Commit activity

Try asking: "Is {release} green?" or "Show me critical bugs" or "What's the RRS?"""

        return None

    def _detect_multi_tool_query(self, message: str, release_context: str = None) -> Optional[list]:
        """
        Detect queries that need multiple tools to answer comprehensively.
        Returns a list of tool configs if multi-tool query detected, None otherwise.
        """
        msg_lower = message.lower()
        release = release_context or DEFAULT_RELEASE
        fix_version = release.replace("R", "") + ".0"

        # Comprehensive release overview / executive summary
        if re.search(r"\b(full|complete|comprehensive|executive)\s*(summary|overview|status|report)", msg_lower):
            return [
                {"tool": "get_rrs", "params": {"release_id": release}, "label": "Release Readiness Score"},
                {
                    "tool": "jira_get_bugs_summary",
                    "params": {"project_key": "YOUR_PRODUCT", "fix_version": fix_version},
                    "label": "Bug Status",
                },
                {"tool": "jira_get_critical_bugs", "params": {"project_key": "YOUR_PRODUCT"}, "label": "Critical Bugs"},
                {"tool": "calendar_get_release_dates", "params": {"release_id": release}, "label": "Timeline"},
            ]

        # "Ready to ship" / go-no-go assessment
        if re.search(
            r"\b(ready\s+to\s+ship|go.?no.?go|should\s+we\s+(ship|release)|can\s+we\s+(ship|release))", msg_lower
        ):
            return [
                {"tool": "get_rrs", "params": {"release_id": release}, "label": "Release Readiness Score"},
                {"tool": "jira_get_critical_bugs", "params": {"project_key": "YOUR_PRODUCT"}, "label": "Critical Bugs"},
                {"tool": "jira_get_escalations_summary", "params": {"project_key": "YOUR_PRODUCT"}, "label": "Escalations"},
            ]

        # Quality assessment
        if re.search(r"\b(quality|testing)\s*(status|summary|overview|report)", msg_lower):
            return [
                {"tool": "get_rrs", "params": {"release_id": release}, "label": "Overall Score"},
                {
                    "tool": "jira_get_regression_bugs",
                    "params": {"project_key": "YOUR_PRODUCT", "fix_version": fix_version},
                    "label": "Regressions",
                },
                {"tool": "get_resolution_progress", "params": {"release_id": release}, "label": "Resolution Progress"},
            ]

        # Risks / blockers
        if (
            re.search(r"\b(risk|blocker|blocking|concern|issue)s?\s*(summary|overview|report)?", msg_lower)
            and len(msg_lower.split()) < 6
        ):
            return [
                {"tool": "jira_get_critical_bugs", "params": {"project_key": "YOUR_PRODUCT"}, "label": "Critical Bugs"},
                {"tool": "jira_get_escalations_summary", "params": {"project_key": "YOUR_PRODUCT"}, "label": "Escalations"},
                {"tool": "get_final_build_status", "params": {"release_id": release}, "label": "Final Build Blockers"},
            ]

        # "What's left" / remaining work
        if re.search(r"\b(what'?s?\s+left|remaining|still\s+(to\s+do|open|pending))", msg_lower):
            return [
                {
                    "tool": "jira_get_bugs_summary",
                    "params": {"project_key": "YOUR_PRODUCT", "fix_version": fix_version},
                    "label": "Open Items",
                },
                {
                    "tool": "jira_get_action_items",
                    "params": {"project_key": "YOUR_PRODUCT", "fix_version": fix_version},
                    "label": "Action Items",
                },
            ]

        return None

    async def _execute_multi_tool_query(self, tools: list, release_context: str = None) -> str:
        """
        Execute multiple tools and combine their outputs into a comprehensive response.
        """
        results = []

        for tool_config in tools:
            tool_name = tool_config["tool"]
            params = tool_config["params"]
            label = tool_config.get("label", tool_name)

            try:
                result = await self._execute_tool_call(tool_name, params)
                results.append({"label": label, "content": result, "success": True})
            except Exception as e:
                logger.warning("Multi-tool: {tool_name} failed: %s", e)
                results.append({"label": label, "content": f"Unable to fetch {label}", "success": False})

        # Combine results with analysis
        lines = [
            "## 📊 Comprehensive Release Analysis",
            "",
        ]

        for r in results:
            if r["success"]:
                lines.append(r["content"])
                lines.append("")
                lines.append("---")
                lines.append("")

        # Add integrated summary
        lines.append("## 💡 Summary")
        lines.append("")

        # Analyze the combined data for insights
        combined = "\n".join([r["content"] for r in results if r["success"]])

        if "🔴" in combined or "RED" in combined:
            lines.append("⚠️ **Attention Required:** Some areas show red status and need immediate attention.")
        elif "⚠️" in combined or "YELLOW" in combined:
            lines.append("📋 **Review Needed:** Release is progressing but has areas requiring attention.")
        else:
            lines.append("✅ **Looking Good:** Release appears healthy across checked metrics.")

        # Count specific issues if found
        if "critical bugs" in combined.lower() and "No critical bugs" not in combined:
            lines.append("- Critical bugs detected - review before shipping")
        if "escalation" in combined.lower() and "0" not in combined[:100]:
            lines.append("- Customer escalations present - address for release quality")

        return "\n".join(lines)

    async def _execute_cross_agent_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str = None,
    ) -> str:
        """
        Execute a cross-agent communication tool call.

        Dynamically routes to any registered agent via AgentRegistry.
        Features:
        - Dynamic agent discovery (no hardcoding)
        - Session sharing for context continuity
        - Structured response formatting
        - Error handling with details
        """
        try:
            from core.agent_communication import AgentRegistry, query_agent

            query = params.get("query", params.get("question", ""))
            context = params.get("context", None)

            if not query:
                return "Error: No query provided for cross-agent call."

            # Extract agent name from tool name (e.g., "ask_release_readiness_agent" -> "release_readiness")
            # Pattern: ask_{agent_name}_agent
            agent_name = None
            if tool_name.startswith("ask_") and tool_name.endswith("_agent"):
                # Remove "ask_" prefix and "_agent" suffix
                agent_name = tool_name[4:-6]  # "ask_X_agent" -> "X"

            # Try to find agent by name or partial match
            if not agent_name:
                return f"Could not parse agent name from tool: {tool_name}"

            # Check if agent exists in registry
            registered_agents = AgentRegistry.list_agents()
            matched_agent = None

            # Exact match first
            if agent_name in registered_agents:
                matched_agent = agent_name
            else:
                # Partial match (e.g., "release" matches "release_readiness")
                for reg_name in registered_agents:
                    if agent_name in reg_name or reg_name in agent_name:
                        matched_agent = reg_name
                        break

            if not matched_agent:
                return f"Unknown agent: {agent_name}. Available: {', '.join(registered_agents)}"

            # Query the agent
            result = await query_agent(matched_agent, query, context, session_id)

            if result.get("success"):
                response = result.get("response", "No response from agent.")
                agent_name = result.get("agent", "unknown")
                tools_used = result.get("tools_used", [])

                # Format the cross-agent response
                formatted = f"**Response from {agent_name} agent:**\n\n{response}"
                if tools_used:
                    formatted += f"\n\n*Tools used: {', '.join(tools_used)}*"
                return formatted
            else:
                error = result.get("error", "Unknown error")
                attempts = result.get("attempts", 1)
                return f"Cross-agent query failed after {attempts} attempt(s): {error}"

        except Exception as e:
            logger.error("Cross-agent call error: %s", e)
            import traceback

            traceback.print_exc()
            return f"Error in cross-agent communication: {str(e)}"

    def _format_critical_bugs(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format critical bugs response using common helpers."""
        bugs = data.get("critical_bugs", [])

        # Use helper to get filters dynamically
        filters = self._get_filters({"bugs": bugs}, params, component_keys=["bugs"])
        bugs = self._filter_by_component(bugs, filters["component"])

        # Build response using helpers
        header = self._build_header("🔴", "Critical Bugs", filter_val=filters["component"], count=len(bugs))

        if not bugs:
            empty_msg = "✅ **No critical bugs found!** The release is looking good."
            if filters["component"]:
                empty_msg = f"✅ **No critical bugs found for {filters['component']}!**"
            return empty_msg

        lines = [header, ""]
        lines.extend(self._format_items_list(bugs, lambda b: self._format_jira_item(b, style="detailed"), limit=10))

        return "\n".join(lines)

    def _format_bugs_list(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format bugs list response using common helpers."""
        bugs = data.get("bugs", [])
        count = data.get("count", len(bugs))

        header = self._build_header("🐛", "Bugs", count=count)

        if not bugs:
            return "✅ **No bugs found** matching the criteria."

        lines = [header, ""]
        lines.extend(self._format_items_list(bugs, lambda b: self._format_jira_item(b, style="compact"), limit=15))

        return "\n".join(lines)

    def _format_regression_bugs(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format regression bugs response using common helpers."""
        bugs = data.get("regression_bugs", [])

        # Use helper to get filters dynamically
        filters = self._get_filters({"bugs": bugs}, params, component_keys=["bugs"])
        bugs = self._filter_by_component(bugs, filters["component"])

        # Build response using helpers
        header = self._build_header("🔄", "Regression Bugs", filter_val=filters["component"], count=len(bugs))

        if not bugs:
            empty_msg = "✅ **No regression bugs found!** Great quality!"
            if filters["component"]:
                empty_msg = f"✅ **No regression bugs found for {filters['component']}!** Great quality!"
            return empty_msg

        lines = [header, ""]
        lines.extend(
            self._format_items_list(
                bugs,
                lambda b: self._format_jira_item(b, style="minimal") + f" | {b.get('assignee', 'Unassigned')}",
                limit=10,
            )
        )

        return "\n".join(lines)

    def _format_escalations(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format escalations response using common helpers."""
        result = data.get("result", data)

        total = result.get("total", 0)
        by_status = result.get("by_status", {})
        by_priority = result.get("by_priority", {})
        escalations = result.get("escalations", [])

        blocker_count = by_priority.get("Blocker", 0)
        critical_count = by_priority.get("Critical", 0)

        # Determine status based on blockers
        if blocker_count > 0:
            status_emoji, status_text = "🔴", f"{blocker_count} Blocker escalations need immediate attention"
        elif total > 50:
            status_emoji, status_text = "🟡", f"{total} active escalations - monitor closely"
        else:
            status_emoji, status_text = "🟢", "Escalations under control"

        lines = [
            self._build_header(status_emoji, "Escalations Summary"),
            "",
            f"**Status:** {status_text}",
            "",
            "### Overview",
            "",
            "| Priority | Count |",
            "|----------|-------|",
            f"| 🔴 Blocker | {blocker_count} |",
            f"| 🟠 Critical | {critical_count} |",
            f"| **Total Active** | **{total}** |",
            "",
        ]

        # Show by status
        if by_status:
            lines.extend(["### By Status", ""])
            for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
                lines.append(f"- **{status}:** {count}")
            lines.append("")

        # Show top escalations (prioritize blockers)
        if escalations:
            blockers = [e for e in escalations if e.get("priority") == "Blocker"]
            show_list = blockers[:5] if blockers else escalations[:5]

            lines.append("### Top Escalations" + (" (Blockers)" if blockers else ""))
            lines.append("")

            def format_escalation(esc):
                key = esc.get("key", "N/A")
                summary_text = (esc.get("summary") or "")[:50]
                priority = esc.get("priority", "Unknown")
                assignee = esc.get("assignee", "Unassigned")
                url = esc.get("url", "#")
                icon = "🔴" if priority == "Blocker" else "🟠"
                return f"- {icon} [{key}]({url}) - {summary_text}\n  - Assignee: **{assignee}**"

            lines.extend(self._format_items_list(show_list, format_escalation, limit=5))
            lines.append("")

        return "\n".join(lines)

    def _format_search_results(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """
        Format search results response intelligently based on query type.

        The formatter adapts based on the _query_type parameter:
        - "moreinfo": Format as MoreInfo items with reporter info
        - "blocked": Format as blocked items
        - default: Generic search results
        """
        issues = data.get("issues", [])
        count = data.get("count", len(issues))
        query_type = params.get("_query_type", "generic")

        if not issues:
            if query_type == "moreinfo":
                return "✅ **No items in MoreInfo status!** All items have the information needed to proceed."
            return "✅ No issues found matching your search criteria."

        # MoreInfo query - special formatting with reporter grouping
        if query_type == "moreinfo":
            lines = [f"## 📋 MoreInfo Items ({count} total)", ""]
            lines.append("Items awaiting additional information from reporters:")
            lines.append("")

            # Group by reporter
            by_reporter = {}
            for issue in issues:
                reporter = issue.get("reporter", "Unknown")
                if reporter not in by_reporter:
                    by_reporter[reporter] = []
                by_reporter[reporter].append(issue)

            lines.append("| Reporter | Items | Action |")
            lines.append("|----------|-------|--------|")
            for reporter, items in sorted(by_reporter.items(), key=lambda x: len(x[1]), reverse=True):
                lines.append(f"| {reporter} | {len(items)} | Follow up for details |")

            lines.append("")
            lines.append("### Item Details")
            lines.append("")

            for issue in issues[:15]:
                key = issue.get("key", "N/A")
                summary = issue.get("summary", "")[:45]
                assignee = issue.get("assignee", "Unassigned")
                reporter = issue.get("reporter", "Unknown")
                issue_type = issue.get("issuetype", issue.get("type", "Bug"))

                type_emoji = "🐛" if "bug" in str(issue_type).lower() else "📝"
                lines.append(f"- {type_emoji} **{key}**: {summary}")
                lines.append(f"  - Assignee: {assignee} | Reporter: {reporter}")
                lines.append("")

            if count > 15:
                lines.append(f"*...and {count - 15} more items*")

            lines.extend(
                [
                    "",
                    "### Recommended Actions",
                    "1. Contact reporters to provide the missing information",
                    "2. Set deadlines for information requests",
                ]
            )
            return "\n".join(lines)

        # Default generic search results
        lines = [f"## 🔍 Search Results ({count} issues)", ""]

        for issue in issues[:15]:
            key = issue.get("key", "N/A")
            summary = issue.get("summary", "")[:50]
            status = issue.get("status", "Unknown")
            assignee = issue.get("assignee", "Unassigned")
            priority = issue.get("priority", "")

            priority_emoji = (
                "🔴" if priority in ["Blocker", "Critical"] else "🟠" if priority in ["Major", "High"] else "🟢"
            )
            lines.append(f"- {priority_emoji} **{key}**: {summary}")
            lines.append(f"  - Status: {status} | Assignee: {assignee}")

        if count > 15:
            lines.append(f"\n*...and {count - 15} more issues*")

        return "\n".join(lines)

    def _format_release_dates(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format release dates/milestones response."""
        milestones = data.get("milestones", [])
        release = params.get("release_id", params.get("release", "Current"))

        lines = [f"## 📅 Release {release} Timeline", ""]

        if milestones:
            # Handle both list and dict formats
            if isinstance(milestones, list):
                for m in milestones:
                    if isinstance(m, dict):
                        name = m.get("name", m.get("milestone", "Unknown"))
                        date = m.get("date", m.get("target_date", "TBD"))
                        lines.append(f"- **{name}:** {date}")
                    else:
                        lines.append(f"- {m}")
            elif isinstance(milestones, dict):
                for name, date in milestones.items():
                    lines.append(f"- **{name}:** {date}")
        else:
            lines.append("No milestone dates available for this release.")

        return "\n".join(lines)

    def _format_action_items(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format action items / assignee workload using common helpers."""
        release = params.get("fix_version", params.get("release", DEFAULT_RELEASE))
        if release and "." in str(release):
            release = f"R{str(release).split('.')[0]}"

        post_process = params.get("_post_process", {})
        qualifier = post_process.get("qualifier")
        limit = post_process.get("limit", 10)
        sort_order = post_process.get("sort", "desc")

        # Get components data and collect all items for assignee extraction
        components_data = data.get("componentsData", {})
        all_items = []
        for comp_data in components_data.values():
            all_items.extend(comp_data.get("issues", []))

        # Use helper for filters with assignee support
        filters = self._get_filters(data, params, component_keys=["componentsData"], items_for_assignee=all_items)
        component_filter = filters["component"]
        assignee_filter = filters["assignee"]

        blockers = data.get("blockersAnalysis", {})
        at_risk = blockers.get("atRiskAssignees", [])
        release_summary = data.get("releaseSummary", {})
        total = release_summary.get("totalOpen", 0)

        # Get open items - try openItems first, then extract from componentsData
        open_items = data.get("openItems", [])
        components_data = data.get("componentsData", {})

        if not open_items and components_data:
            # Extract from componentsData structure (used by /api/jira/release-readiness)
            # If component_filter is specified and matches a key, get only that component's items
            if component_filter:
                component_upper = component_filter.upper()
                if component_upper in components_data:
                    # Direct match - get items from this component only
                    open_items = components_data[component_upper].get("issues", [])
                else:
                    # Try to find matching component by name
                    for comp_name, comp_data in components_data.items():
                        if component_upper in comp_name.upper():
                            open_items.extend(comp_data.get("issues", []))
            else:
                # No filter - get all items from all components
                for comp_name, comp_data in components_data.items():
                    open_items.extend(comp_data.get("issues", []))

        # Apply component filter to items (for openItems that were directly provided)
        if component_filter and data.get("openItems"):
            component_upper = component_filter.upper()
            open_items = [
                item
                for item in open_items
                if component_upper in str(item.get("component", "")).upper()
                or component_upper in str(item.get("components", "")).upper()
                or component_upper in str(item.get("key", "")).upper()
                or "NS CLIENT" in str(item.get("component", "")).upper()  # Handle "NS Client (NSC)" format
            ]

        # Recalculate at_risk from open_items when we have component-filtered data
        # This is needed whether items came from componentsData or were filtered from openItems
        if component_filter and open_items:
            assignee_counts = {}
            for item in open_items:
                assignee = item.get("assignee", "Unassigned")
                if assignee not in assignee_counts:
                    assignee_counts[assignee] = {"assignee": assignee, "openItems": 0, "bugs": 0, "stories": 0}
                assignee_counts[assignee]["openItems"] += 1

                item_type = item.get("issuetype", item.get("type", "")).lower()
                if "bug" in item_type:
                    assignee_counts[assignee]["bugs"] += 1
                else:
                    assignee_counts[assignee]["stories"] += 1

            at_risk = list(assignee_counts.values())
            total = len(open_items)

        # Apply assignee filter
        if assignee_filter:
            assignee_lower = assignee_filter.lower()
            open_items = [item for item in open_items if assignee_lower in str(item.get("assignee", "")).lower()]
            at_risk = [a for a in at_risk if assignee_lower in str(a.get("assignee", "")).lower()]
            total = len(open_items)

        # Sort by open items count
        at_risk = sorted(at_risk, key=lambda x: x.get("openItems", 0), reverse=(sort_order == "desc"))

        # Build header based on query
        header_parts = ["## 📋 Action Items"]
        if component_filter:
            header_parts.append(f"for **{component_filter}** component")
        header_parts.append(f"({release})")

        lines = [" ".join(header_parts)]

        # Handle "most" or "least" qualifier - show only top result with emphasis
        if qualifier in ["most", "least"] and at_risk:
            top_assignee = at_risk[0]
            assignee = top_assignee.get("assignee", "Unassigned")
            open_count = top_assignee.get("openItems", 0)
            bugs = top_assignee.get("bugs", 0)
            stories = top_assignee.get("stories", 0)

            qualifier_text = "most" if qualifier == "most" else "fewest"
            lines.append("")
            lines.append(f"### 🏆 Assignee with {qualifier_text} open items:")
            lines.append("")
            lines.append(f"**{assignee}** has **{open_count} open items**")
            lines.append("")
            lines.append(f"- 🐛 Bugs: {bugs}")
            lines.append(f"- 📝 Stories: {stories}")

            # Show their specific items
            assignee_items = [i for i in open_items if i.get("assignee") == assignee]
            if assignee_items:
                lines.append("")
                lines.append("### Their Open Items:")
                for item in assignee_items[:8]:
                    key = item.get("key", "N/A")
                    summary = item.get("summary", "")[:45]
                    priority = item.get("priority", "")
                    priority_emoji = (
                        "🔴" if priority in ["Blocker", "Critical"] else "🟠" if priority in ["Major", "High"] else "🟢"
                    )
                    lines.append(f"- {priority_emoji} **{key}**: {summary}")

            return "\n".join(lines)

        # Handle "top N" qualifier
        if qualifier == "top" and at_risk:
            at_risk = at_risk[:limit]
            lines.append("")
            lines.append(f"### Top {limit} assignees by open items:")
        elif qualifier == "bottom" and at_risk:
            at_risk = at_risk[:limit]
            lines.append("")
            lines.append(f"### {limit} assignees with fewest items:")

        if total > 0:
            lines.append("")
            lines.append(f"**{total} open items** need attention")
        lines.append("")

        # Show workload as a clean table
        if at_risk:
            lines.append("| Assignee | Items | Bugs | Stories |")
            lines.append("|----------|-------|------|---------|")
            display_count = limit if qualifier in ["top", "bottom"] else len(at_risk)
            for item in at_risk[:display_count]:
                assignee = item.get("assignee", "Unassigned")
                open_count = item.get("openItems", 0)
                bugs = item.get("bugs", 0)
                stories = item.get("stories", 0)
                lines.append(f"| {assignee} | {open_count} | {bugs} | {stories} |")

        # Show individual items if available (limited for component-filtered queries)
        if open_items and not qualifier:
            lines.append("")
            lines.append("### Open Items")
            display_limit = 10 if not component_filter else 15
            for item in open_items[:display_limit]:
                key = item.get("key", "N/A")
                summary = item.get("summary", "")[:45]
                assignee = item.get("assignee", "Unassigned")
                priority = item.get("priority", "")

                priority_emoji = (
                    "🔴" if priority in ["Blocker", "Critical"] else "🟠" if priority in ["Major", "High"] else "🟢"
                )
                lines.append(f"- {priority_emoji} **{key}**: {summary} → {assignee}")

            if len(open_items) > display_limit:
                lines.append(f"\n*...and {len(open_items) - display_limit} more items*")

        if not at_risk and not open_items:
            if component_filter:
                lines.append(f"✅ **All clear!** No open items for {component_filter} component.")
            else:
                lines.append("✅ **All clear!** No action items pending.")

        return "\n".join(lines)

    def _format_release_summary(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format release summary with intelligent analysis."""
        release = params.get("fix_version", params.get("release", DEFAULT_RELEASE))
        if release and "." in str(release):
            release = f"R{str(release).split('.')[0]}"

        release_summary = data.get("releaseSummary", {})
        total_open = release_summary.get("totalOpen", 0)
        open_bugs = release_summary.get("openBugs", 0)
        open_stories = release_summary.get("openStories", 0)

        # Calculate health score for status determination
        health_score = max(0, 100 - (total_open * 3))
        status_emoji, status_text = self._get_status_emoji(health_score)

        # Intelligent assessment with context
        if total_open == 0:
            color = "✅ GREEN"
            assessment = "Excellent! No open items - release is ready to ship."
        elif total_open <= 5 and open_bugs <= 2:
            color = "✅ GREEN"
            assessment = "Release looks healthy with minimal open items."
        elif total_open <= 15:
            color = "⚠️ YELLOW"
            assessment = (
                f"Moderate concern: {open_bugs} bugs need resolution."
                if open_bugs > open_stories
                else f"Some work remaining: {total_open} items to close."
            )
        else:
            color = "🔴 RED"
            assessment = f"High risk: {total_open} open items. Review priorities."

        lines = [
            self._build_header("📋", f"Release {release} Status", suffix=color),
            "",
            f"**Assessment:** {assessment}",
            "",
            "### Current Metrics",
            "| Metric | Count |",
            "|--------|-------|",
            f"| 🐛 Open Bugs | {open_bugs} |",
            f"| 📝 Open Stories | {open_stories} |",
            f"| 📊 **Total Open** | **{total_open}** |",
        ]

        # Add phase info with context
        phase = data.get("phaseCountdown", {})
        release_summary = data.get("releaseSummary", {})
        if phase or release_summary:
            # Try multiple field names for phase
            phase_name = (
                phase.get("deadline_name")
                or phase.get("current_phase")
                or release_summary.get("phaseName")
                or release_summary.get("phase")
                or "Unknown"
            )
            days_remaining = phase.get("days_remaining", release_summary.get("daysRemaining", 0))
            deadline_date = phase.get("deadline_date", "")

            lines.append("")
            lines.append("### Timeline")
            lines.append(f"- **Current Phase:** {phase_name}")
            if deadline_date:
                lines.append(f"- **Next Milestone:** {deadline_date}")
            lines.append(f"- **Days Remaining:** {days_remaining}")

            # Add urgency based on days and open items
            if days_remaining <= 3 and total_open > 10:
                lines.append("")
                lines.append(f"⚠️ **Urgency:** Only {days_remaining} days left with {total_open} items open!")

        # Add insights
        lines.append("")
        lines.append("### Analysis")

        if open_bugs == 0:
            lines.append("- ✅ No open bugs - bug health is excellent")
        elif open_bugs <= 5:
            lines.append(f"- ⚠️ {open_bugs} bugs to fix - manageable if prioritized")
        else:
            lines.append(f"- 🔴 {open_bugs} bugs is concerning - consider a bug triage")

        if open_stories > 0:
            lines.append(f"- 📝 {open_stories} stories still in progress - verify scope")

        return "\n".join(lines)

    def _format_rrs(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Release Readiness Score with intelligent analysis."""
        release_id = data.get("release_id", params.get("release_id", DEFAULT_RELEASE))
        rrs = data.get("rrs", {})

        overall = rrs.get("overall", 0)
        components = rrs.get("components", {})

        # Use helper for status, with custom thresholds for RRS
        status_emoji, status_text = self._get_status_emoji(overall, thresholds=(85, 50))

        # Determine assessment based on score
        assessments = {
            "On Track": "Release is in excellent shape and ready to proceed.",
            "At Risk": "Release has some concerns that need attention before shipping.",
            "Critical": "Release is at high risk and NOT recommended to ship in current state.",
        }
        assessment = assessments.get(status_text, "Review release status.")

        lines = [
            self._build_header(status_emoji, "Release Readiness Analysis", release=release_id),
            "",
            f"### Overall Score: {overall}%",
            "",
            f"**Assessment:** {assessment}",
            "",
        ]

        # Analyze component scores and identify concerns
        component_names = {
            "bugs": ("🐛 Bug Health", "bug counts"),
            "automation": ("🤖 Automation", "test automation coverage"),
            "manualExecution": ("✅ Manual Testing", "manual test execution"),
            "pipeline": ("🔧 CI/CD Pipeline", "build and deployment health"),
            "escalations": ("📢 Customer Escalations", "customer-reported issues"),
        }

        # Find weak areas and strong areas
        weak_areas = []
        strong_areas = []

        lines.append("### Component Breakdown")
        lines.append("")

        for key, (label, description) in component_names.items():
            score = components.get(key, 0)
            if score >= 80:
                score_emoji = "✅"
                strong_areas.append((label, score, description))
            elif score >= 60:
                score_emoji = "⚠️"
                weak_areas.append((label, score, description))
            else:
                score_emoji = "🔴"
                weak_areas.append((label, score, description))
            lines.append(f"- {score_emoji} **{label}:** {score}%")

        lines.append("")

        # Provide intelligent analysis
        lines.append("### Analysis")
        lines.append("")

        if strong_areas:
            lines.append("**What's Going Well:**")
            for label, score, desc in strong_areas[:3]:
                lines.append(f"- {label} at {score}% shows healthy {desc}")
            lines.append("")

        if weak_areas:
            lines.append("**Areas of Concern:**")
            for label, score, desc in sorted(weak_areas, key=lambda x: x[1]):
                if score < 60:
                    lines.append(f"- ⚠️ {label} at {score}% - {desc} needs immediate attention")
                else:
                    lines.append(f"- {label} at {score}% - {desc} could be improved")
            lines.append("")

        # Add specific blockers
        if rrs.get("pipelineBlocker") or rrs.get("escalationRisk"):
            lines.append("### Blockers & Risks")
            lines.append("")
            if rrs.get("pipelineBlocker"):
                lines.append(f"🚫 **Pipeline Blocker:** {rrs.get('pipelineReason', 'CI/CD issues detected')}")
            if rrs.get("escalationRisk"):
                lines.append(f"⚠️ **Escalation Risk:** {rrs.get('escalationReason', 'High escalation count')}")
            lines.append("")

        # Provide recommendations
        lines.append("### Recommendations")
        lines.append("")

        if overall >= 85:
            lines.append("✅ Release looks good to proceed. Continue monitoring pipeline health.")
        elif overall >= 70:
            if components.get("escalations", 100) < 60:
                lines.append("1. **Prioritize escalation resolution** - Customer issues are impacting readiness")
            if components.get("pipeline", 100) < 70:
                lines.append("2. **Investigate pipeline failures** - Unstable CI/CD may delay deployment")
            lines.append("3. Review status again before final sign-off")
        else:
            lines.append("⚠️ **Do not ship without addressing:**")
            for label, score, desc in sorted(weak_areas, key=lambda x: x[1])[:2]:
                lines.append(f"- Fix {label.lower()} issues (currently at {score}%)")

        return "\n".join(lines)

    def _format_release_readiness_score_calculation(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """
        Calculate and explain the Release Readiness Score (RRS) with dynamic component filtering.

        Formula: RRS = 100% - (Total Open Items × 3%)
        """
        release = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        release_summary = data.get("releaseSummary", {})
        components_data = data.get("componentsData", {})

        # Use helper for filters
        filters = self._get_filters(data, params, component_keys=["componentsData"])
        component_filter = filters["component"]
        wants_breakdown = filters["wants_breakdown"]

        # Calculate scores based on component filter
        if component_filter and component_filter.upper() in components_data:
            comp_data = components_data[component_filter.upper()]
            comp_summary = comp_data.get("summary", {})
            open_stories = comp_summary.get("bc_stories", 0)
            open_bugs = comp_summary.get("bc_bugs", 0)
            total_open = open_stories + open_bugs
            title_suffix = f" ({component_filter.upper()})"
        else:
            open_stories = release_summary.get("openStories", 0)
            open_bugs = release_summary.get("openBugs", 0)
            total_open = release_summary.get("totalOpen", open_stories + open_bugs)
            title_suffix = ""

        phase = release_summary.get("phaseName", release_summary.get("phase", "Unknown"))

        # Calculate the simple health score
        deduction = total_open * 3
        health_score = max(0, 100 - deduction)

        # Use helper for status
        status_emoji, status_text = self._get_status_emoji(health_score)
        status = f"{status_emoji} {status_text}"

        lines = [
            f"## 📊 Health Score: {release}{title_suffix}",
            "",
            f"### Current Score: {health_score}% ({status})",
            "",
            "### How It's Calculated",
            "",
            "The Release Readiness health score uses a simple formula:",
            "",
            "```",
            "Health Score = 100% - (Open Items × 3%)",
            "```",
            "",
            "### Your Current Numbers",
            "",
            "| Item | Count | Impact |",
            "|------|-------|--------|",
            f"| 📝 Open Stories | {open_stories} | -{open_stories * 3}% |",
            f"| 🐛 Open Bugs | {open_bugs} | -{open_bugs * 3}% |",
            f"| 📊 **Total Open** | **{total_open}** | **-{deduction}%** |",
            "",
            "### Calculation",
            "",
            "- Starting Score: **100%**",
            f"- Total Open Items: **{total_open}**",
            f"- Deduction: {total_open} × 3% = **{deduction}%**",
            f"- Final Score: 100% - {deduction}% = **{health_score}%**",
            "",
            "### Current Phase",
            f"- **Phase:** {phase}",
            "",
            "### How to Improve",
            "",
        ]

        if total_open > 0:
            if open_bugs > 0:
                lines.append(f"- Close {open_bugs} bugs to gain +{open_bugs * 3}%")
            if open_stories > 0:
                lines.append(f"- Resolve {open_stories} stories to gain +{open_stories * 3}%")
            lines.append("- Closing all items would bring score to **100%**")
        else:
            lines.append("🎉 All items are closed! Score is at maximum.")

        lines.append("")
        lines.append("### Score Thresholds")
        lines.append("- 80-100%: ✅ On Track (Green)")
        lines.append("- 50-79%: ⚠️ At Risk (Yellow)")
        lines.append("- 0-49%: 🔴 Critical (Red)")

        # Per-component breakdown if user asked for it or data is available
        if wants_breakdown and components_data and len(components_data) > 1:
            lines.append("")
            lines.append("### 📊 Per-Component Scores")
            lines.append("")
            lines.append("| Component | Open | Score | Status |")
            lines.append("|-----------|------|-------|--------|")
            for comp_name, comp_data in components_data.items():
                comp_summary = comp_data.get("summary", {})
                comp_open = comp_summary.get("bc_stories", 0) + comp_summary.get("bc_bugs", 0)
                comp_score = max(0, 100 - (comp_open * 3))
                comp_status = "✅" if comp_score >= 80 else "⚠️" if comp_score >= 50 else "🔴"
                lines.append(f"| {comp_name} | {comp_open} | {comp_score}% | {comp_status} |")

        return "\n".join(lines)

    def _format_explain_rrs(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """
        Explain why the Release Readiness Score is what it is and how to improve.
        Provides actionable recommendations with specific items to address.
        """
        # release is extracted for potential future use
        _ = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        release_summary = data.get("releaseSummary", {})
        blockers = data.get("blockersAnalysis", {})

        open_stories = release_summary.get("openStories", 0)
        open_bugs = release_summary.get("openBugs", 0)
        total_open = release_summary.get("totalOpen", open_stories + open_bugs)
        code_review = release_summary.get("inCodeReview", 0)
        phase = release_summary.get("phaseName", release_summary.get("phase", "Unknown"))
        days_remaining = release_summary.get("daysRemaining", 0)

        # Calculate health score
        deduction = total_open * 3
        health_score = max(0, 100 - deduction)

        # Determine status
        if health_score >= 80:
            status = "✅ GREEN - On Track"
            status_emoji = "✅"
        elif health_score >= 50:
            status = "⚠️ YELLOW - At Risk"
            status_emoji = "⚠️"
        else:
            status = "🔴 RED - Critical"
            status_emoji = "🔴"

        # Get critical items and at-risk assignees
        critical_items = blockers.get("criticalItems", [])
        at_risk_assignees = blockers.get("atRiskAssignees", [])
        stuck_items = blockers.get("stuckItems", [])

        lines = [
            f"## 📊 Why is the Release Readiness Score {health_score}%?",
            "",
            f"### Current Status: {status}",
            "",
            "---",
            "",
            "### 📈 Score Breakdown",
            "",
            "**Formula:** `100% - (Open Items × 3%)`",
            "",
            "| Metric | Count | Impact |",
            "|--------|-------|--------|",
            f"| 📝 Open Stories | {open_stories} | -{open_stories * 3}% |",
            f"| 🐛 Open Bugs | {open_bugs} | -{open_bugs * 3}% |",
            f"| 📊 **Total** | **{total_open}** | **-{deduction}%** |",
            "",
            f"**Calculation:** 100% - {deduction}% = **{health_score}%**",
            "",
            "---",
            "",
            "### 🔍 Root Causes",
            "",
        ]

        # Analyze why score is low
        causes = []
        if open_bugs > 5:
            causes.append(f"- 🐛 **High bug count ({open_bugs} bugs)** - Each bug reduces score by 3%")
        if open_stories > 3:
            causes.append(f"- 📝 **Incomplete stories ({open_stories} stories)** - Scope not fully delivered")
        if len(critical_items) > 0:
            causes.append(
                f"- 🔴 **{len(critical_items)} Critical/Blocker items** - High priority issues blocking release"
            )
        if len(stuck_items) > 0:
            causes.append(f"- 🟠 **{len(stuck_items)} Stuck items** - Items not making progress")
        if code_review > 3:
            causes.append(f"- 🔵 **{code_review} items in Code Review** - Potential bottleneck")

        if causes:
            lines.extend(causes)
        else:
            lines.append("- Score is healthy, continue current pace")

        lines.extend(
            [
                "",
                "---",
                "",
                "### 🎯 How to Improve the Score",
                "",
            ]
        )

        # Actionable recommendations
        recommendations = []

        if len(critical_items) > 0:
            recommendations.append(
                {
                    "priority": 1,
                    "icon": "🔴",
                    "title": f"Resolve {len(critical_items)} Critical/Blocker bugs",
                    "impact": f"+{len(critical_items) * 3}% potential gain",
                    "items": critical_items[:3],
                }
            )

        if open_bugs > 0:
            recommendations.append(
                {
                    "priority": 2,
                    "icon": "🐛",
                    "title": f"Close {open_bugs} open bugs",
                    "impact": f"+{open_bugs * 3}% potential gain",
                    "items": [],
                }
            )

        if open_stories > 0:
            recommendations.append(
                {
                    "priority": 3,
                    "icon": "📝",
                    "title": f"Complete {open_stories} open stories",
                    "impact": f"+{open_stories * 3}% potential gain",
                    "items": [],
                }
            )

        if len(at_risk_assignees) > 0:
            overloaded = [a for a in at_risk_assignees if a.get("riskLevel") == "high"]
            if overloaded:
                recommendations.append(
                    {
                        "priority": 4,
                        "icon": "👥",
                        "title": f"Redistribute work from {len(overloaded)} overloaded assignees",
                        "impact": "Faster item resolution",
                        "items": [],
                    }
                )

        for i, rec in enumerate(recommendations[:5], 1):
            lines.append(f"**{i}. {rec['icon']} {rec['title']}**")
            lines.append(f"   - Impact: {rec['impact']}")
            if rec.get("items"):
                for item in rec["items"][:2]:
                    lines.append(
                        f"   - `{item.get('key', 'N/A')}`: {item.get('summary', '')[:40]}... ({item.get('assignee', 'Unassigned')})"
                    )
            lines.append("")

        # Target score calculation
        if total_open > 0:
            items_to_green = max(0, total_open - 6)  # Need <= 6 items for 82%
            lines.extend(
                [
                    "---",
                    "",
                    "### 🎯 Target Score",
                    "",
                    f"- Current: **{health_score}%** ({status_emoji})",
                    f"- To reach GREEN (80%): Close at least **{items_to_green}** more items",
                    f"- Days remaining: **{days_remaining}** days until {phase}",
                    "",
                ]
            )

            if days_remaining > 0 and items_to_green > 0:
                items_per_day = round(items_to_green / days_remaining, 1)
                lines.append(f"- Required pace: **{items_per_day} items/day** to reach GREEN")

        return "\n".join(lines)

    def _format_moreinfo_items(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format MoreInfo items using common helpers."""
        release = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        components_data = data.get("componentsData", {})
        stories_by_assignee = data.get("storiesByAssignee", [])

        # Use helper for filters
        filters = self._get_filters(data, params, component_keys=["componentsData"])
        component_filter = filters["component"]

        # Collect all items and filter for MoreInfo status
        moreinfo_items = []
        seen_keys = set()

        for comp_name, comp_data in components_data.items():
            if component_filter and comp_name.upper() != component_filter.upper():
                continue
            for issue in comp_data.get("issues", []):
                status = (issue.get("status") or "").lower()
                key = issue.get("key")
                if ("more info" in status or "moreinfo" in status) and key and key not in seen_keys:
                    seen_keys.add(key)
                    moreinfo_items.append({**issue, "component": comp_name})

        for assignee_data in stories_by_assignee:
            for ticket in assignee_data.get("tickets", []):
                status = (ticket.get("status") or "").lower()
                key = ticket.get("key")
                if ("more info" in status or "moreinfo" in status) and key and key not in seen_keys:
                    seen_keys.add(key)
                    moreinfo_items.append(ticket)

        # Use helper for header
        lines = [self._build_header("📋", "MoreInfo Items", release=release, filter_val=component_filter), ""]

        if not moreinfo_items:
            lines.append("✅ **No items in MoreInfo status!**")
            lines.append("")
            lines.append("All items have the information needed to proceed.")
            return "\n".join(lines)

        lines.append(f"Found **{len(moreinfo_items)} items** awaiting additional information:")
        lines.append("")

        # Group by reporter (who needs to provide info)
        by_reporter = {}
        for item in moreinfo_items:
            reporter = item.get("reporter", "Unknown")
            if reporter not in by_reporter:
                by_reporter[reporter] = []
            by_reporter[reporter].append(item)

        lines.append("### Items by Reporter (who needs to provide info)")
        lines.append("")
        lines.append("| Reporter | Items | Action |")
        lines.append("|----------|-------|--------|")

        for reporter, items in sorted(by_reporter.items(), key=lambda x: len(x[1]), reverse=True):
            lines.append(f"| {reporter} | {len(items)} | Follow up for details |")

        lines.append("")
        lines.append("### Item Details")
        lines.append("")

        for item in moreinfo_items[:15]:
            key = item.get("key", "N/A")
            summary = item.get("summary", "")[:50]
            assignee = item.get("assignee", "Unassigned")
            reporter = item.get("reporter", "Unknown")
            item_type = item.get("type", item.get("issuetype", "Bug"))

            type_emoji = "🐛" if "bug" in str(item_type).lower() else "📝"
            lines.append(f"- {type_emoji} **{key}**: {summary}")
            lines.append(f"  - Assignee: {assignee} | Reporter: {reporter}")
            lines.append("")

        if len(moreinfo_items) > 15:
            lines.append(f"*...and {len(moreinfo_items) - 15} more items*")

        lines.extend(
            [
                "",
                "### Recommended Actions",
                "1. Contact reporters to provide the missing information",
                "2. Set deadlines for information requests",
                "3. Consider closing stale MoreInfo items if info is not forthcoming",
            ]
        )

        return "\n".join(lines)

    def _format_resolution_progress(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format resolution progress data using common helpers."""
        release = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        timeline = data.get("timeline", {})
        summary = data.get("summary", {})
        chart_data = data.get("chartData", [])

        # Use helper for filters
        by_component = summary.get("byComponent", {})
        filters = self._get_filters({"byComponent": by_component}, params, component_keys=["byComponent"])
        component_filter = filters["component"]

        irr_date = timeline.get("irr_date", "Unknown")
        fb_date = timeline.get("final_build_date", "Unknown")
        days_elapsed = timeline.get("days_elapsed", 0)

        total_resolved = summary.get("totalResolved", 0)
        total_stories = summary.get("totalStories", 0)
        total_bugs = summary.get("totalBugs", 0)
        resolved_before_irr = summary.get("resolvedBeforeIRR", 0)
        resolved_after_irr = summary.get("resolvedAfterIRR", 0)
        avg_per_day = summary.get("avgPerDay", 0)

        # Filter to specific component if requested
        title_suffix = ""
        if component_filter:
            comp_upper = component_filter.upper()
            comp_count = by_component.get(comp_upper, 0)
            title_suffix = f" ({comp_upper})"
            # Show component-specific summary
            total_resolved = comp_count
            # Note: stories/bugs breakdown per component may not be in summary, so we show what we have

        lines = [
            f"## 📊 Resolution Progress: {release}{title_suffix}",
            "",
            f"**Period:** {irr_date} (IRR) → {fb_date} (Final Build)",
            f"**Days Elapsed:** {days_elapsed}",
            "",
            "### Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| 📋 Total Resolved | **{total_resolved}** |",
            f"| 📝 Stories | {total_stories} |",
            f"| 🐛 Bugs | {total_bugs} |",
            f"| ⏪ Before IRR | {resolved_before_irr} |",
            f"| ⏩ After IRR | {resolved_after_irr} |",
            f"| 📈 Avg/Day | {avg_per_day:.1f} |",
            "",
        ]

        # Component breakdown (show all or highlight filtered one)
        if by_component:
            lines.append("### By Component")
            lines.append("")
            for comp, count in sorted(by_component.items(), key=lambda x: -x[1]):
                pct = (count / total_resolved * 100) if total_resolved > 0 else 0
                highlight = "**→ " if component_filter and comp.upper() == component_filter.upper() else ""
                end_highlight = " ←**" if highlight else ""
                lines.append(f"- {highlight}**{comp}:** {count} ({pct:.0f}%){end_highlight}")
            lines.append("")

        # Show trend data (last 5 days of activity)
        if chart_data and len(chart_data) > 1:
            lines.append("### Recent Activity")
            lines.append("")
            lines.append("| Date | Stories | Bugs | Total |")
            lines.append("|------|---------|------|-------|")

            # Find days with activity
            active_days = [d for d in chart_data if d.get("dailyTotal", 0) > 0]
            recent = active_days[-5:] if len(active_days) > 5 else active_days

            for day in recent:
                display = day.get("displayDate", day.get("date", "?"))
                stories = day.get("dailyStories", 0)
                bugs = day.get("dailyBugs", 0)
                total = day.get("dailyTotal", 0)
                lines.append(f"| {display} | {stories} | {bugs} | {total} |")
            lines.append("")

        # Analysis
        lines.append("### Analysis")
        lines.append("")

        if resolved_after_irr > resolved_before_irr * 0.5:
            lines.append(f"✅ **Good progress post-IRR:** {resolved_after_irr} items resolved after IRR started")
        else:
            lines.append(
                f"⚠️ Most work ({resolved_before_irr}) was done before IRR - limited progress during release phase"
            )

        if avg_per_day >= 5:
            lines.append(f"✅ **Healthy velocity:** Averaging {avg_per_day:.1f} resolutions per day")
        elif avg_per_day >= 2:
            lines.append(f"⚠️ **Moderate velocity:** {avg_per_day:.1f} resolutions per day")
        else:
            lines.append(f"🔴 **Low velocity:** Only {avg_per_day:.1f} resolutions per day - may need acceleration")

        return "\n".join(lines)

    def _format_milestone_data(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format milestone-specific data using common helpers."""
        release = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        milestone = data.get("milestone", data.get("milestoneName", "Milestone"))
        milestone_name = data.get("milestoneName", milestone)
        milestone_date = data.get("milestoneDate", "")
        deadline_passed = data.get("deadlinePassed", False)
        days_since = data.get("daysSinceDeadline", 0)
        # requirement extracted for potential future use
        _ = data.get("requirement", "")

        # Check if this is MCP response (has on_time_rate) or legacy response (has components)
        is_mcp_response = "on_time_rate" in data or "open_list" in data

        if is_mcp_response:
            # MCP tool response format
            component_filter = data.get("component")
            if component_filter:
                milestone_name = f"{milestone_name} ({component_filter.upper()})"

            total_items = data.get("total_items", 0)
            resolved_items = data.get("resolved_items", 0)
            open_items_count = data.get("open_items", 0)
            on_time_rate = data.get("on_time_rate", 0)
            all_open_items = data.get("open_list", [])

            total_on_time = resolved_items
            total_resolved_late = 0  # MCP doesn't distinguish late vs on-time resolved
            total_still_open = open_items_count
            total_stories = total_items
            all_late_items = []
        else:
            # Legacy response with components structure
            components_data = data.get("components", {})
            filters = self._get_filters({"components": components_data}, params, component_keys=["components"])
            component_filter = filters["component"]
            wants_breakdown = filters["wants_breakdown"]

            # Filter to specific component if requested
            if component_filter and not wants_breakdown:
                filtered_data = {}
                for comp_name, comp_data in components_data.items():
                    if comp_name.upper() == component_filter.upper() or component_filter.upper() in comp_name.upper():
                        filtered_data[comp_name] = comp_data
                        break
                if filtered_data:
                    components_data = filtered_data
                    milestone_name = f"{milestone_name} ({component_filter.upper()})"

            total_on_time = 0
            total_resolved_late = 0
            total_still_open = 0
            all_late_items = []
            all_open_items = []

            for comp_name, comp_data in components_data.items():
                if isinstance(comp_data, dict):
                    total_on_time += comp_data.get("resolvedOnTime", 0)

                    late_items = comp_data.get("resolvedAfterDeadline", [])
                    if isinstance(late_items, list):
                        total_resolved_late += len(late_items)
                        all_late_items.extend(late_items)

                    open_items = comp_data.get("stillOpen", [])
                    if isinstance(open_items, list):
                        total_still_open += len(open_items)
                        all_open_items.extend(open_items)

            total_stories = total_on_time + total_resolved_late + total_still_open
            on_time_rate = round((total_on_time / total_stories * 100), 0) if total_stories > 0 else 0

        # Determine status based on still open items
        if total_still_open == 0:
            status_emoji = "✅"
            status_text = "READY - All items resolved"
            _ = "All stories are resolved. Milestone met!"  # assessment for context
        elif total_still_open <= 3:
            status_emoji = "🟡"
            status_text = f"AT RISK - {total_still_open} items still open"
            # assessment context stored for future use
            _ = f"Release at risk. {total_still_open} items overdue. Escalation required."
        else:
            status_emoji = "🔴"
            status_text = f"BLOCKED - {total_still_open} items still open"
            # assessment used for context, not displayed directly
            _ = f"Release blocked. {total_still_open} items need immediate attention."

        lines = [
            f"## {status_emoji} {milestone_name}: {release}",
            "",
            f"**Status:** {status_text}",
            "",
        ]

        # Add date info
        if milestone_date:
            if deadline_passed:
                lines.append(f"📅 **{milestone}:** {milestone_date} (passed {days_since} days ago)")
            else:
                days_to = data.get("daysToDeadline", 0)
                lines.append(f"📅 **{milestone}:** {milestone_date} ({days_to} days remaining)")
            lines.append("")

        # Concise quantitative summary
        lines.extend(
            [
                "| Metric | Value |",
                "|--------|-------|",
                f"| 📊 **Total Items** | {total_stories} |",
                f"| ✅ **Resolved** | {total_on_time} |",
                f"| 🔴 **Open** | {total_still_open} |",
                f"| 📈 **On-Time Rate** | {on_time_rate}% |",
                "",
            ]
        )

        # Show still open items (most critical)
        if all_open_items:
            lines.append("### 🔴 Still Open Items (Need Immediate Action)")
            lines.append("")
            for item in all_open_items[:5]:
                key = item.get("key", "N/A")
                summary_text = item.get("summary", "")[:45]
                assignee = item.get("assignee", "Unassigned")
                lines.append(f"- [{key}]({item.get('url', '#')}) - {summary_text} (**{assignee}**)")
            if len(all_open_items) > 5:
                lines.append(f"- ... and {len(all_open_items) - 5} more")
            lines.append("")

        # Show recently resolved late items
        if all_late_items and total_still_open == 0:
            lines.append("### 🟡 Recently Resolved (Late)")
            lines.append("")
            # Sort by days late, show worst ones
            sorted_late = sorted(all_late_items, key=lambda x: x.get("daysAfterDeadline", 0), reverse=True)
            for item in sorted_late[:3]:
                key = item.get("key", "N/A")
                missed_by = item.get("missedBy", "")
                assignee = item.get("assignee", "Unassigned")
                lines.append(f"- [{key}]({item.get('url', '#')}) - {missed_by} (**{assignee}**)")
            lines.append("")

        # Per-component breakdown if user asked for "each component"
        if wants_breakdown and len(components_data) > 1:
            lines.append("### 📊 Per-Component Breakdown")
            lines.append("")
            lines.append("| Component | On Time | Late | Open | Rate |")
            lines.append("|-----------|---------|------|------|------|")
            for comp_name, comp_data in components_data.items():
                if isinstance(comp_data, dict):
                    on_time = comp_data.get("resolvedOnTime", 0)
                    late = (
                        len(comp_data.get("resolvedAfterDeadline", []))
                        if isinstance(comp_data.get("resolvedAfterDeadline"), list)
                        else 0
                    )
                    still_open = (
                        len(comp_data.get("stillOpen", [])) if isinstance(comp_data.get("stillOpen"), list) else 0
                    )
                    comp_total = on_time + late + still_open
                    rate = round((on_time / comp_total * 100), 0) if comp_total > 0 else 0
                    status = "✅" if still_open == 0 else "🔴" if still_open > 3 else "🟡"
                    lines.append(f"| {status} {comp_name} | {on_time} | {late} | {still_open} | {rate}% |")
            lines.append("")

        return "\n".join(lines)

    def _format_code_commits(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format GitHub code commits data - focusing on flagged commits after branch cut."""
        release = data.get("release", params.get("release_id", DEFAULT_RELEASE))
        branch_cut_date = data.get("branchCutDate", "")
        repos_data = data.get("repos", {})
        summary = data.get("summary", {})

        user_query = params.get("_user_query", "").lower()
        logger.info("Code commits formatter - user_query: '%s'", user_query[:100] if user_query else "EMPTY")

        # Detect if asking about "before" or "after" branch cut
        show_before = "before" in user_query and "branch" in user_query
        show_after = "after" in user_query or "flagged" in user_query or not show_before
        logger.info("Show before: {show_before}, Show after: %s", show_after)

        # Direct repo matching - check if any repo name appears in the query
        # Sort by length descending to match longer names first (enrollment-service before service)
        matched_filter = None
        if repos_data and user_query:
            available_repos = []
            repo_candidates = []
            for repo_key, repo_data in repos_data.items():
                if isinstance(repo_data, dict):
                    repo_name = repo_data.get("name", repo_key).lower()
                    available_repos.append(repo_name)
                    repo_candidates.append((repo_key.lower(), repo_name))

            # Sort by length descending - longer names first to avoid "service" matching before "enrollment-service"
            repo_candidates.sort(key=lambda x: max(len(x[0]), len(x[1])), reverse=True)

            for repo_key, repo_name in repo_candidates:
                # Check if repo name (or key) appears in query as a word (not substring of another word)
                # Use word boundary check
                if re.search(rf"\b{re.escape(repo_name)}\b", user_query) or re.search(
                    rf"\b{re.escape(repo_key)}\b", user_query
                ):
                    matched_filter = repo_name
                    logger.info("Matched repo '%s' in query (word boundary)", repo_name)
                    break

            logger.info("Available repos: {available_repos}, Matched: %s", matched_filter)

        # Filter repos if we found a match
        if matched_filter and repos_data:
            matched_lower = matched_filter.lower()
            filtered_repos = {}
            for repo_name, repo_data in repos_data.items():
                if isinstance(repo_data, dict):
                    repo_display = repo_data.get("name", repo_name).lower()
                    # Exact match only - no substring matching to avoid service matching enrollment-service
                    if repo_display == matched_lower or repo_name.lower() == matched_lower:
                        filtered_repos[repo_name] = repo_data
            if filtered_repos:
                repos_data = filtered_repos
                # Recalculate summary for filtered data
                total = sum(len(r.get("commits", [])) for r in repos_data.values() if isinstance(r, dict))
                flagged = sum(len(r.get("flaggedCommits", [])) for r in repos_data.values() if isinstance(r, dict))
                summary = {
                    "totalCommits": total,
                    "flaggedCommits": flagged,
                    "reposWithFlaggedCommits": len(
                        [r for r in repos_data.values() if isinstance(r, dict) and r.get("flaggedCommits")]
                    ),
                }
                logger.info("Filtered to {len(filtered_repos)} repos: %s", list(filtered_repos.keys()))

        total_commits = summary.get("totalCommits", 0)
        flagged_count = summary.get("flaggedCommits", 0)
        repos_with_flagged = summary.get("reposWithFlaggedCommits", 0)

        # Calculate before branch cut count
        before_count = 0
        for repo_name, repo_data in repos_data.items():
            if isinstance(repo_data, dict):
                all_commits = repo_data.get("commits", [])
                before_count += len([c for c in all_commits if not c.get("isAfterBranchCut", False)])

        # Determine status based on query type and counts
        if show_before:
            # For "before branch cut" queries
            if before_count > 0:
                status_emoji = "✅"
                status_text = f"{before_count} commits included in release"
            else:
                status_emoji = "⚠️"
                status_text = "No commits found before Branch Cut"
        else:
            # For "after branch cut" queries
            if flagged_count == 0:
                status_emoji = "✅"
                status_text = "No commits after Branch Cut"
            elif flagged_count <= 5:
                status_emoji = "🟡"
                status_text = f"{flagged_count} commits after Branch Cut"
            else:
                status_emoji = "🔴"
                status_text = f"{flagged_count} commits after Branch Cut - Review needed"

        # Build title with filter indication
        title = f"## {status_emoji} Code Commits: {release}"
        if matched_filter:
            title += f" (Filtered: {matched_filter})"

        lines = [
            title,
            "",
            f"**Branch Cut Date:** {branch_cut_date}",
            f"**Status:** {status_text}",
            "",
            "### Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| 📊 Total Commits | {total_commits} |",
            f"| ✅ Before Branch Cut | {before_count} |",
            f"| 🚩 After Branch Cut | {flagged_count} |",
            f"| 📦 Repos with Flagged Commits | {repos_with_flagged} |",
            "",
        ]

        # Handle "before branch cut" vs "after branch cut" queries
        if show_before:
            # User asked about commits BEFORE branch cut - filter by isAfterBranchCut=false
            lines.append("### Commits Before Branch Cut")
            lines.append("")
            total_shown = 0
            for repo_name, repo_data in repos_data.items():
                if isinstance(repo_data, dict):
                    all_commits = repo_data.get("commits", [])
                    # Filter to only commits BEFORE branch cut (isAfterBranchCut == false)
                    before_commits = [c for c in all_commits if not c.get("isAfterBranchCut", False)]
                    if before_commits:
                        repo_display = repo_data.get("name", repo_name)
                        lines.append(f"**{repo_display}** ({len(before_commits)} commits before branch cut)")
                        lines.append("")
                        for commit in before_commits[:5]:
                            sha = commit.get("sha", "")[:8]
                            msg = commit.get("message", "")[:50]
                            author = commit.get("author", "Unknown")
                            date = commit.get("formattedDate", commit.get("date", ""))
                            url = commit.get("url", "#")
                            lines.append(f"- [`{sha}`]({url}) {msg} - **{author}** ({date})")
                        if len(before_commits) > 5:
                            lines.append(f"- ... and {len(before_commits) - 5} more")
                        lines.append("")
                        total_shown += len(before_commits)
            if total_shown == 0:
                lines.append("No commits found before branch cut for the specified filter.")
                lines.append("")
        else:
            # Show flagged commits by repo (after branch cut - this is what the dashboard shows)
            if flagged_count > 0:
                lines.append("### 🚩 Flagged Commits (After Branch Cut)")
                lines.append("")
                lines.append("These commits went in after the branch cut date and need review:")
                lines.append("")

                for repo_name, repo_data in repos_data.items():
                    if isinstance(repo_data, dict):
                        flagged = repo_data.get("flaggedCommits", [])
                        if flagged:
                            lines.append(f"**{repo_data.get('name', repo_name)}** ({len(flagged)} flagged)")
                            lines.append("")
                            for commit in flagged[:5]:
                                sha = commit.get("sha", "")[:8]
                                msg = commit.get("message", "")[:50]
                                author = commit.get("author", "Unknown")
                                date = commit.get("formattedDate", commit.get("date", ""))
                                url = commit.get("url", "#")
                                lines.append(f"- [`{sha}`]({url}) {msg} - **{author}** ({date})")
                            if len(flagged) > 5:
                                lines.append(f"- ... and {len(flagged) - 5} more")
                            lines.append("")
            else:
                lines.append("✅ **All clear!** No commits detected after the branch cut date.")
                lines.append("")

        return "\n".join(lines)

    def _format_test_execution(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format TestRail test execution data."""
        summary = data.get("summary", data)
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        blocked = summary.get("blocked", 0)
        untested = summary.get("untested", 0)

        pass_rate = (passed / total * 100) if total > 0 else 0

        status_emoji = "✅" if pass_rate >= 90 else "⚠️" if pass_rate >= 70 else "🔴"

        lines = [
            f"## {status_emoji} Test Execution Status",
            "",
            f"**Pass Rate:** {pass_rate:.1f}%",
            "",
            "### Results",
            "",
            "| Status | Count |",
            "|--------|-------|",
            f"| ✅ Passed | {passed} |",
            f"| ❌ Failed | {failed} |",
            f"| ⏸️ Blocked | {blocked} |",
            f"| ⏳ Untested | {untested} |",
            f"| 📊 **Total** | **{total}** |",
        ]

        return "\n".join(lines)

    def _format_untested_cases(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format untested test cases by owner."""
        owners = data.get("owners", data.get("byOwner", []))
        total = data.get("totalUntested", sum(o.get("count", 0) for o in owners))

        lines = [
            "## ⏳ Untested Cases",
            "",
            f"**Total Untested:** {total}",
            "",
            "### By Owner",
            "",
            "| Owner | Untested |",
            "|-------|----------|",
        ]

        for owner in sorted(owners, key=lambda x: -x.get("count", 0))[:10]:
            name = owner.get("owner", owner.get("name", "Unknown"))
            count = owner.get("count", owner.get("untested", 0))
            lines.append(f"| {name} | {count} |")

        return "\n".join(lines)

    def _format_manual_execution(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format manual execution data from Google Sheets."""
        categories = data.get("categories", data.get("sheets", []))
        summary = data.get("summary", {})

        total = summary.get("total", 0)
        executed = summary.get("executed", 0)
        passed = summary.get("passed", 0)

        exec_rate = (executed / total * 100) if total > 0 else 0

        lines = [
            "## 📋 Manual Execution Status",
            "",
            f"**Execution Rate:** {exec_rate:.1f}%",
            "",
            "### Summary",
            f"- **Total Cases:** {total}",
            f"- **Executed:** {executed}",
            f"- **Passed:** {passed}",
            "",
        ]

        if categories:
            lines.append("### By Category")
            lines.append("")
            for cat in categories[:5]:
                name = cat.get("name", cat.get("category", "Unknown"))
                count = cat.get("total", cat.get("count", 0))
                exec_count = cat.get("executed", 0)
                lines.append(f"- **{name}:** {exec_count}/{count} executed")

        return "\n".join(lines)

    def _format_pipeline_status(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Jenkins pipeline status."""
        pipelines = data.get("pipelines", data.get("jobs", []))
        summary = data.get("summary", {})

        success = summary.get("success", 0)
        failed = summary.get("failed", 0)
        running = summary.get("running", 0)
        total = success + failed + running

        health = (success / total * 100) if total > 0 else 0
        status_emoji = "✅" if health >= 80 else "⚠️" if health >= 60 else "🔴"

        lines = [
            f"## {status_emoji} Pipeline Status",
            "",
            f"**Health:** {health:.0f}%",
            "",
            "### Summary",
            f"- ✅ Success: {success}",
            f"- ❌ Failed: {failed}",
            f"- 🔄 Running: {running}",
            "",
        ]

        if pipelines:
            lines.append("### Recent Pipelines")
            lines.append("")
            for p in pipelines[:5]:
                name = p.get("name", p.get("job", "Unknown"))
                status = p.get("status", p.get("result", "Unknown"))
                emoji = "✅" if status == "SUCCESS" else "❌" if status == "FAILURE" else "🔄"
                lines.append(f"- {emoji} **{name}**: {status}")

        return "\n".join(lines)

    def _format_golden_regression(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format golden regression test results."""
        # Check if data has 'builds' list (from jenkins_get_golden_regression)
        builds = data.get("builds", [])
        if builds:
            num_builds = params.get("num_builds", 10)
            lines = [
                f"## 🔧 Golden Regression - Last {len(builds)} Builds",
                "",
                "| # | Build | Status | Pass Rate | Duration | Time |",
                "|---|-------|--------|-----------|----------|------|",
            ]

            for i, build in enumerate(builds[:num_builds], 1):
                status = build.get("status", "unknown")
                status_emoji = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
                pass_rate = build.get("pass_rate", 0)
                duration = build.get("duration", "N/A")
                build_num = build.get("build_number", "?")
                time_ago = build.get("time_ago", build.get("timestamp", "N/A"))

                lines.append(
                    f"| {i} | #{build_num} | {status_emoji} {status} | {pass_rate}% | {duration} | {time_ago} |"
                )

            # Summary
            success_count = sum(1 for b in builds if b.get("status") == "success")
            lines.append("")
            lines.append(f"**Summary:** {success_count}/{len(builds)} builds passed")

            return "\n".join(lines)

        # Fallback to summary format
        summary = data.get("summary", data)
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)

        pass_rate = (passed / total * 100) if total > 0 else 0
        status_emoji = "✅" if pass_rate >= 95 else "⚠️" if pass_rate >= 80 else "🔴"

        lines = [
            f"## {status_emoji} Golden Regression Results",
            "",
            f"**Pass Rate:** {pass_rate:.1f}%",
            "",
            "| Status | Count |",
            "|--------|-------|",
            f"| ✅ Passed | {passed} |",
            f"| ❌ Failed | {failed} |",
            f"| 📊 Total | {total} |",
        ]

        # Add failed tests if any
        failures = data.get("failures", data.get("failedTests", []))
        if failures:
            lines.append("")
            lines.append("### Failed Tests")
            for test in failures[:5]:
                name = test.get("name", test.get("test", "Unknown"))
                lines.append(f"- ❌ {name}")

        return "\n".join(lines)

    def _format_build_info(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Jenkins build info response."""
        build_num = data.get("build_number", params.get("build_number", "?"))
        job_name = data.get("job_name", params.get("job_name", "Unknown"))
        status = data.get("status", data.get("result", "unknown"))
        status_emoji = "✅" if status.lower() == "success" else "❌" if status.lower() == "failed" else "⚠️"

        lines = [
            f"## 🔧 Build Info: {job_name} #{build_num}",
            "",
            f"**Status:** {status_emoji} {status}",
            f"**Duration:** {data.get('duration', 'N/A')}",
            f"**Timestamp:** {data.get('timestamp', 'N/A')}",
        ]

        if data.get("url"):
            lines.append(f"**URL:** {data.get('url')}")

        return "\n".join(lines)

    def _format_job_info(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Jenkins job info response."""
        job_name = data.get("name", params.get("job_name", "Unknown"))

        lines = [
            f"## 🔧 Job: {job_name}",
            "",
            f"**Last Build:** #{data.get('lastBuild', {}).get('number', 'N/A')}",
            f"**Last Success:** #{data.get('lastSuccessfulBuild', {}).get('number', 'N/A')}",
            f"**Health:** {data.get('healthReport', [{}])[0].get('description', 'N/A')}",
        ]

        return "\n".join(lines)

    def _format_milestone_status(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format milestone status response."""
        milestone = params.get("milestone", "IRR")

        # Check for display field first
        if "display" in data and data["display"]:
            return data["display"]

        resolved_on_time = data.get("resolved_on_time", 0)
        resolved_late = data.get("resolved_late", 0)
        still_open = data.get("still_open", 0)
        total = data.get("total", resolved_on_time + resolved_late + still_open)

        on_time_rate = (resolved_on_time / total * 100) if total > 0 else 0
        status_emoji = "🟢" if on_time_rate >= 80 else "🟡" if on_time_rate >= 70 else "🔴"

        lines = [
            f"## 📊 {milestone} Milestone Status: {status_emoji} {on_time_rate:.1f}%",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| ✅ Resolved On-Time | {resolved_on_time} |",
            f"| ⚠️ Resolved Late | {resolved_late} |",
            f"| ❌ Still Open | {still_open} |",
            f"| **Total** | {total} |",
        ]

        return "\n".join(lines)

    def _format_bugs_by_classification(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format bugs grouped by classification."""
        lines = ["## 🐛 Bugs by Classification", ""]

        for classification in ["regressions", "features", "others"]:
            class_data = data.get(classification, data.get(f"{classification}_bugs", []))
            if isinstance(class_data, dict):
                count = class_data.get("total", class_data.get("count", 0))
                bugs = class_data.get("bugs", [])
            else:
                count = len(class_data) if isinstance(class_data, list) else 0
                bugs = class_data if isinstance(class_data, list) else []

            emoji = "🔴" if classification == "regressions" else "🟡" if classification == "features" else "⚪"
            lines.append(f"### {emoji} {classification.title()} ({count})")

            for bug in bugs[:5]:
                key = bug.get("key", "?")
                summary = bug.get("summary", "")[:50]
                lines.append(f"- [{key}] {summary}")
            lines.append("")

        return "\n".join(lines)

    def _format_release_comparison(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format release comparison."""
        lines = ["## 📊 Release Comparison", ""]

        releases = data.get("releases", data.get("comparison", []))
        if releases:
            lines.append("| Release | Open | Resolved | Total |")
            lines.append("|---------|------|----------|-------|")
            for r in releases:
                name = r.get("name", r.get("release", "?"))
                open_count = r.get("open", 0)
                resolved = r.get("resolved", 0)
                total = r.get("total", open_count + resolved)
                lines.append(f"| {name} | {open_count} | {resolved} | {total} |")

        return "\n".join(lines)

    def _format_resiliency_trend(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format resiliency trend."""
        lines = ["## 📈 Resiliency Trend", ""]

        trends = data.get("trends", data.get("months", []))
        if trends:
            lines.append("| Month | Score | Change |")
            lines.append("|-------|-------|--------|")
            for t in trends:
                month = t.get("month", "?")
                score = t.get("score", 0)
                change = t.get("change", 0)
                change_emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                lines.append(f"| {month} | {score}% | {change_emoji} {change:+.1f}% |")

        return "\n".join(lines)

    def _format_test_report(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Jenkins test report."""
        job_name = params.get("job_name", "Unknown")
        build_num = params.get("build_number", "?")

        total = data.get("totalCount", data.get("total", 0))
        passed = data.get("passCount", data.get("passed", 0))
        failed = data.get("failCount", data.get("failed", 0))
        skipped = data.get("skipCount", data.get("skipped", 0))

        pass_rate = (passed / total * 100) if total > 0 else 0
        status_emoji = "✅" if pass_rate >= 95 else "⚠️" if pass_rate >= 80 else "🔴"

        lines = [
            f"## {status_emoji} Test Report: {job_name} #{build_num}",
            "",
            f"**Pass Rate:** {pass_rate:.1f}%",
            "",
            "| Status | Count |",
            "|--------|-------|",
            f"| ✅ Passed | {passed} |",
            f"| ❌ Failed | {failed} |",
            f"| ⏭️ Skipped | {skipped} |",
            f"| 📊 Total | {total} |",
        ]

        return "\n".join(lines)

    def _format_console_output(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format Jenkins console output."""
        output = data.get("output", data.get("console", ""))
        error_lines = data.get("error_lines", [])

        lines = [
            f"## 📜 Console Output: {params.get('job_name', 'Unknown')} #{params.get('build_number', '?')}",
            "",
        ]

        if error_lines:
            lines.append("### ❌ Error Lines")
            for err in error_lines[:10]:
                lines.append(f"```\n{err}\n```")

        if output:
            lines.append("### Last 20 Lines")
            last_lines = output.split("\n")[-20:]
            lines.append("```")
            lines.extend(last_lines)
            lines.append("```")

        return "\n".join(lines)

    def _format_calendar_info(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format calendar info."""
        return f"## 📅 Calendar Info\n\n**Status:** {data.get('status', 'Connected')}\n**Source:** {data.get('source', 'Google Calendar')}"

    def _format_upcoming_milestones(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format upcoming milestones."""
        milestones = data.get("milestones", [])
        release = params.get("release", "Current")

        lines = [f"## 📅 Upcoming Milestones - {release}", ""]

        if milestones:
            lines.append("| Milestone | Date | Days |")
            lines.append("|-----------|------|------|")
            for m in milestones:
                name = m.get("name", "?")
                date = m.get("date", "TBD")
                days = m.get("days_until", "?")
                lines.append(f"| {name} | {date} | {days} |")

        return "\n".join(lines)

    def _format_commits(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format GitHub commits."""
        commits = data.get("commits", [])
        repo = params.get("repo", "Unknown")

        lines = [f"## 📝 Commits - {repo}", ""]

        if commits:
            lines.append(f"**Total:** {len(commits)} commits")
            lines.append("")
            for c in commits[:10]:
                sha = c.get("sha", "?")[:7]
                msg = c.get("message", c.get("commit", {}).get("message", ""))[:60]
                author = c.get("author", c.get("commit", {}).get("author", {}).get("name", "?"))
                lines.append(f"- `{sha}` {msg} ({author})")
        else:
            lines.append("No commits found.")

        return "\n".join(lines)

    def _format_branches(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format GitHub branches."""
        branches = data.get("branches", [])
        repo = params.get("repo", "Unknown")

        lines = [f"## 🌿 Branches - {repo}", ""]

        for b in branches[:20]:
            name = b.get("name", "?")
            protected = "🔒" if b.get("protected") else ""
            lines.append(f"- {name} {protected}")

        return "\n".join(lines)

    def _format_branch_comparison(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format branch comparison."""
        ahead = data.get("ahead_by", 0)
        behind = data.get("behind_by", 0)

        lines = [
            "## 🔀 Branch Comparison",
            "",
            f"**{params.get('head', 'head')}** vs **{params.get('base', 'base')}**",
            "",
            f"- Ahead by: {ahead} commits",
            f"- Behind by: {behind} commits",
        ]

        return "\n".join(lines)

    def _format_release_commits_summary(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format release commits summary."""
        repos = data.get("repos", data.get("summary", []))
        release = params.get("release", "Current")

        lines = [f"## 📊 Release Commits Summary - {release}", ""]

        if repos:
            lines.append("| Repository | Before Cut | After Cut | Total |")
            lines.append("|------------|------------|-----------|-------|")
            for r in repos:
                name = r.get("repo", r.get("name", "?"))
                before = r.get("before_cut", r.get("before", 0))
                after = r.get("after_cut", r.get("after", 0))
                total = before + after
                lines.append(f"| {name} | {before} | {after} | {total} |")

        return "\n".join(lines)

    def _format_generic(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Generic formatter for unknown data structures."""
        # Check for display field first
        if isinstance(data, dict) and "display" in data and data["display"]:
            return data["display"]
        return f"Data retrieved: {json.dumps(data, indent=2)[:500]}..."

    # =========================================================================
    # Run Method - Sub-functions
    # =========================================================================

    async def _process_adk_result(
        self, result: Any, timeout: float = 300.0
    ) -> Tuple[str, List[str], List[Dict[str, Any]]]:
        """
        Process ADK runner result and extract content and tools used.

        Handles both async generator (newer ADK) and coroutine responses.
        Filters events by author to only get agent responses.

        Args:
            result: ADK runner result (async generator or coroutine)
            timeout: Maximum time to wait for events (default 120 seconds)

        Returns:
            Tuple of (content string, list of tools used, list of tool responses)
        """
        import asyncio
        import sys
        import time as time_module
        from collections import Counter

        content_parts = []
        tools_used = []
        tool_responses = []  # Capture tool responses for fallback formatting
        max_events = 100  # Increased to handle tool call sequences
        event_count = 0
        start_time = asyncio.get_event_loop().time()

        # LOOP PROTECTION: Prevent infinite tool call loops (common with local LLMs)
        # Multi-agent orchestrators need more headroom (orchestrator + 3 sub-agents × 2 tools each)
        # For multi-PR analysis (e.g., escalation tickets with 5+ PRs), allow higher same-tool calls
        MAX_TOTAL_TOOL_CALLS = 20
        MAX_SAME_TOOL_CALLS = 8
        tool_call_counter = Counter()
        total_tool_calls = 0
        loop_detected = False
        _t_start = time_module.time()

        # Check if result is an async generator
        if hasattr(result, "__anext__"):
            try:
                async for event in result:
                    # Check timeout
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed > timeout:
                        logger.error("Timeout after %.1fs waiting for ADK events", elapsed)
                        break

                    # Stop if loop detected
                    if loop_detected:
                        print("[LOOP PROTECTION] Stopping event processing", file=sys.stderr)
                        break

                    event_count += 1
                    if event_count > max_events:
                        logger.warning("Max events (%s) reached, stopping processing", max_events)
                        break

                    # Per-event error handling: multi-agent orchestration can
                    # produce varied event types (dicts, sub-agent transfers).
                    # Skip malformed events instead of crashing the loop.
                    try:
                        # Get event metadata
                        if isinstance(event, dict):
                            author = event.get("author")
                            is_partial = event.get("partial", False)
                        else:
                            author = getattr(event, "author", None)
                            is_partial = getattr(event, "partial", False)
                        logger.debug("Event {event_count}: author={author}, partial=%s", is_partial)

                        # Skip user events - we only want agent responses
                        if author == "user":
                            continue

                        # Only skip if partial is explicitly True (not None or False)
                        if is_partial is True:
                            continue

                        # Extract content from event
                        if hasattr(event, "content") and event.content:
                            if hasattr(event.content, "parts"):
                                for part in event.content.parts:
                                    if hasattr(part, "text") and part.text:
                                        content_parts.append(part.text)
                                    # Track tool calls with loop protection
                                    if hasattr(part, "function_call") and part.function_call:
                                        func_name = getattr(part.function_call, "name", None)
                                        if func_name:
                                            tools_used.append(func_name)
                                            total_tool_calls += 1
                                            tool_call_counter[func_name] += 1
                                            print(f"[TOOL #{total_tool_calls}] {func_name}", file=sys.stderr)

                                            # Check loop conditions
                                            if total_tool_calls >= MAX_TOTAL_TOOL_CALLS:
                                                print(
                                                    f"[LOOP PROTECTION] Max tool calls ({MAX_TOTAL_TOOL_CALLS}) reached",
                                                    file=sys.stderr,
                                                )
                                                loop_detected = True
                                            elif tool_call_counter[func_name] >= MAX_SAME_TOOL_CALLS:
                                                print(
                                                    f"[LOOP PROTECTION] {func_name} called {tool_call_counter[func_name]}x, stopping",
                                                    file=sys.stderr,
                                                )
                                                loop_detected = True
                                    # Capture tool responses (function_response)
                                    if hasattr(part, "function_response") and part.function_response:
                                        try:
                                            fn_resp = part.function_response
                                            response_data = getattr(fn_resp, "response", None)
                                            tool_name = getattr(fn_resp, "name", "unknown")

                                            if response_data:
                                                tool_responses.append(
                                                    {
                                                        "name": tool_name,
                                                        "data": response_data,
                                                    }
                                                )
                                        except (ValueError, TypeError, KeyError):
                                            pass
                            elif isinstance(event.content, str):
                                content_parts.append(event.content)

                        # Direct text attribute
                        if hasattr(event, "text") and event.text:
                            content_parts.append(event.text)

                        # Extract tool calls from event.actions or event.tool_calls
                        if hasattr(event, "actions") and event.actions:
                            actions = event.actions
                            if hasattr(actions, "tool_calls"):
                                for tool_call in actions.tool_calls:
                                    tools_used.append(getattr(tool_call, "name", str(tool_call)))

                        if hasattr(event, "tool_calls"):
                            for tool_call in event.tool_calls:
                                tools_used.append(getattr(tool_call, "name", str(tool_call)))
                    except Exception as event_err:
                        logger.debug("Skipping malformed event #%d: %s", event_count, event_err)
                        continue
            except asyncio.TimeoutError:
                logger.error("AsyncIO timeout during ADK event processing")
            except Exception as e:
                logger.error("Error processing ADK events: %s", e)
        else:
            # It's a coroutine - await it
            response = await result

            # Extract from response object
            if hasattr(response, "events"):
                for event in response.events:
                    # Skip user events
                    author = getattr(event, "author", None)
                    if author == "user":
                        continue

                    if hasattr(event, "content") and event.content:
                        if hasattr(event.content, "parts"):
                            for part in event.content.parts:
                                if hasattr(part, "text") and part.text:
                                    content_parts.append(part.text)
                        elif isinstance(event.content, str):
                            content_parts.append(event.content)

                    if hasattr(event, "text") and event.text:
                        content_parts.append(event.text)

                    if hasattr(event, "tool_calls"):
                        for tool_call in event.tool_calls:
                            tools_used.append(getattr(tool_call, "name", str(tool_call)))

            if hasattr(response, "text"):
                content_parts.append(response.text)
            elif hasattr(response, "output"):
                content_parts.append(str(response.output))

        # Combine all content parts
        content = "\n".join(content_parts) if content_parts else ""

        # Remove duplicate tools
        tools_used = list(dict.fromkeys(tools_used))

        # If LLM didn't generate text but we have tool responses, format them
        # IMPORTANT: Only use the FIRST tool response to avoid mixing unrelated data
        if not content.strip() and tool_responses:
            logger.info("LLM didn't generate text, formatting first tool response")
            content = self._format_tool_responses(tool_responses[:1])  # Only first response

        # Timing log
        _elapsed = round(time_module.time() - _t_start, 2)
        print(f"[TIMING] LLM+Tools: {_elapsed}s | Events: {event_count} | Tools: {tools_used[:3]}", file=sys.stderr)

        return content, tools_used, tool_responses

    def _extract_display_from_tool_responses(self, tool_responses: List[Dict[str, Any]]) -> str:
        """Extract display field from the FIRST tool response only.

        IMPORTANT: Only use the first tool response to avoid mixing data from
        multiple tools. The first tool called is usually the correct one.
        """
        import sys

        if not tool_responses:
            return ""

        # ONLY check the first tool response
        first_response = tool_responses[0]
        tool_name = first_response.get("name", "unknown")
        data = first_response.get("data", {})

        print(f"[DEBUG] First tool response: {tool_name}", file=sys.stderr)

        # Handle ADK/MCP content wrapper format
        # Format: {"content": [{"type": "text", "text": "JSON string"}]}
        if isinstance(data, dict) and "content" in data and isinstance(data["content"], list):
            print("[DEBUG] Unwrapping MCP content wrapper", file=sys.stderr)
            for content_item in data["content"]:
                if isinstance(content_item, dict) and content_item.get("type") == "text":
                    text = content_item.get("text", "")
                    if text:
                        try:
                            inner_data = json.loads(text)
                            if isinstance(inner_data, dict):
                                data = inner_data  # Use unwrapped data
                                print(f"[DEBUG] Unwrapped, keys: {list(data.keys())}", file=sys.stderr)
                        except json.JSONDecodeError:
                            pass

        if isinstance(data, dict) and "display" in data:
            display = data["display"]
            print(f"[DEBUG] Using display from {tool_name} ({len(display)} chars)", file=sys.stderr)
            return display

        print(
            f"[DEBUG] No display field in {tool_name}, keys: {list(data.keys()) if isinstance(data, dict) else type(data)}",
            file=sys.stderr,
        )
        return ""

    def _validate_response(self, response: str) -> Tuple[bool, str, str]:
        """
        Validate LLM response for quality issues.

        Checks for:
        - Placeholder text like "[display field]"
        - Non-English characters (Chinese, Japanese, Korean)
        - Very short garbled responses

        Args:
            response: LLM response string

        Returns:
            Tuple of (is_valid, issue_type, corrected_response)
        """
        import re

        # Check for placeholder text
        placeholder_patterns = [
            r"\[display\s*field",
            r"\[tool\s*response",
            r"\[output\s*from",
            r"\[insert\s*",
        ]
        for pattern in placeholder_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                return False, "placeholder", ""

        # Check for Thai characters
        if re.search(r"[\u0e00-\u0e7f]", response):
            return False, "thai", ""

        # Check for Chinese characters
        if re.search(r"[\u4e00-\u9fff]", response):
            return False, "chinese", ""

        # Check for Japanese characters (Hiragana, Katakana, Kanji)
        if re.search(r"[\u3040-\u30ff]", response):
            return False, "japanese", ""

        # Check for Korean characters
        if re.search(r"[\uac00-\ud7af]", response):
            return False, "korean", ""

        # Check for garbled/very short responses (less than 10 chars, likely garbage)
        if len(response.strip()) < 10 and not response.strip().isdigit():
            # Allow short numeric responses (like counts)
            if not re.match(r"^[\d\s\.,]+$", response.strip()):
                return False, "garbled", ""

        return True, "", response

    def _contains_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        import re

        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _filter_non_english(self, text: str) -> str:
        """
        Filter out non-English text from response.

        Removes lines containing Thai, Chinese, Japanese, Korean characters
        and keeps only English content.

        Args:
            text: Response text that may contain non-English content

        Returns:
            Filtered text with only English content
        """
        import re

        if not text:
            return text

        # Patterns for non-English scripts
        non_english_patterns = [
            r"[\u0e00-\u0e7f]",  # Thai
            r"[\u4e00-\u9fff]",  # Chinese
            r"[\u3040-\u30ff]",  # Japanese (Hiragana, Katakana)
            r"[\uac00-\ud7af]",  # Korean
        ]

        # Check if text contains any non-English characters
        has_non_english = any(re.search(p, text) for p in non_english_patterns)

        if not has_non_english:
            return text

        logger.warning("Filtering non-English content from response")

        # Split into lines and filter
        lines = text.split("\n")
        english_lines = []

        for line in lines:
            # Check if line contains non-English characters
            is_non_english = any(re.search(p, line) for p in non_english_patterns)

            if not is_non_english:
                english_lines.append(line)
            else:
                # Try to extract any English portions from mixed lines
                # Remove non-English character sequences
                cleaned = line
                for pattern in non_english_patterns:
                    cleaned = re.sub(pattern + "+", "", cleaned)

                # Keep if there's meaningful English content left
                cleaned = cleaned.strip()
                if len(cleaned) > 10 and re.search(r"[a-zA-Z]{3,}", cleaned):
                    english_lines.append(cleaned)

        result = "\n".join(english_lines).strip()

        # If we filtered out everything, return a generic message
        if not result or len(result) < 20:
            return "I apologize, but I encountered an issue generating an English response. Please try rephrasing your question."

        return result

    def _deduplicate_response(self, content: str) -> Tuple[str, bool]:
        """
        Detect and remove duplicate content in LLM responses.

        LLMs sometimes repeat the same data multiple times (e.g., listing the same
        repositories 9 times). This function detects such patterns and deduplicates.

        Args:
            content: LLM response string

        Returns:
            Tuple of (deduplicated_content, was_duplicated)
        """
        if not content or len(content) < 200:
            return content, False

        lines = content.split("\n")
        if len(lines) < 10:
            return content, False

        # Strategy 1: Detect repeated numbered lists (1. repo: data, 1. repo: data...)
        # Look for patterns like "1. **device-classification**:" appearing multiple times
        numbered_pattern = re.compile(r"^\d+\.\s+\*\*([^*]+)\*\*:?")
        seen_items = {}
        duplicates_found = False

        for line in lines:
            match = numbered_pattern.match(line.strip())
            if match:
                item_name = match.group(1).lower().strip()
                if item_name in seen_items:
                    seen_items[item_name] += 1
                    if seen_items[item_name] > 1:
                        duplicates_found = True
                else:
                    seen_items[item_name] = 1

        # If we found significant duplication (same item 3+ times), deduplicate
        if duplicates_found and any(count >= 3 for count in seen_items.values()):
            logger.warning("[Dedup] Detected duplicate items: %s", {k: v for k, v in seen_items.items() if v > 1})

            # Strategy: Keep only the first occurrence of each numbered item
            deduped_lines = []
            seen_in_output = set()
            skip_until_next_item = False

            for line in lines:
                match = numbered_pattern.match(line.strip())
                if match:
                    item_name = match.group(1).lower().strip()
                    if item_name in seen_in_output:
                        skip_until_next_item = True
                        continue
                    else:
                        seen_in_output.add(item_name)
                        skip_until_next_item = False

                if not skip_until_next_item:
                    deduped_lines.append(line)
                elif line.strip() == "":
                    # Empty lines can pass through
                    pass

            deduped_content = "\n".join(deduped_lines)
            logger.info("[Dedup] Reduced response from %d to %d lines", len(lines), len(deduped_lines))
            return deduped_content, True

        # Strategy 2: Detect repeated section blocks (### Summary appearing multiple times)
        section_pattern = re.compile(r"^###?\s+(.+)$")
        section_counts = {}

        for line in lines:
            match = section_pattern.match(line.strip())
            if match:
                section_title = match.group(1).lower().strip()
                section_counts[section_title] = section_counts.get(section_title, 0) + 1

        # If same section appears 3+ times, it's likely a loop
        repeated_sections = {k: v for k, v in section_counts.items() if v >= 3}
        if repeated_sections:
            logger.warning("[Dedup] Detected repeated sections: %s", repeated_sections)

            # Keep only first occurrence of each section
            deduped_lines = []
            seen_sections = set()
            skip_section = False

            for line in lines:
                match = section_pattern.match(line.strip())
                if match:
                    section_title = match.group(1).lower().strip()
                    if section_title in repeated_sections:
                        if section_title in seen_sections:
                            skip_section = True
                            continue
                        else:
                            seen_sections.add(section_title)
                            skip_section = False
                    else:
                        skip_section = False

                if not skip_section:
                    deduped_lines.append(line)

            deduped_content = "\n".join(deduped_lines)
            logger.info("[Dedup] Reduced response from %d to %d lines (sections)", len(lines), len(deduped_lines))
            return deduped_content, True

        return content, False

    def _format_tool_responses(self, tool_responses: List[Dict[str, Any]]) -> str:
        """Format tool responses when LLM doesn't generate text.

        Priority:
        1. Use 'display' field if available (pre-formatted by tool)
        2. Use 'message' field for simple summary
        3. Fall back to generic JSON display
        """
        lines = []

        for resp in tool_responses:
            name = resp.get("name", "unknown")
            data = resp.get("data", {})

            if not isinstance(data, dict):
                lines.append(str(data))
                continue

            # Unwrap ADK/MCP content wrapper if present
            # Format: {"content": [{"type": "text", "text": "JSON string"}]}
            if "content" in data and isinstance(data["content"], list):
                for content_item in data["content"]:
                    if isinstance(content_item, dict) and content_item.get("type") == "text":
                        text = content_item.get("text", "")
                        if text:
                            try:
                                # Parse the inner JSON to get actual tool response
                                inner_data = json.loads(text)
                                if isinstance(inner_data, dict):
                                    data = inner_data  # Use unwrapped data
                            except json.JSONDecodeError:
                                # Not JSON, use the text directly
                                lines.append(text)
                                continue

            # Check for error first
            if "error" in data:
                lines.append(f"**Error:** {data['error']}")
                continue

            # Priority 1: Use pre-formatted 'display' field if available
            if "display" in data and data["display"]:
                lines.append(data["display"])
                continue

            # Priority 2: Use 'message' field for simple summary
            if "message" in data and data["message"]:
                lines.append(data["message"])
                continue

            # Priority 3: Generic JSON display (last resort)
            lines.append(f"**Tool Response ({name}):**")
            # Show key metrics if available
            key_fields = ["total", "count", "status", "score", "on_time_rate"]
            summary_parts = []
            for field in key_fields:
                if field in data:
                    summary_parts.append(f"{field}: {data[field]}")
            if summary_parts:
                lines.append(", ".join(summary_parts))
            else:
                lines.append(f"```json\n{json.dumps(data, indent=2, default=str)[:500]}\n```")

        return "\n".join(lines) if lines else ""

    def _create_greeting_response(
        self,
        session_id: str,
        agent_name: str,
        release_context: str,
    ) -> AgentResponse:
        """Create response for greeting messages."""
        return AgentResponse(
            content=self._get_greeting_response(),
            session_id=session_id,
            agent_name=agent_name,
            tools_used=[],
            metadata={
                "release": release_context or DEFAULT_RELEASE,
                "timestamp": datetime.now().isoformat(),
                "greeting": True,
            },
        )

    def _validate_tool_for_query(self, query: str, tools_used: List[str]) -> Tuple[bool, str]:
        """
        Validate that the correct tool was called for the query type.

        Helps detect when LLM called the wrong tool (e.g., GitHub commits for IRR status).

        Args:
            query: Original user query
            tools_used: List of tools that were called

        Returns:
            Tuple of (is_valid, expected_tool_hint)
        """
        if not tools_used:
            return True, ""

        query_lower = query.lower()

        # Define expected tools for certain query patterns
        QUERY_TOOL_MAPPINGS = {
            # IRR/milestone queries should use JIRA milestone tools
            "irr": ["jira_get_milestone_status", "jira_get_release_readiness_score"],
            "irr status": ["jira_get_milestone_status"],
            "milestone status": ["jira_get_milestone_status"],
            "branch cut status": ["jira_get_milestone_status"],
            "final build status": ["jira_get_milestone_status"],
            # Release readiness/RRS queries
            "green": ["jira_get_release_readiness_score"],
            "red": ["jira_get_release_readiness_score"],
            "release status": ["jira_get_release_readiness_score", "jira_get_milestone_status"],
            "rrs": ["jira_get_release_readiness_score"],
            # Bug queries should use JIRA bug tools
            "critical bugs": ["jira_get_critical_bugs"],
            "blocker": ["jira_get_critical_bugs"],
            "p0": ["jira_get_critical_bugs"],
            # Date queries should use calendar
            "when is": ["calendar_get_release_dates"],
            "release date": ["calendar_get_release_dates"],
            # Commit queries should use GitHub
            "commits": [
                "github_get_commits",
                "github_get_commits_after_branch_cut",
            ],
            # Jenkins pipeline/build queries
            "pipeline runs": ["jenkins_get_job_builds", "jenkins_get_pipelines"],
            "builds for": ["jenkins_get_job_builds"],
            "build history": ["jenkins_get_job_builds"],
            "last builds": ["jenkins_get_job_builds"],
            "list pipelines": ["jenkins_get_pipelines"],
            "pipeline status": ["jenkins_get_pipelines"],
            "tfa": ["jenkins_get_test_failure_analysis"],
            "why did build": ["jenkins_get_test_failure_analysis"],
            "golden regression": ["jenkins_get_golden_regression"],
        }

        # Check each pattern
        for pattern, expected_tools in QUERY_TOOL_MAPPINGS.items():
            if pattern in query_lower:
                # Check if any of the expected tools were used
                if any(tool in expected_tools for tool in tools_used):
                    return True, ""

                # Wrong tool was called
                # But only warn if query is a clear match (not just contains the pattern)
                # For example, "IRR status" clearly expects milestone tool
                if pattern in ["irr status", "milestone status", "branch cut status"]:
                    logger.warning(
                        "[ToolValidation] Query '%s' expected tools %s but got %s",
                        query[:50],
                        expected_tools,
                        tools_used,
                    )
                    return False, expected_tools[0]

        return True, ""

    # =========================================================================
    # Main Run Method
    # =========================================================================

    async def run(
        self,
        agent: Any,
        message: str,
        session_id: str = "default",
        release_context: str = None,
    ) -> AgentResponse:
        """
        Run agent with MCP tools via ADK.

        Args:
            agent: ADK agent with MCP toolsets (or MultiAgentOrchestrator or Router)
            message: User message
            session_id: Session identifier
            release_context: Optional release ID (e.g., "R134")

        Returns:
            AgentResponse with content and metadata
        """
        try:
            # Step 1: Preprocess query if enabled
            processed_message = message
            if self.settings.use_query_preprocessing:
                from core.query_processor import get_processor

                processor = get_processor()
                processed_message = processor.process(message)
                if processed_message != message:
                    logger.info("[QueryPreprocessor] '%s' → '%s'", message[:50], processed_message[:50])

            # Step 2: Route to specialized agent
            # Multi-agent with routing (either pattern-based or LLM-based):
            # 1. Router selects specialized agent
            # 2. Specialized agent uses LLM to pick MCP tools
            routing_confidence = 1.0  # Default for pattern-based routing

            if hasattr(agent, "route"):
                # Check if it's async route (SemanticRouter) or sync (AgentRouter)
                if asyncio.iscoroutinefunction(agent.route):
                    selected_agent, routing_confidence = await agent.route(processed_message)
                    logger.info(
                        "[SemanticRouter] Selected: %s (confidence: %.2f)", selected_agent.name, routing_confidence
                    )
                elif hasattr(agent, "route_async"):
                    # SemanticRouter with sync wrapper - use async method directly
                    selected_agent, routing_confidence = await agent.route_async(processed_message)
                    logger.info(
                        "[SemanticRouter] Selected: %s (confidence: %.2f)", selected_agent.name, routing_confidence
                    )
                else:
                    # Pattern-based AgentRouter - returns just the agent
                    selected_agent = agent.route(processed_message)
                    logger.info("[PatternRouter] Selected: %s", selected_agent.name)
            else:
                selected_agent = agent
                logger.info("[Agent] Using: %s", agent.name)

            if self._is_greeting(processed_message):
                return self._create_greeting_response(session_id, selected_agent.name, release_context)

            # PRE-ROUTING: For common queries, bypass LLM and call tools directly
            # This is faster but bypasses the LLM's tool selection logic
            # Disable with ADK_USE_PREROUTING=false to always use LLM
            if self.settings.use_prerouting:
                pre_route_response = await self._pre_route_query(
                    selected_agent, processed_message, session_id, release_context
                )
                if pre_route_response:
                    logger.info("[PreRoute] Bypassed LLM for: %s", processed_message[:50])
                    return pre_route_response

            logger.info("[MCP] Processing: '%s' (agent: %s)", processed_message[:50], selected_agent.name)

            # Step 3: Let LLM decide which tool to use
            session = await self._get_or_create_session(selected_agent, session_id, release_context)
            runner = self._get_runner(selected_agent)

            user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=processed_message)])

            # Retry logic for transient network errors (common with Ollama/SGL)
            import sys as _sys

            max_retries = 3
            content = ""
            tools_used = []
            tool_responses = []
            last_error = None

            for attempt in range(max_retries):
                try:
                    result = runner.run_async(
                        user_id=session_id,
                        session_id=session.id,
                        new_message=user_content,
                    )

                    content, tools_used, tool_responses = await self._process_adk_result(result)

                    # If we got content or tool responses, we're done
                    if content.strip() or tool_responses:
                        break

                    # Empty response might be transient - retry
                    if attempt < max_retries - 1:
                        logger.warning("[MCP] Empty response on attempt %d, retrying...", attempt + 1)
                        await asyncio.sleep(1)  # Brief delay before retry

                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    # Check for transient network errors (retry these)
                    if any(
                        x in error_msg.lower()
                        for x in [
                            "failed to execute http request",
                            "connection closed",
                            "timeout",
                            "connection reset",
                            "server disconnected",
                        ]
                    ):
                        if attempt < max_retries - 1:
                            logger.warning(
                                "[MCP] Transient error on attempt %d: %s, retrying...", attempt + 1, type(e).__name__
                            )
                            print(
                                f"[RETRY {attempt + 1}/{max_retries}] {type(e).__name__}: {error_msg[:100]}",
                                file=_sys.stderr,
                            )
                            await asyncio.sleep(1 + attempt)  # Exponential backoff
                            continue
                    # Non-transient error - don't retry
                    raise

            # If all retries failed with an error, raise the last one
            if not content.strip() and not tool_responses and last_error:
                raise last_error

            print(f"[DEBUG] Got {len(tool_responses)} tool_responses, content length: {len(content)}", file=sys.stderr)
            for i, tr in enumerate(tool_responses):
                tr_name = tr.get("name", "unknown")
                tr_data = tr.get("data", {})
                has_display = isinstance(tr_data, dict) and "display" in tr_data
                print(f"[DEBUG] Response {i}: {tr_name}, has_display: {has_display}", file=sys.stderr)
                # Show data structure
                if isinstance(tr_data, dict):
                    keys = list(tr_data.keys())[:10]
                    print(f"[DEBUG]   Keys: {keys}", file=sys.stderr)
                else:
                    print(
                        f"[DEBUG]   Data type: {type(tr_data).__name__}, preview: {str(tr_data)[:200]}", file=sys.stderr
                    )

            # Log tool usage
            if tools_used and not content.strip():
                logger.warning("[MCP] Tool %s called but no LLM response - using fallback formatter", tools_used)
            elif tools_used:
                logger.info("[MCP] Tools called: %s, response length: %s", tools_used, len(content))

            display_content = None
            if tool_responses:
                print(f"[DEBUG] {len(tool_responses)} tool responses, extracting display from first", file=sys.stderr)
                display_content = self._extract_display_from_tool_responses(tool_responses)
                if display_content:
                    # ALWAYS use display field - ignore LLM text completely
                    print(
                        f"[FIX] Using first tool's display ({len(display_content)} chars), ignoring LLM text ({len(content)} chars)",
                        file=sys.stderr,
                    )
                    logger.info(
                        "[MCP] Using tool's display field (%s chars) over LLM text (%s chars)",
                        len(display_content),
                        len(content),
                    )
                    content = display_content
                else:
                    print("[DEBUG] No display field found, using LLM text", file=sys.stderr)

            # CLEANUP: Remove raw tool response sections that LLM might have included
            # Pattern matches: **Tool Response (tool_name):** followed by ```json blocks
            tool_response_pattern = r"\*\*Tool Response \([^)]+\):\*\*\s*```(?:json)?\s*[\s\S]*?```"
            if re.search(tool_response_pattern, content):
                print("[CLEANUP] Removing raw tool response sections from output", file=sys.stderr)
                content = re.sub(tool_response_pattern, "", content).strip()

            # Also remove any trailing partial JSON that got cut off
            partial_json_pattern = r"\*\*Tool Response \([^)]+\):\*\*\s*```(?:json)?\s*\{[\s\S]*$"
            if re.search(partial_json_pattern, content):
                print("[CLEANUP] Removing partial/incomplete tool response from output", file=sys.stderr)
                content = re.sub(partial_json_pattern, "", content).strip()

            # Step 4a: Apply deduplication if LLM generated text (not using display field)
            if not display_content and content.strip():
                deduped_content, was_duplicated = self._deduplicate_response(content)
                if was_duplicated:
                    logger.info("[Dedup] Response contained duplicates, using deduped version")
                    content = deduped_content

                    # If dedup removed a lot, try display field again as fallback
                    if len(deduped_content) < len(content) * 0.3 and tool_responses:
                        display_content = self._extract_display_from_tool_responses(tool_responses)
                        if display_content:
                            logger.info("[Dedup] Dedup removed too much, using display field instead")
                            content = display_content

            # Validate response for quality issues (placeholder text, non-English, garbled)
            is_valid, issue_type, _ = self._validate_response(content)
            if not is_valid:
                logger.warning("[Validation] Response failed validation: %s", issue_type)

                # If we have tool responses, try to extract display again
                if tool_responses:
                    fallback_content = self._format_tool_responses(tool_responses)
                    if fallback_content:
                        logger.info("[Validation] Using formatted tool response as fallback")
                        content = fallback_content
                else:
                    # No tool response to fall back to
                    if issue_type in ("chinese", "japanese", "korean"):
                        content = "I apologize, but I can only respond in English. Let me try again with your request."
                    elif issue_type == "placeholder":
                        content = "I encountered an issue processing the response. Please try your request again."
                    elif issue_type == "garbled":
                        content = "I had trouble generating a response. Please rephrase your question."

            # Validate that tool was called for data queries
            is_data_query = self._is_data_query(message)

            # Check if LLM is asking for clarification instead of calling tools
            is_asking_clarification = self._is_asking_clarification(content)

            if is_data_query and (not tools_used or is_asking_clarification):
                # LLM didn't call a tool for a data query - this is a problem
                logger.warning(
                    "[MCP] No tool called for data query: %s (clarification: %s)", message[:50], is_asking_clarification
                )

                # Try to auto-call the appropriate tool based on query patterns
                auto_response = await self._auto_call_tool(selected_agent, message, session_id, release_context)
                if auto_response:
                    logger.info("[MCP] Auto-tool-call succeeded for: %s", message[:50])
                    content = auto_response
                    tools_used = ["auto_tool_call"]
                elif not self._response_contains_data(content):
                    content = (
                        "I wasn't able to retrieve the data you requested. "
                        "Please try asking in a different way, for example:\n\n"
                        "- 'What's the IRR status?'\n"
                        "- 'Show me critical bugs'\n"
                        "- 'Is R134 green?'\n"
                        "- 'Any commits before branch cut?'"
                    )

            # Handle empty response
            if not content.strip():
                content = "I processed your request but couldn't generate a response. Please try rephrasing."

            # Filter out non-English content (Thai, Chinese, etc.)
            content = self._filter_non_english(content)

            # Log tool usage for debugging
            if tools_used:
                logger.info("[MCP] Tools used: %s", tools_used)

            return AgentResponse(
                content=content,
                session_id=session_id,
                agent_name=selected_agent.name,
                tools_used=tools_used,
                metadata={
                    "release": session.state.get("release"),
                    "timestamp": datetime.now().isoformat(),
                    "tool_called": bool(tools_used),
                },
            )

        except Exception as e:
            logger.error("Agent run error: %s", e)
            import traceback

            traceback.print_exc()
            agent_name = selected_agent.name if "selected_agent" in locals() else getattr(agent, "name", "unknown")
            return AgentResponse(
                content=f"I encountered an error: {str(e)}. Please try again.",
                session_id=session_id,
                agent_name=agent_name,
                error=str(e),
            )

    async def run_stream(
        self,
        agent: Any,
        message: str,
        session_id: str = "default",
        release_context: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run agent with streaming response.

        Args:
            agent: ADK agent to run
            message: User message
            session_id: Session identifier
            release_context: Optional release ID

        Yields:
            Dict with type (metadata, token, tool_call, done) and content
        """
        try:
            session = await self._get_or_create_session(agent, session_id, release_context)
            runner = self._get_runner(agent)

            # Create proper ADK message content
            user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])

            # Yield metadata first
            yield {
                "type": "metadata",
                "session_id": session_id,
                "agent": agent.name,
                "release": session.state.get("release"),
            }

            # Stream the response
            async for event in runner.run_stream_async(
                user_id=session_id,
                session_id=session.id,
                new_message=user_content,
            ):
                if hasattr(event, "text") and event.text:
                    yield {
                        "type": "token",
                        "content": event.text,
                    }

                if hasattr(event, "tool_calls"):
                    for tool_call in event.tool_calls:
                        yield {
                            "type": "tool_call",
                            "name": tool_call.name,
                            "arguments": getattr(tool_call, "arguments", {}),
                        }

                if hasattr(event, "agent_transfer"):
                    yield {
                        "type": "transfer",
                        "to_agent": event.agent_transfer,
                    }

            yield {
                "type": "done",
                "session_id": session_id,
            }

        except Exception as e:
            logger.error("Streaming error: %s", e)
            yield {
                "type": "error",
                "content": str(e),
            }

    def clear_session(self, session_id: str):
        """Clear a specific session."""
        keys_to_remove = [k for k in self._sessions if k.endswith(f":{session_id}")]
        for key in keys_to_remove:
            del self._sessions[key]


# Singleton runner
_runner: Optional[AgentRunner] = None


def get_runner() -> AgentRunner:
    """Get or create agent runner singleton."""
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner

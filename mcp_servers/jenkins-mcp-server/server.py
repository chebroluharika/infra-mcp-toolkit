# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.0.0",
#   "httpx>=0.27.0",
#   "python-dotenv>=1.0.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
Jenkins MCP Server
Exposes Jenkins API as MCP tools for AI agents

Usage:
    uv run server.py

Architecture:
    MCP Tools -> Backend API -> JenkinsClient -> Jenkins API

    All tools call the backend API endpoints, which use the direct
    JenkinsClient for authentication and data fetching.

Environment Variables:
    API_BASE_URL - Backend API URL (default: http://localhost:8000)
"""

import os
from typing import Any, Dict

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("jenkins-mcp-server")


# =============================================================================
# MCP Tools - All call Backend API
# =============================================================================


@mcp.tool()
async def jenkins_get_pipelines() -> Dict[str, Any]:
    """
    List Jenkins CI/CD pipeline build results.

    ONLY use for:
    - "list pipelines" or "show pipelines"
    - "CI/CD builds" or "Jenkins jobs"
    - "pipeline health"

    DO NOT use for:
    - "IRR status" → use jira_get_milestone_status
    - "Is R134 green?" → use jira_get_release_readiness_score
    - Any JIRA-related queries

    Returns: List of pipeline names, build status, and run times.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jenkins/pipelines")

            if response.status_code != 200:
                return {
                    "error": f"Backend returned {response.status_code}",
                    "message": "Failed to fetch pipeline data",
                }

            data = response.json()

            # Build display field for AI Assistant
            overall = data.get("overall", {})
            pipelines = data.get("pipelines", [])

            health_pct = overall.get("healthPercent", 0)
            total_pipes = overall.get("totalPipelines", 0)
            passing = overall.get("passing", 0)
            failing = overall.get("failing", 0)
            unstable = overall.get("unstable", 0)
            display_lines = [
                "## Jenkins Pipeline Status",
                "",
                f"**Health:** {health_pct}%",
                f"**Total Pipelines:** {total_pipes}",
                f"**Passing:** {passing} | **Failing:** {failing} | **Unstable:** {unstable}",
                "",
            ]

            if pipelines:
                display_lines.append("| Pipeline | Status | Last Run | Duration |")
                display_lines.append("|----------|--------|----------|----------|")
                for pipeline in pipelines[:10]:
                    p_status = pipeline.get("status")
                    if p_status == "success":
                        status_icon = "✅"
                    elif p_status == "failed":
                        status_icon = "❌"
                    else:
                        status_icon = "⚠️"
                    p_name = pipeline.get("name", "Unknown")
                    p_status_str = pipeline.get("status", "unknown")
                    p_last_run = pipeline.get("lastRun", "")
                    p_duration = pipeline.get("duration", "")
                    display_lines.append(f"| {p_name} | {status_icon} {p_status_str} | {p_last_run} | {p_duration} |")

            data["display"] = "\n".join(display_lines)
            data["source"] = "jenkins-mcp"
            return data

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err), "message": "Failed to connect to backend"}


@mcp.tool()
async def jenkins_get_job_info(job_name: str) -> Dict[str, Any]:
    """
    Get information about a specific Jenkins job.

    Args:
        job_name: Name of the Jenkins job

    Returns job details including last build info.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Use pipelines endpoint and filter
            response = await client.get(f"{api_base}/api/jenkins/pipelines")

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            pipelines = data.get("pipelines", [])

            # Find matching job
            for pipeline in pipelines:
                if pipeline.get("name") == job_name or pipeline.get("fullName") == job_name:
                    p_name = pipeline.get("name")
                    p_status = pipeline.get("status")
                    p_build = pipeline.get("buildNumber")
                    return {
                        "job": pipeline,
                        "display": f"**{p_name}**: {p_status} (Build #{p_build})",
                        "source": "jenkins-mcp",
                    }

            return {"error": f"Job '{job_name}' not found", "source": "jenkins-mcp"}

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


@mcp.tool()
async def jenkins_get_job_builds(job_name: str, limit: int = 10) -> Dict[str, Any]:
    """
    Get build history for a specific Jenkins job - shows last N builds.

    Use when asked about:
    - "last 10 builds for your-product-backend-test"
    - "build history for X pipeline"
    - "recent builds for job Y"

    Args:
        job_name: Name of the Jenkins job (e.g., "your-product-backend-test")
        limit: Number of builds to return (default 10)

    Returns list of builds with status, timestamp, and duration.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # First try exact match
            response = await client.get(f"{api_base}/api/jenkins/pipelines/{job_name}/builds")

            # If not found, try to find matching job name (case-insensitive)
            if response.status_code == 404:
                # Get all pipelines and find matching job
                pipelines_resp = await client.get(f"{api_base}/api/jenkins/pipelines")
                if pipelines_resp.status_code == 200:
                    pipelines = pipelines_resp.json().get("pipelines", [])
                    job_name_lower = job_name.lower().replace(" ", "_").replace("-", "_")

                    for pipeline in pipelines:
                        p_name = pipeline.get("name", "")
                        p_name_normalized = p_name.lower().replace(" ", "_").replace("-", "_")

                        # Case-insensitive match or partial match
                        if p_name_normalized == job_name_lower or job_name_lower in p_name_normalized:
                            # Found matching job, retry with correct name
                            job_name = p_name
                            response = await client.get(f"{api_base}/api/jenkins/pipelines/{p_name}/builds")
                            break

            if response.status_code == 404:
                # Get available pipelines to suggest
                pipelines_resp = await client.get(f"{api_base}/api/jenkins/pipelines")
                available = []
                if pipelines_resp.status_code == 200:
                    pipelines = pipelines_resp.json().get("pipelines", [])
                    available = [p.get("name") for p in pipelines[:10]]

                return {
                    "error": f"Job '{job_name}' not found",
                    "available_pipelines": available,
                    "hint": "Use 'list all pipelines' to see exact job names",
                    "display": f"❌ Job '{job_name}' not found.\n\n**Available pipelines:**\n"
                    + "\n".join(f"- {p}" for p in available[:10]),
                    "source": "jenkins-mcp",
                }

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            builds = data.get("builds", [])[:limit]

            # Format display
            display_lines = [
                f"## Build History: {job_name}",
                "",
                f"**Showing last {len(builds)} builds**",
                "",
                "| # | Build | Status | Time | Duration |",
                "|---|-------|--------|------|----------|",
            ]

            for idx, build in enumerate(builds, 1):
                b_status = build.get("status")
                if b_status == "success":
                    status_icon = "✅"
                elif b_status == "failed":
                    status_icon = "❌"
                else:
                    status_icon = "🔄"
                b_num = build.get("buildNumber")
                b_time = build.get("timestamp")
                b_dur = build.get("duration")
                display_lines.append(f"| {idx} | #{b_num} | {status_icon} {b_status} | {b_time} | {b_dur} |")

            # Summary
            success = sum(1 for bld in builds if bld.get("status") == "success")
            failed = sum(1 for bld in builds if bld.get("status") == "failed")
            display_lines.append("")
            display_lines.append(f"**Summary:** {success} ✅ success, {failed} ❌ failed")

            return {
                "job": job_name,
                "builds": builds,
                "summary": {"success": success, "failed": failed, "total": len(builds)},
                "display": "\n".join(display_lines),
                "source": "jenkins-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


@mcp.tool()
async def jenkins_get_build_info(job_name: str, build_number: int) -> Dict[str, Any]:
    """
    Get information about a specific Jenkins build.

    Args:
        job_name: Name of the Jenkins job
        build_number: Build number to fetch

    Returns build details including status and duration.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Use TFA endpoint which has build info
            response = await client.get(f"{api_base}/api/jenkins/tfa/{job_name}/{build_number}")

            if response.status_code == 404:
                return {"error": f"Build #{build_number} not found for {job_name}"}

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            summary = data.get("summary", {})

            passed = summary.get("passed", 0)
            failed_cnt = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
            display = f"**{job_name} Build #{build_number}**\n"
            display += f"Tests: {passed} passed, {failed_cnt} failed, {skipped} skipped"

            return {
                "job": job_name,
                "buildNumber": build_number,
                "summary": summary,
                "display": display,
                "source": "jenkins-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


@mcp.tool()
async def jenkins_get_test_report(job_name: str, build_number: int) -> Dict[str, Any]:
    """
    Get test report for a Jenkins build including failed test details.

    Args:
        job_name: Name of the Jenkins job
        build_number: Build number to fetch

    Returns test results with pass/fail counts and failed test details.

    NOTE: For detailed TFA with AI analysis, use jenkins_get_test_failure_analysis instead.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Use the builds endpoint to get basic test info, avoiding circular TFA call
            response = await client.get(f"{api_base}/api/jenkins/pipelines/{job_name}/builds", params={"num_builds": 1})

            if response.status_code == 404:
                return {"error": f"Job '{job_name}' not found"}

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            builds = data.get("builds", [])

            # Find the specific build
            target_build = None
            for bld in builds:
                if bld.get("buildNumber") == build_number:
                    target_build = bld
                    break

            if not target_build and builds:
                # If specific build not found, return info about available builds
                return {
                    "error": f"Build #{build_number} not in recent builds. Latest: #{builds[0].get('buildNumber')}",
                    "available_builds": [b.get("buildNumber") for b in builds[:5]],
                    "note": "Use jenkins_get_test_failure_analysis for detailed test failure analysis.",
                }

            display_lines = [
                f"## Test Report: {job_name} Build #{build_number}",
                "",
                f"**Status:** {target_build.get('status', 'unknown') if target_build else 'unknown'}",
                "",
                "**Note:** For detailed test failure analysis with AI-powered root cause detection,",
                "use `jenkins_get_test_failure_analysis` tool.",
            ]

            return {
                "job": job_name,
                "buildNumber": build_number,
                "status": target_build.get("status") if target_build else "unknown",
                "display": "\n".join(display_lines),
                "note": "Use jenkins_get_test_failure_analysis for detailed TFA with failed tests",
                "source": "jenkins-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


@mcp.tool()
async def jenkins_get_console_output(job_name: str, build_number: int) -> Dict[str, Any]:
    """
    Get console output for a Jenkins build with error lines extracted.

    Args:
        job_name: Name of the Jenkins job
        build_number: Build number to fetch

    Returns last 100 lines of console output and extracted error lines.
    """
    # Console output is typically used for TFA analysis
    # Return a message directing to TFA endpoint
    return {
        "message": (
            f"Use jenkins_get_test_report for {job_name} build #{build_number} "
            "to get test analysis with console context."
        ),
        "source": "jenkins-mcp",
    }


@mcp.tool()
async def jenkins_get_golden_regression(num_builds: int = 10) -> Dict[str, Any]:
    """
    Get Endpoint PDV Runs / Golden Regression Suite data - builds grouped by stack.

    Use this tool when the user asks about:
    - "Endpoint PDV runs" or "PDV runs" or "PDV status"
    - "golden regression" or "golden regression status"
    - "PDV pipeline runs" or "endpoint PDV builds"
    - "show PDV runs by stack"

    This returns aggregated data across all stacks (fr4, sin2, sjc1, dfw3, etc.)

    Args:
        num_builds: Number of recent builds per stack to fetch (default 10)

    Returns build history grouped by stack with success rates and health metrics.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jenkins/golden-regression")

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            builds = data.get("builds", [])
            stats = data.get("overallStats", {})

            total_builds = stats.get("totalBuilds", 0)
            success_builds = stats.get("successBuilds", 0)
            failed_builds = stats.get("failedBuilds", 0)
            display_lines = [
                "## Golden Regression Suite",
                "",
                f"**Success Rate:** {stats.get('successRate', 0)}%",
                f"**Total:** {total_builds} | **Success:** {success_builds} | **Failed:** {failed_builds}",
                "",
            ]

            if builds:
                display_lines.append("| Build | Status | Passed | Failed | Health |")
                display_lines.append("|-------|--------|--------|--------|--------|")
                for bld in builds[:num_builds]:
                    b_status = bld.get("status")
                    if b_status == "success":
                        status_icon = "✅"
                    elif b_status == "failed":
                        status_icon = "❌"
                    else:
                        status_icon = "⚠️"
                    b_num = bld.get("buildNumber", "")
                    b_passed = bld.get("passed", 0)
                    b_failed = bld.get("failed", 0)
                    b_health = bld.get("healthPercent", 0)
                    display_lines.append(f"| #{b_num} | {status_icon} | {b_passed} | {b_failed} | {b_health}% |")

            return {
                "builds": builds[:num_builds],
                "summary": stats,
                "display": "\n".join(display_lines),
                "source": "jenkins-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


@mcp.tool()
async def jenkins_get_test_failure_analysis(  # pylint: disable=too-many-locals
    job_name: str, build_number: int
) -> Dict[str, Any]:
    """
    Get Test Failure Analysis (TFA) for ANY Jenkins build - uses RAG + LLM for intelligent analysis.

    **CRITICAL**: ALWAYS call this when user asks about WHY a build failed or wants failure details!

    This provides:
    - Failed test names and error messages
    - AI-powered root cause analysis (using LLM + RAG)
    - Similar past failures from knowledge base
    - Intelligent recommendations for fixing

    Use when asked:
    - "Why did build X fail?" → ALWAYS call this! ⚠️
    - "What's the error in build Y?" → ALWAYS call this! ⚠️
    - "Reason for failure in job Z?" → ALWAYS call this! ⚠️
    - "How to fix build failure?" → ALWAYS call this! ⚠️

    Args:
        job_name: Jenkins job name (e.g., "your-product-backend-test")
        build_number: Build number to analyze (e.g., 464)

    Returns:
        Comprehensive TFA with root causes, failed tests, and fix recommendations
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jenkins/tfa/{job_name}/{build_number}")

            if response.status_code == 404:
                return {
                    "error": f"No test report found for {job_name} build #{build_number}",
                    "note": "Build may not have test results or doesn't exist",
                }

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            summary = data.get("summary", {})
            failed_tests = data.get("failedTests", [])
            root_causes = data.get("rootCauses", [])
            recommendations = data.get("recommendations", [])
            analysis_type = data.get("analysisType", "pattern_based")
            analysis_engine = data.get("analysisEngine", "pattern_based")

            # Build formatted display for AI Assistant
            passed_cnt = summary.get("passed", 0)
            failed_cnt = summary.get("failed", 0)
            skipped_cnt = summary.get("skipped", 0)
            display_lines = [
                f"## 🔍 Test Failure Analysis: {job_name} #{build_number}",
                "",
                f"**Analysis Engine:** {analysis_engine}",
                f"**Tests:** {passed_cnt} ✅, {failed_cnt} ❌, {skipped_cnt} ⏭️",
                "",
            ]

            # Root causes with severity and confidence
            if root_causes:
                display_lines.extend(
                    [
                        "### 🎯 Root Causes (AI-Analyzed)",
                        "",
                    ]
                )
                for root_cause in root_causes:
                    severity = root_cause.get("severity", "medium")
                    severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "🟡")
                    confidence = root_cause.get("confidence", "medium")
                    rc_type = root_cause.get("type", "unknown").upper()
                    rc_desc = root_cause.get("description", "No description")
                    display_lines.append(f"{severity_emoji} **{rc_type}** (Confidence: {confidence})")
                    display_lines.append(f"   └─ {rc_desc}")
                display_lines.append("")

            # Failed test details
            if failed_tests:
                display_lines.extend(
                    [
                        "### ❌ Failed Tests",
                        "",
                    ]
                )
                for idx, test in enumerate(failed_tests[:5], 1):
                    test_name = test.get("name", "Unknown")
                    error_msg = test.get("errorMessage", "No error message")[:150]
                    analysis = test.get("analysis", {})

                    display_lines.append(f"**{idx}. {test_name}**")
                    if analysis.get("root_cause"):
                        display_lines.append(f"   • Root cause: {analysis['root_cause']}")
                    else:
                        display_lines.append(f"   • Error: {error_msg}")

                    # Show similar failures if available
                    similar = test.get("similarFailures", [])
                    if similar:
                        display_lines.append(f"   • Similar past failures: {len(similar)} found")
                    display_lines.append("")

            # Recommendations
            if recommendations:
                display_lines.extend(
                    [
                        "### 💡 Recommended Actions",
                        "",
                    ]
                )
                for idx, rec in enumerate(recommendations, 1):
                    display_lines.append(f"{idx}. {rec}")
                display_lines.append("")

            return {
                "job": job_name,
                "buildNumber": build_number,
                "summary": summary,
                "rootCauses": root_causes,
                "failedTests": failed_tests,
                "recommendations": recommendations,
                "analysisType": analysis_type,
                "analysisEngine": analysis_engine,
                "display": "\n".join(display_lines),
                "source": "jenkins-tfa-rag",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": f"TFA analysis failed: {str(err)}"}


@mcp.tool()
async def jenkins_get_golden_regression_tfa(build_number: int) -> Dict[str, Any]:
    """
    Get Test Failure Analysis for a specific Golden Regression build.

    Use when asked about:
    - Why did a golden regression build fail?
    - What tests failed in build X?
    - Root cause of failures

    Args:
        build_number: Build number to analyze

    Returns failed tests with error details and recommendations.
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            response = await client.get(f"{api_base}/api/jenkins/golden-regression/{build_number}/tfa")

            if response.status_code == 404:
                return {"error": f"No test report found for build #{build_number}"}

            if response.status_code != 200:
                return {"error": f"Backend returned {response.status_code}"}

            data = response.json()
            summary = data.get("summary", {})
            failed_tests = data.get("failedTests", [])
            root_causes = data.get("rootCauses", [])
            recommendations = data.get("recommendations", [])

            passed = summary.get("passed", 0)
            failed_cnt = summary.get("failed", 0)
            pass_rate = summary.get("passRate", 0)
            display_lines = [
                f"## TFA: Golden Regression Build #{build_number}",
                "",
                f"**Tests:** {passed} passed, {failed_cnt} failed ({pass_rate}% pass rate)",
                "",
            ]

            if root_causes:
                display_lines.append("### Root Causes")
                for root_cause in root_causes:
                    rc_type = root_cause.get("type", "unknown")
                    rc_count = root_cause.get("count", 0)
                    rc_desc = root_cause.get("description", "")
                    display_lines.append(f"- **{rc_type}** ({rc_count}): {rc_desc}")
                display_lines.append("")

            if failed_tests:
                display_lines.append("### Failed Tests")
                for test in failed_tests[:5]:
                    t_name = test.get("name", "Unknown")
                    t_err = (test.get("errorMessage") or "")[:80]
                    display_lines.append(f"- **{t_name}**: {t_err}")
                display_lines.append("")

            if recommendations:
                display_lines.append("### Recommendations")
                for rec in recommendations:
                    display_lines.append(f"- {rec}")

            return {
                "job": "Golden Regression Suite",
                "buildNumber": build_number,
                "failedTests": failed_tests,
                "summary": summary,
                "rootCauses": root_causes,
                "recommendations": recommendations,
                "display": "\n".join(display_lines),
                "source": "jenkins-mcp",
            }

        except (httpx.HTTPError, ValueError, KeyError) as err:
            return {"error": str(err)}


if __name__ == "__main__":
    # Run with stdio transport (required for subprocess communication)
    mcp.run(transport="stdio")

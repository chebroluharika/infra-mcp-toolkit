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
Release Risk MCP Server
=======================

Exposes release risk analysis tools for AI agents.
Part of the multi-agentic Release Risk architecture.

Tools:
- risk_get_blocker_analysis: Analyze P0/P1 blockers, unassigned items, bug aging
- risk_get_quality_metrics: Test pass rates, build stability, regression status
- risk_get_velocity_analysis: Trend data, velocity, historical comparison
- risk_get_milestone_criteria: Exit criteria for IRR/Branch Cut/Final Build

Architecture:
    MCP Tools -> Backend API -> Various Services -> External APIs

Usage:
    uv run server.py

Environment Variables:
    API_BASE_URL - Backend API URL (default: http://localhost:8000)
    CURRENT_RELEASE - Default release (e.g., R136)
"""

import os
from datetime import datetime
from typing import Any, Dict

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("release-risk-mcp-server")

DEFAULT_RELEASE = os.getenv("CURRENT_RELEASE", "R136")


# =============================================================================
# JIRA Risk Tools (Blockers, Bugs, RRS)
# =============================================================================


@mcp.tool()
async def risk_get_blocker_analysis(release: str = None) -> Dict[str, Any]:
    """
    Analyze P0/P1 blockers, unassigned items, and bug aging for release risk.

    This tool provides:
    - P0/Blocker bug count and details
    - P1/Critical bug count and details
    - Unassigned blocker count (high risk - no owner = no progress)
    - Bug aging analysis (old bugs = stuck = high risk)
    - Stuck items (Open/To Do/Reopened for too long)
    - RRS (Release Readiness Score)

    Use when analyzing JIRA-based release health and blocker risks.

    Args:
        release: Release ID (e.g., "R136"). Defaults to CURRENT_RELEASE.

    Returns:
        Comprehensive blocker analysis with risk signals
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    release = release or DEFAULT_RELEASE

    if not release.upper().startswith("R"):
        release = f"R{release.split('.')[0]}"
    else:
        release = release.upper()

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Fetch blockers
            blockers_resp = await client.get(f"{api_base}/api/jira/release-data/blockers", params={"release": release})

            # Fetch release readiness for RRS
            readiness_resp = await client.get(f"{api_base}/api/jira/release-readiness", params={"release": release})

            # Fetch by-assignee for unassigned analysis
            assignee_resp = await client.get(
                f"{api_base}/api/jira/release-data/by-assignee", params={"release": release}
            )

            blockers_data = blockers_resp.json() if blockers_resp.status_code == 200 else {}
            readiness_data = readiness_resp.json() if readiness_resp.status_code == 200 else {}
            assignee_data = assignee_resp.json() if assignee_resp.status_code == 200 else {}

            blockers = blockers_data.get("blockers", [])

            # Count by priority
            p0_bugs = [b for b in blockers if b.get("priority") in ["P0", "Highest", "Blocker"]]
            p1_bugs = [b for b in blockers if b.get("priority") in ["P1", "Critical"]]

            # Count unassigned
            unassigned_blockers = [b for b in blockers if not b.get("assignee") or b.get("assignee") == "Unassigned"]

            # Analyze bug aging
            now = datetime.now()
            aged_bugs = []
            for bug in blockers:
                created = bug.get("created")
                if created:
                    try:
                        created_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if created_date.tzinfo:
                            created_date = created_date.replace(tzinfo=None)
                        age_days = (now - created_date).days
                        if age_days > 7:
                            bug["age_days"] = age_days
                            aged_bugs.append(bug)
                    except (ValueError, TypeError):
                        pass

            # Get RRS from readiness data
            components_data = readiness_data.get("componentsData", {})
            product_data = components_data.get("YOUR_PRODUCT", {})
            product_summary = product_data.get("summary", {})
            open_bugs = product_summary.get("bc_bugs", 0)
            open_stories = product_summary.get("bc_stories", 0)
            total_open = open_bugs + open_stories

            rrs_score = max(0, min(100, 100 - (total_open * 3)))
            if rrs_score >= 80:
                rrs_status = "GREEN"
            elif rrs_score >= 70:
                rrs_status = "YELLOW"
            else:
                rrs_status = "RED"

            # Get assignee workload
            assignees = assignee_data.get("assignees", [])
            top_assignees = assignees[:5] if assignees else []

            # Calculate risk signals
            risk_signals = []
            if len(p0_bugs) > 0:
                risk_signals.append(
                    {
                        "signal": "P0_BLOCKERS",
                        "severity": "critical",
                        "message": f"{len(p0_bugs)} P0/Blocker bugs - must be zero for IRR/Branch Cut",
                        "count": len(p0_bugs),
                    }
                )
            if len(p1_bugs) > 5:
                risk_signals.append(
                    {
                        "signal": "HIGH_P1_COUNT",
                        "severity": "high",
                        "message": f"{len(p1_bugs)} P1/Critical bugs - should be <5 for IRR",
                        "count": len(p1_bugs),
                    }
                )
            if len(unassigned_blockers) > 0:
                risk_signals.append(
                    {
                        "signal": "UNASSIGNED_BLOCKERS",
                        "severity": "high",
                        "message": f"{len(unassigned_blockers)} blockers have no owner - no progress possible",
                        "count": len(unassigned_blockers),
                    }
                )
            if len(aged_bugs) > 0:
                risk_signals.append(
                    {
                        "signal": "AGED_BUGS",
                        "severity": "medium",
                        "message": f"{len(aged_bugs)} bugs open for >7 days - may be stuck",
                        "count": len(aged_bugs),
                    }
                )
            if rrs_score < 70:
                risk_signals.append(
                    {
                        "signal": "LOW_RRS",
                        "severity": "high",
                        "message": f"RRS {rrs_score}% is RED - release not ready",
                        "score": rrs_score,
                    }
                )

            # Build display
            display_lines = [
                f"## Blocker Analysis: {release}",
                "",
                "### Summary",
                f"- **P0/Blocker Bugs:** {len(p0_bugs)}",
                f"- **P1/Critical Bugs:** {len(p1_bugs)}",
                f"- **Unassigned Blockers:** {len(unassigned_blockers)}",
                f"- **Aged Bugs (>7 days):** {len(aged_bugs)}",
                f"- **RRS Score:** {rrs_score}% ({rrs_status})",
                "",
            ]

            if risk_signals:
                display_lines.append("### ⚠️ Risk Signals")
                for signal in risk_signals:
                    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(signal["severity"], "⚪")
                    display_lines.append(f"- {severity_emoji} **{signal['signal']}**: {signal['message']}")
                display_lines.append("")

            if p0_bugs:
                display_lines.append("### P0/Blocker Bugs")
                for bug in p0_bugs[:5]:
                    assignee = bug.get("assignee", "Unassigned")
                    display_lines.append(f"- **{bug.get('key')}**: {bug.get('summary', '')[:50]}... ({assignee})")
                display_lines.append("")

            if unassigned_blockers:
                display_lines.append("### Unassigned Blockers (Need Owner)")
                for bug in unassigned_blockers[:5]:
                    display_lines.append(f"- **{bug.get('key')}**: {bug.get('summary', '')[:50]}...")
                display_lines.append("")

            return {
                "release": release,
                "p0_count": len(p0_bugs),
                "p1_count": len(p1_bugs),
                "total_blockers": len(blockers),
                "unassigned_count": len(unassigned_blockers),
                "aged_bugs_count": len(aged_bugs),
                "rrs_score": rrs_score,
                "rrs_status": rrs_status,
                "open_bugs": open_bugs,
                "open_stories": open_stories,
                "total_open": total_open,
                "risk_signals": risk_signals,
                "p0_bugs": [
                    {
                        "key": b.get("key"),
                        "summary": b.get("summary", "")[:60],
                        "assignee": b.get("assignee", "Unassigned"),
                        "status": b.get("status"),
                        "priority": b.get("priority"),
                    }
                    for b in p0_bugs
                ],
                "p1_bugs": [
                    {
                        "key": b.get("key"),
                        "summary": b.get("summary", "")[:60],
                        "assignee": b.get("assignee", "Unassigned"),
                        "status": b.get("status"),
                        "priority": b.get("priority"),
                    }
                    for b in p1_bugs[:10]
                ],
                "unassigned_blockers": [
                    {"key": b.get("key"), "summary": b.get("summary", "")[:60], "priority": b.get("priority")}
                    for b in unassigned_blockers
                ],
                "aged_bugs": [
                    {
                        "key": b.get("key"),
                        "summary": b.get("summary", "")[:60],
                        "age_days": b.get("age_days", 0),
                        "assignee": b.get("assignee", "Unassigned"),
                    }
                    for b in aged_bugs[:10]
                ],
                "top_assignees": top_assignees,
                "display": "\n".join(display_lines),
            }

        except Exception as err:
            return {
                "release": release,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def risk_get_quality_metrics(release: str = None) -> Dict[str, Any]:
    """
    Get test and build quality metrics for release risk analysis.

    This tool provides:
    - Test pass rate from TestRail (target: >95% for Final Build)
    - Test execution rate (low = incomplete testing)
    - Golden Regression status and failures
    - PDV pipeline health (build success rate)
    - Build stability indicators

    Use when analyzing quality-related release risks.

    Args:
        release: Release ID (e.g., "R136"). Defaults to CURRENT_RELEASE.

    Returns:
        Quality metrics with risk signals
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    release = release or DEFAULT_RELEASE

    if not release.upper().startswith("R"):
        release = f"R{release.split('.')[0]}"
    else:
        release = release.upper()

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Fetch Golden Regression status
            golden_resp = await client.get(f"{api_base}/api/jenkins/golden-regression")

            # Fetch PDV pipelines
            pipelines_resp = await client.get(f"{api_base}/api/jenkins/pipelines")

            # Fetch TestRail status from overview (includes test pass rate)
            overview_resp = await client.get(f"{api_base}/api/overview/release-items", params={"release": release})

            golden_data = golden_resp.json() if golden_resp.status_code == 200 else {}
            pipelines_data = pipelines_resp.json() if pipelines_resp.status_code == 200 else {}
            overview_data = overview_resp.json() if overview_resp.status_code == 200 else {}

            # Golden Regression analysis
            golden_stats = golden_data.get("overallStats", {})
            golden_builds = golden_data.get("builds", [])
            golden_success_rate = golden_stats.get("successRate", 0)
            golden_failed = golden_stats.get("failedBuilds", 0)
            golden_total = golden_stats.get("totalBuilds", 0)

            # Recent golden regression failures
            recent_golden_failures = [b for b in golden_builds[:5] if b.get("status") in ["failed", "unstable"]]

            # PDV pipeline analysis
            pipelines_overall = pipelines_data.get("overall", {})
            pipelines = pipelines_data.get("pipelines", [])
            build_health = pipelines_overall.get("healthPercent", 0)
            pipeline_failing = pipelines_overall.get("failing", 0)
            pipeline_unstable = pipelines_overall.get("unstable", 0)

            failing_pipelines = [p for p in pipelines if p.get("status") in ["failed", "unstable"]]

            # Test pass rate from overview
            test_pass_rate = overview_data.get("test_pass_rate")
            test_execution_rate = overview_data.get("test_execution_rate")

            # Calculate risk signals
            risk_signals = []

            if golden_success_rate < 90:
                risk_signals.append(
                    {
                        "signal": "LOW_GOLDEN_REGRESSION_RATE",
                        "severity": "critical",
                        "message": f"Golden Regression success rate {golden_success_rate}% - should be >90%",
                        "value": golden_success_rate,
                    }
                )

            if build_health < 80:
                risk_signals.append(
                    {
                        "signal": "LOW_BUILD_HEALTH",
                        "severity": "high",
                        "message": f"Build health {build_health}% indicates unstable codebase",
                        "value": build_health,
                    }
                )

            if test_pass_rate is not None and test_pass_rate < 95:
                risk_signals.append(
                    {
                        "signal": "LOW_TEST_PASS_RATE",
                        "severity": "high" if test_pass_rate < 90 else "medium",
                        "message": f"Test pass rate {test_pass_rate}% - needs >95% for Final Build",
                        "value": test_pass_rate,
                    }
                )
            elif test_pass_rate is None:
                risk_signals.append(
                    {
                        "signal": "UNKNOWN_TEST_PASS_RATE",
                        "severity": "medium",
                        "message": "Test pass rate unknown - blind spot for quality",
                        "value": None,
                    }
                )

            if len(failing_pipelines) > 2:
                risk_signals.append(
                    {
                        "signal": "MULTIPLE_FAILING_PIPELINES",
                        "severity": "high",
                        "message": f"{len(failing_pipelines)} pipelines failing - integration issues",
                        "count": len(failing_pipelines),
                    }
                )

            if recent_golden_failures:
                risk_signals.append(
                    {
                        "signal": "RECENT_GOLDEN_FAILURES",
                        "severity": "high",
                        "message": f"{len(recent_golden_failures)} recent Golden Regression failures - blocking deployment",
                        "count": len(recent_golden_failures),
                    }
                )

            # Build display
            display_lines = [
                f"## 🔬 Quality Metrics: {release}",
                "",
                "### Test Quality",
                f"- **Test Pass Rate:** {test_pass_rate}%" if test_pass_rate else "- **Test Pass Rate:** Unknown ⚠️",
                f"- **Test Execution Rate:** {test_execution_rate}%" if test_execution_rate else "",
                "",
                "### Build Quality",
                f"- **Golden Regression Success:** {golden_success_rate}% ({golden_failed}/{golden_total} failed)",
                f"- **Pipeline Health:** {build_health}%",
                f"- **Failing Pipelines:** {pipeline_failing}",
                f"- **Unstable Pipelines:** {pipeline_unstable}",
                "",
            ]

            if risk_signals:
                display_lines.append("### ⚠️ Quality Risk Signals")
                for signal in risk_signals:
                    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(signal["severity"], "⚪")
                    display_lines.append(f"- {severity_emoji} **{signal['signal']}**: {signal['message']}")
                display_lines.append("")

            if recent_golden_failures:
                display_lines.append("### Recent Golden Regression Failures")
                for build in recent_golden_failures[:3]:
                    display_lines.append(f"- Build #{build.get('buildNumber')}: {build.get('status')}")
                display_lines.append("")

            return {
                "release": release,
                "test_pass_rate": test_pass_rate,
                "test_execution_rate": test_execution_rate,
                "golden_regression": {
                    "success_rate": golden_success_rate,
                    "failed_builds": golden_failed,
                    "total_builds": golden_total,
                    "recent_failures": [
                        {
                            "build_number": b.get("buildNumber"),
                            "status": b.get("status"),
                            "passed": b.get("passed", 0),
                            "failed": b.get("failed", 0),
                        }
                        for b in recent_golden_failures
                    ],
                },
                "build_health": {
                    "health_percent": build_health,
                    "failing_count": pipeline_failing,
                    "unstable_count": pipeline_unstable,
                    "failing_pipelines": [
                        {"name": p.get("name"), "status": p.get("status"), "last_run": p.get("lastRun")}
                        for p in failing_pipelines[:5]
                    ],
                },
                "risk_signals": risk_signals,
                "display": "\n".join(display_lines),
            }

        except Exception as err:
            return {
                "release": release,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def risk_get_velocity_analysis(release: str = None) -> Dict[str, Any]:
    """
    Analyze velocity, trends, and historical comparison for release risk.

    This tool provides:
    - Current velocity (items resolved per day)
    - Velocity trend (improving/declining/stable)
    - Days to milestone and buffer calculation
    - Historical comparison to past releases
    - Similar release outcomes
    - Plateau detection (stuck periods)
    - Week-over-week changes

    Use when analyzing progress-related release risks.

    Args:
        release: Release ID (e.g., "R136"). Defaults to CURRENT_RELEASE.

    Returns:
        Velocity analysis with predictions and risk signals
    """
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    release = release or DEFAULT_RELEASE

    if not release.upper().startswith("R"):
        release = f"R{release.split('.')[0]}"
    else:
        release = release.upper()

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            # Fetch trend data
            trends_resp = await client.get(f"{api_base}/api/overview/trends", params={"release": release})

            # Fetch release calendar for milestone dates
            calendar_resp = await client.get(f"{api_base}/api/release-calendar/releases/{release}")

            # Fetch release history for comparison
            history_resp = await client.get(f"{api_base}/api/release-risk/history/{release}")

            trends_data = trends_resp.json() if trends_resp.status_code == 200 else {}
            calendar_data = calendar_resp.json() if calendar_resp.status_code == 200 else {}
            history_data = history_resp.json() if history_resp.status_code == 200 else {}

            # Extract trend metrics
            velocity = trends_data.get("velocity", 0)
            trend_direction = trends_data.get("trend_direction", "unknown")
            trend_message = trends_data.get("trend_message", "")
            plateau_detected = trends_data.get("plateau_detected", False)
            plateau_message = trends_data.get("plateau_message", "")
            prediction = trends_data.get("prediction", "")
            prediction_date = trends_data.get("prediction_date")
            spikes = trends_data.get("spikes", [])
            current_total = trends_data.get("current_total", 0)

            # Extract milestone dates
            release_info = calendar_data.get("release", {})
            milestones = release_info.get("milestones", {})

            # Calculate days to next milestone
            days_to_milestone = None
            next_milestone = None
            now = datetime.now()

            milestone_order = ["irr", "branch_cut", "final_build", "day1_deploy"]
            for ms in milestone_order:
                ms_date_str = milestones.get(ms)
                if ms_date_str:
                    try:
                        ms_date = datetime.strptime(ms_date_str, "%Y-%m-%d")
                        if ms_date > now:
                            days_to_milestone = (ms_date - now).days
                            next_milestone = ms.replace("_", " ").title()
                            break
                    except ValueError:
                        pass

            # Calculate buffer/deficit
            buffer_days = None
            days_needed = None
            if velocity > 0 and current_total > 0:
                days_needed = current_total / velocity
                if days_to_milestone is not None:
                    buffer_days = days_to_milestone - days_needed

            # Historical comparison
            historical_avg = history_data.get("historical_average", {})
            similar_releases = history_data.get("similar_releases", [])
            on_time_rate = history_data.get("on_time_rate", {})

            # Week-over-week from trends
            wow_change = trends_data.get("week_over_week", {})

            # Risk signals
            risk_signals = []

            if trend_direction == "declining":
                risk_signals.append(
                    {
                        "signal": "DECLINING_TREND",
                        "severity": "high",
                        "message": f"Open items increasing - {trend_message}",
                        "trend": trend_direction,
                    }
                )

            if plateau_detected:
                risk_signals.append(
                    {
                        "signal": "PLATEAU_DETECTED",
                        "severity": "medium",
                        "message": plateau_message or "Progress has stalled - team may be blocked",
                        "stuck_value": current_total,
                    }
                )

            if buffer_days is not None and buffer_days < 0:
                risk_signals.append(
                    {
                        "signal": "NEGATIVE_BUFFER",
                        "severity": "critical",
                        "message": f"{abs(buffer_days):.1f} days deficit - cannot finish at current velocity",
                        "deficit_days": abs(buffer_days),
                    }
                )
            elif buffer_days is not None and buffer_days < 2:
                risk_signals.append(
                    {
                        "signal": "LOW_BUFFER",
                        "severity": "high",
                        "message": f"Only {buffer_days:.1f} days buffer - no room for surprises",
                        "buffer_days": buffer_days,
                    }
                )

            if velocity <= 0 and current_total > 0:
                risk_signals.append(
                    {
                        "signal": "ZERO_VELOCITY",
                        "severity": "critical",
                        "message": "No items being resolved - release blocked",
                        "velocity": velocity,
                    }
                )

            if spikes:
                risk_signals.append(
                    {
                        "signal": "RECENT_SPIKES",
                        "severity": "medium",
                        "message": f"{len(spikes)} sudden increases in open items",
                        "spike_count": len(spikes),
                    }
                )

            # Build display
            display_lines = [
                f"## 📈 Velocity Analysis: {release}",
                "",
                "### Current Progress",
                f"- **Open Items:** {current_total}",
                f"- **Velocity:** {velocity:.1f} items/day",
                f"- **Trend:** {trend_direction.title()} - {trend_message}",
                "",
            ]

            if next_milestone and days_to_milestone is not None:
                display_lines.append("### Milestone Projection")
                display_lines.append(f"- **Next Milestone:** {next_milestone}")
                display_lines.append(f"- **Days Remaining:** {days_to_milestone}")
                if days_needed is not None:
                    display_lines.append(f"- **Days Needed:** {days_needed:.1f}")
                if buffer_days is not None:
                    buffer_status = "buffer" if buffer_days >= 0 else "DEFICIT"
                    display_lines.append(f"- **Buffer:** {abs(buffer_days):.1f} days {buffer_status}")
                display_lines.append("")

            if prediction:
                display_lines.append("### Prediction")
                display_lines.append(f"{prediction}")
                display_lines.append("")

            if risk_signals:
                display_lines.append("### ⚠️ Velocity Risk Signals")
                for signal in risk_signals:
                    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(signal["severity"], "⚪")
                    display_lines.append(f"- {severity_emoji} **{signal['signal']}**: {signal['message']}")
                display_lines.append("")

            if similar_releases:
                display_lines.append("### Similar Past Releases")
                for sr in similar_releases[:3]:
                    outcome = "on-time" if sr.get("on_time") else f"slipped {sr.get('slip_days', '?')} days"
                    display_lines.append(f"- **{sr.get('release')}**: {outcome}")
                display_lines.append("")

            return {
                "release": release,
                "current_total": current_total,
                "velocity_per_day": velocity,
                "trend_direction": trend_direction,
                "trend_message": trend_message,
                "plateau_detected": plateau_detected,
                "plateau_message": plateau_message,
                "prediction": prediction,
                "prediction_date": prediction_date,
                "milestone": {
                    "next": next_milestone,
                    "days_remaining": days_to_milestone,
                    "days_needed": days_needed,
                    "buffer_days": buffer_days,
                },
                "milestones": milestones,
                "spikes": spikes,
                "week_over_week": wow_change,
                "historical_comparison": {
                    "average": historical_avg,
                    "similar_releases": similar_releases,
                    "on_time_rate": on_time_rate,
                },
                "risk_signals": risk_signals,
                "display": "\n".join(display_lines),
            }

        except Exception as err:
            return {
                "release": release,
                "error": str(err),
                "display": f"**Error:** {err}",
            }


@mcp.tool()
async def risk_get_milestone_criteria(milestone: str = "IRR") -> Dict[str, Any]:
    """
    Get exit criteria and requirements for a specific release milestone.

    This tool provides:
    - Exit criteria (what must be true to pass the milestone)
    - Bug count requirements (P0, P1 thresholds)
    - Test requirements (pass rate thresholds)
    - Build requirements
    - What happens after the milestone

    Use when explaining milestone requirements or evaluating readiness.

    Args:
        milestone: Milestone name - "IRR", "BranchCut", "FinalBuild", "Day1Deploy"

    Returns:
        Milestone criteria and requirements
    """
    milestone_criteria = {
        "IRR": {
            "name": "Initial Release Readiness (IRR)",
            "description": "First checkpoint to assess if release is on track",
            "exit_criteria": [
                "Zero P0/Blocker bugs",
                "P1/Critical bugs should be under 5",
                "All planned stories in Code Review or later",
                "Test plan approved and test cases ready",
            ],
            "bug_requirements": {
                "p0": {"max": 0, "critical": True},
                "p1": {"max": 5, "critical": False},
            },
            "test_requirements": {"test_plan": "Approved", "test_cases": "Ready for execution"},
            "what_happens_after": "Code freeze begins - only bug fixes allowed",
            "risk_level_thresholds": {
                "low": "P0=0, P1<3, RRS>85%",
                "medium": "P0=0, P1<5, RRS>70%",
                "high": "P0>0 OR P1>5 OR RRS<70%",
            },
        },
        "BRANCHCUT": {
            "name": "Branch Cut",
            "description": "Code branch is cut for the release - no more features",
            "exit_criteria": [
                "Zero P0/Blocker bugs",
                "Zero P1/Critical bugs (or approved waivers)",
                "All stories resolved or waivered",
                "Regression test suite passing",
            ],
            "bug_requirements": {
                "p0": {"max": 0, "critical": True},
                "p1": {"max": 0, "critical": True, "waiver_allowed": True},
            },
            "test_requirements": {"regression_suite": "Passing", "test_pass_rate": ">90%"},
            "what_happens_after": "Only approved bug fixes - release branch is locked",
            "risk_level_thresholds": {
                "low": "P0=0, P1=0, tests>95%",
                "medium": "P0=0, P1<2 (waivered), tests>90%",
                "high": "P0>0 OR P1>2 OR tests<90%",
            },
        },
        "FINALBUILD": {
            "name": "Final Build",
            "description": "Final build candidate for production deployment",
            "exit_criteria": [
                "Zero P0/P1 bugs",
                "Regression tests >95% pass rate",
                "Golden Regression suite passing",
                "Sign-off from QA, Dev, and PM",
            ],
            "bug_requirements": {
                "p0": {"max": 0, "critical": True},
                "p1": {"max": 0, "critical": True},
            },
            "test_requirements": {
                "regression_pass_rate": ">95%",
                "golden_regression": "Passing",
                "execution_rate": ">90%",
            },
            "what_happens_after": "This build goes to production",
            "risk_level_thresholds": {
                "low": "P0=0, P1=0, tests>98%, golden=pass",
                "medium": "P0=0, P1=0, tests>95%, golden=pass",
                "high": "ANY bugs OR tests<95% OR golden=fail",
            },
        },
        "DAY1DEPLOY": {
            "name": "Day 1 Deploy",
            "description": "Production deployment begins",
            "exit_criteria": [
                "Final Build approved",
                "Deployment runbook reviewed",
                "Rollback plan documented",
                "On-call team briefed",
            ],
            "bug_requirements": {
                "p0": {"max": 0, "critical": True},
                "p1": {"max": 0, "critical": True},
            },
            "test_requirements": {"smoke_tests": "Ready", "monitoring_dashboards": "Active"},
            "what_happens_after": "Production rollout begins",
            "risk_level_thresholds": {
                "low": "All criteria met, team confident",
                "medium": "Minor concerns, mitigation in place",
                "high": "Criteria not met - STOP deployment",
            },
        },
    }

    # Normalize milestone name
    milestone_key = milestone.upper().replace(" ", "").replace("_", "")

    if milestone_key not in milestone_criteria:
        # Try partial match
        for key in milestone_criteria:
            if milestone_key in key or key in milestone_key:
                milestone_key = key
                break

    criteria = milestone_criteria.get(milestone_key, milestone_criteria.get("IRR"))

    # Build display
    display_lines = [
        f"## 📋 {criteria['name']}",
        "",
        f"**Description:** {criteria['description']}",
        "",
        "### Exit Criteria",
    ]
    for criterion in criteria["exit_criteria"]:
        display_lines.append(f"- ✅ {criterion}")

    display_lines.extend(
        [
            "",
            "### Bug Requirements",
            f"- **P0/Blocker:** Max {criteria['bug_requirements']['p0']['max']} (mandatory)",
            f"- **P1/Critical:** Max {criteria['bug_requirements']['p1']['max']}"
            + (" (waiver allowed)" if criteria["bug_requirements"]["p1"].get("waiver_allowed") else " (mandatory)"),
            "",
            "### After This Milestone",
            f"➡️ {criteria['what_happens_after']}",
            "",
            "### Risk Thresholds",
        ]
    )

    for level, threshold in criteria["risk_level_thresholds"].items():
        emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}[level]
        display_lines.append(f"- {emoji} **{level.upper()}**: {threshold}")

    return {
        "milestone": milestone_key,
        "criteria": criteria,
        "display": "\n".join(display_lines),
    }


@mcp.tool()
async def risk_synthesize_analysis(
    release: str = None, blocker_data: Dict = None, quality_data: Dict = None, velocity_data: Dict = None
) -> Dict[str, Any]:
    """
    Synthesize all risk data into a final risk assessment.

    This tool combines findings from:
    - Blocker analysis (P0/P1, unassigned, RRS)
    - Quality metrics (tests, builds)
    - Velocity analysis (trends, projections)

    And produces:
    - Overall risk probability (AI-reasoned)
    - Risk level (HIGH/MEDIUM/LOW)
    - Confidence level
    - Prioritized action items
    - Evidence-backed reasoning

    Call this AFTER calling the other risk tools to synthesize findings.

    Args:
        release: Release ID
        blocker_data: Output from risk_get_blocker_analysis
        quality_data: Output from risk_get_quality_metrics
        velocity_data: Output from risk_get_velocity_analysis

    Returns:
        Synthesized risk assessment
    """
    release = release or DEFAULT_RELEASE

    # Collect all risk signals
    all_signals = []
    if blocker_data:
        all_signals.extend(blocker_data.get("risk_signals", []))
    if quality_data:
        all_signals.extend(quality_data.get("risk_signals", []))
    if velocity_data:
        all_signals.extend(velocity_data.get("risk_signals", []))

    # Count by severity
    critical_count = len([s for s in all_signals if s.get("severity") == "critical"])
    high_count = len([s for s in all_signals if s.get("severity") == "high"])
    medium_count = len([s for s in all_signals if s.get("severity") == "medium"])

    # Calculate probability (inverse of risk)
    # Start at 80% (optimistic), deduct for risk signals
    probability = 80
    probability -= critical_count * 20
    probability -= high_count * 10
    probability -= medium_count * 5
    probability = max(5, min(95, probability))

    # Determine risk level
    if probability >= 75:
        risk_level = "LOW"
        risk_emoji = "🟢"
    elif probability >= 50:
        risk_level = "MEDIUM"
        risk_emoji = "🟡"
    else:
        risk_level = "HIGH"
        risk_emoji = "🔴"

    # Determine confidence
    has_blocker_data = blocker_data is not None and "error" not in blocker_data
    has_quality_data = quality_data is not None and "error" not in quality_data
    has_velocity_data = velocity_data is not None and "error" not in velocity_data

    data_sources = sum([has_blocker_data, has_quality_data, has_velocity_data])
    if data_sources >= 3:
        confidence = "HIGH"
    elif data_sources >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Generate action items based on risk signals
    action_items = []

    # Critical actions first
    for signal in [s for s in all_signals if s.get("severity") == "critical"]:
        if signal["signal"] == "P0_BLOCKERS":
            action_items.append(
                {
                    "priority": 1,
                    "action": "Resolve all P0/Blocker bugs immediately - they block the release",
                    "impact": "critical",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "NEGATIVE_BUFFER":
            action_items.append(
                {
                    "priority": 1,
                    "action": f"Increase velocity or reduce scope - {signal.get('deficit_days', 0):.1f} days behind",
                    "impact": "critical",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "LOW_GOLDEN_REGRESSION_RATE":
            action_items.append(
                {
                    "priority": 1,
                    "action": "Fix Golden Regression failures - blocking deployment",
                    "impact": "critical",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "ZERO_VELOCITY":
            action_items.append(
                {
                    "priority": 1,
                    "action": "Unblock the team - no items being resolved",
                    "impact": "critical",
                    "signal": signal["signal"],
                }
            )

    # High priority actions
    for signal in [s for s in all_signals if s.get("severity") == "high"]:
        if signal["signal"] == "UNASSIGNED_BLOCKERS":
            action_items.append(
                {
                    "priority": 2,
                    "action": f"Assign owners to {signal.get('count', 0)} unassigned blockers",
                    "impact": "high",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "HIGH_P1_COUNT":
            action_items.append(
                {
                    "priority": 2,
                    "action": f"Triage and prioritize {signal.get('count', 0)} P1 bugs",
                    "impact": "high",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "LOW_TEST_PASS_RATE":
            action_items.append(
                {
                    "priority": 2,
                    "action": f"Investigate test failures - pass rate at {signal.get('value', 0)}%",
                    "impact": "high",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "DECLINING_TREND":
            action_items.append(
                {
                    "priority": 2,
                    "action": "Identify why open items are increasing - stop the bleed",
                    "impact": "high",
                    "signal": signal["signal"],
                }
            )

    # Medium priority actions
    for signal in [s for s in all_signals if s.get("severity") == "medium"]:
        if signal["signal"] == "PLATEAU_DETECTED":
            action_items.append(
                {
                    "priority": 3,
                    "action": "Check for blockers - progress has stalled",
                    "impact": "medium",
                    "signal": signal["signal"],
                }
            )
        elif signal["signal"] == "AGED_BUGS":
            action_items.append(
                {
                    "priority": 3,
                    "action": f"Review {signal.get('count', 0)} aged bugs - may need escalation",
                    "impact": "medium",
                    "signal": signal["signal"],
                }
            )

    # Limit to top 5 actions
    action_items = action_items[:5]

    # Build reasoning
    reasoning_parts = []

    if blocker_data:
        p0 = blocker_data.get("p0_count", 0)
        p1 = blocker_data.get("p1_count", 0)
        rrs = blocker_data.get("rrs_score", 0)
        reasoning_parts.append(f"{p0} P0 bugs, {p1} P1 bugs, RRS {rrs}%")

    if velocity_data:
        velocity = velocity_data.get("velocity_per_day", 0)
        buffer = velocity_data.get("milestone", {}).get("buffer_days")
        if buffer is not None:
            reasoning_parts.append(f"velocity {velocity:.1f}/day, {buffer:.1f} days buffer")
        else:
            reasoning_parts.append(f"velocity {velocity:.1f}/day")

    if quality_data:
        golden_rate = quality_data.get("golden_regression", {}).get("success_rate", 0)
        test_rate = quality_data.get("test_pass_rate")
        if test_rate:
            reasoning_parts.append(f"test pass rate {test_rate}%, golden regression {golden_rate}%")
        else:
            reasoning_parts.append(f"golden regression {golden_rate}%")

    reasoning = f"{risk_level} RISK ({probability}% on-time): " + "; ".join(reasoning_parts)

    # Build summary
    summary = f"{risk_emoji} **{risk_level} RISK** - {probability}% probability of on-time release"

    if critical_count > 0:
        summary += f". {critical_count} critical issue(s) require immediate attention."
    elif high_count > 0:
        summary += f". {high_count} high-priority issue(s) need resolution."
    else:
        summary += ". Release is on track."

    # Build display
    display_lines = [
        f"## {risk_emoji} Risk Assessment: {release}",
        "",
        f"### Overall: {risk_level} RISK ({probability}% on-time)",
        f"**Confidence:** {confidence}",
        "",
        "### Risk Summary",
        summary,
        "",
    ]

    if all_signals:
        display_lines.append("### Risk Signals")
        display_lines.append(f"- 🔴 Critical: {critical_count}")
        display_lines.append(f"- 🟠 High: {high_count}")
        display_lines.append(f"- 🟡 Medium: {medium_count}")
        display_lines.append("")

    if action_items:
        display_lines.append("### Recommended Actions")
        for idx, action in enumerate(action_items, 1):
            impact_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(action["impact"], "⚪")
            display_lines.append(f"{idx}. {impact_emoji} {action['action']}")
        display_lines.append("")

    display_lines.append("### Reasoning")
    display_lines.append(reasoning)

    return {
        "release": release,
        "probability": probability,
        "risk_level": risk_level,
        "confidence": confidence,
        "summary": summary,
        "reasoning": reasoning,
        "risk_signals": {
            "critical": critical_count,
            "high": high_count,
            "medium": medium_count,
            "total": len(all_signals),
            "details": all_signals,
        },
        "action_items": action_items,
        "data_sources": {
            "blocker_analysis": has_blocker_data,
            "quality_metrics": has_quality_data,
            "velocity_analysis": has_velocity_data,
        },
        "display": "\n".join(display_lines),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

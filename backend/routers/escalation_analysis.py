"""
Escalation Analysis Router
===========================

[TECH PREVIEW] This feature is under active development.

REST endpoints for customer escalation analysis:
- List releases with escalation data
- Get filtered tickets for a release
- Run full AI-powered analysis (PR impact, test recommendations)
- Quick summary without AI analysis

Endpoints:
    GET /api/escalation-analysis/releases       - Available releases
    GET /api/escalation-analysis/tickets/{id}    - Tickets for a release
    GET /api/escalation-analysis/analyze/{id}    - Full AI analysis
    GET /api/escalation-analysis/summary/{id}    - Quick summary (no AI)
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/escalation-analysis",
    tags=["Escalation Analysis (Tech Preview)"],
)

# Injected into every response so frontend can display a banner
TECH_PREVIEW_META = {
    "tech_preview": True,
    "tech_preview_message": (
        "This feature is a Tech Preview and under active development. " "Data and analysis results may be incomplete."
    ),
}


@router.get("/releases")
async def get_available_releases(
    jql: Optional[str] = Query(None, description="Custom JQL override"),
):
    """
    Get list of releases that have escalation tickets.

    Returns releases sorted by version number (newest first) with ticket counts.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        tickets = await service.get_all_escalations(jql=jql)
        releases = service.get_available_releases(tickets)

        return {
            **TECH_PREVIEW_META,
            "releases": releases,
            "total_escalations": len(tickets),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching escalation releases: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all-tickets")
async def get_all_escalation_tickets(
    jql: Optional[str] = Query(None, description="Custom JQL override"),
):
    """
    Get ALL escalation tickets across all releases (no filtering).
    Returns all tickets with PR links enriched.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        all_tickets = await service.get_all_escalations(jql=jql)

        def enrich_ticket_fast(ticket):
            """
            Fast enrichment using only data from the initial search results.
            No additional API calls - just extract PR links from description.
            Full enrichment (linked issues, dev-status) happens on-demand in ticket details.
            """
            desc_pr_links = service.extract_pr_links(ticket)
            for pr in desc_pr_links:
                pr["source"] = "description"

            fix_versions = ticket.get("fixVersions", [])
            fix_version_str = ", ".join(fix_versions) if fix_versions else "—"

            return {
                "key": ticket.get("key"),
                "summary": ticket.get("summary"),
                "assignee": ticket.get("assignee"),
                "priority": ticket.get("priority"),
                "status": ticket.get("status"),
                "url": ticket.get("url"),
                "created": ticket.get("created"),
                "resolution_date": ticket.get("resolutiondate"),
                "components": ticket.get("components", []),
                "fix_versions": fix_versions,
                "fix_version_str": fix_version_str,
                "customer": ticket.get("salesforce_account") or "Unknown",
                "sub_component": ticket.get("sub_component") or "Unknown",
                "linked_assignees": [],
                "qa": ticket.get("qa"),
                "all_qas": [ticket.get("qa")] if ticket.get("qa") else [],
                "pr_count": len(desc_pr_links),
                "pr_links": desc_pr_links,
            }

        # Fast enrichment - no additional API calls, just use search results
        ticket_results = [enrich_ticket_fast(t) for t in all_tickets]

        total_prs = sum(t["pr_count"] for t in ticket_results)

        return {
            **TECH_PREVIEW_META,
            "total_tickets": len(ticket_results),
            "tickets_with_prs": sum(1 for t in ticket_results if t["pr_count"] > 0),
            "total_prs": total_prs,
            "tickets": ticket_results,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching all escalation tickets: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all-summary")
async def get_all_escalations_summary(
    jql: Optional[str] = Query(None, description="Custom JQL override"),
):
    """
    Get summary of ALL escalations across all releases.
    Returns aggregated stats, assignee/priority/component/customer breakdowns, MTTR.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        summary = await service.get_all_summary(jql=jql)
        summary["generated_at"] = datetime.now().isoformat()
        return {**TECH_PREVIEW_META, **summary}

    except Exception as e:
        logger.error("Error getting all escalations summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tickets/{release_id}")
async def get_escalation_tickets(
    release_id: str,
    jql: Optional[str] = Query(None, description="Custom JQL override"),
):
    """
    Get escalation tickets filtered for a specific release.

    Returns tickets with extracted PR links (no AI analysis).
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        all_tickets = await service.get_all_escalations(jql=jql)
        filtered = service.filter_by_release(all_tickets, release_id)

        def enrich_ticket_fast(ticket):
            """
            Fast enrichment using only data from the initial search results.
            No additional API calls - just extract PR links from description.
            """
            desc_pr_links = service.extract_pr_links(ticket)
            for pr in desc_pr_links:
                pr["source"] = "description"

            fix_versions = ticket.get("fixVersions", [])
            fix_version_str = ", ".join(fix_versions) if fix_versions else "—"

            return {
                "key": ticket.get("key"),
                "summary": ticket.get("summary"),
                "assignee": ticket.get("assignee"),
                "priority": ticket.get("priority"),
                "status": ticket.get("status"),
                "url": ticket.get("url"),
                "created": ticket.get("created"),
                "resolution_date": ticket.get("resolutiondate"),
                "components": ticket.get("components", []),
                "fix_versions": fix_versions,
                "fix_version_str": fix_version_str,
                "customer": ticket.get("salesforce_account") or "Unknown",
                "sub_component": ticket.get("sub_component") or "Unknown",
                "pr_count": len(desc_pr_links),
                "pr_links": desc_pr_links,
            }

        # Fast enrichment - no additional API calls
        ticket_results = [enrich_ticket_fast(t) for t in filtered]

        total_prs = sum(t["pr_count"] for t in ticket_results)

        return {
            **TECH_PREVIEW_META,
            "release_id": release_id,
            "total_tickets": len(ticket_results),
            "tickets_with_prs": sum(1 for t in ticket_results if t["pr_count"] > 0),
            "total_prs": total_prs,
            "tickets": ticket_results,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Error fetching escalation tickets for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze/{release_id}")
async def analyze_release_escalations(
    release_id: str,
    jql: Optional[str] = Query(None, description="Custom JQL override"),
    include_ai: bool = Query(True, description="Include LLM-powered analysis"),
):
    """
    Run full AI analysis for escalation tickets in a release.

    Pipeline:
    1. Fetch escalation tickets from Jira
    2. Filter by release (fixVersion)
    3. Extract GitHub PR links
    4. Fetch PR details (files, diffs)
    5. Run AI analysis (risk, test recommendations)
    6. Aggregate results

    Returns file hotspots, test recommendations, risk summary, and per-ticket details.
    This endpoint may take 30-60s depending on the number of PRs and LLM availability.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        result = await service.analyze_escalations_for_release(
            release_id=release_id,
            jql=jql,
            include_ai_analysis=include_ai,
        )

        result["generated_at"] = datetime.now().isoformat()
        return {**TECH_PREVIEW_META, **result}

    except Exception as e:
        logger.error("Error analyzing escalations for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{release_id}")
async def get_release_summary(
    release_id: str,
    jql: Optional[str] = Query(None, description="Custom JQL override"),
):
    """
    Quick summary of escalations for a release without full PR analysis.

    Returns ticket counts, assignee breakdown, and priority distribution.
    Much faster than /analyze since it skips GitHub API and LLM calls.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        summary = await service.get_release_summary(
            release_id=release_id,
            jql=jql,
        )

        summary["generated_at"] = datetime.now().isoformat()
        return {**TECH_PREVIEW_META, **summary}

    except Exception as e:
        logger.error("Error getting escalation summary for %s: %s", release_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticket-details/{ticket_key}")
async def get_ticket_details(ticket_key: str):
    """
    Get full details for a single escalation ticket.

    Returns:
    - Ticket fields (summary, description, status, assignee, etc.)
    - Linked issues (from Jira issuelinks)
    - PR links from the Development panel of the ticket and its linked workitems
    - PR links extracted from the description text

    This is the detail view when clicking on a ticket in the escalation list.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        details = await service.get_ticket_details(ticket_key)

        if details.get("error"):
            raise HTTPException(status_code=404, detail=details["error"])

        details["generated_at"] = datetime.now().isoformat()
        return {**TECH_PREVIEW_META, **details}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching ticket details for %s: %s", ticket_key, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ticket-pr-counts")
async def get_ticket_pr_counts(ticket_keys: list[str]):
    """
    Fetch PR counts for a batch of tickets.

    This endpoint is called in the background after initial page load
    to populate PR counts without blocking the UI.

    Returns a dict mapping ticket_key -> pr_count.
    """
    from services.escalation_service import get_escalation_service
    from services.jira_client import get_jira_client

    service = get_escalation_service()
    jira = get_jira_client()

    async def get_pr_count(ticket_key: str) -> tuple[str, int]:
        """Get PR count for a single ticket (from dev-status + linked issues)."""
        try:
            count = 0
            seen_urls = set()

            # PRs from description (already extracted, fast)
            # We skip this since we want dev-status PRs

            # PRs from dev-status of the ticket itself
            try:
                dev_status = await service._get_issue_dev_status_cached(ticket_key)
                for pr in dev_status.get("pull_requests", []):
                    url = pr.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        count += 1
            except Exception:
                pass

            # PRs from linked issues
            try:
                issue = await jira.get_issue(ticket_key, include_links=True)
                if issue:
                    for linked in issue.get("linked_issues", []):
                        linked_key = linked.get("key", "")
                        if linked_key:
                            try:
                                linked_dev = await service._get_issue_dev_status_cached(linked_key)
                                for pr in linked_dev.get("pull_requests", []):
                                    url = pr.get("url", "")
                                    if url and url not in seen_urls:
                                        seen_urls.add(url)
                                        count += 1
                            except Exception:
                                pass
            except Exception:
                pass

            return (ticket_key, count)
        except Exception as e:
            logger.debug("Error getting PR count for %s: %s", ticket_key, e)
            return (ticket_key, 0)

    # Process in small batches to avoid rate limiting
    BATCH_SIZE = 5
    results = {}

    for i in range(0, len(ticket_keys), BATCH_SIZE):
        batch = ticket_keys[i : i + BATCH_SIZE]
        batch_results = await asyncio.gather(*[get_pr_count(k) for k in batch])
        for key, count in batch_results:
            results[key] = count
        if i + BATCH_SIZE < len(ticket_keys):
            await asyncio.sleep(0.3)  # Small delay between batches

    return {"pr_counts": results}


@router.get("/ticket/{ticket_key}/impact")
async def analyze_ticket_impact(ticket_key: str):
    """
    Analyze impacted areas for a single escalation ticket.

    Uses CommitAnalyzer to analyze each linked PR and returns:
    - impacted_features: List of product components/features affected
    - test_areas: Recommended test areas based on file changes

    This analysis combines:
    - Pattern-based test area detection (COMPONENT_TEST_MAPPING)
    - LLM semantic analysis of code changes
    - Ticket sub-component metadata
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        result = await service.analyze_single_ticket_impact(ticket_key)

        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])

        result["generated_at"] = datetime.now().isoformat()
        return {**TECH_PREVIEW_META, **result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error analyzing impact for %s: %s", ticket_key, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug-fields/{ticket_key}")
async def debug_ticket_fields(ticket_key: str):
    """
    Debug endpoint to inspect raw JIRA fields for a ticket.
    Use this to find the correct custom field IDs for Salesforce Account Name and Sub-component.
    """
    import httpx
    from services.jira_client import get_jira_client

    jira = get_jira_client()

    try:
        url = f"{jira.base_url}/rest/api/3/issue/{ticket_key}"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, headers=jira._headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"JIRA API error: {response.text[:500]}")

            data = response.json()
            fields = data.get("fields", {})

            custom_fields = {}
            for key, value in fields.items():
                if key.startswith("customfield_"):
                    field_preview = str(value)[:200] if value else None
                    custom_fields[key] = {
                        "value_preview": field_preview,
                        "type": type(value).__name__,
                    }

            return {
                "ticket_key": ticket_key,
                "hint": "Look for fields containing 'Salesforce', 'Account', 'Customer', 'Sub-component', 'Subcomponent'",
                "custom_fields": custom_fields,
                "standard_fields": {
                    "components": fields.get("components"),
                    "labels": fields.get("labels"),
                },
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching raw fields for %s: %s", ticket_key, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticket-features")
async def get_ticket_features():
    """
    Get AI-analyzed impacted features for all tickets from the analysis cache.

    Returns a dict mapping ticket_key -> {impacted_features, analyzed_at, ...}
    This data is populated when users run AI analysis on tickets.
    """
    import json
    import os

    cache_file = os.path.join(os.environ.get("DATA_DIR", "/app/data"), "ticket_analysis_cache.json")

    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                cache = json.load(f)
            return {
                **TECH_PREVIEW_META,
                "ticket_features": cache.get("tickets", {}),
                "updated_at": cache.get("updated_at"),
                "total_analyzed": len(cache.get("tickets", {})),
            }
        else:
            return {
                **TECH_PREVIEW_META,
                "ticket_features": {},
                "updated_at": None,
                "total_analyzed": 0,
            }
    except Exception as e:
        logger.error("Error loading ticket features cache: %s", e)
        return {
            **TECH_PREVIEW_META,
            "ticket_features": {},
            "error": str(e),
        }


@router.get("/trends")
async def get_escalation_trends(
    jql: Optional[str] = Query(None, description="Custom JQL override"),
    months: int = Query(12, ge=3, le=24, description="Number of months to include"),
):
    """
    Get escalation trends over time, grouped by month and sub-component.

    Returns data suitable for a stacked area chart showing:
    - Monthly escalation counts
    - Breakdown by sub-component (top 8 + "Other")

    Use this to visualize historical escalation patterns and identify
    which components have trending issues.
    """
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()

    try:
        trends = await service.get_escalation_trends(jql=jql, months=months)
        return {
            **TECH_PREVIEW_META,
            "data": trends,
        }
    except Exception as e:
        logger.error("Error fetching escalation trends: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug-field-names")
async def debug_field_names():
    """
    Debug endpoint to list all JIRA field names and their IDs.
    Helps find the correct custom field ID for 'Sub-Component'.
    """
    import httpx
    from services.jira_client import get_jira_client

    jira = get_jira_client()

    try:
        url = f"{jira.base_url}/rest/api/3/field"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, headers=jira._headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"JIRA API error: {response.text[:500]}")

            all_fields = response.json()

            # Filter to find Sub-Component related fields
            sub_component_fields = [
                {"id": f.get("id"), "name": f.get("name"), "custom": f.get("custom", False)}
                for f in all_fields
                if "sub" in (f.get("name") or "").lower() or "component" in (f.get("name") or "").lower()
            ]

            return {
                "matching_fields": sub_component_fields,
                "total_fields": len(all_fields),
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching field names: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize-pattern")
async def summarize_escalation_pattern(
    customer: str = Query(..., description="Customer name"),
    component: str = Query(..., description="Component/feature name"),
    ticket_keys: str = Query(..., description="Comma-separated list of ticket keys"),
):
    """
    Use AI to summarize a recurring escalation pattern (customer + component combination).

    Takes the ticket summaries and descriptions to generate:
    - Root cause hypothesis
    - Common themes across the escalations
    - Recommended actions
    """
    from services.commit_analyzer import CommitAnalyzer
    from services.escalation_service import get_escalation_service

    service = get_escalation_service()
    analyzer = CommitAnalyzer()

    if not analyzer._configured:
        return {
            **TECH_PREVIEW_META,
            "ai_summary": None,
            "error": "AI not configured - Ollama settings missing",
            "fallback_summary": f"Recurring pattern: {customer} has reported {len(ticket_keys.split(','))} issues with {component}. Manual review recommended.",
        }

    try:
        # Parse ticket keys
        keys = [k.strip() for k in ticket_keys.split(",") if k.strip()]

        if not keys:
            raise HTTPException(status_code=400, detail="No ticket keys provided")

        # Fetch ticket details for context
        all_tickets = await service.get_all_escalations()
        pattern_tickets = [t for t in all_tickets if t.get("key") in keys]

        if not pattern_tickets:
            raise HTTPException(status_code=404, detail="No matching tickets found")

        # Build context for LLM
        ticket_context = []
        for t in pattern_tickets[:10]:  # Limit to 10 tickets to avoid token limits
            ticket_context.append(
                {
                    "key": t.get("key"),
                    "summary": t.get("summary", ""),
                    "priority": t.get("priority", ""),
                    "created": t.get("created", "")[:10] if t.get("created") else "",
                    "description_snippet": (t.get("description") or "")[:300],
                }
            )

        prompt = f"""Analyze this recurring escalation pattern and provide insights.

CUSTOMER: {customer}
COMPONENT: {component}
NUMBER OF ESCALATIONS: {len(keys)}

TICKET DETAILS:
{json.dumps(ticket_context, indent=2)}

Based on the ticket summaries and descriptions above, provide:
1. A brief root cause hypothesis (what's likely causing these repeated issues?)
2. Common themes or patterns you notice across these escalations
3. One actionable recommendation to prevent future escalations

IMPORTANT: Respond ONLY in valid JSON format:
{{
    "root_cause": "Brief hypothesis about the root cause",
    "common_themes": ["Theme 1", "Theme 2"],
    "recommendation": "One specific actionable recommendation",
    "confidence": "low|medium|high"
}}"""

        # Call LLM
        response = await analyzer._call_llm(prompt)
        parsed = analyzer._parse_llm_response(response)

        if parsed.get("parse_error"):
            return {
                **TECH_PREVIEW_META,
                "ai_summary": None,
                "raw_response": response[:500],
                "fallback_summary": f"AI analysis incomplete. {customer} has {len(keys)} escalations for {component}.",
            }

        return {
            **TECH_PREVIEW_META,
            "ai_summary": parsed,
            "customer": customer,
            "component": component,
            "ticket_count": len(keys),
            "analyzed_tickets": len(pattern_tickets),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error summarizing pattern for %s/%s: %s", customer, component, e)
        return {
            **TECH_PREVIEW_META,
            "ai_summary": None,
            "error": str(e),
            "fallback_summary": f"Error analyzing pattern. {customer} has multiple escalations for {component}.",
        }

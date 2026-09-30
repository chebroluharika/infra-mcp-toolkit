# Merge Status Feature — Release Content for R137

## Overview

Adds a **Merge Status** column to the "Release Content" section of the Release Readiness page. Shows PR/commit merge progress for every NPLAN and its sub-tickets (ENG-*) so the team can see at a glance how much code has landed.

## What Changed

### Backend

| File | Change |
|------|--------|
| `backend/services/jira_client.py` | New `get_issue_dev_status()` method — fetches PRs and commits from JIRA's Development panel for a given issue key. Includes `_dev_status_request` helper with 429 retry + exponential backoff. |
| `backend/services/jira_client.py` | Semaphore increased from 10 → 20 to improve throughput for batch dev-status fetches. |
| `backend/routers/jira.py` | New endpoint `GET /api/jira/nplan-dev-status?release=R137` — aggregates merge status across all NPLANs in a release. |

### Frontend

| File | Change |
|------|--------|
| `src/services/api.js` | New method `getNplanDevStatus(release)` calling the backend endpoint. |
| `src/components/sections/ReleaseReadinessSection.js` | Added "Merge Status" column to the NPLAN table (7th column) and per-ENG-ticket merge status in the expanded bugs panel (6th column). |
| `src/components/sections/ReleaseReadinessSection.css` | Grid layouts updated (6→7 cols for NPLANs, 5→6 for bugs table). Added badge styles for MERGED/PARTIAL/OPEN/COMMITTED/NONE states. |

## Why It's Slow — API Call Breakdown

JIRA does **not** expose merge/PR data in its standard search API. The only way to get it is through the **Development Status REST API** (`/rest/dev-status/1.0/issue/detail`), which requires:

1. The **numeric issue ID** (not the key like `ENG-12345`)
2. Separate calls for **PRs** and **commits**

### Per ENG Ticket: 3 REST Calls

| # | Call | Purpose |
|---|------|---------|
| 1 | `GET /rest/api/3/issue/{key}` | Resolve issue key → numeric ID |
| 2 | `GET /rest/dev-status/1.0/issue/detail?issueId={id}&dataType=pullrequest` | Fetch PRs |
| 3 | `GET /rest/dev-status/1.0/issue/detail?issueId={id}&dataType=repository` | Fetch commits |

### Per NPLAN: 2 JQL Searches

| # | Call | Purpose |
|---|------|---------|
| 1 | JQL: `portfolioChildIssuesOf = "NPLAN-XXXX"` | Get child workitems |
| 2 | JQL: `labels = "nplan-xxxx"` | Get label-linked bugs |

### Total for a Release (Example: R137 with 6 NPLANs, ~200 ENG tickets)

| Category | Calls | Notes |
|----------|-------|-------|
| NPLAN workitem queries | 6 | One per NPLAN |
| NPLAN bug label queries | 6 | One per NPLAN |
| ENG ticket ID resolution | ~200 | One per unique ENG ticket |
| ENG ticket PR fetch | ~200 | One per unique ENG ticket |
| ENG ticket commit fetch | ~200 | One per unique ENG ticket |
| **Total** | **~612** | All to JIRA's API |

### Why ~600 calls can't be avoided

- JIRA's dev-status API has **no bulk endpoint** — it only accepts one issue ID at a time.
- The numeric ID must be fetched separately (JIRA search results return keys, not IDs in the dev-status format).
- PRs and commits are separate `dataType` parameters requiring separate calls.

### Rate Limiting Mitigations

| Technique | Detail |
|-----------|--------|
| Async concurrency | `asyncio.gather` with semaphore (20 concurrent) |
| 429 retry | Exponential backoff (2s, 4s, 8s) on rate-limit responses |
| Result caching | `jira_client` caches dev-status per issue key (5-min TTL) — second load is instant |
| Timeout guard | 30s per-ticket timeout prevents one slow call from blocking everything |

### Observed Performance

| Metric | Value |
|--------|-------|
| First load (cold) | ~90–120 seconds for ~200 ENG tickets |
| Subsequent loads (cached) | < 2 seconds |
| Cache TTL | 5 minutes |

## Merge Status Logic

For each ENG ticket, status is determined by this priority:

```
Has PRs?
  ├── All merged        → MERGED  (green)
  ├── Some merged       → PARTIAL (yellow)
  ├── Some open/draft   → OPEN    (blue)
  └── All declined      → DECLINED
No PRs, has commits?
  ├── Merged to develop/main/nplan branch → MERGED    (green)
  └── Not on target branch               → COMMITTED (purple)
No PRs, no commits     → NONE    (grey)
```

NPLAN-level badge shows `{merged_count}/{total_items}` where `total_items` is ALL sub-tickets (not just ones with dev activity).

## ENG Ticket Sources

Each NPLAN's sub-tickets come from **two sources**, de-duplicated by key:

1. **Child workitems** — JIRA parent/portfolio-child relationship (`portfolioChildIssuesOf`)
2. **Label-linked bugs** — Bugs tagged with label `nplan-xxxx` (lowercase)

Both are needed because some bugs are linked via labels only, not as direct children.

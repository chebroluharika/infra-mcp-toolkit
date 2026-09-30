"""
Release History Service
=======================

Stores and queries historical release snapshots for risk prediction.
Tracks metrics at each milestone phase to enable cross-release comparisons.

Storage: JSON file (simple, no database required)
Location: backend/data/release_history.json
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "release_history.json")

MILESTONE_PHASES = [
    "irr_minus_7",
    "irr_minus_3",
    "irr",
    "branch_cut_minus_3",
    "branch_cut",
    "final_build_minus_3",
    "final_build",
    "deploy_day1",
]


@dataclass
class PhaseMetrics:
    """Metrics captured at a specific milestone phase."""

    timestamp: str
    phase: str
    days_to_milestone: int
    p0_bugs: int
    p1_bugs: int
    p2_bugs: int
    total_open: int
    open_stories: int
    open_bugs: int
    code_review: int
    velocity_per_day: float
    test_pass_rate: Optional[float] = None
    build_success_rate: Optional[float] = None
    blockers_unassigned: int = 0
    rrs_score: Optional[float] = None


@dataclass
class ReleaseOutcome:
    """Final outcome of a release."""

    on_time: bool
    slip_days: int = 0
    blockers_at_release: int = 0
    final_rrs_score: Optional[float] = None
    notes: str = ""


@dataclass
class ReleaseHistory:
    """Complete history for a release."""

    release_id: str
    phases: Dict[str, PhaseMetrics]
    outcome: Optional[ReleaseOutcome] = None


def _ensure_data_dir():
    """Ensure data directory exists."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def _load_history() -> Dict[str, Any]:
    """Load release history from JSON file."""
    _ensure_data_dir()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading release history: %s", e)
    return {}


def _save_history(data: Dict[str, Any]):
    """Save release history to JSON file."""
    _ensure_data_dir()
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Saved release history to %s", HISTORY_FILE)
    except Exception as e:
        logger.error("Error saving release history: %s", e)


def save_release_snapshot(
    release_id: str,
    phase: str,
    metrics: Dict[str, Any],
    force: bool = False,
) -> bool:
    """
    Save a snapshot of release metrics at a specific phase.

    Args:
        release_id: Release identifier (e.g., "R136")
        phase: Milestone phase (e.g., "irr_minus_3", "branch_cut")
        metrics: Dictionary of metrics to store
        force: If True, overwrite existing snapshot

    Returns:
        True if saved, False if skipped (already exists and not forced)
    """
    history = _load_history()

    if release_id not in history:
        history[release_id] = {"phases": {}, "outcome": None}

    if phase in history[release_id].get("phases", {}) and not force:
        logger.debug("Snapshot for %s phase %s already exists", release_id, phase)
        return False

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "phase": phase,
        **metrics,
    }

    if "phases" not in history[release_id]:
        history[release_id]["phases"] = {}

    history[release_id]["phases"][phase] = snapshot
    _save_history(history)
    logger.info("Saved snapshot for %s at phase %s", release_id, phase)
    return True


def save_release_outcome(
    release_id: str,
    on_time: bool,
    slip_days: int = 0,
    blockers_at_release: int = 0,
    final_rrs_score: Optional[float] = None,
    notes: str = "",
) -> bool:
    """
    Record the final outcome of a release.

    Args:
        release_id: Release identifier
        on_time: Whether release shipped on schedule
        slip_days: Number of days slipped (if any)
        blockers_at_release: Number of blockers at release time
        final_rrs_score: Final RRS score
        notes: Additional notes

    Returns:
        True if saved successfully
    """
    history = _load_history()

    if release_id not in history:
        history[release_id] = {"phases": {}, "outcome": None}

    history[release_id]["outcome"] = {
        "on_time": on_time,
        "slip_days": slip_days,
        "blockers_at_release": blockers_at_release,
        "final_rrs_score": final_rrs_score,
        "notes": notes,
        "recorded_at": datetime.now().isoformat(),
    }

    _save_history(history)
    logger.info("Saved outcome for %s: on_time=%s, slip_days=%s", release_id, on_time, slip_days)
    return True


def get_release_history(release_id: str) -> Optional[Dict[str, Any]]:
    """
    Get complete history for a release.

    Args:
        release_id: Release identifier

    Returns:
        Dictionary with phases and outcome, or None if not found
    """
    history = _load_history()
    return history.get(release_id)


def get_historical_releases(
    phase: str,
    limit: int = 5,
    exclude_release: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get historical releases that have data for a specific phase.

    Args:
        phase: Milestone phase to query
        limit: Maximum number of releases to return
        exclude_release: Release to exclude (usually current release)

    Returns:
        List of releases with their phase data and outcomes
    """
    history = _load_history()
    results = []

    for release_id, data in history.items():
        if exclude_release and release_id == exclude_release:
            continue

        phases = data.get("phases", {})
        if phase in phases:
            results.append(
                {
                    "release_id": release_id,
                    "phase_data": phases[phase],
                    "outcome": data.get("outcome"),
                }
            )

    results.sort(key=lambda x: x["release_id"], reverse=True)
    return results[:limit]


def get_release_outcome(release_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the outcome for a specific release.

    Args:
        release_id: Release identifier

    Returns:
        Outcome dictionary or None if not found
    """
    history = _load_history()
    release_data = history.get(release_id, {})
    return release_data.get("outcome")


def get_all_releases() -> List[str]:
    """Get list of all releases in history."""
    history = _load_history()
    return sorted(history.keys(), reverse=True)


def calculate_historical_averages(
    phase: str,
    exclude_release: Optional[str] = None,
) -> Dict[str, float]:
    """
    Calculate average metrics across historical releases at a phase.

    Args:
        phase: Milestone phase
        exclude_release: Release to exclude

    Returns:
        Dictionary of average values for each metric
    """
    releases = get_historical_releases(phase, limit=10, exclude_release=exclude_release)

    if not releases:
        return {}

    metrics_keys = [
        "p0_bugs",
        "p1_bugs",
        "p2_bugs",
        "total_open",
        "open_stories",
        "open_bugs",
        "code_review",
        "velocity_per_day",
        "test_pass_rate",
        "build_success_rate",
        "blockers_unassigned",
        "rrs_score",
    ]

    averages = {}
    for key in metrics_keys:
        values = [r["phase_data"].get(key) for r in releases if r["phase_data"].get(key) is not None]
        if values:
            averages[key] = round(sum(values) / len(values), 2)

    averages["releases_compared"] = len(releases)
    return averages


def get_on_time_rate(phase: str, exclude_release: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate on-time delivery rate for releases at a given phase.

    Args:
        phase: Milestone phase
        exclude_release: Release to exclude

    Returns:
        Dictionary with on_time_rate and counts
    """
    releases = get_historical_releases(phase, limit=20, exclude_release=exclude_release)

    releases_with_outcome = [r for r in releases if r.get("outcome")]

    if not releases_with_outcome:
        return {"available": False, "message": "No historical outcomes available"}

    on_time_count = sum(1 for r in releases_with_outcome if r["outcome"].get("on_time", False))
    total = len(releases_with_outcome)

    return {
        "available": True,
        "on_time_count": on_time_count,
        "total_releases": total,
        "on_time_rate": round((on_time_count / total) * 100, 1) if total > 0 else 0,
    }


def determine_current_phase(days_to_irr: int, days_to_branch_cut: int, days_to_final_build: int) -> str:
    """
    Determine the current milestone phase based on days remaining.

    Args:
        days_to_irr: Days until IRR
        days_to_branch_cut: Days until branch cut
        days_to_final_build: Days until final build

    Returns:
        Phase identifier string
    """
    if days_to_irr > 7:
        return "pre_irr"
    elif days_to_irr > 3:
        return "irr_minus_7"
    elif days_to_irr > 0:
        return "irr_minus_3"
    elif days_to_branch_cut > 3:
        return "irr"
    elif days_to_branch_cut > 0:
        return "branch_cut_minus_3"
    elif days_to_final_build > 3:
        return "branch_cut"
    elif days_to_final_build > 0:
        return "final_build_minus_3"
    else:
        return "final_build"


def get_similar_releases(
    current_metrics: Dict[str, Any],
    phase: str,
    exclude_release: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Find releases most similar to current metrics at a given phase.

    Uses weighted similarity based on key metrics.

    Args:
        current_metrics: Current release metrics
        phase: Milestone phase
        exclude_release: Release to exclude
        limit: Maximum results

    Returns:
        List of similar releases with similarity scores
    """
    releases = get_historical_releases(phase, limit=10, exclude_release=exclude_release)

    if not releases:
        return []

    weights = {
        "p1_bugs": 3.0,
        "total_open": 2.0,
        "velocity_per_day": 2.5,
        "test_pass_rate": 1.5,
        "build_success_rate": 1.0,
    }

    similarities = []
    for release in releases:
        phase_data = release["phase_data"]
        score = 0.0
        max_score = 0.0

        for metric, weight in weights.items():
            current_val = current_metrics.get(metric)
            hist_val = phase_data.get(metric)

            if current_val is not None and hist_val is not None:
                max_score += weight
                if hist_val == 0 and current_val == 0:
                    score += weight
                elif hist_val != 0:
                    diff_ratio = abs(current_val - hist_val) / max(abs(hist_val), 1)
                    similarity = max(0, 1 - diff_ratio)
                    score += weight * similarity

        if max_score > 0:
            final_similarity = round(score / max_score, 2)
            outcome = release.get("outcome", {})
            outcome_str = "on_time" if outcome.get("on_time") else f"slipped_{outcome.get('slip_days', '?')}_days"

            similarities.append(
                {
                    "release": release["release_id"],
                    "similarity": final_similarity,
                    "outcome": outcome_str if outcome else "unknown",
                    "outcome_data": outcome,
                    "phase_metrics": phase_data,
                }
            )

    similarities.sort(key=lambda x: x["similarity"], reverse=True)
    return similarities[:limit]

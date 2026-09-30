#!/usr/bin/env python3
"""
Seed Release History
====================

One-time script to backfill historical release data for risk prediction.
Uses existing trend snapshots and known release outcomes to populate
the release_history.json file.

Usage:
    python -m scripts.seed_release_history

    # Or with specific releases
    python -m scripts.seed_release_history --releases R133,R134,R135
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_release_dates
from services.release_history import HISTORY_FILE, get_release_history, save_release_outcome, save_release_snapshot
from services.trend_tracker import _load_snapshots as load_trend_snapshots

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


KNOWN_OUTCOMES = {
    "R133": {"on_time": True, "slip_days": 0, "blockers_at_release": 0, "notes": "Shipped on schedule"},
    "R134": {
        "on_time": True,
        "slip_days": 0,
        "blockers_at_release": 1,
        "notes": "Shipped on schedule with 1 known issue",
    },
    "R135": {"on_time": True, "slip_days": 0, "blockers_at_release": 0, "notes": "Completed release"},
}


def estimate_velocity(snapshots: list) -> float:
    """Estimate velocity from trend snapshots."""
    if len(snapshots) < 2:
        return 0.0

    snapshots = sorted(snapshots, key=lambda x: x.get("timestamp", ""))

    first = snapshots[0]
    last = snapshots[-1]

    first_total = first.get("total_open", 0)
    last_total = last.get("total_open", 0)

    items_resolved = first_total - last_total

    try:
        first_time = datetime.fromisoformat(first.get("timestamp", ""))
        last_time = datetime.fromisoformat(last.get("timestamp", ""))
        days = max((last_time - first_time).total_seconds() / 86400, 0.1)
    except (ValueError, TypeError):
        days = len(snapshots) / 12

    return round(items_resolved / days, 2) if days > 0 else 0.0


def extract_phase_from_date(release_id: str, snapshot_date: str) -> str:
    """Determine the phase based on snapshot date relative to milestones."""
    try:
        dates = get_release_dates(release_id)
        if not dates:
            return "unknown"

        snapshot_dt = datetime.strptime(snapshot_date, "%Y-%m-%d").date()

        irr_date = dates.get("irr")
        branch_cut_date = dates.get("branch_cut")
        final_build_date = dates.get("final_build")

        milestones = []
        if irr_date:
            if isinstance(irr_date, str):
                irr_date = datetime.strptime(irr_date, "%Y-%m-%d").date()
            milestones.append(("irr", irr_date))
        if branch_cut_date:
            if isinstance(branch_cut_date, str):
                branch_cut_date = datetime.strptime(branch_cut_date, "%Y-%m-%d").date()
            milestones.append(("branch_cut", branch_cut_date))
        if final_build_date:
            if isinstance(final_build_date, str):
                final_build_date = datetime.strptime(final_build_date, "%Y-%m-%d").date()
            milestones.append(("final_build", final_build_date))

        for milestone_name, milestone_date in milestones:
            days_diff = (milestone_date - snapshot_dt).days

            if days_diff > 7:
                continue
            elif days_diff > 3:
                return f"{milestone_name}_minus_7"
            elif days_diff > 0:
                return f"{milestone_name}_minus_3"
            elif days_diff >= -1:
                return milestone_name

        return "post_release"

    except Exception as e:
        logger.warning("Failed to extract phase for %s on %s: %s", release_id, snapshot_date, e)
        return "unknown"


def seed_from_trend_snapshots(releases: list = None):
    """Seed release history from existing trend snapshots."""
    trend_snapshots = load_trend_snapshots()

    if not trend_snapshots:
        logger.warning("No trend snapshots found to seed from")
        return

    releases_to_process = releases or list(trend_snapshots.keys())

    for release_id in releases_to_process:
        if release_id not in trend_snapshots:
            logger.info("No trend data for %s, skipping", release_id)
            continue

        release_snapshots = trend_snapshots[release_id]
        logger.info("Processing %s with %d trend snapshots", release_id, len(release_snapshots))

        snapshots_by_phase = {}

        for snapshot_key, snapshot_data in release_snapshots.items():
            snapshot_date = snapshot_data.get("date", "")
            if not snapshot_date:
                continue

            phase = extract_phase_from_date(release_id, snapshot_date)
            if phase == "unknown" or phase == "post_release":
                continue

            if phase not in snapshots_by_phase:
                snapshots_by_phase[phase] = []
            snapshots_by_phase[phase].append(snapshot_data)

        all_snapshots = list(release_snapshots.values())
        velocity = estimate_velocity(all_snapshots)

        for phase, phase_snapshots in snapshots_by_phase.items():
            latest = max(phase_snapshots, key=lambda x: x.get("timestamp", ""))

            metrics = {
                "p0_bugs": 0,
                "p1_bugs": 0,
                "p2_bugs": 0,
                "total_open": latest.get("total_open", 0),
                "open_stories": latest.get("open_stories", 0),
                "open_bugs": latest.get("open_bugs", 0),
                "code_review": latest.get("code_review", 0),
                "velocity_per_day": velocity,
                "test_pass_rate": None,
                "build_success_rate": None,
                "blockers_unassigned": 0,
                "rrs_score": None,
            }

            saved = save_release_snapshot(release_id, phase, metrics, force=False)
            if saved:
                logger.info("  Saved %s phase: %s", release_id, phase)
            else:
                logger.debug("  Phase %s already exists for %s", phase, release_id)


def seed_known_outcomes():
    """Seed known release outcomes."""
    for release_id, outcome in KNOWN_OUTCOMES.items():
        existing = get_release_history(release_id)
        if existing and existing.get("outcome"):
            logger.info("Outcome already exists for %s, skipping", release_id)
            continue

        saved = save_release_outcome(
            release_id=release_id,
            on_time=outcome["on_time"],
            slip_days=outcome["slip_days"],
            blockers_at_release=outcome["blockers_at_release"],
            notes=outcome["notes"],
        )
        if saved:
            logger.info("Saved outcome for %s: on_time=%s", release_id, outcome["on_time"])


def seed_sample_data():
    """Create sample historical data for demonstration if no real data exists."""
    sample_releases = ["R133", "R134", "R135"]

    for release_id in sample_releases:
        existing = get_release_history(release_id)
        if existing and existing.get("phases"):
            logger.info("Data already exists for %s, skipping sample data", release_id)
            continue

        logger.info("Creating sample data for %s", release_id)

        phases = ["irr_minus_7", "irr_minus_3", "irr", "branch_cut_minus_3", "branch_cut"]

        base_metrics = {
            "R133": {"p1_bugs": 6, "total_open": 35, "velocity": 4.5},
            "R134": {"p1_bugs": 8, "total_open": 42, "velocity": 3.8},
            "R135": {"p1_bugs": 5, "total_open": 30, "velocity": 5.2},
        }

        base = base_metrics.get(release_id, {"p1_bugs": 6, "total_open": 35, "velocity": 4.0})

        for i, phase in enumerate(phases):
            decay_factor = 1.0 - (i * 0.15)

            metrics = {
                "p0_bugs": 0,
                "p1_bugs": max(0, int(base["p1_bugs"] * decay_factor)),
                "p2_bugs": max(0, int(base["p1_bugs"] * 1.5 * decay_factor)),
                "total_open": max(0, int(base["total_open"] * decay_factor)),
                "open_stories": max(0, int(base["total_open"] * 0.4 * decay_factor)),
                "open_bugs": max(0, int(base["total_open"] * 0.6 * decay_factor)),
                "code_review": max(0, int(5 * decay_factor)),
                "velocity_per_day": base["velocity"],
                "test_pass_rate": 75 + (i * 4),
                "build_success_rate": 88 + (i * 2),
                "blockers_unassigned": max(0, 3 - i),
                "rrs_score": 60 + (i * 8),
            }

            save_release_snapshot(release_id, phase, metrics, force=True)
            logger.info("  Created sample %s phase: %s", release_id, phase)


def main():
    parser = argparse.ArgumentParser(description="Seed release history data for risk prediction")
    parser.add_argument(
        "--releases", type=str, help="Comma-separated list of releases to process (e.g., R133,R134,R135)"
    )
    parser.add_argument("--sample", action="store_true", help="Create sample data for demonstration")
    parser.add_argument("--outcomes-only", action="store_true", help="Only seed known outcomes, not phase data")

    args = parser.parse_args()

    releases = args.releases.split(",") if args.releases else None

    logger.info("=" * 60)
    logger.info("Release History Seeding")
    logger.info("=" * 60)

    if args.sample:
        logger.info("Creating sample data for demonstration...")
        seed_sample_data()
    elif args.outcomes_only:
        logger.info("Seeding known outcomes only...")
    else:
        logger.info("Seeding from trend snapshots...")
        seed_from_trend_snapshots(releases)

    logger.info("Seeding known outcomes...")
    seed_known_outcomes()

    logger.info("=" * 60)
    logger.info("Seeding complete!")
    logger.info("Data saved to: %s", HISTORY_FILE)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

"""
Risk Analysis Cache Service
===========================

Caches AI-driven risk analysis results for fast dashboard reads.

Architecture:
    Agent (slow, 60-120s) → Saves to cache
    Dashboard (fast) → Reads from cache

Cache Strategy:
- JSON file storage (simple, no database required)
- TTL-based expiration
- Manual refresh trigger
- Automatic refresh when metrics change significantly

Storage: backend/data/risk_cache.json
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CACHE_FILE = os.path.join(DATA_DIR, "risk_cache.json")

DEFAULT_TTL_HOURS = 4


def _ensure_data_dir():
    """Ensure data directory exists."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def _load_cache() -> Dict:
    """Load cache from JSON file."""
    _ensure_data_dir()
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading risk cache: %s", e)
    return {}


def _save_cache(data: Dict):
    """Save cache to JSON file."""
    _ensure_data_dir()
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error("Error saving risk cache: %s", e)


def save_risk_analysis(
    release_id: str,
    analysis: Dict[str, Any],
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> bool:
    """
    Save risk analysis to cache.

    Args:
        release_id: Release ID (e.g., "R136")
        analysis: Complete risk analysis from agent
        ttl_hours: Time-to-live in hours

    Returns:
        True if saved successfully
    """
    cache = _load_cache()

    now = datetime.now()
    expires_at = now + timedelta(hours=ttl_hours)

    cache[release_id] = {
        "release_id": release_id,
        "analysis": analysis,
        "generated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_hours": ttl_hours,
        "refresh_count": cache.get(release_id, {}).get("refresh_count", 0) + 1,
    }

    _save_cache(cache)
    logger.info("Cached risk analysis for %s (expires: %s)", release_id, expires_at)
    return True


def get_cached_risk_analysis(
    release_id: str,
    max_age_hours: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get cached risk analysis for a release.

    Args:
        release_id: Release ID (e.g., "R136")
        max_age_hours: Optional max age in hours (overrides TTL)

    Returns:
        Cached analysis or None if expired/not found
    """
    cache = _load_cache()

    if release_id not in cache:
        return None

    entry = cache[release_id]

    # Check expiration
    try:
        expires_at = datetime.fromisoformat(entry["expires_at"])
        generated_at = datetime.fromisoformat(entry["generated_at"])
    except (ValueError, KeyError):
        return None

    now = datetime.now()

    # Check TTL expiration
    if now > expires_at:
        logger.debug("Cache expired for %s", release_id)
        return None

    # Check max_age if specified
    if max_age_hours is not None:
        age_hours = (now - generated_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            logger.debug("Cache too old for %s (%d hours)", release_id, age_hours)
            return None

    # Add cache metadata
    analysis = entry.get("analysis", {})
    analysis["_cache"] = {
        "cached": True,
        "generated_at": entry["generated_at"],
        "expires_at": entry["expires_at"],
        "age_minutes": int((now - generated_at).total_seconds() / 60),
        "refresh_count": entry.get("refresh_count", 1),
    }

    return analysis


def is_cache_valid(release_id: str) -> bool:
    """Check if cache is valid (not expired)."""
    return get_cached_risk_analysis(release_id) is not None


def invalidate_cache(release_id: str) -> bool:
    """
    Invalidate cache for a release.

    Args:
        release_id: Release ID to invalidate

    Returns:
        True if cache was invalidated
    """
    cache = _load_cache()

    if release_id in cache:
        del cache[release_id]
        _save_cache(cache)
        logger.info("Invalidated cache for %s", release_id)
        return True

    return False


def get_cache_status(release_id: str) -> Dict[str, Any]:
    """
    Get cache status for a release.

    Returns:
        Cache metadata including validity, age, etc.
    """
    cache = _load_cache()

    if release_id not in cache:
        return {
            "cached": False,
            "message": "No cached analysis available",
        }

    entry = cache[release_id]

    try:
        generated_at = datetime.fromisoformat(entry["generated_at"])
        expires_at = datetime.fromisoformat(entry["expires_at"])
    except (ValueError, KeyError):
        return {
            "cached": False,
            "message": "Cache corrupted",
        }

    now = datetime.now()
    is_valid = now < expires_at
    age_minutes = int((now - generated_at).total_seconds() / 60)
    ttl_remaining = int((expires_at - now).total_seconds() / 60) if is_valid else 0

    return {
        "cached": is_valid,
        "generated_at": entry["generated_at"],
        "expires_at": entry["expires_at"],
        "age_minutes": age_minutes,
        "ttl_remaining_minutes": ttl_remaining,
        "refresh_count": entry.get("refresh_count", 1),
        "valid": is_valid,
    }


def should_auto_refresh(release_id: str, metrics: Dict[str, Any]) -> bool:
    """
    Check if cache should auto-refresh based on metric changes.

    Triggers refresh when:
    - P0 count changes (critical)
    - RRS drops significantly (>10 points)
    - Velocity changes direction

    Args:
        release_id: Release ID
        metrics: Current metrics to compare against cached

    Returns:
        True if refresh is recommended
    """
    cached = get_cached_risk_analysis(release_id)

    if not cached:
        return True

    cached_analysis = cached.get("analysis", {})

    # Check P0 count change
    cached_p0 = cached_analysis.get("risk_signals", {}).get("details", [])
    cached_p0_count = sum(1 for s in cached_p0 if s.get("signal") == "P0_BLOCKERS")
    current_p0 = metrics.get("p0_count", 0)

    if current_p0 != cached_p0_count:
        logger.info("P0 count changed (%d -> %d) - refresh recommended", cached_p0_count, current_p0)
        return True

    # Check significant RRS change
    cached_rrs = cached_analysis.get("rrs_score", 0)
    current_rrs = metrics.get("rrs_score", 0)

    if current_rrs and cached_rrs and abs(current_rrs - cached_rrs) > 10:
        logger.info("RRS changed significantly (%d -> %d) - refresh recommended", cached_rrs, current_rrs)
        return True

    return False


def get_all_cached_releases() -> Dict[str, Dict]:
    """
    Get status of all cached releases.

    Returns:
        Dict mapping release_id to cache status
    """
    cache = _load_cache()

    result = {}
    for release_id in cache:
        result[release_id] = get_cache_status(release_id)

    return result

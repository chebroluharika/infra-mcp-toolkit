"""
Utilities Package
=================

Common utility functions used across the backend.
"""

from .jira import (
    CRITICAL_PRIORITIES,
    analyze_blockers,
    determine_phase,
    get_phase_status,
    get_readiness_recommendation,
    get_release_id_from_param,
    parse_date_safe,
    parse_version_from_release,
)
from .testrail import (
    aggregate_run_to_platform,
    build_empty_milestone_response,
    build_empty_untested_response,
    build_test_run_entry,
    calculate_other_count,
    calculate_run_pass_rate,
    calculate_run_total,
    finalize_platform_stats,
    initialize_platform_data,
    parse_platform_from_run_name,
)
from .time_utils import format_relative_time, get_current_time_formatted
from .xml_utils import parse_junit_xml

__all__ = [
    # JIRA utilities
    "parse_date_safe",
    "parse_version_from_release",
    "get_release_id_from_param",
    "determine_phase",
    "get_phase_status",
    "get_readiness_recommendation",
    "analyze_blockers",
    # JIRA Constants
    "CRITICAL_PRIORITIES",
    # TestRail utilities
    "parse_platform_from_run_name",
    "calculate_run_pass_rate",
    "calculate_other_count",
    "calculate_run_total",
    "build_empty_milestone_response",
    "build_empty_untested_response",
    "build_test_run_entry",
    "initialize_platform_data",
    "aggregate_run_to_platform",
    "finalize_platform_stats",
    # Time utilities
    "format_relative_time",
    "get_current_time_formatted",
    # XML utilities
    "parse_junit_xml",
]

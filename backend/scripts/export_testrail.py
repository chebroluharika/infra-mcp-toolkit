#!/usr/bin/env python3
"""
TestRail Bulk Export Script
===========================

One-time bulk export of TestRail test cases to local JSON cache.
Run this during off-peak hours to avoid rate limiting issues.

The exported JSON can then be used by TestRailIndexer.index_from_cache()
for FAISS indexing without hitting the TestRail API.

Usage:
    # Export all test cases for a milestone
    python export_testrail.py --project-id 38 --milestone-id 5319

    # Export with custom output file
    python export_testrail.py --project-id 38 --milestone-id 5319 --output custom_cache.json

    # Export with longer delays to be extra safe on rate limits
    python export_testrail.py --project-id 38 --milestone-id 5319 --delay 1.0

Environment Variables:
    TESTRAIL_URL - TestRail base URL
    TESTRAIL_USERNAME - Your email
    TESTRAIL_API_KEY - API key from TestRail

Output:
    Creates backend/data/testrail_cache.json with structure:
    {
        "metadata": {
            "exported_at": "2024-03-13T10:00:00",
            "project_id": 38,
            "milestone_id": 5319,
            "total_runs": 50,
            "total_tests": 5000
        },
        "runs": [
            {
                "id": 1234,
                "name": "Run Name",
                "tests": [
                    {
                        "id": 5678,
                        "case_id": 9012,
                        "title": "Test Case Title",
                        "case_title": "...",
                        "case_description": "...",
                        "case_steps": "...",
                        "case_expected": "...",
                        "status": "passed",
                        "priority_id": 3,
                        "case_refs": "JIRA-123"
                    }
                ]
            }
        ]
    }
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add parent directories to path
script_dir = Path(__file__).parent
backend_dir = script_dir.parent
project_root = backend_dir.parent

sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Default output path
DATA_DIR = backend_dir / "data"
DEFAULT_CACHE_FILE = DATA_DIR / "testrail_cache.json"


async def export_testrail(
    project_id: int,
    milestone_id: int,
    output_file: Path,
    delay: float = 0.5,
    include_completed: bool = False,
) -> Dict[str, Any]:
    """
    Export all test cases from a TestRail milestone to JSON.

    Args:
        project_id: TestRail project ID
        milestone_id: TestRail milestone ID
        output_file: Path to output JSON file
        delay: Delay between API requests (seconds)
        include_completed: Include completed runs (default: only active runs)

    Returns:
        Export statistics
    """
    from services.testrail_client import TestRailClient

    client = TestRailClient()

    if not client.is_configured():
        logger.error("TestRail not configured. Set TESTRAIL_URL, TESTRAIL_USERNAME, TESTRAIL_API_KEY")
        return {"error": "TestRail not configured"}

    logger.info(f"Starting TestRail export for project {project_id}, milestone {milestone_id}")
    logger.info(f"Using delay of {delay}s between requests")

    # Fetch all runs for milestone
    logger.info("Fetching runs for milestone...")
    all_runs = await client.get_all_runs_for_milestone(project_id, milestone_id)

    if include_completed:
        runs_to_export = all_runs
    else:
        runs_to_export = [r for r in all_runs if not r.get("is_completed", False)]
        if not runs_to_export:
            logger.warning("No active runs found, falling back to all runs (max 50)")
            runs_to_export = all_runs[:50]

    logger.info(f"Found {len(all_runs)} total runs, exporting {len(runs_to_export)} runs")

    # Export data structure
    export_data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "project_id": project_id,
            "milestone_id": milestone_id,
            "testrail_url": client.base_url,
            "total_runs": len(runs_to_export),
            "total_tests": 0,
            "export_settings": {
                "delay": delay,
                "include_completed": include_completed,
            },
        },
        "runs": [],
    }

    total_tests = 0
    failed_runs = 0

    for i, run in enumerate(runs_to_export, 1):
        run_id = run["id"]
        run_name = run.get("name", f"Run {run_id}")

        logger.info(f"[{i}/{len(runs_to_export)}] Exporting run: {run_name} (ID: {run_id})")

        try:
            # Fetch tests with case details
            tests = await client.get_tests_with_cases(run_id)

            run_data = {
                "id": run_id,
                "name": run_name,
                "description": run.get("description", ""),
                "is_completed": run.get("is_completed", False),
                "passed_count": run.get("passed_count", 0),
                "failed_count": run.get("failed_count", 0),
                "blocked_count": run.get("blocked_count", 0),
                "untested_count": run.get("untested_count", 0),
                "tests": [],
            }

            for test in tests:
                test_data = {
                    "id": test.get("id"),
                    "case_id": test.get("case_id"),
                    "title": test.get("title", ""),
                    "case_title": test.get("case_title", ""),
                    "case_description": test.get("case_description", ""),
                    "case_steps": test.get("case_steps", ""),
                    "case_expected": test.get("case_expected", ""),
                    "status": test.get("status", "unknown"),
                    "status_id": test.get("status_id"),
                    "priority_id": test.get("priority_id"),
                    "case_refs": test.get("case_refs", ""),
                    "assignee_id": test.get("assignee_id"),
                    "type_id": test.get("type_id"),
                }
                run_data["tests"].append(test_data)
                total_tests += 1

            export_data["runs"].append(run_data)
            logger.info(f"  → Exported {len(tests)} tests from '{run_name}'")

            # Rate limiting delay
            await asyncio.sleep(delay)

        except Exception as e:
            logger.error(f"  ✗ Failed to export run {run_id}: {e}")
            failed_runs += 1
            # Continue with other runs
            await asyncio.sleep(delay * 2)  # Extra delay after error
            continue

    # Update metadata with final counts
    export_data["metadata"]["total_tests"] = total_tests
    export_data["metadata"]["failed_runs"] = failed_runs
    export_data["metadata"]["successful_runs"] = len(runs_to_export) - failed_runs

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Save to file
    logger.info(f"Saving export to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    stats = {
        "status": "success",
        "output_file": str(output_file),
        "file_size_mb": round(file_size_mb, 2),
        "total_runs": len(runs_to_export),
        "successful_runs": len(runs_to_export) - failed_runs,
        "failed_runs": failed_runs,
        "total_tests": total_tests,
        "exported_at": export_data["metadata"]["exported_at"],
    }

    logger.info("=" * 60)
    logger.info("Export Complete!")
    logger.info(f"  Output file: {output_file}")
    logger.info(f"  File size: {file_size_mb:.2f} MB")
    logger.info(f"  Total runs: {len(runs_to_export)} ({failed_runs} failed)")
    logger.info(f"  Total tests: {total_tests}")
    logger.info("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Export TestRail test cases to local JSON cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Export milestone 5319 from project 38
    python export_testrail.py --project-id 38 --milestone-id 5319

    # Export with custom delay (1 second between requests)
    python export_testrail.py --project-id 38 --milestone-id 5319 --delay 1.0

    # Include completed runs
    python export_testrail.py --project-id 38 --milestone-id 5319 --include-completed

    # Custom output file
    python export_testrail.py --project-id 38 --milestone-id 5319 --output my_cache.json
        """,
    )

    parser.add_argument(
        "--project-id",
        type=int,
        required=True,
        help="TestRail project ID",
    )
    parser.add_argument(
        "--milestone-id",
        type=int,
        required=True,
        help="TestRail milestone ID",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_CACHE_FILE),
        help=f"Output JSON file path (default: {DEFAULT_CACHE_FILE})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between API requests in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--include-completed",
        action="store_true",
        help="Include completed runs (default: only active runs)",
    )

    args = parser.parse_args()

    output_path = Path(args.output)

    # Run export
    stats = asyncio.run(
        export_testrail(
            project_id=args.project_id,
            milestone_id=args.milestone_id,
            output_file=output_path,
            delay=args.delay,
            include_completed=args.include_completed,
        )
    )

    if stats.get("error"):
        sys.exit(1)

    print(f"\nExport saved to: {output_path}")
    print("You can now run indexing with: curl -X POST 'http://localhost:8000/api/index/testrail/reindex-from-cache'")


if __name__ == "__main__":
    main()

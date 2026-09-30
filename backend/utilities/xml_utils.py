"""
XML Utilities
=============

Common XML parsing utilities, including JUnit test result parsing.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)


def parse_junit_xml(xml_file: str) -> Dict:
    """
    Parse JUnit XML test results.

    Supports standard JUnit XML format with testsuite element containing
    tests, failures, errors, and skipped counts.

    Args:
        xml_file: Path to JUnit XML file

    Returns:
        Dict with parsed test results:
        - total: Total number of tests
        - passed: Number of passed tests
        - failed: Number of failed tests
        - error: Number of error tests
        - skipped: Number of skipped tests
        - timestamp: Test run timestamp
    """
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Get testsuite element (root might be testsuite or testsuites)
        testsuite = root if root.tag == "testsuite" else root.find(".//testsuite")

        if testsuite is not None:
            total = int(testsuite.get("tests", 0))
            failures = int(testsuite.get("failures", 0))
            errors = int(testsuite.get("errors", 0))
            skipped = int(testsuite.get("skipped", 0))
            passed = total - (failures + errors + skipped)

            return {
                "total": total,
                "passed": passed,
                "failed": failures,
                "error": errors,
                "skipped": skipped,
                "timestamp": testsuite.get("timestamp", datetime.now().isoformat()),
            }
        logger.warning("No testsuite element found in %s", xml_file)
        return _empty_junit_result()

    except ET.ParseError as parse_err:
        logger.error("XML parse error in %s: %s", xml_file, parse_err)
        return {**_empty_junit_result(), "parse_error": str(parse_err)}
    except (OSError, ValueError) as err:
        logger.error("Error parsing XML file %s: %s", xml_file, err)
        return {**_empty_junit_result(), "parse_error": str(err)}


def _empty_junit_result() -> Dict:
    """Return empty JUnit result structure."""
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
    }

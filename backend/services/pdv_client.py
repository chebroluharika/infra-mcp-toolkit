"""
PDV (Post-Deployment Validation) Client Service
================================================

Fetches PDV status data from YourCompany Insights Platform Query Service API.
Shows status for staging, preprod, and prod deployment days (Day 1-4).

API: https://insights-platform.example.com/ip_queryservice/v1/releasemgmt/pdv_runs

Features:
- Simple Query Service API for PDV run data
- Token from PDVService auth file or environment variable
- Status change detection for Slack notifications

Authentication: Okta Bearer Token (valid for 24 hours)

Token Priority:
1. INSIGHTS_PLATFORM_TOKEN or OKTA_TOKEN environment variable
2. PDVService auth token file (~/.config/your-pdv-service/auth_token)

Token Refresh:
Run pdv-auth tool manually (opens browser for Okta login):
  ~/Downloads/dist/pdv-auth-darwin-amd64  # macOS
  ~/.local/bin/pdv-auth-linux-amd64       # Linux
"""

import base64
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Data directory for caching
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data", "pdv")
CONFIG_FILE = os.path.join(DATA_DIR, "pdv_config.json")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

# PDVService auth token location
PDV_TOKEN_FILE = Path.home() / ".config" / "your-pdv-service" / "auth_token"


def _load_pdv_config() -> Dict:
    """Load PDV configuration from config file with defaults."""
    defaults = {
        "api": {
            "query_service_url": "https://insights-platform.example.com/ip_queryservice/v1/releasemgmt",
        },
        "target_components": ["Your-Product", "Client", "DataNewTenantMapper", "PDFReportScheduler"],
        "target_applications": ["DP", "MP", "MP_Manual", "DP_Compliance", "MP_Compliance", "MP_Manual_Compliance"],
        "day_mapping": {
            "Day 1": "prod day 1",
            "Day 2": "prod day 2",
            "Day 3": "prod day 3",
            "Day 4": "prod day 4",
            "Staging": "staging",
        },
    }

    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            for key, value in defaults.items():
                if key not in config:
                    config[key] = value
            return config
        except Exception as e:
            logger.warning("Failed to load PDV config: %s, using defaults", e)

    return defaults


# Load configuration
PDV_CONFIG = _load_pdv_config()

# API Configuration
QUERY_SERVICE_URL = PDV_CONFIG["api"]["query_service_url"]

# Target components and applications to filter
TARGET_COMPONENTS = PDV_CONFIG.get("target_components", {})
if isinstance(TARGET_COMPONENTS, dict):
    TARGET_COMPONENT_NAMES = [c.get("name", k) for k, c in TARGET_COMPONENTS.items()]
else:
    TARGET_COMPONENT_NAMES = TARGET_COMPONENTS

TARGET_APPLICATIONS = PDV_CONFIG.get("target_applications", [])
DAY_MAPPING = PDV_CONFIG.get("day_mapping", {})


class PDVClient:
    """Client for fetching PDV status from YourCompany Insights Platform Query Service."""

    def __init__(self, token: str = None):
        """Initialize PDV client."""
        self._ensure_data_dirs()
        self._token = token

    def _ensure_data_dirs(self):
        """Create data directories if they don't exist."""
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)

    # =========================================================================
    # Token Management
    # =========================================================================

    def get_token(self) -> str:
        """
        Get a valid bearer token.

        Priority:
        1. INSIGHTS_PLATFORM_TOKEN or OKTA_TOKEN environment variable
        2. PDVService auth token (~/.config/your-pdv-service/auth_token) - valid 24 hours

        For automated use, install pylclient for Vault integration.
        The scheduler will auto-fetch CLIENT_SECRET from Vault and refresh tokens.
        """
        # Priority 1: Environment variables (check both)
        for env_var in ["INSIGHTS_PLATFORM_TOKEN", "OKTA_TOKEN"]:
            env_token = os.getenv(env_var, "").strip()
            if env_token:
                if env_token.lower().startswith("bearer "):
                    env_token = env_token[7:].strip()
                if env_token.startswith("eyJ"):
                    if self._token != env_token:
                        logger.info("Using token from %s environment variable", env_var)
                    self._token = env_token
                    return env_token

        # Priority 2: PDVService auth token file (valid for 24 hours)
        pdv_service_token = self._load_pdv_service_token()
        if pdv_service_token:
            if self._token != pdv_service_token:
                logger.info("Using token from PDVService auth file: %s", PDV_TOKEN_FILE)
            self._token = pdv_service_token
            return pdv_service_token

        # Priority 3: Constructor token (for manual override)
        if self._token and self._token.startswith("eyJ"):
            return self._token

        raise Exception(
            "No valid PDV token available.\n"
            "Run pdv-auth to get a new token:\n"
            "  ~/Downloads/dist/pdv-auth-darwin-amd64\n"
            "Or set INSIGHTS_PLATFORM_TOKEN in .env"
        )

    def _load_pdv_service_token(self) -> Optional[str]:
        """Load token from PDVService auth file (~/.config/your-pdv-service/auth_token)."""
        if not PDV_TOKEN_FILE.is_file():
            return None
        try:
            token = PDV_TOKEN_FILE.read_text().strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            if token and token.startswith("eyJ"):
                # Check if token is expired
                if not self._is_token_expired(token):
                    return token
                else:
                    logger.warning("PDVService token is expired")
        except Exception as e:
            logger.warning("Failed to load PDVService token: %s", e)
        return None

    def _is_token_expired(self, token: str) -> bool:
        """Check if JWT token is expired."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return True
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            exp = decoded.get("exp")
            if not exp:
                return False
            return datetime.now(timezone.utc).timestamp() >= exp
        except Exception:
            return True

    def refresh_pdv_token(self) -> Optional[str]:
        """
        Refresh token using pdv-auth tool.

        The tool will open a browser for Okta authentication if needed.
        Downloads pdv-auth if not present.

        Returns:
            New token if successful

        Raises:
            Exception: If pdv-auth fails
        """
        import platform

        try:
            # Determine correct binary for platform
            system = platform.system().lower()
            arch = platform.machine().lower()

            if system == "darwin":
                binary_name = "pdv-auth-darwin-amd64"
            elif system == "linux":
                if "arm" in arch or "aarch" in arch:
                    binary_name = "pdv-auth-linux-arm64"
                else:
                    binary_name = "pdv-auth-linux-amd64"
            else:
                raise Exception(f"Unsupported platform: {system}")

            # Check common locations for pdv-auth
            search_paths = [
                Path.home() / "Downloads" / "dist" / binary_name,
                Path.home() / ".local" / "bin" / binary_name,
                Path("/tmp") / "dist" / binary_name,
            ]

            pdv_auth_bin = None
            for path in search_paths:
                if path.exists():
                    pdv_auth_bin = path
                    break

            if not pdv_auth_bin:
                # Download the tool
                logger.info("Downloading pdv-auth tool...")
                download_dir = Path.home() / ".local" / "bin"
                download_dir.mkdir(parents=True, exist_ok=True)

                download_url = (
                    f"https://artifactory-rd.example.com/artifactory/list/your-company-generic/"
                    f"qe/your-pdv-service-auth-tool/{binary_name}-latest.tar.gz"
                )
                download_cmd = f"curl -sL {download_url} | tar xzv -C {download_dir}"
                subprocess.run(download_cmd, shell=True, check=True)
                pdv_auth_bin = download_dir / "dist" / binary_name

                if not pdv_auth_bin.exists():
                    raise Exception(f"Failed to download pdv-auth to {pdv_auth_bin}")

            # Create token directory
            PDV_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Run pdv-auth (will open browser for auth)
            logger.info("Running pdv-auth to get new token...")
            result = subprocess.run(
                [str(pdv_auth_bin)], capture_output=True, text=True, timeout=120  # Longer timeout for browser auth
            )

            if result.returncode == 0 and PDV_TOKEN_FILE.is_file():
                token = PDV_TOKEN_FILE.read_text().strip()
                if token.lower().startswith("bearer "):
                    token = token[7:].strip()
                if token.startswith("eyJ"):
                    logger.info("Successfully refreshed token from pdv-auth")
                    self._token = token
                    return token

            logger.error("pdv-auth failed: %s", result.stderr)
            raise Exception(f"pdv-auth failed: {result.stderr or 'Unknown error'}")

        except Exception as e:
            logger.error("Failed to refresh token from pdv-auth: %s", e)
            return None

    def get_token_info(self) -> Dict:
        """Get information about the current token."""
        try:
            token = self.get_token()
        except Exception:
            return {"has_token": False, "is_valid": False, "message": "No token available"}

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return {"has_token": True, "is_valid": False, "message": "Invalid token format"}

            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = json.loads(base64.urlsafe_b64decode(payload))

            exp = decoded.get("exp")
            now = datetime.now(timezone.utc).timestamp()

            return {
                "has_token": True,
                "is_valid": exp is None or now < exp,
                "subject": decoded.get("sub"),
                "expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat() if exp else None,
                "expires_in_seconds": int(exp - now) if exp else None,
                "is_expired": now >= exp if exp else False,
            }
        except Exception as e:
            return {"has_token": True, "is_valid": False, "message": str(e)}

    # =========================================================================
    # API Helpers
    # =========================================================================

    def _headers(self) -> Dict:
        """Build HTTP headers for API requests."""
        token = self.get_token()
        return {
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _api_get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make GET request to Query Service API."""
        url = f"{QUERY_SERVICE_URL}/{endpoint}"

        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)

            if resp.status_code == 401:
                raise Exception("Token expired or invalid. Please update INSIGHTS_PLATFORM_TOKEN in .env")

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("API request failed: %s", e)
            raise

    # =========================================================================
    # PDV Data Fetching (Query Service API)
    # =========================================================================

    def get_pdv_runs(
        self,
        release: str,
        day: str = None,
        release_type: str = None,
        application: str = None,
        latest_status: bool = True,
        limit: int = 1000,
    ) -> List[Dict]:
        """
        Fetch PDV runs from Query Service API.

        Args:
            release: Release version (e.g., "136.0")
            day: Day filter (e.g., "Day 1", "Day 2")
            release_type: Optional filter (not commonly used - API groups by Day instead)
            application: Filter by application (e.g., "DP", "MP")
            latest_status: If True, return only latest status per component
            limit: Max results per page

        Returns:
            List of PDV run records
        """
        params = {
            "release": release,
            "latestStatus": str(latest_status).lower(),
            "limit": limit,
        }

        if day:
            params["day"] = day
        if release_type:
            params["releaseType"] = release_type
        if application:
            params["application"] = application

        result = self._api_get("pdv_runs", params)
        return result.get("pdvRuns", [])

    def get_release_status(self, version: str, use_cache: bool = True) -> Dict:
        """
        Get PDV status for all days of a release.

        Args:
            version: Release version (e.g., "136.0")
            use_cache: Whether to use cached data (not implemented for Query Service)

        Returns:
            Dict with status for each day
        """
        result = {
            "version": version,
            "days": {},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Fetch PDV runs for all days (API uses Day field, not releaseType)
        try:
            pdv_runs = self.get_pdv_runs(release=version, latest_status=True)
        except Exception as e:
            logger.error("Failed to fetch PDV runs for %s: %s", version, e)
            return result

        # Group by day
        by_day = {}
        for run in pdv_runs:
            day = run.get("day", "Unknown")
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(run)

        # Process each day
        for day, runs in by_day.items():
            day_label = DAY_MAPPING.get(day, day.lower().replace(" ", " "))
            if not day_label.startswith("prod") and day_label != "staging":
                day_label = f"prod {day_label}" if "day" in day_label.lower() else day_label

            result["days"][day_label] = self._process_day_runs(runs, day_label)

        return result

    def _process_day_runs(self, runs: List[Dict], label: str) -> Dict:
        """Process PDV runs for a single day into status summary."""
        summary = {
            "success": 0,
            "failure": 0,
            "pending": 0,
            "running": 0,
            "total": 0,
        }

        failures = []
        components_by_app = {}

        for run in runs:
            component = run.get("component", "Unknown")
            application = run.get("application", "Unknown")
            datacenter = run.get("datacenter", "Unknown")
            status = (run.get("status") or "TODO").upper()

            # Filter to target applications only
            if TARGET_APPLICATIONS and application not in TARGET_APPLICATIONS:
                continue

            # Filter to target components only
            if TARGET_COMPONENT_NAMES and component not in TARGET_COMPONENT_NAMES:
                continue

            summary["total"] += 1

            if status in ("SUCCESS", "APPROVED"):
                summary["success"] += 1
            elif status == "FAILURE":
                summary["failure"] += 1
                failures.append(
                    {
                        "datacenter": datacenter,
                        "component": component,
                        "application": application,
                        "created_by": run.get("createdBy", ""),
                    }
                )
            elif status in ("RUNNING", "QUEUED"):
                summary["running"] += 1
            else:
                summary["pending"] += 1

            # Group components by application
            if application not in components_by_app:
                components_by_app[application] = {"name": component, "application": application, "datacenters": []}

            components_by_app[application]["datacenters"].append(
                {
                    "name": datacenter,
                    "status": status,
                    "deploy_status": "DEPLOYED" if status != "TODO" else "TODO",
                    "created_by": run.get("createdBy", ""),
                    "created_at": run.get("createdAt", ""),
                }
            )

        # Determine overall status
        if summary["total"] == 0:
            overall_status = "TODO"
        elif summary["failure"] > 0:
            overall_status = "FAILURE"
        elif summary["running"] > 0:
            overall_status = "IN_PROGRESS"
        elif summary["success"] == summary["total"]:
            overall_status = "SUCCESS"
        elif summary["pending"] > 0:
            overall_status = "PENDING"
        else:
            overall_status = "IN_PROGRESS"

        completion_percent = 0
        if summary["total"] > 0:
            completion_percent = round((summary["success"] / summary["total"]) * 100, 1)

        return {
            "label": label,
            "status": overall_status,
            "summary": summary,
            "completion_percent": completion_percent,
            "failures": failures,
            "components": list(components_by_app.values()),
        }

    def get_day_status(self, version: str, day: str) -> Dict:
        """
        Get PDV status for a specific deployment day.

        Args:
            version: Release version (e.g., "136.0")
            day: Day name (e.g., "Day 1", "Day 2")

        Returns:
            Dict with day status details
        """
        try:
            pdv_runs = self.get_pdv_runs(release=version, day=day, latest_status=True)
        except Exception as e:
            logger.error("Failed to fetch PDV runs for %s %s: %s", version, day, e)
            return {
                "label": day,
                "status": "ERROR",
                "error": str(e),
            }

        day_label = DAY_MAPPING.get(day, day.lower())
        return self._process_day_runs(pdv_runs, day_label)

    # =========================================================================
    # Status Change Detection
    # =========================================================================

    def _get_previous_status_file(self, version: str) -> str:
        """Get path to previous status snapshot for change detection."""
        return os.path.join(CACHE_DIR, f"prev_status_{version.replace('.', '_')}.json")

    def _load_previous_status(self, version: str) -> Optional[Dict]:
        """Load previous PDV status snapshot."""
        prev_file = self._get_previous_status_file(version)
        if not os.path.isfile(prev_file):
            return None
        try:
            with open(prev_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_previous_status(self, version: str, status: Dict):
        """Save current status as previous for next comparison."""
        prev_file = self._get_previous_status_file(version)
        try:
            with open(prev_file, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save previous status for %s: %s", version, e)

    def detect_status_changes(self, version: str) -> List[Dict]:
        """
        Detect PDV status changes for a release.

        Compares current status with previous snapshot to detect:
        - PDV started (TODO -> RUNNING)
        - PDV completed (RUNNING -> SUCCESS)
        - PDV failed (any -> FAILURE)

        Returns:
            List of change events with datacenter, old_status, new_status, message
        """
        try:
            current = self.get_release_status(version, use_cache=False)
        except Exception as e:
            logger.error("Failed to fetch current status for %s: %s", version, e)
            return []

        previous = self._load_previous_status(version)
        changes = []

        if not previous:
            self._save_previous_status(version, current)
            logger.info("First status check for %s - saved baseline", version)
            return []

        # Compare each day's overall status
        for day_label, day_data in current.get("days", {}).items():
            prev_day = previous.get("days", {}).get(day_label, {})

            old_status = prev_day.get("status", "TODO")
            new_status = day_data.get("status", "TODO")

            if old_status != new_status:
                summary = day_data.get("summary", {})
                changes.append(
                    {
                        "type": "day_status",
                        "day": day_label,
                        "old_status": old_status,
                        "new_status": new_status,
                        "message": self._build_change_message(day_label, new_status, summary),
                    }
                )

        self._save_previous_status(version, current)
        return changes

    def _build_change_message(self, day: str, status: str, summary: Dict) -> str:
        """Build human-readable message for status change."""
        day_title = day.replace("prod ", "Prod ").replace("preprod ", "PreProd ").title()
        success = summary.get("success", 0)
        failure = summary.get("failure", 0)
        total = summary.get("total", 0)

        if status == "SUCCESS":
            return f"{day_title} - PDV complete ({success}/{total} passed)"
        elif status == "FAILURE":
            return f"{day_title} - PDV {failure} test(s) failed"
        elif status == "IN_PROGRESS":
            pct = round((success / total * 100) if total > 0 else 0, 0)
            return f"{day_title} - PDV in progress ({pct:.0f}%)"
        elif status == "PENDING":
            return f"{day_title} - Deployments complete, PDV pending"
        else:
            return f"{day_title} - Status: {status}"


# Singleton instance
_pdv_client: Optional[PDVClient] = None


def get_pdv_client(token: str = None) -> PDVClient:
    """Get or create PDV client instance."""
    global _pdv_client

    if token:
        return PDVClient(token)

    if _pdv_client is None:
        _pdv_client = PDVClient()

    return _pdv_client

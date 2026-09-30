"""
Environment Configuration Loader

Loads environment configurations from JSON files in the your-product-qe GitHub repository.

Source: your-company-qe/your-product-qe
  - your-product-qe/environment/*.json (NPE/staging stacks)
  - your-product-qe/environment/pe/*.json (Production stacks)

Requirements:
  - GITHUB_TOKEN: Required for private repository access

Caching Strategy (Hybrid):
  1. File-based cache: Persists across backend restarts
  2. ETag validation: GitHub returns 304 Not Modified without counting against rate limit
  3. Graceful fallback: Uses file cache if GitHub API fails (rate limit, network issues)

JSON File Structure:
    {
        "env": "stg01-mp.nc4.iad0.nsscloud.net",
        "alias_env": "stg.boomskope.com",
        "kube_config": "stork-stg01-mp-iad0-nc4.yaml",
        "production": false,
        "vault": true,
        "services": {...},
        "tenants": {...}
    }

Usage:
    from services.environment_config import get_environment_config, get_all_environments

    # Get specific environment
    config = get_environment_config("stg01-mp-npe")

    # Get all environments
    envs = get_all_environments()
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# GitHub repository configuration
GITHUB_REPO_OWNER = "your-company-qe"
GITHUB_REPO_NAME = "your-product-qe"
GITHUB_REPO_BRANCH = "main"
GITHUB_ENV_PATH = "your-product-qe/environment"

# GitHub API URLs
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

# Cache configuration
CACHE_TTL_HOURS = 24  # How long before validating with GitHub (using ETag)
CACHE_MAX_AGE_HOURS = 168  # Max age before forcing refresh (7 days)

# File-based cache paths
_CACHE_DIR = Path(__file__).parent.parent / "data" / "env_config_cache"
_ENV_CACHE_FILE = _CACHE_DIR / "environments.json"
_GLOBAL_CACHE_FILE = _CACHE_DIR / "global_config.json"
_ETAG_FILE = _CACHE_DIR / "etags.json"

# In-memory cache for loaded configurations
_env_config_cache: Dict[str, Dict[str, Any]] = {}
_global_config_cache: Optional[Dict[str, Any]] = None
_cache_loaded: bool = False
_cache_timestamp: Optional[datetime] = None
_etags: Dict[str, str] = {}  # path -> etag mapping


def _get_github_token() -> str:
    """Get GitHub token from environment for API access."""
    return os.environ.get("GITHUB_TOKEN", "")


def _ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_file_cache() -> bool:
    """
    Load configurations from file cache.

    Returns:
        True if cache was loaded successfully
    """
    global _env_config_cache, _global_config_cache, _cache_timestamp, _etags

    try:
        if not _ENV_CACHE_FILE.exists():
            return False

        # Load environment configs
        with open(_ENV_CACHE_FILE, "r") as f:
            cache_data = json.load(f)

        _env_config_cache = cache_data.get("environments", {})
        _cache_timestamp = datetime.fromisoformat(cache_data.get("timestamp", ""))

        # Load global config if exists
        if _GLOBAL_CACHE_FILE.exists():
            with open(_GLOBAL_CACHE_FILE, "r") as f:
                _global_config_cache = json.load(f)

        # Load ETags if exists
        if _ETAG_FILE.exists():
            with open(_ETAG_FILE, "r") as f:
                _etags = json.load(f)

        logger.info(
            "Loaded %d environments from file cache (age: %s)",
            len(_env_config_cache),
            datetime.now() - _cache_timestamp if _cache_timestamp else "unknown",
        )
        return len(_env_config_cache) > 0

    except Exception as e:
        logger.warning("Failed to load file cache: %s", e)
        return False


def _save_file_cache() -> None:
    """Save current configurations to file cache."""
    global _cache_timestamp

    try:
        _ensure_cache_dir()

        # Save environment configs with timestamp
        _cache_timestamp = datetime.now()
        cache_data = {
            "environments": _env_config_cache,
            "timestamp": _cache_timestamp.isoformat(),
        }
        with open(_ENV_CACHE_FILE, "w") as f:
            json.dump(cache_data, f, indent=2)

        # Save global config
        if _global_config_cache:
            with open(_GLOBAL_CACHE_FILE, "w") as f:
                json.dump(_global_config_cache, f, indent=2)

        # Save ETags
        if _etags:
            with open(_ETAG_FILE, "w") as f:
                json.dump(_etags, f, indent=2)

        logger.info("Saved %d environments to file cache", len(_env_config_cache))

    except Exception as e:
        logger.error("Failed to save file cache: %s", e)


def _fetch_from_github_api(path: str, use_etag: bool = True) -> Optional[Dict[str, Any]]:
    """
    Fetch directory listing or file content from GitHub API.

    Uses ETag for conditional requests - if content hasn't changed,
    GitHub returns 304 Not Modified without counting against rate limit.

    Args:
        path: Path within the repository (e.g., "your-product-qe/environment")
        use_etag: Whether to use ETag for conditional request

    Returns:
        API response as dict, None on failure, or "not_modified" string if unchanged
    """
    global _etags

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{path}"
    params = {"ref": GITHUB_REPO_BRANCH}

    headers = {"Accept": "application/vnd.github.v3+json"}
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"

    # Add ETag for conditional request (doesn't count against rate limit if unchanged)
    if use_etag and path in _etags:
        headers["If-None-Match"] = _etags[path]

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers, params=params)

            # 304 Not Modified - content unchanged, use cached version
            if response.status_code == 304:
                logger.debug("GitHub content unchanged (304) for: %s", path)
                return "not_modified"

            if response.status_code == 404:
                logger.warning("GitHub path not found: %s", path)
                return None

            if response.status_code == 403:
                # Check if it's rate limiting
                remaining = response.headers.get("x-ratelimit-remaining", "?")
                logger.warning("GitHub API rate limit or access denied for: %s (remaining: %s)", path, remaining)
                return None

            response.raise_for_status()

            # Store ETag for future conditional requests
            etag = response.headers.get("etag")
            if etag:
                _etags[path] = etag

            return response.json()

    except Exception as e:
        logger.error("Failed to fetch from GitHub API: %s", e)
        return None


def _fetch_raw_json_from_github(path: str, use_etag: bool = True) -> Optional[Dict[str, Any]]:
    """
    Fetch raw JSON file content from GitHub API.

    Uses the GitHub API to fetch file contents (with authentication),
    which works for private repositories. Supports ETag for conditional requests.

    Args:
        path: Path within the repository (e.g., "your-product-qe/environment/stg01-mp-npe.json")
        use_etag: Whether to use ETag for conditional request

    Returns:
        Parsed JSON content as dict, None on failure, or "not_modified" if unchanged
    """
    import base64

    global _etags

    # Use GitHub API to fetch file content (works with private repos)
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{path}"
    params = {"ref": GITHUB_REPO_BRANCH}

    headers = {"Accept": "application/vnd.github.v3+json"}
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"

    # Add ETag for conditional request
    if use_etag and path in _etags:
        headers["If-None-Match"] = _etags[path]

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers, params=params)

            # 304 Not Modified - content unchanged
            if response.status_code == 304:
                return "not_modified"

            if response.status_code == 404:
                logger.debug("GitHub file not found: %s", path)
                return None

            if response.status_code == 403:
                # Rate limited - return None to trigger fallback to cache
                return None

            response.raise_for_status()

            # Store ETag for future requests
            etag = response.headers.get("etag")
            if etag:
                _etags[path] = etag

            api_response = response.json()

            # GitHub API returns file content as base64 encoded
            content_base64 = api_response.get("content", "")
            if not content_base64:
                logger.warning("No content in GitHub API response for: %s", path)
                return None

            # Decode base64 content (remove newlines first)
            content_bytes = base64.b64decode(content_base64.replace("\n", ""))
            content_str = content_bytes.decode("utf-8")

            return json.loads(content_str)

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in GitHub file %s: %s", path, e)
        return None
    except Exception as e:
        logger.error("Failed to fetch raw file from GitHub: %s", e)
        return None


def _list_github_directory(path: str):
    """
    List files in a GitHub directory.

    Args:
        path: Directory path within the repository

    Returns:
        List of file info dicts with 'name', 'path', 'type' keys,
        "not_modified" if unchanged (ETag match), or empty list on failure
    """
    result = _fetch_from_github_api(path)

    if result == "not_modified":
        return "not_modified"

    if result is None:
        return []

    if isinstance(result, list):
        return result

    return []


class EnvironmentConfig:
    """Represents a single environment configuration."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self._config = config

    @property
    def env_hostname(self) -> str:
        """Primary environment hostname."""
        return self._config.get("env", "")

    @property
    def alias_hostname(self) -> str:
        """Alias hostname (e.g., boomskope.com)."""
        return self._config.get("alias_env", "")

    @property
    def stork_env(self) -> str:
        """Stork environment hostname."""
        return self._config.get("stork_env", self.env_hostname)

    @property
    def kubeconfig_filename(self) -> str:
        """Kubeconfig filename (without path)."""
        return self._config.get("kube_config", "")

    @property
    def is_production(self) -> bool:
        """Whether this is a production environment."""
        return self._config.get("production", False)

    @property
    def environment_category(self) -> str:
        """
        Get the environment category for filtering.

        Categories:
        - 'npe': Non-Production Automation (qa01, npa01)
        - 'staging': Staging environments (stg01, fed1mp, stg01-mplegacy)
        - 'preprod': Pre-production (devint, fed-preprod)
        - 'prod': Production (all PE stacks)

        Returns:
            Environment category string
        """
        name_lower = self.name.lower()
        stack_lower = self.stack_name.lower()

        # Check if it's production (from JSON config)
        if self.is_production:
            return "prod"

        # NPE environments
        npe_patterns = ["qa01", "npe01", "qa-", "npe-"]
        if any(p in name_lower or p in stack_lower for p in npe_patterns):
            return "npe"

        # Staging environments
        staging_patterns = ["stg01", "stg-", "staging", "fed1mp", "fed1-mp", "mplegacy", "betaskope"]
        if any(p in name_lower or p in stack_lower for p in staging_patterns):
            return "staging"

        # Pre-prod environments
        preprod_patterns = ["devint", "preprod", "pre-prod", "fed-preprod", "fed02-mp-preprod", "fed02"]
        if any(p in name_lower or p in stack_lower for p in preprod_patterns):
            return "preprod"

        # PE environments (production)
        if name_lower.startswith("pe-"):
            return "prod"

        # Default to staging for non-production environments
        return "staging"

    @property
    def uses_vault(self) -> bool:
        """Whether this environment uses Vault for secrets."""
        return self._config.get("vault", True)

    @property
    def stork_run(self) -> bool:
        """Whether Stork should be run for this environment."""
        return self._config.get("stork_run", False)

    @property
    def port_forward(self) -> bool:
        """Whether port forwarding is needed."""
        return self._config.get("port_forward", False)

    @property
    def services(self) -> Dict[str, Any]:
        """Service configurations."""
        return self._config.get("services", {})

    @property
    def tenants(self) -> Dict[str, Any]:
        """Tenant configuration."""
        return self._config.get("tenants", {})

    @property
    def stack_name(self) -> str:
        """Extract stack name from tenants config or derive from name."""
        tenants = self.tenants
        if tenants and "stack" in tenants:
            return tenants["stack"]
        # Derive from environment name (e.g., "stg01-mp-npe" -> "stg01")
        return self.name.split("-")[0] if "-" in self.name else self.name

    @property
    def namespace_suffix(self) -> str:
        """
        Derive namespace suffix from environment name.
        e.g., "stg01-mp-npe" -> "-mp-npe", "stg01-mplegacy" -> "-mplegacy"
        """
        parts = self.name.split("-", 1)
        if len(parts) > 1:
            return f"-{parts[1]}"
        return "-mp"

    @property
    def region(self) -> str:
        """Extract region from environment hostname."""
        # e.g., "stg01-mp.nc4.iad0.nsscloud.net" -> "US-IAD0"
        env = self.env_hostname
        stork = self.stork_env.lower() if self.stork_env else ""
        if "iad0" in env.lower():
            return "US-IAD0"
        elif "npe" in env.lower():
            return "US-NPE"
        elif "sjc" in env.lower():
            return "US-SJC"
        elif "dfw" in env.lower() or "dfw" in stork:
            return "US-DFW"
        elif "fra" in env.lower() or "fra2" in stork:
            return "EU-FRA"
        elif "lon" in env.lower() or "lon3" in stork:
            return "EU-LON"
        elif "sin" in env.lower() or "sin2" in stork:
            return "AP-SIN"
        elif "mel" in env.lower() or "mel2" in stork:
            return "AP-MEL"
        elif "zur" in env.lower() or "zur2" in stork:
            return "EU-ZUR"
        elif "ruh" in env.lower() or "ruh1" in stork:
            return "ME-RUH"
        elif "bom" in env.lower() or "bom3" in stork:
            return "IN-BOM"
        return "Unknown"

    def get_service_namespace(self, service_name: str) -> Optional[str]:
        """Get the namespace for a specific service."""
        service = self.services.get(service_name, {})
        return service.get("namespace")

    def get_service_hosts(self, service_name: str) -> List[Dict[str, Any]]:
        """Get the hosts configuration for a specific service."""
        service = self.services.get(service_name, {})
        return service.get("hosts", [])

    def get_kubernetes_services(self) -> Dict[str, str]:
        """
        Get all services that have Kubernetes namespaces configured.

        Returns:
            Dict mapping service_name -> namespace
            Only includes services with valid namespace (not None/empty)
        """
        k8s_services = {}
        for svc_name, svc_config in self.services.items():
            namespace = svc_config.get("namespace")
            if namespace and namespace != "N/A":
                k8s_services[svc_name] = namespace
        return k8s_services

    def to_stack_config(self) -> Dict[str, str]:
        """
        Convert to stack configuration format compatible with config.py.

        Returns:
            Dict with keys: context, region, namespace_suffix, description,
            environment_category, etc.
        """
        # Derive context from kubeconfig filename
        # e.g., "stork-stg01-mp-iad0-nc4.yaml" -> "stork-stg01-mp-iad0-nc4"
        context = self.kubeconfig_filename.replace(".yaml", "").replace(".yml", "")

        # Get category-specific description
        category = self.environment_category
        category_labels = {"npe": "NPE", "staging": "Staging", "preprod": "Pre-Prod", "prod": "Production"}
        category_label = category_labels.get(category, "Non-Production")

        return {
            "context": context,
            "region": self.region,
            "namespace_suffix": self.namespace_suffix,
            "description": f"{self.stack_name.upper()} Stack ({category_label})",
            "is_production": self.is_production,
            "environment_category": category,
            "env_hostname": self.env_hostname,
            "alias_hostname": self.alias_hostname,
        }

    def __repr__(self) -> str:
        return f"EnvironmentConfig(name={self.name}, env={self.env_hostname}, production={self.is_production})"


def _is_cache_fresh() -> bool:
    """Check if cache is fresh enough to skip GitHub validation."""
    global _cache_timestamp

    if _cache_timestamp is None:
        return False

    ttl = timedelta(hours=CACHE_TTL_HOURS)
    return datetime.now() - _cache_timestamp < ttl


def _is_cache_expired() -> bool:
    """Check if cache is too old and must be refreshed (even if GitHub fails)."""
    global _cache_timestamp

    if _cache_timestamp is None:
        return True

    max_age = timedelta(hours=CACHE_MAX_AGE_HOURS)
    return datetime.now() - _cache_timestamp > max_age


def _load_configs_from_github(validate_only: bool = False) -> bool:
    """
    Load configurations from GitHub repository.

    Fetches JSON files from:
    - your-company-qe/your-product-qe/your-product-qe/environment/*.json
    - your-company-qe/your-product-qe/your-product-qe/environment/pe/*.json

    Uses ETag for conditional requests - unchanged content doesn't count against rate limit.

    Args:
        validate_only: If True, only check if content changed (using ETags)

    Returns:
        True if configs were loaded/validated successfully
    """
    global _env_config_cache, _global_config_cache

    logger.info("Fetching environment configs from GitHub repository...")

    # List files in the environment directory
    files = _list_github_directory(GITHUB_ENV_PATH)

    # If we got "not_modified", directory listing unchanged - use existing cache
    if files == "not_modified":
        logger.info("GitHub directory unchanged (ETag match) - using cached configs")
        return True

    if not files:
        logger.warning("No files found in GitHub environment directory")
        return False

    loaded_count = 0
    unchanged_count = 0

    for file_info in files:
        file_name = file_info.get("name", "")
        file_type = file_info.get("type", "")
        file_path = file_info.get("path", "")

        # Handle subdirectories (like 'pe')
        if file_type == "dir":
            if file_name == "pe":
                # Load PE configs
                pe_files = _list_github_directory(file_path)
                if pe_files == "not_modified":
                    unchanged_count += 1
                    continue
                if not pe_files:
                    continue

                for pe_file in pe_files:
                    pe_name = pe_file.get("name", "")
                    pe_path = pe_file.get("path", "")

                    if pe_name.endswith(".json"):
                        config = _fetch_raw_json_from_github(pe_path)
                        if config == "not_modified":
                            unchanged_count += 1
                        elif config:
                            env_name = f"pe-{pe_name[:-5]}"  # Remove .json extension
                            _env_config_cache[env_name] = config
                            loaded_count += 1
                            logger.debug("Loaded PE config from GitHub: %s", env_name)
            continue

        # Load JSON files from main directory
        if file_name.endswith(".json"):
            config = _fetch_raw_json_from_github(file_path)
            if config == "not_modified":
                unchanged_count += 1
            elif config:
                env_name = file_name[:-5]  # Remove .json extension

                if env_name == "global-config":
                    _global_config_cache = config
                    logger.info("Loaded global config from GitHub")
                else:
                    _env_config_cache[env_name] = config
                    loaded_count += 1
                    logger.debug("Loaded environment config from GitHub: %s", env_name)

    if loaded_count > 0 or unchanged_count > 0:
        logger.info("GitHub sync: %d loaded, %d unchanged (ETag match)", loaded_count, unchanged_count)
        return True

    return False


def _load_all_configs(force_reload: bool = False) -> None:
    """
    Load all environment configurations with hybrid caching strategy.

    Strategy:
    1. On startup: Load from file cache first (instant, survives restarts)
    2. If cache is fresh (< 24h): Skip GitHub validation
    3. If cache needs validation: Use ETag (304 Not Modified = free API call)
    4. If GitHub fails: Fall back to file cache (even if stale)
    5. Save to file cache after successful GitHub fetch

    Source: your-company-qe/your-product-qe repository (single source of truth)
    Requires: GITHUB_TOKEN for private repo access
    """
    global _env_config_cache, _global_config_cache, _cache_loaded, _cache_timestamp

    # If already loaded and cache is fresh, skip
    if _cache_loaded and not force_reload and _is_cache_fresh():
        return

    # Step 1: Try loading from file cache first (instant startup)
    if not _cache_loaded and not force_reload:
        if _load_file_cache():
            _cache_loaded = True
            # If file cache is fresh, we're done
            if _is_cache_fresh():
                logger.info("Using fresh file cache (age < %dh)", CACHE_TTL_HOURS)
                return
            # If file cache exists but needs validation, continue to GitHub check
            logger.info("File cache loaded but needs GitHub validation")

    # Step 2: Try to refresh/validate from GitHub
    github_success = False
    try:
        github_success = _load_configs_from_github()
    except Exception as e:
        logger.error("GitHub fetch failed: %s", e)

    if github_success:
        _cache_loaded = True
        _cache_timestamp = datetime.now()
        # Save to file cache for next restart
        _save_file_cache()
        return

    # Step 3: GitHub failed - check if we have any cached data to fall back to
    if len(_env_config_cache) > 0:
        if _is_cache_expired():
            logger.warning(
                "GitHub unavailable and cache is expired (> %dh old). Using stale cache.", CACHE_MAX_AGE_HOURS
            )
        else:
            logger.warning("GitHub unavailable. Using cached configs.")
        _cache_loaded = True
        return

    # Step 4: No cache and GitHub failed - try file cache one more time
    if _load_file_cache():
        _cache_loaded = True
        logger.warning("GitHub unavailable. Loaded from file cache as fallback.")
        return

    # No data available
    logger.error("Failed to load environment configs. No cache available and GitHub unreachable.")
    _cache_loaded = True  # Mark as loaded to avoid repeated attempts
    _cache_timestamp = datetime.now()


def get_global_config() -> Dict[str, Any]:
    """
    Get the global configuration (rancher_secret, external_resources, etc.).

    Returns:
        Dict with global configuration or empty dict if not found
    """
    _load_all_configs()
    return _global_config_cache or {}


def get_rancher_secret_path() -> str:
    """Get the Vault path for Rancher secret from global config."""
    config = get_global_config()
    return config.get("rancher_secret", "")


def get_environment_config(env_name: str) -> Optional[EnvironmentConfig]:
    """
    Get configuration for a specific environment.

    Args:
        env_name: Environment name (e.g., "stg01-mp-npe", "qa01-mp-npe", "pe-sjc1")

    Returns:
        EnvironmentConfig object or None if not found
    """
    _load_all_configs()

    config = _env_config_cache.get(env_name)
    if config:
        return EnvironmentConfig(env_name, config)

    # Try without "pe-" prefix for production environments
    if not env_name.startswith("pe-"):
        config = _env_config_cache.get(f"pe-{env_name}")
        if config:
            return EnvironmentConfig(f"pe-{env_name}", config)

    return None


def get_all_environments() -> List[EnvironmentConfig]:
    """
    Get all available environment configurations.

    Returns:
        List of EnvironmentConfig objects
    """
    _load_all_configs()
    return [EnvironmentConfig(name, config) for name, config in _env_config_cache.items()]


def get_non_production_environments() -> List[EnvironmentConfig]:
    """Get all non-production (NPE/staging) environments."""
    return [env for env in get_all_environments() if not env.is_production]


def get_production_environments() -> List[EnvironmentConfig]:
    """Get all production environments."""
    return [env for env in get_all_environments() if env.is_production]


def get_stack_configs_from_json() -> Dict[str, Dict[str, str]]:
    """
    Convert all environment configs to stack configuration format.

    This can be used to dynamically build KUBERNETES_STACKS in config.py
    without hardcoding stack definitions.

    Returns:
        Dict mapping stack_id to stack configuration
    """
    stacks = {}

    for env_config in get_all_environments():
        stack_id = env_config.stack_name

        # Handle PE stacks with their PE name prefix
        if env_config.name.startswith("pe-"):
            stack_id = env_config.name.replace("pe-", "")

        # Use the full env name if there's a conflict (e.g., stg01 vs stg01-mplegacy)
        if stack_id in stacks:
            stack_id = env_config.name.replace("-", "_")

        stacks[stack_id] = env_config.to_stack_config()

    return stacks


def reload_configs() -> int:
    """
    Force reload all configurations from GitHub.

    Clears both in-memory and file caches, then fetches fresh from GitHub.

    Returns:
        Number of configurations loaded
    """
    global _env_config_cache, _global_config_cache, _cache_loaded, _cache_timestamp, _etags
    _env_config_cache = {}
    _global_config_cache = None
    _cache_loaded = False
    _cache_timestamp = None
    _etags = {}  # Clear ETags to force full fetch

    _load_all_configs(force_reload=True)
    return len(_env_config_cache)


def get_config_source() -> str:
    """
    Get the source of the current configuration.

    Returns:
        "github", "file_cache", or "none"
    """
    if _cache_loaded and len(_env_config_cache) > 0:
        # Check if we have a recent GitHub fetch or using file cache
        if _cache_timestamp and (datetime.now() - _cache_timestamp).total_seconds() < 60:
            return "github"
        return "file_cache"
    return "none"


def get_cache_status() -> Dict[str, Any]:
    """
    Get detailed cache status for debugging.

    Returns:
        Dict with cache status information
    """
    age_seconds = None
    if _cache_timestamp:
        age_seconds = (datetime.now() - _cache_timestamp).total_seconds()

    return {
        "loaded": _cache_loaded,
        "environment_count": len(_env_config_cache),
        "has_global_config": _global_config_cache is not None,
        "cache_timestamp": _cache_timestamp.isoformat() if _cache_timestamp else None,
        "cache_age_seconds": age_seconds,
        "cache_age_hours": round(age_seconds / 3600, 1) if age_seconds else None,
        "is_fresh": _is_cache_fresh(),
        "is_expired": _is_cache_expired(),
        "file_cache_exists": _ENV_CACHE_FILE.exists(),
        "etag_count": len(_etags),
        "source": get_config_source(),
    }


def get_kubeconfig_filename_for_stack(stack_name: str) -> Optional[str]:
    """
    Get the kubeconfig filename for a given stack.

    Args:
        stack_name: Stack name (e.g., "stg01", "qa01", "sjc1")

    Returns:
        Kubeconfig filename or None if not found
    """
    # Try direct match first
    for env_config in get_all_environments():
        if env_config.stack_name == stack_name:
            return env_config.kubeconfig_filename

    # Try matching by environment name
    env_config = get_environment_config(stack_name)
    if env_config:
        return env_config.kubeconfig_filename

    return None


def get_services_for_stack(stack_name: str) -> Dict[str, str]:
    """
    Get Kubernetes services and their namespaces for a given stack.

    Args:
        stack_name: Stack name (e.g., "stg01", "qa01", "sjc1")

    Returns:
        Dict mapping service_name -> namespace
        Empty dict if stack not found or no services configured
    """
    # Try direct match by stack_name
    for env_config in get_all_environments():
        if env_config.stack_name == stack_name:
            return env_config.get_kubernetes_services()

    # Try matching by environment name (for pe-sjc1 -> sjc1)
    for env_config in get_all_environments():
        if env_config.name == f"pe-{stack_name}" or env_config.name == stack_name:
            return env_config.get_kubernetes_services()

    return {}


# Export for convenience
__all__ = [
    "EnvironmentConfig",
    "get_environment_config",
    "get_all_environments",
    "get_non_production_environments",
    "get_production_environments",
    "get_global_config",
    "get_rancher_secret_path",
    "get_services_for_stack",
    "get_stack_configs_from_json",
    "get_kubeconfig_filename_for_stack",
    "reload_configs",
    "get_config_source",
    "get_cache_status",
]

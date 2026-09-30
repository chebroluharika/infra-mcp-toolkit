"""
Rancher API Client

Downloads kubeconfig files from Rancher using the generateKubeconfig API action.
This eliminates the manual step of downloading kubeconfig files from Rancher UI.

Based on: your-product-qe/tools/cluster_downloader.py

Rancher Servers:
    - Production: rancher.example.com (PE stacks: sjc1, fra2, etc.)
    - NPE/Staging: your-rancher.example.com (qa01, stg01, etc.)

API Tokens:
    Option 1: Environment variables
        - RANCHER_NPE_KEY: Token for NPE/Staging clusters
        - RANCHER_PROD_KEY: Token for Production clusters

    Option 2: Vault (if pylclient is available)
        - Path: /your-product-tw/stack/rancher_secret
        - Keys: rancher_npe_key, rancher_prod_key

Usage:
    from services.rancher_client import download_all_kubeconfigs

    # Download all kubeconfigs
    download_all_kubeconfigs()
"""

import logging
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import urllib3
import yaml

# Suppress SSL warnings when verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

logger = logging.getLogger(__name__)

# Default directory for saving kubeconfig files
DEFAULT_KUBECONFIG_DIR = os.path.expanduser("~/.kube/rancher")

# Rancher server configurations (from your-product-qe/tools/cluster_downloader.py)
RANCHER_SERVERS = {
    "npe": {
        "url": "your-rancher.example.com",
        "token_env": "RANCHER_NPE_KEY",
        "token_vault_key": "rancher_npe_key",
        "clusters": {
            "stork-npa01-mp-npe-iad0-nc1": "c-t624f",
            "stork-stg01-mp-iad0-nc4": "c-mvvwx",
            "stork-qa01-mp-npe-iad0-nc1": "c-nwgg2",
            "stork-stg01-mplegacy-iad0-nc4": "c-x7qdv",
            "stork-devint-automation-iad0-nc1": "c-2kslm",
            "c1-betaskope-sje011": "c-jggfx",
            "stork-fed1mp-iad0-nc1": "c-czc66",
            "stork-perf01-mp-iad0-nc6": "c-rsnsj",
            "stork-npe02-mp-iad0-nc4": "c-wfc98",
        },
    },
    "prod": {
        "url": "rancher.example.com",
        "token_env": "RANCHER_PROD_KEY",
        "token_vault_key": "rancher_prod_key",
        "clusters": {
            "stork-ruh1-mp-prod-ruh1-nc1": "c-2pdc5",
            "stork-dfw3-mp-prod-dfw3-nc1": "c-55v8b",
            "stork-fra2-mp-prod-fra2-nc1": "c-dwkwn",
            "stork-lon3-mp-prod-lon3-nc1": "c-llwvb",
            "stork-zur2-mp-prod-zur2-nc1": "c-h7l64",
            "stork-sin2-mp-prod-sin2-nc1": "c-tsd5r",
            "stork-mel2-mp-mel2-nc1": "c-lm4zl",
            "stork-sjc2-mp-prod-sjc2-nc1": "c-5hbzg",
            "c1-sv5": "c-kwjsw",
            "c4-am2": "c-pgth7",
            "c4-sjc1": "c-9wc4v",
            "c4-fr4": "c-2lxm6",
            "stork-bom3-mp-prod-bom3-nc1": "c-x6j4h",
        },
    },
}


class RancherClientError(Exception):
    """Base exception for Rancher client errors."""

    pass


class RancherAuthError(RancherClientError):
    """Authentication error with Rancher API."""

    pass


class RancherNotFoundError(RancherClientError):
    """Resource not found in Rancher."""

    pass


def _get_token_from_vault(vault_key: str) -> Optional[str]:
    """
    Try to get Rancher token from Vault using pylclient.

    Args:
        vault_key: Key name in the rancher_secret (e.g., 'rancher_npe_key')

    Returns:
        Token string or None if Vault is not available
    """
    try:
        from pylclient.secrets.secret import Secret

        secret_path = "/your-product-tw/stack/rancher_secret"
        secrets = Secret(secret_path).get_all().as_dict()
        return secrets.get(vault_key)
    except ImportError:
        logger.debug("pylclient not available, skipping Vault lookup")
        return None
    except Exception as e:
        logger.warning("Failed to get token from Vault: %s", e)
        return None


def _get_rancher_token(server_type: str) -> Optional[str]:
    """
    Get Rancher API token for a server type (npe or prod).

    Priority:
    1. Environment variable (RANCHER_NPE_KEY or RANCHER_PROD_KEY)
    2. Vault secret (/your-product-tw/stack/rancher_secret)

    Args:
        server_type: "npe" or "prod"

    Returns:
        API token or None if not found
    """
    server_config = RANCHER_SERVERS.get(server_type, {})

    # Try environment variable first
    env_key = server_config.get("token_env", "")
    token = os.environ.get(env_key)
    if token:
        logger.debug("Using Rancher token from env: %s", env_key)
        return token

    # Try Vault
    vault_key = server_config.get("token_vault_key", "")
    token = _get_token_from_vault(vault_key)
    if token:
        logger.debug("Using Rancher token from Vault: %s", vault_key)
        return token

    return None


def _generate_kubeconfig(rancher_url: str, cluster_id: str, token: str, retries: int = 3) -> str:
    """
    Generate kubeconfig for a cluster using Rancher API.

    Args:
        rancher_url: Rancher server URL (without https://)
        cluster_id: Rancher cluster ID (e.g., "c-mvvwx")
        token: Rancher API token
        retries: Number of retry attempts for transient SSL errors

    Returns:
        Kubeconfig content as string

    Raises:
        RancherClientError: If all retries fail
    """
    import ssl
    import time

    url = f"https://{rancher_url}/v3/clusters/{cluster_id}?action=generateKubeconfig"
    headers = {"Authorization": f"Bearer {token}"}

    last_error = None
    for attempt in range(retries):
        try:
            # Create custom SSL context that's more lenient
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            # Set lower TLS version for compatibility with older servers
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

            with httpx.Client(
                verify=ssl_context,
                timeout=httpx.Timeout(60.0, connect=30.0),
                http2=False,  # Disable HTTP/2 to avoid some SSL issues
            ) as client:
                response = client.post(url, headers=headers)
                response.raise_for_status()
                return response.json().get("config", "")
        except ssl.SSLError as e:
            last_error = e
            logger.warning("SSL error downloading kubeconfig (attempt %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)  # Exponential backoff: 1s, 2s, 4s
        except httpx.ConnectError as e:
            last_error = e
            logger.warning("Connection error downloading kubeconfig (attempt %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
        except httpx.ReadError as e:
            last_error = e
            logger.warning("Read error downloading kubeconfig (attempt %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)

    raise RancherClientError(f"Failed to download kubeconfig after {retries} attempts: {last_error}")


def _save_kubeconfig(content: str, output_dir: Path) -> Path:
    """
    Save kubeconfig content to a file.

    Args:
        content: Kubeconfig YAML content
        output_dir: Directory to save the file

    Returns:
        Path to saved file
    """
    data = yaml.safe_load(content)
    filename = data.get("current-context", "unknown") + ".yaml"
    filepath = output_dir / filename

    filepath.write_text(content)
    logger.info("Saved kubeconfig: %s", filepath)
    return filepath


def download_cluster_kubeconfig(
    cluster_name: str,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Download kubeconfig for a specific cluster.

    Args:
        cluster_name: Cluster name (e.g., "stork-stg01-mp-iad0-nc4")
        output_dir: Directory to save the file (default: ~/.kube/rancher)

    Returns:
        Path to saved file, or None if failed
    """
    output_dir = output_dir or Path(DEFAULT_KUBECONFIG_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find which server has this cluster
    for server_type, config in RANCHER_SERVERS.items():
        if cluster_name in config["clusters"]:
            cluster_id = config["clusters"][cluster_name]
            token = _get_rancher_token(server_type)

            if not token:
                logger.error(
                    "No Rancher token for %s. Set %s env var or configure Vault.",
                    server_type,
                    config["token_env"],
                )
                return None

            try:
                logger.info("Downloading kubeconfig for %s from %s...", cluster_name, config["url"])
                content = _generate_kubeconfig(config["url"], cluster_id, token)
                return _save_kubeconfig(content, output_dir)
            except Exception as e:
                logger.error("Failed to download kubeconfig for %s: %s", cluster_name, e)
                return None

    logger.error("Cluster not found in any Rancher server: %s", cluster_name)
    return None


def download_all_kubeconfigs(
    output_dir: Optional[Path] = None,
    server_type: Optional[str] = None,
) -> Dict[str, Optional[Path]]:
    """
    Download kubeconfigs for all clusters.

    Args:
        output_dir: Directory to save files (default: ~/.kube/rancher)
        server_type: "npe", "prod", or None for both

    Returns:
        Dict mapping cluster name to saved file path (or None if failed)
    """
    output_dir = output_dir or Path(DEFAULT_KUBECONFIG_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    servers_to_process = [server_type] if server_type else ["npe", "prod"]

    for srv_type in servers_to_process:
        config = RANCHER_SERVERS.get(srv_type)
        if not config:
            continue

        token = _get_rancher_token(srv_type)
        if not token:
            logger.warning(
                "No token for %s server. Set %s or configure Vault.",
                srv_type,
                config["token_env"],
            )
            for cluster_name in config["clusters"]:
                results[cluster_name] = None
            continue

        for cluster_name, cluster_id in config["clusters"].items():
            try:
                logger.info("Downloading: %s", cluster_name)
                content = _generate_kubeconfig(config["url"], cluster_id, token)
                results[cluster_name] = _save_kubeconfig(content, output_dir)
            except httpx.TimeoutException:
                logger.warning("Timeout downloading %s", cluster_name)
                results[cluster_name] = None
            except RancherClientError as e:
                logger.error("Failed to download %s: %s", cluster_name, e)
                results[cluster_name] = None
            except Exception as e:
                error_str = str(e).lower()
                if "ssl" in error_str or "eof" in error_str or "unexpected" in error_str:
                    logger.error(
                        "SSL/Connection error downloading %s: %s. "
                        "This may indicate network issues, VPN problems, or the Rancher server is unavailable.",
                        cluster_name,
                        e,
                    )
                else:
                    logger.error("Failed to download %s: %s", cluster_name, e)
                results[cluster_name] = None

    return results


def get_available_clusters() -> Dict[str, List[str]]:
    """
    Get list of all available clusters by server type.

    Returns:
        Dict with "npe" and "prod" keys containing cluster name lists
    """
    return {server_type: list(config["clusters"].keys()) for server_type, config in RANCHER_SERVERS.items()}


def get_rancher_status() -> Dict[str, Any]:
    """
    Get status of Rancher configuration and connectivity.

    Returns:
        Dict with status information
    """
    status = {
        "kubeconfig_dir": DEFAULT_KUBECONFIG_DIR,
        "servers": {},
    }

    for server_type, config in RANCHER_SERVERS.items():
        token = _get_rancher_token(server_type)
        server_status = {
            "url": config["url"],
            "token_configured": bool(token),
            "token_source": None,
            "cluster_count": len(config["clusters"]),
            "clusters": list(config["clusters"].keys()),
        }

        if token:
            if os.environ.get(config["token_env"]):
                server_status["token_source"] = f"env:{config['token_env']}"
            else:
                server_status["token_source"] = "vault"

        status["servers"][server_type] = server_status

    # Check for existing kubeconfigs
    kubeconfig_dir = Path(DEFAULT_KUBECONFIG_DIR)
    if kubeconfig_dir.exists():
        status["saved_kubeconfigs"] = [f.name for f in kubeconfig_dir.glob("*.yaml")]
    else:
        status["saved_kubeconfigs"] = []

    return status


# Export for convenience
__all__ = [
    "RancherClientError",
    "RancherAuthError",
    "RancherNotFoundError",
    "download_cluster_kubeconfig",
    "download_all_kubeconfigs",
    "get_available_clusters",
    "get_rancher_status",
    "RANCHER_SERVERS",
    "DEFAULT_KUBECONFIG_DIR",
]

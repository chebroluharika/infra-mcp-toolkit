"""
Rancher API Router

Handles Rancher integration endpoints for kubeconfig management.
Based on your-product-qe/tools/cluster_downloader.py pattern.

Rancher Servers:
    - NPE/Staging: your-rancher.example.com (qa01, stg01, etc.)
    - Production: rancher.example.com (sjc1, fra2, etc.)

ENDPOINTS:
- GET /api/rancher/status - Check Rancher connection status
- GET /api/rancher/clusters - List available clusters
- POST /api/rancher/kubeconfig/download/{cluster_name} - Download single kubeconfig
- POST /api/rancher/kubeconfig/download-all - Download all kubeconfigs
- GET /api/rancher/environments - List environments from JSON configs
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/rancher",
    tags=["rancher"],
)


@router.get("/status")
async def get_rancher_status():
    """
    Get Rancher configuration status.

    Shows which Rancher servers are configured and available clusters.
    Tokens can come from environment variables or Vault.

    RETURNS:
        {
            "servers": {
                "npe": {
                    "url": "your-rancher.example.com",
                    "token_configured": true,
                    "token_source": "env:RANCHER_NPE_KEY",
                    "cluster_count": 9,
                    "clusters": ["stork-stg01-mp-iad0-nc4", ...]
                },
                "prod": {...}
            },
            "saved_kubeconfigs": ["stork-stg01-mp-iad0-nc4.yaml", ...],
            "kubeconfig_dir": "~/.kube/rancher"
        }
    """
    try:
        from services.rancher_client import get_rancher_status

        return get_rancher_status()
    except Exception as e:
        logger.error("Error getting Rancher status: %s", e)
        return {"error": str(e)}


@router.get("/clusters")
async def list_clusters():
    """
    List all available clusters from both Rancher servers.

    RETURNS:
        {
            "npe": ["stork-stg01-mp-iad0-nc4", "stork-qa01-mp-npe-iad0-nc1", ...],
            "prod": ["c4-sjc1", "stork-fra2-mp-prod-fra2-nc1", ...]
        }
    """
    try:
        from services.rancher_client import get_available_clusters

        return get_available_clusters()
    except Exception as e:
        logger.error("Error listing clusters: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kubeconfig/download/{cluster_name}")
async def download_kubeconfig(cluster_name: str):
    """
    Download kubeconfig for a specific cluster.

    PARAMETERS:
        - cluster_name: Cluster name (e.g., "stork-stg01-mp-iad0-nc4")

    RETURNS:
        {
            "success": true,
            "cluster_name": "stork-stg01-mp-iad0-nc4",
            "kubeconfig_path": "/Users/user/.kube/rancher/stork-stg01-mp-iad0-nc4.yaml"
        }
    """
    try:
        from services.rancher_client import download_cluster_kubeconfig

        filepath = download_cluster_kubeconfig(cluster_name)

        if filepath:
            return {
                "success": True,
                "cluster_name": cluster_name,
                "kubeconfig_path": str(filepath),
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to download kubeconfig for {cluster_name}. Check logs and ensure RANCHER_NPE_KEY or RANCHER_PROD_KEY is set.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error downloading kubeconfig: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kubeconfig/download-all")
async def download_all_kubeconfigs(
    server: Optional[str] = Query(None, description="Server type: 'npe', 'prod', or None for both"),
):
    """
    Download kubeconfigs for all clusters.

    PARAMETERS:
        - server: "npe" (staging), "prod" (production), or None for both

    RETURNS:
        {
            "success": true,
            "downloaded": ["stork-stg01-mp-iad0-nc4", ...],
            "failed": ["cluster-xyz", ...],
            "kubeconfig_dir": "~/.kube/rancher"
        }
    """
    try:
        from config import refresh_stack_discovery
        from services.rancher_client import DEFAULT_KUBECONFIG_DIR, download_all_kubeconfigs

        results = download_all_kubeconfigs(server_type=server)

        downloaded = [name for name, path in results.items() if path]
        failed = [name for name, path in results.items() if not path]

        # Re-discover stacks so kubeconfig_path is populated for newly downloaded files
        if downloaded:
            refresh_stack_discovery()

        return {
            "success": len(failed) == 0,
            "downloaded": downloaded,
            "failed": failed,
            "total_downloaded": len(downloaded),
            "total_failed": len(failed),
            "kubeconfig_dir": DEFAULT_KUBECONFIG_DIR,
        }
    except Exception as e:
        logger.error("Error downloading kubeconfigs: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/environments")
async def list_environments(
    production_only: bool = Query(False, description="Only show production environments"),
    non_production_only: bool = Query(False, description="Only show non-production environments"),
    refresh: bool = Query(False, description="Force refresh from GitHub"),
):
    """
    List environments from your-product-qe GitHub repository.

    PURPOSE:
        Get list of all environments configured in your-product-qe JSON files.
        Fetches from GitHub: your-company-qe/your-product-qe repository.
        Shows environment details including kubeconfig filename for Rancher matching.

    PARAMETERS:
        - production_only (bool): Only show production environments
        - non_production_only (bool): Only show non-production environments
        - refresh (bool): Force refresh from GitHub

    RETURNS:
        {
            "environments": [...],
            "total": 20,
            "source": "github",
            "github_repo": "your-company-qe/your-product-qe"
        }
    """
    try:
        from services.environment_config import (
            get_all_environments,
            get_config_source,
            get_non_production_environments,
            get_production_environments,
            reload_configs,
        )

        # Force refresh if requested
        if refresh:
            reload_configs()

        if production_only:
            environments = get_production_environments()
        elif non_production_only:
            environments = get_non_production_environments()
        else:
            environments = get_all_environments()

        # Format for API response
        formatted_envs = []
        for env in environments:
            formatted_envs.append(
                {
                    "name": env.name,
                    "stack_name": env.stack_name,
                    "hostname": env.env_hostname,
                    "alias_hostname": env.alias_hostname,
                    "kubeconfig_filename": env.kubeconfig_filename,
                    "is_production": env.is_production,
                    "region": env.region,
                    "namespace_suffix": env.namespace_suffix,
                    "uses_vault": env.uses_vault,
                }
            )

        source = get_config_source()

        return {
            "environments": formatted_envs,
            "total": len(formatted_envs),
            "source": source,
            "github_repo": "your-company-qe/your-product-qe",
        }

    except Exception as e:
        logger.error("Error listing environments: %s", e)
        return {
            "environments": [],
            "total": 0,
            "source": "error",
            "error": str(e),
            "message": "Failed to load environment configs from GitHub.",
            "help": "Ensure GITHUB_TOKEN is set for private repo access.",
        }


@router.get("/stacks")
async def list_configured_stacks():
    """
    List all configured Kubernetes stacks.

    PURPOSE:
        Get list of all stacks discovered from all sources
        (base config, JSON files, environment variables).

    RETURNS:
        {
            "stacks": {
                "stg01": {
                    "context": "stork-stg01-mp-iad0-nc4",
                    "region": "US-IAD0",
                    "description": "STG01 Stack (Staging)",
                    "kubeconfig_configured": true
                },
                ...
            },
            "total": 5
        }
    """
    try:
        from config import get_kubernetes_stacks

        stacks = get_kubernetes_stacks()

        # Format for API response
        formatted_stacks = {}
        for stack_id, config in stacks.items():
            formatted_stacks[stack_id] = {
                "context": config.get("context", ""),
                "region": config.get("region", "Unknown"),
                "description": config.get("description", f"{stack_id.upper()} Stack"),
                "namespace_suffix": config.get("namespace_suffix", "-mp"),
                "kubeconfig_filename": config.get("kubeconfig_filename", ""),
                "kubeconfig_configured": bool(config.get("kubeconfig_path")),
                "kubeconfig_path": config.get("kubeconfig_path", ""),
                "is_production": config.get("is_production", False),
            }

        return {
            "stacks": formatted_stacks,
            "total": len(formatted_stacks),
        }

    except Exception as e:
        logger.error("Error listing stacks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kubeconfig/ensure/{stack_id}")
async def ensure_kubeconfig(
    stack_id: str,
    max_age_hours: int = Query(24, description="Max age before refresh"),
):
    """
    Ensure kubeconfig exists and is fresh for a stack.

    PURPOSE:
        Check if kubeconfig exists and refresh if expired.
        Downloads from Rancher if not found locally.

    PARAMETERS:
        - stack_id (str): Stack ID (e.g., "stg01", "qa01")
        - max_age_hours (int): Max age before auto-refresh (default: 24)

    RETURNS:
        {
            "success": true,
            "stack_id": "stg01",
            "kubeconfig_path": "/path/to/kubeconfig.yaml",
            "refreshed": false,
            "age_hours": 12.5
        }
    """
    try:
        from config import get_kubernetes_stacks
        from services.rancher_client import get_rancher_client

        stacks = get_kubernetes_stacks()

        if stack_id not in stacks:
            raise HTTPException(
                status_code=404, detail=f"Stack not found: {stack_id}. Available: {list(stacks.keys())}"
            )

        stack_config = stacks[stack_id]

        # Check if kubeconfig already exists
        existing_path = stack_config.get("kubeconfig_path")
        if existing_path:
            import os
            from datetime import datetime

            if os.path.exists(existing_path):
                age_hours = (datetime.now().timestamp() - os.path.getmtime(existing_path)) / 3600

                if age_hours < max_age_hours:
                    return {
                        "success": True,
                        "stack_id": stack_id,
                        "kubeconfig_path": existing_path,
                        "refreshed": False,
                        "age_hours": round(age_hours, 1),
                        "message": "Kubeconfig is fresh",
                    }

        # Need to download/refresh
        client = get_rancher_client()

        if not client.is_configured():
            raise HTTPException(status_code=503, detail="Rancher not configured and kubeconfig not found locally")

        # Determine cluster name
        kubeconfig_filename = stack_config.get("kubeconfig_filename", "")
        cluster_name = kubeconfig_filename.replace(".yaml", "").replace(".yml", "")

        if not cluster_name:
            cluster_name = stack_config.get("context", "")

        if not cluster_name:
            raise HTTPException(status_code=400, detail=f"Cannot determine cluster name for stack {stack_id}")

        # Download kubeconfig
        filepath = client.download_kubeconfig_by_name(cluster_name, overwrite=True)

        return {
            "success": True,
            "stack_id": stack_id,
            "kubeconfig_path": str(filepath),
            "refreshed": True,
            "age_hours": 0,
            "message": "Kubeconfig downloaded from Rancher",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error ensuring kubeconfig: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

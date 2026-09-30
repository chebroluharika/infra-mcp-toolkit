"""
Stack Monitoring Service
Integrates with Kubernetes to monitor deployment versions across stacks
Based on: stack-monitoring repository

PERFORMANCE OPTIMIZATIONS:
- Parallel Kubernetes API calls using concurrent.futures
- Result caching (5 minute TTL)
- Batch namespace operations

AUTH HANDLING:
- Automatically skips TLS verification for Rancher clusters
- Detects auth failures and provides actionable error messages
- Tracks per-stack authentication status

FEATURES:
- Deployment version tracking across stacks
- Resource metrics (CPU/Memory) from metrics-server
- Pod logs preview
- Readiness/Liveness probe status
- Historical snapshots for trend analysis
"""

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import urllib3
from config import get_kubernetes_stacks, settings
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from services.environment_config import get_services_for_stack
from utilities.time_utils import get_current_time_formatted

# Use PST timezone for milestone date comparisons
# This ensures consistent behavior regardless of server location
PST_TIMEZONE = ZoneInfo("America/Los_Angeles")

# Historical snapshots storage path
SNAPSHOTS_DIR = Path(__file__).parent.parent / "data" / "stack_snapshots"

# Suppress SSL warnings when TLS verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class StackMonitoringService:
    """Service to monitor Your-Product stack deployments across Kubernetes clusters"""

    # DEPLOYMENT_MAP: Maps namespace suffix -> list of deployment names to monitor
    #
    # Total: 18 services across 12 namespace entries
    #
    # Format:
    # - Stack-specific namespaces use suffixes like "--addonman", "--clientstatus"
    #   Full namespace = {stack}-mp[-npe]{suffix} (e.g., "qa01-mp-npe--addonman")
    # - Standalone namespaces (otp, enrollment-service, device-classification)
    #   are the same across all stacks
    DEPLOYMENT_MAP: Dict[str, List[str]] = {
        # === Stack-specific namespaces ===
        # Row 1: addonman (1 deployment)
        "--addonman": ["addonman-addonman"],
        # Rows 2-3: clientstatus (2 deployments)
        "--clientstatus": ["clientstatus-clientstatus", "clientstatus-clientasyncstatus"],
        # Row 4: provisioner-core--clientservices (1 deployment)
        "--provisioner-core--clientservices": ["provisioner-core-provisioner-core"],
        # Rows 5-9: provisioner-pycore (5 namespaces, each with 1 deployment)
        "--provisioner-pycore--branding": ["provisioner-pycore-provisioner-pycore"],
        "--provisioner-pycore--clientservices": ["provisioner-pycore-provisioner-pycore"],
        "--provisioner-pycore--clientstatus": ["provisioner-pycore-provisioner-pycore"],
        "--provisioner-pycore--provisioner": ["provisioner-pycore-provisioner-pycore"],
        "--provisioner-pycore--support": ["provisioner-pycore-provisioner-pycore"],
        # === Standalone namespaces (same across all stacks) ===
        # Row 10: otp (1 deployment)
        "otp": ["otp"],
        # Rows 11-14: enrollment-service (4 deployments)
        "enrollment-service": [
            "enrollment-service-configuration",
            "enrollment-service-validation",
            "enrollment-service-deprovision",
            "enrollment-service-vaultrotate",
        ],
        # Rows 15-18: device-classification (4 deployments)
        "device-classification": [
            "device-classification-configuration",
            "device-classification-deprovisioner",
            "device-classification-evaluator",
            "device-classification-tag",
        ],
    }

    # Standalone namespaces that don't use stack prefix
    STANDALONE_NAMESPACES = {"otp", "enrollment-service", "device-classification"}

    # CONTEXT_MAP is now dynamically loaded from config.py
    # Add new stacks in config.py KUBERNETES_STACKS instead of here
    @property
    def CONTEXT_MAP(self) -> Dict[str, str]:
        """Dynamically build context map from config."""
        stacks = get_kubernetes_stacks()
        return {stack_id: cfg["context"] for stack_id, cfg in stacks.items()}

    @property
    def STACK_CONFIG(self) -> Dict[str, Dict[str, str]]:
        """Get full stack configuration from config."""
        return get_kubernetes_stacks()

    def _get_stack_namespace_prefix(self, stack: str) -> Optional[str]:
        """
        Get the namespace prefix for a stack.

        Namespace prefix patterns vary by stack type:
        - NPE stacks (qa01, npa01): {stack}-mp-npe
        - Staging stacks (stg01): {stack}-mp
        - Production stacks: {stack}-mp-prod
        - Legacy stacks: {stack} (e.g., stg01-mplegacy)
        - Special stacks (devint, fed1mp): mp-{stack}

        Returns:
            Namespace prefix string, or None if not found
        """
        stack_config = self.STACK_CONFIG.get(stack, {})

        # Check for explicit namespace_prefix in config
        if "namespace_prefix" in stack_config:
            return stack_config["namespace_prefix"]

        # FIRST: Try JSON config as it has the most accurate namespace info
        services = get_services_for_stack(stack)
        if services:
            # Try to extract prefix from addonman namespace
            addonman_ns = services.get("addonman", "")
            if addonman_ns and "--addonman" in addonman_ns:
                prefix = addonman_ns.replace("--addonman", "")
                logger.debug("Using namespace prefix from JSON config for %s: %s", stack, prefix)
                return prefix

        # Derive from context name
        # Context format: stork-{prefix}-{region} e.g., stork-stg01-mp-iad0-nc4
        context = stack_config.get("context", "")
        if context.startswith("stork-"):
            # Extract prefix from context: stork-stg01-mp-iad0-nc4 -> stg01-mp
            parts = context[6:].split("-")  # Remove 'stork-' prefix
            if len(parts) >= 2:
                # Find where region starts (iad0, sjc1, fra2, etc.)
                region_markers = ["iad", "sjc", "fra", "lon", "sin", "mel", "zur", "ruh", "dfw", "bom", "nc"]
                prefix_parts = []
                for part in parts:
                    is_region = any(part.startswith(m) for m in region_markers)
                    if is_region:
                        break
                    prefix_parts.append(part)
                if prefix_parts:
                    return "-".join(prefix_parts)

        # Handle c4-* and c1-* contexts (production clusters with short names)
        if context.startswith("c4-") or context.startswith("c1-"):
            # c4-sjc1 -> sjc1-mp-prod, c1-sv5 -> sv5-mp-prod
            stack_name = context.split("-", 1)[1] if "-" in context else stack
            return f"{stack_name}-mp-prod"

        # Final fallback: simple pattern
        return f"{stack}-mp"

    def get_deployment_map_for_stack(self, stack: str) -> Dict[str, List[str]]:
        """
        Dynamically build deployment map for a specific stack based on its JSON config.

        This ensures we only query namespaces that actually exist for this stack,
        rather than using a hardcoded map that assumes all stacks have the same namespaces.

        Args:
            stack: Stack name (e.g., "stg01", "qa01", "sjc1")

        Returns:
            Dict mapping namespace_key -> list of deployment names
        """
        services = get_services_for_stack(stack)

        # Check if this is a VM-based stack (AM2, FR4, SV5) - they don't have clientstatus pods
        is_vm_based = self._is_vm_based_stack(stack)

        if not services:
            # Fallback to hardcoded map if no JSON config available
            logger.debug("No JSON config for stack %s, using fallback DEPLOYMENT_MAP", stack)
            if is_vm_based:
                # Exclude clientstatus namespace for VM-based stacks
                return {k: v for k, v in self.DEPLOYMENT_MAP.items() if k != "--clientstatus"}
            return self.DEPLOYMENT_MAP

        namespace_prefix = self._get_stack_namespace_prefix(stack)
        deployment_map: Dict[str, List[str]] = {}

        for svc_name, full_namespace in services.items():
            # Extract namespace suffix from full namespace
            # e.g., "qa01-mp-npe--addonman" -> "--addonman"
            # e.g., "enrollment-service" -> "enrollment-service" (standalone)

            if full_namespace in self.STANDALONE_NAMESPACES:
                namespace_suffix = full_namespace
            elif namespace_prefix and full_namespace.startswith(namespace_prefix):
                namespace_suffix = full_namespace[len(namespace_prefix) :]
            else:
                # Could be a standalone namespace or unknown format
                namespace_suffix = full_namespace

            # Skip clientstatus namespace for VM-based stacks (AM2, FR4, SV5)
            if is_vm_based and namespace_suffix == "--clientstatus":
                logger.debug("Skipping clientstatus for VM-based stack %s", stack)
                continue

            # Look up deployments for this namespace suffix
            if namespace_suffix in self.DEPLOYMENT_MAP:
                deployment_map[namespace_suffix] = self.DEPLOYMENT_MAP[namespace_suffix]
            else:
                # Unknown namespace - try to infer deployment name
                # Common pattern: namespace "x" contains deployment "x" or "x-x"
                logger.debug("Unknown namespace suffix %s for stack %s, inferring deployment", namespace_suffix, stack)
                clean_suffix = namespace_suffix.lstrip("-")
                deployment_map[namespace_suffix] = [clean_suffix]

        logger.debug(
            "Built deployment map for stack %s: %d namespaces, services=%s",
            stack,
            len(deployment_map),
            list(services.keys()),
        )
        return deployment_map

    def __init__(self):
        self.master_config = {}
        self._cache = None
        self._cache_timestamp = None
        self._cache_ttl = 300  # 5 minutes cache
        self._lock = threading.Lock()
        # Track auth status per stack for error reporting
        self._auth_status: Dict[str, Dict] = {}
        # Track if we've already warned about auth issues this session
        self._auth_warned: Dict[str, bool] = {}
        # Store namespace events for API response
        self._namespace_events: Dict[str, Dict] = {}
        # Cache for loaded kubeconfigs (stack -> timestamp)
        self._kubeconfig_cache: Dict[str, float] = {}
        self._kubeconfig_cache_ttl = 60  # 1 minute cache for kubeconfig
        # Cache for API clients per stack (reuse across parallel calls)
        self._api_client_cache: Dict[str, Dict] = {}
        self._api_client_cache_ttl = 300  # 5 minutes cache for API clients

    def _get_api_clients(self, stack: str) -> tuple:
        """
        Get or create cached API clients for a stack.
        Returns (apps_v1, core_v1, api_client) tuple, or (None, None, None) if failed.

        THREAD-SAFE: Creates API clients with stack-specific configuration to avoid
        race conditions when running parallel requests to different stacks.
        """
        import time

        current_time = time.time()

        with self._lock:
            cached = self._api_client_cache.get(stack)
            if cached and (current_time - cached.get("timestamp", 0)) < self._api_client_cache_ttl:
                return cached["apps_v1"], cached["core_v1"], cached["api_client"]

        # Create new clients with stack-specific configuration
        context = self.CONTEXT_MAP.get(stack)
        if not context:
            return None, None, None

        try:
            # Load kubeconfig for this specific stack
            kubeconfig_file = self._get_kubeconfig_path(stack)

            if kubeconfig_file and os.path.exists(kubeconfig_file):
                # Load config into a NEW configuration object (not the global default)
                # This is thread-safe as each stack gets its own configuration
                config.load_kube_config(config_file=kubeconfig_file, persist_config=False)
            else:
                config.load_kube_config(context=context, persist_config=False)

            # Get the configuration that was just loaded and modify it
            configuration = client.Configuration.get_default_copy()
            configuration.verify_ssl = False
            configuration.assert_hostname = False

            # Set explicit timeouts to prevent hanging on slow/unreachable clusters
            # These are defaults that can be overridden per-request with _request_timeout
            configuration.retries = 1  # Don't retry failed requests (fail fast)

            # Create ApiClient with this specific configuration (not the global default)
            api_client = client.ApiClient(configuration=configuration)

            # Set socket-level timeouts on the REST client
            # This ensures even if _request_timeout isn't respected, we still timeout
            if hasattr(api_client.rest_client, "pool_manager"):
                api_client.rest_client.pool_manager.connection_pool_kw["timeout"] = settings.k8s_read_timeout

            # Create API objects using this specific client
            apps_v1 = client.AppsV1Api(api_client=api_client)
            core_v1 = client.CoreV1Api(api_client=api_client)

            with self._lock:
                self._api_client_cache[stack] = {
                    "apps_v1": apps_v1,
                    "core_v1": core_v1,
                    "api_client": api_client,
                    "timestamp": current_time,
                }

            return apps_v1, core_v1, api_client
        except config.ConfigException as e:
            self._update_auth_status(stack, "config_error", str(e))
            return None, None, None
        except Exception as e:
            logger.error("Failed to create API clients for %s: %s", stack, e)
            return None, None, None

    def get_all_deployments_in_namespace(
        self, api_client: client.AppsV1Api, namespace: str, deployment_names: List[str]
    ) -> Dict[str, List[Dict]]:
        """
        Fetches all deployments in a namespace with a single API call.
        Much faster than fetching each deployment individually.

        Args:
            api_client: Kubernetes AppsV1 API client
            namespace: Kubernetes namespace
            deployment_names: List of deployment names to extract

        Returns:
            Dict mapping deployment name to list of deployment info dicts
        """
        results = {}

        try:
            # Single API call to get ALL deployments in namespace
            # Timeouts are configurable via settings (K8S_CONNECT_TIMEOUT, K8S_READ_TIMEOUT)
            # Production stacks via Rancher (especially distant regions) may need longer timeouts
            deployment_list = api_client.list_namespaced_deployment(
                namespace=namespace, _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout)
            )

            # Index deployments by name for quick lookup
            deployment_map = {d.metadata.name: d for d in deployment_list.items}

            for deployment_name in deployment_names:
                if deployment_name in deployment_map:
                    deployment_obj = deployment_map[deployment_name]
                    results[deployment_name] = self._parse_deployment_obj(deployment_obj)
                else:
                    # Deployment not found
                    results[deployment_name] = [
                        {
                            "name": deployment_name,
                            "version": "not_found",
                            "status": "not_found",
                            "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                            "age": "unknown",
                            "last_updated": None,
                            "created_at": None,
                            "image": None,
                        }
                    ]

            return results

        except ApiException as e:
            # Return error status for all requested deployments
            error_status = (
                "auth_failed" if e.status == 401 else ("forbidden" if e.status == 403 else f"api_error_{e.status}")
            )
            for deployment_name in deployment_names:
                results[deployment_name] = [
                    {
                        "name": deployment_name,
                        "version": "error",
                        "status": error_status,
                        "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                        "age": "unknown",
                        "last_updated": None,
                        "created_at": None,
                        "image": None,
                    }
                ]
            return results
        except Exception as e:
            error_str = str(e).lower()
            # Determine specific error type for better UI feedback
            if "timeout" in error_str or "timed out" in error_str:
                error_status = "timeout"
                logger.warning("Timeout fetching deployments in %s (cluster may be slow/unreachable)", namespace)
            elif "connection" in error_str or "connect" in error_str:
                error_status = "connection_error"
                logger.warning("Connection error fetching deployments in %s: %s", namespace, e)
            else:
                error_status = "fetch_error"
                logger.error("Error fetching deployments in %s: %s", namespace, e)

            for deployment_name in deployment_names:
                results[deployment_name] = [
                    {
                        "name": deployment_name,
                        "version": "error",
                        "status": error_status,
                        "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                        "age": "unknown",
                        "last_updated": None,
                        "created_at": None,
                        "image": None,
                    }
                ]
            return results

    def _parse_deployment_obj(self, deployment_obj) -> List[Dict]:
        """Parse a Kubernetes deployment object into deployment info dicts."""
        deployments_data = []

        # Check deployment availability status
        status_str = "unknown"
        last_updated = None
        status_changed_at = None  # When status actually transitioned (for unhealthy)
        if deployment_obj.status and deployment_obj.status.conditions:
            for condition in deployment_obj.status.conditions:
                if condition.type == "Available":
                    if condition.status == "True":
                        status_str = "healthy"
                        last_updated = condition.last_update_time
                    else:
                        reason = condition.reason if condition.reason else "unavailable"
                        status_str = f"unhealthy ({reason})"
                        # For unhealthy, use last_transition_time (when it became unhealthy)
                        # not last_update_time (when condition was last checked)
                        last_updated = condition.last_update_time
                        status_changed_at = condition.last_transition_time
                    break

        # Extract replica information
        status = deployment_obj.status
        replicas_info = {
            "desired": status.replicas or 0,
            "ready": status.ready_replicas or 0,
            "available": status.available_replicas or 0,
            "unavailable": status.unavailable_replicas or 0,
            "updated": status.updated_replicas or 0,
        }

        # Calculate deployment age
        created_at = deployment_obj.metadata.creation_timestamp
        age_str = self._calculate_age(created_at) if created_at else "unknown"
        created_iso = created_at.isoformat() if created_at else None

        # Format timestamps
        last_updated_str = last_updated.strftime("%Y-%m-%d %H:%M:%S") if last_updated else None
        # status_changed_at is when the deployment became unhealthy (last_transition_time)
        status_changed_at_str = status_changed_at.isoformat() if status_changed_at else None

        # Get container images and versions
        containers = deployment_obj.spec.template.spec.containers
        for container in containers:
            image = container.image if container.image else "unknown"
            # Extract version from image tag
            version = "latest"
            if ":" in image:
                version = image.split(":")[-1]
            elif "@" in image:  # Handle digest-based versions
                version = image.split("@")[-1][:12]

            deployments_data.append(
                {
                    "name": f"{deployment_obj.metadata.name}/{container.name}",
                    "version": version,
                    "status": status_str,
                    "replicas": replicas_info,
                    "age": age_str,
                    "last_updated": last_updated_str,
                    "created_at": created_iso,
                    "image": image,
                    "status_changed_at": status_changed_at_str,  # When status transitioned (for unhealthy)
                }
            )

        # If no containers found, add deployment-level entry
        if not deployments_data:
            deployments_data.append(
                {
                    "name": deployment_obj.metadata.name,
                    "version": "unknown",
                    "status": status_str,
                    "replicas": replicas_info,
                    "age": age_str,
                    "last_updated": last_updated_str,
                    "created_at": created_iso,
                    "image": None,
                    "status_changed_at": status_changed_at_str,
                }
            )

        return deployments_data

    def get_deployment_info(self, api_client: client.AppsV1Api, deployment_name: str, namespace: str) -> List[Dict]:
        """
        Fetches comprehensive deployment information including version, status, replicas, and age.

        Returns: List of dicts with deployment info:
            - name: deployment/container name
            - version: image tag
            - status: health status string
            - replicas: dict with desired, ready, available, unavailable counts
            - age: deployment age in human-readable format
            - last_updated: last update timestamp
            - created_at: creation timestamp (ISO format)
        """
        deployments_data = []

        try:
            deployment_obj = api_client.read_namespaced_deployment(name=deployment_name, namespace=namespace)

            # Check deployment availability status
            status_str = "unknown"
            last_updated = None
            status_changed_at = None  # When status actually transitioned (for unhealthy)
            if deployment_obj.status and deployment_obj.status.conditions:
                for condition in deployment_obj.status.conditions:
                    if condition.type == "Available":
                        if condition.status == "True":
                            status_str = "healthy"
                            last_updated = condition.last_update_time
                        else:
                            reason = condition.reason if condition.reason else "unavailable"
                            status_str = f"unhealthy ({reason})"
                            last_updated = condition.last_update_time
                            # For unhealthy, use last_transition_time (when it became unhealthy)
                            status_changed_at = condition.last_transition_time
                        break

            # Extract replica information
            status = deployment_obj.status
            replicas_info = {
                "desired": status.replicas or 0,
                "ready": status.ready_replicas or 0,
                "available": status.available_replicas or 0,
                "unavailable": status.unavailable_replicas or 0,
                "updated": status.updated_replicas or 0,
            }

            # Calculate deployment age
            created_at = deployment_obj.metadata.creation_timestamp
            age_str = self._calculate_age(created_at) if created_at else "unknown"
            created_iso = created_at.isoformat() if created_at else None

            # Format timestamps
            last_updated_str = None
            if last_updated:
                last_updated_str = self._calculate_age(last_updated)
            status_changed_at_str = status_changed_at.isoformat() if status_changed_at else None

            # Extract container versions
            for container in deployment_obj.spec.template.spec.containers:
                image_url = container.image
                version = image_url.split(":")[-1] if ":" in image_url else image_url

                full_name = f"{deployment_name}/{container.name}"
                deployments_data.append(
                    {
                        "name": full_name,
                        "version": version,
                        "status": status_str,
                        "replicas": replicas_info,
                        "age": age_str,
                        "last_updated": last_updated_str,
                        "created_at": created_iso,
                        "image": image_url,
                        "status_changed_at": status_changed_at_str,
                    }
                )

            # If no containers found
            if not deployment_obj.spec.template.spec.containers:
                deployments_data.append(
                    {
                        "name": deployment_name,
                        "version": "N/A",
                        "status": status_str,
                        "replicas": replicas_info,
                        "age": age_str,
                        "last_updated": last_updated_str,
                        "created_at": created_iso,
                        "image": None,
                        "status_changed_at": status_changed_at_str,
                    }
                )

            return deployments_data

        except ApiException as e:
            if e.status == 404:
                status_text = "not_found"
            elif e.status == 401:
                status_text = "auth_failed"
                logger.warning(
                    f"K8s auth failed for {deployment_name}: Token expired or invalid. Re-authenticate with kubectl."
                )
            elif e.status == 403:
                status_text = "forbidden"
                logger.warning("K8s access denied for %s: Missing RBAC permissions.", deployment_name)
            else:
                status_text = f"api_error_{e.status}"
            deployments_data.append(
                {
                    "name": deployment_name,
                    "version": "error",
                    "status": status_text,
                    "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                    "age": "unknown",
                    "last_updated": None,
                    "created_at": None,
                    "image": None,
                }
            )
            return deployments_data
        except Exception as e:
            logger.error("Unexpected error fetching deployment {deployment_name}: %s", e)
            deployments_data.append(
                {
                    "name": deployment_name,
                    "version": "error",
                    "status": "unexpected_error",
                    "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                    "age": "unknown",
                    "last_updated": None,
                    "created_at": None,
                    "image": None,
                }
            )
            return deployments_data

    def _calculate_age(self, timestamp) -> str:
        """Calculate human-readable age from a timestamp."""
        if not timestamp:
            return "unknown"

        now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
        delta = now - timestamp

        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 30:
            months = days // 30
            return f"{months}mo" if months == 1 else f"{months}mo"
        elif days > 0:
            return f"{days}d" if days == 1 else f"{days}d"
        elif hours > 0:
            return f"{hours}h" if hours == 1 else f"{hours}h"
        else:
            return f"{minutes}m" if minutes == 1 else f"{minutes}m"

    def get_pod_restart_counts(self, namespace: str, stack: str) -> Dict[str, Dict]:
        """
        Fetch pod restart counts for all pods in a namespace.
        Batches by namespace to minimize API calls.
        Uses cached API clients for better performance.

        Returns:
            Dict mapping deployment name to restart info:
            {
                "deployment-name": {
                    "total_restarts": 5,
                    "pods": [
                        {"name": "pod-xxx", "restarts": 2, "status": "Running"},
                        ...
                    ]
                }
            }
        """
        restart_data = {}

        try:
            # Use cached API clients for better performance
            _, core_v1, _ = self._get_api_clients(stack)
            if not core_v1:
                return restart_data

            pods = core_v1.list_namespaced_pod(
                namespace=namespace, _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout)
            )

            for pod in pods.items:
                # Extract deployment name from pod (usually in labels or owner references)
                deployment_name = None
                if pod.metadata.labels:
                    deployment_name = pod.metadata.labels.get("app") or pod.metadata.labels.get(
                        "app.kubernetes.io/name"
                    )

                if not deployment_name:
                    # Try to extract from pod name (e.g., "myapp-deployment-xxx-yyy" -> "myapp-deployment")
                    parts = pod.metadata.name.rsplit("-", 2)
                    if len(parts) >= 2:
                        deployment_name = parts[0]
                    else:
                        deployment_name = pod.metadata.name

                if deployment_name not in restart_data:
                    restart_data[deployment_name] = {
                        "total_restarts": 0,
                        "pods": [],
                        "crash_loop": False,
                        "error_reason": None,
                        "error_message": None,
                        "error_occurred_at": None,  # Actual timestamp when error occurred
                        "last_restart_at": None,  # Actual K8s timestamp of most recent container restart
                    }

                # Get restart count from container statuses
                pod_restarts = 0
                pod_status = pod.status.phase if pod.status else "Unknown"
                is_crash_loop = False
                error_reason = None
                error_message = None
                error_occurred_at = None  # Track when the error actually occurred
                last_restart_at = None  # Track actual K8s restart time from container status

                # Check init container statuses first (common source of ImagePullBackOff)
                if pod.status and pod.status.init_container_statuses:
                    for init_status in pod.status.init_container_statuses:
                        if init_status.state and init_status.state.waiting:
                            waiting = init_status.state.waiting
                            if waiting.reason:
                                error_reason = waiting.reason
                                error_message = waiting.message
                                # Update pod status to reflect init container issue
                                if waiting.reason in ["ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"]:
                                    pod_status = f"Init:{waiting.reason}"
                        # Check for terminated init containers with timestamps
                        if init_status.state and init_status.state.terminated:
                            terminated = init_status.state.terminated
                            if terminated.finished_at and terminated.reason in ["Error", "OOMKilled"]:
                                error_occurred_at = terminated.finished_at

                if pod.status and pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        pod_restarts += container_status.restart_count or 0
                        # Check for CrashLoopBackOff or other waiting states
                        if container_status.state and container_status.state.waiting:
                            waiting = container_status.state.waiting
                            if waiting.reason == "CrashLoopBackOff":
                                is_crash_loop = True
                                # For CrashLoopBackOff, get the timestamp from last_state.terminated
                                # This shows when the last crash occurred
                                if container_status.last_state and container_status.last_state.terminated:
                                    last_term = container_status.last_state.terminated
                                    if last_term.finished_at:
                                        error_occurred_at = last_term.finished_at
                            # Capture error reason/message if not already set by init container
                            if waiting.reason and not error_reason:
                                error_reason = waiting.reason
                                error_message = waiting.message

                        # Check for OOMKilled in terminated state (container was killed due to memory)
                        if container_status.state and container_status.state.terminated:
                            terminated = container_status.state.terminated
                            if terminated.reason == "OOMKilled":
                                if not error_reason:
                                    error_reason = "OOMKilled"
                                    error_message = "Container killed due to exceeding memory limits"
                                # Extract actual OOM timestamp
                                if terminated.finished_at:
                                    error_occurred_at = terminated.finished_at

                        # Also check last_state for OOMKilled (if container restarted after OOM)
                        if container_status.last_state and container_status.last_state.terminated:
                            last_terminated = container_status.last_state.terminated
                            if last_terminated.reason == "OOMKilled":
                                if not error_reason:
                                    error_reason = "OOMKilled"
                                    error_message = "Container was killed due to exceeding memory limits (restarted)"
                                # Extract actual OOM timestamp from last termination
                                if last_terminated.finished_at and not error_occurred_at:
                                    error_occurred_at = last_terminated.finished_at

                        # Extract actual last restart time from K8s for any container with restarts
                        # This is the actual timestamp when the container was last terminated/restarted,
                        # as opposed to when our snapshot detected the restart count change
                        if container_status.restart_count and container_status.restart_count > 0:
                            if container_status.last_state and container_status.last_state.terminated:
                                term_finished = container_status.last_state.terminated.finished_at
                                if term_finished:
                                    # Keep the most recent restart time across all containers
                                    if last_restart_at is None or term_finished > last_restart_at:
                                        last_restart_at = term_finished

                # Format error_occurred_at as ISO string
                error_occurred_at_str = None
                if error_occurred_at:
                    error_occurred_at_str = (
                        error_occurred_at.isoformat()
                        if hasattr(error_occurred_at, "isoformat")
                        else str(error_occurred_at)
                    )

                # Format last_restart_at as ISO string
                last_restart_at_str = None
                if last_restart_at:
                    last_restart_at_str = (
                        last_restart_at.isoformat() if hasattr(last_restart_at, "isoformat") else str(last_restart_at)
                    )

                restart_data[deployment_name]["total_restarts"] += pod_restarts
                restart_data[deployment_name]["pods"].append(
                    {
                        "name": pod.metadata.name,
                        "restarts": pod_restarts,
                        "status": pod_status,
                        "crash_loop": is_crash_loop,
                        "error_reason": error_reason,
                        "error_message": error_message,
                        "error_occurred_at": error_occurred_at_str,
                        "last_restart_at": last_restart_at_str,
                    }
                )
                if is_crash_loop:
                    restart_data[deployment_name]["crash_loop"] = True
                # Bubble up error info to deployment level (use first/most recent error found)
                if error_reason and not restart_data[deployment_name]["error_reason"]:
                    restart_data[deployment_name]["error_reason"] = error_reason
                    restart_data[deployment_name]["error_message"] = error_message
                    restart_data[deployment_name]["error_occurred_at"] = error_occurred_at_str
                # Update occurred_at if we have a more recent timestamp
                elif error_occurred_at_str and restart_data[deployment_name]["error_occurred_at"]:
                    existing = restart_data[deployment_name]["error_occurred_at"]
                    if error_occurred_at_str > existing:
                        restart_data[deployment_name]["error_occurred_at"] = error_occurred_at_str

                # Bubble up last_restart_at to deployment level (keep most recent)
                if last_restart_at_str:
                    existing_restart = restart_data[deployment_name]["last_restart_at"]
                    if existing_restart is None or last_restart_at_str > existing_restart:
                        restart_data[deployment_name]["last_restart_at"] = last_restart_at_str

            return restart_data

        except ApiException as e:
            logger.warning("Failed to fetch pod restarts for %s/%s: %s", stack, namespace, e.status)
            return restart_data
        except Exception as e:
            logger.error("Error fetching pod restarts: %s", e)
            return restart_data

    def get_namespace_events(self, namespace: str, stack: str, limit: int = 20) -> List[Dict]:
        """
        Fetch recent warning/error events for a namespace.
        Batches by namespace to minimize API calls.
        Uses cached API clients for better performance.

        Args:
            namespace: Kubernetes namespace
            stack: Stack identifier
            limit: Maximum number of events to return

        Returns:
            List of event dicts:
            [
                {
                    "type": "Warning",
                    "reason": "BackOff",
                    "message": "Back-off restarting failed container",
                    "object": "pod/myapp-xxx",
                    "count": 5,
                    "age": "2m",
                    "first_seen": "10m",
                }
            ]
        """
        events_list = []

        try:
            # Use cached API clients for better performance
            _, core_v1, _ = self._get_api_clients(stack)
            if not core_v1:
                return events_list

            events = core_v1.list_namespaced_event(
                namespace=namespace,
                _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
                limit=100,  # Fetch more, then filter
            )

            # Filter for warnings and errors, sort by last timestamp
            warning_events = []
            for event in events.items:
                if event.type in ["Warning", "Error"]:
                    last_time = event.last_timestamp or event.event_time or event.metadata.creation_timestamp
                    warning_events.append((last_time, event))

            # Sort by most recent first
            warning_events.sort(key=lambda x: x[0] if x[0] else datetime.min, reverse=True)

            for _, event in warning_events[:limit]:
                involved_obj = ""
                if event.involved_object:
                    involved_obj = f"{event.involved_object.kind}/{event.involved_object.name}"

                age = self._calculate_age(event.last_timestamp or event.event_time)
                first_seen = self._calculate_age(event.first_timestamp) if event.first_timestamp else age

                events_list.append(
                    {
                        "type": event.type,
                        "reason": event.reason or "Unknown",
                        "message": (event.message or "")[:200],  # Truncate long messages
                        "object": involved_obj,
                        "count": event.count or 1,
                        "age": age,
                        "first_seen": first_seen,
                    }
                )

            return events_list

        except ApiException as e:
            logger.warning("Failed to fetch events for %s/%s: %s", stack, namespace, e.status)
            return events_list
        except Exception as e:
            logger.error("Error fetching events: %s", e)
            return events_list

    def _fetch_namespace_details(self, stack: str, namespace_full: str) -> Dict:
        """
        Fetch pod restart counts and events for a namespace.
        Called in parallel with deployment fetches.

        Returns:
            Dict with restart_counts and events for the namespace
        """
        return {
            "namespace": namespace_full,
            "stack": stack,
            "restart_counts": self.get_pod_restart_counts(namespace_full, stack),
            "events": self.get_namespace_events(namespace_full, stack),
        }

    def get_resource_metrics(self, namespace: str, stack: str) -> Dict[str, Dict]:
        """
        Fetch CPU and Memory metrics for pods in a namespace.
        Requires metrics-server to be installed in the cluster.
        Uses cached API clients for better performance.

        Returns:
            Dict mapping pod name to resource metrics:
            {
                "pod-name": {
                    "cpu": {"usage": "100m", "percentage": 25},
                    "memory": {"usage": "256Mi", "percentage": 50}
                }
            }
        """
        metrics_data = {}

        try:
            # Use cached API clients for better performance
            _, _, api_client = self._get_api_clients(stack)
            if not api_client:
                return metrics_data

            # Call metrics API directly
            path = f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods"
            try:
                response = api_client.call_api(
                    path, "GET", auth_settings=["BearerToken"], response_type="object", _return_http_data_only=True
                )

                for item in response.get("items", []):
                    pod_name = item["metadata"]["name"]
                    containers = item.get("containers", [])

                    total_cpu = 0
                    total_memory = 0

                    for container in containers:
                        usage = container.get("usage", {})
                        cpu_str = usage.get("cpu", "0")
                        mem_str = usage.get("memory", "0")

                        # Parse CPU (convert to millicores)
                        if cpu_str.endswith("n"):
                            total_cpu += int(cpu_str[:-1]) / 1000000
                        elif cpu_str.endswith("m"):
                            total_cpu += int(cpu_str[:-1])
                        else:
                            total_cpu += int(cpu_str) * 1000

                        # Parse Memory (convert to Mi)
                        if mem_str.endswith("Ki"):
                            total_memory += int(mem_str[:-2]) / 1024
                        elif mem_str.endswith("Mi"):
                            total_memory += int(mem_str[:-2])
                        elif mem_str.endswith("Gi"):
                            total_memory += int(mem_str[:-2]) * 1024
                        else:
                            total_memory += int(mem_str) / (1024 * 1024)

                    metrics_data[pod_name] = {
                        "cpu": {
                            "usage": f"{int(total_cpu)}m",
                            "value_millicores": int(total_cpu),
                        },
                        "memory": {
                            "usage": f"{int(total_memory)}Mi",
                            "value_mb": int(total_memory),
                        },
                    }

            except ApiException as e:
                if e.status == 404:
                    logger.debug("Metrics server not available for %s/%s", stack, namespace)
                else:
                    logger.warning("Failed to fetch metrics for %s/%s: %s", stack, namespace, e.status)

            return metrics_data

        except Exception as e:
            logger.error("Error fetching resource metrics: %s", e)
            return metrics_data

    def get_pod_logs(self, namespace: str, pod_name: str, stack: str, container: str = None, lines: int = 50) -> Dict:
        """
        Fetch the last N lines of logs from a pod.
        Uses cached API clients for better performance.

        Args:
            namespace: Kubernetes namespace
            pod_name: Name of the pod
            stack: Stack identifier
            container: Container name (optional, auto-detects first container if not specified)
            lines: Number of lines to fetch (default 50)

        Returns:
            Dict with logs and metadata:
            {
                "pod": "pod-name",
                "container": "container-name",
                "lines": 50,
                "logs": "log line 1\nlog line 2\n...",
                "truncated": false
            }
        """
        try:
            # Use cached API clients for better performance
            _, core_v1, _ = self._get_api_clients(stack)
            if not core_v1:
                return {"error": "Failed to get API client"}

            # If no container specified, get the first container from the pod
            if not container:
                try:
                    pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                    if pod.spec and pod.spec.containers:
                        container = pod.spec.containers[0].name
                        logger.debug("Auto-detected container: %s for pod %s", container, pod_name)
                except ApiException:
                    pass  # Will try without container specification

            # Get logs - only pass container if we have one
            log_kwargs = {"name": pod_name, "namespace": namespace, "tail_lines": lines, "timestamps": True}
            if container:
                log_kwargs["container"] = container

            logs = core_v1.read_namespaced_pod_log(**log_kwargs)

            return {
                "pod": pod_name,
                "container": container,
                "namespace": namespace,
                "stack": stack,
                "lines": lines,
                "logs": logs,
                "truncated": len(logs.split("\n")) >= lines,
            }

        except ApiException as e:
            if e.status == 404:
                return {"error": f"Pod not found: {pod_name}"}
            elif e.status == 400:
                # Try to provide more helpful error
                return {"error": f"Bad request - check if pod '{pod_name}' exists and has containers"}
            else:
                return {"error": f"API error: {e.status}"}
        except Exception as e:
            logger.error("Error fetching pod logs: %s", e)
            return {"error": str(e)}

    def get_deployment_logs(self, namespace: str, deployment_name: str, stack: str, lines: int = 50) -> Dict:
        """
        Fetch logs from a deployment by finding its pods automatically.
        Useful for getting error logs without knowing specific pod names.

        Args:
            namespace: Kubernetes namespace (can be short key like '--addonman' or full)
            deployment_name: Name of the deployment
            stack: Stack identifier
            lines: Number of lines to fetch per pod (default 50)

        Returns:
            Dict with logs from all pods of the deployment:
            {
                "deployment": "deployment-name",
                "namespace": "namespace",
                "stack": "stack",
                "pods": [
                    {"name": "pod-1", "logs": "...", "status": "Running"},
                    {"name": "pod-2", "logs": "...", "status": "CrashLoopBackOff"}
                ],
                "total_pods": 2
            }
        """
        try:
            _, core_v1, apps_v1 = self._get_api_clients(stack)
            if not apps_v1 or not core_v1:
                return {"error": "Failed to get API client"}

            # Construct full namespace if needed
            # If namespace is a short key (like '--addonman' or 'enrollment-service'),
            # we need to construct the full namespace
            namespace_full = namespace
            if namespace in self.STANDALONE_NAMESPACES:
                namespace_full = namespace
            elif not namespace.startswith(stack):
                # Namespace is a short key, construct full namespace
                namespace_prefix = self._get_stack_namespace_prefix(stack)
                if namespace_prefix:
                    namespace_full = f"{namespace_prefix}{namespace}"

            logger.debug(
                "get_deployment_logs: namespace=%s -> namespace_full=%s, deployment=%s, stack=%s",
                namespace,
                namespace_full,
                deployment_name,
                stack,
            )

            # Get the deployment to find its label selector
            try:
                dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace_full)
            except ApiException as e:
                if e.status == 404:
                    return {"error": f"Deployment not found: {deployment_name} in namespace {namespace_full}"}
                return {"error": f"API error: {e.status}"}

            # Get pods for this deployment
            selector = dep.spec.selector.match_labels
            label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

            pods = core_v1.list_namespaced_pod(namespace=namespace_full, label_selector=label_selector)

            result = {
                "deployment": deployment_name,
                "namespace": namespace_full,
                "stack": stack,
                "pods": [],
                "total_pods": len(pods.items),
            }

            # Fetch logs from each pod (limit to first 3 pods for performance)
            for pod in pods.items[:3]:
                pod_name = pod.metadata.name
                pod_status = pod.status.phase if pod.status else "Unknown"

                # Check for crash loop
                if pod.status and pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.state and cs.state.waiting:
                            if cs.state.waiting.reason == "CrashLoopBackOff":
                                pod_status = "CrashLoopBackOff"
                                break

                # Get container name
                container = None
                if pod.spec and pod.spec.containers:
                    container = pod.spec.containers[0].name

                # Fetch logs
                try:
                    log_kwargs = {
                        "name": pod_name,
                        "namespace": namespace_full,
                        "tail_lines": lines,
                        "timestamps": True,
                    }
                    if container:
                        log_kwargs["container"] = container

                    logs = core_v1.read_namespaced_pod_log(**log_kwargs)

                    result["pods"].append(
                        {
                            "name": pod_name,
                            "status": pod_status,
                            "container": container,
                            "logs": logs,
                            "truncated": len(logs.split("\n")) >= lines,
                        }
                    )
                except ApiException as e:
                    result["pods"].append(
                        {
                            "name": pod_name,
                            "status": pod_status,
                            "container": container,
                            "logs": None,
                            "error": f"Failed to fetch logs: {e.reason}",
                        }
                    )

            return result

        except Exception as e:
            logger.error("Error fetching deployment logs: %s", e)
            return {"error": str(e)}

    def get_probe_status(self, namespace: str, deployment_name: str, stack: str) -> Dict:
        """
        Get readiness and liveness probe configuration and status for a deployment.
        Uses cached API clients for better performance.

        Returns:
            Dict with probe info:
            {
                "readiness": {
                    "configured": true,
                    "type": "httpGet",
                    "path": "/health",
                    "port": 8080,
                    "status": "passing"
                },
                "liveness": {
                    "configured": true,
                    "type": "tcpSocket",
                    "port": 8080,
                    "status": "passing"
                },
                "startup": {
                    "configured": false
                }
            }
        """
        probe_data = {
            "readiness": {"configured": False},
            "liveness": {"configured": False},
            "startup": {"configured": False},
        }

        try:
            # Use cached API clients for better performance
            apps_v1, core_v1, _ = self._get_api_clients(stack)
            if not apps_v1 or not core_v1:
                return probe_data

            # Get deployment
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
            )

            # Get container spec (use first container)
            containers = deployment.spec.template.spec.containers
            if not containers:
                return probe_data

            container = containers[0]

            # Extract probe configurations
            def extract_probe_info(probe, probe_type: str) -> Dict:
                if not probe:
                    return {"configured": False}

                info = {"configured": True}

                if probe.http_get:
                    info["type"] = "httpGet"
                    info["path"] = probe.http_get.path
                    info["port"] = probe.http_get.port
                elif probe.tcp_socket:
                    info["type"] = "tcpSocket"
                    info["port"] = probe.tcp_socket.port
                elif probe.exec:
                    info["type"] = "exec"
                    info["command"] = probe.exec.command
                elif probe.grpc:
                    info["type"] = "grpc"
                    info["port"] = probe.grpc.port

                info["initial_delay"] = probe.initial_delay_seconds or 0
                info["period"] = probe.period_seconds or 10
                info["timeout"] = probe.timeout_seconds or 1
                info["failure_threshold"] = probe.failure_threshold or 3

                return info

            probe_data["readiness"] = extract_probe_info(container.readiness_probe, "readiness")
            probe_data["liveness"] = extract_probe_info(container.liveness_probe, "liveness")
            probe_data["startup"] = extract_probe_info(container.startup_probe, "startup")

            # Get actual pod status to determine if probes are passing
            selector = deployment.spec.selector.match_labels
            label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

            pods = core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
            )

            # Check pod conditions for probe status
            all_ready = True
            for pod in pods.items:
                if pod.status and pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == "Ready" and condition.status != "True":
                            all_ready = False
                            break

            # Set status based on pod conditions
            if probe_data["readiness"]["configured"]:
                probe_data["readiness"]["status"] = "passing" if all_ready else "failing"
            if probe_data["liveness"]["configured"]:
                probe_data["liveness"]["status"] = "passing" if all_ready else "unknown"

            return probe_data

        except ApiException as e:
            logger.warning("Failed to fetch probe status for %s/%s: %s", stack, namespace, e.status)
            return probe_data
        except Exception as e:
            logger.error("Error fetching probe status: %s", e)
            return probe_data

    def save_snapshot(self) -> str:
        """
        Save current monitoring data as a historical snapshot.
        Called automatically after each data refresh.

        Returns:
            Snapshot filename
        """
        try:
            # Ensure snapshots directory exists
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

            # Generate snapshot filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_{timestamp}.json"
            filepath = SNAPSHOTS_DIR / filename

            # Prepare snapshot data
            snapshot = {"timestamp": datetime.now().isoformat(), "summary": self.get_stack_summary(), "deployments": []}

            # Collect deployment summaries (not full data to save space)
            for namespace, deps in self.master_config.items():
                for deployment, stacks in deps.items():
                    # Skip metadata entries (like _namespace_full)
                    if deployment.startswith("_"):
                        continue
                    dep_summary = {"namespace": namespace, "deployment": deployment, "stacks": {}}
                    for stack, data in stacks.items():
                        dep_summary["stacks"][stack] = {
                            "version": data.get("version"),
                            "status": data.get("status"),
                            "replicas": data.get("replicas"),
                            "restarts": data.get("restarts", 0),
                        }
                    snapshot["deployments"].append(dep_summary)

            # Write snapshot
            with open(filepath, "w") as f:
                json.dump(snapshot, f, indent=2)

            # Cleanup old snapshots (keep last 336 = 14 days of hourly snapshots)
            self._cleanup_old_snapshots(keep_count=336)

            logger.info("Saved snapshot: %s", filename)
            return filename

        except Exception as e:
            logger.error("Failed to save snapshot: %s", e)
            return ""

    def _cleanup_old_snapshots(self, keep_count: int = 336):
        """Remove old snapshots, keeping only the most recent ones (default: 14 days of hourly)."""
        try:
            snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_*.json"), reverse=True)
            for old_snapshot in snapshots[keep_count:]:
                old_snapshot.unlink()
                logger.debug("Removed old snapshot: %s", old_snapshot.name)
        except Exception as e:
            logger.error("Failed to cleanup snapshots: %s", e)

    def get_latest_snapshot_data(self) -> Optional[Dict]:
        """
        Get the most recent snapshot data.

        Returns:
            The latest snapshot dict with deployments data, or None if no snapshots exist.
        """
        try:
            if not SNAPSHOTS_DIR.exists():
                return None

            # Get the most recent snapshot file
            snapshot_files = sorted(SNAPSHOTS_DIR.glob("snapshot_*.json"), reverse=True)
            if not snapshot_files:
                return None

            latest_file = snapshot_files[0]
            with open(latest_file, "r") as f:
                snapshot = json.load(f)

            logger.debug("Loaded latest snapshot: %s", latest_file.name)
            return snapshot

        except Exception as e:
            logger.error("Failed to get latest snapshot: %s", e)
            return None

    def get_historical_data(self, hours: int = 24) -> List[Dict]:
        """
        Get historical snapshot data for trend analysis.

        Args:
            hours: Number of hours of history to retrieve (default 24)

        Returns:
            List of snapshots with summary data:
            [
                {
                    "timestamp": "2024-02-10T10:00:00",
                    "summary": {...},
                    "total_restarts": 5,
                    "healthy_count": 50,
                    "unhealthy_count": 2
                }
            ]
        """
        history = []

        try:
            if not SNAPSHOTS_DIR.exists():
                return history

            # Get snapshots within time range (hours=0 means all available)
            cutoff = datetime.now().timestamp() - (hours * 3600) if hours > 0 else 0

            for snapshot_file in sorted(SNAPSHOTS_DIR.glob("snapshot_*.json")):
                try:
                    # Check file modification time (skip filter when hours=0)
                    if cutoff > 0 and snapshot_file.stat().st_mtime < cutoff:
                        continue

                    with open(snapshot_file, "r") as f:
                        snapshot = json.load(f)

                    # Calculate aggregates
                    total_restarts = 0
                    healthy_count = 0
                    unhealthy_count = 0

                    for dep in snapshot.get("deployments", []):
                        for stack, data in dep.get("stacks", {}).items():
                            total_restarts += data.get("restarts", 0)
                            if data.get("status") == "healthy":
                                healthy_count += 1
                            elif data.get("status") and "unhealthy" in data.get("status", ""):
                                unhealthy_count += 1

                    history.append(
                        {
                            "timestamp": snapshot.get("timestamp"),
                            "summary": snapshot.get("summary", {}),
                            "total_restarts": total_restarts,
                            "healthy_count": healthy_count,
                            "unhealthy_count": unhealthy_count,
                        }
                    )

                except Exception as e:
                    logger.warning("Failed to read snapshot %s: %s", snapshot_file.name, e)

            return history

        except Exception as e:
            logger.error("Failed to get historical data: %s", e)
            return history

    def get_restart_timeline(self, namespace: str, deployment: str, stack: str) -> Dict:
        """
        Analyze restart history for a deployment from historical snapshots
        and fetch actual restart timestamp from live Kubernetes data.

        This method examines historical snapshots to determine:
        - When restarts first appeared (first non-zero count)
        - When restarts last increased (in our snapshots)
        - Whether restarts are ongoing or have stopped
        - The restart history over time

        It also fetches live K8s data to get the actual last restart time
        (last_restart_at) from container status, which is more accurate than
        snapshot-based detection.

        Args:
            namespace: Namespace key (e.g., "--addonman")
            deployment: Deployment name
            stack: Stack identifier (e.g., "stg01", "qa01")

        Returns:
            Dict with restart timeline information:
            {
                "current_restarts": 15,
                "first_seen_at": "2024-02-10T08:00:00",
                "last_increased_at": "2024-02-10T14:00:00",
                "last_restart_at": "2024-02-10T12:30:00",  # Actual K8s restart time
                "is_ongoing": True,
                "hours_since_last_increase": 2,
                "hours_since_last_restart": 3.5,
                "restart_history": [
                    {"timestamp": "...", "restarts": 0},
                    {"timestamp": "...", "restarts": 5},
                    ...
                ]
            }
        """
        timeline = {
            "namespace": namespace,
            "deployment": deployment,
            "stack": stack,
            "current_restarts": 0,
            "first_seen_at": None,
            "last_increased_at": None,
            "last_restart_at": None,  # Actual K8s restart timestamp
            "is_ongoing": False,
            "hours_since_last_increase": None,
            "hours_since_last_restart": None,
            "restart_history": [],
        }

        try:
            if not SNAPSHOTS_DIR.exists():
                return timeline

            restart_history = []
            prev_restarts = 0
            first_nonzero_timestamp = None
            last_increase_timestamp = None

            # Read all snapshots sorted by time (oldest first)
            for snapshot_file in sorted(SNAPSHOTS_DIR.glob("snapshot_*.json")):
                try:
                    with open(snapshot_file, "r") as f:
                        snapshot = json.load(f)

                    timestamp = snapshot.get("timestamp")

                    # Find the specific deployment in this snapshot
                    current_restarts = 0
                    for dep in snapshot.get("deployments", []):
                        if dep.get("namespace") == namespace and dep.get("deployment") == deployment:
                            stack_data = dep.get("stacks", {}).get(stack, {})
                            current_restarts = stack_data.get("restarts", 0)
                            break

                    # Track restart history
                    restart_history.append({"timestamp": timestamp, "restarts": current_restarts})

                    # Track when restarts first appeared
                    if current_restarts > 0 and first_nonzero_timestamp is None:
                        first_nonzero_timestamp = timestamp

                    # Track when restarts last increased
                    if current_restarts > prev_restarts:
                        last_increase_timestamp = timestamp

                    prev_restarts = current_restarts

                except Exception as e:
                    logger.warning("Failed to read snapshot %s for restart timeline: %s", snapshot_file.name, e)

            # Calculate hours since last increase
            hours_since_last_increase = None
            if last_increase_timestamp:
                try:
                    last_increase_dt = datetime.fromisoformat(last_increase_timestamp.replace("Z", "+00:00"))
                    if last_increase_dt.tzinfo:
                        last_increase_dt = last_increase_dt.replace(tzinfo=None)
                    hours_since_last_increase = round((datetime.now() - last_increase_dt).total_seconds() / 3600, 1)
                except Exception:
                    pass

            # Determine if restarts are ongoing
            # Ongoing = restart count increased AFTER first detection AND within last 2 hours
            # If first_seen_at == last_increased_at, it means no increase since first detected (stable)
            has_increased_since_first = (
                first_nonzero_timestamp is not None
                and last_increase_timestamp is not None
                and first_nonzero_timestamp != last_increase_timestamp
            )
            is_ongoing = (
                has_increased_since_first and hours_since_last_increase is not None and hours_since_last_increase < 2
            )

            timeline.update(
                {
                    "current_restarts": prev_restarts,
                    "first_seen_at": first_nonzero_timestamp,
                    "last_increased_at": last_increase_timestamp,
                    "is_ongoing": is_ongoing,
                    "hours_since_last_increase": hours_since_last_increase,
                    "restart_history": restart_history[-48:],  # Last 48 data points (48 hours if hourly)
                    "snapshots_analyzed": len(restart_history),
                    "data_available": len(restart_history) > 0,
                }
            )

            # Fetch actual last_restart_at from live K8s data
            # This gives the real timestamp when the container was last restarted,
            # as opposed to when our snapshot detected the change
            try:
                restart_data = self.get_pod_restart_counts(namespace, stack)
                if deployment in restart_data:
                    dep_data = restart_data[deployment]
                    last_restart_at = dep_data.get("last_restart_at")
                    if last_restart_at:
                        timeline["last_restart_at"] = last_restart_at
                        # Calculate hours since actual last restart
                        try:
                            restart_dt = datetime.fromisoformat(last_restart_at.replace("Z", "+00:00"))
                            if restart_dt.tzinfo:
                                restart_dt = restart_dt.replace(tzinfo=None)
                            hours_since_restart = round((datetime.now() - restart_dt).total_seconds() / 3600, 1)
                            timeline["hours_since_last_restart"] = hours_since_restart
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("Failed to fetch live K8s data for restart timeline: %s", e)

            return timeline

        except Exception as e:
            logger.error("Failed to get restart timeline: %s", e)
            return timeline

    def get_deployment_history(self, namespace: str, deployment: str, stack: str, hours: int = 24) -> Dict:
        """
        Get historical data for a specific deployment on a specific stack.

        Args:
            namespace: Namespace key (e.g., "--provisioner-pycore--support")
            deployment: Deployment name
            stack: Stack identifier (e.g., "stg01", "qa01")
            hours: Number of hours of history to retrieve (default 24, 0 = all)

        Returns:
            Dict with deployment-specific history:
            {
                "namespace": "--provisioner-pycore--support",
                "deployment": "provisioner-pycore-provisioner-pycore",
                "stack": "am2",
                "history": [
                    {
                        "timestamp": "2024-02-10T10:00:00",
                        "healthy_count": 3,
                        "unhealthy_count": 0,
                        "restarts": 5,
                        "status": "healthy",
                        "replicas": {"desired": 3, "ready": 3, "available": 3}
                    },
                    ...
                ],
                "summary": {
                    "data_points": 24,
                    "avg_healthy": 3,
                    "max_unhealthy": 1,
                    "total_restarts": 150,
                    "healthy_trend": +1,
                    "unhealthy_trend": 0
                }
            }
        """
        result = {
            "namespace": namespace,
            "deployment": deployment,
            "stack": stack,
            "history": [],
            "summary": {
                "data_points": 0,
                "avg_healthy": 0,
                "max_unhealthy": 0,
                "total_restarts": 0,
                "healthy_trend": 0,
                "unhealthy_trend": 0,
            },
        }

        try:
            if not SNAPSHOTS_DIR.exists():
                logger.warning("Snapshots directory does not exist: %s", SNAPSHOTS_DIR)
                return result

            cutoff = datetime.now().timestamp() - (hours * 3600) if hours > 0 else 0
            history = []

            # Normalize deployment name (remove container suffix for matching)
            deployment_base = deployment.split("/")[0] if "/" in deployment else deployment

            logger.debug(
                "Getting deployment history: namespace=%s, deployment=%s (base=%s), stack=%s, hours=%s",
                namespace,
                deployment,
                deployment_base,
                stack,
                hours,
            )

            for snapshot_file in sorted(SNAPSHOTS_DIR.glob("snapshot_*.json")):
                try:
                    if cutoff > 0 and snapshot_file.stat().st_mtime < cutoff:
                        continue

                    with open(snapshot_file, "r") as f:
                        snapshot = json.load(f)

                    timestamp = snapshot.get("timestamp")

                    # Find the specific deployment in this snapshot
                    for dep in snapshot.get("deployments", []):
                        dep_namespace = dep.get("namespace", "")
                        dep_deployment = dep.get("deployment", "")
                        dep_deployment_base = dep_deployment.split("/")[0] if "/" in dep_deployment else dep_deployment

                        # EXACT namespace match required - namespace must match exactly
                        # This ensures we only get data for the specific namespace instance
                        # (e.g., --provisioner-pycore--support, not all provisioner-pycore namespaces)
                        namespace_matches = dep_namespace == namespace

                        # Deployment match: either exact or base name match
                        deployment_matches = dep_deployment == deployment or dep_deployment_base == deployment_base

                        if namespace_matches and deployment_matches:
                            stack_data = dep.get("stacks", {}).get(stack, {})
                            if stack_data:
                                replicas = stack_data.get("replicas", {})
                                ready = replicas.get("ready", 0)
                                unavailable = replicas.get("unavailable", 0)

                                history.append(
                                    {
                                        "timestamp": timestamp,
                                        "healthy_count": ready,
                                        "unhealthy_count": unavailable,
                                        "restarts": stack_data.get("restarts", 0),
                                        "status": stack_data.get("status", "unknown"),
                                        "version": stack_data.get("version"),
                                        "replicas": replicas,
                                    }
                                )
                            break  # Found the deployment, move to next snapshot

                except Exception as e:
                    logger.warning("Failed to read snapshot %s for deployment history: %s", snapshot_file.name, e)

            if history:
                # Calculate summary statistics
                healthy_counts = [h["healthy_count"] for h in history]
                unhealthy_counts = [h["unhealthy_count"] for h in history]
                restarts = [h["restarts"] for h in history]

                result["history"] = history
                result["summary"] = {
                    "data_points": len(history),
                    "avg_healthy": round(sum(healthy_counts) / len(healthy_counts), 1) if healthy_counts else 0,
                    "max_unhealthy": max(unhealthy_counts) if unhealthy_counts else 0,
                    "total_restarts": max(restarts) if restarts else 0,  # Use max since restarts accumulate
                    "healthy_trend": healthy_counts[-1] - healthy_counts[0] if len(healthy_counts) >= 2 else 0,
                    "unhealthy_trend": unhealthy_counts[-1] - unhealthy_counts[0] if len(unhealthy_counts) >= 2 else 0,
                }
                logger.debug(
                    "Found %d history points for %s/%s on %s. Summary: avg_healthy=%s, total_restarts=%s",
                    len(history),
                    namespace,
                    deployment_base,
                    stack,
                    result["summary"]["avg_healthy"],
                    result["summary"]["total_restarts"],
                )
            else:
                logger.warning(
                    "No history found for namespace=%s, deployment=%s, stack=%s. "
                    "This may indicate the namespace key doesn't match snapshot data.",
                    namespace,
                    deployment_base,
                    stack,
                )

            return result

        except Exception as e:
            logger.error("Failed to get deployment history: %s", e)
            return result

    def get_deployment_details(self, namespace: str, deployment: str, stack: str, lite: bool = False) -> Dict:
        """
        Get detailed information for a specific deployment including
        resource metrics, probe status, and pod info.

        This is the main method for the side panel detail view.
        OPTIMIZED: Uses parallel API calls for faster loading.

        Args:
            namespace: Kubernetes namespace
            deployment: Deployment name (may include container name as "deployment/container")
            stack: Stack identifier (qa01, stg01, etc.)
            lite: If True, skip expensive calls (metrics, events) for faster response

        Returns:
            Comprehensive deployment details for the side panel
        """
        import time
        from concurrent.futures import ThreadPoolExecutor

        start_time = time.time()

        # Handle deployment name format: "deployment-name/container-name" -> "deployment-name"
        deployment_name = deployment.split("/")[0] if "/" in deployment else deployment

        details = {"namespace": namespace, "deployment": deployment_name, "stack": stack, "found": False}

        try:
            # Use cached API clients for better performance
            apps_v1, core_v1, api_client = self._get_api_clients(stack)
            if not apps_v1 or not core_v1:
                details["error"] = "Failed to get API client"
                return details

            # Get deployment - this must succeed first
            try:
                dep = apps_v1.read_namespaced_deployment(
                    name=deployment_name,
                    namespace=namespace,
                    _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
                )
                details["found"] = True
            except ApiException as e:
                if e.status == 404:
                    details["error"] = "Deployment not found"
                else:
                    details["error"] = f"API error: {e.status}"
                return details

            # Basic deployment info (from already-fetched deployment)
            details["replicas"] = {
                "desired": dep.status.replicas or 0,
                "ready": dep.status.ready_replicas or 0,
                "available": dep.status.available_replicas or 0,
                "unavailable": dep.status.unavailable_replicas or 0,
            }
            details["age"] = self._calculate_age(dep.metadata.creation_timestamp)
            details["created_at"] = (
                dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else None
            )

            # Container info (from already-fetched deployment)
            containers = dep.spec.template.spec.containers
            details["containers"] = []
            for c in containers:
                details["containers"].append(
                    {
                        "name": c.name,
                        "image": c.image,
                        "version": c.image.split(":")[-1] if ":" in c.image else "latest",
                    }
                )

            # Extract probe info directly from deployment spec (no extra API call needed)
            details["probes"] = self._extract_probes_from_deployment(dep)

            # Get pods - need label selector from deployment
            selector = dep.spec.selector.match_labels
            label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

            # Fetch pods synchronously (required for other operations)
            # This is fast and must complete before we know which pods to get metrics for
            pods = core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
            )

            # Process pods
            details["pods"] = []
            total_restarts = 0

            for pod in pods.items:
                pod_info = {
                    "name": pod.metadata.name,
                    "status": pod.status.phase if pod.status else "Unknown",
                    "restarts": 0,
                    "age": self._calculate_age(pod.metadata.creation_timestamp),
                    "node": pod.spec.node_name,
                    "ip": pod.status.pod_ip if pod.status else None,
                    "crash_loop": False,
                }

                if pod.status and pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        pod_info["restarts"] += cs.restart_count or 0
                        if cs.state and cs.state.waiting:
                            if cs.state.waiting.reason == "CrashLoopBackOff":
                                pod_info["crash_loop"] = True
                                pod_info["status"] = "CrashLoopBackOff"

                total_restarts += pod_info["restarts"]
                details["pods"].append(pod_info)

            details["total_restarts"] = total_restarts

            # For lite mode, skip expensive calls (metrics, events)
            if lite:
                details["resource_metrics"] = {}
                details["events"] = []
            else:
                # Fetch metrics and events in parallel using existing API clients (no kubeconfig reload)
                # api_client is already obtained from _get_api_clients above

                def fetch_metrics_inline():
                    """Fetch metrics using existing connection (no kubeconfig reload)."""
                    try:
                        path = f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods"
                        response = api_client.call_api(
                            path,
                            "GET",
                            auth_settings=["BearerToken"],
                            response_type="object",
                            _return_http_data_only=True,
                        )

                        metrics_data = {}
                        for item in response.get("items", []):
                            pod_name = item["metadata"]["name"]
                            containers = item.get("containers", [])

                            total_cpu = 0
                            total_memory = 0

                            for container in containers:
                                usage = container.get("usage", {})
                                cpu_str = usage.get("cpu", "0")
                                mem_str = usage.get("memory", "0")

                                # Parse CPU (convert to millicores)
                                if cpu_str.endswith("n"):
                                    total_cpu += int(cpu_str[:-1]) / 1000000
                                elif cpu_str.endswith("m"):
                                    total_cpu += int(cpu_str[:-1])
                                else:
                                    total_cpu += int(cpu_str) * 1000

                                # Parse Memory (convert to Mi)
                                if mem_str.endswith("Ki"):
                                    total_memory += int(mem_str[:-2]) / 1024
                                elif mem_str.endswith("Mi"):
                                    total_memory += int(mem_str[:-2])
                                elif mem_str.endswith("Gi"):
                                    total_memory += int(mem_str[:-2]) * 1024

                            metrics_data[pod_name] = {
                                "cpu": {"usage": f"{int(total_cpu)}m"},
                                "memory": {"usage": f"{int(total_memory)}Mi"},
                            }
                        return metrics_data
                    except Exception:
                        return {}

                def fetch_events_inline():
                    """Fetch events using existing connection (no kubeconfig reload)."""
                    try:
                        events = core_v1.list_namespaced_event(
                            namespace=namespace,
                            limit=50,
                            _request_timeout=(settings.k8s_connect_timeout, settings.k8s_read_timeout),
                        )

                        warning_events = []
                        for event in events.items:
                            if event.type in ["Warning", "Error"]:
                                last_time = (
                                    event.last_timestamp or event.event_time or event.metadata.creation_timestamp
                                )
                                warning_events.append((last_time, event))

                        warning_events.sort(key=lambda x: x[0] if x[0] else datetime.min, reverse=True)

                        events_list = []
                        for _, event in warning_events[:10]:
                            events_list.append(
                                {
                                    "type": event.type,
                                    "reason": event.reason,
                                    "message": event.message,
                                    "object": f"{event.involved_object.kind}/{event.involved_object.name}".lower(),
                                    "count": event.count or 1,
                                    "age": self._calculate_age(
                                        event.last_timestamp or event.metadata.creation_timestamp
                                    ),
                                }
                            )
                        return events_list
                    except Exception:
                        return []

                # Execute metrics and events in parallel
                with ThreadPoolExecutor(max_workers=2) as executor:
                    metrics_future = executor.submit(fetch_metrics_inline)
                    events_future = executor.submit(fetch_events_inline)

                    metrics = metrics_future.result()
                    events = events_future.result()

                details["resource_metrics"] = {}
                for pod in details["pods"]:
                    if pod["name"] in metrics:
                        details["resource_metrics"][pod["name"]] = metrics[pod["name"]]

                details["events"] = [
                    e
                    for e in events
                    if deployment in e.get("object", "")
                    or any(pod["name"] in e.get("object", "") for pod in details["pods"])
                ]

            elapsed = time.time() - start_time
            details["load_time_ms"] = int(elapsed * 1000)
            logger.info("Deployment details for %s/%s loaded in %.2fs", namespace, deployment_name, elapsed)

            return details

        except Exception as e:
            logger.error("Error getting deployment details: %s", e)
            details["error"] = str(e)
            return details

    def _extract_probes_from_deployment(self, dep) -> Dict:
        """Extract probe configuration directly from deployment spec (no API call needed)."""
        probes = {
            "readiness": {"configured": False},
            "liveness": {"configured": False},
            "startup": {"configured": False},
        }

        try:
            containers = dep.spec.template.spec.containers
            if not containers:
                return probes

            # Use first container's probes
            container = containers[0]

            if container.readiness_probe:
                probe = container.readiness_probe
                probes["readiness"] = {
                    "configured": True,
                    "type": self._get_probe_type(probe),
                    "initial_delay": probe.initial_delay_seconds,
                    "period": probe.period_seconds,
                    "timeout": probe.timeout_seconds,
                }

            if container.liveness_probe:
                probe = container.liveness_probe
                probes["liveness"] = {
                    "configured": True,
                    "type": self._get_probe_type(probe),
                    "initial_delay": probe.initial_delay_seconds,
                    "period": probe.period_seconds,
                    "timeout": probe.timeout_seconds,
                }

            if container.startup_probe:
                probe = container.startup_probe
                probes["startup"] = {
                    "configured": True,
                    "type": self._get_probe_type(probe),
                    "initial_delay": probe.initial_delay_seconds,
                    "period": probe.period_seconds,
                    "timeout": probe.timeout_seconds,
                }
        except Exception as e:
            logger.debug("Error extracting probes: %s", e)

        return probes

    def _get_probe_type(self, probe) -> str:
        """Determine probe type from probe spec."""
        if probe.http_get:
            return "httpGet"
        elif probe.tcp_socket:
            return "tcpSocket"
        elif probe.exec:
            return "exec"
        elif probe.grpc:
            return "grpc"
        return "unknown"

    # Keep old method for backward compatibility
    def get_image_tag(
        self, api_client: client.AppsV1Api, deployment_name: str, namespace: str
    ) -> List[Tuple[str, str, str]]:
        """
        Legacy method - fetches deployment image tag(s) and status.
        Returns: List of (deployment/container_name, version, status) tuples

        Deprecated: Use get_deployment_info() for richer data.
        """
        info_list = self.get_deployment_info(api_client, deployment_name, namespace)
        return [(info["name"], info["version"], info["status"]) for info in info_list]

    def _get_kubeconfig_path(self, stack: str) -> str:
        """
        Get kubeconfig file path for a stack.
        Returns empty string if not configured.

        Kubeconfig paths are auto-discovered from ~/.kube/rancher/ based on
        the kubeconfig_filename in the JSON config.
        """
        stack_config = self.STACK_CONFIG.get(stack, {})
        path = stack_config.get("kubeconfig_path", "")

        # Expand ~ to home directory if present
        if path:
            path = os.path.expanduser(path)
        return path

    def _load_kube_config_with_tls_skip(self, stack: str, context: str) -> bool:
        """
        Load kubeconfig with automatic TLS verification skip for Rancher clusters.
        Uses caching to avoid reloading the same config repeatedly.

        Returns:
            True if config loaded successfully, False otherwise
        """
        import time

        # Check if we recently loaded this kubeconfig (within cache TTL)
        cache_key = f"{stack}:{context}"
        current_time = time.time()

        with self._lock:
            cached_time = self._kubeconfig_cache.get(cache_key)
            if cached_time and (current_time - cached_time) < self._kubeconfig_cache_ttl:
                # Already loaded recently, just ensure SSL settings are correct
                configuration = client.Configuration.get_default_copy()
                configuration.verify_ssl = False
                configuration.assert_hostname = False
                client.Configuration.set_default(configuration)
                return True

        try:
            kubeconfig_file = self._get_kubeconfig_path(stack)

            if kubeconfig_file and os.path.exists(kubeconfig_file):
                config.load_kube_config(config_file=kubeconfig_file)
                logger.debug("Using kubeconfig file: %s", kubeconfig_file)
            else:
                config.load_kube_config(context=context)
                logger.debug("Using context from default kubeconfig: %s", context)

            # Disable SSL verification for Rancher clusters that use self-signed certs
            # This is safe for internal monitoring of known clusters
            configuration = client.Configuration.get_default_copy()
            configuration.verify_ssl = False
            # Also disable SSL warnings in the client
            configuration.assert_hostname = False
            client.Configuration.set_default(configuration)

            # Update cache
            with self._lock:
                self._kubeconfig_cache[cache_key] = current_time

            return True

        except config.ConfigException as e:
            error_msg = str(e)
            if "No configuration found" in error_msg or "Invalid kube-config" in error_msg:
                self._update_auth_status(
                    stack,
                    "config_missing",
                    "Kubeconfig not found. Run POST /api/rancher/kubeconfig/download-all to download from Rancher.",
                )
            else:
                self._update_auth_status(stack, "config_error", error_msg)
            return False
        except Exception as e:
            self._update_auth_status(stack, "config_error", str(e))
            return False

    def _update_auth_status(self, stack: str, status: str, message: str):
        """Update authentication status for a stack."""
        with self._lock:
            self._auth_status[stack] = {"status": status, "message": message, "timestamp": datetime.now().isoformat()}
            # Log warning only once per session
            if not self._auth_warned.get(stack):
                if status in ["auth_failed", "tls_error", "config_missing"]:
                    logger.warning("🔐 K8s auth issue for {stack}: %s", message)
                    self._auth_warned[stack] = True

    def _detect_auth_error(self, error: Exception, stack: str) -> str:
        """
        Detect the type of authentication error and provide actionable message.

        Returns:
            Error status string
        """
        error_str = str(error).lower()

        if "tls" in error_str or "certificate" in error_str or "ssl" in error_str:
            self._update_auth_status(
                stack,
                "tls_error",
                "TLS certificate verification failed. The kubeconfig needs 'insecure-skip-tls-verify: true' "
                "or the CA certificate needs to be trusted.",
            )
            return "tls_error"

        if "401" in error_str or "unauthorized" in error_str or "credentials" in error_str:
            self._update_auth_status(
                stack,
                "auth_failed",
                "Authentication token expired or invalid. Re-download kubeconfig from Rancher: "
                f"https://your-rancher.example.com → {self.CONTEXT_MAP.get(stack, stack)} → Kubeconfig File",
            )
            return "auth_failed"

        if "403" in error_str or "forbidden" in error_str:
            self._update_auth_status(
                stack, "forbidden", "Access denied. User lacks RBAC permissions for deployments. Contact cluster admin."
            )
            return "forbidden"

        if "timeout" in error_str or "connection" in error_str:
            self._update_auth_status(
                stack, "connection_error", "Cannot connect to Kubernetes cluster. Check network/VPN access."
            )
            return "connection_error"

        return "unknown_error"

    def _fetch_deployment(
        self, stack: str, context: str, namespace_key: str, namespace_full: str, deployment_name: str
    ) -> Dict:
        """
        Fetch a single deployment's data (used for parallel execution).
        Automatically handles TLS verification and auth errors.
        Uses cached API clients for better performance.

        Returns:
            Dict with namespace_key, namespace_full, stack, and deployments_info (rich deployment data)
        """
        try:
            # Use cached API clients for better performance
            apps_v1, _, _ = self._get_api_clients(stack)
            if not apps_v1:
                return {
                    "namespace_key": namespace_key,
                    "namespace_full": namespace_full,
                    "stack": stack,
                    "deployments_info": [
                        {
                            "name": deployment_name,
                            "version": "error",
                            "status": "config_error",
                            "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                            "age": "unknown",
                            "last_updated": None,
                            "created_at": None,
                            "image": None,
                        }
                    ],
                }

            deployments_info = self.get_deployment_info(apps_v1, deployment_name, namespace_full)

            # Check if we got auth errors in the result
            for info in deployments_info:
                if info["status"] == "auth_failed":
                    self._update_auth_status(
                        stack, "auth_failed", "Token expired. Re-download kubeconfig from Rancher."
                    )

            # Mark auth as successful if we got real data
            if deployments_info and deployments_info[0]["status"] not in ["auth_failed", "forbidden", "fetch_error"]:
                with self._lock:
                    if stack in self._auth_status and self._auth_status[stack].get("status") != "ok":
                        self._auth_status[stack] = {
                            "status": "ok",
                            "message": "Connected",
                            "timestamp": datetime.now().isoformat(),
                        }

            return {
                "namespace_key": namespace_key,
                "namespace_full": namespace_full,
                "stack": stack,
                "deployments_info": deployments_info,
            }

        except Exception as e:
            error_type = self._detect_auth_error(e, stack)
            logger.error("Error fetching {deployment_name} in {namespace_full} for {stack}: %s", e)
            return {
                "namespace_key": namespace_key,
                "namespace_full": namespace_full,
                "stack": stack,
                "deployments_info": [
                    {
                        "name": deployment_name,
                        "version": "error",
                        "status": error_type,
                        "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                        "age": "unknown",
                        "last_updated": None,
                        "created_at": None,
                        "image": None,
                    }
                ],
            }

    def _fetch_namespace_deployments(
        self, stack: str, context: str, namespace_key: str, namespace_full: str, deployment_names: List[str]
    ) -> Dict:
        """
        Fetch ALL deployments in a namespace with a SINGLE API call (batched fetch).
        Much faster than fetching each deployment individually.
        Uses cached API clients for better performance.

        Returns:
            Dict with namespace_key, namespace_full, stack, and deployments_info (list for all deployments)
        """
        try:
            # Use cached API clients for better performance
            apps_v1, _, _ = self._get_api_clients(stack)
            if not apps_v1:
                # Return error for all requested deployments
                return {
                    "namespace_key": namespace_key,
                    "namespace_full": namespace_full,
                    "stack": stack,
                    "deployments_info": [
                        {
                            "name": name,
                            "version": "error",
                            "status": "config_error",
                            "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                            "age": "unknown",
                            "last_updated": None,
                            "created_at": None,
                            "image": None,
                        }
                        for name in deployment_names
                    ],
                }

            # SINGLE API call to get all deployments in namespace
            all_deployments = self.get_all_deployments_in_namespace(apps_v1, namespace_full, deployment_names)

            # Flatten results into single list
            all_deployments_info = []
            for deployment_name, deployment_info_list in all_deployments.items():
                all_deployments_info.extend(deployment_info_list)

                # Check for auth errors
                for info in deployment_info_list:
                    if info["status"] == "auth_failed":
                        self._update_auth_status(
                            stack, "auth_failed", "Token expired. Re-download kubeconfig from Rancher."
                        )

            # Mark auth as successful if we got real data
            if all_deployments_info and all_deployments_info[0]["status"] not in [
                "auth_failed",
                "forbidden",
                "fetch_error",
            ]:
                with self._lock:
                    if stack in self._auth_status and self._auth_status[stack].get("status") != "ok":
                        self._auth_status[stack] = {
                            "status": "ok",
                            "message": "Connected",
                            "timestamp": datetime.now().isoformat(),
                        }

            return {
                "namespace_key": namespace_key,
                "namespace_full": namespace_full,
                "stack": stack,
                "deployments_info": all_deployments_info,
            }

        except Exception as e:
            error_type = self._detect_auth_error(e, stack)
            logger.error("Error fetching deployments in %s for %s: %s", namespace_full, stack, e)
            return {
                "namespace_key": namespace_key,
                "namespace_full": namespace_full,
                "stack": stack,
                "deployments_info": [
                    {
                        "name": name,
                        "version": "error",
                        "status": error_type,
                        "replicas": {"desired": 0, "ready": 0, "available": 0, "unavailable": 0, "updated": 0},
                        "age": "unknown",
                        "last_updated": None,
                        "created_at": None,
                        "image": None,
                    }
                    for name in deployment_names
                ],
            }

    def generate_stack_config(
        self,
        stacks: Optional[List[str]] = None,
        use_cache: bool = True,
        lite_mode: bool = False,
        background_refresh: bool = False,
    ) -> Dict:
        """
        Generates the master configuration with deployment versions across stacks.
        Uses parallel execution and caching for better performance.

        Args:
            stacks: List of stack names to monitor (e.g., ["qa01", "stg01"])
                   If None, monitors all stacks in CONTEXT_MAP
            use_cache: If True, return cached data if available and fresh
            lite_mode: If True, skip fetching events and restart counts (faster)
            background_refresh: If True, trigger async refresh but return stale data

        Returns:
            Dict with structure:
            {
                "namespace": {
                    "deployment/container": {
                        "qa01": {"version": "...", "status": "..."},
                        "stg01": {"version": "...", "status": "..."}
                    }
                }
            }
        """
        # Check cache
        if use_cache and self._cache is not None and self._cache_timestamp is not None:
            age = (datetime.now() - self._cache_timestamp).total_seconds()
            if age < self._cache_ttl:
                logger.info("Returning cached data (age: %.1fs)", age)
                return self._cache

            # Stale-while-revalidate: Return stale data but trigger background refresh
            # Cache is expired but we have data - return it immediately for fast response
            if background_refresh and self._cache is not None:
                logger.info("Returning stale data (age: %.1fs) - will refresh in background", age)
                # TODO: In production, trigger async refresh here
                # For now, we just return stale data on first call, fresh on next
                return self._cache

        logger.info("🚀 Starting parallel stack monitoring (cache miss or expired, lite_mode=%s)", lite_mode)
        start_time = datetime.now()

        self.master_config = {}

        if stacks is None:
            stacks = list(self.CONTEXT_MAP.keys())

        # PRE-LOAD all kubeconfigs in parallel to avoid per-request loading
        # This significantly speeds up the main parallel execution
        logger.info("Pre-loading kubeconfigs for %d stacks...", len(stacks))
        preload_start = datetime.now()

        valid_stacks = []
        for stack in stacks:
            context = self.CONTEXT_MAP.get(stack)
            if not context:
                logger.warning("Unknown stack: %s", stack)
                continue
            # Pre-load kubeconfig (will be cached)
            if self._load_kube_config_with_tls_skip(stack, context):
                valid_stacks.append(stack)
            else:
                logger.warning("Failed to load kubeconfig for stack: %s", stack)

        preload_time = (datetime.now() - preload_start).total_seconds()
        logger.info("Kubeconfig preload completed in %.2fs for %d stacks", preload_time, len(valid_stacks))

        # Build BATCHED tasks - one API call per (stack, namespace) instead of per deployment
        # This dramatically reduces the number of K8s API calls
        namespace_batch_tasks = []  # (stack, context, namespace_key, namespace_full, [deployment_names])

        for stack in valid_stacks:
            context = self.CONTEXT_MAP.get(stack)

            # Get namespace prefix from JSON config (e.g., 'stg01-mp', 'qa01-mp-npe', 'sjc1c4-mp-prod')
            namespace_prefix = self._get_stack_namespace_prefix(stack)

            if not namespace_prefix:
                # Fallback for stacks not in JSON config
                logger.debug("No namespace prefix for %s, using fallback", stack)
                namespace_prefix = f"{stack}-mp"

            # Use full DEPLOYMENT_MAP for all stacks
            # This queries ALL possible namespaces - ones that don't exist will be marked 'not_found'
            # and filtered out in the frontend. This is safer than relying on incomplete JSON configs.
            is_vm_based = self._is_vm_based_stack(stack)

            for namespace_key, deployments in self.DEPLOYMENT_MAP.items():
                # Skip clientstatus namespace for VM-based stacks (AM2, FR4, SV5)
                # These stacks don't have clientstatus pods
                if is_vm_based and namespace_key == "--clientstatus":
                    logger.debug("Skipping clientstatus namespace for VM-based stack %s", stack)
                    continue

                # Build full namespace name
                if namespace_key not in self.STANDALONE_NAMESPACES:
                    # Stack-specific namespaces: {prefix}{namespace_key}
                    # e.g., stg01-mp--addonman, sjc1c4-mp-prod--addonman
                    namespace_full = f"{namespace_prefix}{namespace_key}"
                else:
                    # Standalone namespaces (same across all stacks)
                    namespace_full = namespace_key

                # BATCH: Add all deployments in namespace as single task
                namespace_batch_tasks.append((stack, context, namespace_key, namespace_full, deployments))

        # Build unique namespace list for fetching restart counts and events
        # Skip in lite_mode for faster initial load
        namespace_tasks = set()
        if not lite_mode:
            for stack, context, namespace_key, namespace_full, _ in namespace_batch_tasks:
                namespace_tasks.add((stack, namespace_full))

        logger.info(
            "Executing %s batched namespace tasks + %s restart/event tasks in parallel... (lite_mode=%s)",
            len(namespace_batch_tasks),
            len(namespace_tasks),
            lite_mode,
        )

        # Storage for namespace details (restart counts, events)
        namespace_details = {}

        # Execute all tasks in parallel using ThreadPoolExecutor
        # max_workers is configurable via K8S_MAX_WORKERS (default: 30)
        # Lower values reduce connection pool exhaustion on Rancher proxies
        with ThreadPoolExecutor(max_workers=settings.k8s_max_workers) as executor:
            # Submit BATCHED deployment fetch tasks (one per namespace, not per deployment)
            # This reduces API calls from N*M to N (where N=stacks, M=deployments per namespace)
            future_to_task = {
                executor.submit(
                    self._fetch_namespace_deployments, stack, context, namespace_key, namespace_full, deployments
                ): ("deployment", stack, namespace_key, deployments)
                for stack, context, namespace_key, namespace_full, deployments in namespace_batch_tasks
            }

            # Submit namespace detail tasks (restart counts + events) - skip in lite mode
            if not lite_mode:
                for stack, namespace_full in namespace_tasks:
                    future = executor.submit(self._fetch_namespace_details, stack, namespace_full)
                    future_to_task[future] = ("namespace_details", stack, namespace_full, None)

            # Collect results as they complete with per-task timeout
            # This prevents slow clusters from blocking the entire fetch
            completed = 0
            timed_out = 0
            total_tasks = len(future_to_task)
            task_timeout = settings.k8s_read_timeout + 10  # Per-task timeout (read timeout + buffer)
            overall_timeout = 150  # Max time to wait for all tasks (leave buffer for router's 180s)

            try:
                for future in as_completed(future_to_task, timeout=overall_timeout):
                    completed += 1
                    if completed % 20 == 0:
                        logger.info("Progress: %s/%s tasks completed (%s timed out)", completed, total_tasks, timed_out)

                    try:
                        task_type = future_to_task[future][0]

                        if task_type == "deployment":
                            result = future.result(timeout=task_timeout)
                            namespace_key = result["namespace_key"]
                            namespace_full = result.get("namespace_full", namespace_key)
                            stack = result["stack"]
                            deployments_info = result["deployments_info"]

                            # Initialize namespace in master config
                            with self._lock:
                                if namespace_key not in self.master_config:
                                    self.master_config[namespace_key] = {"_namespace_full": {}}

                                # Store rich deployment data
                                for info in deployments_info:
                                    full_name = info["name"]
                                    if full_name not in self.master_config[namespace_key]:
                                        self.master_config[namespace_key][full_name] = {}

                                    if stack not in self.master_config[namespace_key][full_name]:
                                        self.master_config[namespace_key][full_name][stack] = {}

                                    # Store all deployment info (version, status, replicas, age, etc.)
                                    self.master_config[namespace_key][full_name][stack] = {
                                        "version": info["version"],
                                        "status": info["status"],
                                        "replicas": info["replicas"],
                                        "age": info["age"],
                                        "last_updated": info["last_updated"],
                                        "created_at": info["created_at"],
                                        "image": info["image"],
                                    }

                                # Store the full namespace for each stack
                                self.master_config[namespace_key]["_namespace_full"][stack] = namespace_full

                        elif task_type == "namespace_details":
                            result = future.result(timeout=task_timeout)
                            ns_key = f"{result['stack']}:{result['namespace']}"
                            with self._lock:
                                namespace_details[ns_key] = {
                                    "restart_counts": result["restart_counts"],
                                    "events": result["events"],
                                }

                    except TimeoutError:
                        task_info = future_to_task[future]
                        timed_out += 1
                        logger.warning("Task timed out after %ss for %s", task_timeout, task_info[1:3])
                    except Exception as e:
                        task_info = future_to_task[future]
                        logger.error("Task failed for %s: %s", task_info, e)

            except TimeoutError:
                # Overall timeout hit - some tasks didn't complete
                remaining = total_tasks - completed
                timed_out += remaining
                logger.warning(
                    "Overall timeout after %ss - %s/%s tasks completed, %s skipped",
                    overall_timeout,
                    completed,
                    total_tasks,
                    remaining,
                )

        # Merge restart counts and error info into deployment data
        for namespace_key, deployments in self.master_config.items():
            for deployment_name, stack_data in deployments.items():
                # Skip metadata entries (like _namespace_full)
                if deployment_name.startswith("_"):
                    continue
                for stack, data in stack_data.items():
                    # Find the namespace details for this stack
                    # Build possible namespace keys to check
                    for ns_key, ns_data in namespace_details.items():
                        if ns_key.startswith(f"{stack}:") and namespace_key in ns_key:
                            restart_info = ns_data.get("restart_counts", {})
                            # Match deployment name (without container suffix)
                            base_deployment = deployment_name.split("/")[0]
                            if base_deployment in restart_info:
                                data["restarts"] = restart_info[base_deployment]["total_restarts"]
                                data["crash_loop"] = restart_info[base_deployment]["crash_loop"]
                                # Add error info if available
                                if restart_info[base_deployment].get("error_reason"):
                                    data["error_reason"] = restart_info[base_deployment]["error_reason"]
                                    data["error_message"] = restart_info[base_deployment]["error_message"]
                                # Add actual error occurrence timestamp
                                if restart_info[base_deployment].get("error_occurred_at"):
                                    data["error_occurred_at"] = restart_info[base_deployment]["error_occurred_at"]
                            break

        # Store namespace events separately for the API response
        self._namespace_events = namespace_details

        elapsed = (datetime.now() - start_time).total_seconds()
        if timed_out > 0:
            logger.warning(
                "⚠️ Stack monitoring completed in %.2fs (%s/%s tasks, %s timed out)",
                elapsed,
                completed,
                total_tasks,
                timed_out,
            )
        else:
            logger.info("✅ Stack monitoring completed in %.2fs (%s tasks)", elapsed, total_tasks)

        # Update cache
        with self._lock:
            self._cache = self.master_config
            self._cache_timestamp = datetime.now()

        return self.master_config

    def get_stack_summary(self) -> Dict:
        """
        Generate a summary of stack health.

        NOTE: Deployments with status "not_found" are excluded from counts.
        These represent hardcoded deployment names that don't exist in all stacks.

        Returns:
            Dict with counts of healthy, warning, critical, and not_found deployments per stack
        """
        # Dynamically initialize summary for all configured stacks
        summary = {
            stack_id: {"total": 0, "healthy": 0, "warning": 0, "critical": 0, "not_found": 0, "restarts": 0}
            for stack_id in self.CONTEXT_MAP.keys()
        }

        # Use try/except to handle "dictionary changed during iteration" gracefully
        # This avoids taking a lock which could cause deadlocks with async code
        try:
            master_config_items = list(self.master_config.items())
        except RuntimeError:
            # Dictionary changed during iteration - return current summary (partial data)
            logger.warning("master_config changed during get_stack_summary, returning partial data")
            return summary

        for namespace, deployments in master_config_items:
            try:
                deployment_items = list(deployments.items())
            except RuntimeError:
                continue  # Skip this namespace if dict changed

            for deployment, stacks in deployment_items:
                # Skip metadata entries (like _namespace_full)
                if deployment.startswith("_"):
                    continue

                try:
                    stack_items = list(stacks.items()) if isinstance(stacks, dict) else []
                except (RuntimeError, AttributeError):
                    continue  # Skip if dict changed or not a dict

                for stack, data in stack_items:
                    if stack not in summary:
                        # Auto-add stacks found in data but not in config
                        summary[stack] = {
                            "total": 0,
                            "healthy": 0,
                            "warning": 0,
                            "critical": 0,
                            "not_found": 0,
                            "restarts": 0,
                        }

                    status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
                    is_crash_loop = data.get("crash_loop", False) if isinstance(data, dict) else False
                    restarts = data.get("restarts", 0) if isinstance(data, dict) else 0

                    # Track restarts per stack
                    summary[stack]["restarts"] += restarts

                    # Skip NOT_FOUND deployments from main counts - these are config mismatches
                    # Track them separately for debugging but don't count as warnings
                    if status == "not_found":
                        summary[stack]["not_found"] += 1
                        continue  # Don't add to total or other counts

                    summary[stack]["total"] += 1

                    # CrashLoopBackOff deployments are critical regardless of status
                    if is_crash_loop:
                        summary[stack]["critical"] += 1
                    elif status == "healthy":
                        summary[stack]["healthy"] += 1
                    elif "unhealthy" in status or "error" in status:
                        summary[stack]["critical"] += 1
                    else:
                        summary[stack]["warning"] += 1

        return summary

    # NPE stacks to exclude from version comparisons
    # These are development environments that can have any version
    NPE_STACKS = {"npa01", "npe01", "npe02"}

    # Legacy stacks to exclude from all version comparisons
    # These stacks are on older versions and don't follow the standard release cycle
    LEGACY_STACKS = {"stg01-mplegacy", "stg01_mplegacy"}

    # VM-based production stacks that don't have certain Kubernetes deployments
    # These stacks run on VMs and don't have clientstatus pods
    VM_BASED_STACKS = {"am2", "fr4", "sv5"}

    # Deployments that don't exist on VM-based stacks
    # These should be excluded from version compliance checks for VM-based stacks
    VM_BASED_EXCLUDED_DEPLOYMENTS = {
        "clientstatus-clientstatus",
        "clientstatus-clientasyncstatus",
    }

    # Stack categorization for milestone-based comparison
    # Production stacks are grouped by deployment day for accurate version drift detection
    # Note: stg01-mplegacy is excluded from comparisons via LEGACY_STACKS
    STACK_CATEGORIES = {
        "npe": ["npa01", "npe01", "npe02"],
        "qa": ["qa01"],
        "staging": ["stg01", "fed1mp", "stg01-mp", "fed1-mp", "betaskope"],
        "preprod": ["devint", "fed-preprod", "fedpreprod", "fed02-mp-preprod", "fed02mppreprod", "fed02"],
        # Production stacks grouped by deployment day
        "prod_day1": ["sin2", "fr4"],
        "prod_day2": ["am2", "ruh1", "zur2"],
        "prod_day3": ["fra2", "lon3", "mel2", "dfw3", "sjc2"],
        "prod_day4": ["sv5", "sjc1"],
        # FedRAMP/PBMM stacks (follow their own schedule, typically aligned with Day 4)
        "prod_fedramp": ["fedramp", "fed-prod", "pbmm", "pbmm-prod"],
    }

    # Milestone to stack category mapping - defines when each category should have the new version
    # Each prod day milestone maps to its corresponding stack group
    # NOTE: QA is NOT included here because QA01 is always on develop branch (N+1),
    # not tied to any specific milestone. QA expected version is calculated separately.
    MILESTONE_TO_CATEGORY = {
        "Signoff STG/FedAlpha - ENG": "staging",
        "Deploy MP Pre PROD": "preprod",
        "Deploy Prod Day 1": "prod_day1",
        "Deploy Prod Day 2": "prod_day2",
        "Deploy Prod Day 3": "prod_day3",
        "Deploy Prod Day 4": "prod_day4",
    }

    def _get_stack_category(self, stack_id: str) -> str:
        """
        Determine the category of a stack.

        Categories:
        - npe: Development environments (npa01, npe01, npe02)
        - qa: QA environments (qa01)
        - staging: Staging environments (stg01, fed1mp, etc.)
        - preprod: Pre-production (devint, fed-preprod, etc.)
        - prod_day1: Production Day 1 stacks (SIN2, FR4)
        - prod_day2: Production Day 2 stacks (AM2, RUH1, ZUR2)
        - prod_day3: Production Day 3 stacks (FRA2, LON3, MEL2, DFW3, SJC2)
        - prod_day4: Production Day 4 stacks (SV5, SJC1)
        - prod_fedramp: FedRAMP/PBMM stacks
        """
        if not stack_id:
            return "unknown"

        normalized = stack_id.lower().replace("-", "").replace("_", "")
        original = stack_id.lower()

        for category, stacks in self.STACK_CATEGORIES.items():
            for pattern in stacks:
                normalized_pattern = pattern.replace("-", "").replace("_", "")
                if normalized == normalized_pattern or normalized.startswith(normalized_pattern):
                    return category
                if original == pattern or original.startswith(pattern):
                    return category

        # Fallback: check production patterns and assign to appropriate day
        # This handles variations like "pe-sin2", "mp-prod-sin2", etc.
        prod_day1_patterns = ["sin2", "fr4"]
        prod_day2_patterns = ["am2", "ruh1", "zur2"]
        prod_day3_patterns = ["fra2", "lon3", "mel2", "dfw3", "sjc2"]
        prod_day4_patterns = ["sv5", "sjc1"]
        prod_fedramp_patterns = ["fedramp", "fed-prod", "pbmm"]

        for pattern in prod_day1_patterns:
            if pattern in original:
                return "prod_day1"
        for pattern in prod_day2_patterns:
            if pattern in original:
                return "prod_day2"
        for pattern in prod_day3_patterns:
            if pattern in original:
                return "prod_day3"
        for pattern in prod_day4_patterns:
            if pattern in original:
                return "prod_day4"
        for pattern in prod_fedramp_patterns:
            if pattern in original:
                return "prod_fedramp"

        return "unknown"

    def _is_vm_based_stack(self, stack_id: str) -> bool:
        """
        Check if a stack is VM-based (not running on Kubernetes for all services).

        VM-based stacks don't have certain Kubernetes deployments like clientstatus pods.
        """
        if not stack_id:
            return False

        normalized = stack_id.lower().replace("-", "").replace("_", "")
        for vm_stack in self.VM_BASED_STACKS:
            vm_normalized = vm_stack.replace("-", "").replace("_", "")
            if normalized == vm_normalized or vm_normalized in normalized:
                return True
        return False

    def _get_active_milestones(self) -> Dict[str, Dict]:
        """
        Get active milestones based on current date from release calendar.
        Returns dict mapping category to expected version info.

        Special handling for QA stacks:
        - QA01 is always on the develop branch, which is N+1 (one major version ahead of STG01)
        - N = the release version that has reached Branch Cut milestone (what STG01 should have)
        - QA01 should have N+1 (develop branch version)
        - Example: If R137 has reached Branch Cut, STG01 should have R137, QA01 should have R138
        """
        try:
            from services.release_calendar_parser import get_release_calendar_data

            calendar_data = get_release_calendar_data()
            releases = calendar_data.get("releases", [])

            if not releases:
                return {}

            # Use PST timezone for date comparisons to ensure consistent behavior
            today = datetime.now(PST_TIMEZONE).date()
            active_milestones = {}

            # Track the latest release that has reached Branch Cut (for QA N+1 calculation)
            branch_cut_release_info = None

            for release in releases:
                release_name = release.get("name", "")
                milestones = release.get("milestones", {})

                # Extract version prefix from release name (e.g., R137.0 -> 137.0)
                version_prefix = release_name.upper().replace("R", "").strip()
                parts = version_prefix.split(".")
                if len(parts) >= 2:
                    version_prefix = f"{parts[0]}.{parts[1]}"
                elif parts:
                    version_prefix = parts[0]

                # Check Branch Cut milestone to track N for QA calculation
                branch_cut_date_str = milestones.get("Branch Cut - EP", "-")
                if branch_cut_date_str != "-":
                    try:
                        branch_cut_date = datetime.strptime(branch_cut_date_str, "%d-%b-%Y").date()
                        if today >= branch_cut_date:
                            # Track the latest release that has reached Branch Cut
                            if branch_cut_release_info is None or branch_cut_date > branch_cut_release_info["date"]:
                                branch_cut_release_info = {
                                    "release": release_name,
                                    "version_prefix": version_prefix,
                                    "date": branch_cut_date,
                                    "date_str": branch_cut_date_str,
                                }
                    except ValueError:
                        pass

                # Check each milestone (excludes QA - handled separately below)
                for milestone_name, category in self.MILESTONE_TO_CATEGORY.items():
                    milestone_date_str = milestones.get(milestone_name, "-")
                    if milestone_date_str == "-":
                        continue

                    try:
                        milestone_date = datetime.strptime(milestone_date_str, "%d-%b-%Y").date()

                        # If milestone date has passed, this category should have this version
                        if today >= milestone_date:
                            # Store the latest milestone that has passed for each category
                            if (
                                category not in active_milestones
                                or milestone_date > active_milestones[category]["date"]
                            ):
                                active_milestones[category] = {
                                    "release": release_name,
                                    "version_prefix": version_prefix,
                                    "milestone": milestone_name,
                                    "date": milestone_date,
                                    "date_str": milestone_date_str,
                                }
                    except ValueError:
                        logger.warning("Invalid date format for %s: %s", milestone_name, milestone_date_str)

            # QA stacks: Always on develop branch (N+1)
            # N = the release version that has reached Branch Cut (what STG01 should have)
            # QA01 should have N+1 (one version ahead of STG01)
            if branch_cut_release_info:
                try:
                    # Extract major version from the release that reached Branch Cut
                    branch_cut_version = branch_cut_release_info["version_prefix"]
                    major_version = int(branch_cut_version.split(".")[0])  # e.g., 137
                    develop_version = major_version + 1  # e.g., 138

                    active_milestones["qa"] = {
                        "release": f"R{develop_version}.0 (develop)",
                        "version_prefix": str(develop_version),
                        "milestone": "Develop Branch (N+1)",
                        "date": branch_cut_release_info["date"],
                        "date_str": branch_cut_release_info["date_str"],
                        "note": f"QA01 runs on develop branch, N+1 from Branch Cut release R{major_version}",
                    }
                    logger.info(
                        "QA expected version set to develop branch: R%s (N+1 from Branch Cut release R%s)",
                        develop_version,
                        major_version,
                    )
                except (ValueError, IndexError) as e:
                    logger.warning("Could not calculate develop branch version for QA: %s", e)

            return active_milestones

        except Exception as e:
            logger.error("Error getting active milestones: %s", e)
            return {}

    def invalidate_cache(self):
        """Invalidate the cache to force a fresh fetch on next request."""
        with self._lock:
            self._cache = None
            self._cache_timestamp = None
        logger.info("Cache invalidated")

    def get_cache_age(self) -> Optional[float]:
        """Get the age of the current cache in seconds, or None if no cache."""
        if self._cache_timestamp is None:
            return None
        return (datetime.now() - self._cache_timestamp).total_seconds()

    def get_auth_status(self) -> Dict[str, Dict]:
        """
        Get authentication status for all stacks.

        Returns:
            Dict with auth status per stack, including actionable error messages
        """
        return self._auth_status.copy()

    def has_auth_errors(self) -> bool:
        """Check if any stack has authentication errors."""
        for stack, status in self._auth_status.items():
            if status.get("status") not in ["ok", None]:
                return True
        return False

    def get_formatted_data(self, refresh: bool = False) -> Dict:
        """
        Get formatted data for the dashboard API.

        Args:
            refresh: If True, bypass cache and fetch fresh data

        Returns:
            Dict with stacks, deployments, summary, metadata, and auth status
        """
        # If refresh requested, invalidate cache first
        if refresh:
            self.invalidate_cache()
            # Also reset auth warnings to re-check
            self._auth_warned = {}

        # Ensure we have data (will use cache if available)
        if not self.master_config or refresh:
            self.generate_stack_config(use_cache=not refresh)

        summary = self.get_stack_summary()

        # Format deployments for frontend
        # Use try/except to handle concurrent modifications gracefully
        deployments = []
        try:
            master_config_items = list(self.master_config.items())
        except RuntimeError:
            master_config_items = []

        for namespace_key, deps in master_config_items:
            # Get the namespace_full mapping for this namespace_key
            namespace_full_map = deps.get("_namespace_full", {}) if isinstance(deps, dict) else {}

            try:
                deps_items = list(deps.items()) if isinstance(deps, dict) else []
            except RuntimeError:
                continue

            for deployment, stacks in deps_items:
                # Skip metadata entries
                if deployment.startswith("_"):
                    continue

                # Add full namespace info for each stack
                stacks_with_namespace = {}
                try:
                    stacks_items = list(stacks.items()) if isinstance(stacks, dict) else []
                except RuntimeError:
                    continue

                for stack, data in stacks_items:
                    stacks_with_namespace[stack] = {
                        **(data if isinstance(data, dict) else {}),
                        "namespace_full": namespace_full_map.get(stack, namespace_key),
                    }

                deployment_data = {
                    "namespace": namespace_key,
                    "deployment": deployment,
                    "stacks": stacks_with_namespace,
                }
                deployments.append(deployment_data)

        cache_age = self.get_cache_age()

        # Determine overall status based on auth and deployment health
        overall_status = "operational"
        status_message = None

        if self.has_auth_errors():
            # Check what type of auth errors we have
            auth_status = self.get_auth_status()
            error_types = [s.get("status") for s in auth_status.values() if s.get("status") not in ["ok", None]]

            if "auth_failed" in error_types:
                overall_status = "auth_failed"
                status_message = (
                    "Kubernetes authentication failed. Token may be expired. " "Re-download kubeconfig from Rancher UI."
                )
            elif "tls_error" in error_types:
                overall_status = "tls_error"
                status_message = (
                    "TLS certificate verification failed. "
                    "Add 'insecure-skip-tls-verify: true' to kubeconfig cluster section."
                )
            elif "config_missing" in error_types:
                overall_status = "config_missing"
                status_message = (
                    "Kubeconfig not found. Run POST /api/rancher/kubeconfig/download-all to download from Rancher."
                )
            elif "connection_error" in error_types:
                overall_status = "connection_error"
                status_message = "Cannot connect to Kubernetes cluster. Check network/VPN access."
            else:
                overall_status = "partial_error"
                status_message = "Some stacks have errors. Check auth_status for details."

        # Build stacks metadata for frontend (region, description, etc.)
        stacks_meta = {}
        for stack_id, stack_cfg in self.STACK_CONFIG.items():
            stacks_meta[stack_id] = {
                "region": stack_cfg.get("region", "Unknown"),
                "description": stack_cfg.get("description", f"{stack_id.upper()} Stack"),
            }

        # Aggregate events by stack for frontend
        events_by_stack = {}
        for ns_key, ns_data in self._namespace_events.items():
            stack = ns_key.split(":")[0]
            if stack not in events_by_stack:
                events_by_stack[stack] = []
            events_by_stack[stack].extend(ns_data.get("events", []))

        # Sort events by most recent and limit to top 10 per stack
        for stack in events_by_stack:
            events_by_stack[stack] = sorted(
                events_by_stack[stack],
                key=lambda e: e.get("age", "999d"),
            )[:10]

        # Count total restarts and crash loops
        total_restarts = 0
        crash_loop_count = 0
        try:
            for namespace, deps in list(self.master_config.items()):
                if not isinstance(deps, dict):
                    continue
                for deployment, stacks_data in list(deps.items()):
                    # Skip metadata entries (like _namespace_full)
                    if deployment.startswith("_"):
                        continue
                    if not isinstance(stacks_data, dict):
                        continue
                    for stack, data in list(stacks_data.items()):
                        if isinstance(data, dict):
                            total_restarts += data.get("restarts", 0)
                            if data.get("crash_loop"):
                                crash_loop_count += 1
        except RuntimeError:
            pass  # Ignore if dict changed during iteration

        return {
            "status": overall_status,
            "status_message": status_message,
            "timestamp": get_current_time_formatted(),
            "summary": summary,
            "deployments": deployments,
            "total_deployments": len(deployments),
            "cache_age_seconds": cache_age,
            "cached": cache_age is not None and cache_age < self._cache_ttl,
            "auth_status": self.get_auth_status(),
            "source": (
                "kubernetes-live"
                if not self.has_auth_errors()
                else ("error" if overall_status == "config_missing" else "kubernetes-partial")
            ),
            "stacks_meta": stacks_meta,  # Stack metadata for frontend
            "events_by_stack": events_by_stack,  # Warning/error events per stack
            "total_restarts": total_restarts,  # Total pod restarts across all deployments
            "crash_loop_count": crash_loop_count,  # Number of deployments in CrashLoopBackOff
        }


# Singleton instance
_monitoring_service = None


def get_monitoring_service() -> StackMonitoringService:
    """Get or create the monitoring service singleton."""
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = StackMonitoringService()
    return _monitoring_service

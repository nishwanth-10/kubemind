"""
KubeMind — Multi-Cluster Connection Manager
Manages multiple Kubernetes cluster connections, agent registrations, and heartbeat tracking.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kubernetes import client, config as k8s_config

logger = logging.getLogger("kubemind.cluster_manager")


class ClusterConnection:
    """Represents a single cluster's K8s API connection."""

    def __init__(self, cluster_id: str, name: str, provider: str = "unknown", org_id: str = None):
        self.cluster_id = cluster_id
        self.name = name
        self.provider = provider  # minikube, eks, aks, gke, k3s, etc.
        self.org_id = org_id
        self.core_v1: Optional[client.CoreV1Api] = None
        self.apps_v1: Optional[client.AppsV1Api] = None
        self.custom: Optional[client.CustomObjectsApi] = None
        self.net_v1: Optional[client.NetworkingV1Api] = None
        self.connected = False
        self.last_heartbeat: float = 0
        self.agent_connected = False
        self.agent_version: str = ""
        self.error: str = ""

    def init_from_kubeconfig(self, kubeconfig_path: Optional[str] = None):
        """Initialize K8s clients from kubeconfig file."""
        try:
            if kubeconfig_path:
                k8s_config.load_kube_config(config_file=kubeconfig_path)
            else:
                try:
                    k8s_config.load_incluster_config()
                    logger.info(f"Cluster {self.cluster_id}: loaded in-cluster config")
                except Exception:
                    k8s_config.load_kube_config()
                    logger.info(f"Cluster {self.cluster_id}: loaded local kubeconfig")

            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.custom = client.CustomObjectsApi()
            self.net_v1 = client.NetworkingV1Api()
            self.connected = True
            self.last_heartbeat = time.time()
            self.error = ""
            logger.info(f"✅ Cluster {self.name} ({self.cluster_id}) connected")
        except Exception as e:
            self.connected = False
            self.error = str(e)
            logger.error(f"Cluster {self.cluster_id} connection failed: {e}")

    def update_heartbeat(self):
        self.last_heartbeat = time.time()
        self.agent_connected = True

    @property
    def is_healthy(self) -> bool:
        if self.agent_connected:
            return time.time() - self.last_heartbeat < 60  # 60s timeout
        return self.connected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "provider": self.provider,
            "org_id": self.org_id,
            "connected": self.connected,
            "agent_connected": self.agent_connected,
            "agent_version": self.agent_version,
            "is_healthy": self.is_healthy,
            "last_heartbeat": datetime.fromtimestamp(
                self.last_heartbeat, tz=timezone.utc
            ).isoformat() if self.last_heartbeat else None,
            "error": self.error,
        }


class ClusterManager:
    """Manages all cluster connections."""

    def __init__(self):
        self._clusters: Dict[str, ClusterConnection] = {}
        self._default_id: Optional[str] = None

    def register_cluster(
        self,
        cluster_id: str,
        name: str,
        provider: str = "unknown",
        kubeconfig_path: Optional[str] = None,
    ) -> ClusterConnection:
        """Register and connect a new cluster."""
        conn = ClusterConnection(cluster_id, name, provider)
        if kubeconfig_path:
            conn.init_from_kubeconfig(kubeconfig_path)
        self._clusters[cluster_id] = conn
        if not self._default_id:
            self._default_id = cluster_id
        return conn

    def register_agent_cluster(
        self, cluster_id: str, name: str, provider: str = "agent", org_id: str = None
    ) -> ClusterConnection:
        """Register a cluster that will be fed by an agent (no direct K8s API)."""
        conn = ClusterConnection(cluster_id, name, provider)
        conn.agent_connected = True
        conn.last_heartbeat = time.time()
        conn.org_id = org_id
        self._clusters[cluster_id] = conn
        if not self._default_id:
            self._default_id = cluster_id
        return conn

    def get_cluster(self, cluster_id: str) -> Optional[ClusterConnection]:
        return self._clusters.get(cluster_id)

    def get_cluster_dict(self, cluster_id: str) -> Dict:
        conn = self._clusters.get(cluster_id)
        return conn.to_dict() if conn else {}

    def get_default_cluster(self) -> Optional[ClusterConnection]:
        if self._default_id:
            return self._clusters.get(self._default_id)
        if self._clusters:
            first = next(iter(self._clusters))
            return self._clusters[first]
        return None

    def get_all_clusters(self) -> List[Dict]:
        return [c.to_dict() for c in self._clusters.values()]

    def remove_cluster(self, cluster_id: str):
        if cluster_id in self._clusters:
            del self._clusters[cluster_id]
            if self._default_id == cluster_id:
                self._default_id = next(iter(self._clusters), None)

    def update_agent_heartbeat(self, cluster_id: str, agent_info: Dict = None):
        conn = self._clusters.get(cluster_id)
        if conn:
            conn.update_heartbeat()
            if agent_info:
                conn.agent_version = agent_info.get("version", "")
                conn.provider = agent_info.get("provider", conn.provider)

    @property
    def cluster_count(self) -> int:
        return len(self._clusters)

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self._clusters.values() if c.is_healthy)

    def init_default_cluster(self):
        """Initialize a default cluster from local kubeconfig (for backward compat)."""
        from app.core.auth import generate_cluster_id
        cid = generate_cluster_id()
        conn = self.register_cluster(cid, "Local Cluster", "local")
        conn.init_from_kubeconfig()
        return conn


# Global singleton
cluster_manager = ClusterManager()

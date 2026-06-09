"""
KubeMind — Real-Time Kubernetes Metrics Collector
Replaces simulator.py entirely. Pulls live data from:
  - Kubernetes Metrics API (kubectl top)
  - Prometheus PromQL
  - kube_state_metrics / CoreV1Api / AppsV1Api
"""
import asyncio
import concurrent.futures
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

logger = logging.getLogger("kubemind.collector")

# ── K8s client initialization ────────────────────────────────────────────────
_k8s_initialized = False
_k8s_reachable = True
_k8s_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_K8S_TIMEOUT = (5, 10)  # (connect_seconds, read_seconds)
_core_v1: Optional[client.CoreV1Api] = None
_apps_v1: Optional[client.AppsV1Api] = None
_custom: Optional[client.CustomObjectsApi] = None
_net_v1: Optional[client.NetworkingV1Api] = None


def _init_k8s():
    global _k8s_initialized, _core_v1, _apps_v1, _custom, _net_v1
    if _k8s_initialized:
        return
    try:
        k8s_config.load_incluster_config()
        logger.info("K8s: loaded in-cluster config")
    except Exception:
        try:
            k8s_config.load_kube_config()
            logger.info("K8s: loaded local kubeconfig")
        except Exception as e:
            logger.error(f"K8s config failed: {e}")
            return
    cfg = client.Configuration.get_default_copy()
    cfg.connect_timeout = 5
    cfg.read_timeout = 10
    cfg.retries = 0
    cfg._request_timeout = (5, 10)
    client.Configuration.set_default(cfg)
    _core_v1 = client.CoreV1Api()
    _apps_v1 = client.AppsV1Api()
    _custom  = client.CustomObjectsApi()
    _net_v1  = client.NetworkingV1Api()
    _k8s_initialized = True


# ── In-memory metric history (same shape as old simulator) ───────────────────
_metric_history: Dict[str, List[Dict]] = {}
_last_snapshot: List[Dict[str, Any]] = []
_last_summary: Dict[str, Any] = {}
_collection_lock = asyncio.Lock()

# ── Prometheus URL (read at import time, updated by collector) ───────────────
_PROMETHEUS_URL = "http://localhost:9090"


def set_prometheus_url(url: str):
    global _PROMETHEUS_URL
    _PROMETHEUS_URL = url.rstrip("/")


# ── Prometheus PromQL helper ─────────────────────────────────────────────────
async def _prom_query(query: str, session: aiohttp.ClientSession) -> List[Dict]:
    try:
        url = f"{_PROMETHEUS_URL}/api/v1/query"
        async with session.get(url, params={"query": query}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return []
            j = await resp.json()
            return j.get("data", {}).get("result", [])
    except Exception as e:
        logger.debug(f"Prometheus query failed [{query}]: {e}")
        return []


def _prom_value(result: List[Dict], labels: Dict[str, str]) -> Optional[float]:
    """Find first matching result by label subset."""
    for r in result:
        lbs = r.get("metric", {})
        if all(lbs.get(k) == v for k, v in labels.items()):
            try:
                return float(r["value"][1])
            except Exception:
                pass
    return None


# ── Collect Metrics API (kubectl top pods) ───────────────────────────────────
def _collect_metrics_api() -> Dict[str, Dict]:
    """Returns {pod_name: {cpu_nano: int, mem_bytes: int}}"""
    if not _custom:
        return {}
    pod_metrics: Dict[str, Dict] = {}
    try:
        res = _custom.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="pods",
            _request_timeout=_K8S_TIMEOUT,
        )
        for item in res.get("items", []):
            name = item["metadata"]["name"]
            ns   = item["metadata"]["namespace"]
            containers = item.get("containers", [])
            cpu_sum = 0
            mem_sum = 0
            for c in containers:
                usage = c.get("usage", {})
                cpu_str = usage.get("cpu", "0n")
                mem_str = usage.get("memory", "0Ki")
                # Parse CPU (nanocores)
                if cpu_str.endswith("n"):
                    cpu_sum += int(cpu_str[:-1])
                elif cpu_str.endswith("m"):
                    cpu_sum += int(float(cpu_str[:-1]) * 1_000_000)
                else:
                    try:
                        cpu_sum += int(float(cpu_str) * 1_000_000_000)
                    except Exception:
                        pass
                # Parse memory
                if mem_str.endswith("Ki"):
                    mem_sum += int(mem_str[:-2]) * 1024
                elif mem_str.endswith("Mi"):
                    mem_sum += int(mem_str[:-2]) * 1024 * 1024
                elif mem_str.endswith("Gi"):
                    mem_sum += int(float(mem_str[:-2]) * 1024 * 1024 * 1024)
                elif mem_str.endswith("k"):
                    mem_sum += int(mem_str[:-1]) * 1000
                else:
                    try:
                        mem_sum += int(mem_str)
                    except Exception:
                        pass
            pod_metrics[f"{ns}/{name}"] = {"cpu_nano": cpu_sum, "mem_bytes": mem_sum}
    except ApiException as e:
        logger.warning(f"Metrics API unavailable: {e.status} — ensure metrics-server is running")
    except Exception as e:
        logger.warning(f"Metrics API error: {e}")
    return pod_metrics


def _collect_node_metrics() -> Dict[str, Dict]:
    """Returns {node_name: {cpu_nano, mem_bytes, cpu_capacity_nano, mem_capacity_bytes}}"""
    if not _custom or not _core_v1:
        return {}
    node_m: Dict[str, Dict] = {}
    try:
        res = _custom.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes",
            _request_timeout=_K8S_TIMEOUT,
        )
        for item in res.get("items", []):
            name = item["metadata"]["name"]
            usage = item.get("usage", {})
            cpu_str = usage.get("cpu", "0n")
            mem_str = usage.get("memory", "0Ki")
            cpu_nano = int(cpu_str[:-1]) if cpu_str.endswith("n") else 0
            mem_bytes = int(mem_str[:-2]) * 1024 if mem_str.endswith("Ki") else 0
            node_m[name] = {"cpu_nano": cpu_nano, "mem_bytes": mem_bytes}
        # Add capacity from node objects
        nodes = _core_v1.list_node(_request_timeout=_K8S_TIMEOUT)
        for node in nodes.items:
            n = node.metadata.name
            alloc = node.status.allocatable or {}
            cap   = node.status.capacity or {}
            cpu_cap_str = alloc.get("cpu", "1")
            mem_cap_str = alloc.get("memory", "1Ki")
            try:
                cpu_cap_nano = int(float(cpu_cap_str) * 1_000_000_000)
            except Exception:
                cpu_cap_nano = 1_000_000_000
            if mem_cap_str.endswith("Ki"):
                mem_cap = int(mem_cap_str[:-2]) * 1024
            elif mem_cap_str.endswith("Mi"):
                mem_cap = int(mem_cap_str[:-2]) * 1024 * 1024
            elif mem_cap_str.endswith("Gi"):
                mem_cap = int(float(mem_cap_str[:-2]) * 1024 * 1024 * 1024)
            else:
                mem_cap = 4 * 1024 * 1024 * 1024
            if n not in node_m:
                node_m[n] = {"cpu_nano": 0, "mem_bytes": 0}
            node_m[n]["cpu_capacity_nano"] = cpu_cap_nano
            node_m[n]["mem_capacity_bytes"] = mem_cap
    except Exception as e:
        logger.warning(f"Node metrics error: {e}")
    return node_m


# ── Collect pod list from CoreV1Api ─────────────────────────────────────────
def _collect_pods() -> List[Dict]:
    if not _core_v1:
        return []
    pods = []
    try:
        pod_list = _core_v1.list_pod_for_all_namespaces(watch=False, _request_timeout=_K8S_TIMEOUT)
        for pod in pod_list.items:
            meta = pod.metadata
            spec = pod.spec
            status = pod.status
            # Restart count (sum all containers)
            restart_count = 0
            container_statuses = status.container_statuses or []
            oom_killed = False
            crash_loop = False
            for cs in container_statuses:
                restart_count += cs.restart_count or 0
                last_state = cs.last_state
                if last_state and last_state.terminated:
                    if last_state.terminated.reason == "OOMKilled":
                        oom_killed = True
                state = cs.state
                if state and state.waiting:
                    if "CrashLoopBackOff" in (state.waiting.reason or ""):
                        crash_loop = True

            # Ready containers
            ready = sum(1 for cs in container_statuses if cs.ready)
            total_containers = len(spec.containers) if spec.containers else 1

            # Pod phase / status string
            phase = status.phase or "Unknown"
            pod_status = "Running"
            if crash_loop:
                pod_status = "CrashLoopBackOff"
            elif oom_killed:
                pod_status = "OOMKilled"
            elif phase in ("Failed", "Unknown"):
                pod_status = phase
            elif phase == "Pending":
                pod_status = "Pending"

            # Node
            node_name = spec.node_name or "unscheduled"

            # Labels
            labels = meta.labels or {}

            pods.append({
                "name": meta.name,
                "namespace": meta.namespace,
                "node_name": node_name,
                "phase": phase,
                "status": pod_status,
                "restart_count": restart_count,
                "ready_containers": ready,
                "total_containers": total_containers,
                "oom_killed": oom_killed,
                "crash_loop": crash_loop,
                "labels": labels,
                "creation_timestamp": meta.creation_timestamp,
            })
    except Exception as e:
        logger.error(f"Pod listing error: {e}")
    return pods


# ── Collect deployments ───────────────────────────────────────────────────────
def _collect_deployments() -> List[Dict]:
    if not _apps_v1:
        return []
    deps = []
    try:
        dep_list = _apps_v1.list_deployment_for_all_namespaces(watch=False, _request_timeout=_K8S_TIMEOUT)
        for dep in dep_list.items:
            meta = dep.metadata
            spec = dep.spec
            status = dep.status
            deps.append({
                "name": meta.name,
                "namespace": meta.namespace,
                "replicas": spec.replicas or 1,
                "ready_replicas": status.ready_replicas or 0,
                "available_replicas": status.available_replicas or 0,
                "selector": spec.selector.match_labels if spec.selector else {},
                "labels": meta.labels or {},
            })
    except Exception as e:
        logger.warning(f"Deployment listing error: {e}")
    return deps


# ── Collect services ─────────────────────────────────────────────────────────
def _collect_services() -> List[Dict]:
    if not _core_v1:
        return []
    svcs = []
    try:
        svc_list = _core_v1.list_service_for_all_namespaces(watch=False, _request_timeout=_K8S_TIMEOUT)
        for svc in svc_list.items:
            meta = svc.metadata
            spec = svc.spec
            svcs.append({
                "name": meta.name,
                "namespace": meta.namespace,
                "selector": spec.selector or {},
                "type": spec.type or "ClusterIP",
                "labels": meta.labels or {},
            })
    except Exception as e:
        logger.warning(f"Service listing error: {e}")
    return svcs


# ── Collect PVCs ─────────────────────────────────────────────────────────────
def _collect_pvcs() -> List[Dict]:
    if not _core_v1:
        return []
    pvcs = []
    try:
        pvc_list = _core_v1.list_persistent_volume_claim_for_all_namespaces(watch=False, _request_timeout=_K8S_TIMEOUT)
        for pvc in pvc_list.items:
            meta = pvc.metadata
            spec = pvc.spec
            status = pvc.status
            storage_req = "0"
            if spec.resources and spec.resources.requests:
                storage_req = spec.resources.requests.get("storage", "0")
            pvcs.append({
                "name": meta.name,
                "namespace": meta.namespace,
                "phase": status.phase or "Unknown",
                "storage_request": storage_req,
            })
    except Exception as e:
        logger.warning(f"PVC listing error: {e}")
    return pvcs


# ── Collect events ───────────────────────────────────────────────────────────
def _collect_events() -> List[Dict]:
    if not _core_v1:
        return []
    events = []
    try:
        ev_list = _core_v1.list_event_for_all_namespaces(watch=False, _request_timeout=_K8S_TIMEOUT)
        for ev in ev_list.items:
            if ev.type != "Warning":
                continue
            events.append({
                "namespace": ev.metadata.namespace,
                "name": ev.metadata.name,
                "reason": ev.reason or "",
                "message": ev.message or "",
                "involved_object": ev.involved_object.name if ev.involved_object else "",
                "involved_kind": ev.involved_object.kind if ev.involved_object else "",
                "count": ev.count or 1,
                "first_time": str(ev.first_timestamp) if ev.first_timestamp else "",
                "last_time": str(ev.last_timestamp) if ev.last_timestamp else "",
            })
    except Exception as e:
        logger.warning(f"Events listing error: {e}")
    return events


# ── Build live topology ──────────────────────────────────────────────────────
def _build_topology(deployments: List[Dict], services: List[Dict], pods: List[Dict]) -> Dict[str, Any]:
    """
    Build nodes from deployments/pods and infer links from shared namespaces
    and label selectors. This builds a real dependency graph.
    """
    nodes = []
    links = []

    # Group by namespace
    ns_deps: Dict[str, List[str]] = {}
    for dep in deployments:
        ns = dep["namespace"]
        ns_deps.setdefault(ns, []).append(dep["name"])
        nodes.append({
            "id": dep["name"],
            "namespace": ns,
            "domain": ns,
            "replicas": dep["replicas"],
            "ready_replicas": dep["ready_replicas"],
            "type": "deployment",
        })

    # Services that have selectors can link to deployments
    for svc in services:
        ns = svc["namespace"]
        selector = svc["selector"]
        if not selector:
            continue
        # Find deployments in same namespace whose pod template labels match
        matching = []
        for dep in deployments:
            if dep["namespace"] != ns:
                continue
            dep_sel = dep.get("selector", {})
            if dep_sel and all(selector.get(k) == v for k, v in dep_sel.items() if k in selector):
                matching.append(dep["name"])
        # Cross-namespace links: skip for now (ingress-level)

    # Intra-namespace dependency links (services within same NS calling each other)
    # We link all deployments in same namespace that have >1 sibling
    for ns, dep_names in ns_deps.items():
        if len(dep_names) < 2:
            continue
        # Create a simple chain for visualization: first → rest
        for i in range(1, len(dep_names)):
            links.append({"source": dep_names[0], "target": dep_names[i]})

    return {"nodes": nodes, "links": links}


# ── Main async collection function ───────────────────────────────────────────
async def _async_collect_prometheus(pod_keys: List[str]) -> Dict[str, Dict]:
    """Query Prometheus for network + PVC metrics."""
    prom_data: Dict[str, Dict] = {k: {} for k in pod_keys}
    try:
        async with aiohttp.ClientSession() as session:
            # Network RX
            net_rx_res = await _prom_query(
                'sum(rate(container_network_receive_bytes_total[1m])) by (pod, namespace)', session
            )
            # Network TX
            net_tx_res = await _prom_query(
                'sum(rate(container_network_transmit_bytes_total[1m])) by (pod, namespace)', session
            )
            # PVC usage %
            pvc_res = await _prom_query(
                '(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) * 100', session
            )

            for r in net_rx_res:
                pod = r["metric"].get("pod", "")
                ns  = r["metric"].get("namespace", "")
                key = f"{ns}/{pod}"
                if key in prom_data:
                    try:
                        prom_data[key]["net_rx_kbps"] = float(r["value"][1]) / 1024
                    except Exception:
                        pass

            for r in net_tx_res:
                pod = r["metric"].get("pod", "")
                ns  = r["metric"].get("namespace", "")
                key = f"{ns}/{pod}"
                if key in prom_data:
                    try:
                        prom_data[key]["net_tx_kbps"] = float(r["value"][1]) / 1024
                    except Exception:
                        pass

            for r in pvc_res:
                ns  = r["metric"].get("namespace", "")
                pod = r["metric"].get("pod", "")
                key = f"{ns}/{pod}"
                if key in prom_data:
                    try:
                        prom_data[key]["pvc_usage_percent"] = float(r["value"][1])
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"Prometheus async collect error: {e}")
    return prom_data


# ── Unified generate_all_metrics ─────────────────────────────────────────────
async def collect_all_metrics() -> List[Dict[str, Any]]:
    global _k8s_reachable
    if not _k8s_reachable:
        return []

    loop = asyncio.get_running_loop()
    _init_k8s()

    pods, deployments, services, events, pod_metrics = await asyncio.gather(
        loop.run_in_executor(_k8s_executor, _collect_pods),
        loop.run_in_executor(_k8s_executor, _collect_deployments),
        loop.run_in_executor(_k8s_executor, _collect_services),
        loop.run_in_executor(_k8s_executor, _collect_events),
        loop.run_in_executor(_k8s_executor, _collect_metrics_api),
    )

    # If all K8s calls returned empty, cluster is unreachable
    if not pods and not deployments and not services and not events and not pod_metrics:
        if _k8s_reachable:
            _k8s_reachable = False
            logger.warning("K8s cluster unreachable — disabling collector")
        return []

    # Build event index by involved object name
    event_index: Dict[str, List[Dict]] = {}
    for ev in events:
        obj = ev["involved_object"]
        event_index.setdefault(obj, []).append(ev)

    # Async Prometheus
    pod_keys = [f"{p['namespace']}/{p['name']}" for p in pods]
    prom_data = await _async_collect_prometheus(pod_keys)

    # CPU capacity per node (for % calculation)
    # We approximate: 1 CPU core = 1_000_000_000 nanocores
    # If metrics API returns nanocores, divide by capacity_nano (or assume 2 cores)
    DEFAULT_CPU_CAP_NANO = 2_000_000_000  # 2 cores

    metrics_list = []
    ts = datetime.now(timezone.utc).isoformat()

    for pod in pods:
        ns   = pod["namespace"]
        name = pod["name"]
        key  = f"{ns}/{name}"

        raw = pod_metrics.get(key, {})
        prom = prom_data.get(key, {})

        cpu_nano  = raw.get("cpu_nano", 0)
        mem_bytes = raw.get("mem_bytes", 0)

        cpu_percent = round((cpu_nano / DEFAULT_CPU_CAP_NANO) * 100, 2)
        memory_mb   = round(mem_bytes / (1024 * 1024), 1)

        # Memory limit: approximate 512MB per container if not available
        mem_limit_mb = max(memory_mb * 2, 256)

        net_in  = round(prom.get("net_rx_kbps", 0), 1)
        net_out = round(prom.get("net_tx_kbps", 0), 1)
        pvc_pct = round(prom.get("pvc_usage_percent", 0), 1)

        # Get deployment info for this pod
        pod_labels = pod.get("labels", {})
        dep_info = None
        for dep in deployments:
            if dep["namespace"] == ns:
                dep_sel = dep.get("selector", {})
                if dep_sel and all(pod_labels.get(k) == v for k, v in dep_sel.items()):
                    dep_info = dep
                    break

        replicas       = dep_info["replicas"]       if dep_info else 1
        ready_replicas = dep_info["ready_replicas"] if dep_info else (1 if pod["status"] == "Running" else 0)

        # Pod events
        pod_events = event_index.get(name, [])

        # Latency: approximate from Prometheus (use 0 if unavailable)
        latency_ms = round(prom.get("latency_ms", 0), 1)

        dep_name = dep_info["name"] if dep_info else name

        m = {
            # Identity
            "service":     dep_name,
            "pod_name":    name,
            "deployment":  dep_name,
            "namespace":   ns,
            "node_name":   pod["node_name"],
            "domain":      ns,
            "timestamp":   ts,
            # Status
            "status":      pod["status"],
            "phase":       pod["phase"],
            "replicas":    replicas,
            "ready_replicas": ready_replicas,
            "container_count": pod["total_containers"],
            # CPU / Memory
            "cpu_percent":       cpu_percent,
            "memory_mb":         memory_mb,
            "memory_limit_mb":   mem_limit_mb,
            # Network
            "network_in_kbps":  net_in,
            "network_out_kbps": net_out,
            # Disk / PVC
            "disk_usage_percent": pvc_pct,
            "pvc_usage_percent":  pvc_pct,
            # Restarts
            "restart_count":    pod["restart_count"],
            "oom_killed":       pod["oom_killed"],
            "crash_loop":       pod["crash_loop"],
            # Latency
            "latency_ms":       latency_ms,
            "error_rate_percent": 0.0,
            # Events
            "events": pod_events[:5],
            # Misc (kept for UI compat)
            "active_fault":  None,
            "dependencies":  [],
            "image":         "",
        }

        # Update in-memory history
        if key not in _metric_history:
            _metric_history[key] = []
        _metric_history[key].append({
            "cpu_percent": cpu_percent,
            "memory_mb":   memory_mb,
            "latency_ms":  latency_ms,
            "ts":          time.time(),
        })
        if len(_metric_history[key]) > 120:
            _metric_history[key].pop(0)

        metrics_list.append(m)

    return metrics_list


def get_metric_history(service: str, limit: int = 60) -> List[Dict]:
    # Try exact key first, then suffix match
    for key in _metric_history:
        if key.endswith(f"/{service}") or key == service:
            return _metric_history[key][-limit:]
    return []


def get_cluster_summary(metrics: Optional[List[Dict]] = None) -> Dict[str, Any]:
    if metrics is None:
        metrics = _last_snapshot
    if not metrics:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_services": 0,
            "running_services": 0,
            "degraded_services": 0,
            "active_faults": 0,
            "namespaces": [],
            "avg_cpu_percent": 0,
            "avg_memory_mb": 0,
            "cluster_health": "Unknown",
            "simulation_mode": False,
        }

    total = len(metrics)
    running   = sum(1 for m in metrics if m["status"] == "Running")
    degraded  = total - running
    crash_pods = sum(1 for m in metrics if m.get("crash_loop") or m.get("oom_killed"))
    avg_cpu = round(sum(m["cpu_percent"] for m in metrics) / total, 2) if total else 0
    avg_mem = round(sum(m["memory_mb"] for m in metrics) / total, 1) if total else 0
    namespaces = list({m["namespace"] for m in metrics})

    health = "Healthy"
    if crash_pods >= 3 or avg_cpu > 90:
        health = "Critical"
    elif crash_pods >= 1 or degraded >= 1 or avg_cpu > 70:
        health = "Degraded"

    return {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "total_services":   total,
        "running_services": running,
        "degraded_services": degraded,
        "active_faults":    crash_pods,
        "namespaces":       namespaces,
        "avg_cpu_percent":  avg_cpu,
        "avg_memory_mb":    avg_mem,
        "cluster_health":   health,
        "simulation_mode":  False,
    }


def build_live_topology(metrics: Optional[List[Dict]] = None) -> Dict[str, Any]:
    try:
        _init_k8s()
        deployments = _collect_deployments()
        services    = _collect_services()
        pods        = _collect_pods()
        if deployments:
            return _build_topology(deployments, services, pods)
    except Exception as e:
        logger.warning(f"K8s topology failed, building from agent data: {e}")

    if not metrics:
        logger.warning("build_live_topology: no metrics provided")
        return {"nodes": [], "links": []}
    logger.info(f"build_live_topology: building from {len(metrics)} metrics")
    nodes = []
    links = []
    ns_map = {}
    for m in metrics:
        svc = m.get("service", "unknown")
        ns = m.get("namespace", "default")
        if ns not in ns_map:
            ns_map[ns] = []
        ns_map[ns].append(svc)
        nodes.append({
            "id": svc, "namespace": ns, "domain": ns,
            "replicas": m.get("replicas", 1),
            "ready_replicas": m.get("ready_replicas", 1),
            "type": "deployment",
        })
    for ns, svcs in ns_map.items():
        for i in range(1, len(svcs)):
            links.append({"source": svcs[0], "target": svcs[i]})
    return {"nodes": nodes, "links": links}


# ── Real Kubernetes Chaos / Fault Injection ────────────────────────────────
_active_faults: Dict[str, Dict] = {}

def inject_fault(service: str, fault_type: str, duration_seconds: int = 120) -> bool:
    """Injects a real fault by scaling deployments to simulate chaos."""
    if not _apps_v1:
        logger.error("K8s AppsV1Api not initialized, cannot inject fault.")
        return False
        
    logger.info(f"Injecting {fault_type} into {service} for {duration_seconds}s")
    
    # Try to find the deployment matching the service name across namespaces
    target_dep = None
    target_ns = None
    original_replicas = 1
    
    try:
        deps = _apps_v1.list_deployment_for_all_namespaces(watch=False)
        for dep in deps.items:
            if dep.metadata.name == service:
                target_dep = dep.metadata.name
                target_ns = dep.metadata.namespace
                original_replicas = dep.spec.replicas or 1
                break

        # Fallback: try matching by stripping pod hash suffix (e.g., cpu-stress-demo-5ffcc97757-ntz8t -> cpu-stress-demo)
        if not target_dep:
            base = service.rsplit("-", 2)[0] if "-" in service else service
            for dep in deps.items:
                if dep.metadata.name == base:
                    target_dep = dep.metadata.name
                    target_ns = dep.metadata.namespace
                    original_replicas = dep.spec.replicas or 1
                    break
                
        if not target_dep:
            logger.warning(f"Could not find deployment for service {service}")
            return False
            
        # For a simulated crash/restart loop, scale to 0
        new_replicas = 0 if fault_type in ["restart_loop", "memory_leak"] else 5
        
        body = {"spec": {"replicas": new_replicas}}
        _apps_v1.patch_namespaced_deployment(name=target_dep, namespace=target_ns, body=body)
        
        _active_faults[service] = {
            "type": fault_type,
            "started_at": time.time(),
            "duration": duration_seconds,
            "original_replicas": original_replicas,
            "namespace": target_ns,
            "stub": False,
        }
        return True
    except Exception as e:
        logger.error(f"Failed to inject fault: {e}")
        return False


def clear_fault(service: str) -> bool:
    """Restores the deployment to its original replica count."""
    if service in _active_faults:
        fault = _active_faults[service]
        if not _apps_v1:
            del _active_faults[service]
            return False
            
        try:
            body = {"spec": {"replicas": fault["original_replicas"]}}
            _apps_v1.patch_namespaced_deployment(name=service, namespace=fault["namespace"], body=body)
            logger.info(f"Cleared fault for {service}, restored to {fault['original_replicas']} replicas.")
        except Exception as e:
            logger.error(f"Failed to clear fault for {service}: {e}")
            
        del _active_faults[service]
        return True
    return False


def list_faults() -> Dict:
    # Auto-clear expired faults
    now = time.time()
    expired = []
    for svc, f in _active_faults.items():
        if now - f["started_at"] > f["duration"]:
            expired.append(svc)
            
    for svc in expired:
        clear_fault(svc)
        
    return {
        svc: f for svc, f in _active_faults.items()
    }


# ── Sync wrapper for backward compat ────────────────────────────────────────
def generate_all_metrics() -> List[Dict[str, Any]]:
    """Sync wrapper — use only when event loop is not available."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Return cached snapshot if loop is already running
            return _last_snapshot or []
        return loop.run_until_complete(collect_all_metrics())
    except Exception as e:
        logger.error(f"generate_all_metrics error: {e}")
        return _last_snapshot or []

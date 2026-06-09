import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Query, HTTPException, Depends, Body
from fastapi.responses import PlainTextResponse
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.core.k8s_collector import (
    collect_all_metrics, get_cluster_summary, get_metric_history,
    build_live_topology, _collect_events, _collect_node_metrics,
    _collect_pods, _collect_services, _collect_pvcs, _collect_deployments, _core_v1,
)
from app.core.microservice_clients import ml_client, ai_client
from app.core.ai_agents.agent_coordinator import agent_coordinator
from app.core.correlation_engine import correlation_engine
from app.core.auth import require_role
from app.core.cluster_manager import cluster_manager
from app.services import state as app_state

logger = logging.getLogger("kubemind.dashboard")
router = APIRouter(tags=["dashboard"])

PROM_CPU = Gauge("kubemind_cpu_percent", "CPU usage percent", ["pod", "namespace"])
PROM_MEM = Gauge("kubemind_memory_mb", "Memory usage MB", ["pod", "namespace"])
PROM_NET_IN = Gauge("kubemind_network_rx_kbps", "Network RX kbps", ["pod", "namespace"])
PROM_NET_OUT = Gauge("kubemind_network_tx_kbps", "Network TX kbps", ["pod", "namespace"])
PROM_RESTARTS = Gauge("kubemind_restarts_total", "Total pod restarts", ["pod", "namespace"])
PROM_PVC = Gauge("kubemind_pvc_usage_percent", "PVC usage percent", ["pod", "namespace"])

@router.get("/api/v1/health")
async def health():
    return {"status": "ok", "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "version": settings.APP_VERSION, "db_enabled": settings.DB_ENABLED,
            "ws_clients": len(app_state.manager.active), "clusters": cluster_manager.cluster_count,
            "healthy_clusters": cluster_manager.healthy_count,
            "agents_connected": len(app_state.manager.agent_connections)}

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    for m in raw:
        pod, ns = m["service"], m["namespace"]
        PROM_CPU.labels(pod=pod, namespace=ns).set(m["cpu_percent"])
        PROM_MEM.labels(pod=pod, namespace=ns).set(m["memory_mb"])
        PROM_NET_IN.labels(pod=pod, namespace=ns).set(m.get("network_in_kbps", 0))
        PROM_NET_OUT.labels(pod=pod, namespace=ns).set(m.get("network_out_kbps", 0))
        PROM_RESTARTS.labels(pod=pod, namespace=ns).set(m["restart_count"])
        PROM_PVC.labels(pod=pod, namespace=ns).set(m.get("pvc_usage_percent", 0))
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@router.get("/api/v1/cluster/summary")
async def cluster_summary():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    return get_cluster_summary(raw)

@router.get("/api/v1/metrics")
async def all_metrics():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    for m in raw:
        svc = m["service"]
        m["anomaly"] = await ml_client.detect_anomaly(svc, m)
        m["prediction"] = await ml_client.predict_failure(svc, m)
        m["recommendations"] = await ai_client.get_recommendations(m["anomaly"], m["prediction"])
    return raw

@router.get("/api/v1/metrics/{service}")
async def service_metrics(service: str):
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    for m in raw:
        if m["service"] == service:
            m["anomaly"] = await ml_client.detect_anomaly(service, m)
            m["prediction"] = await ml_client.predict_failure(service, m)
            m["recommendations"] = await ai_client.get_recommendations(m["anomaly"], m["prediction"])
            m["history"] = get_metric_history(service)
            return m
    raise HTTPException(404, "Pod not found")

@router.get("/api/v1/services")
async def list_services():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    return [{"service": m["service"], "namespace": m["namespace"], "node_name": m.get("node_name", ""),
             "status": m["status"], "replicas": m["replicas"], "domain": m.get("domain", m["namespace"])} for m in raw]

@router.get("/api/v1/topology")
async def topology():
    return build_live_topology(app_state.get_all_metrics())

@router.get("/api/v1/namespaces")
async def namespaces():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    return list({m["namespace"] for m in raw})

@router.get("/api/v1/anomalies")
async def live_anomalies():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    result = []
    for m in raw:
        det = await ml_client.detect_anomaly(m["service"], m)
        if det.get("is_anomaly"):
            result.append({**det, "domain": m.get("domain", m["namespace"]), "namespace": m["namespace"]})
    return result

@router.get("/api/v1/anomalies/history")
async def anomaly_history(limit: int = Query(50)):
    if settings.DB_ENABLED:
        from app.core.database import get_recent_anomalies
        from app.core.cluster_manager import cluster_manager
        default_cluster = cluster_manager.get_default_cluster()
        cluster_id = default_cluster.cluster_id if default_cluster else "local"
        org_id = "default-org"
        return await get_recent_anomalies(org_id, cluster_id, limit)
    return []

@router.get("/api/v1/rca")
async def root_cause_analysis():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    anomalies = []
    for m in raw:
        det = await ml_client.detect_anomaly(m["service"], m)
        if det.get("is_anomaly"):
            anomalies.append({**det, "domain": m.get("domain", m["namespace"]), "namespace": m["namespace"]})
    return await ai_client.perform_rca(anomalies, raw)

@router.get("/api/v1/events")
async def cluster_events():
    return _collect_events()

@router.get("/api/v1/nodes")
async def cluster_nodes():
    return _collect_node_metrics()

@router.get("/api/v1/insights")
async def ai_insights():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    anomalies = []
    for m in raw:
        det = await ml_client.detect_anomaly(m["service"], m)
        if det.get("is_anomaly"):
            anomalies.append({**det, "namespace": m["namespace"]})
    topology = build_live_topology()
    return agent_coordinator.analyze_all(raw, anomalies, topology)

@router.get("/api/v1/correlation")
async def correlation_analysis():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    anomalies = []
    for m in raw:
        det = await ml_client.detect_anomaly(m["service"], m)
        if det.get("is_anomaly"):
            anomalies.append({**det, "namespace": m["namespace"]})
    return correlation_engine.analyze(raw, anomalies)

@router.get("/api/v1/health-score")
async def cluster_health_score():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    return correlation_engine.get_health_score(raw)

@router.get("/api/v1/exhaustion")
async def exhaustion_predictions():
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    return correlation_engine.get_exhaustion_predictions(raw)

@router.get("/api/v1/faults")
async def active_faults():
    from app.core.k8s_collector import list_faults
    return list_faults()

@router.post("/api/v1/fault/inject")
async def fault_inject(service: str = Query(...), fault_type: str = Query(...), duration: int = Query(120)):
    from app.core.k8s_collector import inject_fault
    valid = {"cpu_spike", "memory_leak", "restart_loop", "network_congestion", "storage_overload"}
    if fault_type not in valid:
        raise HTTPException(400, f"Invalid. Choose from: {valid}")
    ok = inject_fault(service, fault_type, duration)
    if not ok:
        raise HTTPException(500, f"Failed to inject fault: deployment '{service}' not found")
    return {"status": "injected", "service": service, "fault_type": fault_type}

@router.post("/api/v1/fault/clear")
async def fault_clear(service: str = Query(...)):
    from app.core.k8s_collector import clear_fault
    ok = clear_fault(service)
    return {"status": "cleared" if ok else "not_found", "service": service}

@router.post("/api/v1/ai/query")
async def ai_query_route(body: Dict[str, Any] = Body(...)):
    from app.services.payload_builder import run_ai_query
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(400, "query field required")
    return await run_ai_query(query)

@router.get("/api/pods")
async def api_pods():
    pods = _collect_pods()
    return [{
        "name": p["name"], "namespace": p["namespace"],
        "node": p.get("node_name", ""), "status": p["status"],
        "restart_count": p.get("restart_count", 0),
        "ready_containers": p.get("ready_containers", 0),
        "total_containers": p.get("total_containers", 1),
        "creation_timestamp": str(p.get("creation_timestamp", "")),
        "labels": p.get("labels", {}),
    } for p in pods]

@router.get("/api/services")
async def api_services():
    return _collect_services()

@router.get("/api/namespaces")
async def api_namespaces():
    try:
        if _core_v1:
            items = _core_v1.list_namespace().items
            return sorted([ns.metadata.name for ns in items])
    except Exception:
        pass
    namespaces = set()
    for m in (app_state.get_all_metrics() or []):
        ns = m.get("namespace", "")
        if ns:
            namespaces.add(ns)
    return sorted(list(namespaces))

@router.get("/api/pvcs")
async def api_pvcs():
    return _collect_pvcs()

@router.get("/api/events")
async def api_events_live():
    return _collect_events()

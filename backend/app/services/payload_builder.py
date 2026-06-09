import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.k8s_collector import collect_all_metrics, get_cluster_summary, build_live_topology, list_faults
from app.core.microservice_clients import ml_client, ai_client
from app.core.ai_agents.agent_coordinator import agent_coordinator
from app.core.correlation_engine import correlation_engine
from app.services import state as app_state

logger = logging.getLogger("kubemind.payload")

async def build_payload(raw_metrics: List[Dict]) -> Dict[str, Any]:
    anomalies, enriched = [], []
    for m in raw_metrics:
        svc = m["service"]
        detection = await ml_client.detect_anomaly(svc, m)
        prediction = await ml_client.predict_failure(svc, m)
        recs = await ai_client.get_recommendations(detection, prediction)
        m["anomaly"], m["prediction"], m["recommendations"] = detection, prediction, recs
        enriched.append(m)
        if detection.get("is_anomaly"):
            anomalies.append({**detection, "domain": m.get("domain", m["namespace"]), "namespace": m["namespace"]})

    topology = build_live_topology(raw_metrics)
    rca_results = await ai_client.perform_rca(anomalies, enriched, topology=topology)
    summary = get_cluster_summary(raw_metrics)
    nlp_insights = _generate_nlp_insights(rca_results, anomalies, summary)
    ai_insights = agent_coordinator.analyze_all(raw_metrics, anomalies, topology)
    correlation_data = correlation_engine.analyze(raw_metrics, anomalies)
    health_score = correlation_engine.get_health_score(raw_metrics)
    exhaustion = correlation_engine.get_exhaustion_predictions(raw_metrics)

    return {
        "type": "METRICS_UPDATE",
        "ts": datetime.now(timezone.utc).isoformat(),
        "summary": summary, "metrics": enriched, "anomalies": anomalies,
        "rca": rca_results, "nlp_insights": nlp_insights,
        "ai_agent_insights": ai_insights,
        "correlation_intelligence": correlation_data,
        "health_score": health_score,
        "exhaustion_predictions": exhaustion,
        "active_faults": list_faults(), "topology": topology,
    }

def _generate_nlp_insights(rca, anomalies, summary) -> List[Dict]:
    insights, ts = [], datetime.now(timezone.utc).isoformat()
    health = summary.get("cluster_health", "Unknown")
    if health == "Critical":
        insights.append({"id": "cluster-critical", "severity": "critical",
            "message": f"Cluster CRITICAL — {summary.get('degraded_services',0)} pods degraded, avg CPU {summary.get('avg_cpu_percent',0):.1f}%",
            "ts": ts, "source": "correlation-engine"})
    elif health == "Degraded":
        insights.append({"id": "cluster-degraded", "severity": "warning",
            "message": f"Cluster degrading — {summary.get('degraded_services',0)} pods non-running.",
            "ts": ts, "source": "correlation-engine"})
    for r in rca[:5]:
        svc = r.get("service", "unknown")
        if r.get("is_root_cause"):
            types = ", ".join(r.get("anomaly_types", []))
            downstream = r.get("at_risk_downstream", [])
            msg = f"Root cause in {svc}: {types}."
            if downstream:
                msg += f" {len(downstream)} downstream at risk: {', '.join(downstream[:3])}."
            insights.append({"id": f"rca-root-{svc}", "severity": r.get("severity", "warning"),
                "message": msg, "ts": ts, "source": "rca-engine"})
    oom_pods = [m["service"] for m in anomalies if "OOMKilled" in str(m.get("anomaly_types", []))]
    if oom_pods:
        insights.append({"id": "oom-alert", "severity": "critical",
            "message": f"OOMKilled: {', '.join(oom_pods[:3])}. Increase memory limits.",
            "ts": ts, "source": "memory-agent"})
    return insights[:10]

async def run_ai_query(query: str) -> Dict[str, Any]:
    from app.core.k8s_collector import collect_all_metrics, get_cluster_summary
    from app.core.microservice_clients import ml_client, ai_client
    raw = app_state.get_all_metrics() or await collect_all_metrics()
    anomaly_ctx = []
    for m in raw:
        det = await ml_client.detect_anomaly(m["service"], m)
        if det.get("is_anomaly"):
            anomaly_ctx.append(f"{m['service']} ({m['namespace']}): {det.get('anomaly_types', [])}")
    summary = get_cluster_summary(raw)
    context = f"Anomalies: {'; '.join(anomaly_ctx) or 'None'}. Health: {summary['cluster_health']}. Pods: {summary['total_services']}"
    res = await ai_client.ai_query(query, context)
    return {"query": query, "response": res.get("response", "No response."),
            "context": context, "source": res.get("source", "unknown")}

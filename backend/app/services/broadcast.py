import asyncio
import json
import logging
from typing import List, Dict

from app.core.config import settings
from app.core.k8s_collector import collect_all_metrics
from app.core.alerting import check_and_alert
from app.core.cluster_manager import cluster_manager
from app.services import state as app_state
from app.services.payload_builder import build_payload

logger = logging.getLogger("kubemind.broadcast")

async def broadcast_agent_data(agent_metrics: List[Dict], cluster_id: str = "default"):
    try:
        app_state._cached_metrics[cluster_id] = agent_metrics
        all_metrics = app_state.get_all_metrics()
        payload_dict = await build_payload(all_metrics)
        await app_state.manager.broadcast(json.dumps(payload_dict, default=str))
        logger.info(f"Agent metrics broadcast: {len(agent_metrics)} services from {cluster_id}, total {len(all_metrics)}")
    except Exception as e:
        logger.error(f"Agent metrics broadcast error: {e}")

async def broadcast_loop():
    logger.info("Real-time K8s metrics broadcast loop started.")
    await asyncio.sleep(0)
    if settings.DB_ENABLED:
        from app.core.database import save_metrics_batch, save_anomaly, save_prediction, save_alert_record, save_topology_snapshot
    while True:
        try:
            raw_metrics = await asyncio.wait_for(collect_all_metrics(), timeout=30)
            if raw_metrics:
                app_state._cached_metrics["local"] = raw_metrics
            all_metrics = app_state.get_all_metrics()
            if all_metrics and app_state.manager.active:
                payload_dict = await build_payload(all_metrics)
                await app_state.manager.broadcast(json.dumps(payload_dict, default=str))
                anomalies_list = payload_dict.get("anomalies", [])
                asyncio.create_task(check_and_alert(
                    all_metrics, anomalies_list))
                if settings.DB_ENABLED:
                    default_cluster = cluster_manager.get_default_cluster()
                    cluster_id = default_cluster.cluster_id if default_cluster else "local"
                    org_id = next(iter(app_state._orgs_store.keys()), "default-org")
                    for a in anomalies_list:
                        asyncio.create_task(save_alert_record(
                            org_id, cluster_id, a.get("service", "unknown"),
                            ", ".join(a.get("anomaly_types", [])),
                            a.get("severity", "warning"), a.get("message", "")))
                    asyncio.create_task(save_metrics_batch(
                        payload_dict.get("metrics", []), org_id, cluster_id))
                    for a in payload_dict.get("anomalies", []):
                        asyncio.create_task(save_anomaly(a, org_id, cluster_id))
                    predictions = payload_dict.get("exhaustion_predictions", [])
                    for p in predictions[:10]:
                        p["service"] = p.get("service", "unknown")
                        asyncio.create_task(save_prediction(p, org_id, cluster_id))
                    if payload_dict.get("topology"):
                        asyncio.create_task(save_topology_snapshot(payload_dict["topology"], org_id, cluster_id))
        except Exception as exc:
            logger.error(f"Broadcast error: {exc}", exc_info=True)
        await asyncio.sleep(settings.WS_METRICS_BROADCAST_INTERVAL)

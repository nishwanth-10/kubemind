import asyncio
import json
import logging
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from kubernetes import client
from kubernetes.watch import Watch

from app.core.config import settings
from app.core.auth import decode_token
from app.core.cluster_manager import cluster_manager
from app.core.k8s_collector import collect_all_metrics, inject_fault, clear_fault
from app.services import state as app_state
from app.services.payload_builder import build_payload, run_ai_query
from app.services.broadcast import broadcast_agent_data

logger = logging.getLogger("kubemind.ws_router")
router = APIRouter(tags=["websocket"])

@router.websocket("/ws/logs/{namespace}/{pod_name}")
async def pod_logs_ws(ws: WebSocket, namespace: str, pod_name: str):
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    try:
        user = decode_token(token)
    except HTTPException:
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()
    core_v1 = client.CoreV1Api()
    try:
        core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception as e:
        await ws.send_text(f"Error accessing pod: {e}")
        await ws.close()
        return

    main_loop = asyncio.get_running_loop()
    def tail_logs():
        try:
            w = Watch()
            for line in w.stream(core_v1.read_namespaced_pod_log, name=pod_name, namespace=namespace, tail_lines=100, follow=True):
                asyncio.run_coroutine_threadsafe(ws.send_text(line), main_loop)
        except Exception:
            pass

    log_task = asyncio.create_task(asyncio.to_thread(tail_logs))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        log_task.cancel()

@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket):
    api_key = ws.query_params.get("api_key", "")

    cluster_id = None
    cluster_org_id = None
    if settings.DB_ENABLED:
        from app.core.database import get_api_key
        key_record = await get_api_key(api_key)
        if key_record:
            cluster_id = key_record["cluster_id"]
            cluster_org_id = key_record.get("org_id")
    if not cluster_id:
        cluster_id = app_state._api_keys_store.get(api_key)
    if not cluster_id:
        await ws.close(code=4001, reason="Invalid API key")
        return

    if not cluster_manager.get_cluster(cluster_id):
        cluster_manager.register_agent_cluster(cluster_id, f"Cluster-{cluster_id[:8]}", "agent", org_id=cluster_org_id)
    await app_state.manager.connect_agent(cluster_id, ws)
    logger.info(f"Agent connected: cluster={cluster_id}")

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "heartbeat":
                    cluster_manager.update_agent_heartbeat(cluster_id, msg.get("agent_info"))
                    await ws.send_text(json.dumps({"type": "heartbeat_ack"}))
                elif msg_type == "metrics":
                    from app.core.event_bus import publish_metrics
                    asyncio.create_task(publish_metrics(msg.get("data", {}), cluster_id))
                    agent_data = msg.get("data", {}).get("metrics", [])
                    if agent_data:
                        conn = cluster_manager.get_cluster(cluster_id)
                        if conn and conn.name.startswith("Cluster-"):
                            node_name = next((m.get("node_name", "") for m in agent_data if m.get("node_name")), "")
                            if node_name:
                                cluster_name = node_name.rsplit(".", 1)[0]
                                conn.name = cluster_name
                        asyncio.create_task(broadcast_agent_data(agent_data, cluster_id))
                elif msg_type == "topology":
                    from app.core.event_bus import publish_topology
                    asyncio.create_task(publish_topology(msg.get("data", {}), cluster_id))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        app_state.manager.disconnect_agent(cluster_id)
        logger.info(f"Agent disconnected: cluster={cluster_id}")

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    try:
        user = decode_token(token)
    except HTTPException:
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()
    app_state.manager.active.append(ws)
    logger.info("WebSocket accepted")

    try:
        raw = app_state.get_all_metrics()
        if not raw:
            try:
                raw = await asyncio.wait_for(collect_all_metrics(), timeout=30)
            except asyncio.TimeoutError:
                raw = []
        payload_dict = await build_payload(raw)
        await ws.send_text(json.dumps(payload_dict, default=str))
    except (WebSocketDisconnect, RuntimeError):
        app_state.manager.disconnect(ws)
        return
    except Exception as e:
        logger.warning(f"Initial snapshot error: {e}")

    try:
        while True:
            data = await ws.receive_text()
            try:
                cmd = json.loads(data)
                action = cmd.get("action")
                if action == "inject_fault":
                    ok = inject_fault(cmd["service"], cmd["fault_type"], cmd.get("duration", 120))
                    await ws.send_text(json.dumps({"type": "FAULT_ACK", "success": ok, **cmd}))
                elif action == "clear_fault":
                    ok = clear_fault(cmd["service"])
                    await ws.send_text(json.dumps({"type": "FAULT_ACK", "success": ok, **cmd}))
                elif action == "ai_query":
                    resp = await run_ai_query(cmd.get("query", ""))
                    await ws.send_text(json.dumps({"type": "AI_RESPONSE", **resp}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except RuntimeError:
        logger.info("WebSocket client disconnected during initial snapshot")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        app_state.manager.disconnect(ws)

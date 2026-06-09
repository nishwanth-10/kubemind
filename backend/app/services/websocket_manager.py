import logging
from typing import Dict, List, Optional
from fastapi import WebSocket
from app.core.cluster_manager import cluster_manager

logger = logging.getLogger("kubemind.ws_manager")

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.agent_connections: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def connect_agent(self, cluster_id: str, ws: WebSocket):
        await ws.accept()
        self.agent_connections[cluster_id] = ws
        cluster_manager.update_agent_heartbeat(cluster_id)

    def disconnect_agent(self, cluster_id: str):
        self.agent_connections.pop(cluster_id, None)

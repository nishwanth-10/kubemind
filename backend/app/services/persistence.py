import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.alerting import create_alert
from app.services.state import _orgs_store

logger = logging.getLogger("kubemind.persistence")

async def save_alert_record(alert: Dict[str, Any], org_id: str, cluster_id: str):
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO alert_records (org_id, cluster_id, service, alert_type, severity, message)
                VALUES (:org_id, :cluster_id, :service, :alert_type, :severity, :message)
            """),
            {
                "org_id": org_id,
                "cluster_id": cluster_id,
                "service": alert.get("service", ""),
                "alert_type": alert.get("alert_type", ""),
                "severity": alert.get("severity", "warning"),
                "message": alert.get("message", ""),
            },
        )
        await session.commit()


async def save_ai_insight(query: str, response: str, source: str, org_id: str, cluster_id: str, context: str = ""):
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO ai_insights (org_id, cluster_id, query, response, source, context)
                VALUES (:org_id, :cluster_id, :query, :response, :source, :context)
            """),
            {"org_id": org_id, "cluster_id": cluster_id, "query": query,
             "response": response, "source": source, "context": context},
        )
        await session.commit()

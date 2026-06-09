import logging
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.auth import generate_cluster_id, generate_api_key, require_role
from app.core.cluster_manager import cluster_manager
from app.services.state import _clusters_store, _api_keys_store

logger = logging.getLogger("kubemind.clusters")
router = APIRouter(prefix="/api/v1/clusters", tags=["clusters"])

@router.get("")
async def list_clusters(user: Dict = Depends(require_role("viewer"))):
    if settings.DB_ENABLED:
        from app.core.database import get_clusters_by_org
        clusters = await get_clusters_by_org(user["org_id"])
        return [
            {**cluster_manager.get_cluster_dict(c["id"]), **c, "cluster_id": c["id"]} for c in clusters
        ]
    else:
        return [c for c in cluster_manager.get_all_clusters() if c.get("org_id") == user["org_id"]]

@router.post("")
async def register_cluster(body: Dict[str, Any] = Body(...), user: Dict = Depends(require_role("admin"))):
    name = body.get("name", "New Cluster")
    provider = body.get("provider", "unknown")
    cluster_id = generate_cluster_id()
    api_key = generate_api_key()

    try:
        if settings.DB_ENABLED:
            from app.core.database import create_cluster_db, create_api_key
            await create_cluster_db(cluster_id, name, provider, user["org_id"])
            await create_api_key(api_key, cluster_id, user["org_id"])
        else:
            _api_keys_store[api_key] = cluster_id
            _clusters_store[cluster_id] = {"api_key": api_key, "name": name, "provider": provider, "org_id": user.get("org_id")}
            from app.core.redis_store import redis_create_api_key, redis_create_cluster
            await redis_create_api_key(api_key, cluster_id)
            await redis_create_cluster(cluster_id, {"cluster_id": cluster_id, "name": name, "provider": provider, "org_id": user.get("org_id")})
    except IntegrityError as e:
        logger.error(f"FK violation for cluster {cluster_id} org {user.get('org_id')}: {e}")
        raise HTTPException(400, "Organization not found. The organization for this user no longer exists — please re-register or contact an administrator.")
    except Exception as e:
        logger.error(f"Failed to persist cluster {cluster_id}: {e}")
        raise HTTPException(500, f"Failed to create cluster: {e}")

    cluster_manager.register_agent_cluster(cluster_id, name, provider, org_id=user.get("org_id"))

    helm_cmd = (
        f"helm install kubemind-agent kubemind/kubemind-agent \\\n"
        f"  --set agent.apiKey={api_key} \\\n"
        f"  --set agent.backendUrl=ws://<YOUR_KUBEMIND_HOST>:8000/ws/agent \\\n"
        f"  --set agent.clusterId={cluster_id} \\\n"
        f"  --namespace kubemind-agent --create-namespace"
    )

    return {"cluster_id": cluster_id, "api_key": api_key, "name": name,
            "install_command": helm_cmd, "status": "awaiting_agent"}

@router.get("/{cluster_id}")
async def get_cluster(cluster_id: str, user: Dict = Depends(require_role("viewer"))):
    if settings.DB_ENABLED:
        from app.core.database import get_cluster_db
        c = await get_cluster_db(cluster_id)
        if not c or c["org_id"] != user["org_id"]:
            raise HTTPException(404, "Cluster not found")
        live = cluster_manager.get_cluster(cluster_id)
        if live:
            c.update(live.to_dict())
        c["cluster_id"] = c["id"]
        return c
    else:
        c = cluster_manager.get_cluster(cluster_id)
        if not c:
            raise HTTPException(404, "Cluster not found")
        return c.to_dict()

@router.delete("/{cluster_id}")
async def delete_cluster(cluster_id: str, user: Dict = Depends(require_role("admin"))):
    if settings.DB_ENABLED:
        from app.core.database import get_cluster_db, delete_cluster_db
        c = await get_cluster_db(cluster_id)
        if not c or c["org_id"] != user["org_id"]:
            raise HTTPException(404, "Cluster not found")
        await delete_cluster_db(cluster_id, user["org_id"])
    else:
        from app.core.redis_store import redis_delete_cluster
        await redis_delete_cluster(cluster_id)

    cluster_manager.remove_cluster(cluster_id)
    _clusters_store.pop(cluster_id, None)
    return {"status": "deleted", "cluster_id": cluster_id}

@router.get("/{cluster_id}/install-command")
async def cluster_install_cmd(cluster_id: str, user: Dict = Depends(require_role("viewer"))):
    if settings.DB_ENABLED:
        from app.core.database import get_cluster_db, get_api_key_by_cluster
        c = await get_cluster_db(cluster_id)
        if not c or c["org_id"] != user["org_id"]:
            raise HTTPException(404, "Cluster not found")
        key_record = await get_api_key_by_cluster(cluster_id)
        api_key = key_record["key_hash"] if key_record else "<YOUR_API_KEY>"
    else:
        info = _clusters_store.get(cluster_id)
        if not info:
            raise HTTPException(404, "Cluster not found")
        api_key = info.get('api_key', '<YOUR_API_KEY>')

    return {"install_command": (
        f"helm install kubemind-agent kubemind/kubemind-agent "
        f"--set agent.apiKey={api_key} "
        f"--set agent.backendUrl=ws://<YOUR_HOST>:8000/ws/agent "
        f"--set agent.clusterId={cluster_id} "
        f"--namespace kubemind-agent --create-namespace"
    )}

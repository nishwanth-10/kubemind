import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("kubemind.redis")

_UPSTASH_URL = settings.UPSTASH_REDIS_REST_URL
_UPSTASH_TOKEN = settings.UPSTASH_REDIS_REST_TOKEN
_UPSTASH_ENABLED = bool(_UPSTASH_URL and _UPSTASH_TOKEN)

_client: Optional[httpx.AsyncClient] = None

PREFIX_USER = "user:"
PREFIX_ORG = "org:"
PREFIX_CLUSTER = "cluster:"
PREFIX_APIKEY = "apikey:"
PREFIX_REFRESH = "refresh:"

async def _get_redis_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_UPSTASH_URL,
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            timeout=10,
        )
    return _client

async def _redis_cmd(*parts: str) -> Any:
    if not _UPSTASH_ENABLED:
        return None
    client = await _get_redis_client()
    path = "/" + "/".join(parts)
    resp = await client.get(path)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.warning(f"Redis error: {resp.status_code} {resp.text}")
        return None
    try:
        data = resp.json()
        val = data.get("result")
    except (json.JSONDecodeError, TypeError, AttributeError):
        val = resp.text
    if val in (None, "nil", ""):
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val

async def _redis_set(key: str, value: Any) -> bool:
    if not _UPSTASH_ENABLED:
        return False
    client = await _get_redis_client()
    raw = json.dumps(value) if not isinstance(value, str) else value
    import urllib.parse
    path = f"/set/{key}/{urllib.parse.quote(raw)}"
    resp = await client.get(path)
    data = resp.json()
    return data.get("result") == "OK"

async def _redis_del(key: str) -> bool:
    if not _UPSTASH_ENABLED:
        return False
    client = await _get_redis_client()
    resp = await client.get(f"/del/{key}")
    data = resp.json()
    return data.get("result") == "OK" or data.get("result") == 1

async def _redis_keys(pattern: str) -> List[str]:
    if not _UPSTASH_ENABLED:
        return []
    client = await _get_redis_client()
    resp = await client.get(f"/keys/{pattern}")
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
        val = data.get("result")
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []

async def close_redis():
    global _client
    if _client:
        await _client.aclose()
        _client = None

# ── Users ──────────────────────────────────────────────────────────────────

async def redis_get_user(email: str) -> Optional[Dict]:
    return await _redis_cmd("get", PREFIX_USER + email.lower())

async def redis_create_user(email: str, user_data: Dict) -> bool:
    return await _redis_set(PREFIX_USER + email.lower(), user_data)

async def redis_delete_user(email: str) -> bool:
    return await _redis_del(PREFIX_USER + email.lower())

async def redis_list_users() -> List[Dict]:
    keys = await _redis_keys(PREFIX_USER + "*")
    users = []
    for key in keys:
        raw = await _redis_cmd("get", key)
        if isinstance(raw, dict):
            users.append(raw)
    return users

# ── Orgs ───────────────────────────────────────────────────────────────────

async def redis_get_org(org_id: str) -> Optional[Dict]:
    return await _redis_cmd("get", PREFIX_ORG + org_id)

async def redis_create_org(org_id: str, org_data: Dict) -> bool:
    return await _redis_set(PREFIX_ORG + org_id, org_data)

async def redis_delete_org(org_id: str) -> bool:
    return await _redis_del(PREFIX_ORG + org_id)

# ── Clusters ───────────────────────────────────────────────────────────────

async def redis_get_cluster(cluster_id: str) -> Optional[Dict]:
    return await _redis_cmd("get", PREFIX_CLUSTER + cluster_id)

async def redis_create_cluster(cluster_id: str, cluster_data: Dict) -> bool:
    return await _redis_set(PREFIX_CLUSTER + cluster_id, cluster_data)

async def redis_delete_cluster(cluster_id: str) -> bool:
    return await _redis_del(PREFIX_CLUSTER + cluster_id)

async def redis_list_clusters() -> List[Dict]:
    keys = await _redis_keys(PREFIX_CLUSTER + "*")
    clusters = []
    for key in keys:
        raw = await _redis_cmd("get", key)
        if isinstance(raw, dict):
            clusters.append(raw)
    return clusters

async def redis_list_clusters_by_org(org_id: str) -> List[Dict]:
    all_clusters = await redis_list_clusters()
    return [c for c in all_clusters if c.get("org_id") == org_id]

# ── API Keys ───────────────────────────────────────────────────────────────

async def redis_get_api_key(api_key: str) -> Optional[str]:
    return await _redis_cmd("get", PREFIX_APIKEY + api_key)

async def redis_create_api_key(api_key: str, cluster_id: str) -> bool:
    return await _redis_set(PREFIX_APIKEY + api_key, cluster_id)

async def redis_delete_api_key(api_key: str) -> bool:
    return await _redis_del(PREFIX_APIKEY + api_key)

async def redis_list_api_keys() -> Dict[str, str]:
    keys = await _redis_keys(PREFIX_APIKEY + "*")
    result = {}
    for key in keys:
        cid = await _redis_cmd("get", key)
        if cid and isinstance(cid, str):
            api_key = key[len(PREFIX_APIKEY):]
            result[api_key] = cid
    return result

# ── Refresh Tokens ─────────────────────────────────────────────────────────

async def redis_get_refresh_token(token: str) -> Optional[Dict]:
    return await _redis_cmd("get", PREFIX_REFRESH + token)

async def redis_create_refresh_token(token: str, user_id: str, expires_at: str) -> bool:
    return await _redis_set(PREFIX_REFRESH + token, {"user_id": user_id, "expires_at": expires_at})

async def redis_delete_refresh_token(token: str) -> bool:
    return await _redis_del(PREFIX_REFRESH + token)

# ── Bootstrap: load all data from Redis into memory stores ─────────────────

async def bootstrap_from_redis():
    if not _UPSTASH_ENABLED:
        logger.info("Upstash Redis not configured, using in-memory stores")
        return

    logger.info("Bootstrapping from Upstash Redis...")
    from app.services import state as app_state

    # Load API keys
    api_keys = await redis_list_api_keys()
    app_state._api_keys_store.update(api_keys)
    logger.info(f"Loaded {len(api_keys)} API keys from Redis")

    # Load users
    users = await redis_list_users()
    loaded_users = 0
    for u in users:
        email = u.get("email")
        if email:
            app_state._users_store[email] = u
            loaded_users += 1
    logger.info(f"Loaded {loaded_users} users from Redis")

    # Load orgs
    for u in users:
        org_id = u.get("org_id")
        if org_id and org_id not in app_state._orgs_store:
            org = await redis_get_org(org_id)
            if org:
                app_state._orgs_store[org_id] = org
    logger.info(f"Loaded {len(app_state._orgs_store)} orgs from Redis")

    # Load clusters into cluster_manager (only when DB disabled)
    if not settings.DB_ENABLED:
        clusters = await redis_list_clusters()
        from app.core.cluster_manager import cluster_manager
        loaded_clusters = 0
        for c in clusters:
            cid = c.get("cluster_id")
            if cid:
                cluster_manager.register_agent_cluster(
                    cid, c.get("name", "K8s Cluster"), c.get("provider", "agent"),
                    org_id=c.get("org_id")
                )
                loaded_clusters += 1
        logger.info(f"Loaded {loaded_clusters} clusters from Redis")

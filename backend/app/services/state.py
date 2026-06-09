import asyncio
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional
from app.services.websocket_manager import ConnectionManager

manager = ConnectionManager()
_broadcast_task: Optional[asyncio.Task] = None
_cached_metrics: Dict[str, List[Dict]] = {}

_POD_SUFFIX_RE = re.compile(r'^(.+?)-\w{9,10}-\w{5}$')

def _clean_service_name(pod_name: str) -> str:
    m = _POD_SUFFIX_RE.match(pod_name)
    if m:
        return m.group(1)
    return pod_name

def get_all_metrics() -> List[Dict]:
    result = []
    for cluster_id, metrics in _cached_metrics.items():
        for m in metrics:
            e = dict(m)
            e["cluster_id"] = cluster_id
            e["display_name"] = _clean_service_name(m.get("service", "unknown"))
            result.append(e)
    return result

_users_store: Dict[str, Dict] = {}
_orgs_store: Dict[str, Dict] = {}
_clusters_store: Dict[str, Dict] = {}
_api_keys_store: Dict[str, str] = {
    "km_qEhB-v7fjws2aB9inx4lihDzciEu08VJX8QYkLdxi8o": "f024caae-101",
    "km_8VKihBRA4CO73s2HrVVNnUelwaTlxs0Z0qbtNRQhiGg": "a41a0fb4-3d4",
    "km_9iLp_j44CGVjj7CNzTT_X1XmsQlYSec8FTfv5N6v530": "19287f42-028",
    "km_mh8L4GYj147Vb917CMP_vwpZjhE4hDCrwhMTKJG3c5k": "4677b17f-403",
}

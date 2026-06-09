import sys, os
sys.path.insert(0, "/app")
import asyncio
from app.core.database import _engine, create_cluster_db, create_api_key, get_cluster_db
from sqlalchemy import text

async def test():
    async with _engine.connect() as conn:
        r = await conn.execute(text("SELECT id FROM organizations LIMIT 1"))
        org = r.fetchone()
        org_id = org[0] if org else None
        print(f"Using org_id: {org_id}")
    if org_id:
        await create_cluster_db("test-cluster-1", "Test Cluster", "minikube", org_id)
        await create_api_key("km_test_key_999", "test-cluster-1", org_id)
        c = await get_cluster_db("test-cluster-1")
        print(f"Cluster created: {c}")
        await _engine.dispose()
        print("SUCCESS - DB storage works!")
    else:
        print("No orgs found")
        await _engine.dispose()

asyncio.run(test())

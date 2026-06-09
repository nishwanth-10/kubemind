import asyncio
from app.core.database import (
    init_db, _engine, create_organization, create_user,
    create_cluster_db, create_api_key, get_cluster_db,
    delete_cluster_db, get_user_by_email
)
from app.core.auth import hash_password

async def test():
    try:
        await init_db(enable_timescale=False)
        print("Tables created")

        # Full flow: org -> user -> cluster
        await create_organization("org-123", "KubeMind Org")
        await create_user("user-123", "test@kubemind.ai", "Test User",
                          hash_password("test123"), "admin", "org-123")
        print("Org + User created")

        await create_cluster_db("cluster-abc", "My Cluster", "minikube", "org-123")
        await create_api_key("km_test_key_123", "cluster-abc", "org-123")
        print("Cluster + API key created")

        c = await get_cluster_db("cluster-abc")
        print("Cluster read back:", c)

        u = await get_user_by_email("test@kubemind.ai")
        print("User read back:", u["email"], u["role"])

        await delete_cluster_db("cluster-abc", "org-123")
        print("Cleanup done. DB is fully working!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FAILED: {e}")
    finally:
        await _engine.dispose()

asyncio.run(test())

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)


@pytest.mark.asyncio
async def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_register_validates_input():
    response = client.post("/api/v1/auth/register", json={})
    assert response.status_code == 400
    assert "email and password required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_validates_input():
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code == 400
    assert "email and password required" in response.json()["detail"]

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_full_auth_flow():
    # Register
    r = client.post("/api/v1/auth/register", json={
        "email": "flowtest@test.com",
        "password": "test123",
        "name": "Flow Test",
    })
    assert r.status_code == 200, f"Register failed: {r.json()}"
    data = r.json()
    assert "token" in data
    register_token = data["token"]

    # Login with same credentials
    r = client.post("/api/v1/auth/login", json={
        "email": "flowtest@test.com",
        "password": "test123",
    })
    assert r.status_code == 200, f"Login failed: {r.json()}"
    data = r.json()
    assert "token" in data
    login_token = data["token"]
    assert data["user"]["email"] == "flowtest@test.com"

    # Me endpoint with login token
    r = client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {login_token}"
    })
    assert r.status_code == 200, f"/me failed: {r.json()}"
    assert r.json()["email"] == "flowtest@test.com"

    # Health endpoint (no auth required)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_wrong_password():
    client.post("/api/v1/auth/register", json={
        "email": "wrongpw@test.com",
        "password": "correct",
        "name": "Test",
    })
    r = client.post("/api/v1/auth/login", json={
        "email": "wrongpw@test.com",
        "password": "wrong",
    })
    assert r.status_code == 401


def test_login_nonexistent_user():
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com",
        "password": "test123",
    })
    assert r.status_code == 401


def test_me_without_token():
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_with_invalid_token():
    r = client.get("/api/v1/auth/me", headers={
        "Authorization": "Bearer invalidtoken"
    })
    assert r.status_code == 401

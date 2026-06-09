import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy import text

from app.core.config import settings
from app.core.auth import (
    hash_password, verify_password, create_access_token, decode_token,
    generate_cluster_id, get_current_user,
)
from app.services.state import _users_store, _orgs_store

logger = logging.getLogger("kubemind.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/register")
async def register(body: Dict[str, Any] = Body(...)):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    name = body.get("name", "")
    org_name = body.get("organization", "Default Org")
    if not email or not password:
        raise HTTPException(400, "email and password required")

    if settings.DB_ENABLED:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email}
            )
            if result.fetchone():
                raise HTTPException(409, "User already exists")
            user_id = generate_cluster_id()
            org_id = generate_cluster_id()
            await session.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
                {"id": org_id, "name": org_name}
            )
            await session.execute(
                text("""
                    INSERT INTO users (id, email, name, password_hash, role, org_id)
                    VALUES (:id, :email, :name, :password_hash, :role, :org_id)
                """),
                {"id": user_id, "email": email, "name": name, "password_hash": hash_password(password), "role": "admin", "org_id": org_id}
            )
            await session.commit()
    else:
        if email in _users_store:
            raise HTTPException(409, "User already exists")
        from app.core.redis_store import redis_get_user
        existing_redis = await redis_get_user(email)
        if existing_redis:
            raise HTTPException(409, "User already exists")
        user_id = generate_cluster_id()
        org_id = generate_cluster_id()
        user_data = {
            "id": user_id, "email": email, "name": name,
            "password_hash": hash_password(password),
            "role": "admin", "org_id": org_id,
        }
        _users_store[email] = user_data
        _orgs_store[org_id] = {"id": org_id, "name": org_name, "owner": user_id}
        from app.core.redis_store import redis_create_user, redis_create_org
        await redis_create_user(email, user_data)
        await redis_create_org(org_id, {"id": org_id, "name": org_name, "owner": user_id})

    token = create_access_token({"sub": user_id, "email": email, "role": "admin", "org_id": org_id})
    refresh_token = secrets.token_urlsafe(32)
    if settings.DB_ENABLED:
        from app.core.database import create_refresh_token
        await create_refresh_token(refresh_token, user_id, datetime.now(timezone.utc) + timedelta(days=7))

    return {"token": token, "refresh_token": refresh_token, "user": {"id": user_id, "email": email, "name": name, "role": "admin", "org_id": org_id}}

@router.post("/login")
async def login(body: Dict[str, Any] = Body(...)):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(400, "email and password required")

    if settings.DB_ENABLED:
        from app.core.database import get_user_by_email
        user = await get_user_by_email(email)
    else:
        user = _users_store.get(email)
        if not user:
            from app.core.redis_store import redis_get_user
            user = await redis_get_user(email)

    if not user or not isinstance(user, dict) or not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token({"sub": user["id"], "email": user["email"], "role": user["role"], "org_id": user["org_id"]})
    refresh_token = secrets.token_urlsafe(32)
    if settings.DB_ENABLED:
        from app.core.database import create_refresh_token
        await create_refresh_token(refresh_token, user["id"], datetime.now(timezone.utc) + timedelta(days=7))

    return {"token": token, "refresh_token": refresh_token, "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"], "org_id": user["org_id"]}}

@router.post("/refresh")
async def refresh_auth(body: Dict[str, Any] = Body(...)):
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(400, "refresh_token required")
    if not settings.DB_ENABLED:
        raise HTTPException(501, "Refresh tokens require DB")

    from app.core.database import get_refresh_token, delete_refresh_token, AsyncSessionLocal
    token_record = await get_refresh_token(refresh_token)
    if not token_record or token_record["expires_at"] < datetime.now(timezone.utc):
        if token_record:
            await delete_refresh_token(refresh_token)
        raise HTTPException(401, "Invalid or expired refresh token")
    await delete_refresh_token(refresh_token)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, email, name, role, org_id FROM users WHERE id = :id"),
            {"id": token_record["user_id"]}
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(401, "User no longer exists")
        user = dict(row._mapping)

    token = create_access_token({"sub": user["id"], "email": user["email"], "role": user["role"], "org_id": user["org_id"]})
    new_refresh_token = secrets.token_urlsafe(32)
    from app.core.database import create_refresh_token
    await create_refresh_token(new_refresh_token, user["id"], datetime.now(timezone.utc) + timedelta(days=7))

    return {"token": token, "refresh_token": new_refresh_token, "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"], "org_id": user["org_id"]}}

@router.get("/me")
async def get_me(user: Dict = Depends(get_current_user)):
    return user

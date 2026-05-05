# memory-neo/api/services/auth.py
# Path: api/services/auth.py
# Purpose: API key creation, hashing, validation. Dev mode bypass. Supabase via Prisma.

import os
import secrets
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEV_API_KEY = os.getenv("DEV_API_KEY", "local-dev-key")
DEV_USER_ID = os.getenv("DEV_USER_ID", "usr_local")
DEV_EMAIL   = os.getenv("DEV_EMAIL", "dev@local.dev")


def _hash_key(raw_key: str) -> str:
    salt = os.getenv("API_SECRET_SALT", "default_salt_change_me")
    return hashlib.sha256(f"{salt}{raw_key}".encode()).hexdigest()


def _generate_key() -> str:
    return "mnk_" + secrets.token_urlsafe(40)


async def create_user_with_key(email: str) -> dict:
    """
    Create a new user + API key.
    Returns the raw key once — not retrievable after this call.
    """
    if ENVIRONMENT == "development":
        raise HTTPException(
            status_code=501,
            detail="Registration not available in dev mode. Use DEV_API_KEY from .env",
        )

    from api.db.prisma import get_db
    db = await get_db()

    existing = await db.user.find_unique(where={"email": email})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    raw_key = _generate_key()
    hashed  = _hash_key(raw_key)

    user = await db.user.create(data={"email": email})
    await db.apikey.create(data={
        "userId": user.id,
        "key":    hashed,
        "label":  "default",
    })

    return {
        "user_id": user.id,
        "email":   user.email,
        "api_key": raw_key,  # shown once
    }


async def validate_api_key(raw_key: str) -> dict | None:
    # ── Dev mode ──────────────────────────────────────────────────────────────
    if ENVIRONMENT == "development":
        if raw_key == DEV_API_KEY:
            return {"id": DEV_USER_ID, "email": DEV_EMAIL}
        return None

    # ── Production ────────────────────────────────────────────────────────────
    from api.db.prisma import get_db
    db = await get_db()

    hashed = _hash_key(raw_key)
    key_record = await db.apikey.find_first(
        where={"key": hashed},
        include={"user": True},
    )

    if not key_record:
        return None

    await db.apikey.update(
        where={"id": key_record.id},
        data={"lastUsed": datetime.now(timezone.utc)},
    )

    return {"id": key_record.user.id, "email": key_record.user.email}


async def require_valid_key(raw_key: str) -> dict:
    user = await validate_api_key(raw_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    return user


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """
    Coexistence auth dependency.

    Order:
      1. Authorization: Bearer <jwt>  → validated against laboria-auth
      2. X-API-Key: <mnk_...>          → legacy path (unchanged)
      3. Otherwise → 401

    Returns a dict with a 'source' field: 'laboria-auth' or 'legacy'.
    Does NOT modify or replace require_valid_key.
    """
    # 1. Bearer JWT laboria-auth (priority)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Empty bearer token")

        # Local import to avoid any circular-import surprise.
        from api.services.laboria_auth import validate_laboria_token

        claims = await validate_laboria_token(token)
        if claims is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return {
            "source": "laboria-auth",
            "sub": claims.get("sub"),
            "email": claims.get("email"),
            "name": claims.get("name"),
            "plan": claims.get("plan", "free"),
            "organizations": claims.get("organizations", []),
            "active_org_id": claims.get("activeOrgId"),
        }

    # 2. Fallback X-API-Key legacy
    if x_api_key:
        user = await require_valid_key(x_api_key)
        # validate_api_key currently returns a dict; guard for object case anyway.
        user_fields = user if isinstance(user, dict) else getattr(user, "__dict__", {})
        return {
            "source": "legacy",
            "api_key": x_api_key,
            **user_fields,
        }

    raise HTTPException(status_code=401, detail="No authentication credentials provided")
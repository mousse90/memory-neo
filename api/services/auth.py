# memory-neo/api/services/auth.py
# Path: api/services/auth.py
# Purpose: API key creation, hashing, validation. Dev mode bypass. Supabase via Prisma.

import os
import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException

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
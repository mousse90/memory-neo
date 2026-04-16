# memory-neo/api/routes/auth.py
# Path: api/routes/auth.py

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr

from api.services.auth import create_user_with_key, validate_api_key, require_valid_key
from api.services.email import send_welcome_email, send_key_reminder

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr


class RegisterResponse(BaseModel):
    user_id:  str
    email:    str
    api_key:  str


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    """Create account + send API key by email via Resend."""
    result = await create_user_with_key(body.email)

    # Send welcome email non-blocking
    await send_welcome_email(
        to=result["email"],
        api_key=result["api_key"],
        user_id=result["user_id"],
    )

    return result


class ValidateResponse(BaseModel):
    user_id: str
    email:   str


@router.post("/validate")
async def validate(x_api_key: str = Header(..., alias="X-API-Key")):
    """Validate API key — called by CLI login."""
    user = await validate_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user_id": user["id"], "email": user["email"]}


class ForgotRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-key")
async def forgot_key(body: ForgotRequest):
    """
    Send API key reminder by email.
    Security: only sends if email exists — doesn't reveal if it doesn't.
    """
    import os
    if os.getenv("ENVIRONMENT", "development") == "development":
        raise HTTPException(status_code=501, detail="Not available in dev mode")

    from api.db.prisma import get_db
    db = await get_db()

    user = await db.user.find_unique(
        where={"email": body.email},
        include={"apiKeys": True},
    )

    if user and user.apiKeys:
        # We can't send the plaintext key (we only store hashes)
        # So we generate a new key and update the record
        import secrets, hashlib, os
        raw_key = "mnk_" + secrets.token_urlsafe(40)
        salt    = os.getenv("API_SECRET_SALT", "default_salt_change_me")
        hashed  = hashlib.sha256(f"{salt}{raw_key}".encode()).hexdigest()

        await db.apikey.update(
            where={"id": user.apiKeys[0].id},
            data={"key": hashed},
        )
        await send_key_reminder(to=body.email, api_key=raw_key)

    # Always return 200 — don't reveal if email exists
    return {"message": "If this email is registered, you'll receive your key shortly."}

# # memory-neo/api/routes/auth.py
# # Path: api/routes/auth.py
# # Purpose: Auth endpoints — register user, validate API key
# # Used by: CLI `memory-neo login` → POST /auth/validate

# from fastapi import APIRouter, HTTPException, Header
# from pydantic import BaseModel, EmailStr

# from api.services.auth import (
#     create_user_with_key,
#     validate_api_key,
# )

# router = APIRouter()


# class RegisterRequest(BaseModel):
#     email: EmailStr


# class RegisterResponse(BaseModel):
#     user_id: str
#     email: str
#     api_key: str          # shown once — user must save it


# @router.post("/register", response_model=RegisterResponse)
# async def register(body: RegisterRequest):
#     """
#     Create a new user and return their API key.
#     The key is shown once — not stored in plaintext.

#     Called by: web UI signup flow (future)
#     """
#     result = await create_user_with_key(body.email)
#     return result


# class ValidateResponse(BaseModel):
#     user_id: str
#     email: str


# @router.post("/validate")
# async def validate(x_api_key: str = Header(..., alias="X-API-Key")):
#     """
#     Validate an API key and return user info.
#     Called by: CLI `memory-neo login`
#     """
#     user = await validate_api_key(x_api_key)
#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid API key")
#     return {"user_id": user["id"], "email": user["email"]}

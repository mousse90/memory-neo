# memory-neo/api/routes/auth.py
# Path: api/routes/auth.py
# Purpose: Auth endpoints — register user, validate API key
# Used by: CLI `memory-neo login` → POST /auth/validate

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr

from api.services.auth import (
    create_user_with_key,
    validate_api_key,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    api_key: str          # shown once — user must save it


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    """
    Create a new user and return their API key.
    The key is shown once — not stored in plaintext.

    Called by: web UI signup flow (future)
    """
    result = await create_user_with_key(body.email)
    return result


class ValidateResponse(BaseModel):
    user_id: str
    email: str


@router.post("/validate")
async def validate(x_api_key: str = Header(..., alias="X-API-Key")):
    """
    Validate an API key and return user info.
    Called by: CLI `memory-neo login`
    """
    user = await validate_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user_id": user["id"], "email": user["email"]}

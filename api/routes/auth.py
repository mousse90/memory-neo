from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr
from api.services.otp import generate_otp, verify_otp, send_otp_email, generate_api_key
from api.services.auth import validate_api_key

router = APIRouter()

class SendCodeRequest(BaseModel):
    email: EmailStr

@router.post("/send-code")
async def send_code(body: SendCodeRequest):
    code = generate_otp(body.email)
    sent = await send_otp_email(body.email, code)
    if not sent:
        raise HTTPException(status_code=500, detail="Failed to send code")
    return {"message": "Code sent", "email": body.email}

class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str

@router.post("/verify-code")
async def verify_code(body: VerifyCodeRequest):
    if not verify_otp(body.email, body.code):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    from api.db.prisma import get_db
    db = await get_db()
    user = await db.user.find_unique(where={"email": body.email}, include={"apiKeys": True})
    if user:
        raw_key, hashed_key = generate_api_key()
        if user.apiKeys:
            await db.apikey.update(where={"id": user.apiKeys[0].id}, data={"key": hashed_key})
        else:
            await db.apikey.create(data={"key": hashed_key, "userId": user.id})
        return {"user_id": user.id, "email": user.email, "api_key": raw_key}
    raw_key, hashed_key = generate_api_key()
    new_user = await db.user.create(data={"email": body.email})
    await db.apikey.create(data={"key": hashed_key, "userId": new_user.id})
    return {"user_id": new_user.id, "email": new_user.email, "api_key": raw_key}

@router.post("/validate")
async def validate(x_api_key: str = Header(..., alias="X-API-Key")):
    user = await validate_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user_id": user["id"], "email": user["email"]}

@router.post("/regenerate-key")
async def regenerate_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Invalidate the caller's current API key and issue a fresh one."""
    user = await validate_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    from api.db.prisma import get_db
    db = await get_db()
    db_user = await db.user.find_unique(
        where={"email": user["email"]}, include={"apiKeys": True}
    )
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    raw_key, hashed_key = generate_api_key()
    if db_user.apiKeys:
        await db.apikey.update(
            where={"id": db_user.apiKeys[0].id}, data={"key": hashed_key}
        )
    else:
        await db.apikey.create(data={"key": hashed_key, "userId": db_user.id})
    return {"user_id": db_user.id, "email": db_user.email, "api_key": raw_key}

class RegisterRequest(BaseModel):
    email: EmailStr

@router.post("/register")
async def register(body: RegisterRequest):
    from api.db.prisma import get_db
    db = await get_db()
    existing = await db.user.find_unique(where={"email": body.email})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    raw_key, hashed_key = generate_api_key()
    user = await db.user.create(data={"email": body.email})
    await db.apikey.create(data={"key": hashed_key, "userId": user.id})
    return {"user_id": user.id, "email": user.email, "api_key": raw_key}

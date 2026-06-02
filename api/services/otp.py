import os
import random
import hashlib
import secrets
from datetime import datetime, timedelta
import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "memory-neo <onboarding@resend.dev>")
API_SECRET_SALT = os.getenv("API_SECRET_SALT", "default_salt_change_me")

_otp_store: dict[str, dict] = {}

def generate_otp(email: str) -> str:
    code = f"{random.randint(0, 999999):06d}"
    _otp_store[email.lower()] = {"code": code, "expires": datetime.utcnow() + timedelta(minutes=10), "attempts": 0}
    return code

def verify_otp(email: str, code: str) -> bool:
    entry = _otp_store.get(email.lower())
    if not entry: return False
    if entry["attempts"] >= 5:
        del _otp_store[email.lower()]
        return False
    entry["attempts"] += 1
    if datetime.utcnow() > entry["expires"]:
        del _otp_store[email.lower()]
        return False
    if entry["code"] != code.strip(): return False
    del _otp_store[email.lower()]
    return True

async def send_otp_email(to: str, code: str) -> bool:
    if not RESEND_API_KEY:
        print(f"[otp] No RESEND_API_KEY — code for {to}: {code}")
        return True
    html = f'<div style="font-family:monospace;max-width:480px;margin:0 auto;padding:40px;color:#c9d1d9;background:#0f1419"><div style="margin-bottom:32px"><span style="font-size:20px;font-weight:600">🧠 memory<span style="color:#00d4aa">-neo</span></span></div><p style="font-size:14px;line-height:1.8;margin-bottom:24px">Your verification code:</p><div style="background:#141a22;border:1px solid #00d4aa;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px"><div style="font-size:36px;font-weight:700;letter-spacing:12px;color:#00d4aa">{code}</div></div><p style="font-size:12px;color:#4a5568">This code expires in 10 minutes.</p></div>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}, json={"from": FROM_EMAIL, "to": [to], "subject": f"memory-neo: {code} is your verification code", "html": html}, timeout=10)
            if resp.status_code in (200, 201):
                return True
            print(f"[otp] Resend rejected: HTTP {resp.status_code} — {resp.text}")
            return False
    except Exception as e:
        print(f"[otp] Send failed: {e}")
        return False

def generate_api_key() -> tuple[str, str]:
    raw = "mnk_" + secrets.token_urlsafe(40)
    hashed = hashlib.sha256(f"{API_SECRET_SALT}{raw}".encode()).hexdigest()
    return raw, hashed

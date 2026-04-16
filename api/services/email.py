# memory-neo/api/services/email.py
# Path: api/services/email.py
# Purpose: Send transactional emails via Resend
# Called by: api/routes/auth.py after register

import os
import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "memory-neo <noreply@memory-neo.dev>")
APP_URL        = os.getenv("APP_URL", "https://memory-neo-ui.vercel.app")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


async def send_welcome_email(to: str, api_key: str, user_id: str) -> bool:
    """
    Send welcome email with API key after successful registration.
    Returns True if sent, False if skipped (dev mode or no Resend key).
    """
    if ENVIRONMENT == "development" or not RESEND_API_KEY:
        print(f"[email] Dev mode — skipping welcome email to {to}")
        return False

    body = f"""
<div style="font-family: 'IBM Plex Mono', monospace; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #c9d1d9; background: #0f1419;">

  <div style="margin-bottom: 32px;">
    <span style="font-size: 20px; font-weight: 600; letter-spacing: 1px;">🧠 memory<span style="color: #00d4aa;">-neo</span></span>
  </div>

  <p style="font-size: 14px; line-height: 1.8; margin-bottom: 24px;">
    Welcome to memory-neo. Your account is ready.
  </p>

  <div style="background: #141a22; border: 1px solid #1e2836; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
    <div style="font-size: 11px; color: #4a5568; margin-bottom: 8px; letter-spacing: 1px; text-transform: uppercase;">Your API key — save it now</div>
    <div style="font-size: 13px; color: #00d4aa; word-break: break-all; line-height: 1.6;">{api_key}</div>
  </div>

  <p style="font-size: 12px; color: #4a5568; line-height: 1.8; margin-bottom: 24px;">
    This key is shown once in the app and once here. If you lose it, generate a new one from your account settings.
  </p>

  <div style="background: #141a22; border: 1px solid #1e2836; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
    <div style="font-size: 11px; color: #4a5568; margin-bottom: 12px; letter-spacing: 1px; text-transform: uppercase;">Get started</div>
    <div style="font-size: 12px; line-height: 2.2; color: #c9d1d9;">
      <div><span style="color: #4a5568;">$</span> pip install memory-neo</div>
      <div><span style="color: #4a5568;">$</span> memory-neo login <span style="color: #4a5568;"># paste your key</span></div>
      <div><span style="color: #4a5568;">$</span> cd your-project</div>
      <div><span style="color: #4a5568;">$</span> memory-neo push my-project</div>
    </div>
  </div>

  <a href="{APP_URL}" style="display: inline-block; background: linear-gradient(135deg, #00d4aa, #0088ff); color: #0a0e14; text-decoration: none; padding: 10px 24px; border-radius: 8px; font-size: 12px; font-weight: 600; margin-bottom: 32px;">
    Open memory-neo →
  </a>

  <div style="border-top: 1px solid #1e2836; padding-top: 20px; font-size: 11px; color: #2d3748; line-height: 1.8;">
    <div>User ID: {user_id}</div>
    <div>Email: {to}</div>
  </div>

</div>
"""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from":    FROM_EMAIL,
                    "to":      [to],
                    "subject": "Your memory-neo API key",
                    "html":    body,
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                print(f"[email] Welcome email sent to {to}")
                return True
            else:
                print(f"[email] Resend error {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        print(f"[email] Send failed: {e}")
        return False


async def send_key_reminder(to: str, api_key: str) -> bool:
    """Send API key reminder email (forgot key flow)."""
    if ENVIRONMENT == "development" or not RESEND_API_KEY:
        return False

    body = f"""
<div style="font-family: 'IBM Plex Mono', monospace; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #c9d1d9; background: #0f1419;">
  <div style="margin-bottom: 32px;">
    <span style="font-size: 20px; font-weight: 600; letter-spacing: 1px;">🧠 memory<span style="color: #00d4aa;">-neo</span></span>
  </div>
  <p style="font-size: 14px; line-height: 1.8; margin-bottom: 24px;">You requested your API key.</p>
  <div style="background: #141a22; border: 1px solid #1e2836; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
    <div style="font-size: 11px; color: #4a5568; margin-bottom: 8px; letter-spacing: 1px; text-transform: uppercase;">Your API key</div>
    <div style="font-size: 13px; color: #00d4aa; word-break: break-all; line-height: 1.6;">{api_key}</div>
  </div>
  <a href="{APP_URL}/login" style="display: inline-block; background: linear-gradient(135deg, #00d4aa, #0088ff); color: #0a0e14; text-decoration: none; padding: 10px 24px; border-radius: 8px; font-size: 12px; font-weight: 600;">
    Login →
  </a>
</div>
"""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": FROM_EMAIL, "to": [to], "subject": "Your memory-neo API key", "html": body},
                timeout=10,
            )
            return resp.status_code in (200, 201)
    except Exception:
        return False
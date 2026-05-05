# memory-neo/api/services/laboria_auth.py
# Path: api/services/laboria_auth.py
# Purpose: Validate a Bearer JWT against the laboria-auth service.
#          Coexists with the legacy X-API-Key path in api/services/auth.py.

import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

LABORIA_AUTH_URL = os.getenv("LABORIA_AUTH_URL", "https://auth.laboria.io")
_VALIDATE_PATH = "/api/auth/validate"
_TIMEOUT_SECONDS = 5.0
_CACHE_TTL_SECONDS = 60.0

# Simple in-memory cache: token -> (claims, expires_at)
_cache: dict[str, tuple[dict, float]] = {}


def _cache_get(token: str) -> Optional[dict]:
    entry = _cache.get(token)
    if not entry:
        return None
    claims, expires_at = entry
    if time.monotonic() >= expires_at:
        _cache.pop(token, None)
        return None
    return claims


def _cache_set(token: str, claims: dict) -> None:
    _cache[token] = (claims, time.monotonic() + _CACHE_TTL_SECONDS)


async def validate_laboria_token(token: str) -> Optional[dict]:
    """
    Validate a JWT against the laboria-auth service.

    Returns the claims dict on success, or None on any failure
    (invalid token, network error, non-200 status). Never raises.

    Expected upstream response:
        {"valid": true, "claims": {...}}
        {"valid": false, "error": "..."}
    """
    if not token:
        return None

    cached = _cache_get(token)
    if cached is not None:
        return cached

    url = f"{LABORIA_AUTH_URL.rstrip('/')}{_VALIDATE_PATH}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json={"token": token})
    except httpx.TimeoutException:
        logger.error("laboria-auth validate timeout (%.1fs) for %s", _TIMEOUT_SECONDS, url)
        return None
    except httpx.HTTPError as exc:
        logger.error("laboria-auth validate network error: %s", exc)
        return None

    if resp.status_code != 200:
        logger.warning("laboria-auth validate non-200: %s %s", resp.status_code, resp.text[:200])
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.warning("laboria-auth validate returned non-JSON body")
        return None

    if not data.get("valid"):
        return None

    claims = data.get("claims")
    if not isinstance(claims, dict):
        logger.warning("laboria-auth validate missing/invalid claims field")
        return None

    _cache_set(token, claims)
    return claims

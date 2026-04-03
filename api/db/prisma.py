# memory-neo/api/db/prisma.py
# Path: api/db/prisma.py
# Purpose: Async Prisma client singleton — shared across all service calls
# Usage: from api.db.prisma import get_db

from prisma import Prisma

_client: Prisma | None = None


async def get_db() -> Prisma:
    """Return a connected Prisma client (lazy singleton)."""
    global _client
    if _client is None:
        _client = Prisma()
    if not _client.is_connected():
        await _client.connect()
    return _client


async def disconnect_db() -> None:
    global _client
    if _client and _client.is_connected():
        await _client.disconnect()
        _client = None
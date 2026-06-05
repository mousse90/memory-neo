# memory-neo/api/routes/nodes.py
# Path: api/routes/nodes.py
# Purpose: Ingest Memory nodes from memwar (graph bridge) + read endpoints
#          for lazy-load consumers (RePTiLS).

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.services.auth import require_auth, require_scope, resolve_principal
from api.services.graph import get_graph_client

router = APIRouter()


class Relationship(BaseModel):
    type: str = "HAS_MEMORY"
    from_label: str = "User"
    from_id: str | None = None


class MemoryNode(BaseModel):
    id: str
    content: str
    memory_type: str
    app_id: str
    user_id: str | None = None
    tags: list[str] = []
    created_at: str
    relationship: Relationship | None = None


@router.post("/nodes")
async def create_node(
    node: MemoryNode,
    auth: dict = Depends(require_auth),
):
    """Ingest a Memory node owned by the authenticated caller.

    Ownership is derived from the credential (`resolve_principal`) and is
    the SOLE source of the owner: the node and its
    `(:User)-[:HAS_MEMORY]->(:Memory)` edge are always written under that
    identity, never under a value taken from the payload.

    `user_id` and `relationship` are optional self-assertions, kept so the
    old full client shape still validates: if supplied they MUST equal the
    derived owner, otherwise `403`. Sent neither → the owner is derived
    silently and the edge defaults to `HAS_MEMORY` from the owner.

    No credential → `401`. Service principals need `memory-neo:nodes:write`
    (humans / legacy keys auto-pass).

    Migration note: this endpoint is NO LONGER open. dogydoc must send its
    owner credential (the account's X-API-Key, or a provisioned Bearer)
    BEFORE any real ingestion — until migrated, its writes will 401.
    """
    require_scope(auth, "memory-neo:nodes:write")
    owner, _ = resolve_principal(auth)

    # Optional self-assertions: a supplied user_id / from_id may only
    # confirm the derived owner — it can never select another principal.
    if node.user_id is not None and node.user_id != owner:
        raise HTTPException(status_code=403, detail="user_id mismatch")
    if (
        node.relationship is not None
        and node.relationship.from_id is not None
        and node.relationship.from_id != owner
    ):
        raise HTTPException(status_code=403, detail="from_id mismatch")

    driver = get_graph_client()
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (u:User {id: $owner})
                CREATE (m:`Memory` {
                    id:          $id,
                    content:     $content,
                    memory_type: $memory_type,
                    app_id:      $app_id,
                    user_id:     $owner,
                    tags:        $tags,
                    created_at:  $created_at
                })
                CREATE (u)-[:HAS_MEMORY]->(m)
                """,
                owner=owner,
                id=node.id,
                content=node.content,
                memory_type=node.memory_type,
                app_id=node.app_id,
                tags=node.tags,
                created_at=node.created_at,
            )
    finally:
        driver.close()

    return {"status": "created", "id": node.id}


# ── Read endpoints ───────────────────────────────────────────────────────────
#
# Routing note: GET /nodes/by-ids MUST be declared before GET /nodes/{user_id}
# — otherwise FastAPI matches "by-ids" as the path parameter `user_id`.

@router.get("/nodes/by-ids")
async def get_nodes_by_ids(
    ids: str = Query(..., description="Comma-separated Memory node ids"),
    auth: dict = Depends(require_auth),
):
    """Read a batch of Memory nodes by id — scoped to the CALLER's identity.

    The owner is derived from the credential (`resolve_principal`), never
    from a query param: a key holder reads only its own nodes. Any
    `user_id` still sent by older clients is ignored (FastAPI drops
    undeclared query params), so the contract is backward-compatible.

    Returns only the requested ids that exist AND belong to the caller —
    ids owned by another principal are silently filtered out (never
    leaked), unknown ids are skipped.
    """
    require_scope(auth, "memory-neo:nodes:read")
    owner, _ = resolve_principal(auth)

    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    if not id_list:
        return {"nodes": [], "count": 0}

    driver = get_graph_client()
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (u:User {id: $owner})-[:HAS_MEMORY]->(m:`Memory`)
                WHERE m.id IN $ids
                RETURN m.id AS id, m.content AS content,
                       m.memory_type AS memory_type, m.app_id AS app_id,
                       m.user_id AS user_id, m.tags AS tags,
                       m.created_at AS created_at
                """,
                owner=owner, ids=id_list,
            )
            nodes = [dict(record) for record in result]
    finally:
        driver.close()

    return {"nodes": nodes, "count": len(nodes)}


@router.get("/nodes/{user_id}")
async def get_nodes(
    user_id: str,
    auth: dict = Depends(require_auth),
):
    """List all Memory nodes owned by the CALLER, most recent first.

    Identity is derived from the credential (`resolve_principal`). The
    path `user_id` is a redundant self-assertion: it must equal the
    caller's own id, otherwise `403 user_id mismatch`. You can only list
    your own nodes — consistent with /context/{target}, /push, /query.
    """
    require_scope(auth, "memory-neo:nodes:read")
    owner, _ = resolve_principal(auth)
    if user_id != owner:
        raise HTTPException(status_code=403, detail="user_id mismatch")

    driver = get_graph_client()
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (u:User {id: $owner})-[:HAS_MEMORY]->(m:`Memory`)
                RETURN m.id AS id, m.content AS content,
                       m.memory_type AS memory_type, m.app_id AS app_id,
                       m.user_id AS user_id, m.tags AS tags,
                       m.created_at AS created_at
                ORDER BY m.created_at DESC
                """,
                owner=owner,
            )
            nodes = [dict(record) for record in result]
    finally:
        driver.close()

    return {"nodes": nodes, "count": len(nodes)}

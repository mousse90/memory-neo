# memory-neo/api/routes/context.py
# Path: api/routes/context.py
# Purpose:
#   - GET  /context/{target}  — fetch raw code of a function or file from Memgraph
#   - POST /context/index     — index a multimodal ContextSignature (Episode + axis nodes)
#   - POST /context/query     — query the parallel context graph by axis intersection/union
# Called by: CLI `memory-neo context <fn_or_file>`; RePTiLS MemoryNeoClient.

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field

from api.services.auth import (
    require_auth,
    require_scope,
    require_valid_key,
    resolve_principal,
)
from api.services.graph import fetch_context
from api.services.context_graph import (
    index_episode,
    query_episodes,
    hydrate_episodes,
    delete_episodes,
)

router = APIRouter()


class ContextResponse(BaseModel):
    target: str
    type: str                     # "function" | "file"
    source: str                   # file path
    language: str
    code: str
    start_line: int | None = None
    end_line: int | None = None


@router.get("/context/{target}", response_model=ContextResponse)
async def context(
    target: str,
    project_name: str = Query(...),
    user_id: str = Query(...),
    target_type: str = Query("auto"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Fetch the raw code for a named function or file path.

    target_type:
    - "auto"     → try function first, then file
    - "function" → MATCH (:Function {name: target, namespace: ns})
    - "file"     → MATCH (:File {name: target, namespace: ns})
                   OR MATCH (:File {path: target, namespace: ns})

    Returns code ready to paste into a prompt.
    """
    user = await require_valid_key(x_api_key)

    if user_id != user["id"]:
        raise HTTPException(status_code=403, detail="user_id mismatch")

    namespace = f"{user['id']}::{project_name}"

    result = await fetch_context(
        target=target,
        namespace=namespace,
        target_type=target_type,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"'{target}' not found in project '{project_name}'. Run `memory-neo push` first.",
        )

    return result


# ── POST /context/index ──────────────────────────────────────────────────────

class ContextSignaturePayload(BaseModel):
    when: datetime
    when_relative: str | None = None
    activity: str | None = None
    activity_object: str | None = None
    topic_tags: list[str] = Field(default_factory=list)
    where_label: str | None = None


class ContextIndexRequest(BaseModel):
    user_id: str | None = None
    episode_id: str
    signature: ContextSignaturePayload


class ContextIndexResponse(BaseModel):
    ok: bool
    episode_id: str
    nodes_created: int
    relations_created: int


@router.post("/context/index", response_model=ContextIndexResponse)
async def index_context(
    body: ContextIndexRequest,
    auth: dict = Depends(require_auth),
):
    """Index a ContextSignature into the parallel multimodal graph.

    Workflow:
      1. Authenticate via Bearer JWT (laboria-auth) or X-API-Key (legacy).
      2. Require scope `memory-neo:episodes:write` for service principals.
      3. Resolve scope (legacy → User.id, laboria-auth → claims.sub).
      4. If body.user_id is provided AND caller is legacy, enforce match.
      5. Upsert Episode + axis nodes + relations (idempotent).
    """
    require_scope(auth, "memory-neo:episodes:write")
    scope_uid, scope_tenant = resolve_principal(auth)

    # Preserve the legacy contract: a legacy caller passing a user_id
    # that doesn't match its own User.id is rejected. Service callers
    # write under their sub regardless of body.user_id.
    if (
        auth.get("source") == "legacy"
        and body.user_id is not None
        and body.user_id != scope_uid
    ):
        raise HTTPException(status_code=403, detail="user_id mismatch")

    result = await index_episode(
        user_id=scope_uid,
        episode_id=body.episode_id,
        signature=body.signature.model_dump(),
        tenant_id=scope_tenant,
    )
    return ContextIndexResponse(**result)


# ── POST /context/query ──────────────────────────────────────────────────────

class ContextQueryFilters(BaseModel):
    activity: list[str] | None = None
    topic_tags: list[str] | None = None
    activity_object: list[str] | None = None
    where_label: list[str] | None = None
    when_after: datetime | None = None
    when_before: datetime | None = None
    when_relative: str | None = None


class ContextQueryRequest(BaseModel):
    user_id: str | None = None
    filters: ContextQueryFilters = Field(default_factory=ContextQueryFilters)
    mode: Literal["intersection", "union"] = "intersection"
    limit: int = 50


class ContextQueryResponse(BaseModel):
    episode_ids: list[str]
    count: int
    matched_axes_per_episode: dict[str, list[str]]


@router.post("/context/query", response_model=ContextQueryResponse)
async def query_context(
    body: ContextQueryRequest,
    auth: dict = Depends(require_auth),
):
    """Query the parallel context graph.

    Mode:
      - intersection: episode must match every set axis
      - union:        episode must match at least one set axis

    Results are scoped to the caller's principal (User.id for legacy,
    claims.sub for laboria-auth). Episodes written under a different
    principal are never returned.
    """
    require_scope(auth, "memory-neo:episodes:read")
    scope_uid, _ = resolve_principal(auth)

    if (
        auth.get("source") == "legacy"
        and body.user_id is not None
        and body.user_id != scope_uid
    ):
        raise HTTPException(status_code=403, detail="user_id mismatch")

    result = await query_episodes(
        user_id=scope_uid,
        filters=body.filters.model_dump(),
        mode=body.mode,
        limit=body.limit,
    )
    return ContextQueryResponse(**result)


# ── POST /context/episodes/by-ids — hydration ────────────────────────────────

class EpisodeIdsBatch(BaseModel):
    episode_ids: list[str]


@router.post("/context/episodes/by-ids")
async def hydrate_context_episodes(
    body: EpisodeIdsBatch,
    auth: dict = Depends(require_auth),
):
    """Hydrate a batch of Episodes (full props + axes) for the recall layer.

    POST body (`{episode_ids: [...]}`) — no CSV-in-URL length ceiling.
    Identity derives from the credential (`resolve_principal`), same scoping
    as /context/query. Episodes owned by another principal are silently
    filtered (never leaked); unknown ids are skipped.

    Returns `{episodes: [{episode_id, when, when_relative, activity,
    activity_object, topic_tags, where_label, …}], count}`.
    """
    require_scope(auth, "memory-neo:episodes:read")
    scope_uid, _ = resolve_principal(auth)
    return await hydrate_episodes(user_id=scope_uid, episode_ids=body.episode_ids)


# ── DELETE /context/episodes/by-ids — scoped delete ──────────────────────────

@router.delete("/context/episodes/by-ids")
async def delete_context_episodes(
    ids: str = Query(..., description="Comma-separated Episode ids"),
    auth: dict = Depends(require_auth),
):
    """Delete the caller's Episodes (and their relations; shared axis nodes
    are preserved). Deletion is a write-class action → scope
    `memory-neo:episodes:write`. Ids of other principals / unknown are
    silently ignored. Returns `{deleted: n}`.
    """
    require_scope(auth, "memory-neo:episodes:write")
    scope_uid, _ = resolve_principal(auth)
    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    return await delete_episodes(user_id=scope_uid, episode_ids=id_list)

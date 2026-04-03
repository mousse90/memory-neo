# memory-neo/api/routes/context.py
# Path: api/routes/context.py
# Purpose: GET /context/{target} — fetch raw code of a function or file from Memgraph
# Called by: CLI `memory-neo context <fn_or_file>`

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

from api.services.auth import require_valid_key
from api.services.graph import fetch_context

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

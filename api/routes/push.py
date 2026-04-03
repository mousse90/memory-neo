# memory-neo/api/routes/push.py
# Path: api/routes/push.py
# Purpose: POST /push — receive scanned project, write to Memgraph + update Supabase project registry

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import os

from api.services.auth import require_valid_key
from api.services.graph import write_project_to_graph

router = APIRouter()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


class FunctionData(BaseModel):
    name: str
    start_line: int
    end_line: int
    docstring: str | None = None
    args: list[str] = []
    code: str
    is_async: bool = False


class FileData(BaseModel):
    file_name: str
    file_path: str
    extension: str
    lines: int
    content: str | None = None
    functions: list[FunctionData] = []


class PushRequest(BaseModel):
    project_name: str
    user_id: str
    files: list[FileData]


class PushResponse(BaseModel):
    status: str
    namespace: str
    nodes_created: int
    nodes_merged: int
    file_count: int
    function_count: int


@router.post("/push", response_model=PushResponse)
async def push(
    body: PushRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    user = await require_valid_key(x_api_key)

    if body.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="user_id mismatch")

    namespace = f"{user['id']}::{body.project_name}"
    fn_count  = sum(len(f.functions) for f in body.files)

    # Write to Memgraph
    result = await write_project_to_graph(
        namespace=namespace,
        project_name=body.project_name,
        files=[f.model_dump() for f in body.files],
    )

    # Update Supabase project registry (production only)
    if ENVIRONMENT == "production":
        try:
            from api.db.prisma import get_db
            db = await get_db()
            await db.project.upsert(
                where={"namespace": namespace},
                data={
                    "create": {
                        "userId":    user["id"],
                        "name":      body.project_name,
                        "namespace": namespace,
                        "fileCount": len(body.files),
                        "fnCount":   fn_count,
                    },
                    "update": {
                        "fileCount": len(body.files),
                        "fnCount":   fn_count,
                    },
                },
            )
            await db.pushlog.create(data={
                "userId":       user["id"],
                "projectName":  body.project_name,
                "fileCount":    len(body.files),
                "fnCount":      fn_count,
                "nodesCreated": result["created"],
                "nodesMerged":  result["merged"],
            })
        except Exception as e:
            # Non-blocking — Memgraph write already succeeded
            print(f"⚠ Supabase log failed (non-fatal): {e}")

    return PushResponse(
        status="ok",
        namespace=namespace,
        nodes_created=result["created"],
        nodes_merged=result["merged"],
        file_count=len(body.files),
        function_count=fn_count,
    )
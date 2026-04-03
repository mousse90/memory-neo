# memory-neo/api/routes/query.py
# Path: api/routes/query.py
# Purpose: POST /query — NLP question → Claude or GPT-4o → Cypher → Memgraph → results

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Literal

from api.services.auth import require_valid_key
from api.services.nlp import question_to_cypher, ModelChoice
from api.services.graph import run_cypher_query

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    project_name: str
    user_id: str
    model: ModelChoice = "claude"          # "claude" | "gpt-4o"


class QueryResponse(BaseModel):
    question: str
    cypher: str
    results: list[dict]
    result_count: int
    model: str


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Convert a natural language question to Cypher via Claude or GPT-4o,
    execute against the user's Memgraph namespace, return results.

    Flow:
      1. Validate API key
      2. Build namespace  → user_id::project_name
      3. Chosen LLM generates Cypher scoped to namespace
      4. Run Cypher on Memgraph
      5. Return results + which model was used
    """
    user = await require_valid_key(x_api_key)

    if body.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="user_id mismatch")

    namespace = f"{user['id']}::{body.project_name}"

    cypher = await question_to_cypher(
        question=body.question,
        namespace=namespace,
        model=body.model,
    )

    results = await run_cypher_query(cypher)

    return QueryResponse(
        question=body.question,
        cypher=cypher,
        results=results,
        result_count=len(results),
        model=body.model,
    )
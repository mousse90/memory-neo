# memory-neo/api/routes/query.py
# Path: api/routes/query.py

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Literal

from api.services.auth import require_valid_key
from api.services.nlp import question_to_cypher, ModelChoice
from api.services.graph import run_cypher_query
from api.services.agent import route_question, analyze_with_context

router = APIRouter()


class QueryRequest(BaseModel):
    question:     str
    project_name: str
    user_id:      str
    model:        ModelChoice = "claude"
    agent_mode:   bool = True


class QueryResponse(BaseModel):
    question:     str
    cypher:       str | None
    results:      list[dict]
    result_count: int
    model:        str
    mode:         str
    analysis:     str | None


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    user = await require_valid_key(x_api_key)
    if body.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="user_id mismatch")

    namespace = f"{user['id']}::{body.project_name}"

    mode = await route_question(body.question) if body.agent_mode else "cypher"

    if mode == "cypher":
        cypher = await question_to_cypher(question=body.question, namespace=namespace, model=body.model)
        results = await run_cypher_query(cypher)
        return QueryResponse(question=body.question, cypher=cypher, results=results, result_count=len(results), model=body.model, mode="cypher", analysis=None)

    # analyze mode — fetch broad context then Claude reasons on it
    context_cypher = f"""
        MATCH (f:File {{namespace: "{namespace}"}})
        OPTIONAL MATCH (f)-[:HAS_FUNCTION]->(fn:Function {{namespace: "{namespace}"}})
        RETURN f.path AS file, fn.name AS name, fn.start_line AS start_line, fn.end_line AS end_line, fn.code AS code
        LIMIT 30
    """
    context_results = await run_cypher_query(context_cypher)
    analysis = await analyze_with_context(question=body.question, context=context_results)

    return QueryResponse(question=body.question, cypher=None, results=context_results, result_count=len(context_results), model="claude", mode="analyze", analysis=analysis)

# # memory-neo/api/routes/query.py
# # Path: api/routes/query.py
# # Purpose: POST /query — NLP question → Claude or GPT-4o → Cypher → Memgraph → results

# from fastapi import APIRouter, HTTPException, Header
# from pydantic import BaseModel
# from typing import Literal

# from api.services.auth import require_valid_key
# from api.services.nlp import question_to_cypher, ModelChoice
# from api.services.graph import run_cypher_query

# router = APIRouter()


# class QueryRequest(BaseModel):
#     question: str
#     project_name: str
#     user_id: str
#     model: ModelChoice = "claude"          # "claude" | "gpt-4o"


# class QueryResponse(BaseModel):
#     question: str
#     cypher: str
#     results: list[dict]
#     result_count: int
#     model: str


# @router.post("/query", response_model=QueryResponse)
# async def query(
#     body: QueryRequest,
#     x_api_key: str = Header(..., alias="X-API-Key"),
# ):
#     """
#     Convert a natural language question to Cypher via Claude or GPT-4o,
#     execute against the user's Memgraph namespace, return results.

#     Flow:
#       1. Validate API key
#       2. Build namespace  → user_id::project_name
#       3. Chosen LLM generates Cypher scoped to namespace
#       4. Run Cypher on Memgraph
#       5. Return results + which model was used
#     """
#     user = await require_valid_key(x_api_key)

#     if body.user_id != user["id"]:
#         raise HTTPException(status_code=403, detail="user_id mismatch")

#     namespace = f"{user['id']}::{body.project_name}"

#     cypher = await question_to_cypher(
#         question=body.question,
#         namespace=namespace,
#         model=body.model,
#     )

#     results = await run_cypher_query(cypher)

#     return QueryResponse(
#         question=body.question,
#         cypher=cypher,
#         results=results,
#         result_count=len(results),
#         model=body.model,
#     )
# memory-neo/api/main.py
# Path: api/main.py

from dotenv import load_dotenv
import os
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.routes import push, query, context, auth, nodes
from api.services.auth import require_auth
from api.services.graph import get_graph_client

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    # Memgraph
    try:
        client = get_graph_client()
        client.verify_connectivity()
        print("✓ Memgraph connected")
        client.close()
    except Exception as e:
        print(f"✗ Memgraph connection failed: {e}")

    # Context graph schema (Episode + axis indexes — idempotent)
    try:
        from api.services.context_graph import init_context_schema
        stats = init_context_schema()
        print(f"✓ Context schema ready (indexes created={stats['indexes_created']}, skipped={stats['indexes_skipped']})")
    except Exception as e:
        print(f"⚠ Context schema init failed (non-fatal): {e}")

    # Supabase / Prisma (production only)
    if ENVIRONMENT == "production":
        try:
            from api.db.prisma import get_db
            await get_db()
            print("✓ Supabase (Prisma) connected")
        except Exception as e:
            print(f"✗ Supabase connection failed: {e}")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if ENVIRONMENT == "production":
        from api.db.prisma import disconnect_db
        await disconnect_db()
        print("✓ Supabase disconnected")


app = FastAPI(
    title="memory-neo API",
    description="Push codebase structure to Memgraph, query with natural language.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,    prefix="/auth", tags=["auth"])
app.include_router(push.router,    prefix="",      tags=["push"])
app.include_router(query.router,   prefix="",      tags=["query"])
app.include_router(context.router, prefix="",      tags=["context"])
app.include_router(nodes.router,   prefix="",      tags=["nodes"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "memory-neo-api", "version": "0.3.0"}


# Pilote B1bis — coexistence Bearer JWT laboria-auth + legacy X-API-Key.
# Bench-only endpoint; ne touche à aucun autre handler.
@app.get("/whoami")
async def whoami(auth: dict = Depends(require_auth)):
    return {
        "authenticated": True,
        "source": auth["source"],
        "email": auth.get("email"),
        "details": auth,
    }


@app.get("/graph/{project_name}")
async def get_graph(
    project_name: str,
    user_id: str,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    from api.services.auth import require_valid_key
    from api.services.graph import run_cypher_query
    await require_valid_key(x_api_key)
    namespace = f"{user_id}::{project_name}"
    results = await run_cypher_query(f"""
        MATCH (f:File {{namespace: "{namespace}"}})
        OPTIONAL MATCH (f)-[:HAS_FUNCTION]->(fn:Function {{namespace: "{namespace}"}})
        RETURN f.name AS file_name, f.path AS file_path, f.extension AS extension,
               f.lines AS lines, fn.name AS fn_name, fn.start_line AS start_line,
               fn.end_line AS end_line, fn.code AS code
        ORDER BY f.path, fn.start_line
    """)
    return {"results": results}


# List projects for authenticated user (from Supabase)
@app.get("/projects")
async def list_projects(
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    from api.services.auth import require_valid_key
    user = await require_valid_key(x_api_key)

    if ENVIRONMENT == "development":
        # In dev mode, query Memgraph directly for distinct namespaces
        from api.services.graph import run_cypher_query
        results = await run_cypher_query(f"""
            MATCH (p:Project)
            WHERE p.namespace STARTS WITH "{user['id']}::"
            RETURN p.name AS name, p.namespace AS namespace
        """)
        return {"projects": results}

    from api.db.prisma import get_db
    db = await get_db()
    projects = await db.project.find_many(
        where={"userId": user["id"]},
        order={"updatedAt": "desc"},
    )
    return {
        "projects": [
            {
                "name":      p.name,
                "namespace": p.namespace,
                "fileCount": p.fileCount,
                "fnCount":   p.fnCount,
                "updatedAt": p.updatedAt.isoformat(),
            }
            for p in projects
        ]
    }
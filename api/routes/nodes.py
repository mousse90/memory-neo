# memory-neo/api/routes/nodes.py
# Path: api/routes/nodes.py
# Purpose: Ingest Memory nodes from memwar (graph bridge)

from fastapi import APIRouter
from pydantic import BaseModel
from api.services.graph import get_graph_client

router = APIRouter()


class Relationship(BaseModel):
    type: str = "HAS_MEMORY"
    from_label: str = "User"
    from_id: str


class MemoryNode(BaseModel):
    id: str
    content: str
    memory_type: str
    app_id: str
    user_id: str
    tags: list[str] = []
    created_at: str
    relationship: Relationship


@router.post("/nodes")
async def create_node(node: MemoryNode):
    driver = get_graph_client()
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (u:User {id: $user_id})
                CREATE (m:Memory {
                    id:          $id,
                    content:     $content,
                    memory_type: $memory_type,
                    app_id:      $app_id,
                    user_id:     $user_id,
                    tags:        $tags,
                    created_at:  $created_at
                })
                CREATE (u)-[:HAS_MEMORY]->(m)
                """,
                id=node.id,
                content=node.content,
                memory_type=node.memory_type,
                app_id=node.app_id,
                user_id=node.user_id,
                tags=node.tags,
                created_at=node.created_at,
            )
    finally:
        driver.close()

    return {"status": "created", "id": node.id}


@router.get("/nodes/{user_id}")
async def get_nodes(user_id: str):
    driver = get_graph_client()
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory)
                RETURN m.id AS id, m.content AS content,
                       m.memory_type AS memory_type, m.app_id AS app_id,
                       m.user_id AS user_id, m.tags AS tags,
                       m.created_at AS created_at
                ORDER BY m.created_at DESC
                """,
                user_id=user_id,
            )
            nodes = [dict(record) for record in result]
    finally:
        driver.close()

    return {"nodes": nodes, "count": len(nodes)}

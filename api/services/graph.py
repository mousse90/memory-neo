# memory-neo/api/services/graph.py
# Path: api/services/graph.py
# Purpose: All Memgraph operations — write project graph, run Cypher, fetch context
# Uses: neo4j Python driver (compatible with Memgraph bolt protocol)
# Called by: api/routes/push.py, api/routes/query.py, api/routes/context.py

import os
from neo4j import GraphDatabase, Driver


# ── Driver ────────────────────────────────────────────────────────────────────

def get_graph_client() -> Driver:
    """
    Create a fresh Memgraph driver each call.
    No caching — avoids defunct connection issues after idle.
    """
    host = os.getenv("MEMGRAPH_HOST", "127.0.0.1")
    port = os.getenv("MEMGRAPH_PORT", "7687")
    user = os.getenv("MEMGRAPH_USERNAME", "")
    password = os.getenv("MEMGRAPH_PASSWORD", "")

    uri = f"bolt://{host}:{port}"
    auth = (user, password) if user else None

    return GraphDatabase.driver(
        uri,
        auth=auth,
        max_connection_lifetime=60,
        keep_alive=True,
        connection_timeout=10,
    )


# ── Write ─────────────────────────────────────────────────────────────────────

async def write_project_to_graph(
    namespace: str,
    project_name: str,
    files: list[dict],
) -> dict:
    """
    Write a full project structure to Memgraph.

    Node schema:
      (:Project  {namespace, name})
      (:File     {namespace, name, path, extension, lines, content})
      (:Function {namespace, name, file_path, start_line, end_line, code, docstring, args})

    Relationships:
      (:Project)-[:CONTAINS]->(:File)
      (:File)-[:HAS_FUNCTION]->(:Function)

    Uses MERGE to avoid duplicates on re-push.
    Returns counts of created vs merged nodes.
    """
    driver = get_graph_client()
    created = 0
    merged = 0

    try:
        with driver.session() as session:
            session.run(
                "MERGE (p:Project {namespace: $ns}) SET p.name = $name",
                ns=namespace, name=project_name,
            )

            for file in files:
                result = session.run(
                    """
                    MERGE (f:File {namespace: $ns, path: $path})
                    ON CREATE SET
                      f.name      = $name,
                      f.extension = $ext,
                      f.lines     = $lines,
                      f.content   = $content,
                      f._created  = true
                    ON MATCH SET
                      f.name      = $name,
                      f.extension = $ext,
                      f.lines     = $lines,
                      f.content   = $content,
                      f._created  = false
                    WITH f
                    MATCH (p:Project {namespace: $ns})
                    MERGE (p)-[:CONTAINS]->(f)
                    RETURN f._created AS was_created
                    """,
                    ns=namespace,
                    path=file["file_path"],
                    name=file["file_name"],
                    ext=file["extension"],
                    lines=file["lines"],
                    content=file.get("content") or "",
                )
                row = result.single()
                if row and row["was_created"]:
                    created += 1
                else:
                    merged += 1

                for fn in file.get("functions", []):
                    session.run(
                        """
                        MERGE (fn:Function {namespace: $ns, name: $name, file_path: $file_path})
                        SET
                          fn.start_line = $start,
                          fn.end_line   = $end,
                          fn.code       = $code,
                          fn.docstring  = $doc,
                          fn.args       = $args,
                          fn.is_async   = $is_async
                        WITH fn
                        MATCH (f:File {namespace: $ns, path: $file_path})
                        MERGE (f)-[:HAS_FUNCTION]->(fn)
                        """,
                        ns=namespace,
                        name=fn["name"],
                        file_path=file["file_path"],
                        start=fn["start_line"],
                        end=fn["end_line"],
                        code=fn["code"],
                        doc=fn.get("docstring") or "",
                        args=fn.get("args", []),
                        is_async=fn.get("is_async", False),
                    )
    finally:
        driver.close()

    return {"created": created, "merged": merged}


# ── Read ──────────────────────────────────────────────────────────────────────

async def run_cypher_query(cypher: str) -> list[dict]:
    """
    Execute a read-only Cypher query against Memgraph.
    Returns list of record dicts.
    """
    driver = get_graph_client()
    try:
        with driver.session() as session:
            result = session.run(cypher)
            return [dict(record) for record in result]
    finally:
        driver.close()


async def fetch_context(
    target: str,
    namespace: str,
    target_type: str = "auto",
) -> dict | None:
    """
    Fetch code for a named function or file path.
    Returns context dict or None if not found.
    """
    driver = get_graph_client()

    def _try_function(session):
        result = session.run(
            """
            MATCH (f:File {namespace: $ns})-[:HAS_FUNCTION]->(fn:Function {namespace: $ns, name: $name})
            RETURN fn.code AS code, fn.start_line AS start_line, fn.end_line AS end_line,
                   f.path AS source, f.extension AS ext
            LIMIT 1
            """,
            ns=namespace, name=target,
        )
        row = result.single()
        if row:
            ext = (row["ext"] or ".py").lstrip(".")
            return {
                "target": target,
                "type": "function",
                "source": row["source"],
                "language": ext,
                "code": row["code"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
            }
        return None

    def _try_file(session):
        result = session.run(
            """
            MATCH (f:File {namespace: $ns})
            WHERE f.name = $target OR f.path = $target
            RETURN f.content AS code, f.path AS source, f.extension AS ext
            LIMIT 1
            """,
            ns=namespace, target=target,
        )
        row = result.single()
        if row:
            ext = (row["ext"] or ".txt").lstrip(".")
            return {
                "target": target,
                "type": "file",
                "source": row["source"],
                "language": ext,
                "code": row["code"],
                "start_line": None,
                "end_line": None,
            }
        return None

    try:
        with driver.session() as session:
            if target_type == "function":
                return _try_function(session)
            elif target_type == "file":
                return _try_file(session)
            else:
                return _try_function(session) or _try_file(session)
    finally:
        driver.close()

# # memory-neo/api/services/graph.py
# # Path: api/services/graph.py
# # Purpose: All Memgraph operations — write project graph, run Cypher, fetch context
# # Uses: neo4j Python driver (compatible with Memgraph bolt protocol)
# # Called by: api/routes/push.py, api/routes/query.py, api/routes/context.py

# import os
# from neo4j import GraphDatabase, Driver
# from functools import lru_cache


# # ── Driver ────────────────────────────────────────────────────────────────────

# @lru_cache(maxsize=1)
# def get_graph_client() -> Driver:
#     """
#     Singleton Memgraph driver.
#     Memgraph uses the Bolt protocol — same driver as Neo4j.
#     """
#     host = os.getenv("MEMGRAPH_HOST", "localhost")
#     port = os.getenv("MEMGRAPH_PORT", "7687")
#     user = os.getenv("MEMGRAPH_USERNAME", "")
#     password = os.getenv("MEMGRAPH_PASSWORD", "")

#     uri = f"bolt://{host}:{port}"
#     auth = (user, password) if user else None

#     return GraphDatabase.driver(uri, auth=auth)


# # ── Write ─────────────────────────────────────────────────────────────────────

# async def write_project_to_graph(
#     namespace: str,
#     project_name: str,
#     files: list[dict],
# ) -> dict:
#     """
#     Write a full project structure to Memgraph.

#     Node schema:
#       (:Project  {namespace, name})
#       (:File     {namespace, name, path, extension, lines, content})
#       (:Function {namespace, name, file_path, start_line, end_line, code, docstring, args})

#     Relationships:
#       (:Project)-[:CONTAINS]->(:File)
#       (:File)-[:HAS_FUNCTION]->(:Function)

#     Uses MERGE to avoid duplicates on re-push.
#     Returns counts of created vs merged nodes.
#     """
#     driver = get_graph_client()
#     created = 0
#     merged = 0

#     with driver.session() as session:
#         # Upsert Project node
#         session.run(
#             "MERGE (p:Project {namespace: $ns}) SET p.name = $name",
#             ns=namespace, name=project_name,
#         )

#         for file in files:
#             # Upsert File node
#             result = session.run(
#                 """
#                 MERGE (f:File {namespace: $ns, path: $path})
#                 ON CREATE SET
#                   f.name      = $name,
#                   f.extension = $ext,
#                   f.lines     = $lines,
#                   f.content   = $content,
#                   f._created  = true
#                 ON MATCH SET
#                   f.name      = $name,
#                   f.extension = $ext,
#                   f.lines     = $lines,
#                   f.content   = $content,
#                   f._created  = false
#                 WITH f
#                 MATCH (p:Project {namespace: $ns})
#                 MERGE (p)-[:CONTAINS]->(f)
#                 RETURN f._created AS was_created
#                 """,
#                 ns=namespace,
#                 path=file["file_path"],
#                 name=file["file_name"],
#                 ext=file["extension"],
#                 lines=file["lines"],
#                 content=file.get("content") or "",
#             )
#             row = result.single()
#             if row and row["was_created"]:
#                 created += 1
#             else:
#                 merged += 1

#             # Upsert Function nodes
#             for fn in file.get("functions", []):
#                 session.run(
#                     """
#                     MERGE (fn:Function {namespace: $ns, name: $name, file_path: $file_path})
#                     SET
#                       fn.start_line = $start,
#                       fn.end_line   = $end,
#                       fn.code       = $code,
#                       fn.docstring  = $doc,
#                       fn.args       = $args,
#                       fn.is_async   = $is_async
#                     WITH fn
#                     MATCH (f:File {namespace: $ns, path: $file_path})
#                     MERGE (f)-[:HAS_FUNCTION]->(fn)
#                     """,
#                     ns=namespace,
#                     name=fn["name"],
#                     file_path=file["file_path"],
#                     start=fn["start_line"],
#                     end=fn["end_line"],
#                     code=fn["code"],
#                     doc=fn.get("docstring") or "",
#                     args=fn.get("args", []),
#                     is_async=fn.get("is_async", False),
#                 )

#     return {"created": created, "merged": merged}


# # ── Read ──────────────────────────────────────────────────────────────────────

# async def run_cypher_query(cypher: str) -> list[dict]:
#     """
#     Execute an arbitrary read-only Cypher query.
#     Returns list of record dicts.
#     """
#     driver = get_graph_client()
#     with driver.session() as session:
#         result = session.run(cypher)
#         return [dict(record) for record in result]


# async def fetch_context(
#     target: str,
#     namespace: str,
#     target_type: str = "auto",
# ) -> dict | None:
#     """
#     Fetch code for a named function or file path.
#     Returns context dict or None if not found.
#     """
#     driver = get_graph_client()

#     def _try_function(session):
#         result = session.run(
#             """
#             MATCH (f:File {namespace: $ns})-[:HAS_FUNCTION]->(fn:Function {namespace: $ns, name: $name})
#             RETURN fn.code AS code, fn.start_line AS start_line, fn.end_line AS end_line,
#                    f.path AS source, f.extension AS ext
#             LIMIT 1
#             """,
#             ns=namespace, name=target,
#         )
#         row = result.single()
#         if row:
#             ext = (row["ext"] or ".py").lstrip(".")
#             return {
#                 "target": target,
#                 "type": "function",
#                 "source": row["source"],
#                 "language": ext,
#                 "code": row["code"],
#                 "start_line": row["start_line"],
#                 "end_line": row["end_line"],
#             }
#         return None

#     def _try_file(session):
#         result = session.run(
#             """
#             MATCH (f:File {namespace: $ns})
#             WHERE f.name = $target OR f.path = $target
#             RETURN f.content AS code, f.path AS source, f.extension AS ext
#             LIMIT 1
#             """,
#             ns=namespace, target=target,
#         )
#         row = result.single()
#         if row:
#             ext = (row["ext"] or ".txt").lstrip(".")
#             return {
#                 "target": target,
#                 "type": "file",
#                 "source": row["source"],
#                 "language": ext,
#                 "code": row["code"],
#                 "start_line": None,
#                 "end_line": None,
#             }
#         return None

#     with driver.session() as session:
#         if target_type == "function":
#             return _try_function(session)
#         elif target_type == "file":
#             return _try_file(session)
#         else:  # auto
#             return _try_function(session) or _try_file(session)

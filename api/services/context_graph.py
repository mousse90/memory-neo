# memory-neo/api/services/context_graph.py
# Path: api/services/context_graph.py
# Purpose: Memgraph operations for the parallel multimodal "context" graph
#          (RePTiLS CONTEXT-SIGNATURE sprint).
#
# Nodes (in addition to existing Project/File/Function/Memory):
#   (:Episode        {id, scope_user_id, when})
#   (:Activity       {name, scope_user_id})
#   (:Topic          {name, scope_user_id})
#   (:ActivityObject {name, scope_user_id})
#   (:Where          {name, scope_user_id})
#   (:TimeSlot       {name, scope_user_id})
#
# Relations (Episode -> axis):
#   -[:OCCURRED_DURING]->  (:Activity)
#   -[:ON_TOPIC]->         (:Topic)
#   -[:ABOUT_OBJECT]->     (:ActivityObject)
#   -[:AT_LOCATION]->      (:Where)
#   -[:AT_TIMESLOT]->      (:TimeSlot)

from datetime import datetime
from typing import Any

from api.services.graph import get_graph_client


# ── Schema init ──────────────────────────────────────────────────────────────

_CONTEXT_INDEXES: list[tuple[str, str]] = [
    ("Episode",        "id"),
    ("Episode",        "scope_user_id"),
    ("Episode",        "when"),
    ("Activity",       "name"),
    ("Activity",       "scope_user_id"),
    ("Topic",          "name"),
    ("Topic",          "scope_user_id"),
    ("ActivityObject", "name"),
    ("ActivityObject", "scope_user_id"),
    ("Where",          "name"),
    ("Where",          "scope_user_id"),
    ("TimeSlot",       "name"),
    ("TimeSlot",       "scope_user_id"),
]


def init_context_schema() -> dict:
    """Create indexes for the context graph.

    Idempotent: re-running swallows 'index already exists' errors from
    Memgraph. UNIQUE constraints intentionally not used — MERGE provides
    upsert semantics and Memgraph's UNIQUE constraint syntax differs
    across versions.
    """
    driver = get_graph_client()
    created = 0
    skipped = 0
    try:
        with driver.session() as session:
            for label, prop in _CONTEXT_INDEXES:
                try:
                    session.run(f"CREATE INDEX ON :{label}({prop})")
                    created += 1
                except Exception:
                    # Index already exists (Memgraph throws on duplicate)
                    skipped += 1
    finally:
        driver.close()
    return {"indexes_created": created, "indexes_skipped": skipped}


# ── Index endpoint ───────────────────────────────────────────────────────────

# axis-key in payload -> (node label, relation type)
_SINGLE_VALUE_AXES: dict[str, tuple[str, str]] = {
    "activity":        ("Activity",       "OCCURRED_DURING"),
    "activity_object": ("ActivityObject", "ABOUT_OBJECT"),
    "where_label":     ("Where",          "AT_LOCATION"),
    "when_relative":   ("TimeSlot",       "AT_TIMESLOT"),
}


def _coerce_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def index_episode(
    user_id: str,
    episode_id: str,
    signature: dict,
    tenant_id: str | None = None,
) -> dict:
    """Upsert an Episode + axis nodes + relations.

    `user_id` is the scope key — the principal identity that owns the
    episode. Legacy callers pass User.id; service callers pass claims.sub.
    Episodes written under different principals live in disjoint scopes.

    `tenant_id` is optional and only persisted on the Episode (as
    `scope_tenant_id`) for forensic/multi-tenant queries; isolation
    still goes through `scope_user_id`.

    `signature` keys (all optional except `when`):
      - when           : datetime | str
      - when_relative  : str  ("morning", "weekend", ...)
      - activity       : str
      - activity_object: str
      - topic_tags     : list[str]
      - where_label    : str

    Re-indexing the same episode_id with the same axes is a no-op
    (idempotent). Re-indexing with new axes ADDS them — old relations
    are intentionally not removed (v1 keeps historical versioning).
    """
    when_iso = _coerce_iso(signature.get("when"))

    driver = get_graph_client()
    nodes_created = 0
    relations_created = 0

    try:
        with driver.session() as session:
            # 1. Upsert Episode
            row = session.run(
                """
                MERGE (e:Episode {id: $id, scope_user_id: $uid})
                ON CREATE SET e.when = $when,
                              e.scope_tenant_id = $tenant,
                              e._created = true
                ON MATCH  SET e.when = coalesce($when, e.when),
                              e.scope_tenant_id = coalesce($tenant, e.scope_tenant_id),
                              e._created = false
                RETURN e._created AS created
                """,
                id=episode_id, uid=user_id, when=when_iso, tenant=tenant_id,
            ).single()
            if row and row["created"]:
                nodes_created += 1

            # 2. Single-value axes
            for key, (label, rel) in _SINGLE_VALUE_AXES.items():
                value = signature.get(key)
                if not value:
                    continue
                axis_row = session.run(
                    f"""
                    MERGE (n:{label} {{name: $name, scope_user_id: $uid}})
                    ON CREATE SET n._created = true
                    ON MATCH  SET n._created = false
                    WITH n
                    MATCH (e:Episode {{id: $eid, scope_user_id: $uid}})
                    MERGE (e)-[r:{rel}]->(n)
                    ON CREATE SET r._created = true
                    ON MATCH  SET r._created = false
                    RETURN n._created AS n_created, r._created AS r_created
                    """,
                    name=value, uid=user_id, eid=episode_id,
                ).single()
                if axis_row:
                    if axis_row["n_created"]:
                        nodes_created += 1
                    if axis_row["r_created"]:
                        relations_created += 1

            # 3. Multi-value: topic_tags
            for tag in (signature.get("topic_tags") or []):
                if not tag:
                    continue
                t_row = session.run(
                    """
                    MERGE (t:Topic {name: $name, scope_user_id: $uid})
                    ON CREATE SET t._created = true
                    ON MATCH  SET t._created = false
                    WITH t
                    MATCH (e:Episode {id: $eid, scope_user_id: $uid})
                    MERGE (e)-[r:ON_TOPIC]->(t)
                    ON CREATE SET r._created = true
                    ON MATCH  SET r._created = false
                    RETURN t._created AS n_created, r._created AS r_created
                    """,
                    name=tag, uid=user_id, eid=episode_id,
                ).single()
                if t_row:
                    if t_row["n_created"]:
                        nodes_created += 1
                    if t_row["r_created"]:
                        relations_created += 1
    finally:
        driver.close()

    return {
        "ok": True,
        "episode_id": episode_id,
        "nodes_created": nodes_created,
        "relations_created": relations_created,
    }


# ── Query endpoint ───────────────────────────────────────────────────────────

def _normalize_list(v: Any) -> list[str] | None:
    if v is None:
        return None
    if isinstance(v, list):
        cleaned = [x for x in v if x]
        return cleaned or None
    if isinstance(v, str) and v:
        return [v]
    return None


async def query_episodes(
    user_id: str,
    filters: dict,
    mode: str = "intersection",
    limit: int = 50,
) -> dict:
    """Query episodes by axis filters.

    filters keys (all optional):
      - activity        : list[str]
      - topic_tags      : list[str]
      - activity_object : list[str]
      - where_label     : list[str]
      - when_after      : datetime | str (ISO)
      - when_before     : datetime | str (ISO)
      - when_relative   : str

    mode:
      - "intersection": episode must match every set axis
      - "union":        episode must match at least one set axis

    Returns:
      { episode_ids, count, matched_axes_per_episode }
    """
    activity        = _normalize_list(filters.get("activity"))
    topic_tags      = _normalize_list(filters.get("topic_tags"))
    activity_object = _normalize_list(filters.get("activity_object"))
    where_label     = _normalize_list(filters.get("where_label"))
    when_relative   = filters.get("when_relative") or None
    when_after      = _coerce_iso(filters.get("when_after"))
    when_before     = _coerce_iso(filters.get("when_before"))

    params: dict[str, Any] = {
        "uid":   user_id,
        "limit": int(limit),
    }

    # Always collect all axis values (needed for matched_axes_per_episode)
    base = """
    MATCH (e:Episode {scope_user_id: $uid})
    OPTIONAL MATCH (e)-[:OCCURRED_DURING]->(a:Activity {scope_user_id: $uid})
    OPTIONAL MATCH (e)-[:ABOUT_OBJECT]->(o:ActivityObject {scope_user_id: $uid})
    OPTIONAL MATCH (e)-[:AT_LOCATION]->(w:Where {scope_user_id: $uid})
    OPTIONAL MATCH (e)-[:AT_TIMESLOT]->(ts:TimeSlot {scope_user_id: $uid})
    OPTIONAL MATCH (e)-[:ON_TOPIC]->(t:Topic {scope_user_id: $uid})
    WITH e,
         collect(DISTINCT a.name) AS activities,
         collect(DISTINCT o.name) AS objects,
         collect(DISTINCT w.name) AS wheres,
         collect(DISTINCT ts.name) AS timeslots,
         collect(DISTINCT t.name) AS topics
    """

    # Build conditions
    conds: list[str] = []
    if activity is not None:
        conds.append("any(x IN activities WHERE x IN $f_activity)")
        params["f_activity"] = activity
    if activity_object is not None:
        conds.append("any(x IN objects WHERE x IN $f_object)")
        params["f_object"] = activity_object
    if where_label is not None:
        conds.append("any(x IN wheres WHERE x IN $f_where)")
        params["f_where"] = where_label
    if when_relative is not None:
        conds.append("$f_ts IN timeslots")
        params["f_ts"] = when_relative
    if topic_tags is not None:
        if mode == "intersection":
            # all requested topics must be on the episode
            conds.append("all(tag IN $f_topics WHERE tag IN topics)")
        else:
            conds.append("any(tag IN $f_topics WHERE tag IN topics)")
        params["f_topics"] = topic_tags
    if when_after is not None:
        conds.append("e.when >= $when_after")
        params["when_after"] = when_after
    if when_before is not None:
        conds.append("e.when <= $when_before")
        params["when_before"] = when_before

    if not conds:
        where_clause = ""
    elif mode == "intersection":
        where_clause = "WHERE " + " AND ".join(conds)
    else:  # union
        where_clause = "WHERE " + " OR ".join(conds)

    cypher = base + where_clause + """
    RETURN e.id AS id, e.when AS when,
           activities, objects, wheres, timeslots, topics
    ORDER BY e.when DESC
    LIMIT $limit
    """

    driver = get_graph_client()
    try:
        with driver.session() as session:
            result = session.run(cypher, **params)
            records = [dict(r) for r in result]
    finally:
        driver.close()

    episode_ids: list[str] = []
    matched: dict[str, list[str]] = {}

    for rec in records:
        eid = rec["id"]
        episode_ids.append(eid)
        axes: list[str] = []

        # Only include axis values that were constrained by the filter
        # (the "matched" axes for synthesis citation).
        if activity is not None:
            for v in (rec.get("activities") or []):
                if v and v in activity:
                    axes.append(f"activity:{v}")
        if topic_tags is not None:
            for v in (rec.get("topics") or []):
                if v and v in topic_tags:
                    axes.append(f"topic:{v}")
        if activity_object is not None:
            for v in (rec.get("objects") or []):
                if v and v in activity_object:
                    axes.append(f"object:{v}")
        if where_label is not None:
            for v in (rec.get("wheres") or []):
                if v and v in where_label:
                    axes.append(f"where:{v}")
        if when_relative is not None:
            if when_relative in (rec.get("timeslots") or []):
                axes.append(f"timeslot:{when_relative}")

        matched[eid] = axes

    return {
        "episode_ids": episode_ids,
        "count": len(episode_ids),
        "matched_axes_per_episode": matched,
    }

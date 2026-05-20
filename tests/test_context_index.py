# memory-neo/tests/test_context_index.py
# Path: tests/test_context_index.py
# Purpose: integration tests for POST /context/index — requires running Memgraph.

from datetime import datetime, timezone

from api.services.graph import get_graph_client


def _sig(**overrides) -> dict:
    base = {
        "when": datetime(2026, 5, 20, 10, 23, tzinfo=timezone.utc).isoformat(),
        "when_relative": "morning",
        "activity": "coding",
        "activity_object": "RePTiLS",
        "topic_tags": ["evanescence", "compression"],
        "where_label": "domicile",
    }
    base.update(overrides)
    return base


def _count(label: str, **props) -> int:
    driver = get_graph_client()
    try:
        with driver.session() as session:
            clause = " AND ".join(f"n.{k} = ${k}" for k in props.keys())
            cypher = f"MATCH (n:{label}) WHERE {clause} RETURN count(n) AS c"
            row = session.run(cypher, **props).single()
            return row["c"] if row else 0
    finally:
        driver.close()


def _rel_count(rel: str, episode_id: str, user_id: str) -> int:
    driver = get_graph_client()
    try:
        with driver.session() as session:
            row = session.run(
                f"""
                MATCH (e:Episode {{id: $eid, scope_user_id: $uid}})
                      -[r:{rel}]->()
                RETURN count(r) AS c
                """,
                eid=episode_id, uid=user_id,
            ).single()
            return row["c"] if row else 0
    finally:
        driver.close()


# ── 1. Episode + axis nodes created ──────────────────────────────────────────

def test_index_creates_episode_node(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index",
        headers=headers,
        json={"user_id": user_id, "episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["episode_id"] == episode_id
    assert _count("Episode", id=episode_id, scope_user_id=user_id) == 1


def test_index_creates_activity_node_and_relation(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={"user_id": user_id, "episode_id": episode_id,
              "signature": _sig(activity="coding")},
    )
    assert r.status_code == 200, r.text
    assert _count("Activity", name="coding", scope_user_id=user_id) == 1
    assert _rel_count("OCCURRED_DURING", episode_id, user_id) == 1


def test_index_creates_all_five_axis_types(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={"user_id": user_id, "episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code == 200, r.text
    assert _count("Activity",       name="coding",       scope_user_id=user_id) == 1
    assert _count("ActivityObject", name="RePTiLS",      scope_user_id=user_id) == 1
    assert _count("Where",          name="domicile",     scope_user_id=user_id) == 1
    assert _count("TimeSlot",       name="morning",      scope_user_id=user_id) == 1
    assert _count("Topic",          name="evanescence",  scope_user_id=user_id) == 1
    assert _count("Topic",          name="compression",  scope_user_id=user_id) == 1


# ── 2. Idempotence ───────────────────────────────────────────────────────────

def test_index_upsert_idempotent(client, headers, user_id, episode_id):
    sig = _sig()
    r1 = client.post("/context/index", headers=headers,
                     json={"user_id": user_id, "episode_id": episode_id, "signature": sig})
    r2 = client.post("/context/index", headers=headers,
                     json={"user_id": user_id, "episode_id": episode_id, "signature": sig})
    assert r1.status_code == 200 and r2.status_code == 200
    # second call should not create new nodes or relations
    assert r2.json()["nodes_created"] == 0
    assert r2.json()["relations_created"] == 0
    # single Episode node remains
    assert _count("Episode", id=episode_id, scope_user_id=user_id) == 1
    # single relation per axis
    assert _rel_count("OCCURRED_DURING", episode_id, user_id) == 1
    assert _rel_count("ABOUT_OBJECT",    episode_id, user_id) == 1


# ── 3. Multi-value topic_tags ────────────────────────────────────────────────

def test_index_multiple_topic_tags_creates_multiple_relations(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={
            "user_id": user_id, "episode_id": episode_id,
            "signature": _sig(topic_tags=["alpha", "beta", "gamma"]),
        },
    )
    assert r.status_code == 200, r.text
    assert _rel_count("ON_TOPIC", episode_id, user_id) == 3


# ── 4. Null / missing axes skipped ───────────────────────────────────────────

def test_index_null_axes_skipped(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={
            "user_id": user_id, "episode_id": episode_id,
            "signature": {
                "when": "2026-05-20T10:00:00Z",
                "activity": "reading",
                # all other axes omitted/null
            },
        },
    )
    assert r.status_code == 200, r.text
    assert _rel_count("OCCURRED_DURING", episode_id, user_id) == 1
    assert _rel_count("ABOUT_OBJECT",    episode_id, user_id) == 0
    assert _rel_count("AT_LOCATION",     episode_id, user_id) == 0
    assert _rel_count("AT_TIMESLOT",     episode_id, user_id) == 0
    assert _rel_count("ON_TOPIC",        episode_id, user_id) == 0


def test_index_empty_topic_tags_creates_no_topic_relations(client, headers, user_id, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={
            "user_id": user_id, "episode_id": episode_id,
            "signature": _sig(topic_tags=[]),
        },
    )
    assert r.status_code == 200, r.text
    assert _rel_count("ON_TOPIC", episode_id, user_id) == 0


# ── 5. Auth + validation ─────────────────────────────────────────────────────

def test_index_user_id_mismatch_returns_403(client, headers, episode_id):
    r = client.post(
        "/context/index", headers=headers,
        json={"user_id": "someone_else", "episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code == 403


def test_index_missing_api_key_returns_422_or_401(client, user_id, episode_id):
    # No X-API-Key header at all
    r = client.post(
        "/context/index",
        json={"user_id": user_id, "episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code in (401, 422)


def test_index_invalid_api_key_returns_401(client, user_id, episode_id):
    r = client.post(
        "/context/index",
        headers={"X-API-Key": "definitely-not-valid"},
        json={"user_id": user_id, "episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code == 401


def test_index_missing_required_fields_returns_422(client, headers):
    # Missing episode_id
    r = client.post(
        "/context/index", headers=headers,
        json={"signature": _sig()},
    )
    assert r.status_code == 422


def test_index_optional_user_id_defaults_to_caller(client, headers, user_id, episode_id):
    # Per spec: user_id is optional in the payload; if omitted, the
    # caller's id is used.
    r = client.post(
        "/context/index", headers=headers,
        json={"episode_id": episode_id, "signature": _sig()},
    )
    assert r.status_code == 200, r.text
    assert _count("Episode", id=episode_id, scope_user_id=user_id) == 1

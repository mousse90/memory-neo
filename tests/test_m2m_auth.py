# memory-neo/tests/test_m2m_auth.py
# Path: tests/test_m2m_auth.py
# Purpose: Integration tests for the laboria-auth M2M service path on
#          /context/index, /context/query, /nodes/{user_id}, /nodes/by-ids.
#
# Strategy: monkeypatch validate_laboria_token to return controlled claims
# (type, scopes, sub, orgId) so we don't need a real upstream JWT in local.
# These tests need Memgraph (asserted live by hitting the endpoints).

from datetime import datetime, timezone

import pytest


SERVICE_SUB = "svc_reptils_test"
SERVICE_ORG = "org_laboria"
LEGACY_UID = "usr_test"            # matches DEV_USER_ID in conftest.py
OTHER_LEGACY_UID = "usr_test_other"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bearer(token: str = "fake-bearer-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch_service(monkeypatch, *, scopes, sub=SERVICE_SUB, org_id=SERVICE_ORG):
    """Make validate_laboria_token return a service principal with `scopes`."""
    async def fake(token):
        return {
            "sub": sub,
            "type": "service",
            "scopes": list(scopes),
            "orgId": org_id,
        }
    # Patch the source module — auth.require_auth re-imports it each call.
    monkeypatch.setattr(
        "api.services.laboria_auth.validate_laboria_token", fake
    )
    # Also clear the laboria_auth in-memory cache so the patch wins.
    from api.services import laboria_auth
    laboria_auth._cache.clear()


def _patch_human(monkeypatch, *, sub="usr_human_jwt"):
    """Make validate_laboria_token return a human principal (no scopes)."""
    async def fake(token):
        return {
            "sub": sub,
            "type": "human",
            "email": "human@example.com",
        }
    monkeypatch.setattr(
        "api.services.laboria_auth.validate_laboria_token", fake
    )
    from api.services import laboria_auth
    laboria_auth._cache.clear()


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


# ── conftest extension — clean up service-scoped data after each test ───────

# User ids used as Memory owners across the node-read tests.
NODE_OWNERS = [
    SERVICE_SUB,            # service principal reads its OWN nodes (sub == owner)
    LEGACY_UID,            # legacy X-API-Key holder (usr_test) self-read
    "usr_other_owner",     # a different principal — leak guard
]


@pytest.fixture(autouse=True)
def cleanup_service_scope(memgraph_available):
    yield
    if not memgraph_available:
        return
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (n)
                WHERE n.scope_user_id = $uid
                  AND (n:Episode OR n:Activity OR n:Topic
                       OR n:ActivityObject OR n:Where OR n:TimeSlot)
                DETACH DELETE n
                """,
                uid=SERVICE_SUB,
            )
            # Clean Memory nodes created by the node-read tests. We delete
            # only the Memory (not the User): owner Users are re-created via
            # MERGE on the next seed, and this Memgraph build rejects the
            # `NOT (u)-[:HAS_MEMORY]->()` pattern predicate needed to prune
            # orphan Users. Orphans are harmless — reads match by edge.
            session.run(
                """
                MATCH (u:User)-[:HAS_MEMORY]->(m:`Memory`)
                WHERE u.id IN $owners
                DETACH DELETE m
                """,
                owners=NODE_OWNERS,
            )
    finally:
        driver.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. /context/index — service path
# ─────────────────────────────────────────────────────────────────────────────

def test_index_service_with_scope_writes_under_sub(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write"])

    eid = "ep-svc-write-1"
    r = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": eid, "signature": _sig()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["episode_id"] == eid

    # Verify the Episode is scoped under the service sub, not under any User.id.
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as session:
            row = session.run(
                "MATCH (e:Episode {id: $id}) "
                "RETURN e.scope_user_id AS sid, e.scope_tenant_id AS tid",
                id=eid,
            ).single()
    finally:
        driver.close()
    assert row is not None
    assert row["sid"] == SERVICE_SUB
    assert row["tid"] == SERVICE_ORG


def test_index_service_missing_scope_returns_403(client, monkeypatch):
    # Service has nodes:read but NOT episodes:write
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    r = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": "ep-no-scope", "signature": _sig()},
    )
    assert r.status_code == 403, r.text
    assert "memory-neo:episodes:write" in r.json()["detail"]


def test_index_service_invalid_token_returns_401(client, monkeypatch):
    async def fake(token):
        return None  # upstream says invalid/revoked
    monkeypatch.setattr(
        "api.services.laboria_auth.validate_laboria_token", fake
    )
    from api.services import laboria_auth
    laboria_auth._cache.clear()

    r = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": "ep-revoked", "signature": _sig()},
    )
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 2. /context/query — service path + isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_query_service_scope_required(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write"])  # not read

    r = client.post(
        "/context/query",
        headers=_bearer(),
        json={"filters": {}},
    )
    assert r.status_code == 403
    assert "memory-neo:episodes:read" in r.json()["detail"]


def test_query_service_isolation_from_legacy(
    client, headers, monkeypatch,
):
    """Episodes a service writes are not visible to a legacy caller, and
    legacy episodes are not visible to the service query."""
    # 1. Service writes ep-svc-iso-1
    _patch_service(
        monkeypatch,
        scopes=["memory-neo:episodes:write", "memory-neo:episodes:read"],
    )
    r1 = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": "ep-svc-iso-1", "signature": _sig(activity="coding")},
    )
    assert r1.status_code == 200, r1.text

    # 2. Legacy writes ep-legacy-iso-1 (different user, different scope)
    r2 = client.post(
        "/context/index",
        headers=headers,
        json={"episode_id": "ep-legacy-iso-1", "signature": _sig(activity="coding")},
    )
    assert r2.status_code == 200, r2.text

    # 3. Service query for activity=coding sees only its own episode
    r3 = client.post(
        "/context/query",
        headers=_bearer(),
        json={"filters": {"activity": ["coding"]}},
    )
    assert r3.status_code == 200, r3.text
    eids = set(r3.json()["episode_ids"])
    assert "ep-svc-iso-1" in eids
    assert "ep-legacy-iso-1" not in eids

    # 4. Legacy query for activity=coding sees only its own episode
    r4 = client.post(
        "/context/query",
        headers=headers,
        json={"filters": {"activity": ["coding"]}},
    )
    assert r4.status_code == 200, r4.text
    eids = set(r4.json()["episode_ids"])
    assert "ep-legacy-iso-1" in eids
    assert "ep-svc-iso-1" not in eids


# ─────────────────────────────────────────────────────────────────────────────
# 3. /nodes/{user_id} + /nodes/by-ids — service path
# ─────────────────────────────────────────────────────────────────────────────

def _seed_memory(user_id: str, node_id: str, content: str = "hello") -> None:
    """Insert one Memory node owned by user_id directly (bypassing POST /nodes
    which would also work but we test the read path in isolation).

    Note: `Memory` is backtick-escaped because newer Memgraph builds treat
    it as a reserved keyword. The label is identical with or without the
    backticks — older versions accept both."""
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (u:User {id: $uid})
                CREATE (m:`Memory` {
                    id: $id, content: $c, memory_type: 'context',
                    app_id: 'test', user_id: $uid, tags: [],
                    created_at: $ts
                })
                CREATE (u)-[:HAS_MEMORY]->(m)
                """,
                uid=user_id, id=node_id, c=content,
                ts=datetime.now(timezone.utc).isoformat(),
            )
    finally:
        driver.close()


def test_nodes_list_service_reads_own_sub(client, monkeypatch):
    """A service lists ITS OWN nodes (path user_id == claims.sub)."""
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    _seed_memory(SERVICE_SUB, "node-a-1", "alpha")
    _seed_memory(SERVICE_SUB, "node-a-2", "beta")

    r = client.get(f"/nodes/{SERVICE_SUB}", headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {n["id"] for n in body["nodes"]}
    assert ids == {"node-a-1", "node-a-2"}
    assert body["count"] == 2


def test_nodes_list_other_user_id_returns_403(client, monkeypatch):
    """Identity is derived from the key: listing another principal's nodes
    by putting their id in the path is rejected — never a data leak."""
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    _seed_memory("usr_other_owner", "node-secret", "not yours")

    r = client.get("/nodes/usr_other_owner", headers=_bearer())
    assert r.status_code == 403
    assert "mismatch" in r.json()["detail"]


def test_nodes_list_missing_scope_returns_403(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:read"])  # not nodes:read

    r = client.get(f"/nodes/{SERVICE_SUB}", headers=_bearer())
    assert r.status_code == 403
    assert "memory-neo:nodes:read" in r.json()["detail"]


def test_nodes_list_unauthenticated_returns_401(client):
    # No header at all — previously open, now closed.
    r = client.get(f"/nodes/{SERVICE_SUB}")
    assert r.status_code == 401


def test_nodes_by_ids_scoped_to_caller_never_leaks(client, monkeypatch):
    """by-ids returns ONLY the caller's nodes — an id owned by another
    principal is silently filtered out even when explicitly requested."""
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    _seed_memory(SERVICE_SUB, "node-mix-1", "owned-by-caller")
    _seed_memory("usr_other_owner", "node-mix-2", "owned-by-someone-else")

    # Ask for both ids — only the caller's own node may come back.
    r = client.get(
        "/nodes/by-ids",
        headers=_bearer(),
        params={"ids": "node-mix-1,node-mix-2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {n["id"] for n in body["nodes"]} == {"node-mix-1"}
    assert body["count"] == 1


def test_nodes_by_ids_legacy_key_reads_own_nodes(client, headers):
    """Done-criterion path: a legacy X-API-Key holder re-reads its OWN
    nodes (owner derived from the key == DEV_USER_ID == usr_test)."""
    _seed_memory(LEGACY_UID, "node-leg-1", "mine")
    _seed_memory(LEGACY_UID, "node-leg-2", "also mine")
    _seed_memory("usr_other_owner", "node-leg-other", "theirs")

    r = client.get(
        "/nodes/by-ids",
        headers=headers,  # X-API-Key
        params={"ids": "node-leg-1,node-leg-2,node-leg-other"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {n["id"] for n in body["nodes"]} == {"node-leg-1", "node-leg-2"}
    assert body["count"] == 2


def test_nodes_by_ids_stray_user_id_param_is_ignored(client, monkeypatch):
    """Backward-compat: an old client that still sends user_id does not
    break, and the param has NO effect — it can't redirect the scope to
    another principal's data."""
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    _seed_memory(SERVICE_SUB, "node-own", "caller's")
    _seed_memory("usr_other_owner", "node-foreign", "someone else's")

    r = client.get(
        "/nodes/by-ids",
        headers=_bearer(),
        # stray user_id points at another principal — must be ignored
        params={"ids": "node-own,node-foreign", "user_id": "usr_other_owner"},
    )
    assert r.status_code == 200, r.text
    assert {n["id"] for n in r.json()["nodes"]} == {"node-own"}


def test_nodes_by_ids_unknown_id_skipped(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    _seed_memory(SERVICE_SUB, "node-real", "exists")

    r = client.get(
        "/nodes/by-ids",
        headers=_bearer(),
        params={"ids": "node-real,does-not-exist"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {n["id"] for n in body["nodes"]} == {"node-real"}
    assert body["count"] == 1


def test_nodes_by_ids_empty_ids_returns_empty(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    r = client.get("/nodes/by-ids", headers=_bearer(), params={"ids": ""})
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "count": 0}


def test_nodes_by_ids_missing_ids_returns_422(client, monkeypatch):
    """`ids` stays required (422 when missing). Also a routing guard:
    GET /nodes/by-ids must not be captured by GET /nodes/{user_id}
    (which would treat 'by-ids' as a user_id and 200/403 instead)."""
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])

    r = client.get("/nodes/by-ids", headers=_bearer())  # no 'ids'
    assert r.status_code == 422


def test_nodes_by_ids_unauthenticated_returns_401(client):
    r = client.get("/nodes/by-ids", params={"ids": "whatever"})
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 4. Human laboria-auth — auto-pass (no scope required)
# ─────────────────────────────────────────────────────────────────────────────

def test_human_laboria_auth_passes_without_scopes(client, monkeypatch):
    _patch_human(monkeypatch, sub="usr_human_jwt_pass")

    r = client.post(
        "/context/query",
        headers=_bearer(),
        json={"filters": {}},
    )
    # No scopes required for humans (coexistence). Should be 200 with empty
    # result (no episodes under that sub yet).
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. POST /nodes — CLOSED: ownership derived from the credential
# ─────────────────────────────────────────────────────────────────────────────

def _memory_owner(node_id: str):
    """Return (edge_owner_id, m.user_id) for a Memory node, or (None, None).

    Proves the write went under the derived owner — both the
    (:User)-[:HAS_MEMORY]-> edge and the stored m.user_id."""
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as session:
            row = session.run(
                "MATCH (u:User)-[:HAS_MEMORY]->(m:`Memory` {id: $id}) "
                "RETURN u.id AS owner, m.user_id AS muid",
                id=node_id,
            ).single()
            return (row["owner"], row["muid"]) if row else (None, None)
    finally:
        driver.close()


def _node_body(node_id: str, **overrides) -> dict:
    body = {
        "id": node_id, "content": "hello", "memory_type": "context",
        "app_id": "test", "created_at": "2026-06-06T10:00:00Z",
    }
    body.update(overrides)
    return body


def test_post_nodes_no_credentials_returns_401(client):
    # Previously open; now closed. A valid body with no creds → 401.
    r = client.post("/nodes", json=_node_body("n-noauth"))
    assert r.status_code == 401


def test_post_nodes_legacy_key_owner_is_user_id(client, headers):
    nid = "n-legacy-own"
    r = client.post("/nodes", headers=headers, json=_node_body(nid))
    assert r.status_code == 200, r.text
    assert _memory_owner(nid) == (LEGACY_UID, LEGACY_UID)


def test_post_nodes_bearer_service_owner_is_sub(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:write"])
    nid = "n-svc-own"
    r = client.post("/nodes", headers=_bearer(), json=_node_body(nid))
    assert r.status_code == 200, r.text
    assert _memory_owner(nid) == (SERVICE_SUB, SERVICE_SUB)


def test_post_nodes_service_missing_scope_returns_403(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])  # not :write
    r = client.post("/nodes", headers=_bearer(), json=_node_body("n-svc-noscope"))
    assert r.status_code == 403
    assert "memory-neo:nodes:write" in r.json()["detail"]


def test_post_nodes_user_id_mismatch_returns_403(client, headers):
    r = client.post("/nodes", headers=headers,
                    json=_node_body("n-uid-mismatch", user_id="someone_else"))
    assert r.status_code == 403
    assert "user_id mismatch" in r.json()["detail"]


def test_post_nodes_from_id_mismatch_returns_403(client, headers):
    r = client.post("/nodes", headers=headers, json=_node_body(
        "n-fid-mismatch",
        relationship={"type": "HAS_MEMORY", "from_label": "User",
                      "from_id": "someone_else"}))
    assert r.status_code == 403
    assert "from_id mismatch" in r.json()["detail"]


def test_post_nodes_minimal_payload_derives_owner(client, headers):
    # No user_id, no relationship → owner derived purely from the key.
    nid = "n-minimal"
    r = client.post("/nodes", headers=headers, json=_node_body(nid))
    assert r.status_code == 200, r.text
    assert _memory_owner(nid) == (LEGACY_UID, LEGACY_UID)


def test_post_nodes_legacy_full_shape_matching_owner_ok(client, headers):
    # The old full client shape, correctly asserting its own owner, still works.
    nid = "n-fullshape"
    r = client.post("/nodes", headers=headers, json=_node_body(
        nid, user_id=LEGACY_UID,
        relationship={"type": "HAS_MEMORY", "from_label": "User",
                      "from_id": LEGACY_UID}))
    assert r.status_code == 200, r.text
    assert _memory_owner(nid)[0] == LEGACY_UID


# ─────────────────────────────────────────────────────────────────────────────
# 6. Unified auth matrix — one dependency accepts X-API-Key OR Bearer M2M,
#    rejects no/invalid creds with 401. /context/index proves the schism is
#    closed: a key holder can index with the SAME key it reads nodes with.
# ─────────────────────────────────────────────────────────────────────────────

def test_context_index_with_x_api_key_returns_200(client, headers, monkeypatch):
    """The crux of the sprint: /context/index accepts X-API-Key (legacy)
    and 200s — no longer Bearer-only, no 403."""
    r = client.post(
        "/context/index",
        headers=headers,  # X-API-Key
        json={"episode_id": "ep-unified-key", "signature": _sig()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["episode_id"] == "ep-unified-key"


def test_context_index_with_bearer_service_returns_200(client, monkeypatch):
    """Same endpoint, Bearer M2M with the write scope → 200. Both
    credential families flow through the one dependency."""
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write"])
    r = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": "ep-unified-bearer", "signature": _sig()},
    )
    assert r.status_code == 200, r.text


def test_context_index_no_credentials_returns_401(client):
    r = client.post(
        "/context/index",
        json={"episode_id": "ep-unified-none", "signature": _sig()},
    )
    assert r.status_code == 401


def test_context_index_invalid_key_returns_401(client):
    r = client.post(
        "/context/index",
        headers={"X-API-Key": "definitely-not-valid"},
        json={"episode_id": "ep-unified-badkey", "signature": _sig()},
    )
    assert r.status_code == 401


def test_context_index_invalid_bearer_returns_401(client, monkeypatch):
    async def fake(token):
        return None  # upstream rejects
    monkeypatch.setattr("api.services.laboria_auth.validate_laboria_token", fake)
    from api.services import laboria_auth
    laboria_auth._cache.clear()

    r = client.post(
        "/context/index",
        headers=_bearer(),
        json={"episode_id": "ep-unified-badbearer", "signature": _sig()},
    )
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 7. NODE-OWNERSHIP recall surfaces — hydration, batch read, scoped deletes
# ─────────────────────────────────────────────────────────────────────────────

def _episode_exists(eid: str, uid: str) -> bool:
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as s:
            row = s.run(
                "MATCH (e:Episode {id: $id, scope_user_id: $uid}) RETURN count(e) AS c",
                id=eid, uid=uid,
            ).single()
            return (row["c"] if row else 0) > 0
    finally:
        driver.close()


def _axis_count(label: str, name: str, uid: str) -> int:
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as s:
            row = s.run(
                f"MATCH (n:{label} {{name: $name, scope_user_id: $uid}}) "
                "RETURN count(n) AS c",
                name=name, uid=uid,
            ).single()
            return row["c"] if row else 0
    finally:
        driver.close()


# ── POST /context/episodes/by-ids — hydration ────────────────────────────────

def test_hydrate_episodes_returns_props_and_axes(client, headers, user_id):
    eid = "ep-hyd-1"
    assert client.post("/context/index", headers=headers,
                       json={"episode_id": eid, "signature": _sig()}).status_code == 200
    r = client.post("/context/episodes/by-ids", headers=headers,
                    json={"episode_ids": [eid]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    ep = body["episodes"][0]
    assert ep["episode_id"] == eid
    assert ep["scope_user_id"] == user_id
    assert "when" in ep                       # stored Episode property
    assert ep["activity"] == "coding"
    assert ep["activity_object"] == "RePTiLS"
    assert ep["where_label"] == "domicile"
    assert ep["when_relative"] == "morning"
    assert set(ep["topic_tags"]) == {"evanescence", "compression"}


def test_hydrate_episodes_scoped_never_leaks(client, headers, monkeypatch):
    assert client.post("/context/index", headers=headers,
                       json={"episode_id": "ep-hyd-legacy", "signature": _sig()}).status_code == 200
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write", "memory-neo:episodes:read"])
    assert client.post("/context/index", headers=_bearer(),
                       json={"episode_id": "ep-hyd-svc", "signature": _sig()}).status_code == 200
    # legacy hydrates BOTH ids (+ an unknown) → only its own comes back
    r = client.post("/context/episodes/by-ids", headers=headers,
                    json={"episode_ids": ["ep-hyd-legacy", "ep-hyd-svc", "ep-unknown"]})
    assert r.status_code == 200, r.text
    assert {e["episode_id"] for e in r.json()["episodes"]} == {"ep-hyd-legacy"}


def test_hydrate_episodes_large_batch_no_url_ceiling(client, headers):
    assert client.post("/context/index", headers=headers,
                       json={"episode_id": "ep-hyd-big", "signature": _sig()}).status_code == 200
    ids = [f"ep-fake-{i}" for i in range(120)] + ["ep-hyd-big"]   # 121 ids in the body
    r = client.post("/context/episodes/by-ids", headers=headers,
                    json={"episode_ids": ids})
    assert r.status_code == 200, r.text
    assert {e["episode_id"] for e in r.json()["episodes"]} == {"ep-hyd-big"}


def test_hydrate_episodes_missing_scope_403(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write"])  # not read
    r = client.post("/context/episodes/by-ids", headers=_bearer(),
                    json={"episode_ids": ["x"]})
    assert r.status_code == 403
    assert "memory-neo:episodes:read" in r.json()["detail"]


def test_hydrate_episodes_unauthenticated_401(client):
    r = client.post("/context/episodes/by-ids", json={"episode_ids": ["x"]})
    assert r.status_code == 401


# ── POST /nodes/by-ids — parity with GET + scoping ───────────────────────────

def test_post_nodes_by_ids_parity_with_get(client, headers):
    _seed_memory(LEGACY_UID, "p-1", "a")
    _seed_memory(LEGACY_UID, "p-2", "b")
    g = client.get("/nodes/by-ids", headers=headers, params={"ids": "p-1,p-2"})
    p = client.post("/nodes/by-ids", headers=headers, json={"ids": ["p-1", "p-2"]})
    assert g.status_code == 200 and p.status_code == 200, (g.text, p.text)
    assert g.json() == p.json()
    assert {n["id"] for n in p.json()["nodes"]} == {"p-1", "p-2"}


def test_post_nodes_by_ids_scoped_never_leaks(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])
    _seed_memory(SERVICE_SUB, "pmix-mine", "mine")
    _seed_memory("usr_other_owner", "pmix-other", "theirs")
    r = client.post("/nodes/by-ids", headers=_bearer(),
                    json={"ids": ["pmix-mine", "pmix-other"]})
    assert r.status_code == 200, r.text
    assert {n["id"] for n in r.json()["nodes"]} == {"pmix-mine"}


def test_post_nodes_by_ids_unauthenticated_401(client):
    r = client.post("/nodes/by-ids", json={"ids": ["x"]})
    assert r.status_code == 401


# ── DELETE /nodes/by-ids — scoped delete ─────────────────────────────────────

def test_delete_nodes_by_ids_only_caller(client, headers):
    _seed_memory(LEGACY_UID, "del-mine-1", "m1")
    _seed_memory(LEGACY_UID, "del-mine-2", "m2")
    _seed_memory("usr_other_owner", "del-other", "o")
    r = client.delete("/nodes/by-ids", headers=headers,
                      params={"ids": "del-mine-1,del-mine-2,del-other,del-unknown"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2}
    # caller's gone, another principal's untouched
    g = client.get("/nodes/by-ids", headers=headers,
                   params={"ids": "del-mine-1,del-mine-2"})
    assert g.json()["count"] == 0
    assert _memory_owner("del-other")[0] == "usr_other_owner"


def test_delete_nodes_by_ids_missing_scope_403(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:nodes:read"])  # not :write
    r = client.delete("/nodes/by-ids", headers=_bearer(), params={"ids": "x"})
    assert r.status_code == 403
    assert "memory-neo:nodes:write" in r.json()["detail"]


def test_delete_nodes_by_ids_unauthenticated_401(client):
    r = client.delete("/nodes/by-ids", params={"ids": "x"})
    assert r.status_code == 401


# ── DELETE /context/episodes/by-ids — scoped, axes preserved ─────────────────

def test_delete_episodes_only_caller_preserves_axes(client, headers, monkeypatch):
    assert client.post("/context/index", headers=headers,
                       json={"episode_id": "ep-del-legacy",
                             "signature": _sig(activity="coding")}).status_code == 200
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:write"])
    assert client.post("/context/index", headers=_bearer(),
                       json={"episode_id": "ep-del-svc",
                             "signature": _sig(activity="coding")}).status_code == 200
    # legacy deletes BOTH ids (+ unknown) → only its own removed
    r = client.delete("/context/episodes/by-ids", headers=headers,
                      params={"ids": "ep-del-legacy,ep-del-svc,ep-unknown"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1}
    assert not _episode_exists("ep-del-legacy", LEGACY_UID)
    assert _episode_exists("ep-del-svc", SERVICE_SUB)            # other scope untouched
    # the shared axis node (Activity 'coding', caller's scope) is preserved
    assert _axis_count("Activity", "coding", LEGACY_UID) >= 1


def test_delete_episodes_missing_scope_403(client, monkeypatch):
    _patch_service(monkeypatch, scopes=["memory-neo:episodes:read"])  # not :write
    r = client.delete("/context/episodes/by-ids", headers=_bearer(), params={"ids": "x"})
    assert r.status_code == 403
    assert "memory-neo:episodes:write" in r.json()["detail"]

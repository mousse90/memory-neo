# memory-neo/tests/test_graph_guard.py
# Path: tests/test_graph_guard.py
# Purpose: GET /graph/{project_name} + GET /projects (dev) —
#   credential-derived namespace + parameterized Cypher (no f-string injection).
#   Needs Memgraph for the 200 paths (auto-SKIP via conftest when down).


# ── GET /graph — auth guard ──────────────────────────────────────────────────

def test_graph_missing_key_returns_401_or_422(client):
    # X-API-Key is a required header → missing credentials are rejected.
    r = client.get("/graph/some-project", params={"user_id": "usr_test"})
    assert r.status_code in (401, 422)


def test_graph_user_id_mismatch_returns_403(client, headers):
    r = client.get(
        "/graph/some-project",
        params={"user_id": "someone_else"},
        headers=headers,
    )
    assert r.status_code == 403
    assert "user_id mismatch" in r.json()["detail"]


def test_graph_own_user_id_returns_200(client, headers, user_id):
    r = client.get(
        "/graph/some-project",
        params={"user_id": user_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "results" in r.json()


# ── GET /graph — Cypher injection neutralized by $namespace binding ───────────

def test_graph_namespace_injection_is_neutralized(client, headers, user_id):
    """A project_name crafted to break out of a string-interpolated query is
    bound as literal data ($namespace), never executed as Cypher. The query
    returns 200 with empty results (no File matches that literal namespace),
    and never errors or leaks injected rows. (No '/' in the payload — that
    would change path routing, not the query.)"""
    r = client.get(
        '/graph/x" RETURN 1 AS pwned',
        params={"user_id": user_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"] == []


# ── GET /projects (dev branch) — $prefix binding ─────────────────────────────

def test_projects_dev_returns_200(client, headers):
    r = client.get("/projects", headers=headers)
    assert r.status_code == 200
    assert "projects" in r.json()

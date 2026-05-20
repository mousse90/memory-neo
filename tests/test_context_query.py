# memory-neo/tests/test_context_query.py
# Path: tests/test_context_query.py
# Purpose: integration tests for POST /context/query — requires running Memgraph.

from datetime import datetime, timedelta, timezone

import pytest


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


@pytest.fixture
def seeded_episodes(client, headers, user_id):
    """Seed 4 episodes covering different axis combinations."""
    base = datetime(2026, 5, 20, 9, 0)
    episodes = [
        # ep-1: coding on RePTiLS, topics evanescence+compression, morning, domicile
        ("ep-q-1", {
            "when": _iso(base),
            "when_relative": "morning",
            "activity": "coding",
            "activity_object": "RePTiLS",
            "topic_tags": ["evanescence", "compression"],
            "where_label": "domicile",
        }),
        # ep-2: coding on YuLovePDF, topic compression, afternoon, bureau
        ("ep-q-2", {
            "when": _iso(base + timedelta(hours=4)),
            "when_relative": "afternoon",
            "activity": "coding",
            "activity_object": "YuLovePDF",
            "topic_tags": ["compression"],
            "where_label": "bureau",
        }),
        # ep-3: reading, topic evanescence, evening, domicile (no activity_object)
        ("ep-q-3", {
            "when": _iso(base + timedelta(days=1)),
            "when_relative": "evening",
            "activity": "reading",
            "topic_tags": ["evanescence"],
            "where_label": "domicile",
        }),
        # ep-4: meeting on YuLovePDF, morning, bureau (no topics)
        ("ep-q-4", {
            "when": _iso(base + timedelta(days=2)),
            "when_relative": "morning",
            "activity": "meeting",
            "activity_object": "YuLovePDF",
            "topic_tags": [],
            "where_label": "bureau",
        }),
    ]
    for eid, sig in episodes:
        r = client.post(
            "/context/index", headers=headers,
            json={"user_id": user_id, "episode_id": eid, "signature": sig},
        )
        assert r.status_code == 200, r.text
    return [eid for eid, _ in episodes]


def _query(client, headers, user_id, **payload) -> dict:
    body = {"user_id": user_id, **payload}
    r = client.post("/context/query", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Intersection ──────────────────────────────────────────────────────────

def test_query_intersection_returns_episodes_matching_all_axes(
    client, headers, user_id, seeded_episodes,
):
    # coding AND topic=evanescence → only ep-q-1
    res = _query(client, headers, user_id, filters={
        "activity": ["coding"], "topic_tags": ["evanescence"],
    }, mode="intersection")
    assert set(res["episode_ids"]) == {"ep-q-1"}
    assert res["count"] == 1


def test_query_intersection_requires_all_topic_tags(
    client, headers, user_id, seeded_episodes,
):
    # topics evanescence AND compression → only ep-q-1 (ep-q-2 has only compression)
    res = _query(client, headers, user_id, filters={
        "topic_tags": ["evanescence", "compression"],
    }, mode="intersection")
    assert set(res["episode_ids"]) == {"ep-q-1"}


def test_query_intersection_multivalue_activity(
    client, headers, user_id, seeded_episodes,
):
    # activity IN (coding, reading) → ep-q-1, ep-q-2, ep-q-3
    res = _query(client, headers, user_id, filters={
        "activity": ["coding", "reading"],
    }, mode="intersection")
    assert set(res["episode_ids"]) == {"ep-q-1", "ep-q-2", "ep-q-3"}


# ── 2. Union ─────────────────────────────────────────────────────────────────

def test_query_union_returns_episodes_matching_any_axis(
    client, headers, user_id, seeded_episodes,
):
    # activity=reading OR object=YuLovePDF → ep-q-2, ep-q-3, ep-q-4
    res = _query(client, headers, user_id, filters={
        "activity": ["reading"], "activity_object": ["YuLovePDF"],
    }, mode="union")
    assert set(res["episode_ids"]) == {"ep-q-2", "ep-q-3", "ep-q-4"}


# ── 3. Temporal filters ──────────────────────────────────────────────────────

def test_query_temporal_filter(client, headers, user_id, seeded_episodes):
    # Only episodes from base+1d onwards → ep-q-3, ep-q-4
    after = _iso(datetime(2026, 5, 21, 0, 0))
    res = _query(client, headers, user_id, filters={
        "when_after": after,
    })
    assert set(res["episode_ids"]) == {"ep-q-3", "ep-q-4"}


def test_query_when_relative_filter(client, headers, user_id, seeded_episodes):
    res = _query(client, headers, user_id, filters={"when_relative": "morning"})
    assert set(res["episode_ids"]) == {"ep-q-1", "ep-q-4"}


# ── 4. Edge cases ────────────────────────────────────────────────────────────

def test_query_no_filters_returns_recent_episodes(
    client, headers, user_id, seeded_episodes,
):
    res = _query(client, headers, user_id, filters={})
    assert set(res["episode_ids"]) == set(seeded_episodes)
    assert res["count"] == 4


def test_query_empty_result_returns_empty_list(
    client, headers, user_id, seeded_episodes,
):
    res = _query(client, headers, user_id, filters={
        "activity": ["sleeping"],
    })
    assert res["episode_ids"] == []
    assert res["count"] == 0
    assert res["matched_axes_per_episode"] == {}


def test_query_empty_list_filter_ignored(client, headers, user_id, seeded_episodes):
    # An explicit empty list is treated as "filter not set"
    res = _query(client, headers, user_id, filters={"activity": []})
    assert set(res["episode_ids"]) == set(seeded_episodes)


# ── 5. matched_axes metadata ─────────────────────────────────────────────────

def test_query_returns_matched_axes_metadata(
    client, headers, user_id, seeded_episodes,
):
    res = _query(client, headers, user_id, filters={
        "activity": ["coding"], "topic_tags": ["evanescence"],
    })
    assert "ep-q-1" in res["matched_axes_per_episode"]
    axes = set(res["matched_axes_per_episode"]["ep-q-1"])
    assert "activity:coding" in axes
    assert "topic:evanescence" in axes
    # not in filter → not in matched_axes
    assert "topic:compression" not in axes
    assert "where:domicile" not in axes


def test_query_matched_axes_empty_when_no_filters(
    client, headers, user_id, seeded_episodes,
):
    res = _query(client, headers, user_id, filters={})
    for eid in res["episode_ids"]:
        assert res["matched_axes_per_episode"][eid] == []


# ── 6. Limit + ordering ──────────────────────────────────────────────────────

def test_query_respects_limit(client, headers, user_id, seeded_episodes):
    res = _query(client, headers, user_id, filters={}, limit=2)
    assert len(res["episode_ids"]) == 2


def test_query_orders_by_when_desc(client, headers, user_id, seeded_episodes):
    res = _query(client, headers, user_id, filters={})
    # ep-q-4 has the latest when, ep-q-1 the earliest
    assert res["episode_ids"][0] == "ep-q-4"
    assert res["episode_ids"][-1] == "ep-q-1"


# ── 7. User isolation ────────────────────────────────────────────────────────

def test_query_user_isolation(
    client, headers, user_id, other_user_id, seeded_episodes,
):
    # Seed an episode under a different user directly via graph driver
    from api.services.context_graph import index_episode
    import asyncio
    asyncio.run(index_episode(
        user_id=other_user_id,
        episode_id="ep-other-secret",
        signature={
            "when": _iso(datetime(2026, 5, 25, 12, 0)),
            "activity": "coding",
        },
    ))

    # The caller (usr_test) must NOT see ep-other-secret
    res = _query(client, headers, user_id, filters={"activity": ["coding"]})
    assert "ep-other-secret" not in res["episode_ids"]


def test_query_user_id_mismatch_returns_403(client, headers):
    r = client.post(
        "/context/query", headers=headers,
        json={"user_id": "someone_else", "filters": {}},
    )
    assert r.status_code == 403

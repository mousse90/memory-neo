# memory-neo/tests/test_context_unit.py
# Path: tests/test_context_unit.py
# Purpose: pure-Python unit tests for context endpoints — no Memgraph needed.
# These run on every CI cycle even without a graph DB.

from datetime import datetime, timezone

from api.routes.context import (
    ContextSignaturePayload,
    ContextIndexRequest,
    ContextQueryFilters,
    ContextQueryRequest,
    ContextIndexResponse,
    ContextQueryResponse,
)
from api.services.context_graph import _coerce_iso, _normalize_list


# Override the auto-skip in conftest for this file — it doesn't need Memgraph.
def _strip_skip(items):
    for item in items:
        item.own_markers = [m for m in item.own_markers if m.name != "skip"]


def pytest_collection_modifyitems(config, items):
    _strip_skip(items)


# ── Pydantic model validation ────────────────────────────────────────────────

def test_signature_payload_accepts_full_payload():
    sig = ContextSignaturePayload(
        when="2026-05-20T10:23:00Z",
        when_relative="morning",
        activity="coding",
        activity_object="RePTiLS",
        topic_tags=["evanescence", "compression"],
        where_label="domicile",
    )
    assert sig.activity == "coding"
    assert sig.topic_tags == ["evanescence", "compression"]
    assert isinstance(sig.when, datetime)


def test_signature_payload_defaults_topic_tags_to_empty_list():
    sig = ContextSignaturePayload(when="2026-05-20T10:00:00Z")
    assert sig.topic_tags == []
    assert sig.activity is None


def test_index_request_user_id_optional():
    req = ContextIndexRequest(
        episode_id="ep-x",
        signature=ContextSignaturePayload(when="2026-05-20T10:00:00Z"),
    )
    assert req.user_id is None


def test_query_request_mode_defaults_to_intersection():
    req = ContextQueryRequest(filters=ContextQueryFilters())
    assert req.mode == "intersection"
    assert req.limit == 50


def test_query_request_rejects_invalid_mode():
    import pydantic
    try:
        ContextQueryRequest(mode="weird")  # type: ignore[arg-type]
    except pydantic.ValidationError:
        return
    raise AssertionError("ContextQueryRequest accepted invalid mode")


def test_query_filters_all_optional():
    f = ContextQueryFilters()
    assert f.activity is None
    assert f.topic_tags is None
    assert f.when_after is None


# ── Helper functions ─────────────────────────────────────────────────────────

def test_coerce_iso_handles_datetime():
    dt = datetime(2026, 5, 20, 10, 23, tzinfo=timezone.utc)
    assert _coerce_iso(dt) == "2026-05-20T10:23:00+00:00"


def test_coerce_iso_passes_through_string():
    assert _coerce_iso("2026-05-20T10:23:00Z") == "2026-05-20T10:23:00Z"


def test_coerce_iso_returns_none_for_none():
    assert _coerce_iso(None) is None


def test_normalize_list_strips_empties():
    assert _normalize_list(["a", "", None, "b"]) == ["a", "b"]


def test_normalize_list_returns_none_for_empty_list():
    assert _normalize_list([]) is None


def test_normalize_list_wraps_bare_string():
    assert _normalize_list("solo") == ["solo"]


def test_normalize_list_returns_none_for_none():
    assert _normalize_list(None) is None


# ── Response shape ───────────────────────────────────────────────────────────

def test_index_response_shape():
    r = ContextIndexResponse(ok=True, episode_id="ep-1", nodes_created=3, relations_created=4)
    d = r.model_dump()
    assert d == {"ok": True, "episode_id": "ep-1", "nodes_created": 3, "relations_created": 4}


def test_query_response_shape():
    r = ContextQueryResponse(
        episode_ids=["ep-1", "ep-2"],
        count=2,
        matched_axes_per_episode={"ep-1": ["activity:coding"], "ep-2": []},
    )
    d = r.model_dump()
    assert d["count"] == 2
    assert d["matched_axes_per_episode"]["ep-1"] == ["activity:coding"]

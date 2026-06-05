# memory-neo/tests/conftest.py
# Path: tests/conftest.py
# Purpose: pytest fixtures for the /context/* endpoint tests.
#   - Forces ENVIRONMENT=development so the dev API key path is used
#   - Provides a TestClient and a Memgraph cleanup fixture
#   - Skips the full module when Memgraph is unreachable

import os
import uuid

# Force dev mode BEFORE any api.* import (Supabase/Prisma bypass).
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEV_API_KEY", "test-dev-key")
os.environ.setdefault("DEV_USER_ID", "usr_test")
os.environ.setdefault("DEV_EMAIL", "test@memory-neo.dev")
os.environ.setdefault("MEMGRAPH_HOST", os.environ.get("MEMGRAPH_HOST", "127.0.0.1"))
os.environ.setdefault("MEMGRAPH_PORT", os.environ.get("MEMGRAPH_PORT", "7687"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def memgraph_available() -> bool:
    """Probe Memgraph once per session. Tests that need it will SKIP if absent."""
    try:
        from api.services.graph import get_graph_client
        client = get_graph_client()
        client.verify_connectivity()
        client.close()
        return True
    except Exception as e:
        print(f"⚠ Memgraph not reachable, context graph tests will SKIP: {e}")
        return False


@pytest.fixture(scope="session")
def app():
    """Import the FastAPI app once (lifespan triggers schema init)."""
    from api.main import app as _app
    return _app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers():
    return {"X-API-Key": os.environ["DEV_API_KEY"]}


@pytest.fixture
def user_id():
    return os.environ["DEV_USER_ID"]


@pytest.fixture
def other_user_id():
    """A second isolated user id (no API key — used for direct graph writes)."""
    return "usr_test_other"


@pytest.fixture
def episode_id():
    """A unique episode id per test — avoids cross-test pollution."""
    return f"ep-test-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def cleanup_graph(memgraph_available, request):
    """After each test, delete every Episode / axis node created for the
    test user ids. Keeps the dev Memgraph clean between runs."""
    yield
    if not memgraph_available:
        return
    from api.services.graph import get_graph_client
    driver = get_graph_client()
    try:
        with driver.session() as session:
            for uid in ("usr_test", "usr_test_other"):
                session.run(
                    """
                    MATCH (n)
                    WHERE n.scope_user_id = $uid
                      AND (n:Episode OR n:Activity OR n:Topic
                           OR n:ActivityObject OR n:Where OR n:TimeSlot)
                    DETACH DELETE n
                    """,
                    uid=uid,
                )
    finally:
        driver.close()


def pytest_collection_modifyitems(config, items):
    """Auto-skip context-graph tests when Memgraph is not reachable."""
    try:
        from api.services.graph import get_graph_client
        c = get_graph_client()
        c.verify_connectivity()
        c.close()
        reachable = True
    except Exception:
        reachable = False

    if reachable:
        return

    skip_marker = pytest.mark.skip(reason="Memgraph not reachable on bolt://127.0.0.1:7687")
    # Only auto-skip integration tests — unit tests stay runnable.
    integration_files = (
        "test_context_index.py",
        "test_context_query.py",
        "test_m2m_auth.py",
        "test_graph_guard.py",
    )
    for item in items:
        if any(name in item.nodeid for name in integration_files):
            item.add_marker(skip_marker)

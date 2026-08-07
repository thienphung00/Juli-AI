"""Worker session factories must be created once per process (#813).

Every worker task calls `_ensure_session_factory()` on each invocation. Before this
fix each call built a fresh `create_async_engine`, opening a new connection pool and
leaving the previous one undisposed. Against the Supabase pooler's 15-client ceiling
that exhausts connections, which is what broke the deploy for 703f693a:

    FATAL: (EMAXCONNSESSION) max clients reached in session mode
"""

from __future__ import annotations

import importlib

import pytest

WORKER_TASK_MODULES = [
    "juli_backend.workers.tasks.mock_analytics_reconcile",
    "juli_backend.workers.tasks.material_analytics_precompute",
    "juli_backend.workers.tasks.action_card_refresh",
    "juli_backend.workers.tasks.tool_execution",
    "juli_backend.workers.tasks.analytics_backfill_topup",
]

TEST_URL = "postgresql+asyncpg://u:p@localhost:5432/testdb"


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    from juli_backend.database import database as db

    db._worker_factories.clear()
    yield
    db._worker_factories.clear()


def test_repeated_calls_return_the_same_factory():
    from juli_backend.database.database import ensure_worker_session_factory

    first = ensure_worker_session_factory(TEST_URL)
    second = ensure_worker_session_factory(TEST_URL)
    assert first is second, "each call must reuse the process-wide factory"


def test_repeated_calls_create_only_one_engine(monkeypatch):
    """The regression that broke the deploy: one engine per call, never disposed."""
    from juli_backend.database import database as db

    created: list[str] = []
    real_create = db.create_async_engine

    def counting_create(url, **kwargs):
        created.append(url)
        return real_create(url, **kwargs)

    monkeypatch.setattr(db, "create_async_engine", counting_create)

    for _ in range(5):
        db.ensure_worker_session_factory(TEST_URL)

    assert len(created) == 1, (
        f"expected exactly 1 engine for 5 calls, got {len(created)} — "
        "each extra engine opens another connection pool"
    )


def test_distinct_urls_get_distinct_factories():
    """Caching must key on the URL, not collapse different databases together."""
    from juli_backend.database.database import ensure_worker_session_factory

    a = ensure_worker_session_factory(TEST_URL)
    b = ensure_worker_session_factory(TEST_URL.replace("testdb", "otherdb"))
    assert a is not b


def test_first_call_publishes_the_global_session_factory():
    """get_session() depends on the global being set; that behaviour is preserved."""
    from juli_backend.database import database as db

    db._session_factory = None
    factory = db.ensure_worker_session_factory(TEST_URL)
    assert db._session_factory is factory


@pytest.mark.parametrize("module_name", WORKER_TASK_MODULES)
def test_worker_tasks_do_not_build_their_own_engine(module_name: str):
    """All five tasks must route through the shared helper.

    Five independent copies of the same lifecycle bug is why it reached production;
    this keeps them converged.
    """
    module = importlib.import_module(module_name)
    source = importlib.import_module(module.__name__).__loader__.get_source(module.__name__)
    assert "ensure_worker_session_factory" in source, (
        f"{module_name} must use the shared cached factory"
    )
    assert "create_async_engine" not in source, f"{module_name} must not construct its own engine"

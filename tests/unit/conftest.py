import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def token_encryption_key(monkeypatch):
    monkeypatch.setenv("TIKTOK_TOKEN_ENCRYPTION_KEY", "unit-test-token-encryption-key")


@pytest_asyncio.fixture(autouse=True)
async def reset_shared_redis_clients_for_unit_tests():
    """Close process-lifetime Redis singletons between tests (#631).

    In CI, REDIS_URL points at a real redis:7 service container, so
    get_shared_redis_client() creates a real asyncio client bound to
    whatever event loop is active during the test that first calls it.
    pytest-asyncio's default event loop is function-scoped, so without
    this cleanup a later test reusing the module-level singleton hits
    "Future attached to a different loop" / "Event loop is closed" —
    only reproduces where REDIS_URL is set (CI), never locally without
    a Redis service running.
    """
    yield
    from juli_backend.services.analytics_kpi_cache import (
        close_shared_redis_client as close_analytics_kpi_redis,
    )
    from juli_backend.services.gold_kpi_cache import (
        close_shared_redis_client as close_gold_kpi_redis,
    )

    await close_gold_kpi_redis()
    await close_analytics_kpi_redis()


@pytest.fixture(autouse=True)
def bind_celery_dispatchers_for_unit_tests():
    """Wire MMU-6/7 worker bindings so unit tests can run the execution worker."""
    from juli_backend.services.action_cards.dispatch import set_refresh_dispatcher
    from juli_backend.services.execution.dispatch import set_task_dispatcher
    from juli_backend.services.execution.outcome_port import (
        set_workflow_outcome_recorder,
    )
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    bind_celery_dispatchers()
    yield
    set_refresh_dispatcher(None)
    set_task_dispatcher(None)
    set_workflow_outcome_recorder(None)


@pytest.fixture(autouse=True)
def reset_action_card_refresh_cooldown_gate_for_unit_tests():
    """Leave the #899 per-shop refresh cooldown gate unbound by default.

    Deliberately does NOT auto-bind a gate: production fails closed when
    nothing is bound (see refresh_cooldown.get_refresh_cooldown_gate), and
    tests that exercise POST /v1/action-cards/refresh must opt in to a gate
    explicitly, the same way they opt in to a mock Celery dispatcher.
    """
    yield
    from juli_backend.services.action_cards.refresh_cooldown import (
        set_refresh_cooldown_gate,
    )

    set_refresh_cooldown_gate(None)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )

    def _create_tables(sync_conn):
        Base.metadata.create_all(sync_conn)

    async with eng.begin() as conn:
        await conn.run_sync(_create_tables)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def other_user_id():
    return uuid.uuid4()

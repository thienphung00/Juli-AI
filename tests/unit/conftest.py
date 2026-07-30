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

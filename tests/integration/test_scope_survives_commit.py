"""A scope entered once does not survive the commits inside it (#1576).

`with_shop_scope` sets `app.current_shop_id` with SET LOCAL, which is scoped to
the transaction. A task that commits mid-run therefore loses its tenant context,
and its next INSERT is refused by RLS WITH CHECK with
"new row violates row-level security policy" — observed in production once the
runtime stopped owning its tables.

THE SESSION SHAPE IS THE POINT. These tests build an ENGINE-bound session, so
`commit()` is a real COMMIT. `tests/integration/two_tenant.py::juli_app_session`
binds to one connection whose transaction the fixture began, so its `commit()`
is not a real COMMIT and SET LOCAL survives it — a test written on that fixture
passes while production fails. That divergence is why this defect had no
coverage.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

# NOT in _ISOLATED_DATABASE_MODULES, deliberately. These tests set GUCs and
# commit; they create no schema, write no rows, and downgrade nothing, so they
# are safe on the shared database. Registering them for isolation cost a fresh
# database migrated through every revision and pushed full-regression past its
# 20-minute job timeout — 20:16 against a 12:18 baseline.
pytestmark = [requires_postgres]

_GUC = text("SELECT current_setting('app.current_shop_id', true)")


@pytest.fixture
async def engine_session():
    """An ENGINE-bound session, so commit() really commits."""
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    session = AsyncSession(bind=engine)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_context_is_gone_after_a_commit_inside_the_scope(engine_session):
    """The defect itself, pinned so the fix cannot be quietly reverted.

    This is a characterisation of SET LOCAL, not a wish: a commit ends the
    transaction and the GUC goes with it. The fix is not to change this, it is
    to re-enter the scope per unit of work — which the next test asserts.
    """
    shop_id = uuid.uuid4()

    async with with_shop_scope(engine_session, shop_id):
        before = (await engine_session.execute(_GUC)).scalar()
        await engine_session.commit()
        after = (await engine_session.execute(_GUC)).scalar()

    assert before == str(shop_id), f"the scope must set the GUC; got {before!r}"
    assert after in (None, ""), (
        f"SET LOCAL is expected to die with the transaction; got {after!r}. If this "
        "starts passing, the GUC survives commits and #1576's reasoning needs revisiting"
    )


@pytest.mark.asyncio
async def test_re_entering_the_scope_restores_the_context_after_a_commit(engine_session):
    """The fix: a scope per unit of work, which is what the orchestrator now does.

    Each stage re-enters, so the GUC is freshly applied for that stage's writes
    however many times an earlier stage committed.
    """
    shop_id = uuid.uuid4()

    async with with_shop_scope(engine_session, shop_id):
        await engine_session.commit()

    async with with_shop_scope(engine_session, shop_id):
        second_stage = (await engine_session.execute(_GUC)).scalar()
        await engine_session.commit()

    assert second_stage == str(shop_id), (
        f"the second stage must run with its own context; got {second_stage!r}"
    )


@pytest.mark.asyncio
async def test_a_broken_session_does_not_mask_the_caller_error(engine_session):
    """#1576's second defect: the restore replaced the caller's real exception.

    A body can catch its own failure and return normally, leaving the session
    unusable while `body_failed` is False. The exit path then tried to write and
    raised PendingRollbackError from the `finally`, which in production masked an
    RLS violation and turned a one-line diagnosis into reading past a misleading
    traceback.
    """
    shop_id = uuid.uuid4()

    async with with_shop_scope(engine_session, shop_id):
        # Break the session the way real code does — a failure caught inside.
        with pytest.raises(Exception):
            await engine_session.execute(text("SELECT * FROM does_not_exist_xyz"))

    # Reaching here at all is the assertion: exiting the scope must not raise.
    await engine_session.rollback()
    assert True

"""Process-lifetime async resources must survive asyncio.run-per-task workers (#871).

#815 fixed the #813 engine-per-invocation pooler leak by caching one engine per
process — but worker tasks each enter through ``asyncio.run()``, a fresh event loop
per invocation. A pooled asyncpg connection created on one loop is poison on the
next: checkout raises "Future attached to a different loop" and the task dies at
its first query. In production every celery child failed on every run after its
first, from #815's deploy until this fix.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, text
from sqlalchemy.pool import NullPool

from juli_backend.database import database as db


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    db._worker_factories.clear()
    yield
    db._worker_factories.clear()


def _sqlite_url(tmp_path) -> str:
    # File-backed, not :memory:. With NullPool every checkout is a new connection,
    # and a new :memory: connection is a new empty database.
    return f"sqlite+aiosqlite:///{tmp_path}/worker.db"


def test_worker_engine_does_not_pool_connections(tmp_path):
    """The #871 invariant. A retained connection is loop-bound by construction —
    the only connection count that is safe across asyncio.run() boundaries is zero.
    (aiosqlite tolerates cross-loop reuse, so this pins the mechanism itself
    rather than the asyncpg symptom.)"""
    factory = db.ensure_worker_session_factory(_sqlite_url(tmp_path))
    engine = factory.kw["bind"]

    assert isinstance(engine.sync_engine.pool, NullPool)

    closed: list[int] = []
    event.listen(engine.sync_engine, "close", lambda dbapi_conn, rec: closed.append(1))

    async def use() -> None:
        async with factory() as session:
            await session.execute(text("SELECT 1"))

    asyncio.run(use())
    assert closed, (
        "the DBAPI connection was retained at checkin instead of closed — it is "
        "bound to this loop, and the next asyncio.run() would check it out and "
        "die cross-loop on asyncpg"
    )


def test_cached_factory_works_across_sequential_task_loops(tmp_path):
    """The production shape: one cached factory, one asyncio.run() per hourly task."""
    url = _sqlite_url(tmp_path)

    async def one_task_invocation() -> int:
        factory = db.ensure_worker_session_factory(url)
        async with factory() as session:
            result = await session.execute(text("SELECT 41 + 1"))
            return result.scalar_one()

    assert asyncio.run(one_task_invocation()) == 42
    assert asyncio.run(one_task_invocation()) == 42
    assert asyncio.run(one_task_invocation()) == 42
    # Still one factory — the #813 guarantee is not traded away again.
    assert len(db._worker_factories) == 1


def test_redis_client_is_cached_per_loop(monkeypatch):
    """Same root cause, second instance: the gold-cache refresh client. Cached
    per running loop — stable within a loop (the API case), fresh across loops
    (the worker case). No TTL protects the gold cache key, so a cross-loop-dead
    client means the Demo serves a stale envelope indefinitely."""
    from juli_backend.services.gold_kpi_cache import cache as cache_mod

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")
    cache_mod.reset_shared_redis_client_for_tests()

    async def grab_twice() -> tuple[int, int]:
        a = cache_mod.get_shared_redis_client()
        b = cache_mod.get_shared_redis_client()
        return id(a), id(b)

    first_a, first_b = asyncio.run(grab_twice())
    assert first_a == first_b, "same loop must reuse the same client"

    second_a, _ = asyncio.run(grab_twice())
    assert second_a != first_a, (
        "a new task loop must get a new client — the old one's connections "
        "are bound to a closed loop"
    )

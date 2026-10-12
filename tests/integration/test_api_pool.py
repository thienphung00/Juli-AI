"""P29: the API engine's pool -- warm at startup, kept warm, no pre-ping round trip.

Production pays ~1,257 ms for a new connection to the Supabase pooler and ~395 ms
per round trip, so the API pool (``database.create_api_engine``) must not open
connections on requests and must not ping on checkout. These run on a real
Postgres; the statement counts come from the same ``SqlCounter`` the Ops
round-trip tests use.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.database import (
    PoolKeepWarm,
    api_pool_settings,
    create_api_engine,
    start_api_pool,
    warm_pool,
)
from tests.support.postgres import database_url, requires_postgres
from tests.support.sql_counter import SqlCounter

pytestmark = [requires_postgres]


@pytest.fixture
async def engine():
    engine = create_api_engine(async_database_url(database_url()))
    try:
        yield engine
    finally:
        await engine.dispose()


def test_api_pool_settings_defaults(monkeypatch):
    for name in (
        "API_DB_POOL_SIZE",
        "API_DB_MAX_OVERFLOW",
        "API_DB_POOL_RECYCLE_SECONDS",
        "API_DB_IDLE_LIMIT_SECONDS",
        "API_DB_KEEPWARM_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = api_pool_settings()
    assert settings["pool_size"] == 5
    assert settings["max_overflow"] == 5
    # The idle guard sits under the 350 s TCP idle timeout of the load
    # balancer in front of the pooler; the keep-warm interval well under it.
    assert settings["idle_limit"] < 350
    assert settings["keepwarm"] < settings["idle_limit"]


async def test_engine_is_tuned(engine):
    pool = engine.pool
    assert engine.sync_engine.pool._pre_ping is False
    assert pool.size() == 5
    assert pool._max_overflow == 5


async def test_warm_pool_opens_distinct_connections(engine):
    assert await warm_pool(engine, 3) == 3
    assert engine.pool.checkedin() == 3


async def test_a_request_on_a_warm_pool_sends_no_ping(engine):
    await warm_pool(engine, 2)
    counter = SqlCounter.attach(engine)
    try:
        with counter.measure() as seen:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 42"))
                await conn.rollback()
    finally:
        counter.detach()
    # BEGIN, the statement, ROLLBACK -- and no pre-ping SELECT 1.
    assert [e for e in seen.events if "SELECT 1" in e] == [], seen.describe()
    assert seen.round_trips == 3, seen.describe()


async def test_keepwarm_tick_pings_idle_connections_and_tops_up(engine):
    await warm_pool(engine, 2)
    keepwarm = PoolKeepWarm(engine, interval=60, recycle=1800, target=4)
    await keepwarm.tick()
    assert engine.pool.checkedin() == 4  # topped up to the target


async def _backend_pid(engine) -> int:
    async with engine.connect() as conn:
        pid = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await conn.rollback()
    return int(pid)


async def test_idle_guard_replaces_a_stale_connection_at_checkout(monkeypatch):
    monkeypatch.setenv("API_DB_IDLE_LIMIT_SECONDS", "0.2")
    engine = create_api_engine(async_database_url(database_url()))
    try:
        await warm_pool(engine, 1)
        first = await _backend_pid(engine)
        assert await _backend_pid(engine) == first  # reused while fresh
        await asyncio.sleep(0.4)
        assert await _backend_pid(engine) != first  # idle too long: replaced
        assert engine.pool.checkedin() == 1
    finally:
        await engine.dispose()


async def test_keepwarm_replaces_an_old_connection_in_the_background(engine):
    """Near ``pool_recycle`` age, the tick replaces the connection -- so the
    reconnect is paid here, not by a request's checkout."""
    await warm_pool(engine, 1)
    first = await _backend_pid(engine)
    keepwarm = PoolKeepWarm(engine, interval=0.1, recycle=1, target=1)
    await asyncio.sleep(0.8)
    await keepwarm.tick()
    assert engine.pool.checkedin() == 1
    assert await _backend_pid(engine) != first


async def test_start_api_pool_warms_and_stops(engine, monkeypatch):
    monkeypatch.setenv("API_DB_POOL_SIZE", "2")
    keepwarm = await start_api_pool(engine)
    try:
        assert keepwarm is not None
        assert engine.pool.checkedin() == 2
    finally:
        await keepwarm.stop()


async def test_sqlite_engine_is_left_alone():
    engine = create_api_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert await start_api_pool(engine) is None
    finally:
        await engine.dispose()

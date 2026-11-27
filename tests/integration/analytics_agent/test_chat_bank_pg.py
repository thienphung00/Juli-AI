"""The Chat regression bank's Postgres subset (owner decision #109): every case marked `"pg": true`
in `tests/unit/analytics_agent/bank/cases.json` runs on real Postgres through the production
`ServiceData` unchanged (no SQLite dialect adapter), and its figures must equal the tab's own
service on the same database. Same runner, same checks, same xfail rule as the SQLite bank.

Run: `fasttrack/bin/pg-test.sh tests/integration/analytics_agent/test_chat_bank_pg.py`
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.analytics_agent.data_service import ServiceData
from tests.support.postgres import requires_postgres
from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.test_chat_bank import _param
from tests.unit.analytics_agent.bank.world import seed_into

pytestmark = [requires_postgres]

PG_CASES = [c for c in runner.load_cases() if c.get("pg")]


@pytest_asyncio.fixture
async def world():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()

    def new_session() -> AsyncSession:
        return AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    seed = new_session()
    sid = await seed_into(seed)
    await seed.commit()
    await seed.close()

    @asynccontextmanager
    async def factory():
        s = new_session()
        try:
            yield s
        finally:
            await s.close()

    try:
        yield sid, factory
    finally:
        await outer.rollback()
        await conn.close()
        await engine.dispose()


def test_the_pg_subset_is_not_empty() -> None:
    assert len(PG_CASES) >= 20


@pytest.mark.parametrize("case", [_param(c) for c in PG_CASES])
async def test_bank_case_pg(
    case: dict[str, Any], world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.ungate_if_asked(case, monkeypatch)
    sid, factory = world
    out = await runner.ask(factory, ServiceData(factory, sid), sid, case)
    problems = await runner.check(out, case, factory, sid)
    assert not problems, f"{case['id']} ({case['question']!r}):\n  - " + "\n  - ".join(problems)

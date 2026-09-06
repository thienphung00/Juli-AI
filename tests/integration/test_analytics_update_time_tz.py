"""`update_time` must be naive, because its column is (#1675).

WHY THIS IS AN INTEGRATION TEST. The column is `TIMESTAMP WITHOUT TIME ZONE`
and SQLite does not enforce that, so the unit substrate cannot see this defect
at all. Epic #175's registered lock says so directly: "match the column's
declared tz-awareness exactly; regression tests must run against real
Postgres/asyncpg where the defect manifests (SQLite masks tz mismatches)."

WHAT IT COST. `live` and `catalog` wrote `datetime.fromtimestamp(synced_at,
tz=UTC)` into that column and failed on every run for six weeks. The two buckets
that wrote an aware value are exactly the two that always failed; `product` and
`revenue`, which do not, are exactly the two that completed:

    catalog   failed    11      live      failed    30
    product   complete  26      revenue   complete  30

One cause produced two unrecognisable symptoms depending on which path ran, so
both are pinned here:

    INSERT -> asyncpg DataError, "invalid input for query argument $28"
    UPDATE -> TypeError from `_incoming_is_stale`, "can't compare offset-naive
              and offset-aware datetimes"
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from juli_backend.repositories._base import utc_from_timestamp_naive
from juli_backend.repositories.analytics import AnalyticsPerformanceRepo
from tests.integration.test_agent_events_streaming_matrix import (
    _disposable_postgres_url,
    _postgres_schema_ready,
    pg_engine,
    pg_session_factory,
)
from tests.support.postgres import requires_postgres

# Re-exported so pytest can resolve the fixture chain in this module. This test
# takes its own throwaway database rather than the shared one: it calls
# `create_all`, and doing that on the shared database leaves tables with no
# `alembic_version` row -- the state that produces `DuplicateTable: relation
# "users" already exists` in a later CI stage.
__all__ = [
    "_disposable_postgres_url",
    "_postgres_schema_ready",
    "pg_engine",
    "pg_session_factory",
]

pytestmark = [requires_postgres, pytest.mark.asyncio]

SYNCED_AT = 1757142000  # a fixed instant; the bug is tz-awareness, not the value


@pytest.fixture
async def pg_session(pg_session_factory):
    async with pg_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def shop_id(pg_session):
    """A real `shops` row, so the FK is satisfied and the INSERT actually runs."""
    from juli_backend.models.models import Shop, User

    user = User(id=uuid.uuid4(), phone=f"+84{uuid.uuid4().int % 10**9:09d}")
    pg_session.add(user)
    await pg_session.flush()
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="tz-fixture")
    pg_session.add(shop)
    await pg_session.flush()
    return shop.id


def _values(shop_id: uuid.UUID, update_time: datetime) -> dict:
    return {
        "snapshot_key": f"live_daily|2026-09-03|{uuid.uuid4()}",
        "grain": "live_daily",
        "start_date": date(2026, 9, 3),
        "end_date": date(2026, 9, 3),
        "update_time": update_time,
    }


async def test_the_helper_returns_a_naive_datetime():
    """The contract in one line, so a future edit cannot quietly re-add tzinfo."""
    assert utc_from_timestamp_naive(SYNCED_AT).tzinfo is None


async def test_insert_then_update_both_succeed_with_the_naive_value(pg_session, shop_id):
    """The fix, on the real substrate: both paths, one after the other.

    The second upsert is what exercises `_incoming_is_stale` — the comparison
    that raised TypeError in production. A test that only inserts would pass
    against the broken code on the UPDATE half.
    """
    repo = AnalyticsPerformanceRepo(pg_session)
    values = _values(shop_id, utc_from_timestamp_naive(SYNCED_AT))

    row = await repo.upsert(shop_id=shop_id, **values)
    assert row.update_time.tzinfo is None

    # Same natural key, a strictly newer instant: takes the UPDATE branch.
    newer = {**values, "update_time": utc_from_timestamp_naive(SYNCED_AT + 3600)}
    updated = await repo.upsert(shop_id=shop_id, **newer)
    assert updated.update_time == utc_from_timestamp_naive(SYNCED_AT + 3600)


async def test_the_aware_value_still_fails_on_insert(pg_session, shop_id):
    """Anchors the test to the real defect rather than to the fix's shape.

    If Postgres ever stopped rejecting this, the test above would keep passing
    while proving nothing.
    """
    repo = AnalyticsPerformanceRepo(pg_session)
    aware = datetime.fromtimestamp(SYNCED_AT, tz=UTC)

    with pytest.raises(Exception) as excinfo:
        await repo.upsert(shop_id=shop_id, **_values(shop_id, aware))
    assert "offset-naive and offset-aware" in str(excinfo.value) or "invalid input" in str(
        excinfo.value
    ), f"expected the tz mismatch to be rejected, got: {excinfo.value}"


async def test_the_aware_value_still_fails_on_update(pg_session, shop_id):
    """The `live` symptom specifically: aware incoming vs naive stored."""
    repo = AnalyticsPerformanceRepo(pg_session)
    values = _values(shop_id, utc_from_timestamp_naive(SYNCED_AT))
    await repo.upsert(shop_id=shop_id, **values)

    aware_newer = {**values, "update_time": datetime.fromtimestamp(SYNCED_AT + 3600, tz=UTC)}
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        await repo.upsert(shop_id=shop_id, **aware_newer)

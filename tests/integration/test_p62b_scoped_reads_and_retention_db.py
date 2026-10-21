"""P62-B (D72.2 / D72.3) on real Postgres, as ``juli_app``, with two shops.

- The gold Demo-KPI recompute (each material webhook + the hourly reconcile) reads
  aggregates, not every ``silver.orders`` / ``analytics_performance_intervals`` row: the
  rows it reads are bounded by shop A's order days + 2, and shop B's rows are never read.
  Its five KPIs equal a Python reference computed from the seeded rows.
- The scoring read of ``analytics_performance_intervals`` returns only shop A's rows inside
  the 30-day KPI window (rows outside it are never read), KPI columns only.
- ``load_product_days`` never selects ``snapshot_key`` and reads shop A's window only.
- ``processed_events`` retention: ``juli_app`` has no DELETE on the ledger; the owner-role
  ``purge_processed_events`` removes both shops' expired rows in batches, keeps recent
  ones, and refuses a retention below the SQL floor.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import AnalyticsPerformanceInterval, Order

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

RUNTIME_ROLE = "juli_app"
TODAY = datetime.now(UTC).date()
NOW_NAIVE = datetime.now(UTC).replace(tzinfo=None)


def _urls() -> tuple[str, str]:
    from juli_backend.core.config.runtime import async_database_url, sync_database_url

    url = os.environ["DATABASE_URL"]
    return async_database_url(url), sync_database_url(url)


def _app_engine():
    """An async engine whose every connection runs as ``juli_app``."""
    engine = create_async_engine(_urls()[0])

    @event.listens_for(engine.sync_engine, "connect")
    def _as_app(dbapi_connection, _record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET ROLE {RUNTIME_ROLE}")
        cursor.close()

    return engine


class RowCounter:
    """Wrap ``session.execute``: record each statement and how many rows it returned."""

    def __init__(self, session: AsyncSession) -> None:
        self.calls: list[tuple[str, int]] = []
        original = session.execute

        async def counting(statement, *args, **kwargs):
            result = await original(statement, *args, **kwargs)
            if not getattr(result, "returns_rows", True):
                return result
            frozen = result.freeze()
            if "set_config" in str(statement):  # the tenant-scope GUC round trip
                return frozen()
            self.calls.append((str(statement), len(frozen.data)))
            return frozen()

        session.execute = counting  # type: ignore[method-assign]

    @property
    def rows(self) -> int:
        return sum(n for _, n in self.calls)

    def rows_where(self, fragment: str) -> int:
        return sum(n for sql, n in self.calls if fragment in sql)


def _seed_shop(conn, label: str) -> uuid.UUID:
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.users (id, phone, display_name, created_at, updated_at) "
            "VALUES (:id, :phone, :name, :now, :now)"
        ),
        {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "name": label, "now": NOW_NAIVE},
    )
    conn.execute(
        text(
            "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, created_at, "
            "updated_at) VALUES (:id, :user, :name, :key, :now, :now)"
        ),
        {
            "id": str(shop_id),
            "user": str(user_id),
            "name": f"{label} shop",
            "key": f"tt-{shop_id.hex[:10]}",
            "now": NOW_NAIVE,
        },
    )
    return shop_id


def _orders(shop_id: uuid.UUID, days: int, per_day: int) -> list[Order]:
    out = []
    for d in range(days):
        for i in range(per_day):
            created = NOW_NAIVE - timedelta(days=d, hours=i)
            out.append(
                Order(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    tiktok_order_id=f"o-{shop_id.hex[:6]}-{d}-{i}",
                    status="CANCELLED" if i == 0 else "COMPLETED",
                    total_amount=Decimal(100 + 10 * d + i),
                    currency="VND",
                    tiktok_created_at=created,
                    update_time=created + timedelta(minutes=5),
                )
            )
    return out


def _interval(shop_id: uuid.UUID, grain: str, day: date, product: str | None, **values):
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"{grain}:{product}:{day.isoformat()}:{uuid.uuid4().hex}",
        grain=grain,
        start_date=day,
        end_date=day + timedelta(days=1),
        tiktok_product_id=product,
        update_time=NOW_NAIVE,
        **values,
    )


def _intervals(shop_id: uuid.UUID, days: int) -> list[AnalyticsPerformanceInterval]:
    rows = []
    for d in range(days):
        day = TODAY - timedelta(days=d + 1)
        rows.append(_interval(shop_id, "shop", day, None, live_hours=Decimal("1.5"), gmv=1000))
        for p in ("p1", "p2"):
            rows.append(
                _interval(
                    shop_id,
                    "product",
                    day,
                    p,
                    gmv=Decimal(200 + d),
                    click_order_rate=Decimal("0.05") if p == "p1" else Decimal("0.10"),
                    impressions=1000,
                    clicks=40,
                    sku_orders=3,
                    items_sold=4,
                    traffic_breakdown={"VIDEO": {"impressions": 10, "clicks": 1}},
                )
            )
            for _sku in range(2):  # two SKUs per product-day
                rows.append(
                    _interval(shop_id, "sku", day, p, gmv=Decimal(50), sku_orders=1, items_sold=1)
                )
    return rows


@pytest.fixture(scope="module")
def two_shops():
    """Shop A (90 days of data) and shop B (a non-reference shop, 120 days)."""
    sync_engine = create_engine(_urls()[1])
    with sync_engine.begin() as conn:
        shop_a = _seed_shop(conn, "p62b-a")
        shop_b = _seed_shop(conn, "p62b-b")
    sync_engine.dispose()

    import asyncio

    async def _seed():
        engine = create_async_engine(_urls()[0])
        async with async_sessionmaker(engine)() as session:
            session.add_all(_orders(shop_a, days=20, per_day=3))
            session.add_all(_orders(shop_b, days=40, per_day=5))
            session.add_all(_intervals(shop_a, days=90))
            session.add_all(_intervals(shop_b, days=120))
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())
    return shop_a, shop_b


async def _app_session_call(shop_id: uuid.UUID, fn):
    engine = _app_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            counter = RowCounter(session)
            async with with_shop_scope(session, shop_id):
                value = await fn(session)
            return value, counter
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gold_recompute_reads_aggregates_for_one_shop(two_shops):
    from juli_backend.services.gold_kpi_envelope_serving import compute_demo_main_kpis_payload

    shop_a, _shop_b = two_shops
    payload, counter = await _app_session_call(
        shop_a, lambda s: compute_demo_main_kpis_payload(s, shop_a)
    )

    # Python reference over shop A's seeded rows only.
    orders = _orders(shop_a, days=20, per_day=3)
    live = [o for o in orders if o.status != "CANCELLED"]
    gmv = sum(o.total_amount for o in live)
    kpis = payload["kpis"]
    assert kpis["gmv_tiktok"]["value"] == pytest.approx(float(gmv))
    assert kpis["aov"]["value"] == pytest.approx(float(gmv) / len(live))
    assert kpis["cancellation_rate"]["value"] == pytest.approx(1 / 3)
    assert len(kpis["gmv_tiktok"]["series"]) == len({o.tiktok_created_at.date() for o in live})
    # Each day: p1 at 0.05 and p2 at 0.10 with equal GMV -> GMV-weighted 0.075.
    assert kpis["ctor"]["value"] == pytest.approx(0.075)
    assert kpis["live_hours"]["value"] == pytest.approx(90 * 1.5)
    assert payload["source_freshness"]["silver.orders"]["row_count"] == 60
    assert payload["source_freshness"]["analytics_performance_intervals"]["row_count"] == 270

    # Rows actually read: one shops row, one per order day (<= 21 buckets), two aggregates.
    # Before D72.3 this was 60 orders + 270 interval rows for shop A alone.
    assert counter.rows <= 1 + 21 + 2, counter.calls
    assert counter.rows_where("snapshot_key") == 0
    assert counter.rows_where("buyer_id") == 0


@pytest.mark.asyncio
async def test_scoring_interval_read_is_the_kpi_window_of_one_shop(two_shops):
    from juli_backend.services.aggregates.builder import _rolling_window_intervals
    from juli_backend.services.aggregates.computed_kpis import ROLLING_WINDOW_DAYS

    shop_a, _shop_b = two_shops
    anchor = datetime.now(UTC)
    rows, counter = await _app_session_call(
        shop_a, lambda s: _rolling_window_intervals(s, shop_a, anchor, 10_000)
    )
    first = (anchor - timedelta(days=ROLLING_WINDOW_DAYS)).date()
    # Exactly shop A's window: shop B holds 120 days of the same shape.
    assert all(first <= r.start_date <= anchor.date() for r in rows)
    # 30 stored days (yesterday back) x (1 shop + 2 product + 4 sku) rows; 90 days exist.
    assert len(rows) == 30 * 7
    assert counter.rows == 30 * 7
    assert counter.rows_where("snapshot_key") == 0


@pytest.mark.asyncio
async def test_optimize_product_window_read_prunes_columns(two_shops):
    from juli_backend.services.action_cards.optimize_product_cards import load_product_days

    shop_a, _shop_b = two_shops
    last = TODAY - timedelta(days=1)
    first = last - timedelta(days=59)
    days, counter = await _app_session_call(
        shop_a, lambda s: load_product_days(s, shop_a, first, last)
    )
    assert set(days) == {"p1", "p2"}
    assert all(len(series) == 60 for series in days.values())
    assert days["p1"][-1].sku_orders == 3 and days["p1"][-1].impressions == 1000
    assert "VIDEO" in days["p1"][-1].channels
    # Shop A's window only: 120 product rows + 120 (product, day) SKU sums -- not the 240
    # SKU rows they summarise (and none of shop B's 120-day history).
    assert counter.rows == 60 * 2 + 60 * 2
    assert counter.rows_where("sum(") == 60 * 2
    assert counter.rows_where("snapshot_key") == 0


@pytest.mark.asyncio
async def test_processed_events_retention_as_juli_app(two_shops):
    from juli_backend.services.etl.persistence.ingest.retention import (
        PROCESSED_EVENTS_RETENTION_DAYS,
        purge_processed_events,
    )

    shop_a, shop_b = two_shops
    sync_engine = create_engine(_urls()[1])
    old = NOW_NAIVE - timedelta(days=PROCESSED_EVENTS_RETENTION_DAYS + 5)
    recent = NOW_NAIVE - timedelta(days=PROCESSED_EVENTS_RETENTION_DAYS - 5)
    with sync_engine.begin() as conn:
        for shop in (shop_a, shop_b):
            for i in range(7):
                for when, tag in ((old, "old"), (recent, "new")):
                    conn.execute(
                        text(
                            "INSERT INTO public.processed_events (event_id, epoch, shop_id, "
                            "processed_at) VALUES (:e, 0, :s, :at)"
                        ),
                        {"e": f"p62b:{shop.hex[:6]}:{tag}:{i}", "s": str(shop), "at": when},
                    )

    engine = _app_engine()
    try:
        # juli_app may not delete ledger rows itself.
        async with AsyncSession(engine) as session:
            async with with_shop_scope(session, shop_a):
                with pytest.raises(DBAPIError):
                    await session.execute(text("DELETE FROM public.processed_events"))
            await session.rollback()
        # The SQL floor refuses a near-wipe.
        async with AsyncSession(engine) as session:
            with pytest.raises(DBAPIError):
                await session.execute(text("SELECT public.purge_processed_events(1, 100)"))
            await session.rollback()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        result = await purge_processed_events(factory, batch_size=4, max_batches=10)
    finally:
        await engine.dispose()

    assert result.deleted == 14 and result.exhausted and result.batches == 4
    with sync_engine.connect() as conn:
        left = conn.execute(
            text("SELECT event_id FROM public.processed_events WHERE event_id LIKE 'p62b:%'")
        ).scalars()
        names = sorted(left)
    sync_engine.dispose()
    assert len(names) == 14 and all(":new:" in n for n in names)

"""P98 / ADR-122 d.11.2 on real Postgres: one number on every screen.

The synthetic seller shop is rebuilt into the materialized tables (ShopMetrics + the source rows),
then read through Tổng quan, Phân tích, Sản phẩm, the Kế hoạch base and the builder "before" for
the same shop and window (the readers in ``tests/support/shopee_cross_screen``). Lượt xem, CTR,
CTOR, Đơn, AOV, GMV and Lợi nhuận must agree. Rolled back at the end. The SQLite twin is
``tests/unit/test_p98_cross_screen.py``. Ratios are unrounded and Lợi nhuận is the ShopMetrics
profit on every screen (ADR-122 d.14).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_profit import shop_profit
from juli_backend.services.shopee_recommendations import config
from tests.support.postgres import requires_postgres
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop
from tests.support.shopee_cross_screen import FIELDS, agreed, collect_shop

pytestmark = [requires_postgres]


@asynccontextmanager
async def pg_session():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await conn.close()
        await engine.dispose()


async def test_every_screen_shows_the_same_funnel_numbers_on_postgres(monkeypatch):
    # one number across the screens: the profit gate is lifted (the synthetic shop knows 23-57 %
    # of its GMV); the gate itself is the next test
    monkeypatch.setattr(shop_profit, "MIN_KNOWN_GMV_SHARE_PCT", Decimal(0))
    monkeypatch.setattr(config, "HISTORY_DAYS", 7)  # the plan base reads the window the others show
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session)
        await materialize.backfill_shop(session, seeded.shop_id)
        surfaces, _ = await collect_shop(session, seeded.shop_id, CUR_END, days=7)
        for field in FIELDS:
            shown = agreed(surfaces, field, tol=0.005 if field in ("profit", "aov") else 1e-4)
            assert shown, field
        for field in ("views", "orders", "gmv"):
            assert {"tong_quan", "ke_hoach", "builder_before"} <= set(
                agreed(surfaces, field, tol=0)
            ), field


async def test_below_the_known_share_no_screen_shows_a_profit_on_postgres(monkeypatch):
    """R1: under 70 % known, every screen shows "—" for the profit, none of them a figure."""
    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session)
        await materialize.backfill_shop(session, seeded.shop_id)
        surfaces, _ = await collect_shop(session, seeded.shop_id, CUR_END, days=7)
        assert {
            s.name: s.values["profit"] for s in surfaces if s.values["profit"] is not None
        } == {}
        assert agreed(surfaces, "gmv", tol=0), "GMV stays"

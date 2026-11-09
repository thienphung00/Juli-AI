"""P98 / ADR-122 d.11.2 on real Postgres: one number on every screen.

The synthetic seller shop is rebuilt into the materialized tables (ShopMetrics + the source rows),
then read through Tổng quan, Phân tích, Sản phẩm, the Kế hoạch base and the builder "before" for
the same shop and window (the readers in ``tests/support/shopee_cross_screen``). Lượt xem, CTR,
CTOR, Đơn, AOV, GMV and Lợi nhuận must agree. Rolled back at the end. The SQLite twin is
``tests/unit/test_p98_cross_screen.py`` (which also records the two known gaps as strict xfails).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.shopee_analytics import materialize
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
    monkeypatch.setattr(config, "HISTORY_DAYS", 7)  # the plan base reads the window the others show
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session)
        await materialize.backfill_shop(session, seeded.shop_id)
        surfaces, _ = await collect_shop(session, seeded.shop_id, CUR_END, days=7)
        for field in FIELDS:
            # a ratio is rounded to 2 decimals by Tổng quan's strip and Phân tích's cell
            shown = agreed(
                surfaces, field, tol=0.005, abs_tol=0.005 if field in ("ctr", "ctor") else 0
            )
            assert shown, field
        for field in ("views", "orders", "gmv"):
            assert {"tong_quan", "ke_hoach", "builder_before"} <= set(
                agreed(surfaces, field, tol=0)
            ), field

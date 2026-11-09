"""P98 / ADR-122 d.2: ``funnel.load_funnel_base`` on real Postgres.

The synthetic seller shop (``tests/support/shopee_analytics``) is rebuilt into the materialized
tables (migration 126's partial unique indexes are Postgres-only behaviour worth exercising), then
read back as a :class:`FunnelBase` for the shop and for one product. Rolled back at the end.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.shopee_analytics import funnel, materialize, queries
from tests.support.postgres import requires_postgres
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

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


async def test_load_funnel_base_matches_tong_quan_on_postgres():
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session)
        await materialize.backfill_shop(session, seeded.shop_id)
        window = await funnel.anchor_window(session, seeded.shop_id)
        assert window is not None and window.end == CUR_END and window.days == 30

        base = await funnel.load_funnel_base(session, seeded.shop_id, window=window)
        m = (await queries.overview(session, seeded.shop_id))["shop_metrics"]
        assert base.total("orders") == m["orders"]
        assert base.total("gmv") == Decimal(str(m["gmv"]))
        assert funnel.known_total(base, "views") == m["views"]
        n = funnel.numbers(base, m["orders"])
        assert n.views * n.ctr * n.ctor == m["orders"]

        product = await funnel.load_funnel_base(
            session, seeded.shop_id, item_ids=["1001"], window=window
        )
        assert product.scope == "products" and product.item_ids == ("1001",)
        assert product.source_detail in ("per_source", "all_sources")

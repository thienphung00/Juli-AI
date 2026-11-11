"""P100 S2-A on real Postgres: generate -> in-process gateway ingest -> materialize -> the Shopee
analytics read model returns 30 days with data, product <= shop every day, known-cost profit.

Skips without a reachable disposable ``DATABASE_URL`` (``tests/support/postgres.py``). The loader
commits (it is a CLI), so the module's isolated database holds the shop afterwards; the fixed
reserved ``shopee_shop_id`` makes a re-run find it instead of creating a second one.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.services.shopee_analytics import queries
from scripts.sample_shop import loader
from scripts.sample_shop.generator import DAYS, generate
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

END = date(2026, 11, 10)
NOW = datetime(2026, 11, 11, 3, 0)


async def test_sample_shop_end_to_end_on_postgres():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        report = await loader.load(factory, generate(END), now=NOW)
        assert report.days_materialized == DAYS
        async with factory() as session:
            body = await queries.overview(session, report.shop_id, period="30d")
            assert body["data"]["shop_totals"] == {"basis": "daily", "days_covered": DAYS}
            assert body["shop_metrics"]["profit"] is not None
            assert 3 <= body["shop_metrics"]["ads_roas_placed"] <= 12
            days = (
                (
                    await session.execute(
                        select(ShopeeShopMetricsDaily).where(
                            ShopeeShopMetricsDaily.shop_id == report.shop_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(days) == DAYS and all(d.complete and d.profit is not None for d in days)
            gmv = {d.day: d.gmv for d in days}
            per_day: dict[date, Decimal] = defaultdict(Decimal)
            rows = await session.execute(
                select(ShopeeProductMetricsDaily).where(
                    ShopeeProductMetricsDaily.shop_id == report.shop_id,
                    ShopeeProductMetricsDaily.item_id != RESIDUAL_ITEM,
                )
            )
            for p in rows.scalars():
                per_day[p.day] += p.gmv
            assert set(per_day) == set(gmv) and all(per_day[d] <= gmv[d] for d in per_day)
        again = await loader.load(factory, generate(END), now=NOW)
        assert again.shop_id == report.shop_id and set(again.outcome) == {"duplicate"}
    finally:
        await engine.dispose()


def test_the_postgres_run_is_never_pointed_at_a_remote_host():
    loader.require_local(os.environ["DATABASE_URL"], False)

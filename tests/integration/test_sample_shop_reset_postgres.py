"""P100 S2-G reset on real Postgres: preview deletes nothing; ``--yes`` empties the shop's rows
(keeping the shop row, consent, audit log) and the re-load brings every card back.

P100 S2-D: the seeded card content (``card_content_specs``, append-only for ``juli_app``) goes and
comes back the same way, and a reviewer's used live title draft goes with it (the quota resets)."""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database import Shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.card_content_specs import SOURCE_LLM, SOURCE_SEEDED, CardContentSpec
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.consent import has_consent
from juli_backend.services.sample_shop import content_specs
from juli_backend.services.sample_shop.catalog import PRODUCTS
from scripts.sample_shop import loader, reset
from scripts.sample_shop.generator import generate
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture(scope="module", autouse=True)
def _database_at_head(owner_engine):
    """Its own database (``tests/conftest.py`` lists the module): migrated by ``owner_engine``."""
    yield


END = date(2026, 11, 10)
NOW = datetime(2026, 11, 11, 3, 0)


async def _count(factory, model, shop_id) -> int:
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.shop_id == shop_id)
            )
            or 0
        )


async def test_reset_wipes_then_reload_restores():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first = await loader.load(factory, generate(END), now=NOW)
        sid = first.shop_id
        proposals = await _count(factory, ShopProposal, sid)
        days = await _count(factory, ShopeeShopMetricsDaily, sid)
        specs = await _count(factory, CardContentSpec, sid)
        assert proposals > 0 and days > 0 and specs == 1 + len(PRODUCTS) + 3
        # A reviewer used the one live title draft on a product.
        item = PRODUCTS[0].item_id
        async with factory() as session:
            async with with_shop_scope(session, sid):
                session.add(
                    content_specs.llm_title_row(
                        sid, item, current_title=PRODUCTS[0].name, keywords=[],
                        drafts=[{"title": "x", "chars": 1}], model="fake", user_id=None, now=NOW,
                    )
                )  # fmt: skip
                await session.commit()
                assert await content_specs.live_titles_used(session, sid, item) == 1

        preview = await reset.wipe(factory, sid, commit=False)
        assert not preview.committed and preview.total > 0
        assert await _count(factory, ShopProposal, sid) == proposals

        wiped = await reset.wipe(factory, sid, commit=True)
        assert wiped.committed and wiped.deleted.keys() == preview.deleted.keys()
        assert await _count(factory, ShopProposal, sid) == 0
        assert await _count(factory, ShopeeShopMetricsDaily, sid) == 0
        assert await _count(factory, CardContentSpec, sid) == 0
        async with factory() as session:
            assert await session.get(Shop, sid) is not None
            assert await has_consent(session, sid, "service")

        again = await loader.load(factory, generate(END), now=NOW)
        assert again.shop_id == sid and not again.created
        assert again.decisions is not None and not again.decisions.skipped
        assert await _count(factory, ShopProposal, sid) == proposals
        assert await _count(factory, ShopeeShopMetricsDaily, sid) == days
        assert await _count(factory, CardContentSpec, sid) == specs
        async with factory() as session:
            async with with_shop_scope(session, sid):
                assert await content_specs.live_titles_used(session, sid, item) == 0
                sources = set((await session.scalars(select(CardContentSpec.source))).all())
                assert sources == {SOURCE_SEEDED}
                assert SOURCE_LLM not in sources
    finally:
        await engine.dispose()


async def _figures(factory, shop_id):
    """(order-line count, sum of line GMV, shop-day count, sum of shop GMV, product-day rows)."""
    from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily
    from juli_backend.models.shopee_profit import ShopeeOrderLine

    async with factory() as session:
        lines = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(ShopeeOrderLine.deal_price * ShopeeOrderLine.qty), 0),
                ).where(ShopeeOrderLine.shop_id == shop_id)
            )
        ).one()
        shop = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(ShopeeShopMetricsDaily.gmv), 0)).where(
                    ShopeeShopMetricsDaily.shop_id == shop_id
                )
            )
        ).one()
        products = await session.scalar(
            select(func.count()).select_from(ShopeeProductMetricsDaily)
            .where(ShopeeProductMetricsDaily.shop_id == shop_id)
        )  # fmt: skip
    return (lines[0], lines[1], shop[0], shop[1], products)


async def test_reload_with_a_new_end_date_equals_a_fresh_load():
    """R1-1, R1-2, R1-4 and a reviewer's row surviving: A loads D1 then D2; B loads D2 once."""
    from datetime import timedelta

    from scripts.sample_shop.catalog import SAMPLE_SHOPEE_SHOP_ID

    d2 = END
    d1 = END - timedelta(days=3)
    other_id = str(SAMPLE_SHOPEE_SHOP_ID + 1)
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        fresh = await loader.load(factory, generate(d2, shopee_shop_id=other_id), now=NOW)
        fresh_figures = await _figures(factory, fresh.shop_id)
        assert fresh_figures[0] > 0 and fresh_figures[2] > 0

        first = await loader.load(factory, generate(d1), now=NOW)
        sid = first.shop_id
        assert sid != fresh.shop_id
        assert await _figures(factory, sid) != fresh_figures  # the old window really differs
        proposals = await _count(factory, ShopProposal, sid)
        item = PRODUCTS[0].item_id
        async with factory() as session:
            async with with_shop_scope(session, sid):
                session.add(
                    content_specs.llm_title_row(
                        sid, item, current_title=PRODUCTS[0].name, keywords=[],
                        drafts=[{"title": "x", "chars": 1}], model="fake", user_id=None, now=NOW,
                    )
                )  # fmt: skip
                await session.commit()

        await loader.load(factory, generate(d2), now=NOW)
        assert await _figures(factory, sid) == fresh_figures  # R1-1
        assert await _figures(factory, fresh.shop_id) == fresh_figures  # R1-2
        assert await _count(factory, ShopProposal, sid) == proposals
        async with factory() as session:
            async with with_shop_scope(session, sid):
                assert await content_specs.live_titles_used(session, sid, item) == 1  # kept

        await loader.load(factory, generate(d2), now=NOW)
        assert await _figures(factory, sid) == fresh_figures  # R1-4
    finally:
        await engine.dispose()

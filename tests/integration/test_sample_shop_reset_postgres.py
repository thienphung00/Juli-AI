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

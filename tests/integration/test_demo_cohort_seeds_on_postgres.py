"""The demo cohort seeder runs against the Postgres it will actually run on (#1767).

WHY THIS IS INTEGRATION-TIER. Every other test of this seeder uses the shared
`session` fixture, which is SQLite even when `DATABASE_URL` names a Postgres
database. SQLite accepts a timezone-aware datetime in a column typed
`timestamp without time zone`; asyncpg refuses it outright. So the seeder could
— and did — raise on its very first INSERT while a full green suite reported it
working.

That is the same shape as #1675: a substrate that tolerates what production
rejects turns a broken write path into a passing test. The seeder's whole
purpose is to populate the demo environment, and the demo environment is
Postgres, so "it works on SQLite" is not a claim about anything.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.postgres import database_url, requires_postgres

pytestmark = requires_postgres


@pytest.mark.asyncio
async def test_the_seeder_completes_against_real_postgres(monkeypatch) -> None:
    """Run the seeder for real. It must insert, not raise.

    This asserts on rows the seeder wrote, so it cannot pass by the seeder
    silently doing nothing: a seeder that returned early would leave the counts
    at zero and fail here.
    """
    from juli_backend.services.seeds.demo_cohort import seed_demo_cohort_for_impact

    shop_id = str(uuid.uuid4())
    monkeypatch.setitem(os.environ, "DEMO_SHOP_ID", shop_id)

    engine = create_async_engine(database_url().replace("postgresql://", "postgresql+asyncpg://"))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await seed_demo_cohort_for_impact(session)
            await session.commit()

        async with session_factory() as session:
            products = (
                await session.execute(
                    text("select count(*) from products where shop_id = :s"), {"s": shop_id}
                )
            ).scalar()
            analytics = (
                await session.execute(
                    text("select count(*) from analytics_performance_intervals where shop_id = :s"),
                    {"s": shop_id},
                )
            ).scalar()
            roles = (
                (
                    await session.execute(
                        text(
                            "select tiktok_product_id from products where shop_id = :s "
                            "order by tiktok_product_id"
                        ),
                        {"s": shop_id},
                    )
                )
                .scalars()
                .all()
            )

        # The cohort ADR-099 d.3/d.4 requires: a target, five control candidates,
        # and the two products the algorithm must refuse.
        assert products == 8, f"expected the 8-product cohort, found {products}"
        assert "cohort-target" in roles
        assert "cohort-below-floor" in roles
        assert "cohort-degenerate" in roles
        assert sum(1 for r in roles if r.startswith("cohort-candidate-")) == 5, (
            f"the control pool needs five candidates to clear MIN_CANDIDATES=3 "
            f"with margin; found {roles}"
        )
        # T-14..T+14 for eight products is the window the reader measures over.
        assert analytics > 0, "the seeder wrote products but no series to measure"
    finally:
        async with session_factory() as session:
            await session.execute(
                text("delete from analytics_performance_intervals where shop_id = :s"),
                {"s": shop_id},
            )
            await session.execute(text("delete from products where shop_id = :s"), {"s": shop_id})
            await session.execute(text("delete from shops where id = :s"), {"s": shop_id})
            await session.commit()
        await engine.dispose()

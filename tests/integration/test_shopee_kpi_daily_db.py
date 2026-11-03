"""The daily Shopee KPI run on real Postgres, as ``juli_app`` (ADR-117 step 3).

Seeds one synthetic contract shop (the same fixture as ``test_shopee_kpi_db``), runs the
beat's body against the shared database and checks that the shop is picked up, stored,
and then skipped while its inputs are unchanged -- and run again once new data lands.
Other contract shops in the database are run too, so every assertion is about this
shop's own rows. Synthetic rows only; no downgrade.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from juli_backend.models.kpi_contracts import KpiForecast
from juli_backend.services import shopee_kpi_daily
from juli_backend.services.ops import ops_role
from tests.integration.test_shopee_kpi_db import START, _metric, _now, _seed, app_session
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]


async def _stored_rows(session, shop_id) -> int:
    async with ops_role(session):
        n = (
            await session.execute(
                select(func.count()).select_from(KpiForecast).where(KpiForecast.shop_id == shop_id)
            )
        ).scalar_one()
    await session.commit()
    return n


async def test_daily_run_stores_once_then_skips_until_the_data_changes():
    async with app_session() as session:
        shop_id = await _seed(session)
        assert shop_id in await shopee_kpi_daily.contract_shop_ids(session)
        await session.commit()

        await shopee_kpi_daily.run_daily_kpi(app_session)
        first = await _stored_rows(session, shop_id)
        assert first > 0

        # The first run froze the targets, which may re-key the terms once; the run
        # after that must find the stored sha equal to the one it would produce.
        await shopee_kpi_daily.run_daily_kpi(app_session)
        settled = await _stored_rows(session, shop_id)
        await shopee_kpi_daily.run_daily_kpi(app_session)
        assert await _stored_rows(session, shop_id) == settled

        # A new day of data changes the inputs: the shop runs again.
        from juli_backend.database.tenant_context import with_shop_scope

        async with with_shop_scope(session, shop_id):
            session.add(
                _metric(
                    shop_id,
                    START + timedelta(21),
                    "product_card",
                    "all",
                    "traffic_overview",
                    2100,
                    63,
                    6,
                    610_000,
                )
            )
            await session.flush()
        await session.commit()
        await shopee_kpi_daily.run_daily_kpi(app_session, now=_now())
        assert await _stored_rows(session, shop_id) > settled

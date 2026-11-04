"""P91 D-14 on real Postgres, as ``juli_app``: the daily learning step picks the pilot shops through
the Ops role (``ops_list_shops`` + ``ops_shop_settings``), runs each in its own tenant scope and
leaves every other shop alone. Synthetic tenants only."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete

from juli_backend.models.ops import OpsShopSettings
from juli_backend.services import shopee_reco_learning_daily as daily
from juli_backend.services.ops import ops_role
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 5, 18, 40)


async def test_only_the_pilot_stage_shop_is_picked_and_it_runs_clean(shopee_tenants, monkeypatch):
    a, b = shopee_tenants
    monkeypatch.delenv(daily.ENV_SHOP_IDS, raising=False)
    async with juli_app_session() as session:
        async with ops_role(session):
            await session.execute(
                delete(OpsShopSettings).where(OpsShopSettings.shop_id.in_([a.shop_id, b.shop_id]))
            )
            session.add(OpsShopSettings(shop_id=a.shop_id, stage="pilot"))
            session.add(OpsShopSettings(shop_id=b.shop_id, stage="self"))
            await session.commit()
        picked = await daily.pilot_shop_ids(session)
        assert a.shop_id in picked and b.shop_id not in picked
        await session.commit()
    summary = await daily.run_daily_learning(juli_app_session, now=NOW)
    assert summary.shops >= 1 and summary.failed == 0
    again = await daily.run_daily_learning(juli_app_session, now=NOW)  # idempotent
    assert again == summary

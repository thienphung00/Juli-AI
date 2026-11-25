"""P91 D-14 on real Postgres, as ``juli_app``: the daily learning step picks the pilot shops through
the Ops role (``ops_list_shops`` + ``ops_shop_settings``), runs each in its own tenant scope and
leaves every other shop alone. Synthetic tenants only."""

from __future__ import annotations

from dataclasses import replace
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
    # Data layer #74: the job also backfills every Shopee shop's pending stored days (data days
    # with no stored row, or an older stamp), a day budget per shop per run. On a shared test
    # database other tests' shops may still be catching up, so ``rebuilt_days`` falls run by run
    # (never the same days twice) until nothing is pending; the learning itself is idempotent.
    assert replace(again, rebuilt_days=0) == replace(summary, rebuilt_days=0)
    rebuilt = [summary.rebuilt_days, again.rebuilt_days]
    while rebuilt[-1] and len(rebuilt) < 12:
        rebuilt.append((await daily.run_daily_learning(juli_app_session, now=NOW)).rebuilt_days)
    assert rebuilt[-1] == 0, rebuilt
    assert all(b <= a for a, b in zip(rebuilt[1:], rebuilt[2:], strict=False)), rebuilt

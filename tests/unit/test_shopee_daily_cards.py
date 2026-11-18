"""New Shopee cards every day: one shop gets cards sent to the seller, a same-day rerun adds
none, a stale shop and a sample / sandbox shop are skipped, the Connector's daily run enqueues
the task (stock and skip ticks do not), and the 02:03 UTC beat entry exists. SQLite; synthetic."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_recommendations import daily_generation as daily
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks import shopee_daily_cards as task_module
from tests.support.api import client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ingest_connector_ticks import TICK, _token_headers
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant


@pytest.fixture(autouse=True)
def no_minimum_version(monkeypatch):
    """These tests post made-up older versions; the minimum-version gate has its own tests."""
    monkeypatch.setenv("CONNECTOR_MIN_VERSION", "0.0.0")


NOW = datetime(AS_OF.year, AS_OF.month, AS_OF.day, 3, 0) + timedelta(days=1)


@pytest.fixture(autouse=True)
def band_off(monkeypatch):
    monkeypatch.setattr("juli_backend.services.forecast.triggers.clears_band", lambda *a: True)


async def _count(session, shop_id, **where):
    stmt = select(func.count()).select_from(ShopProposal).where(ShopProposal.shop_id == shop_id)
    for k, v in where.items():
        stmt = stmt.where(getattr(ShopProposal, k) == v)
    return await session.scalar(stmt)


async def test_a_shop_gets_cards_sent_and_a_same_day_rerun_adds_none(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    first = await daily.run_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert first.status == "done"
    assert first.generated >= 1 and first.sent == first.generated
    cycle = daily.cycle_key(daily.local_day(NOW))
    total = await _count(session, seeded.shop_id, cycle=cycle)
    assert total == first.generated
    assert await _count(session, seeded.shop_id, cycle=cycle, status="sent") == total
    again = await daily.run_shop(session, seeded.shop_id, now=NOW)
    assert again.status == "already_done"
    assert await _count(session, seeded.shop_id) == total


async def test_a_stale_shop_gets_no_cards_and_a_skip_reason(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    result = await daily.run_shop(session, seeded.shop_id, now=NOW + timedelta(days=30))
    assert result.status == "stale"
    assert result.reason is not None and result.reason.startswith("orders_through_")
    assert await _count(session, seeded.shop_id) == 0


@pytest.mark.parametrize("kind", ["sample", "sandbox"])
async def test_sample_and_sandbox_shops_are_skipped(session, kind):
    seeded = await seed_reco_shop(session)
    seeded.shop.kind = kind
    await session.commit()
    result = await daily.run_shop(session, seeded.shop_id, now=NOW)
    assert result.status == "not_real"
    assert await _count(session, seeded.shop_id) == 0


async def test_the_reserved_sample_id_is_skipped_even_when_kind_is_real(session):
    seeded = await seed_reco_shop(session)
    seeded.shop.shopee_shop_id = "990000000001"
    await session.commit()
    assert (await daily.run_shop(session, seeded.shop_id, now=NOW)).status == "not_real"


async def test_the_daily_run_tick_enqueues_and_stock_and_skip_ticks_do_not(session, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(celery_app, "send_task", lambda name, args: sent.append((name, args[0])))
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        stock = await ext.post(
            "/v1/ingest/connector-ticks", json={**TICK, "trigger": "stock"}, headers=auth
        )
        skip = await ext.post(
            "/v1/ingest/connector-ticks",
            json={**TICK, "kind": "skip", "result": "backfill_busy", "outcomes": {}},
            headers=auth,
        )
        assert stock.status_code == 202 and skip.status_code == 202
        assert sent == []
        daily_run = await ext.post("/v1/ingest/connector-ticks", json=TICK, headers=auth)
    assert daily_run.status_code == 202
    assert sent == [(task_module.SHOPEE_DAILY_CARDS_TASK, str(shop.id))]


async def test_a_broker_failure_never_fails_the_tick(session, monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(celery_app, "send_task", boom)
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        r = await ext.post("/v1/ingest/connector-ticks", json=TICK, headers=auth)
    assert r.status_code == 202


def test_the_beat_entry_runs_at_0203_utc():
    entry = celery_app.conf.beat_schedule["shopee-daily-cards"]
    assert entry["task"] == task_module.SHOPEE_DAILY_CARDS_TASK
    sched = entry["schedule"]
    assert sched.hour == {2} and sched.minute == {3}

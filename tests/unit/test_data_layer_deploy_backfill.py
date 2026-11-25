"""Data layer, deploy plan (a) (owner decision #74): the stored facts are rebuilt right after a
deploy, each shop says when its stored rows may be read, and the same rows can be computed in
memory meanwhile. Synthetic Shopee shop only (SQLite, invented figures)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from sqlalchemy import select, update

from juli_backend.models.shopee_metrics import (
    CampaignMetricsDaily,
    ProductChannelMetricsDaily,
    ShopChannelMetricsDaily,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
    ShopFactsStatus,
)
from juli_backend.services.shopee_analytics import facts_backfill, materialize
from tests.support.builders import make_shop
from tests.support.shopee_analytics import CUR_END, CUR_START, seed_shopee_shop

OLD_STAMP = "2026-11-24.2/r4/f00000000"


class _Factory:
    """Every ``factory()`` hands the test's one session (SQLite, no advisory lock)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> _Factory:
        self.calls += 1
        return self

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *exc: object) -> bool:
        return False


async def _stale(session, shop_id) -> None:
    t = ShopeeShopMetricsDaily
    await session.execute(
        update(t).where(t.shop_id == shop_id).values(derivation_version=OLD_STAMP)
    )
    await session.flush()


async def _status(session, shop_id) -> ShopFactsStatus | None:
    t = ShopFactsStatus
    return (await session.execute(select(t).where(t.shop_id == shop_id))).scalar_one_or_none()


# -- 1. backfill at worker start -------------------------------------------------------------


async def test_an_outdated_real_shop_is_rebuilt_once_and_a_rerun_does_nothing(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    await _stale(session, sid)
    days = len(await materialize.pending_days(session, sid))
    assert days > 0
    first = await facts_backfill.run(_Factory(session))
    assert (first.shops, first.shops_rebuilt, first.days, first.failed) == (1, 1, days, 0)
    assert await materialize.pending_days(session, sid) == []
    again = await facts_backfill.run(_Factory(session))  # a second worker start
    assert (again.shops_rebuilt, again.days) == (0, 0)
    status = await _status(session, sid)
    assert status is not None and status.complete and status.pending_days == 0


async def test_a_current_shop_gets_only_its_status_row(session, monkeypatch):
    seeded = await seed_shopee_shop(session, rules=True)
    called: list[Any] = []

    async def spy(*a: Any, **k: Any) -> int:
        called.append(a)
        return 0

    monkeypatch.setattr(materialize, "rebuild_days", spy)
    result = await facts_backfill.run(_Factory(session))
    assert result.days == 0 and called == []
    assert (await _status(session, seeded.shop_id)).complete


async def test_the_sample_shop_and_tiktok_shops_are_never_rebuilt(session, monkeypatch):
    seeded = await seed_shopee_shop(session, rules=True)
    tiktok = await make_shop(session, seeded.user, platform="tiktok")
    await _stale(session, seeded.shop_id)
    monkeypatch.setattr(
        facts_backfill, "reviewer_sample_shop_ids", lambda: frozenset({seeded.shop_id})
    )
    result = await facts_backfill.run(_Factory(session))
    assert result.shops == 0 and result.days == 0
    assert len(await materialize.pending_days(session, seeded.shop_id)) > 0  # left to Session B
    assert tiktok.id not in await facts_backfill.real_shopee_shops(session)


async def test_rows_with_no_new_grain_are_pending(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    day = CUR_START
    t = ShopeeShopMetricsDaily
    await session.execute(
        t.__table__.delete().where(t.shop_id == sid, t.day == day)
    )  # a data day with no stored row (a grain added since)
    await session.flush()
    assert day in await materialize.pending_days(session, sid)


def test_the_backfill_is_queued_at_worker_start_and_on_the_beat():
    from celery.signals import worker_ready

    from juli_backend.workers.celery_app import celery_app
    from juli_backend.workers.tasks import shopee_facts_backfill as task_module

    entry = celery_app.conf.beat_schedule["shopee-facts-backfill"]
    assert entry["task"] == task_module.SHOPEE_FACTS_BACKFILL_TASK
    assert sorted(entry["schedule"].minute) == [23, 53]
    receivers = [r[1]() for r in worker_ready.receivers]
    assert task_module._backfill_at_worker_start in receivers


def test_worker_start_enqueues_exactly_one_run(monkeypatch):
    from juli_backend.workers.tasks import shopee_facts_backfill as task_module

    sent: list[Any] = []
    monkeypatch.setattr(task_module.shopee_facts_backfill, "apply_async", lambda: sent.append(1))
    task_module._backfill_at_worker_start(sender=None)
    assert sent == [1]


# -- 2. readiness ------------------------------------------------------------------------------


async def test_no_status_row_means_not_ready(session):
    seeded = await seed_shopee_shop(session, rules=True, materialized=False)
    assert not await materialize.facts_ready(session, seeded.shop_id, (CUR_START, CUR_END))


async def test_a_complete_current_shop_is_ready_for_any_window(session):
    seeded = await seed_shopee_shop(session, rules=True)  # backfill_shop refreshes the status
    sid = seeded.shop_id
    assert await materialize.facts_ready(session, sid, (CUR_START, CUR_END))
    assert await materialize.facts_ready(session, sid, (CUR_END - timedelta(days=89), CUR_END))


async def test_ready_from_the_day_after_the_newest_pending_day(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    t = ShopeeShopMetricsDaily
    old = CUR_START + timedelta(days=2)
    await session.execute(
        update(t).where(t.shop_id == sid, t.day <= old).values(derivation_version=OLD_STAMP)
    )
    await materialize.refresh_status(session, sid)
    status = await _status(session, sid)
    assert not status.complete and status.ready_from == old + timedelta(days=1)
    assert await materialize.facts_ready(session, sid, (old + timedelta(days=1), CUR_END))
    assert not await materialize.facts_ready(session, sid, (old, CUR_END))


async def test_a_new_code_version_makes_the_status_not_ready(session, monkeypatch):
    seeded = await seed_shopee_shop(session, rules=True)
    monkeypatch.setattr(materialize, "DERIVATION_VERSION", "2099-01-01.1")
    assert not await materialize.facts_ready(session, seeded.shop_id, (CUR_START, CUR_END))


# -- 3. the in-memory fallback -------------------------------------------------------------------

_SKIP = {"id", "built_at"}
_TABLES = {
    "shop_metrics_daily": (ShopeeShopMetricsDaily, ("day",)),
    "product_metrics_daily": (ShopeeProductMetricsDaily, ("day", "item_id")),
    "source_metrics_daily": (ShopeeSourceMetricsDaily, ("day", "item_id", "source")),
    "product_channel_metrics_daily": (
        ProductChannelMetricsDaily,
        ("day", "item_id", "channel", "discounted"),
    ),
    "shop_channel_metrics_daily": (ShopChannelMetricsDaily, ("day", "channel", "discounted")),
    "campaign_metrics_daily": (CampaignMetricsDaily, ("day", "campaign_id")),
}


def _norm(value: Any) -> Any:
    if isinstance(value, D):
        return value.quantize(D("0.01"))
    return value


def _key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(k)) for k in keys)


@pytest.mark.parametrize("days", [7, 30, 90])
async def test_fallback_rows_equal_the_stored_rows(session, days):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    start = CUR_END - timedelta(days=days - 1)
    rows = await materialize.compute_facts(session, sid, start, CUR_END)
    for name, (model, keys) in _TABLES.items():
        stored = (
            (
                await session.execute(
                    select(model).where(
                        model.shop_id == sid, model.day >= start, model.day <= CUR_END
                    )
                )
            )
            .scalars()
            .all()
        )
        want = {
            _key({c.name: getattr(r, c.name) for c in model.__table__.columns}, keys): {
                c.name: _norm(getattr(r, c.name))
                for c in model.__table__.columns
                if c.name not in _SKIP
            }
            for r in stored
        }
        got_rows = getattr(rows, name)
        got = {
            _key(r, keys): {c: _norm(r.get(c)) for c in want[_key(r, keys)]}
            for r in got_rows
            if _key(r, keys) in want
        }
        assert {_key(r, keys) for r in got_rows} == set(want), name
        for k, cells in want.items():
            for col, value in cells.items():
                if (
                    col in ("sources", "detail", "complete", "scaled_to_totals")
                    and got[k][col] is None
                ):
                    continue  # server defaults of the stored row, not in the computed dict
                assert got[k][col] == value, (name, k, col)
    assert rows.shop_metrics_daily, "the fixture has data days in the window"


async def test_fallback_writes_nothing(session):
    seeded = await seed_shopee_shop(session, rules=True, materialized=False)
    rows = await materialize.compute_facts(session, seeded.shop_id, CUR_START, CUR_END)
    assert rows.shop_metrics_daily and rows.product_channel_metrics_daily
    t = ShopeeShopMetricsDaily
    assert (await session.execute(select(t).where(t.shop_id == seeded.shop_id))).first() is None

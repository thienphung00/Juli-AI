"""W3 t1 review fixes: the breakdown merge on the interval upsert, the re-read inside its lock,
and the funnel check's sum identity on a TikTok day. Synthetic data only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.integrations.tiktok.mapping import (
    A34_BLOCKS_KEY,
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
)
from juli_backend.repositories.analytics import AnalyticsPerformanceRepo
from juli_backend.services.etl.transform import transform_for_channel
from juli_backend.workers.services.polling import ingestion
from juli_backend.workers.services.polling.analytics_range import (
    BLOCKS_REREAD_STATE_KEY,
    BlocksReread,
)
from tests.support.builders import make_shop, make_user
from tests.support.tiktok_a34 import a34_row

DAY = date(2026, 11, 10)
CHANNEL = "tiktok.analytics.product.raw"


def _detail(synced_at: int) -> dict:
    rows = expand_analytics_product_detail(
        {
            "performance": {
                "intervals": [
                    {
                        "start_date": DAY.isoformat(),
                        "end_date": (DAY + timedelta(days=1)).isoformat(),
                        "sales": {"gmv": {"amount": "450000", "currency": "VND"}, "orders": 4},
                        "traffic": {
                            "breakdowns": [
                                {
                                    "content_type": "VIDEO",
                                    "traffic": {"impressions": 400, "ctr": "0.05"},
                                }
                            ]
                        },
                    }
                ]
            }
        },
        synced_at=synced_at,
        product_id="p1",
    )
    return rows[0]


def _list(synced_at: int) -> dict:
    return expand_analytics_product_list_item(
        a34_row("p1"),
        start_date=DAY.isoformat(),
        end_date=(DAY + timedelta(days=1)).isoformat(),
        synced_at=synced_at,
    )


async def _write(session, shop_id, payload):
    _, kwargs = transform_for_channel(CHANNEL, payload)
    return await AnalyticsPerformanceRepo(session).upsert(shop_id=shop_id, **kwargs)


@pytest.mark.parametrize("first,second", [(_list, _detail), (_detail, _list)])
async def test_a_later_write_keeps_the_breakdown_keys_it_does_not_carry(session, first, second):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    await _write(session, shop.id, first(1_763_000_000))
    row = await _write(session, shop.id, second(1_763_000_100))
    keys = set(row.traffic_breakdown)
    assert {"VIDEO", "A34_TOTAL", A34_BLOCKS_KEY} <= keys


async def test_the_incoming_key_still_replaces_the_same_key(session):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    await _write(session, shop.id, _detail(1_763_000_000))
    newer = _detail(1_763_000_100)
    newer["traffic_breakdown"]["VIDEO"]["impressions"] = 999
    row = await _write(session, shop.id, newer)
    assert row.traffic_breakdown["VIDEO"]["impressions"] == 999


async def test_a_stale_write_changes_nothing(session):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    await _write(session, shop.id, _detail(1_763_000_100))
    row = await _write(session, shop.id, _list(1_763_000_000))
    assert A34_BLOCKS_KEY not in row.traffic_breakdown


# ------------------------------------------------------------------- re-read inside its lock


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_the_reread_stops_between_windows_before_its_budget_and_saves_each_window(
    monkeypatch, session
):
    from contextlib import asynccontextmanager

    clock = _Clock()
    saves: list[int] = []
    state: dict[str, Any] = {}

    class _Repo:
        async def save(self, shop_id, sync_state):
            saves.append(sync_state.get(BLOCKS_REREAD_STATE_KEY))

    @asynccontextmanager
    async def fake_run(**kwargs):
        yield SimpleNamespace(
            resources=SimpleNamespace(analytics=None),
            app_id="app",
            shop_key="tt",
            sync_state=state,
            sync_state_repo=_Repo(),
        )

    windows = iter(range(10))

    async def fake_reread(**kwargs):
        n = next(windows)
        clock.now += 400.0  # each window takes 400 s of the budget
        start = date(2026, 11, 1) - timedelta(days=30 * n)
        kwargs["sync_state"][BLOCKS_REREAD_STATE_KEY] = start.toordinal()
        return BlocksReread(start, start + timedelta(days=30), [start], True, rows=1)

    async def fake_touch(*args, **kwargs):
        return None

    monkeypatch.setattr(ingestion, "_scoped_shop_run", fake_run)
    monkeypatch.setattr(ingestion, "reread_product_blocks", fake_reread)
    monkeypatch.setattr(ingestion, "record_touched_days", fake_touch)
    await ingestion.run_blocks_reread(
        session=session,
        config=None,
        shop_id="shop",
        rate_limiter=None,
        handoff_fn=None,
        budget_seconds=1000.0,
        window_min_seconds=300.0,
        clock=clock,
    )
    # 1000 s: window 1 (600 left), window 2 (200 left < 300) -> stop before window 3
    assert clock.now == 800.0
    assert saves[:2] == [
        date(2026, 11, 1).toordinal(),
        (date(2026, 11, 1) - timedelta(days=30)).toordinal(),
    ]


async def test_the_lock_ttl_always_covers_the_reread_budget():
    from juli_backend.workers.tasks import shop_ingestion

    ttls: list[int] = []
    budgets: list[float] = []

    class _Lock:
        def try_acquire(self, shop_id, name, ttl_seconds):
            ttls.append(ttl_seconds)
            return "t"

        def release(self, *a):
            return None

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    clock = _Clock()

    async def enumerate_fn(_s):
        return [SimpleNamespace(shop_id=f"s{i}") for i in range(4)]

    async def reread_fn(*, session, shop_id, now, budget_seconds, **kw):
        budgets.append(budget_seconds)
        clock.now += budget_seconds  # each shop spends its whole budget
        return frozenset()

    async def rebuild_fn(_s, _id, *, today):
        return 0

    async def collaborators(_s):
        return {}

    from contextlib import asynccontextmanager

    import juli_backend.database.tenant_context as tc

    @asynccontextmanager
    async def no_scope(*a):
        yield

    original, tc.with_sticky_shop_scope = tc.with_sticky_shop_scope, no_scope
    try:
        await shop_ingestion.run_layer4_rebuild_fanout(
            lambda: _Session(),
            lock=_Lock(),
            collaborators=collaborators,
            enumerate_fn=enumerate_fn,
            reread_fn=reread_fn,
            rebuild_fn=rebuild_fn,
            now=datetime(2026, 11, 22, 22, tzinfo=UTC),
            clock=clock,
        )
    finally:
        tc.with_sticky_shop_scope = original
    assert budgets and all(ttl > b for ttl, b in zip(ttls, budgets, strict=True))
    walk = (
        shop_ingestion._LAYER4_REBUILD_TIMEOUT_SECONDS
        - shop_ingestion._LAYER4_REBUILD_RESERVE_SECONDS
    )
    assert sum(budgets) <= walk, "the re-reads leave the reserve for the rebuilds"
    assert len(budgets) < 4, "a shop is skipped once too little time is left"


# ------------------------------------------------------------------------------ funnel check


async def test_a_tiktok_day_logs_no_sources_sum_mismatch_for_the_shop_tab(session, monkeypatch):
    from juli_backend.repositories import shopee_analytics as repo
    from juli_backend.services.shopee_analytics import funnel_check, materialize
    from tests.unit.test_w3_t1_tiktok_layer4 import D1, seed_tiktok_shop

    monkeypatch.setattr(repo, "PLATFORM_SHOPEE", "tiktok")  # t2's own_platform() stand-in
    shop = await seed_tiktok_shop(session)
    await materialize.rebuild_days(session, shop.id, [D1])
    found = await funnel_check.check_day(session, shop.id, D1)
    assert [m for m in found if m.kind == "sources_sum"] == []

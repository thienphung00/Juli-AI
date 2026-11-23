"""W3 t1 (M-1): what builds TikTok's layer-4 rows with no manual step -- the shop cycle after its
analytics pass (and the A-34 blocks re-read), and the nightly rebuild beat."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from juli_backend.workers.services.polling import ingestion
from juli_backend.workers.services.polling.analytics_range import (
    BLOCKS_REREAD_DAYS,
    BLOCKS_REREAD_STATE_KEY,
    AnalyticsRangeResult,
)
from juli_backend.workers.services.polling.sync import SyncOutcome
from juli_backend.workers.tasks import shop_ingestion

TODAY = date(2026, 11, 23)


def _analytics(*days: date) -> AnalyticsRangeResult:
    return AnalyticsRangeResult(
        outcome=SyncOutcome(resource="analytics", shop_id="tt-shop"),
        start=min(days),
        end_exclusive=max(days) + timedelta(days=1),
        days_with_rows={d.isoformat() for d in days},
    )


async def test_the_cycle_rebuilds_the_days_its_analytics_pass_landed(monkeypatch):
    touched: list[tuple[frozenset[date], str]] = []

    async def fake_touch(session, shop_id, days, *, dataset):
        touched.append((days, dataset))

    monkeypatch.setattr(ingestion, "record_touched_days", fake_touch)
    run = SimpleNamespace(session=object(), shop_id="shop-uuid")
    landed = (TODAY - timedelta(days=3), TODAY - timedelta(days=2))
    assert await ingestion.refresh_analytics_layer4(run, _analytics(*landed)) == frozenset(landed)
    assert touched == [(frozenset(landed), "analytics")]
    assert await ingestion.refresh_analytics_layer4(run, None) == frozenset()
    assert len(touched) == 1


class _Analytics:
    """A-34 per day and A-33 daily intervals for the asked range (synthetic)."""

    def __init__(self) -> None:
        self.list_calls = 0

    def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str):
        from tests.support.tiktok_a34 import a34_row

        self.list_calls += 1
        return [a34_row("p1")]

    def get_product_performance(self, *, product_id: str, start_date_ge: str, end_date_lt: str):
        start, end = date.fromisoformat(start_date_ge), date.fromisoformat(end_date_lt)
        return {
            "performance": {
                "intervals": [
                    {
                        "start_date": (start + timedelta(days=i)).isoformat(),
                        "end_date": (start + timedelta(days=i + 1)).isoformat(),
                        "sales": {"gmv": {"amount": "450000", "currency": "VND"}, "orders": 4},
                    }
                    for i in range((end - start).days)
                ]
            }
        }


async def test_the_nightly_reread_walks_the_90_days_saves_the_cursor_and_rebuilds(
    monkeypatch, session
):
    from contextlib import asynccontextmanager

    from tests.support.shop_ingestion_fakes import FakeRateLimiter

    analytics = _Analytics()
    saved: dict[str, Any] = {}
    touched: list[frozenset[date]] = []

    class _Repo:
        async def save(self, shop_id, state):
            saved.update(state)

    @asynccontextmanager
    async def fake_run(**kwargs):
        yield SimpleNamespace(
            resources=SimpleNamespace(analytics=analytics),
            app_id="app",
            shop_key="tt-shop",
            sync_state=dict(saved),
            sync_state_repo=_Repo(),
        )

    async def fake_touch(session, shop_id, days, *, dataset):
        touched.append(days)

    async def handoff(channel, shop_key, payload):
        return None

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(ingestion, "_scoped_shop_run", fake_run)
    monkeypatch.setattr(ingestion, "record_touched_days", fake_touch)
    kwargs = dict(
        session=session,
        config=None,
        shop_id="shop-uuid",
        rate_limiter=FakeRateLimiter(),
        handoff_fn=handoff,
        sleep=no_sleep,
        now=datetime(2026, 11, 23, 1, tzinfo=UTC),
    )
    days = await ingestion.run_blocks_reread(**kwargs)
    assert len(days) == BLOCKS_REREAD_DAYS and touched == [days]
    assert saved[BLOCKS_REREAD_STATE_KEY] == (TODAY - timedelta(days=90)).toordinal()
    calls = analytics.list_calls
    assert await ingestion.run_blocks_reread(**kwargs) == frozenset()
    assert analytics.list_calls == calls, "a finished walk makes no call"


async def test_the_tiktok_hook_reaches_the_rebuild(monkeypatch, session):
    """``record_touched_days`` -> ``materialize.after_ingest`` for platform tiktok (no no-op)."""
    from juli_backend.services.ingest import tiktok_canonical
    from juli_backend.services.shopee_analytics import materialize

    calls: list[tuple[str, str, date, date]] = []

    async def fake_rebuild(session, shop_id, days):
        calls.append(("rebuild", "", min(days), max(days)))
        return len(list(days))

    monkeypatch.setattr(materialize, "rebuild_days", fake_rebuild)
    day = date(2026, 11, 20)
    await tiktok_canonical.record_touched_days(
        session, "shop", frozenset({day, day + timedelta(days=1)}), dataset="analytics"
    )
    assert calls == [("rebuild", "", day, day + timedelta(days=1))]


async def test_the_nightly_rebuild_walks_every_tiktok_shop_and_survives_one_failure(session):
    class _Factory:
        def __call__(self):
            return _Session()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    shops = [SimpleNamespace(shop_id="a"), SimpleNamespace(shop_id="b")]
    seen: list[tuple[str, date]] = []

    async def enumerate_fn(_session):
        return shops

    reread: list[str] = []

    async def reread_fn(*, session, shop_id, now, **kwargs):
        reread.append(shop_id)
        return frozenset()

    class _Lock:
        def try_acquire(self, shop_id, name, ttl_seconds):
            return None if shop_id == "b" else "token"

        def release(self, shop_id, name, token):
            return None

    async def collaborators(_session):
        return {"config": None, "rate_limiter": None, "handoff_fn": None}

    async def rebuild_fn(_session, shop_id, *, today):
        seen.append((shop_id, today))
        if shop_id == "a":
            raise RuntimeError("one shop fails")
        return 7

    from contextlib import asynccontextmanager

    import juli_backend.database.tenant_context as tenant_context

    @asynccontextmanager
    async def no_scope(_session, _shop_id):
        yield

    original = tenant_context.with_sticky_shop_scope
    tenant_context.with_sticky_shop_scope = no_scope
    try:
        days = await shop_ingestion.run_layer4_rebuild_fanout(
            _Factory(),
            lock=_Lock(),
            collaborators=collaborators,
            enumerate_fn=enumerate_fn,
            reread_fn=reread_fn,
            rebuild_fn=rebuild_fn,
            now=datetime(2026, 11, 22, 22, 9, tzinfo=UTC),
        )
    finally:
        tenant_context.with_sticky_shop_scope = original
    assert days == 7
    assert reread == ["a"], "a shop whose cycle lock is held is re-read another night"
    assert seen == [("a", TODAY), ("b", TODAY)], "today is the VN day of the run"


def test_the_nightly_rebuild_is_on_the_beat():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["tiktok-layer4-rebuild"]
    assert entry["task"] == shop_ingestion.LAYER4_REBUILD_TASK

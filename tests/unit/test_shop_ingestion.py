"""Per-shop ingestion: bootstrap, history, scheduling, cadence, isolation (fast track P1-B).

ACCEPTANCE.md AC-1.1 – AC-1.6, AC-1.10, AC-1.12. AC-1.7 (parallel detail
calls) lives in ``test_analytics_range_parallel.py``.

Every vendor call goes to ``tests/support/shop_ingestion_fakes.py``; nothing
here reaches TikTok, Redis or a broker.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import call

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.ingestion import (
    BOOTSTRAP_FAST_DONE,
    BOOTSTRAP_HISTORY_DONE,
    ShopIngestionState,
)
from juli_backend.models.models import (
    ActionCard,
    AnalyticsPerformanceInterval,
    Order,
    Product,
    Return,
    Shop,
    User,
)
from juli_backend.repositories import ShopIngestionStateRepo, TikTokCredentialRepo
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion import make_etl_handoff
from juli_backend.workers.services.polling import FujiwaPollConfig
from juli_backend.workers.services.polling import ingestion as ingestion_module
from juli_backend.workers.services.polling.ingestion import (
    enumerate_pollable_shops,
    run_bootstrap_fast_phase,
    run_history_chunks,
    run_shop_cycle,
)
from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
from tests.support.shop_ingestion_fakes import (
    FakeAnalyticsResource,
    FakeRateLimiter,
    make_resources,
)

TODAY = date(2026, 7, 16)
NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
LATEST = date(2026, 7, 15)
CONFIG = FujiwaPollConfig(app_key="app-key", app_secret="app-secret")

ANALYTICS_CHANNELS = frozenset(
    {
        "tiktok.analytics.shop.raw",
        "tiktok.analytics.product.raw",
        "tiktok.analytics.sku.raw",
        "tiktok.analytics.live.raw",
    }
)


@pytest.fixture(autouse=True)
def _no_lazy_refresh(monkeypatch):
    """`_lazy_refresh` is a no-op without TikTok app env -- keep it that way."""
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)


async def _no_sleep(_seconds: float) -> None:
    return None


# -- builders ---------------------------------------------------------------


async def _make_shop(
    session,
    *,
    label: str,
    capability: TikTokCapability = TikTokCapability.SELLER_CONNECT,
    status: str = "active",
    is_active: bool = True,
    with_credential: bool = True,
    seed_scoring_data: bool = False,
) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name=f"{label} shop",
        tiktok_shop_id=f"tt-{label}-{uuid.uuid4().hex[:6]}",
        is_active=is_active,
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=120),
    )
    session.add_all([user, shop])
    await session.flush()
    if with_credential:
        credential = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token=f"access-{label}",
            refresh_token=f"refresh-{label}",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=f"merchant-{label}",
            capability=capability.value,
            shop_cipher=f"cipher-{label}",
        )
        if status != "active":
            credential.status = status
    if seed_scoring_data:
        now = datetime.now(UTC)
        session.add_all(
            [
                Product(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    tiktok_product_id=f"{label}-seed-product",
                    name=f"{label} widget",
                    status="ACTIVE",
                    revenue=Decimal("800000"),
                    units_sold=40,
                    update_time=now,
                ),
                Order(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    tiktok_order_id=f"{label}-ord",
                    status="COMPLETED",
                    total_amount=Decimal("150000"),
                    currency="VND",
                    update_time=now,
                ),
                Return(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    tiktok_return_id=f"{label}-ret",
                    tiktok_order_id=f"{label}-ord",
                    return_type="refund",
                    refund_amount=Decimal("10000"),
                    status="COMPLETED",
                    update_time=now,
                ),
            ]
        )
    await session.flush()
    await session.commit()
    return shop


class Handoffs:
    """Analytics rows go through the REAL ETL; commerce rows are captured.

    Commerce mocks return vendor-shaped stubs the ETL would reject -- they are
    here to prove the commerce steps ran, not to test the order mapper.
    """

    def __init__(self, session) -> None:
        async def _dlq(channel: str, shop_key: str, payload: bytes) -> None:
            self.dlq.append(channel)

        self.dlq: list[str] = []
        self.captured: list[tuple[str, str]] = []
        self._etl = make_etl_handoff(EtlConsumer(session=session, dlq_handoff=_dlq))
        self.analytics: list[tuple[str, str, dict]] = []

    async def __call__(self, channel: str, shop_key: str, payload: bytes) -> None:
        if channel in ANALYTICS_CHANNELS:
            self.analytics.append((channel, shop_key, json.loads(payload)))
            await self._etl(channel, shop_key, payload)
        else:
            self.captured.append((channel, shop_key))


async def _product_days(session, shop_id) -> set[date]:
    rows = await session.execute(
        select(AnalyticsPerformanceInterval.start_date).where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.grain == "product",
        )
    )
    return {row[0] for row in rows.all()}


async def _state(session, shop_id) -> ShopIngestionState:
    state = await ShopIngestionStateRepo(session).find(shop_id)
    assert state is not None
    return state


async def _fast(
    session, shop, analytics, *, score_fn=None, rate_limiter=None, orders=None, **kwargs
):
    handoff = Handoffs(session)
    result = await run_bootstrap_fast_phase(
        session=session,
        config=CONFIG,
        shop_id=shop.id,
        rate_limiter=rate_limiter or FakeRateLimiter(),
        handoff_fn=handoff,
        create_resources=lambda _cfg: make_resources(analytics, orders=orders),
        sleep=_no_sleep,
        now=NOW,
        score_fn=score_fn,
        **kwargs,
    )
    return result, handoff


async def _count_score(session, shop_id):
    return [object()]


# ---------------------------------------------------------------------------
# AC-1.1 -- the OAuth callback enqueues bootstrap AFTER commit; never fails on it
# ---------------------------------------------------------------------------


class _CallbackService:
    def verify_state(self, state):
        return uuid.uuid4()

    async def exchange_code(self, code, *, user_id=None):
        return {"access_token_expire_in": 3600}


class _Facade:
    def __init__(self, shop_id, events):
        self.shop_id = shop_id
        self.events = events

    async def provision_shop_and_credentials(self, token_data, *, user_id):
        self.events.append("provision")
        return SimpleNamespace(id=self.shop_id, tiktok_shop_id="tt-new")


class _Session:
    def __init__(self, events, *, fail_commit=False):
        self.events = events
        self.fail_commit = fail_commit

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.events.append("commit")


class _RecordingDispatcher:
    def __init__(self, events, *, raises=False):
        self.events = events
        self.raises = raises
        self.calls: list[dict] = []

    def enqueue(self, shop_id, *, connect_committed_at, enqueued_at):
        self.events.append("enqueue")
        if self.raises:
            raise ConnectionError("broker down")
        self.calls.append(
            {
                "shop_id": shop_id,
                "connect_committed_at": connect_committed_at,
                "enqueued_at": enqueued_at,
            }
        )
        return "task-1"


class TestOAuthCallbackEnqueuesBootstrap:
    async def _callback(self, monkeypatch, *, dispatcher, fail_commit=False):
        from juli_backend.services.ingestion import set_bootstrap_dispatcher
        from juli_backend.services.tiktok import oauth

        events: list[str] = []
        shop_id = uuid.uuid4()
        dispatcher.events = events
        monkeypatch.setattr(
            oauth, "build_partner_oauth_facade", lambda session, svc: _Facade(shop_id, events)
        )
        set_bootstrap_dispatcher(dispatcher)
        try:
            result = await oauth.complete_tiktok_oauth_callback(
                _Session(events, fail_commit=fail_commit),
                code="code",
                state="signed-state",
                oauth_service=_CallbackService(),
            )
        finally:
            set_bootstrap_dispatcher(None)
        return result, events, shop_id

    @pytest.mark.asyncio
    async def test_enqueues_bootstrap_for_the_shop_after_the_commit(self, monkeypatch, caplog):
        dispatcher = _RecordingDispatcher([])
        caplog.set_level(logging.INFO)
        result, events, shop_id = await self._callback(monkeypatch, dispatcher=dispatcher)

        assert result.status == "ok"
        assert events == ["provision", "commit", "enqueue"]
        assert dispatcher.calls[0]["shop_id"] == str(shop_id)
        assert dispatcher.calls[0]["connect_committed_at"] is not None
        names = [record.getMessage() for record in caplog.records]
        assert "shop_connect_committed" in names
        assert "shop_bootstrap_enqueued" in names

    @pytest.mark.asyncio
    async def test_an_enqueue_failure_is_logged_and_does_not_fail_the_callback(
        self, monkeypatch, caplog
    ):
        dispatcher = _RecordingDispatcher([], raises=True)
        caplog.set_level(logging.INFO)
        result, events, _ = await self._callback(monkeypatch, dispatcher=dispatcher)

        assert result.status == "ok"
        assert events == ["provision", "commit", "enqueue"]
        failures = [r for r in caplog.records if r.getMessage() == "shop_bootstrap_enqueue_failed"]
        assert failures and failures[0].levelno == logging.ERROR

    @pytest.mark.asyncio
    async def test_an_unbound_dispatcher_does_not_fail_the_callback(self, monkeypatch, caplog):
        from juli_backend.services.ingestion import set_bootstrap_dispatcher
        from juli_backend.services.tiktok import oauth

        monkeypatch.setattr(
            oauth,
            "build_partner_oauth_facade",
            lambda session, svc: _Facade(uuid.uuid4(), []),
        )
        set_bootstrap_dispatcher(None)
        caplog.set_level(logging.INFO)
        result = await oauth.complete_tiktok_oauth_callback(
            _Session([]), code="c", state="s", oauth_service=_CallbackService()
        )
        assert result.status == "ok"
        assert any(r.getMessage() == "shop_bootstrap_enqueue_failed" for r in caplog.records)

    @pytest.mark.asyncio
    async def test_nothing_is_enqueued_when_the_commit_fails(self, monkeypatch):
        dispatcher = _RecordingDispatcher([])
        with pytest.raises(RuntimeError, match="commit failed"):
            await self._callback(monkeypatch, dispatcher=dispatcher, fail_commit=True)
        assert dispatcher.calls == []

    def test_the_celery_dispatcher_routes_bootstrap_to_the_high_priority_queue(self, monkeypatch):
        from juli_backend.workers.dispatch_binding import CeleryBootstrapDispatcher
        from juli_backend.workers.tasks import shop_ingestion

        captured: dict = {}

        def _apply_async(*, args, kwargs, queue):
            captured.update(args=args, kwargs=kwargs, queue=queue)
            return SimpleNamespace(id="celery-task-id")

        monkeypatch.setattr(shop_ingestion.bootstrap_shop, "apply_async", _apply_async)
        task_id = CeleryBootstrapDispatcher().enqueue(
            "shop-1", connect_committed_at="2026-07-16T10:00:00", enqueued_at="x"
        )
        assert task_id == "celery-task-id"
        assert captured["queue"] == shop_ingestion.QUEUE_PRIORITY == "ingest_priority"
        assert captured["args"] == ["shop-1"]

    def test_task_routes_put_bootstrap_high_and_history_low(self):
        from juli_backend.workers.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert routes["juli_backend.bootstrap_shop"] == {"queue": "ingest_priority"}
        assert routes["juli_backend.shop_history_backfill"] == {"queue": "ingest_backfill"}


# ---------------------------------------------------------------------------
# AC-1.2 / AC-1.4 / AC-1.10 -- fast phase
# ---------------------------------------------------------------------------


class TestFastPhase:
    @pytest.mark.asyncio
    async def test_writes_30_distinct_days_with_one_detail_call_per_item_and_persists_a_card(
        self, session
    ):
        shop = await _make_shop(session, label="fast", seed_scoring_data=True)
        analytics = FakeAnalyticsResource(prefix="fast")
        connected = datetime(2026, 7, 16, 9, 59, 0)

        from juli_backend.workers.tasks.shop_ingestion import score_and_persist_cards

        result, handoff = await _fast(
            session,
            shop,
            analytics,
            score_fn=score_and_persist_cards,
            orders=[{"id": "o-1", "update_time": 1_784_000_000}],
            connect_committed_at=connected,
            enqueued_at=connected + timedelta(seconds=1),
        )

        # 30 distinct days, ending at TikTok's latest_available_date.
        days = await _product_days(session, shop.id)
        assert len(days) == 30
        assert max(days) == LATEST
        assert min(days) == LATEST - timedelta(days=29)
        assert result.window_start == LATEST - timedelta(days=29)
        assert result.window_end_exclusive == LATEST + timedelta(days=1)

        # Date-range calls: ONE detail call per product / per SKU for the window.
        product_calls = analytics.calls["get_product_performance"]
        assert len(product_calls) == len(analytics.products)
        assert {(c["start"], c["end"]) for c in product_calls} == {
            ((LATEST - timedelta(days=29)).isoformat(), (LATEST + timedelta(days=1)).isoformat())
        }
        assert len(analytics.calls["get_sku_performance"]) == len(analytics.skus)

        # Commerce cold start: no watermark, so the first read is the backfill.
        resources_orders_calls = [c for c in handoff.captured if c[0] == "tiktok.orders.raw"]
        assert resources_orders_calls, "the commerce orders step ran"

        # Scoring + card persistence ran for this shop, with no second poll.
        cards = (
            await session.execute(
                select(func.count()).select_from(ActionCard).where(ActionCard.shop_id == shop.id)
            )
        ).scalar_one()
        assert cards >= 1
        assert result.cards and result.cards >= 1

        state = await _state(session, shop.id)
        assert state.status == BOOTSTRAP_FAST_DONE
        assert state.analytics_through_date == LATEST
        assert state.history_earliest_date == LATEST - timedelta(days=29)
        assert state.latest_available_date == LATEST
        # AC-1.4 / AC-1.10: the latency timestamps are persisted, in order.
        assert state.connect_committed_at == connected
        assert state.bootstrap_enqueued_at == connected + timedelta(seconds=1)
        assert state.fast_started_at is not None
        assert state.fast_done_at is not None and state.first_card_at is not None
        assert state.fast_started_at <= state.fast_done_at <= state.first_card_at

    @pytest.mark.asyncio
    async def test_commerce_steps_run_as_a_cold_start(self, session):
        shop = await _make_shop(session, label="cold")
        analytics = FakeAnalyticsResource(prefix="cold")
        resources = make_resources(analytics)

        await run_bootstrap_fast_phase(
            session=session,
            config=CONFIG,
            shop_id=shop.id,
            rate_limiter=FakeRateLimiter(),
            handoff_fn=Handoffs(session),
            create_resources=lambda _cfg: resources,
            sleep=_no_sleep,
            now=NOW,
            score_fn=_count_score,
        )
        for search in (
            resources.orders.search_all,
            resources.products.search_all,
            resources.returns.search_returns_all,
        ):
            assert search.call_args_list == [call(update_time_from=None)], "cold start"

    @pytest.mark.asyncio
    async def test_emits_a_structured_event_at_each_transition(self, session, caplog):
        shop = await _make_shop(session, label="events")
        caplog.set_level(logging.INFO)
        await _fast(
            session,
            shop,
            FakeAnalyticsResource(prefix="events"),
            score_fn=_count_score,
            connect_committed_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        events = {
            record.getMessage(): record
            for record in caplog.records
            if record.getMessage().startswith("shop_")
        }
        for name in (
            "shop_bootstrap_fast_started",
            "shop_bootstrap_fast_done",
            "shop_first_card_persisted",
        ):
            assert name in events, name
            assert events[name].shop_id == str(shop.id)
        assert events["shop_first_card_persisted"].seconds_since_connect is not None

    @pytest.mark.asyncio
    async def test_a_completed_fast_phase_is_not_re_run(self, session):
        shop = await _make_shop(session, label="again")
        analytics = FakeAnalyticsResource(prefix="again")
        await _fast(session, shop, analytics, score_fn=_count_score)
        calls = analytics.detail_calls()

        result, _ = await _fast(session, shop, analytics, score_fn=_count_score)
        assert result.skipped and result.reason == "fast_done"
        assert analytics.detail_calls() == calls

    @pytest.mark.asyncio
    async def test_a_scoring_failure_keeps_the_fast_phase_done(self, session):
        shop = await _make_shop(session, label="scorefail")

        async def broken(session, shop_id):
            raise RuntimeError("scoring blew up")

        result, _ = await _fast(session, shop, FakeAnalyticsResource(prefix="sf"), score_fn=broken)
        assert result.cards is None
        state = await _state(session, shop.id)
        assert state.fast_done_at is not None and state.first_card_at is None
        assert "scoring" in (state.last_error or "")

    @pytest.mark.asyncio
    async def test_a_failed_fast_phase_is_recorded_and_raises(self, session):
        shop = await _make_shop(session, label="boom")
        analytics = FakeAnalyticsResource(prefix="boom")

        def explode(**_kwargs):
            raise RuntimeError("vendor exploded")

        setattr(analytics, "list_product_performance_all", explode)
        with pytest.raises(RuntimeError, match="vendor exploded"):
            await _fast(session, shop, analytics, score_fn=_count_score)
        state = await _state(session, shop.id)
        assert state.status == "failed" and state.failed_phase == "fast"
        assert state.fast_done_at is None


# ---------------------------------------------------------------------------
# AC-1.3 -- history phase
# ---------------------------------------------------------------------------


async def _history(session, shop, analytics, *, rate_limiter=None, **kwargs):
    return await run_history_chunks(
        session=session,
        config=CONFIG,
        shop_id=shop.id,
        rate_limiter=rate_limiter or FakeRateLimiter(),
        handoff_fn=Handoffs(session),
        create_resources=lambda _cfg: make_resources(analytics),
        sleep=_no_sleep,
        now=NOW,
        chunk_days=30,
        **kwargs,
    )


class TestHistoryPhase:
    @pytest.mark.asyncio
    async def test_walks_back_in_chunks_until_no_data_and_records_the_earliest_date(
        self, session, caplog
    ):
        shop = await _make_shop(session, label="hist")
        # TikTok has 100 days of data before the latest available day.
        analytics = FakeAnalyticsResource(prefix="hist", earliest_data=LATEST - timedelta(days=99))
        await _fast(session, shop, analytics, score_fn=_count_score)
        caplog.set_level(logging.INFO)

        result = await _history(session, shop, analytics, max_chunks=20, empty_chunks_to_stop=2)

        fast_start = LATEST - timedelta(days=29)
        expected = [
            (fast_start - timedelta(days=30 * (i + 1)), fast_start - timedelta(days=30 * i))
            for i in range(5)
        ]
        assert result.chunks == expected
        assert result.done and result.reason == "no_data"
        state = await _state(session, shop.id)
        assert state.status == BOOTSTRAP_HISTORY_DONE
        assert state.history_earliest_date == expected[-1][0]
        assert state.history_chunks_done == 5
        assert state.history_done_at is not None
        # Every day TikTok had is now stored: 100 days in total.
        days = await _product_days(session, shop.id)
        assert len(days) == 100
        assert min(days) == LATEST - timedelta(days=99)
        names = {r.getMessage() for r in caplog.records}
        assert {"shop_history_started", "shop_history_chunk_done", "shop_history_done"} <= names

    @pytest.mark.asyncio
    async def test_is_resumable_and_never_refetches_a_completed_chunk(self, session):
        shop = await _make_shop(session, label="resume")
        analytics = FakeAnalyticsResource(prefix="res", earliest_data=LATEST - timedelta(days=200))
        await _fast(session, shop, analytics, score_fn=_count_score)

        first = await _history(session, shop, analytics, max_chunks=2)
        assert not first.done and len(first.chunks) == 2
        windows_before = {
            (c["start"], c["end"]) for c in analytics.calls["get_product_performance"]
        }

        second = await _history(session, shop, analytics, max_chunks=1)
        assert len(second.chunks) == 1
        assert second.chunks[0][1] == first.chunks[-1][0], "resumes at the earliest date reached"
        new_windows = [
            (c["start"], c["end"])
            for c in analytics.calls["get_product_performance"]
            if (c["start"], c["end"]) not in windows_before
        ]
        assert new_windows and all(
            (start, end) == (second.chunks[0][0].isoformat(), second.chunks[0][1].isoformat())
            for start, end in new_windows
        )
        assert len(analytics.calls["get_product_performance"]) == len(analytics.products) * (
            1 + 2 + 1
        )

    @pytest.mark.asyncio
    async def test_an_out_of_range_refusal_ends_the_walk(self, session):
        shop = await _make_shop(session, label="oor")
        analytics = FakeAnalyticsResource(prefix="oor", earliest_data=date(2025, 1, 1))
        await _fast(session, shop, analytics, score_fn=_count_score)
        analytics.out_of_range_before = LATEST - timedelta(days=60)

        result = await _history(session, shop, analytics, max_chunks=10)
        assert result.done and result.reason == "out_of_range"
        state = await _state(session, shop.id)
        # The refused window is narrowed until it fits, so the walk ends AT
        # TikTok's limit, not up to a chunk short of it.
        assert state.history_earliest_date == LATEST - timedelta(days=60)
        assert state.history_done_at is not None
        days = await _product_days(session, shop.id)
        assert min(days) == LATEST - timedelta(days=60)

    @pytest.mark.asyncio
    async def test_a_rate_limited_chunk_is_not_recorded(self, session):
        shop = await _make_shop(session, label="rl")
        analytics = FakeAnalyticsResource(prefix="rl")
        await _fast(session, shop, analytics, score_fn=_count_score)
        before = (await _state(session, shop.id)).history_earliest_date

        from juli_backend.integrations.tiktok import ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH

        limiter = FakeRateLimiter()
        limiter.refuse.add(ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH)
        result = await _history(session, shop, analytics, rate_limiter=limiter, max_chunks=3)
        assert not result.done and result.reason == "incomplete_chunk"
        state = await _state(session, shop.id)
        assert state.history_earliest_date == before
        assert state.history_chunks_done == 0

    @pytest.mark.asyncio
    async def test_waits_for_the_fast_phase(self, session):
        shop = await _make_shop(session, label="early")
        result = await _history(session, shop, FakeAnalyticsResource(prefix="early"))
        assert result.reason == "fast_not_done" and not result.done

    @pytest.mark.asyncio
    async def test_the_bootstrap_task_enqueues_history_on_the_low_priority_path(self):
        from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_bootstrap_task

        history_calls: list[tuple] = []
        lock = InMemoryShopIngestLock()
        shop_x = str(uuid.uuid4())

        @asynccontextmanager
        async def factory():
            yield _NullSession()

        async def collaborators(_session):
            return {}

        async def fast_fn(**kwargs):
            return SimpleNamespace(skipped=False, reason=None)

        enqueuers = Enqueuers(
            bootstrap=lambda *a, **k: "b",
            history=lambda shop_id, *, marker_token, countdown=0: (
                history_calls.append((shop_id, marker_token, countdown)) or "h"
            ),
            poll=lambda shop_id: "p",
        )
        await run_bootstrap_task(
            shop_x,
            session_factory=factory,
            lock=lock,
            collaborators=collaborators,
            enqueuers=enqueuers,
            fast_fn=fast_fn,
        )
        assert len(history_calls) == 1 and history_calls[0][0] == shop_x
        # A second completion while one is queued does not stack another.
        await run_bootstrap_task(
            shop_x,
            session_factory=factory,
            lock=lock,
            collaborators=collaborators,
            enqueuers=enqueuers,
            fast_fn=fast_fn,
        )
        assert len(history_calls) == 1
        assert not lock.is_held(shop_x, "cycle")


class _NullSession:
    async def commit(self):
        return None


# ---------------------------------------------------------------------------
# AC-1.5 -- fan-out with >= 2 shops, bootstrap routing, per-shop mutex
# ---------------------------------------------------------------------------


class _RecordingEnqueuers:
    def __init__(self):
        self.polls: list[str] = []
        self.bootstraps: list[str] = []
        self.histories: list[str] = []

    def as_enqueuers(self):
        from juli_backend.workers.tasks.shop_ingestion import Enqueuers

        return Enqueuers(
            bootstrap=lambda shop_id, **k: self.bootstraps.append(shop_id) or "b",
            history=lambda shop_id, **k: self.histories.append(shop_id) or "h",
            poll=lambda shop_id: self.polls.append(shop_id) or "p",
        )


class TestFanout:
    @pytest_asyncio.fixture
    async def fleet(self, session):
        seller = await _make_shop(
            session, label="seller", capability=TikTokCapability.SELLER_CONNECT
        )
        merchant = await _make_shop(
            session, label="merchant", capability=TikTokCapability.PRODUCTION_READ
        )
        fresh = await _make_shop(session, label="fresh", capability=TikTokCapability.SELLER_CONNECT)
        sandbox = await _make_shop(
            session, label="sandbox", capability=TikTokCapability.SANDBOX_WRITE
        )
        reauth = await _make_shop(session, label="reauth", status="needs_reauth")
        inactive = await _make_shop(session, label="inactive", is_active=False)
        bare = await _make_shop(session, label="bare", with_credential=False)
        repo = ShopIngestionStateRepo(session)
        for shop in (seller, merchant):
            await repo.stamp_once(shop.id, "fast_done_at", status=BOOTSTRAP_FAST_DONE)
        await session.commit()
        return SimpleNamespace(
            seller=seller,
            merchant=merchant,
            fresh=fresh,
            excluded={sandbox.id, reauth.id, inactive.id, bare.id},
        )

    @pytest.mark.asyncio
    async def test_enumerates_production_and_seller_connect_shops_only(self, session, fleet):
        shops = await enumerate_pollable_shops(session)
        by_id = {shop.shop_id: shop.fast_done for shop in shops}
        assert by_id == {fleet.seller.id: True, fleet.merchant.id: True, fleet.fresh.id: False}
        assert not (set(by_id) & fleet.excluded)

    @pytest.mark.asyncio
    async def test_one_task_per_shop_and_bootstrap_for_shops_without_a_fast_phase(
        self, session, fleet
    ):
        from juli_backend.workers.tasks.shop_ingestion import run_fanout

        recorder = _RecordingEnqueuers()
        summary = await run_fanout(
            session, lock=InMemoryShopIngestLock(), enqueuers=recorder.as_enqueuers()
        )
        assert sorted(recorder.polls) == sorted([str(fleet.seller.id), str(fleet.merchant.id)])
        assert recorder.bootstraps == [str(fleet.fresh.id)]
        assert summary.shops == 3 and summary.cycles == 2 and summary.bootstraps == 1

    @pytest.mark.asyncio
    async def test_a_held_shop_lock_skips_that_shop_only(self, session, fleet):
        from juli_backend.workers.tasks.shop_ingestion import run_fanout

        lock = InMemoryShopIngestLock()
        assert lock.try_acquire(str(fleet.seller.id), "cycle", ttl_seconds=600)
        recorder = _RecordingEnqueuers()
        summary = await run_fanout(session, lock=lock, enqueuers=recorder.as_enqueuers())
        assert str(fleet.seller.id) not in recorder.polls
        assert str(fleet.merchant.id) in recorder.polls
        assert summary.skipped_locked == 1

    @pytest.mark.asyncio
    async def test_a_queued_bootstrap_is_not_enqueued_twice(self, session, fleet):
        from juli_backend.workers.tasks.shop_ingestion import run_fanout

        lock = InMemoryShopIngestLock()
        recorder = _RecordingEnqueuers()
        await run_fanout(session, lock=lock, enqueuers=recorder.as_enqueuers())
        summary = await run_fanout(session, lock=lock, enqueuers=recorder.as_enqueuers())
        assert recorder.bootstraps == [str(fleet.fresh.id)]
        assert summary.deduplicated == 1

    @pytest.mark.asyncio
    async def test_two_cycles_for_one_shop_never_overlap(self):
        from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_poll_shop_task

        lock = InMemoryShopIngestLock()
        shop_1 = str(uuid.uuid4())
        release = asyncio.Event()
        running = 0
        peak = 0
        ran = 0

        @asynccontextmanager
        async def factory():
            yield _NullSession()

        async def collaborators(_session):
            return {}

        async def cycle_fn(**_kwargs):
            nonlocal running, peak, ran
            running += 1
            ran += 1
            peak = max(peak, running)
            await release.wait()
            running -= 1
            return SimpleNamespace(needs_bootstrap=False, history_done=True)

        async def run():
            return await run_poll_shop_task(
                shop_1,
                session_factory=factory,
                lock=lock,
                collaborators=collaborators,
                enqueuers=Enqueuers(),
                cycle_fn=cycle_fn,
            )

        first = asyncio.create_task(run())
        await asyncio.sleep(0)
        second = await run()  # the lock is held: skipped, not queued behind
        assert second is None
        release.set()
        await first
        assert ran == 1 and peak == 1
        assert not lock.is_held(shop_1, "cycle"), "released after the cycle"

    @pytest.mark.asyncio
    async def test_a_cycle_for_a_shop_without_a_fast_phase_enqueues_bootstrap(self, session):
        from juli_backend.workers.tasks.shop_ingestion import run_poll_shop_task

        shop = await _make_shop(session, label="needsboot")
        recorder = _RecordingEnqueuers()

        @asynccontextmanager
        async def factory():
            yield session

        async def collaborators(_session):
            return {
                "config": CONFIG,
                "rate_limiter": FakeRateLimiter(),
                "handoff_fn": Handoffs(session),
            }

        analytics = FakeAnalyticsResource(prefix="nb")
        result = await run_poll_shop_task(
            str(shop.id),
            session_factory=factory,
            lock=InMemoryShopIngestLock(),
            collaborators=collaborators,
            enqueuers=recorder.as_enqueuers(),
            run_kwargs={"create_resources": lambda _cfg: make_resources(analytics), "now": NOW},
        )
        assert result.needs_bootstrap
        assert recorder.bootstraps == [str(shop.id)]
        assert analytics.calls == {}, "no vendor call for a shop that still needs bootstrap"

    def test_the_fanout_replaces_the_single_merchant_beat_entry(self):
        from juli_backend.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "fujiwa-poll-cycle" not in schedule
        assert schedule["shop-poll-fanout"]["task"] == "juli_backend.shop_poll_fanout"


# ---------------------------------------------------------------------------
# AC-1.6 -- commerce every cycle, analytics at most once a day
# ---------------------------------------------------------------------------


async def _cycle(session, shop, analytics, *, now, score_fn=None, resources=None):
    return await run_shop_cycle(
        session=session,
        config=CONFIG,
        shop_id=shop.id,
        rate_limiter=FakeRateLimiter(),
        handoff_fn=Handoffs(session),
        create_resources=lambda _cfg: resources or make_resources(analytics),
        sleep=_no_sleep,
        now=now,
        score_fn=score_fn or _count_score,
    )


class TestCadence:
    @pytest.mark.asyncio
    async def test_analytics_runs_at_most_once_a_day_and_only_for_new_days(self, session):
        shop = await _make_shop(session, label="cad")
        analytics = FakeAnalyticsResource(prefix="cad")
        await _fast(session, shop, analytics, score_fn=_count_score)
        baseline_detail = analytics.detail_calls()
        baseline_probe = len(analytics.calls["get_shop_performance"])

        # Same day as the fast phase: commerce runs, analytics does not.
        resources = make_resources(analytics)
        same_day = await _cycle(session, shop, analytics, now=NOW, resources=resources)
        assert same_day.analytics_skip_reason == "already_ran_today"
        assert analytics.detail_calls() == baseline_detail
        assert len(analytics.calls["get_shop_performance"]) == baseline_probe
        resources.orders.search_all.assert_called_once()
        resources.inventory.search.assert_not_called()  # no products synced yet

        # Next day, TikTok has published nothing new: one probe, ZERO detail calls.
        tomorrow = NOW + timedelta(days=1)
        nothing_new = await _cycle(session, shop, analytics, now=tomorrow)
        assert nothing_new.analytics_skip_reason == "nothing_new"
        assert analytics.detail_calls() == baseline_detail
        assert len(analytics.calls["get_shop_performance"]) == baseline_probe + 1
        # ...and the gate stays open: the next cycle probes again.
        assert (await _state(session, shop.id)).analytics_last_run_on == TODAY

        # TikTok publishes two days: every missing day is fetched, in ONE range.
        analytics.latest = LATEST + timedelta(days=2)
        scored: list[uuid.UUID] = []

        async def score(session, shop_id):
            scored.append(shop_id)
            return []

        fetched = await _cycle(session, shop, analytics, now=tomorrow, score_fn=score)
        assert fetched.analytics_ran and fetched.analytics is not None
        new_calls = analytics.calls["get_product_performance"][-len(analytics.products) :]
        assert {(c["start"], c["end"]) for c in new_calls} == {
            (
                (LATEST + timedelta(days=1)).isoformat(),
                (LATEST + timedelta(days=3)).isoformat(),
            )
        }
        assert analytics.detail_calls() == baseline_detail + len(analytics.products) + len(
            analytics.skus
        )
        days = await _product_days(session, shop.id)
        assert {LATEST + timedelta(days=1), LATEST + timedelta(days=2)} <= days
        state = await _state(session, shop.id)
        assert state.analytics_through_date == LATEST + timedelta(days=2)
        assert state.analytics_last_run_on == TODAY + timedelta(days=1)
        assert scored == [shop.id], "D11: scoring re-runs after a day's analytics pass"

        # Same day again: nothing at all.
        detail = analytics.detail_calls()
        again = await _cycle(session, shop, analytics, now=tomorrow + timedelta(hours=3))
        assert again.analytics_skip_reason == "already_ran_today"
        assert analytics.detail_calls() == detail

    @pytest.mark.asyncio
    async def test_commerce_stays_incremental_every_cycle(self, session):
        shop = await _make_shop(session, label="inc")
        analytics = FakeAnalyticsResource(prefix="inc")
        await _fast(
            session,
            shop,
            analytics,
            score_fn=_count_score,
            orders=[{"id": "o-1", "update_time": 1_784_000_000}],
        )
        resources = make_resources(analytics)
        await _cycle(session, shop, analytics, now=NOW, resources=resources)
        assert resources.orders.search_all.call_args_list == [
            call(update_time_from=1_784_000_000)
        ], "the watermark from the fast phase drives the next read"


# ---------------------------------------------------------------------------
# AC-1.12 -- shop isolation with two shops
# ---------------------------------------------------------------------------


_active_scope: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "test_active_scope", default=None
)


class TestShopIsolation:
    @pytest.fixture
    def scope_spy(self, monkeypatch):
        entered: list[uuid.UUID] = []
        real = ingestion_module.with_sticky_shop_scope

        @asynccontextmanager
        async def spy(session, shop_id):
            entered.append(shop_id)
            token = _active_scope.set(shop_id)
            try:
                async with real(session, shop_id):
                    yield
            finally:
                _active_scope.reset(token)

        monkeypatch.setattr(ingestion_module, "with_sticky_shop_scope", spy)
        return entered

    @pytest.mark.asyncio
    async def test_two_shops_never_write_into_each_other(self, session, scope_spy):
        shop_a = await _make_shop(session, label="iso-a")
        shop_b = await _make_shop(session, label="iso-b")
        fakes = {
            shop_a.id: FakeAnalyticsResource(prefix="A", gmv="1111.00"),
            shop_b.id: FakeAnalyticsResource(prefix="B", gmv="2222.00"),
        }
        keys = {shop_a.id: shop_a.tiktok_shop_id, shop_b.id: shop_b.tiktok_shop_id}
        writes: list[tuple[uuid.UUID | None, str]] = []

        for shop in (shop_a, shop_b):
            handoff = Handoffs(session)

            async def recording(channel, shop_key, payload, inner=handoff):
                writes.append((_active_scope.get(), shop_key))
                await inner(channel, shop_key, payload)

            await run_bootstrap_fast_phase(
                session=session,
                config=CONFIG,
                shop_id=shop.id,
                rate_limiter=FakeRateLimiter(),
                handoff_fn=recording,
                create_resources=lambda _cfg, s=shop: make_resources(fakes[s.id]),
                sleep=_no_sleep,
                now=NOW,
                score_fn=_count_score,
            )

        assert scope_spy == [shop_a.id, shop_b.id]
        # Every write happened under the scope of the shop it belongs to.
        assert writes and all(keys[scope] == shop_key for scope, shop_key in writes)

        for shop, prefix, gmv in ((shop_a, "A", "1111.00"), (shop_b, "B", "2222.00")):
            rows = (
                await session.execute(
                    select(AnalyticsPerformanceInterval).where(
                        AnalyticsPerformanceInterval.shop_id == shop.id,
                        AnalyticsPerformanceInterval.grain == "product",
                    )
                )
            ).scalars()
            rows = list(rows)
            assert rows
            assert {row.tiktok_product_id.split("-")[0] for row in rows} == {prefix}
            assert {row.gmv for row in rows} == {Decimal(gmv)}
            state = await _state(session, shop.id)
            assert state.fast_done_at is not None

    @pytest.mark.asyncio
    async def test_another_shops_credential_is_refused_before_any_scope(self, session, scope_spy):
        from juli_backend.core.security.credential_resolver import (
            resolve_read_credential_for_shop,
        )

        shop_a = await _make_shop(session, label="own-a")
        shop_b = await _make_shop(session, label="own-b")

        async def wrong_shop(session, shop_id):
            return await resolve_read_credential_for_shop(session, shop_b.id)

        analytics = FakeAnalyticsResource(prefix="X")
        with pytest.raises(ValueError, match="owned by the shop being polled"):
            await run_shop_cycle(
                session=session,
                config=CONFIG,
                shop_id=shop_a.id,
                rate_limiter=FakeRateLimiter(),
                handoff_fn=Handoffs(session),
                resolve_credential=wrong_shop,
                create_resources=lambda _cfg: make_resources(analytics),
                sleep=_no_sleep,
                now=NOW,
            )
        assert scope_spy == [], "no shop authority was granted"
        assert analytics.calls == {}

    @pytest.mark.asyncio
    async def test_a_shop_without_a_read_credential_is_not_polled(self, session, scope_spy):
        from juli_backend.core.security.credential_resolver import NoReadCredentialForShop

        shop = await _make_shop(session, label="nocred", with_credential=False)
        with pytest.raises(NoReadCredentialForShop):
            await run_shop_cycle(
                session=session,
                config=CONFIG,
                shop_id=shop.id,
                rate_limiter=FakeRateLimiter(),
                handoff_fn=Handoffs(session),
                create_resources=lambda _cfg: make_resources(FakeAnalyticsResource()),
                sleep=_no_sleep,
                now=NOW,
            )
        assert scope_spy == []


# ---------------------------------------------------------------------------
# AC-1.4 -- the migration creates what the model declares
# ---------------------------------------------------------------------------


def test_the_migration_creates_every_model_column_and_chains_onto_073():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/src/juli_backend/database/migrations/versions/074_shop_ingestion_state.py"
    )
    text = path.read_text(encoding="utf-8")
    assert 'revision: str = "074_shop_ingestion_state"' in text
    assert len("074_shop_ingestion_state") <= 32
    assert 'down_revision: str | None = "073_waiting_external"' in text
    # P17 adds the quick-scan columns in 084_onboarding_speed.
    p17 = path.with_name("084_onboarding_speed.py").read_text(encoding="utf-8")
    for column in ShopIngestionState.__table__.columns.keys():
        assert f'"{column}"' in text or f'"{column}"' in p17, column
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text
    assert "SECURITY DEFINER" in text
    assert "REVOKE ALL ON FUNCTION" in text


# ---------------------------------------------------------------------------
# P14-C -- the scheduled cycle reads a few orders' cost data after commerce
# ---------------------------------------------------------------------------


class TestOrderCostsInTheCycle:
    @pytest.mark.asyncio
    async def test_the_cycle_reads_cost_data_and_a_vendor_failure_never_fails_it(self, session):
        from juli_backend.integrations.tiktok import TikTokAPIError
        from juli_backend.models.order_costs import OrderCostFetch, OrderPriceDetail

        shop = await _make_shop(session, label="cost")
        analytics = FakeAnalyticsResource(prefix="cost")
        await _fast(session, shop, analytics)
        created = NOW.replace(tzinfo=None) - timedelta(days=2)
        session.add(
            Order(
                shop_id=shop.id,
                tiktok_order_id="5793990727963214852",
                status="DELIVERED",
                total_amount=Decimal(100000),
                currency="VND",
                tiktok_created_at=created,
                update_time=created,
            )
        )
        await session.commit()

        calls: list[str] = []

        class Costs:
            def get_price_detail(self, order_id):
                calls.append(f"price:{order_id}")
                return {"currency": "VND", "subtotal_deduction_seller": "5000", "line_items": []}

            def get_statement_transactions(self, order_id):
                calls.append(f"finance:{order_id}")
                raise TikTokAPIError(36009003, "internal")

        resources = make_resources(analytics)
        resources.order_costs = Costs()
        resources.orders.get_details.return_value = {"orders": []}
        result = await _cycle(session, shop, analytics, now=NOW, resources=resources)

        assert calls == ["price:5793990727963214852", "finance:5793990727963214852"]
        assert result.order_costs is not None
        assert (result.order_costs.price.fetched, result.order_costs.finance.errors) == (1, 1)
        stored = (
            await session.execute(
                select(OrderPriceDetail).where(OrderPriceDetail.shop_id == shop.id)
            )
        ).scalar_one()
        assert stored.seller_funded_amount == Decimal(5000)
        fetch = (
            await session.execute(select(OrderCostFetch).where(OrderCostFetch.shop_id == shop.id))
        ).scalar_one()
        assert fetch.finance_attempts == 1 and fetch.price_fetched_at is not None

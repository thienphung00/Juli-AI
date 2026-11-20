"""P101 W2 t1: raw -> canonical is wired into every path that lands TikTok orders.

- the poll steps (``polling.sync.sync_orders`` / ``sync_returns``) hand what they fetched to the
  job's ``TikTokCanonicalSync``; ``_run_poll_step`` passes it to those two steps only;
- the webhook's targeted fetch (``cdp_speed.targeted_fetch_sync``) does the same;
- B-1: a shop's first order read is bounded to the 90-day connect window by ``create_time`` and
  connecting a shop (the bootstrap fast phase) lands those 90 days in ``order_lines``;
- the order re-fetch by id takes at most 50 ids a call and a rate-limiter token per call;
- the nightly reconcile beat is scheduled and walks every pollable shop.

Synthetic payloads only."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok.constants import ORDER_DETAIL_PATH
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.cdp_speed import targeted_fetch_sync
from juli_backend.services.ingest import tiktok_canonical as tc
from juli_backend.services.ingest.canonical import day_of
from juli_backend.workers.services.polling import orchestrate
from juli_backend.workers.services.polling.sync import sync_orders, sync_returns

NOW = datetime(2026, 11, 19, 18, 30, tzinfo=UTC)  # 01:30 on 20/11 in Vietnam


class _Limiter:
    def __init__(self, allow: int = 10_000) -> None:
        self.allow = allow
        self.calls: list[str] = []

    def acquire(self, app_id, shop_id, path, *, max_requests, window_seconds) -> bool:
        self.calls.append(path)
        self.allow -= 1
        return self.allow >= 0


class _Canonical:
    def __init__(self) -> None:
        self.orders: list[list[dict]] = []
        self.returns: list[list[dict]] = []

    async def on_orders(self, orders):
        self.orders.append(list(orders))

    async def on_returns(self, returns):
        self.returns.append(list(returns))


class _Orders:
    def __init__(self, orders: list[dict]) -> None:
        self._orders = orders
        self.kwargs: list[dict[str, Any]] = []

    def search_all(self, **kwargs: Any) -> list[dict]:
        self.kwargs.append(kwargs)
        since = kwargs.get("create_time_from")
        return [o for o in self._orders if since is None or o["create_time"] >= since]


class _Returns:
    def __init__(self, returns: list[dict]) -> None:
        self._returns = returns

    def search_returns_all(self, **_: Any) -> list[dict]:
        return list(self._returns)


async def _handoff(channel: str, shop_key: str, payload: bytes) -> None:
    return None


def _order(order_id: str, created: int) -> dict[str, Any]:
    return {
        "id": order_id,
        "status": "COMPLETED",
        "create_time": created,
        "update_time": created + 60,
        "paid_time": created + 30,
        "payment": {"currency": "VND"},
        "line_items": [
            {
                "id": f"{order_id}1",
                "product_id": "p1",
                "sku_id": "s1",
                "original_price": "100000",
                "sale_price": "100000",
                "seller_discount": "0",
                "platform_discount": "0",
                "currency": "VND",
            }
        ],
    }


async def test_the_poll_order_step_hands_its_orders_to_the_canonical_sync() -> None:
    canonical = _Canonical()
    resource = _Orders([_order("1", 1_790_000_000)])
    state: dict[str, Any] = {"orders_last_update_time": 1_789_000_000}

    outcome = await sync_orders(
        resource=resource,
        rate_limiter=_Limiter(),
        handoff_fn=_handoff,
        app_id="app",
        shop_id="tt-shop",
        sync_state=state,
        canonical=canonical,
    )

    assert [o["id"] for o in canonical.orders[0]] == ["1"]
    assert resource.kwargs == [{"update_time_from": 1_789_000_000}]
    assert outcome.persisted == 2 and state["orders_last_update_time"] == 1_790_000_060


async def test_the_first_order_read_is_bounded_to_the_connect_window(monkeypatch) -> None:
    monkeypatch.delenv("SHOP_HISTORY_CONNECT_DAYS", raising=False)
    resource = _Orders([])

    await sync_orders(
        resource=resource,
        rate_limiter=_Limiter(),
        handoff_fn=_handoff,
        app_id="app",
        shop_id="tt-shop",
        sync_state={},
        now=NOW,
    )

    (kwargs,) = resource.kwargs
    start = datetime.fromtimestamp(kwargs["create_time_from"], tz=UTC)
    assert kwargs["update_time_from"] is None
    assert day_of(start) == date(2026, 8, 23)  # 90 VN days ending 20/11
    assert start == datetime(2026, 8, 22, 17, 0, tzinfo=UTC)  # 00:00 VN


async def test_the_poll_return_step_hands_its_returns_to_the_canonical_sync() -> None:
    canonical = _Canonical()
    returns = [{"return_id": "r1", "order_id": "1", "return_status": "BUYER_SHIPPED_ITEM"}]

    await sync_returns(
        resource=_Returns(returns),
        rate_limiter=_Limiter(),
        handoff_fn=_handoff,
        app_id="app",
        shop_id="tt-shop",
        sync_state={},
        canonical=canonical,
    )

    assert [r["return_id"] for r in canonical.returns[0]] == ["r1"]


async def test_run_poll_step_gives_the_canonical_sync_to_orders_and_returns_only() -> None:
    seen: dict[str, Any] = {}

    def recorder(name: str):
        async def fn(**kwargs):
            seen[name] = kwargs.get("canonical", "absent")
            return SimpleNamespace()

        return fn

    canonical = _Canonical()
    resources = SimpleNamespace(orders=1, products=2, returns=3)
    for path, attr, wants in (
        ("/o", "orders", True),
        ("/p", "products", False),
        ("/r", "returns", True),
    ):
        step = orchestrate._PollStep(path, attr, recorder(attr), wants_canonical=wants)
        await orchestrate._run_poll_step(
            step,
            resources=resources,
            rate_limiter=SimpleNamespace(is_exhausted=lambda *a, **k: False),
            handoff_fn=_handoff,
            app_id="app",
            shop_key="tt",
            sync_state={},
            sleep=lambda _s: None,
            deadline=orchestrate._CycleDeadline(budget_seconds=60),
            canonical=canonical,
        )

    assert seen == {"orders": canonical, "products": "absent", "returns": canonical}
    flags = {s.resource_attr: s.wants_canonical for s in orchestrate._FUJIWA_POLL_STEPS}
    assert flags == {"orders": True, "products": False, "returns": True, "inventory": False}


async def test_the_webhook_targeted_fetch_maps_orders_and_returns_in_the_same_job() -> None:
    canonical = _Canonical()
    state: dict[str, Any] = {"orders_last_update_time": 5}

    await targeted_fetch_sync.sync_orders(
        resource=_Orders([_order("1", 1_790_000_000)]),
        rate_limiter=_Limiter(),
        handoff_fn=_handoff,
        app_id="app",
        shop_key="tt",
        sync_state=state,
        correlation_id="c",
        canonical=canonical,
    )
    await targeted_fetch_sync.sync_returns(
        resource=_Returns([{"return_id": "r1", "order_id": "1", "return_status": "X"}]),
        rate_limiter=_Limiter(),
        handoff_fn=_handoff,
        app_id="app",
        shop_key="tt",
        sync_state={},
        correlation_id="c",
        canonical=canonical,
    )

    assert [o["id"] for o in canonical.orders[0]] == ["1"]
    assert [r["return_id"] for r in canonical.returns[0]] == ["r1"]


def test_the_order_refetch_takes_fifty_ids_and_one_token_per_call() -> None:
    calls: list[list[str]] = []

    class Detail:
        def get_details(self, ids: list[str]) -> dict:
            calls.append(ids)
            return {"orders": [{"id": i} for i in ids]}

    limiter = _Limiter()
    fetch = tc.order_details_fetcher(Detail(), rate_limiter=limiter, app_id="a", shop_id="s")

    orders = fetch([str(n) for n in range(120)])

    assert [len(c) for c in calls] == [50, 50, 20]
    assert len(orders) == 120 and limiter.calls == [ORDER_DETAIL_PATH] * 3

    empty = tc.order_details_fetcher(Detail(), rate_limiter=_Limiter(0), app_id="a", shop_id="s")
    with pytest.raises(tc.OrderRefetchRateLimitedError) as excinfo:
        empty(["1"])
    assert str(excinfo.value) == ORDER_DETAIL_PATH


def test_the_nightly_reconcile_beat_is_scheduled() -> None:
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["tiktok-canonical-reconcile"]
    assert entry["task"] == "juli_backend.tiktok_canonical_reconcile"
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({21}, {39})


async def test_the_reconcile_fanout_walks_every_shop_in_its_own_scope(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from juli_backend.database import tenant_context
    from juli_backend.workers.tasks.shop_ingestion import run_canonical_reconcile_fanout

    shops = [SimpleNamespace(shop_id=uuid.uuid4()), SimpleNamespace(shop_id=uuid.uuid4())]
    scopes: list[uuid.UUID] = []
    calls: list[tuple[uuid.UUID, date, date]] = []

    @asynccontextmanager
    async def scope(_session, shop_id):
        scopes.append(shop_id)
        yield

    monkeypatch.setattr(tenant_context, "with_sticky_shop_scope", scope)

    class _Session:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    @asynccontextmanager
    async def factory():
        yield _Session()

    async def enumerate_fn(_session):
        return shops

    async def reconcile(_session, shop_id, *, start, end, queue):
        calls.append((shop_id, start, end))
        if shop_id == shops[0].shop_id:
            raise RuntimeError("one shop fails")

    done = await run_canonical_reconcile_fanout(
        factory,
        queue=tc.InMemoryRefetchQueue(),
        enumerate_fn=enumerate_fn,
        reconcile_fn=reconcile,
        now=NOW,
    )

    assert done == 1 and scopes == [s.shop_id for s in shops]
    assert {(start, end) for _, start, end in calls} == {(date(2026, 8, 23), date(2026, 11, 20))}


# -- B-1 on connect -------------------------------------------------------------------------


async def test_connecting_a_shop_lands_the_last_90_days_of_orders_in_order_lines(
    session, monkeypatch
) -> None:
    from tests.support.shop_ingestion_fakes import FakeAnalyticsResource, make_resources
    from tests.unit.test_shop_ingestion import _fast, _make_shop

    monkeypatch.delenv("SHOP_HISTORY_CONNECT_DAYS", raising=False)
    monkeypatch.delenv(tc.ENABLED_ENV, raising=False)
    shop = await _make_shop(session, label="b1")
    now = datetime.now(UTC)
    # one order a day at 12:00 VN, for the last 120 VN days (today included)
    today = (now + timedelta(hours=7)).date()
    orders = []
    for back in range(120):
        day = today - timedelta(days=back)
        noon_vn = datetime(day.year, day.month, day.day, 5, 0, tzinfo=UTC)
        orders.append(_order(f"9{back:017d}", int(noon_vn.timestamp())))
    search = _Orders(orders)
    resources = make_resources(FakeAnalyticsResource(prefix="b1"))
    resources.orders = search
    monkeypatch.setattr(
        "tests.support.shop_ingestion_fakes.make_resources", lambda *_a, **_k: resources
    )
    monkeypatch.setattr(
        "tests.unit.test_shop_ingestion.make_resources", lambda *_a, **_k: resources
    )

    await _fast(session, shop, FakeAnalyticsResource(prefix="b1"))

    rows = (
        await session.execute(
            select(ShopeeOrderLine.order_ref, ShopeeOrderLine.day).where(
                ShopeeOrderLine.shop_id == shop.id, ShopeeOrderLine.platform == "tiktok"
            )
        )
    ).all()
    days = sorted({day for _, day in rows})
    assert len(rows) == 90 and len(days) == 90
    assert (days[0], days[-1]) == (today - timedelta(days=89), today)
    assert search.kwargs[0]["update_time_from"] is None and "create_time_from" in search.kwargs[0]

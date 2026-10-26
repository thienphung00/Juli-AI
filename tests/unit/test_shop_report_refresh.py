"""B12 (P68): an order change after the stored report's date rebuilds that report once."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pytest

from juli_backend.models.models import Shop, User
from juli_backend.repositories import ShopDiagnosisReportsRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.shop_diagnosis_daily.refresh import (
    clear_report_cache,
    maybe_refresh_stored_report,
)

pytestmark = pytest.mark.asyncio

END = date(2026, 10, 6)
BUILT = datetime(2026, 10, 7, 0, 15)
# 2026-10-05 10:00 UTC = 17:00 local, inside the window; 10-07 10:00 UTC is after END.
INSIDE = datetime(2026, 10, 5, 10, 0)
AFTER = datetime(2026, 10, 7, 10, 0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_report_cache()


async def _shop(session, tt_id: str, *, source: str | None = "orders") -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=tt_id, tiktok_shop_id=tt_id)
    session.add_all([user, shop])
    await session.flush()
    report = {"gmv": 904000} | ({"metrics_source": source} if source else {})
    await ShopDiagnosisReportsRepo(session).save(
        shop.id, end_date=END, ranking="60d", report=report, built_at=BUILT
    )
    await session.commit()
    return shop


class _Spy:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.claimed: set[str] = set()

    def claim(self, shop_id: str) -> bool:
        if shop_id in self.claimed:
            return False
        self.claimed.add(shop_id)
        return True

    def enqueue(self, shop_id: str) -> None:
        self.enqueued.append(shop_id)


async def _change(session, shop, spy, *, status="cancelled", created_at=INSIDE) -> bool:
    return await maybe_refresh_stored_report(
        session, shop.id, status=status, created_at=created_at, claim=spy.claim, enqueue=spy.enqueue
    )


async def test_cancellation_after_report_date_triggers_exactly_one_rebuild(session):
    shop = await _shop(session, "tt-a")
    spy = _Spy()
    assert await _change(session, shop, spy) is True
    # A batch of further changes in the debounce window adds nothing.
    assert await _change(session, shop, spy, status="returned") is False
    assert await _change(session, shop, spy, status="confirmed") is False
    assert spy.enqueued == [str(shop.id)]


async def test_unrelated_shop_is_untouched(session):
    a = await _shop(session, "tt-a")
    b = await _shop(session, "tt-b")
    spy = _Spy()
    await _change(session, a, spy)
    assert spy.enqueued == [str(a.id)]
    assert str(b.id) not in spy.claimed
    await _change(session, b, spy)
    assert spy.enqueued == [str(a.id), str(b.id)]


async def test_change_after_report_window_does_not_trigger(session):
    shop = await _shop(session, "tt-a")
    spy = _Spy()
    assert await _change(session, shop, spy, created_at=AFTER) is False
    assert spy.enqueued == []


async def test_unpaid_status_and_analytics_report_do_not_trigger(session):
    shop = await _shop(session, "tt-a")
    other = await _shop(session, "tt-b", source="analytics")
    spy = _Spy()
    assert await _change(session, shop, spy, status="pending") is False
    assert await _change(session, other, spy) is False
    assert spy.enqueued == []


async def test_etl_consumer_hook_fires_on_cancelled_order(session):
    shop = await _shop(session, "tt-etl")
    calls: list[dict] = []

    async def hook(sess, shop_id, kwargs):
        calls.append({"shop_id": shop_id, **kwargs})

    async def dlq(topic, key, value):  # pragma: no cover
        raise AssertionError("unexpected DLQ")

    consumer = EtlConsumer(session=session, publish_dlq=dlq, after_order_change=hook)
    payload = {
        "order_id": "o-cancel",
        "status": "CANCELLED",
        "total_amount": "150000",
        "currency": "VND",
        "create_time": 1_759_658_400,
        "update_time": 1_759_900_000,
    }
    record = IngestRecord(
        channel="tiktok.orders.raw", shop_key="tt-etl", value=json.dumps(payload).encode()
    )
    assert await consumer.ingest(record) == ProcessOutcome.PROCESSED
    assert [(c["shop_id"], c["status"]) for c in calls] == [(shop.id, "cancelled")]


async def test_many_orders_inside_ttl_do_one_report_lookup(session, monkeypatch):
    shop = await _shop(session, "tt-a")
    calls = 0
    real = ShopDiagnosisReportsRepo.latest

    async def counting(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(ShopDiagnosisReportsRepo, "latest", counting)
    spy = _Spy()
    for _ in range(25):
        await _change(session, shop, spy)
    assert calls == 1
    assert spy.enqueued == [str(shop.id)]
    # A status that does not qualify never reaches the lookup at all.
    await _change(session, shop, spy, status="pending")
    assert calls == 1

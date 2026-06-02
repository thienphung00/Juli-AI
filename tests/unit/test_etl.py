"""Issue #32 — ETL ingest consumer + dedup + DLQ.

AC1 → test_etl_processes_event_within_latency_budget
AC2 → test_etl_deduplicates_by_event_id
AC3 → test_etl_routes_malformed_to_dlq
AC4 → test_etl_maintains_shop_ordering_under_load
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.shared.utils.data.models import ProcessedEvent, Shop, User
from src.shared.utils.data.repos import OrdersRepo
from src.modules.ordering.use_cases.etl.consumer import EtlConsumer, ProcessOutcome
from src.modules.ordering.use_cases.etl.record import IngestRecord

pytestmark = pytest.mark.asyncio

TIKTOK_SHOP_ID = "7000000000000001"


@pytest.fixture
def dlq_messages():
    return []


@pytest.fixture
def publish_dlq(dlq_messages):
    async def _publish(topic: str, key: str, value: bytes) -> None:
        dlq_messages.append(
            {"topic": topic, "key": key, "value": json.loads(value.decode())}
        )

    return _publish


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+84903333333")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="ETL Shop",
        tiktok_shop_id=TIKTOK_SHOP_ID,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


def _order_record(
    *,
    order_id: str = "o1",
    update_time: int = 1_700_000_100,
    event_id: str | None = None,
    received_at: float | None = None,
) -> IngestRecord:
    payload: dict = {
        "order_id": order_id,
        "status": "AWAITING_SHIPMENT",
        "total_amount": "150.00",
        "currency": "VND",
        "update_time": update_time,
    }
    if event_id:
        payload["event_id"] = event_id
    return IngestRecord(
        channel="tiktok.orders.raw",
        shop_key=TIKTOK_SHOP_ID,
        value=json.dumps(payload).encode(),
        received_at=received_at,
    )


async def test_make_etl_handoff_wires_producer_to_consumer(session, shop, publish_dlq):
    from src.modules.ordering.api.ingestion.handoff import make_etl_handoff

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    handoff = make_etl_handoff(consumer)
    payload = {
        "order_id": "handoff-o1",
        "status": "AWAITING_SHIPMENT",
        "total_amount": "99.00",
        "currency": "VND",
        "update_time": 1_700_000_300,
        "event_id": "evt-handoff-1",
    }
    await handoff("tiktok.orders.raw", TIKTOK_SHOP_ID, json.dumps(payload).encode())
    await session.commit()

    repo = OrdersRepo(session)
    orders = await repo.list(shop.id)
    assert len(orders) == 1
    assert orders[0].tiktok_order_id == "handoff-o1"


async def test_etl_processes_event_within_latency_budget(
    session, shop, publish_dlq, dlq_messages
):
    now = 1_000_000.0
    consumer = EtlConsumer(
        session=session,
        publish_dlq=publish_dlq,
        clock=lambda: now,
    )
    record = _order_record(received_at=now - 30.0)

    outcome = await consumer.ingest(record)

    assert outcome == ProcessOutcome.PROCESSED
    repo = OrdersRepo(session)
    orders = await repo.list(shop.id)
    assert len(orders) == 1
    assert orders[0].tiktok_order_id == "o1"
    assert orders[0].total_amount == Decimal("150.00")
    assert dlq_messages == []


async def test_etl_deduplicates_by_event_id(session, shop, publish_dlq):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    event_id = "evt-dup-1"
    first = _order_record(event_id=event_id, update_time=1_700_000_100)
    second = _order_record(
        event_id=event_id,
        order_id="o1",
        update_time=1_700_000_200,
    )

    assert await consumer.ingest(first) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(second) == ProcessOutcome.DUPLICATE

    repo = OrdersRepo(session)
    orders = await repo.list(shop.id)
    assert len(orders) == 1
    expected = datetime.fromtimestamp(1_700_000_100, tz=timezone.utc).replace(
        tzinfo=None
    )
    assert orders[0].update_time == expected

    result = await session.execute(select(ProcessedEvent))
    assert len(result.scalars().all()) == 1


async def test_etl_routes_malformed_to_dlq(session, shop, publish_dlq, dlq_messages):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    record = IngestRecord(
        channel="tiktok.orders.raw",
        shop_key=TIKTOK_SHOP_ID,
        value=b"not-json",
    )

    outcome = await consumer.ingest(record)

    assert outcome == ProcessOutcome.DLQ
    assert len(dlq_messages) == 1
    assert dlq_messages[0]["topic"] == "tiktok.events.dlq"
    assert "error" in dlq_messages[0]["value"]
    assert dlq_messages[0]["value"]["original_channel"] == "tiktok.orders.raw"

    repo = OrdersRepo(session)
    assert await repo.list(shop.id) == []


async def test_etl_maintains_shop_ordering_under_load(session, shop, publish_dlq):
    completion_order: list[str] = []

    async def before_persist(record: IngestRecord) -> None:
        payload = json.loads(record.value)
        if payload.get("order_id") == "slow":
            await asyncio.sleep(0.05)

    consumer = EtlConsumer(
        session=session,
        publish_dlq=publish_dlq,
        max_pending_per_shop=50,
        before_persist=before_persist,
    )

    async def ingest_labeled(order_id: str, update_time: int) -> None:
        record = _order_record(
            order_id=order_id,
            update_time=update_time,
            event_id=f"evt-{order_id}",
        )
        await consumer.ingest(record)
        completion_order.append(order_id)
        await session.commit()

    await asyncio.gather(
        ingest_labeled("slow", 1),
        ingest_labeled("fast-1", 2),
        ingest_labeled("fast-2", 3),
    )

    assert completion_order[0] == "slow"
    assert completion_order[1:] == ["fast-1", "fast-2"]

    repo = OrdersRepo(session)
    orders = {o.tiktok_order_id for o in await repo.list(shop.id, limit=10)}
    assert orders == {"slow", "fast-1", "fast-2"}

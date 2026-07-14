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

from juli_backend.models.models import ProcessedEvent, Shop, User
from juli_backend.repositories.repos import OrdersRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord

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
    from juli_backend.services.ingestion.handoff import make_etl_handoff

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


async def test_etl_persists_order_item_after_parent_order(session, shop, publish_dlq):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    order_payload = {
        "order_id": "ord-with-lines",
        "status": "AWAITING_SHIPMENT",
        "total_amount": "100.00",
        "currency": "VND",
        "update_time": 1_700_000_400,
        "event_id": "evt-order-lines-1",
    }
    line_payload = {
        "tiktok_order_id": "ord-with-lines",
        "product_id": "prod-1",
        "sku_id": "sku-1",
        "quantity": 1,
        "unit_price": "100.00",
        "line_total": "100.00",
        "update_time": 1_700_000_400,
        "event_id": "evt-line-1",
    }

    assert await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(order_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(
        IngestRecord(
            channel="tiktok.order_items.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(line_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    from juli_backend.models.models import OrderItem
    from sqlalchemy import select

    result = await session.execute(
        select(OrderItem).where(OrderItem.tiktok_sku_id == "sku-1")
    )
    item = result.scalar_one()
    assert item.tiktok_order_id == "ord-with-lines"
    assert item.line_total == Decimal("100.00")


async def test_etl_persists_return_record(session, shop, publish_dlq):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({
                "order_id": "ord-ret",
                "status": "DELIVERED",
                "total_amount": "50.00",
                "currency": "VND",
                "update_time": 1_700_000_500,
                "event_id": "evt-order-ret",
            }).encode(),
        )
    )
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    outcome = await consumer2.ingest(
        IngestRecord(
            channel="tiktok.returns.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({
                "return_id": "ret-100",
                "order_id": "ord-ret",
                "buyer_id": "buyer-x",
                "sku_id": "sku-ret",
                "refund_amount": "50.00",
                "return_type": "other",
                "return_condition": "unknown",
                "status": "approved",
                "update_time": 1_700_000_600,
                "event_id": "evt-ret-1",
            }).encode(),
        )
    )
    assert outcome == ProcessOutcome.PROCESSED
    await session.commit()

    from juli_backend.models.models import Return
    from sqlalchemy import select

    result = await session.execute(
        select(Return).where(Return.tiktok_return_id == "ret-100")
    )
    ret = result.scalar_one()
    assert ret.tiktok_order_id == "ord-ret"
    assert ret.refund_amount == Decimal("50.00")


async def test_etl_derives_item_swap_return_from_order_item_edge(
    session, shop, publish_dlq
):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({
                "order_id": "ord-swap",
                "status": "DELIVERED",
                "total_amount": "80.00",
                "currency": "VND",
                "update_time": 1_700_000_500,
                "event_id": "evt-order-swap",
            }).encode(),
        )
    )
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    await consumer2.ingest(
        IngestRecord(
            channel="tiktok.order_items.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({
                "tiktok_order_id": "ord-swap",
                "product_id": "prod-swap",
                "sku_id": "sku-ordered",
                "quantity": 1,
                "unit_price": "80.00",
                "update_time": 1_700_000_510,
                "event_id": "evt-order-swap-line",
            }).encode(),
        )
    )
    await session.commit()

    consumer3 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    outcome = await consumer3.ingest(
        IngestRecord(
            channel="tiktok.returns.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({
                "return_id": "ret-swap",
                "order_id": "ord-swap",
                "buyer_id": "buyer-x",
                "product_id": "prod-swap",
                "sku_id": "sku-returned",
                "refund_amount": "80.00",
                "return_condition": "unknown",
                "status": "approved",
                "update_time": 1_700_000_600,
                "event_id": "evt-ret-swap",
            }).encode(),
        )
    )
    assert outcome == ProcessOutcome.PROCESSED
    await session.commit()

    from juli_backend.models.models import Return

    result = await session.execute(select(Return).where(Return.tiktok_return_id == "ret-swap"))
    ret = result.scalar_one()
    assert ret.order_id is not None
    assert ret.return_type == "item_swap"


async def test_etl_accepts_official_tiktok_order_shape(session, shop, publish_dlq):
    """Versioned API returns id, user_id, payment.total_amount — not legacy handoff names."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    payload = {
        "id": "577000000000099",
        "user_id": "masked-buyer-1",
        "order_status": "AWAITING_SHIPMENT",
        "update_time": 1_700_000_500,
        "payment": {"total_amount": "250.00", "currency": "VND"},
        "event_id": "evt-official-1",
    }
    outcome = await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(payload).encode(),
        )
    )
    assert outcome == ProcessOutcome.PROCESSED
    orders = await OrdersRepo(session).list(shop.id)
    assert len(orders) == 1
    assert orders[0].tiktok_order_id == "577000000000099"
    assert orders[0].total_amount == Decimal("250.00")


async def test_etl_persists_canonical_product_and_repolls_idempotently(
    session, shop, publish_dlq
):
    from juli_backend.models.models import Product

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    first_payload = {
        "id": "prod-canonical-1",
        "title": "Canonical Widget",
        "category": "Household",
        "category_id": "cat-1",
        "skus": [
            {
                "price": {"sale_price": "199000.00", "currency": "VND"},
                "inventory": [{"quantity": 7}],
            }
        ],
        "audit": {"status": "ON_SALE"},
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_100,
    }
    updated_payload = {
        **first_payload,
        "title": "Canonical Widget Updated",
        "skus": [
            {
                "price": {"sale_price": "219000.00", "currency": "VND"},
                "inventory": [{"quantity": 5}],
            }
        ],
        "update_time": 1_700_000_200,
    }

    assert await consumer.ingest(
        IngestRecord(
            channel="tiktok.products.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(first_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(
        IngestRecord(
            channel="tiktok.products.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(updated_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    result = await session.execute(select(Product))
    products = result.scalars().all()
    assert len(products) == 1
    product = products[0]
    assert product.tiktok_product_id == "prod-canonical-1"
    assert product.title == "Canonical Widget Updated"
    assert product.category == "Household"
    assert product.category_id == "cat-1"
    assert product.price == Decimal("219000.00")
    assert product.price_currency == "VND"
    assert product.inventory == 5
    assert product.audit_status == "active"


async def test_etl_upserts_inventory_from_webhook_68_and_poll_snapshot(
    session, shop, publish_dlq
):
    """#68 snapshot and poll flat rows upsert the same InventoryItem by shop/SKU."""
    from juli_backend.models.models import InventoryItem
    from juli_backend.repositories.repos import InventoryRepo

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    webhook_payload = {
        "event_id": "d7813cae-9997-4d24-a583-7d85801250f1",
        "product_id": "1891234567890123456",
        "sku_id": "sku-inv-1",
        "quantity_snapshot_after_change": {"total_available_quantity": 7},
        "occurred_at": "2026-04-02T09:28:34.979101552Z",
    }
    poll_payload = {
        "sku_id": "sku-inv-1",
        "product_id": "1891234567890123456",
        "available_quantity": 15,
        "warehouse_id": "wh-1",
        "update_time": 1_800_000_000,
    }

    assert await consumer.ingest(
        IngestRecord(
            channel="tiktok.inventory.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(webhook_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(
        IngestRecord(
            channel="tiktok.inventory.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(poll_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    items = await InventoryRepo(session).list(shop.id)
    assert len(items) == 1
    assert items[0].tiktok_sku_id == "sku-inv-1"
    assert items[0].quantity == 15
    assert items[0].warehouse_id == "wh-1"

    result = await session.execute(select(InventoryItem).where(InventoryItem.shop_id == shop.id))
    assert len(list(result.scalars().all())) == 1


async def test_etl_second_poll_updates_inventory_without_duplicating(
    session, shop, publish_dlq
):
    from juli_backend.repositories.repos import InventoryRepo

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    first = {
        "sku_id": "sku-poll-2",
        "product_id": "prod-poll-2",
        "available_quantity": 10,
        "update_time": 1_700_000_600,
    }
    second = {
        "sku_id": "sku-poll-2",
        "product_id": "prod-poll-2",
        "available_quantity": 3,
        "update_time": 1_700_000_700,
    }

    assert await consumer.ingest(
        IngestRecord(
            channel="tiktok.inventory.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(first).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(
        IngestRecord(
            channel="tiktok.inventory.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(second).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    items = await InventoryRepo(session).list(shop.id)
    assert len(items) == 1
    assert items[0].quantity == 3


async def test_etl_persists_canonical_order_and_repolls_idempotently(
    session, shop, publish_dlq
):
    from juli_backend.models.models import Order

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    first_payload = {
        "id": "order-canonical-1",
        "user_id": "buyer_masked_1",
        "order_status": "AWAITING_SHIPMENT",
        "payment": {"total_amount": "150000.00", "currency": "VND"},
        "payment_time": 1_700_000_010,
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_100,
    }
    updated_payload = {
        **first_payload,
        "order_status": "CANCELLED",
        "payment": {"total_amount": "175000.00", "currency": "VND"},
        "cancellation_initiator": "SELLER",
        "cancel_reason": "OUT_OF_STOCK",
        "update_time": 1_700_000_200,
    }

    assert await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(first_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(updated_payload).encode(),
        )
    ) == ProcessOutcome.PROCESSED
    await session.commit()

    result = await session.execute(select(Order))
    orders = result.scalars().all()
    assert len(orders) == 1
    order = orders[0]
    assert order.tiktok_order_id == "order-canonical-1"
    assert order.buyer_id == "buyer_masked_1"
    assert order.order_value == Decimal("175000.00")
    assert order.total_amount == Decimal("175000.00")
    assert order.payment_time == datetime.fromtimestamp(
        1_700_000_010, tz=timezone.utc
    ).replace(tzinfo=None)
    assert order.cancel_reason == "OUT_OF_STOCK"
    assert order.is_seller_fault is True


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

"""Integration: sync_analytics handoff → ETL upserts AnalyticsPerformanceInterval (#425)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsPerformanceRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.workers.services.polling.sync import sync_analytics

TIKTOK_SHOP_ID = "7658073774813611784"

A36_SHOP_PERFORMANCE = {
    "latest_available_date": "2026-07-14",
    "performance": {
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "sales": {
                    "gmv": {
                        "overall": {"amount": "6408074.00", "currency": "VND"},
                    },
                    "orders_count": 26,
                    "sku_orders_count": 29,
                    "items_sold": 32,
                },
                "traffic": {
                    "avg_visitors": 303,
                    "avg_conversation_rate": "0.0759",
                },
            }
        ]
    },
}

A28_LIVE_LIST = [
    {
        "id": "1783927832000000001",
        "title": "Morning Live",
        "sales_performance": {
            "gmv": {"amount": "1575824", "currency": "VND"},
            "sku_orders": 7,
            "items_sold": 7,
            "customers": 4,
            "click_to_order_rate": "6.19%",
        },
        "interaction_performance": {
            "viewers": 245,
            "product_impressions": 1134,
            "click_through_rate": "9.96%",
        },
    }
]

A31_SKU_DETAIL = {
    "latest_available_date": "2026-07-15",
    "performance": {
        "sku_id": "1729700293904534135",
        "product_id": "1729700293904403063",
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "gmv": {"amount": "916678.00", "currency": "VND"},
                "sku_orders": 4,
                "items_sold": 4,
            }
        ],
    },
}


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+84909993816")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Analytics ETL Shop",
        tiktok_shop_id=TIKTOK_SHOP_ID,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


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


@pytest.mark.asyncio
async def test_analytics_poll_handoff_persists_shop_and_sku_rows(session, shop, publish_dlq):
    rate_limiter = MagicMock()
    rate_limiter.acquire.return_value = True
    resource = MagicMock()
    resource.list_sku_performance_all.return_value = [
        {"id": "1729700293904534135", "product_id": "1729700293904403063"}
    ]
    resource.get_sku_performance.return_value = A31_SKU_DETAIL
    resource.list_product_performance_all.return_value = []
    resource.list_live_performance_all.return_value = A28_LIVE_LIST
    resource.get_shop_performance.return_value = A36_SHOP_PERFORMANCE
    resource.get_shop_performance_per_hour.return_value = {}
    resource.get_bestselling_products.return_value = {}
    resource.get_bestselling_videos.return_value = {}

    handoffs: list[dict] = []

    async def capture_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoffs.append({"channel": channel, "shop_key": shop_key, "value": value})

    fixed_now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    sync_state: dict = {}
    await sync_analytics(
        resource=resource,
        rate_limiter=rate_limiter,
        handoff_fn=capture_handoff,
        app_id="app",
        shop_id=TIKTOK_SHOP_ID,
        sync_state=sync_state,
        now=fixed_now,
    )

    assert any(h["channel"] == "tiktok.analytics.shop.raw" for h in handoffs)
    assert any(h["channel"] == "tiktok.analytics.sku.raw" for h in handoffs)
    assert any(h["channel"] == "tiktok.analytics.live.raw" for h in handoffs)

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    for call in handoffs:
        outcome = await consumer.ingest(
            IngestRecord(
                channel=call["channel"],
                shop_key=call["shop_key"],
                value=call["value"],
            )
        )
        assert outcome == ProcessOutcome.PROCESSED
    await session.commit()

    repo = AnalyticsPerformanceRepo(session)
    rows = await repo.list(shop.id, limit=100)
    assert len(rows) == 3

    shop_row = next(r for r in rows if r.grain == "shop")
    assert shop_row.gmv is not None
    assert shop_row.sku_orders == 29
    assert shop_row.visitors == 303
    assert shop_row.ctr is None

    sku_row = next(r for r in rows if r.grain == "sku")
    assert sku_row.tiktok_sku_id == "1729700293904534135"
    assert sku_row.sku_orders == 4

    live_row = next(r for r in rows if r.grain == "live")
    assert live_row.tiktok_live_id == "1783927832000000001"
    assert live_row.sku_orders == 7
    assert live_row.click_through_rate is not None


@pytest.mark.asyncio
async def test_duplicate_analytics_handoff_is_idempotent(session, shop, publish_dlq):
    payload = {
        "grain": "shop",
        "start_date": "2026-07-13",
        "end_date": "2026-07-14",
        "gmv": "100.00",
        "gmv_currency": "VND",
        "sku_orders": 1,
        "update_time": 1_700_000_000,
        "event_id": "evt-analytics-dup-1",
    }

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    record = IngestRecord(
        channel="tiktok.analytics.shop.raw",
        shop_key=TIKTOK_SHOP_ID,
        value=json.dumps(payload).encode(),
    )
    assert await consumer.ingest(record) == ProcessOutcome.PROCESSED
    await session.commit()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer2.ingest(record) == ProcessOutcome.DUPLICATE
    await session.commit()

    rows = await AnalyticsPerformanceRepo(session).list(shop.id, limit=10)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_analytics_etl_dlq_error_taxonomy(session, shop, publish_dlq, dlq_messages):
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    outcome = await consumer.ingest(
        IngestRecord(
            channel="tiktok.analytics.shop.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps({"grain": "shop"}).encode(),
        )
    )
    assert outcome == ProcessOutcome.DLQ
    assert dlq_messages
    assert "start_date" in dlq_messages[0]["value"]["error"]

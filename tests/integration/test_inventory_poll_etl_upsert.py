"""Integration: poll sync_inventory → ETL upserts InventoryItem without duplicates (#381)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import InventoryRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.workers.services.polling.sync import sync_inventory

TIKTOK_SHOP_ID = "7658073774813611784"

SEARCH_RESPONSE_QTY = {
    "code": 0,
    "data": {
        "inventory": [
            {
                "product_id": "1729700293904403063",
                "skus": [
                    {
                        "id": "1729700293904534135",
                        "total_available_quantity": 995,
                        "warehouse_inventory": [
                            {
                                "available_quantity": 995,
                                "warehouse_id": "7272949914115966726",
                            }
                        ],
                    }
                ],
            }
        ]
    },
}

SEARCH_RESPONSE_UPDATED = {
    "code": 0,
    "data": {
        "inventory": [
            {
                "product_id": "1729700293904403063",
                "skus": [
                    {
                        "id": "1729700293904534135",
                        "total_available_quantity": 880,
                        "warehouse_inventory": [
                            {
                                "available_quantity": 880,
                                "warehouse_id": "7272949914115966726",
                            }
                        ],
                    }
                ],
            }
        ]
    },
}


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+84909993815")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Inventory Poll Shop",
        tiktok_shop_id=TIKTOK_SHOP_ID,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


@pytest.fixture
def publish_dlq():
    async def _publish(topic: str, key: str, value: bytes) -> None:
        return None

    return _publish


@pytest.mark.asyncio
async def test_second_poll_cycle_updates_inventory_item_not_duplicates(session, shop, publish_dlq):
    rate_limiter = MagicMock()
    rate_limiter.acquire.return_value = True
    resource = MagicMock()
    resource.search.side_effect = [SEARCH_RESPONSE_QTY, SEARCH_RESPONSE_UPDATED]

    handoffs: list[dict] = []

    async def capture_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoffs.append({"channel": channel, "shop_key": shop_key, "value": value})

    sync_state: dict = {}
    await sync_inventory(
        resource=resource,
        rate_limiter=rate_limiter,
        handoff_fn=capture_handoff,
        app_id="app",
        shop_id=TIKTOK_SHOP_ID,
        sync_state=sync_state,
    )
    # Force newer version on second cycle for update_time monotonicity
    first_synced_at = sync_state["inventory_last_sync_at"]

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

    items = await InventoryRepo(session).list(shop.id)
    assert len(items) == 1
    assert items[0].quantity == 995

    handoffs.clear()
    sync_state["inventory_last_sync_at"] = first_synced_at
    await sync_inventory(
        resource=resource,
        rate_limiter=rate_limiter,
        handoff_fn=capture_handoff,
        app_id="app",
        shop_id=TIKTOK_SHOP_ID,
        sync_state=sync_state,
    )
    # Ensure second handoff carries a newer update_time than the first persist
    for call in handoffs:
        payload = json.loads(call["value"])
        payload["update_time"] = first_synced_at + 60
        call["value"] = json.dumps(payload).encode()

    consumer2 = EtlConsumer(session=session, publish_dlq=publish_dlq)
    for call in handoffs:
        outcome = await consumer2.ingest(
            IngestRecord(
                channel=call["channel"],
                shop_key=call["shop_key"],
                value=call["value"],
            )
        )
        assert outcome == ProcessOutcome.PROCESSED
    await session.commit()

    items = await InventoryRepo(session).list(shop.id)
    assert len(items) == 1
    assert items[0].quantity == 880
    assert items[0].tiktok_sku_id == "1729700293904534135"

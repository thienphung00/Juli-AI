"""TDD tests for polling sync workers.

Behaviors under test:
- sync_orders fetches orders since last sync, publishes each to Kafka
- sync_products fetches products since last sync, publishes each to Kafka
- sync_inventory fetches all inventory, publishes to Kafka
- Workers skip API call when rate limiter denies
- Workers update sync state after successful fetch
- Workers handle API errors gracefully without crashing
"""

import json
import time

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.integrations.tiktok.exceptions import RateLimitError, TikTokSystemError
from src.services.polling.sync import sync_orders, sync_products, sync_inventory


@pytest.fixture
def mock_orders_resource():
    resource = MagicMock()
    resource.search_all.return_value = [
        {"order_id": "o1", "update_time": 1700000100},
        {"order_id": "o2", "update_time": 1700000200},
    ]
    return resource


@pytest.fixture
def mock_products_resource():
    resource = MagicMock()
    resource.search_all.return_value = [
        {"product_id": "p1", "updated_at": 1700000100},
        {"product_id": "p2", "updated_at": 1700000200},
    ]
    return resource


@pytest.fixture
def mock_inventory_resource():
    resource = MagicMock()
    resource.search.return_value = {
        "inventory": [
            {"sku_id": "sku1", "available_quantity": 50},
            {"sku_id": "sku2", "available_quantity": 0},
        ]
    }
    return resource


@pytest.fixture
def mock_rate_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    limiter.time_until_reset.return_value = 0
    return limiter


@pytest.fixture
def kafka_messages():
    return []


@pytest.fixture
def publish_fn(kafka_messages):
    async def _publish(topic: str, key: str, value: bytes) -> None:
        kafka_messages.append({"topic": topic, "key": key, "value": value})
    return _publish


@pytest.fixture
def sync_state():
    return {}


class TestSyncOrders:
    @pytest.mark.asyncio
    async def test_fetches_orders_and_publishes_to_kafka(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(kafka_messages) == 2
        assert kafka_messages[0]["topic"] == "tiktok.orders.raw"
        assert kafka_messages[0]["key"] == "shop1"
        payload = json.loads(kafka_messages[0]["value"])
        assert payload["order_id"] == "o1"

    @pytest.mark.asyncio
    async def test_passes_update_time_from_sync_state(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        sync_state["orders_last_update_time"] = 1700000000

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_orders_resource.search_all.call_args[1]
        assert call_kwargs["update_time_from"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["orders_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_orders_resource.search_all.assert_not_called()
        assert len(kafka_messages) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        mock_orders_resource.search_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(kafka_messages) == 0
        assert "orders_last_update_time" not in sync_state


class TestSyncProducts:
    @pytest.mark.asyncio
    async def test_fetches_products_and_publishes_to_kafka(
        self, mock_products_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(kafka_messages) == 2
        assert kafka_messages[0]["topic"] == "tiktok.products.raw"
        payload = json.loads(kafka_messages[0]["value"])
        assert payload["product_id"] == "p1"

    @pytest.mark.asyncio
    async def test_passes_update_time_from_sync_state(
        self, mock_products_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        sync_state["products_last_update_time"] = 1700000000

        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_products_resource.search_all.call_args[1]
        assert call_kwargs["update_time_from"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_products_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["products_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_products_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_products_resource.search_all.assert_not_called()
        assert len(kafka_messages) == 0


class TestSyncInventory:
    @pytest.mark.asyncio
    async def test_fetches_inventory_and_publishes_to_kafka(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(kafka_messages) == 2
        assert kafka_messages[0]["topic"] == "tiktok.inventory.raw"
        payload = json.loads(kafka_messages[0]["value"])
        assert payload["sku_id"] == "sku1"

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_inventory_resource.search.assert_not_called()
        assert len(kafka_messages) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, kafka_messages, sync_state
    ):
        mock_inventory_resource.search.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(kafka_messages) == 0

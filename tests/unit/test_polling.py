"""TDD tests for polling sync workers.

Behaviors under test:
- sync_orders fetches orders since last sync, hands each off to ETL
- sync_products fetches products since last sync, hands each off to ETL
- sync_inventory fetches all inventory, hands off to ETL
- Workers skip API call when rate limiter denies
- Workers update sync state after successful fetch
- Workers handle API errors gracefully without crashing
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from backend.integrations.catalog.domain.integrations.tiktok.exceptions import (
    PermissionDeniedError,
    TikTokSystemError,
)
from backend.workers.services.polling.sync import (
    BACKFILL_WINDOW_SECONDS,
    backfill_shop,
    sync_creators,
    sync_inventory,
    sync_livestreams,
    sync_orders,
    sync_products,
    sync_returns,
    sync_settlements,
)


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
def handoff_calls():
    return []


@pytest.fixture
def handoff_fn(handoff_calls):
    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append({"channel": channel, "shop_key": shop_key, "value": value})

    return _handoff


@pytest.fixture
def publish_fn(handoff_fn):
    """Deprecated alias for ``handoff_fn``."""
    return handoff_fn


@pytest.fixture
def sync_state():
    return {}


class TestSyncOrders:
    @pytest.mark.asyncio
    async def test_fetches_orders_and_publishes_to_kafka(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.orders.raw"
        assert handoff_calls[0]["shop_key"] == "shop1"
        payload = json.loads(handoff_calls[0]["value"])
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
        self, mock_orders_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
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
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_orders_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
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

        assert len(handoff_calls) == 0
        assert "orders_last_update_time" not in sync_state


@pytest.fixture
def mock_returns_resource():
    resource = MagicMock()
    resource.search_returns_all.return_value = [
        {
            "return_id": "r1",
            "order_id": "o1",
            "update_time": 1700000300,
            "refund": {"refund_total": "25.00"},
        },
    ]
    return resource


class TestSyncReturns:
    @pytest.mark.asyncio
    async def test_fetches_returns_and_publishes(
        self, mock_returns_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_returns(
            resource=mock_returns_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "tiktok.returns.raw"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["return_id"] == "r1"
        assert sync_state["returns_last_update_time"] == 1700000300


class TestSyncProducts:
    @pytest.mark.asyncio
    async def test_fetches_products_and_publishes_to_kafka(
        self, mock_products_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.products.raw"
        payload = json.loads(handoff_calls[0]["value"])
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
        self, mock_products_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
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
        assert len(handoff_calls) == 0


class TestSyncInventory:
    @pytest.mark.asyncio
    async def test_fetches_inventory_and_publishes_to_kafka(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.inventory.raw"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["sku_id"] == "sku1"

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
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
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_inventory_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
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

        assert len(handoff_calls) == 0


# ---------------------------------------------------------------------------
# Fixtures for new sync workers (#31)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_creators_resource():
    resource = MagicMock()
    resource.list_all.return_value = [
        {"creator_id": "c1", "name": "Creator A", "update_time": 1700000100},
        {"creator_id": "c2", "name": "Creator B", "update_time": 1700000200},
    ]
    return resource


@pytest.fixture
def mock_livestreams_resource():
    resource = MagicMock()
    resource.list_all.return_value = [
        {"livestream_id": "ls1", "title": "Stream 1", "update_time": 1700000300},
        {"livestream_id": "ls2", "title": "Stream 2", "update_time": 1700000400},
    ]
    return resource


@pytest.fixture
def mock_settlements_resource():
    resource = MagicMock()
    resource.list_all.return_value = [
        {"settlement_id": "s1", "amount": "100.00", "update_time": 1700000500},
        {"settlement_id": "s2", "amount": "250.00", "update_time": 1700000600},
    ]
    return resource


# ---------------------------------------------------------------------------
# AC1 — sync_creators
# ---------------------------------------------------------------------------


class TestSyncCreators:
    @pytest.mark.asyncio
    async def test_fetches_creators_and_publishes_to_kafka(
        self, mock_creators_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.creators.raw"
        assert handoff_calls[0]["shop_key"] == "shop1"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["creator_id"] == "c1"

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_creators_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["creators_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_creators_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_creators_resource.list_all.assert_not_called()
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_creators_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_creators_resource.list_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 0
        assert "creators_last_update_time" not in sync_state

    @pytest.mark.asyncio
    async def test_surfaces_permission_denied_error(
        self, mock_creators_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        mock_creators_resource.list_all.side_effect = PermissionDeniedError(
            code=100003, message="scope_missing"
        )

        with pytest.raises(PermissionDeniedError):
            await sync_creators(
                resource=mock_creators_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
                sync_state=sync_state,
            )


# ---------------------------------------------------------------------------
# AC2 — sync_livestreams
# ---------------------------------------------------------------------------


class TestSyncLivestreams:
    @pytest.mark.asyncio
    async def test_fetches_livestreams_and_publishes_to_kafka(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_livestreams(
            resource=mock_livestreams_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.livestreams.raw"
        assert handoff_calls[0]["shop_key"] == "shop1"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["livestream_id"] == "ls1"

    @pytest.mark.asyncio
    async def test_passes_start_time_from_sync_state(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        sync_state["livestreams_last_update_time"] = 1700000000

        await sync_livestreams(
            resource=mock_livestreams_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_livestreams_resource.list_all.call_args[1]
        assert call_kwargs["start_time"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        await sync_livestreams(
            resource=mock_livestreams_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["livestreams_last_update_time"] == 1700000400

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_livestreams(
            resource=mock_livestreams_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_livestreams_resource.list_all.assert_not_called()
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_livestreams_resource.list_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_livestreams(
            resource=mock_livestreams_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 0
        assert "livestreams_last_update_time" not in sync_state

    @pytest.mark.asyncio
    async def test_surfaces_permission_denied_error(
        self, mock_livestreams_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        mock_livestreams_resource.list_all.side_effect = PermissionDeniedError(
            code=100003, message="scope_missing"
        )

        with pytest.raises(PermissionDeniedError):
            await sync_livestreams(
                resource=mock_livestreams_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
                sync_state=sync_state,
            )


# ---------------------------------------------------------------------------
# AC3 — sync_settlements
# ---------------------------------------------------------------------------


class TestSyncSettlements:
    @pytest.mark.asyncio
    async def test_fetches_settlements_and_publishes_to_kafka(
        self, mock_settlements_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        await sync_settlements(
            resource=mock_settlements_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 2
        assert handoff_calls[0]["channel"] == "tiktok.settlements.raw"
        assert handoff_calls[0]["shop_key"] == "shop1"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["settlement_id"] == "s1"

    @pytest.mark.asyncio
    async def test_passes_settle_time_from_sync_state(
        self, mock_settlements_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        sync_state["settlements_last_update_time"] = 1700000000

        await sync_settlements(
            resource=mock_settlements_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_settlements_resource.list_all.call_args[1]
        assert call_kwargs["settle_time_from"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_settlements_resource, mock_rate_limiter, publish_fn, sync_state
    ):
        await sync_settlements(
            resource=mock_settlements_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["settlements_last_update_time"] == 1700000600

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_settlements_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_settlements(
            resource=mock_settlements_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_settlements_resource.list_all.assert_not_called()
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_settlements_resource, mock_rate_limiter, publish_fn, handoff_calls, sync_state
    ):
        mock_settlements_resource.list_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_settlements(
            resource=mock_settlements_resource,
            rate_limiter=mock_rate_limiter,
            publish_fn=publish_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 0
        assert "settlements_last_update_time" not in sync_state


# ---------------------------------------------------------------------------
# AC4 — backfill_shop (90-day initial backfill)
# ---------------------------------------------------------------------------


class TestBackfillShop:
    @pytest.mark.asyncio
    async def test_backfill_sets_90_day_lookback_for_livestreams(
        self, mock_creators_resource, mock_livestreams_resource,
        mock_settlements_resource, mock_rate_limiter, publish_fn,
    ):
        fake_now = 1700000000

        with patch("backend.workers.services.polling.sync.time") as mock_time:
            mock_time.time.return_value = fake_now

            await backfill_shop(
                creators_resource=mock_creators_resource,
                livestreams_resource=mock_livestreams_resource,
                settlements_resource=mock_settlements_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
            )

        expected_lookback = fake_now - BACKFILL_WINDOW_SECONDS
        ls_kwargs = mock_livestreams_resource.list_all.call_args[1]
        assert ls_kwargs["start_time"] == expected_lookback

    @pytest.mark.asyncio
    async def test_backfill_sets_90_day_lookback_for_settlements(
        self, mock_creators_resource, mock_livestreams_resource,
        mock_settlements_resource, mock_rate_limiter, publish_fn,
    ):
        fake_now = 1700000000

        with patch("backend.workers.services.polling.sync.time") as mock_time:
            mock_time.time.return_value = fake_now

            await backfill_shop(
                creators_resource=mock_creators_resource,
                livestreams_resource=mock_livestreams_resource,
                settlements_resource=mock_settlements_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
            )

        expected_lookback = fake_now - BACKFILL_WINDOW_SECONDS
        st_kwargs = mock_settlements_resource.list_all.call_args[1]
        assert st_kwargs["settle_time_from"] == expected_lookback

    @pytest.mark.asyncio
    async def test_backfill_calls_all_three_syncs(
        self, mock_creators_resource, mock_livestreams_resource,
        mock_settlements_resource, mock_rate_limiter, publish_fn, handoff_calls,
    ):
        with patch("backend.workers.services.polling.sync.time") as mock_time:
            mock_time.time.return_value = 1700000000

            await backfill_shop(
                creators_resource=mock_creators_resource,
                livestreams_resource=mock_livestreams_resource,
                settlements_resource=mock_settlements_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
            )

        mock_creators_resource.list_all.assert_called_once()
        mock_livestreams_resource.list_all.assert_called_once()
        mock_settlements_resource.list_all.assert_called_once()
        assert len(handoff_calls) == 6

    @pytest.mark.asyncio
    async def test_backfill_returns_sync_state(
        self, mock_creators_resource, mock_livestreams_resource,
        mock_settlements_resource, mock_rate_limiter, publish_fn,
    ):
        with patch("backend.workers.services.polling.sync.time") as mock_time:
            mock_time.time.return_value = 1700000000

            result = await backfill_shop(
                creators_resource=mock_creators_resource,
                livestreams_resource=mock_livestreams_resource,
                settlements_resource=mock_settlements_resource,
                rate_limiter=mock_rate_limiter,
                publish_fn=publish_fn,
                app_id="app1",
                shop_id="shop1",
            )

        assert result["creators_last_update_time"] == 1700000200
        assert result["livestreams_last_update_time"] == 1700000400
        assert result["settlements_last_update_time"] == 1700000600

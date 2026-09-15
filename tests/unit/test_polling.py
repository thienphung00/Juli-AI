"""TDD tests for polling sync workers.

Behaviors under test:
- sync_orders fetches orders since last sync, hands each off to ETL
- sync_products fetches products since last sync, hands each off to ETL
- Workers skip API call when rate limiter denies
- Workers update sync state after successful fetch
- Workers handle API errors gracefully without crashing
- sync_inventory sends product_ids (required by the vendor endpoint, #1948),
  pages a large product-id list, and fails loudly instead of swallowing errors
"""

import json
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.exceptions import (
    PermissionDeniedError,
    TikTokAPIError,
    TikTokSystemError,
)
from juli_backend.workers.services.polling.sync import (
    backfill_shop,
    sync_creators,
    sync_inventory,
    sync_orders,
    sync_products,
    sync_returns,
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
def sync_state():
    return {}


class TestSyncOrders:
    @pytest.mark.asyncio
    async def test_fetches_orders_and_publishes_to_kafka(
        self, mock_orders_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
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
        self, mock_orders_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        sync_state["orders_last_update_time"] = 1700000000

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_orders_resource.search_all.call_args[1]
        assert call_kwargs["update_time_from"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_orders_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["orders_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_orders_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_orders_resource.search_all.assert_not_called()
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_orders_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        mock_orders_resource.search_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_orders(
            resource=mock_orders_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
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
        self, mock_returns_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        await sync_returns(
            resource=mock_returns_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
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
        self, mock_products_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
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
        self, mock_products_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        sync_state["products_last_update_time"] = 1700000000

        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        call_kwargs = mock_products_resource.search_all.call_args[1]
        assert call_kwargs["update_time_from"] == 1700000000

    @pytest.mark.asyncio
    async def test_updates_sync_state_after_success(
        self, mock_products_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["products_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_updates_sync_state_from_update_time_field(
        self, mock_products_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        mock_products_resource.search_all.return_value = [
            {"product_id": "p1", "update_time": 1700000300},
        ]

        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["products_last_update_time"] == 1700000300

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_products_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_products(
            resource=mock_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_products_resource.search_all.assert_not_called()
        assert len(handoff_calls) == 0


@pytest.fixture
def mock_creators_resource():
    resource = MagicMock()
    resource.list_all.return_value = [
        {"creator_id": "c1", "name": "Creator A", "update_time": 1700000100},
        {"creator_id": "c2", "name": "Creator B", "update_time": 1700000200},
    ]
    return resource


class TestSyncCreators:
    @pytest.mark.asyncio
    async def test_fetches_creators_and_publishes_to_kafka(
        self, mock_creators_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
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
        self, mock_creators_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert sync_state["creators_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self, mock_creators_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        mock_rate_limiter.acquire.return_value = False

        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        mock_creators_resource.list_all.assert_not_called()
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(
        self, mock_creators_resource, mock_rate_limiter, handoff_fn, handoff_calls, sync_state
    ):
        mock_creators_resource.list_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )

        await sync_creators(
            resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
        )

        assert len(handoff_calls) == 0
        assert "creators_last_update_time" not in sync_state

    @pytest.mark.asyncio
    async def test_surfaces_permission_denied_error(
        self, mock_creators_resource, mock_rate_limiter, handoff_fn, sync_state
    ):
        mock_creators_resource.list_all.side_effect = PermissionDeniedError(
            code=100003, message="scope_missing"
        )

        with pytest.raises(PermissionDeniedError):
            await sync_creators(
                resource=mock_creators_resource,
                rate_limiter=mock_rate_limiter,
                handoff_fn=handoff_fn,
                app_id="app1",
                shop_id="shop1",
                sync_state=sync_state,
            )


class TestBackfillShop:
    @pytest.mark.asyncio
    async def test_backfill_calls_sync_creators(
        self,
        mock_creators_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
    ):
        await backfill_shop(
            creators_resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
        )

        mock_creators_resource.list_all.assert_called_once()
        assert len(handoff_calls) == 2

    @pytest.mark.asyncio
    async def test_backfill_returns_sync_state(
        self,
        mock_creators_resource,
        mock_rate_limiter,
        handoff_fn,
    ):
        result = await backfill_shop(
            creators_resource=mock_creators_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
        )

        assert result["creators_last_update_time"] == 1700000200


def _inventory_page_response(product_id: str, sku_id: str, quantity: int) -> dict:
    return {
        "code": 0,
        "data": {
            "inventory": [
                {
                    "product_id": product_id,
                    "skus": [
                        {
                            "id": sku_id,
                            "total_available_quantity": quantity,
                            "warehouse_inventory": [
                                {"available_quantity": quantity, "warehouse_id": "wh-1"}
                            ],
                        }
                    ],
                }
            ]
        },
    }


class _FakeInventoryResource:
    """Binds the real ``InventoryResource.search`` signature (#1948).

    A call this endpoint would actually reject -- e.g. one made without
    ``product_ids`` -- fails here too, instead of a ``MagicMock`` silently
    absorbing whatever kwargs production code happens to pass.
    """

    def __init__(self, responses: list[dict] | None = None, *, error: Exception | None = None):
        self._responses = list(responses or [])
        self._error = error
        self.calls: list[list[str]] = []

    def search(self, *, product_ids: list[str], sku_ids: list[str] | None = None) -> dict:
        if not product_ids:
            raise ValueError("product_ids must be non-empty")
        self.calls.append(list(product_ids))
        if self._error is not None:
            raise self._error
        return self._responses[(len(self.calls) - 1) % len(self._responses)]


class TestSyncInventory:
    @pytest.fixture
    def mock_inventory_resource(self):
        return _FakeInventoryResource([_inventory_page_response("prod-1", "sku-1", 42)])

    @staticmethod
    async def _one_product_id():
        return ["prod-1"]

    @pytest.mark.asyncio
    async def test_sends_product_ids_and_flattens_inventory(
        self,
        mock_inventory_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=self._one_product_id,
        )

        assert mock_inventory_resource.calls == [["prod-1"]]
        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "tiktok.inventory.raw"
        payload = json.loads(handoff_calls[0]["value"])
        assert payload["sku_id"] == "sku-1"
        assert payload["available_quantity"] == 42
        assert payload["event_id"].startswith("poll-inventory:shop1:sku-1:")
        assert "inventory_last_sync_at" in sync_state

    @pytest.mark.asyncio
    async def test_pages_product_ids_across_multiple_search_calls(
        self,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        """30 confirmed to work in one call; page rather than assume a larger set fits (#1948)."""
        resource = _FakeInventoryResource(
            [
                _inventory_page_response("prod-1", "sku-1", 10),
                _inventory_page_response("prod-2", "sku-2", 20),
                _inventory_page_response("prod-3", "sku-3", 30),
            ]
        )

        async def list_product_ids() -> list[str]:
            return ["prod-1", "prod-2", "prod-3"]

        await sync_inventory(
            resource=resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=list_product_ids,
            page_size=1,
        )

        assert resource.calls == [["prod-1"], ["prod-2"], ["prod-3"]]
        assert len(handoff_calls) == 3
        sku_ids = {json.loads(call["value"])["sku_id"] for call in handoff_calls}
        assert sku_ids == {"sku-1", "sku-2", "sku-3"}
        assert "inventory_last_sync_at" in sync_state

    @pytest.mark.asyncio
    async def test_inventory_event_id_stable_for_identical_snapshot(
        self,
        mock_inventory_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=self._one_product_id,
        )
        first_event_id = json.loads(handoff_calls[0]["value"])["event_id"]
        handoff_calls.clear()

        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=self._one_product_id,
        )
        second_event_id = json.loads(handoff_calls[0]["value"])["event_id"]
        assert second_event_id == first_event_id

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(
        self,
        mock_inventory_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        mock_rate_limiter.acquire.return_value = False

        async def list_product_ids_should_not_be_called() -> list[str]:
            raise AssertionError("list_product_ids must not run when rate-limited")

        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=list_product_ids_should_not_be_called,
        )

        assert mock_inventory_resource.calls == []
        assert handoff_calls == []

    @pytest.mark.asyncio
    async def test_no_op_when_no_product_ids(
        self,
        mock_inventory_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        """A shop with no synced products yet is a legitimate no-op, not a failure."""

        async def no_product_ids() -> list[str]:
            return []

        await sync_inventory(
            resource=mock_inventory_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="shop1",
            sync_state=sync_state,
            list_product_ids=no_product_ids,
        )

        assert mock_inventory_resource.calls == []
        assert handoff_calls == []
        assert sync_state == {}

    @pytest.mark.asyncio
    async def test_raises_instead_of_swallowing_api_error(
        self,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
    ):
        """The whole lesson of #1948: a dropped sync must surface as a failure."""
        resource = _FakeInventoryResource(error=TikTokAPIError(12019008, "Invalid Parameter"))

        with pytest.raises(TikTokAPIError):
            await sync_inventory(
                resource=resource,
                rate_limiter=mock_rate_limiter,
                handoff_fn=handoff_fn,
                app_id="app1",
                shop_id="shop1",
                sync_state=sync_state,
                list_product_ids=self._one_product_id,
            )

        assert handoff_calls == []
        assert sync_state == {}


class TestDefaultListProductIds:
    """sync_inventory's list_product_ids default (#1948 review): self-contained,
    reads the products table through the existing repository layer so
    orchestrate.py's call site (no list_product_ids kwarg) keeps working."""

    @pytest.mark.asyncio
    async def test_resolves_synced_product_ids_via_repository_layer(
        self, session, engine, monkeypatch
    ):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        import juli_backend.database.database as database_module
        from juli_backend.workers.services.polling.sync import (
            _resolve_synced_product_ids,
        )
        from tests.support.builders import make_product, make_tenant

        _user, shop = await make_tenant(session, tiktok_shop_id="tt-shop-default")
        await make_product(session, shop, tiktok_product_id="prod-a")
        await make_product(session, shop, tiktok_product_id="prod-b")
        await session.commit()

        test_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            database_module, "ensure_worker_session_factory", lambda _url: test_factory
        )

        product_ids = await _resolve_synced_product_ids("tt-shop-default")

        assert set(product_ids) == {"prod-a", "prod-b"}

    @pytest.mark.asyncio
    async def test_unknown_shop_resolves_to_empty(self, session, engine, monkeypatch):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        import juli_backend.database.database as database_module
        from juli_backend.workers.services.polling.sync import (
            _resolve_synced_product_ids,
        )

        test_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            database_module, "ensure_worker_session_factory", lambda _url: test_factory
        )

        assert await _resolve_synced_product_ids("no-such-shop") == []

    @pytest.mark.asyncio
    async def test_unavailable_database_resolves_to_empty_not_raise(self):
        """A misconfigured/unreachable DB is a resolution miss, not a crash (#1948 review)."""
        from juli_backend.workers.services.polling.sync import (
            _resolve_synced_product_ids,
        )

        assert await _resolve_synced_product_ids("any-shop") == []

    @pytest.mark.asyncio
    async def test_sync_inventory_uses_default_when_not_injected(
        self,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
        session,
        engine,
        monkeypatch,
    ):
        """orchestrate.py's existing call (no list_product_ids kwarg) still works."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        import juli_backend.database.database as database_module
        from tests.support.builders import make_product, make_tenant

        _user, shop = await make_tenant(session, tiktok_shop_id="tt-shop-caller")
        await make_product(session, shop, tiktok_product_id="prod-caller")
        await session.commit()

        test_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            database_module, "ensure_worker_session_factory", lambda _url: test_factory
        )

        resource = _FakeInventoryResource(
            [_inventory_page_response("prod-caller", "sku-caller", 7)]
        )

        await sync_inventory(
            resource=resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id="app1",
            shop_id="tt-shop-caller",
            sync_state=sync_state,
        )

        assert resource.calls == [["prod-caller"]]
        assert len(handoff_calls) == 1
        assert "inventory_last_sync_at" in sync_state

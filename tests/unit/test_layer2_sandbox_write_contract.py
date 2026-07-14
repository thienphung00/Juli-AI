"""Layer 2 sandbox write contract tests for issue #301.

Validates signing, HTTP status, TikTok code handling, response parsing, and
factory isolation per contract-collection.md §B-1–B-8 and §A-25 (Get Activity).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.capabilities import SANDBOX_AUTH_ID
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_CREATE_PATH,
    PROMOTION_CREATE_PATH,
    fulfillment_batch_ship_path,
    fulfillment_combine_packages_path,
    fulfillment_ship_package_path,
    fulfillment_split_order_path,
    fulfillment_uncombine_package_path,
    product_edit_path,
    product_inventory_update_path,
    promotion_activity_path,
    promotion_activity_products_path,
    promotion_deactivate_path,
    supply_chain_confirm_shipment_path,
)
from juli_backend.integrations.tiktok.exceptions import ResourceNotFoundError, TransportGuardError
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    SandboxWriteClientFactory,
    SandboxWriteResources,
)
from juli_backend.integrations.tiktok.signing import sign_request


@pytest.fixture
def sandbox_config() -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="sandbox-app-key",
        app_secret="sandbox-app-secret",
        access_token="sandbox-access-token",
        merchant_auth_id=SANDBOX_AUTH_ID,
        shop_cipher="ROW_sandboxcipher12",
    )


@pytest.fixture
def production_config() -> ClientFactoryConfig:
    from juli_backend.integrations.tiktok.capabilities import PRODUCTION_AUTH_ID

    return ClientFactoryConfig(
        app_key="prod-app-key",
        app_secret="prod-app-secret",
        access_token="prod-access-token",
        merchant_auth_id=PRODUCTION_AUTH_ID,
        shop_cipher="ROW_prodcipher1234",
    )


def _mock_success_response(data: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"code": 0, "data": data or {}, "message": "Success"}
    resp.raise_for_status = MagicMock()
    return resp


def _assert_signed_request(
    session_method: MagicMock,
    *,
    app_secret: str,
    path: str,
    method: str,
) -> None:
    assert session_method.called
    call_kwargs = session_method.call_args.kwargs
    params = call_kwargs.get("params") or session_method.call_args[1].get("params", {})
    assert "sign" in params
    body = call_kwargs.get("json")
    if body is None:
        body_str = ""
    else:
        body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)
    expected = sign_request(
        app_secret=app_secret,
        path=path,
        params={k: v for k, v in params.items() if k != "sign"},
        body=body_str,
    )
    assert params["sign"] == expected
    assert call_kwargs.get("headers", {}).get("x-tts-access-token") == "sandbox-access-token"
    assert method in ("POST", "PUT", "GET")


def _assert_signed_get(
    session_method: MagicMock,
    *,
    app_secret: str,
    path: str,
) -> None:
    assert session_method.called
    call_kwargs = session_method.call_args.kwargs
    params = call_kwargs.get("params") or session_method.call_args[1].get("params", {})
    assert "sign" in params
    expected = sign_request(
        app_secret=app_secret,
        path=path,
        params={k: v for k, v in params.items() if k != "sign"},
        body="",
    )
    assert params["sign"] == expected
    assert call_kwargs.get("headers", {}).get("x-tts-access-token") == "sandbox-access-token"


class TestSandboxWriteClientFactoryResources:
    def test_create_resources_returns_write_bundle(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        assert isinstance(resources, SandboxWriteResources)
        assert resources.inventory is not None
        assert resources.products is not None
        assert resources.fulfillment is not None
        assert resources.promotion is not None

    def test_production_factory_does_not_expose_sandbox_write_resources(
        self,
        production_config: ClientFactoryConfig,
    ):
        prod_resources = ProductionReadClientFactory().create_resources(production_config)
        assert not hasattr(prod_resources, "fulfillment")
        assert not hasattr(prod_resources, "promotion")
        # Inventory search is Layer 1 (P2-B9); write update remains sandbox-guarded.
        assert prod_resources.inventory is not None


class TestInventoryUpdateContract:
    PRODUCT_ID = "1736363193934775939"
    SKU_ID = "1736404513645233795"

    def test_inventory_update_signing_and_response(
        self,
        sandbox_config: ClientFactoryConfig,
    ):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.inventory._client
        client._session = MagicMock()
        client._session.post.return_value = _mock_success_response()

        path = product_inventory_update_path(self.PRODUCT_ID)
        result = resources.inventory.update(
            product_id=self.PRODUCT_ID,
            sku_id=self.SKU_ID,
            quantity=15,
        )

        assert result == {}
        _assert_signed_request(
            client._session.post,
            app_secret=sandbox_config.app_secret,
            path=path,
            method="POST",
        )

    def test_inventory_update_blocked_on_production(
        self,
        production_config: ClientFactoryConfig,
    ):
        client = ProductionReadClientFactory().create(production_config)
        client._session = MagicMock()
        from juli_backend.integrations.tiktok.resources.inventory import InventoryResource

        resource = InventoryResource(client)
        with pytest.raises(TransportGuardError):
            resource.update(
                product_id=self.PRODUCT_ID,
                sku_id=self.SKU_ID,
                warehouse_id="7657265511696664340",
                quantity=10,
            )
        client._session.post.assert_not_called()


class TestProductCreateEditContract:
    CREATE_BODY = {
        "title": "Premium Stainless Steel Water Bottle 750ml",
        "category_id": "605254",
    }
    PRODUCT_ID = "1736405947247986307"

    def test_create_product_signing_and_response(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        client._session.post.return_value = _mock_success_response(
            {"product_id": self.PRODUCT_ID, "skus": []}
        )

        result = resources.products.create(body=self.CREATE_BODY)

        assert result["product_id"] == self.PRODUCT_ID
        _assert_signed_request(
            client._session.post,
            app_secret=sandbox_config.app_secret,
            path=PRODUCT_CREATE_PATH,
            method="POST",
        )

    def test_edit_product_signing_and_response(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        client._session.put.return_value = _mock_success_response()

        path = product_edit_path(self.PRODUCT_ID)
        result = resources.products.edit(product_id=self.PRODUCT_ID, body={"title": "Updated"})

        assert result == {}
        _assert_signed_request(
            client._session.put,
            app_secret=sandbox_config.app_secret,
            path=path,
            method="PUT",
        )

    def test_create_product_blocked_on_production(self, production_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(production_config)
        client._session = MagicMock()
        from juli_backend.integrations.tiktok.resources.products import ProductsResource

        resource = ProductsResource(client)
        with pytest.raises(TransportGuardError):
            resource.create(body={"title": "blocked"})
        client._session.post.assert_not_called()


class TestFulfillmentWriteContract:
    PACKAGE_ID = "1153486604836964618"
    ORDER_ID = "577958834469439754"

    @pytest.fixture
    def fulfillment_resources(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        client._session.post.return_value = _mock_success_response()
        return resources, client, sandbox_config

    def test_combine_packages(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = fulfillment_combine_packages_path()
        resources.fulfillment.combine_packages(body={"combinable_packages": [self.PACKAGE_ID]})
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_ship_package(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = fulfillment_ship_package_path(self.PACKAGE_ID)
        resources.fulfillment.ship_package(package_id=self.PACKAGE_ID, body={"package_id": self.PACKAGE_ID})
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_batch_ship_packages(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = fulfillment_batch_ship_path()
        resources.fulfillment.batch_ship_packages(body={"package_ids": [self.PACKAGE_ID]})
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_split_order(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = fulfillment_split_order_path(self.ORDER_ID)
        resources.fulfillment.split_order(order_id=self.ORDER_ID, body={"order_id": self.ORDER_ID})
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_uncombine_package(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = fulfillment_uncombine_package_path(self.PACKAGE_ID)
        resources.fulfillment.uncombine_package(package_id=self.PACKAGE_ID)
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_confirm_shipment_supply_chain(self, fulfillment_resources):
        resources, client, config = fulfillment_resources
        path = supply_chain_confirm_shipment_path()
        resources.fulfillment.confirm_shipment(body={"package_id": self.PACKAGE_ID})
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )


class TestPromotionWriteContract:
    ACTIVITY_ID = "7660012771723118343"
    CREATE_BODY = {
        "title": "7/7 Flash Sale",
        "activity_type": "FLASHSALE",
        "product_level": "VARIATION",
        "duration_type": "FIXED_TIME",
        "begin_time": 1783411200,
        "end_time": 1783432800,
    }

    @pytest.fixture
    def promotion_resources(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.promotion._client
        client._session = MagicMock()
        client._session.get.return_value = _mock_success_response(
            {"activity_id": self.ACTIVITY_ID, "status": "ONGOING"}
        )
        client._session.post.return_value = _mock_success_response(
            {"activity_id": self.ACTIVITY_ID, "status": "EXPIRED"}
        )
        client._session.put.return_value = _mock_success_response(
            {"activity_id": self.ACTIVITY_ID, "status": "NOT_START"}
        )
        return resources, client, sandbox_config

    def test_get_activity(self, promotion_resources):
        resources, client, config = promotion_resources
        path = promotion_activity_path(self.ACTIVITY_ID)
        result = resources.promotion.get_activity(self.ACTIVITY_ID)
        assert result["activity_id"] == self.ACTIVITY_ID
        _assert_signed_get(
            client._session.get,
            app_secret=config.app_secret,
            path=path,
        )

    def test_create_activity(self, promotion_resources):
        resources, client, config = promotion_resources
        result = resources.promotion.create_activity(body=self.CREATE_BODY)
        assert result["activity_id"] == self.ACTIVITY_ID
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=PROMOTION_CREATE_PATH,
            method="POST",
        )

    def test_update_activity(self, promotion_resources):
        resources, client, config = promotion_resources
        path = promotion_activity_path(self.ACTIVITY_ID)
        resources.promotion.update_activity(
            activity_id=self.ACTIVITY_ID,
            body={"title": "Updated"},
        )
        _assert_signed_request(
            client._session.put,
            app_secret=config.app_secret,
            path=path,
            method="PUT",
        )

    def test_update_activity_products(self, promotion_resources):
        resources, client, config = promotion_resources
        path = promotion_activity_products_path(self.ACTIVITY_ID)
        resources.promotion.update_activity_products(
            activity_id=self.ACTIVITY_ID,
            body={"products": []},
        )
        _assert_signed_request(
            client._session.put,
            app_secret=config.app_secret,
            path=path,
            method="PUT",
        )

    def test_deactivate_activity(self, promotion_resources):
        resources, client, config = promotion_resources
        path = promotion_deactivate_path(self.ACTIVITY_ID)
        result = resources.promotion.deactivate(activity_id=self.ACTIVITY_ID)
        assert result["status"] == "EXPIRED"
        _assert_signed_request(
            client._session.post,
            app_secret=config.app_secret,
            path=path,
            method="POST",
        )

    def test_create_activity_blocked_on_production(self, production_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(production_config)
        client._session = MagicMock()
        from juli_backend.integrations.tiktok.resources.promotion import PromotionResource

        resource = PromotionResource(client)
        with pytest.raises(TransportGuardError):
            resource.create_activity(body={"title": "blocked"})
        client._session.post.assert_not_called()


class TestTikTokCodeAndHttpStatus:
    PRODUCT_ID = "1736363193934775939"

    def test_nonzero_tiktok_code_raises_typed_error(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.inventory._client
        client._session = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {
            "code": 100004,
            "message": "Product not found",
            "request_id": "req-404",
        }
        resp.raise_for_status = MagicMock()
        client._session.post.return_value = resp

        with pytest.raises(ResourceNotFoundError):
            resources.inventory.update(
                product_id=self.PRODUCT_ID,
                sku_id="1736404513645233795",
                quantity=1,
            )

    def test_http_error_propagates(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("500 Server Error")
        client._session.post.return_value = resp

        with pytest.raises(Exception, match="500"):
            resources.products.create(body={"title": "x"})


class TestTechnicalValidationDocumentation:
    def test_handoff_documents_layer2_technical_validation_bar(self):
        from pathlib import Path

        handoff = (
            Path(__file__).resolve().parents[2]
            / "docs/handoffs/phase-2-tiktok-implementation.md"
        )
        text = handoff.read_text(encoding="utf-8")
        assert "Layer 2" in text
        assert "technical correctness" in text.lower() or "technical validation" in text.lower()

    def test_contract_collection_inventory_update_verified(self):
        from pathlib import Path

        contracts = (
            Path(__file__).resolve().parents[2]
            / "docs/integrations/tiktok_api/contract-collection.md"
        )
        text = contracts.read_text(encoding="utf-8")
        assert "POST /product/202309/products/{product_id}/inventory/update" in text
        assert "POST /product/202309/products" in text
        assert "POST /supply_chain/202309/packages/sync" in text
        assert "GET /promotion/202309/activities/{activity_id}" in text
        assert "POST /promotion/202309/activities" in text

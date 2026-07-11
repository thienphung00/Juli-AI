"""Layer 2 sandbox write resources — fixture-backed validation via SandboxWriteClientFactory (#301)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
)
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_CREATE_PATH,
    fulfillment_batch_ship_path,
    fulfillment_package_ship_path,
    product_inventory_update_path,
)
from juli_backend.integrations.tiktok.resources.inventory import InventoryResource
from juli_backend.integrations.tiktok.exceptions import TikTokAPIError, TransportGuardError
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    SandboxWriteClientFactory,
    SandboxWriteResources,
)
from juli_backend.integrations.tiktok.resources.fulfillment_writes import (
    FulfillmentWriteResource,
)
from juli_backend.integrations.tiktok.resources.product_writes import ProductWriteResource

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/samples"


def _load_fixture(name: str) -> dict:
    return json.loads((SAMPLES_DIR / name).read_text(encoding="utf-8"))


def _mock_http_response(data: dict, *, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


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
def sandbox_resources(sandbox_config: ClientFactoryConfig) -> SandboxWriteResources:
    resources = SandboxWriteClientFactory().create_resources(sandbox_config)
    resources.inventory._client._session = MagicMock()  # noqa: SLF001
    resources.products._client._session = MagicMock()  # noqa: SLF001
    resources.fulfillment._client._session = MagicMock()  # noqa: SLF001
    return resources


class TestSandboxWriteClientFactory:
    def test_create_resources_returns_write_bundle(self, sandbox_config: ClientFactoryConfig):
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        assert isinstance(resources, SandboxWriteResources)
        assert isinstance(resources.inventory, InventoryResource)
        assert isinstance(resources.products, ProductWriteResource)
        assert isinstance(resources.fulfillment, FulfillmentWriteResource)

    def test_production_factory_does_not_expose_write_resources(
        self,
        sandbox_config: ClientFactoryConfig,
    ):
        production = ProductionReadClientFactory().create_resources(
            ClientFactoryConfig(
                app_key=sandbox_config.app_key,
                app_secret=sandbox_config.app_secret,
                access_token=sandbox_config.access_token,
                merchant_auth_id=PRODUCTION_AUTH_ID,
                shop_cipher=sandbox_config.shop_cipher,
            )
        )
        assert not hasattr(production, "inventory")
        assert not hasattr(production, "products_write")
        assert not hasattr(production, "fulfillment")
        assert not hasattr(ProductionReadClientFactory, "create_write_resources")


class TestInventoryUpdateWriteResource:
    def test_inventory_update_signing_status_code_and_parsing(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        fixture = _load_fixture("inventory-update-response.json")
        envelope = fixture["response"]
        client = sandbox_resources.inventory._client  # noqa: SLF001
        client._session.post.return_value = _mock_http_response(envelope)

        with patch(
            "juli_backend.integrations.tiktok.client.sign_request",
            return_value="deadbeef" * 8,
        ) as mock_sign:
            result = sandbox_resources.inventory.update(
                product_id="1736363193934775939",
                sku_id="1736404513645233795",
                warehouse_id="7657265511696664340",
                quantity=15,
            )

        mock_sign.assert_called_once()
        call_kwargs = client._session.post.call_args.kwargs
        assert "sign=deadbeef" in str(call_kwargs.get("params", {})) or call_kwargs["params"]["sign"]
        assert client._session.post.call_args[0][0].endswith(
            product_inventory_update_path("1736363193934775939")
        )
        assert result == {}

    def test_sparse_sandbox_business_failure_still_parses_tiktok_code(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        client = sandbox_resources.inventory._client  # noqa: SLF001
        client._session.post.return_value = _mock_http_response(
            {
                "code": 12052048,
                "message": "Product not found in sandbox",
                "data": {},
                "request_id": "req-sparse-fail",
            }
        )

        with pytest.raises(TikTokAPIError) as exc_info:
            sandbox_resources.inventory.update(
                product_id="1736363193934775939",
                sku_id="sku-1",
                warehouse_id="wh-1",
                quantity=1,
            )

        assert exc_info.value.code == 12052048
        assert exc_info.value.request_id == "req-sparse-fail"


class TestProductWriteResource:
    def test_create_product_matches_verified_contract(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        fixture = _load_fixture("product-create-response.json")
        envelope = fixture["response"]
        client = sandbox_resources.products._client  # noqa: SLF001
        client._session.post.return_value = _mock_http_response(envelope)

        body = {
            "title": "Premium Stainless Steel Water Bottle 750ml",
            "category_id": "605254",
            "skus": [{"seller_sku": "water-bottle-100ml", "inventory": [{"quantity": 100}]}],
        }
        with patch(
            "juli_backend.integrations.tiktok.client.sign_request",
            return_value="cafebabe" * 8,
        ) as mock_sign:
            result = sandbox_resources.products.create(body)

        mock_sign.assert_called_once()
        assert client._session.post.call_args[0][0].endswith(PRODUCT_CREATE_PATH)
        assert result["product_id"] == envelope["data"]["product_id"]
        assert result["skus"][0]["seller_sku"] == "water-bottle-100ml"

    def test_edit_product_uses_put_and_guard(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        client = sandbox_resources.products._client  # noqa: SLF001
        client._session.put = MagicMock(
            return_value=_mock_http_response({"code": 0, "data": {}, "message": "Success"})
        )

        sandbox_resources.products.edit("1736405947247986307", {"title": "Updated title"})

        assert client._session.put.called


class TestFulfillmentWriteResource:
    def test_ship_package_posts_to_verified_path(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        client = sandbox_resources.fulfillment._client  # noqa: SLF001
        client._session.post.return_value = _mock_http_response(
            {"code": 0, "data": {}, "message": "Success"}
        )

        with patch(
            "juli_backend.integrations.tiktok.client.sign_request",
            return_value="ship-sign" * 8,
        ):
            sandbox_resources.fulfillment.ship_package("1153486604836964618", body={})

        path = fulfillment_package_ship_path("1153486604836964618")
        assert client._session.post.call_args[0][0].endswith(path)

    def test_batch_ship_packages_posts_to_verified_path(
        self,
        sandbox_resources: SandboxWriteResources,
    ):
        client = sandbox_resources.fulfillment._client  # noqa: SLF001
        client._session.post.return_value = _mock_http_response(
            {"code": 0, "data": {}, "message": "Success"}
        )

        sandbox_resources.fulfillment.batch_ship_packages({"packages": []})

        assert client._session.post.call_args[0][0].endswith(fulfillment_batch_ship_path())


class TestProductionWriteIsolation:
    def test_production_client_rejects_inventory_update_before_signing(
        self,
        sandbox_config: ClientFactoryConfig,
    ):
        client = ProductionReadClientFactory().create(
            ClientFactoryConfig(
                app_key=sandbox_config.app_key,
                app_secret=sandbox_config.app_secret,
                access_token=sandbox_config.access_token,
                merchant_auth_id=PRODUCTION_AUTH_ID,
                shop_cipher=sandbox_config.shop_cipher,
            )
        )
        client._session = MagicMock()

        with pytest.raises(TransportGuardError):
            client.post(product_inventory_update_path("1736363193934775939"), body={})

        client._session.post.assert_not_called()

    def test_production_client_rejects_product_create_before_signing(
        self,
        sandbox_config: ClientFactoryConfig,
    ):
        client = ProductionReadClientFactory().create(
            ClientFactoryConfig(
                app_key=sandbox_config.app_key,
                app_secret=sandbox_config.app_secret,
                access_token=sandbox_config.access_token,
                merchant_auth_id=PRODUCTION_AUTH_ID,
                shop_cipher=sandbox_config.shop_cipher,
            )
        )
        client._session = MagicMock()

        with pytest.raises(TransportGuardError):
            client.post(PRODUCT_CREATE_PATH, body={"title": "blocked"})

        client._session.post.assert_not_called()

    def test_production_client_rejects_fulfillment_ship_before_signing(
        self,
        sandbox_config: ClientFactoryConfig,
    ):
        client = ProductionReadClientFactory().create(
            ClientFactoryConfig(
                app_key=sandbox_config.app_key,
                app_secret=sandbox_config.app_secret,
                access_token=sandbox_config.access_token,
                merchant_auth_id=PRODUCTION_AUTH_ID,
                shop_cipher=sandbox_config.shop_cipher,
            )
        )
        client._session = MagicMock()

        with pytest.raises(TransportGuardError):
            client.post(
                fulfillment_package_ship_path("1153486604836964618"),
                body={},
            )

        client._session.post.assert_not_called()


def test_technical_validation_documented_in_handoff():
    handoff = (
        Path(__file__).resolve().parents[2]
        / "docs/handoffs/phase-2-tiktok-implementation.md"
    )
    text = handoff.read_text(encoding="utf-8")
    assert "Layer 2 technical validation (#301)" in text
    assert "inventory-update-response.json" in text
    assert "SandboxWriteClientFactory.create_resources()" in text


def test_production_factory_does_not_expose_write_resources(sandbox_config: ClientFactoryConfig):
    """Acceptance: write resources unreachable from production factory."""
    production = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=sandbox_config.app_key,
            app_secret=sandbox_config.app_secret,
            access_token=sandbox_config.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=sandbox_config.shop_cipher,
        )
    )
    assert not hasattr(production, "inventory")
    assert not hasattr(production, "fulfillment")
    assert not hasattr(ProductionReadClientFactory, "create_write_resources")


def test_create_product_matches_verified_contract(sandbox_resources: SandboxWriteResources):
    """Acceptance: Layer 0 create-product contract parsing."""
    fixture = _load_fixture("product-create-response.json")
    envelope = fixture["response"]
    client = sandbox_resources.products._client  # noqa: SLF001
    client._session.post.return_value = _mock_http_response(envelope)

    result = sandbox_resources.products.create({"title": "Premium Stainless Steel Water Bottle 750ml"})

    assert result["product_id"] == envelope["data"]["product_id"]

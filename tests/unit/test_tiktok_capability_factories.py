"""Unit tests for P2-A1 capability-separated TikTok client factories and guards."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.integrations.catalog.domain.integrations.tiktok.capabilities import (
    PRODUCTION_AUTH_ID,
    PRODUCTION_READ_GET_EXACT,
    PRODUCTION_READ_POST_PATHS,
    SANDBOX_AUTH_ID,
    path_contains_write_marker,
)
from backend.integrations.catalog.domain.integrations.tiktok.constants import (
    AUTHORIZED_SHOPS_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    product_detail_path,
    product_inventory_update_path,
)
from backend.integrations.catalog.domain.integrations.tiktok.exceptions import TransportGuardError
from backend.integrations.catalog.domain.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    SandboxWriteClientFactory,
)
from backend.integrations.catalog.domain.integrations.tiktok.guards import redact_shop_identifier
from backend.integrations.catalog.domain.integrations.tiktok.resources.inventory import InventoryResource


@pytest.fixture
def factory_config() -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="app-key",
        app_secret="app-secret",
        access_token="access-token",
        merchant_auth_id=PRODUCTION_AUTH_ID,
        shop_cipher="ROW_cipher1234567890",
    )


@pytest.fixture
def sandbox_factory_config() -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="app-key",
        app_secret="app-secret",
        access_token="access-token",
        merchant_auth_id=SANDBOX_AUTH_ID,
        shop_cipher="ROW_sandboxcipher12",
    )


class TestProductionReadClientFactory:
    def test_rejects_non_fujiwa_merchant_auth_id(self, factory_config: ClientFactoryConfig):
        with pytest.raises(ValueError, match="Fujiwa"):
            ProductionReadClientFactory().create(
                ClientFactoryConfig(
                    app_key=factory_config.app_key,
                    app_secret=factory_config.app_secret,
                    access_token=factory_config.access_token,
                    merchant_auth_id=SANDBOX_AUTH_ID,
                    shop_cipher=factory_config.shop_cipher,
                )
            )

    def test_allows_production_read_get(self, factory_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"shops": []}}
        mock_resp.raise_for_status = MagicMock()
        client._session.get.return_value = mock_resp

        client.get(AUTHORIZED_SHOPS_PATH)

        assert client._session.get.called

    def test_allows_production_read_post_search(self, factory_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"orders": []}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post(ORDER_SEARCH_PATH, body={})

        assert client._session.post.called

    def test_rejects_write_path_before_signing(self, factory_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()

        with pytest.raises(TransportGuardError, match="Production-read transport rejected"):
            client.post(product_inventory_update_path("1736363193934775939"), body={})

        client._session.post.assert_not_called()

    def test_fujiwa_inventory_resource_update_blocked(self, factory_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()
        resource = InventoryResource(client)

        with pytest.raises(TransportGuardError):
            resource.update(
                product_id="1736363193934775939",
                sku_id="1736404513645233795",
                warehouse_id="7657265511696664340",
                quantity=10,
            )

        client._session.post.assert_not_called()

    @patch("backend.integrations.catalog.domain.integrations.tiktok.guarded_client.log_outbound_request")
    def test_logs_outbound_metadata_without_secrets(
        self,
        mock_log: MagicMock,
        factory_config: ClientFactoryConfig,
    ):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"orders": []}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post(ORDER_SEARCH_PATH, body={})

        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["capability"].value == "production_read"
        assert kwargs["merchant_auth_id"] == PRODUCTION_AUTH_ID
        assert kwargs["method"] == "POST"
        assert kwargs["path"] == ORDER_SEARCH_PATH
        assert kwargs["shop_cipher"] == factory_config.shop_cipher
        assert "access-token" not in str(mock_log.call_args)


class TestSandboxWriteClientFactory:
    def test_rejects_fujiwa_merchant_auth_id(self, sandbox_factory_config: ClientFactoryConfig):
        with pytest.raises(ValueError, match="SANDBOX_VN"):
            SandboxWriteClientFactory().create(
                ClientFactoryConfig(
                    app_key=sandbox_factory_config.app_key,
                    app_secret=sandbox_factory_config.app_secret,
                    access_token=sandbox_factory_config.access_token,
                    merchant_auth_id=PRODUCTION_AUTH_ID,
                    shop_cipher=sandbox_factory_config.shop_cipher,
                )
            )

    def test_allows_sandbox_inventory_update(self, sandbox_factory_config: ClientFactoryConfig):
        client = SandboxWriteClientFactory().create(sandbox_factory_config)
        client._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post(product_inventory_update_path("1736363193934775939"), body={"skus": []})

        assert client._session.post.called

    def test_rejects_production_read_search_on_sandbox_client(
        self,
        sandbox_factory_config: ClientFactoryConfig,
    ):
        client = SandboxWriteClientFactory().create(sandbox_factory_config)
        client._session = MagicMock()

        with pytest.raises(TransportGuardError, match="Sandbox write-validation transport rejected"):
            client.post(ORDER_SEARCH_PATH, body={})

        client._session.post.assert_not_called()


class TestProductionAllowlistStaticChecks:
  def test_production_post_allowlist_has_no_write_markers(self):
      for path in PRODUCTION_READ_POST_PATHS:
          assert not path_contains_write_marker(path), path

  def test_production_get_allowlist_has_no_write_markers(self):
      for path in PRODUCTION_READ_GET_EXACT:
          assert not path_contains_write_marker(path), path

  def test_inventory_search_allowed_but_update_blocked(self, factory_config: ClientFactoryConfig):
      client = ProductionReadClientFactory().create(factory_config)
      client._session = MagicMock()
      mock_resp = MagicMock()
      mock_resp.json.return_value = {"code": 0, "data": {}}
      mock_resp.raise_for_status = MagicMock()
      client._session.post.return_value = mock_resp

      client.post(INVENTORY_SEARCH_PATH, body={})

      with pytest.raises(TransportGuardError):
          client.post(product_inventory_update_path("123"), body={})


class TestRedactShopIdentifier:
    def test_redacts_cipher(self):
        assert redact_shop_identifier("ROW_cipher1234567890") == "ROW_...7890"

    def test_handles_missing_cipher(self):
        assert redact_shop_identifier(None) == "none"


class TestMerchantAuthSeparation:
    def test_fujiwa_auth_id_absent_from_sandbox_factory_constant(self):
        assert PRODUCTION_AUTH_ID != SANDBOX_AUTH_ID

    def test_product_detail_allowed_on_production(self, factory_config: ClientFactoryConfig):
        client = ProductionReadClientFactory().create(factory_config)
        client._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {}}
        mock_resp.raise_for_status = MagicMock()
        client._session.get.return_value = mock_resp

        client.get(product_detail_path("1736363193934775939"))

        assert client._session.get.called

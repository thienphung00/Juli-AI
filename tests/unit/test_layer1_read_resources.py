"""Layer 1 read resources — fixture-backed parsing via ProductionReadClientFactory (#297)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.capabilities import PRODUCTION_AUTH_ID
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    SandboxWriteClientFactory,
)
from juli_backend.integrations.tiktok.resources.authorization import AuthorizationResource
from juli_backend.integrations.tiktok.resources.orders import OrdersResource
from juli_backend.integrations.tiktok.resources.products import ProductsResource
from juli_backend.integrations.tiktok.resources.returns import ReturnsResource

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/samples"

LAYER1_RESOURCE_FIXTURES = [
  ("authorized-shops-response.json", "list_shops", AuthorizationResource, {}),
  ("orders-search-response.json", "search", OrdersResource, {}),
  (
      "orders-detail-response.json",
      "get_details",
      OrdersResource,
      {"order_ids": ["577958834469439754"]},
  ),
  ("products-search-response.json", "search", ProductsResource, {}),
  ("products-detail-response.json", "get_details", ProductsResource, {"product_id": None}),
  ("returns-search-response.json", "search_returns", ReturnsResource, {}),
  ("cancellations-search-response.json", "search_cancellations", ReturnsResource, {}),
]


def _load_fixture(name: str) -> dict:
    return json.loads((SAMPLES_DIR / name).read_text(encoding="utf-8"))


def _mock_tiktok_response(data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"code": 0, "data": data, "message": "Success"}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


@pytest.fixture
def production_client():
    client = ProductionReadClientFactory().create(
        ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher="ROW_cipher1234567890",
        )
    )
    client._session = MagicMock()
    return client


def _call_resource(
    resource_cls: type,
    method_name: str,
    client,
    *,
    product_id: str | None = None,
    order_ids: list[str] | None = None,
):
    resource = resource_cls(client)
    method = getattr(resource, method_name)
    if product_id is not None:
        return method(product_id)
    if order_ids is not None:
        return method(order_ids)
    return method()


@pytest.mark.parametrize(
    ("fixture_name", "method_name", "resource_cls", "kwargs"),
    LAYER1_RESOURCE_FIXTURES,
    ids=[
        "authorized-shops",
        "orders-search",
        "orders-detail",
        "products-search",
        "products-detail",
        "returns-search",
        "cancellations-search",
    ],
)
def test_each_resource_matches_sanitized_fixture_schema(
    production_client,
    fixture_name: str,
    method_name: str,
    resource_cls: type,
    kwargs: dict,
):
    fixture = _load_fixture(fixture_name)
    data = fixture["response"]["data"]
    if kwargs.get("product_id") is None and method_name == "get_details" and resource_cls is ProductsResource:
        kwargs = {"product_id": data["id"]}

    if method_name in {"search", "search_returns", "search_cancellations"}:
        production_client._session.post.return_value = _mock_tiktok_response(data)
    else:
        production_client._session.get.return_value = _mock_tiktok_response(data)

    result = _call_resource(resource_cls, method_name, production_client, **kwargs)

    if "shops" in data:
        assert result["shops"][0]["id"] == data["shops"][0]["id"]
    elif "orders" in data:
        assert result["orders"][0]["id"] == data["orders"][0]["id"]
    elif "products" in data:
        assert result["products"][0]["id"] == data["products"][0]["id"]
    elif "return_orders" in data:
        assert result["return_orders"][0]["return_id"] == data["return_orders"][0]["return_id"]
    elif "cancellations" in data:
        assert result["cancellations"][0]["cancel_id"] == data["cancellations"][0]["cancel_id"]
    else:
        assert result["id"] == data["id"]


def test_fujiwa_production_read_factory_only():
    resources = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher="ROW_cipher1234567890",
        )
    )
    assert isinstance(resources.authorization, AuthorizationResource)
    assert isinstance(resources.orders, OrdersResource)
    assert isinstance(resources.products, ProductsResource)
    assert isinstance(resources.returns, ReturnsResource)
    assert hasattr(SandboxWriteClientFactory(), "create_resources")
    assert not hasattr(ProductionReadClientFactory(), "create_write_resources")


def test_one_pytest_per_resource_with_fixture_backed_parsing():
    assert len(LAYER1_RESOURCE_FIXTURES) == 7

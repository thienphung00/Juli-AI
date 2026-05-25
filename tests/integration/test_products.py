"""Integration tests for the Products resource against a mock HTTP server."""

from __future__ import annotations

import responses

from src.integrations.kiotviet.client import KiotVietClient
from src.integrations.kiotviet.resources.products import ProductsResource
from tests.mocks.kiotviet_responses import (
    ATTRIBUTES_RESPONSE,
    DELETE_SUCCESS_RESPONSE,
    INVENTORY_LIST_RESPONSE,
    PRODUCT_ITEM,
    PRODUCTS_LIST_RESPONSE,
    PRODUCTS_PAGINATED_PAGE_1,
    PRODUCTS_PAGINATED_PAGE_2,
)

BASE = "https://public.kiotapi.com"


class TestProductsList:

    @responses.activate
    def test_list_default(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        products = ProductsResource(client)
        result = products.list()
        assert result["total"] == 1
        assert result["data"][0]["code"] == "SP001"

    @responses.activate
    def test_list_with_filters(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        products = ProductsResource(client)
        result = products.list(category_id=1, is_active=True, include_inventory=True)
        assert result["total"] == 1

        qs = responses.calls[0].request.params
        assert qs["categoryId"] == "1"
        assert qs["isActive"] == "True"
        assert qs["includeInventory"] == "True"

    @responses.activate
    def test_list_all_paginates(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_PAGINATED_PAGE_1, status=200)
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_PAGINATED_PAGE_2, status=200)

        products = ProductsResource(client)
        result = products.list_all()
        assert len(result) == 150


class TestProductsCRUD:

    @responses.activate
    def test_get_by_id(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products/12345", json=PRODUCT_ITEM, status=200)

        products = ProductsResource(client)
        result = products.get_by_id(12345)
        assert result["id"] == 12345

    @responses.activate
    def test_get_by_code(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products/code/SP001", json=PRODUCT_ITEM, status=200)

        products = ProductsResource(client)
        result = products.get_by_code("SP001")
        assert result["code"] == "SP001"

    @responses.activate
    def test_create(self, client: KiotVietClient) -> None:
        created = {**PRODUCT_ITEM, "id": 99999}
        responses.add(responses.POST, f"{BASE}/products", json=created, status=200)

        products = ProductsResource(client)
        result = products.create({"name": "New Product", "basePrice": 100000})
        assert result["id"] == 99999

    @responses.activate
    def test_update(self, client: KiotVietClient) -> None:
        updated = {**PRODUCT_ITEM, "name": "Updated Name"}
        responses.add(responses.PUT, f"{BASE}/products/12345", json=updated, status=200)

        products = ProductsResource(client)
        result = products.update(12345, {"name": "Updated Name"})
        assert result["name"] == "Updated Name"

    @responses.activate
    def test_delete(self, client: KiotVietClient) -> None:
        responses.add(
            responses.DELETE,
            f"{BASE}/products/12345",
            json=DELETE_SUCCESS_RESPONSE,
            status=200,
        )

        products = ProductsResource(client)
        result = products.delete(12345)
        assert "message" in result


class TestProductsBatch:

    @responses.activate
    def test_batch_create(self, client: KiotVietClient) -> None:
        resp = {"data": [{"id": 1}, {"id": 2}]}
        responses.add(responses.POST, f"{BASE}/listaddproducts", json=resp, status=200)

        products = ProductsResource(client)
        result = products.batch_create([{"name": "A"}, {"name": "B"}])
        assert "data" in result

    @responses.activate
    def test_batch_update(self, client: KiotVietClient) -> None:
        resp = {"data": [{"id": 1, "name": "Updated"}]}
        responses.add(responses.PUT, f"{BASE}/listupdatedproducts", json=resp, status=200)

        products = ProductsResource(client)
        result = products.batch_update([{"id": 1, "name": "Updated"}])
        assert "data" in result


class TestProductsAttributes:

    @responses.activate
    def test_get_attributes(self, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/attributes/allwithdistinctvalue",
            json=ATTRIBUTES_RESPONSE,
            status=200,
        )

        products = ProductsResource(client)
        result = products.get_attributes()
        assert result[0]["name"] == "Color"


class TestProductsInventory:

    @responses.activate
    def test_get_inventory(self, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/productOnHands",
            json=INVENTORY_LIST_RESPONSE,
            status=200,
        )

        products = ProductsResource(client)
        result = products.get_inventory(branch_ids=[1])
        assert result["total"] == 1

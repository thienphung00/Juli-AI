"""Integration tests for the Customers resource against a mock HTTP server."""

from __future__ import annotations

import responses

from src.integrations.kiotviet.client import KiotVietClient
from src.integrations.kiotviet.resources.customers import CustomersResource
from tests.mocks.kiotviet_responses import (
    CUSTOMER_GROUPS_RESPONSE,
    CUSTOMER_ITEM,
    CUSTOMERS_LIST_RESPONSE,
    DELETE_SUCCESS_RESPONSE,
)

BASE = "https://public.kiotapi.com"


class TestCustomersList:

    @responses.activate
    def test_list_default(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/customers", json=CUSTOMERS_LIST_RESPONSE, status=200)

        customers = CustomersResource(client)
        result = customers.list()
        assert result["total"] == 1
        assert result["data"][0]["code"] == "KH001"

    @responses.activate
    def test_list_with_filters(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/customers", json=CUSTOMERS_LIST_RESPONSE, status=200)

        customers = CustomersResource(client)
        result = customers.list(
            name="Customer",
            contact_number="0901234567",
            include_customer_group=True,
        )
        assert result["total"] == 1

        qs = responses.calls[0].request.params
        assert qs["name"] == "Customer"
        assert qs["contactNumber"] == "0901234567"
        assert qs["includeCustomerGroup"] == "True"

    @responses.activate
    def test_list_all(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/customers", json=CUSTOMERS_LIST_RESPONSE, status=200)

        customers = CustomersResource(client)
        result = customers.list_all()
        assert len(result) == 1


class TestCustomersCRUD:

    @responses.activate
    def test_get_by_id(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/customers/200", json=CUSTOMER_ITEM, status=200)

        customers = CustomersResource(client)
        result = customers.get_by_id(200)
        assert result["id"] == 200

    @responses.activate
    def test_get_by_code(self, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/customers/code/KH001",
            json=CUSTOMER_ITEM,
            status=200,
        )

        customers = CustomersResource(client)
        result = customers.get_by_code("KH001")
        assert result["code"] == "KH001"

    @responses.activate
    def test_create(self, client: KiotVietClient) -> None:
        created = {**CUSTOMER_ITEM, "id": 999}
        responses.add(responses.POST, f"{BASE}/customers", json=created, status=200)

        customers = CustomersResource(client)
        result = customers.create({"name": "New Customer", "contactNumber": "0999999999"})
        assert result["id"] == 999

    @responses.activate
    def test_update(self, client: KiotVietClient) -> None:
        updated = {**CUSTOMER_ITEM, "name": "Updated Customer"}
        responses.add(responses.PUT, f"{BASE}/customers/200", json=updated, status=200)

        customers = CustomersResource(client)
        result = customers.update(200, {"name": "Updated Customer"})
        assert result["name"] == "Updated Customer"

    @responses.activate
    def test_delete(self, client: KiotVietClient) -> None:
        responses.add(
            responses.DELETE,
            f"{BASE}/customers/200",
            json=DELETE_SUCCESS_RESPONSE,
            status=200,
        )

        customers = CustomersResource(client)
        result = customers.delete(200)
        assert "message" in result


class TestCustomerGroups:

    @responses.activate
    def test_list_groups(self, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/customergroups",
            json=CUSTOMER_GROUPS_RESPONSE,
            status=200,
        )

        customers = CustomersResource(client)
        result = customers.list_groups()
        assert result["total"] == 1
        assert result["data"][0]["name"] == "VIP"

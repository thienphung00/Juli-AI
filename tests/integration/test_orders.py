"""Integration tests for the Orders resource against a mock HTTP server."""

from __future__ import annotations

import responses

from src.integrations.kiotviet.client import KiotVietClient
from src.integrations.kiotviet.resources.orders import OrdersResource
from tests.mocks.kiotviet_responses import ORDER_ITEM, ORDERS_LIST_RESPONSE

BASE = "https://public.kiotapi.com"


class TestOrdersList:

    @responses.activate
    def test_list_default(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/orders", json=ORDERS_LIST_RESPONSE, status=200)

        orders = OrdersResource(client)
        result = orders.list()
        assert result["total"] == 1
        assert result["data"][0]["code"] == "DH000001"

    @responses.activate
    def test_list_with_filters(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/orders", json=ORDERS_LIST_RESPONSE, status=200)

        orders = OrdersResource(client)
        result = orders.list(
            branch_ids=[1, 2],
            include_payment=True,
            include_order_delivery=True,
            status=[1],
        )
        assert result["total"] == 1

        qs = responses.calls[0].request.params
        assert qs["branchIds"] == "1,2"
        assert qs["includePayment"] == "True"
        assert qs["includeOrderDelivery"] == "True"

    @responses.activate
    def test_list_all(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/orders", json=ORDERS_LIST_RESPONSE, status=200)

        orders = OrdersResource(client)
        result = orders.list_all()
        assert len(result) == 1


class TestOrdersCRUD:

    @responses.activate
    def test_get_by_id(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/orders/1001", json=ORDER_ITEM, status=200)

        orders = OrdersResource(client)
        result = orders.get_by_id(1001)
        assert result["id"] == 1001

    @responses.activate
    def test_get_by_code(self, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/orders/code/DH000001",
            json=ORDER_ITEM,
            status=200,
        )

        orders = OrdersResource(client)
        result = orders.get_by_code("DH000001")
        assert result["code"] == "DH000001"

    @responses.activate
    def test_create(self, client: KiotVietClient) -> None:
        created = {**ORDER_ITEM, "id": 2001}
        responses.add(responses.POST, f"{BASE}/orders", json=created, status=200)

        orders = OrdersResource(client)
        result = orders.create({
            "branchId": 1,
            "orderDetails": [{"productId": 12345, "quantity": 1, "price": 250000}],
        })
        assert result["id"] == 2001

    @responses.activate
    def test_update(self, client: KiotVietClient) -> None:
        updated = {**ORDER_ITEM, "description": "Updated note"}
        responses.add(responses.PUT, f"{BASE}/orders/1001", json=updated, status=200)

        orders = OrdersResource(client)
        result = orders.update(1001, {"description": "Updated note"})
        assert result["description"] == "Updated note"

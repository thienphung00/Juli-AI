"""Integration tests for the Inventory resource against a mock HTTP server."""

from __future__ import annotations

import responses

from src.integrations.kiotviet.client import KiotVietClient
from src.integrations.kiotviet.resources.inventory import InventoryResource
from tests.mocks.kiotviet_responses import INVENTORY_LIST_RESPONSE

BASE = "https://public.kiotapi.com"


class TestInventoryList:

    @responses.activate
    def test_list_default(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/productOnHands", json=INVENTORY_LIST_RESPONSE, status=200)

        inv = InventoryResource(client)
        result = inv.list()
        assert result["total"] == 1
        assert result["data"][0]["code"] == "SP001"

    @responses.activate
    def test_list_with_branch_filter(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/productOnHands", json=INVENTORY_LIST_RESPONSE, status=200)

        inv = InventoryResource(client)
        result = inv.list(branch_ids=[1, 2])
        assert result["total"] == 1

        qs = responses.calls[0].request.params
        assert qs["branchIds"] == "1,2"

    @responses.activate
    def test_list_all(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/productOnHands", json=INVENTORY_LIST_RESPONSE, status=200)

        inv = InventoryResource(client)
        result = inv.list_all()
        assert len(result) == 1


class TestInventoryHelpers:

    @responses.activate
    def test_get_by_branch(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/productOnHands", json=INVENTORY_LIST_RESPONSE, status=200)

        inv = InventoryResource(client)
        result = inv.get_by_branch(1)
        assert len(result) == 1

    @responses.activate
    def test_sync(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/productOnHands", json=INVENTORY_LIST_RESPONSE, status=200)

        inv = InventoryResource(client)
        result = inv.sync("2024-01-15T00:00:00", branch_ids=[1])
        assert len(result) == 1

        qs = responses.calls[0].request.params
        assert qs["lastModifiedFrom"] == "2024-01-15T00:00:00"
        assert qs["branchIds"] == "1"

"""Unit tests for the KiotVietClient — retry logic, pagination, error mapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from src.integrations.kiotviet.client import KiotVietClient
from src.integrations.kiotviet.exceptions import (
    KiotVietError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from tests.mocks.kiotviet_responses import (
    ERROR_400_RESPONSE,
    ERROR_404_RESPONSE,
    ERROR_429_RESPONSE,
    ERROR_500_RESPONSE,
    PRODUCTS_LIST_RESPONSE,
    PRODUCTS_PAGINATED_PAGE_1,
    PRODUCTS_PAGINATED_PAGE_2,
)

BASE = "https://public.kiotapi.com"


class TestClientBasicRequests:

    @responses.activate
    def test_get_success(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        result = client.get("products")
        assert result["total"] == 1
        assert result["data"][0]["id"] == 12345

    @responses.activate
    def test_post_success(self, client: KiotVietClient) -> None:
        body = {"id": 99, "name": "New Product"}
        responses.add(responses.POST, f"{BASE}/products", json=body, status=200)

        result = client.post("products", json={"name": "New Product"})
        assert result["id"] == 99

    @responses.activate
    def test_put_success(self, client: KiotVietClient) -> None:
        body = {"id": 12345, "name": "Updated"}
        responses.add(responses.PUT, f"{BASE}/products/12345", json=body, status=200)

        result = client.put("products/12345", json={"name": "Updated"})
        assert result["name"] == "Updated"

    @responses.activate
    def test_delete_success(self, client: KiotVietClient) -> None:
        responses.add(
            responses.DELETE,
            f"{BASE}/products/12345",
            json={"message": "Xóa dữ liệu thành công"},
            status=200,
        )

        result = client.delete("products/12345")
        assert "message" in result


class TestClientErrorHandling:

    @responses.activate
    def test_400_raises_validation_error(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=ERROR_400_RESPONSE, status=400)

        with pytest.raises(ValidationError, match="Invalid request"):
            client.get("products")

    @responses.activate
    def test_404_raises_not_found(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products/999", json=ERROR_404_RESPONSE, status=404)

        with pytest.raises(NotFoundError, match="Resource not found"):
            client.get("products/999")


class TestClientRetry:

    @responses.activate
    @patch("src.integrations.kiotviet.client.time.sleep")
    def test_retries_on_429(self, mock_sleep: MagicMock, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=ERROR_429_RESPONSE, status=429)
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        result = client.get("products")
        assert result["total"] == 1
        mock_sleep.assert_called_once()

    @responses.activate
    @patch("src.integrations.kiotviet.client.time.sleep")
    def test_retries_on_500(self, mock_sleep: MagicMock, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=ERROR_500_RESPONSE, status=500)
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        result = client.get("products")
        assert result["total"] == 1

    @responses.activate
    @patch("src.integrations.kiotviet.client.time.sleep")
    def test_retries_on_401_with_reauth(
        self, mock_sleep: MagicMock, client: KiotVietClient
    ) -> None:
        responses.add(responses.GET, f"{BASE}/products", status=401, json={})
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        result = client.get("products")
        assert result["total"] == 1
        client._token.invalidate.assert_called_once()

    @responses.activate
    @patch("src.integrations.kiotviet.client.time.sleep")
    def test_exhausted_retries_raises(self, mock_sleep: MagicMock) -> None:
        tm = MagicMock()
        tm.access_token = "tok"
        c = KiotVietClient(token_manager=tm, retailer="store", max_retries=2)

        responses.add(responses.GET, f"{BASE}/products", json=ERROR_500_RESPONSE, status=500)
        responses.add(responses.GET, f"{BASE}/products", json=ERROR_500_RESPONSE, status=500)

        with pytest.raises(ServerError):
            c.get("products")

    @responses.activate
    @patch("src.integrations.kiotviet.client.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep: MagicMock, client: KiotVietClient) -> None:
        responses.add(
            responses.GET,
            f"{BASE}/products",
            body=requests.ConnectionError("refused"),
        )
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        result = client.get("products")
        assert result["total"] == 1


class TestClientPagination:

    @responses.activate
    def test_get_all_single_page(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        data = client.get_all("products")
        assert len(data) == 1
        assert data[0]["id"] == 12345

    @responses.activate
    def test_get_all_multi_page(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_PAGINATED_PAGE_1, status=200)
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_PAGINATED_PAGE_2, status=200)

        data = client.get_all("products")
        assert len(data) == 150

    @responses.activate
    def test_iter_pages_yields_records(self, client: KiotVietClient) -> None:
        responses.add(responses.GET, f"{BASE}/products", json=PRODUCTS_LIST_RESPONSE, status=200)

        records = list(client.iter_pages("products"))
        assert len(records) == 1
        assert records[0]["code"] == "SP001"

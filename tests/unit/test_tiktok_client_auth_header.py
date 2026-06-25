"""Access token transport for versioned vs legacy TikTok API paths."""

from unittest.mock import MagicMock

import pytest

from src.modules.catalog.domain.integrations.tiktok.client import (
    TikTokClient,
    uses_header_auth,
)
from src.modules.catalog.domain.integrations.tiktok.constants import (
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
)


@pytest.fixture
def client():
    c = TikTokClient(
        app_key="key",
        app_secret="secret",
        access_token="tok-abc",
        shop_cipher="cipher",
    )
    c._session = MagicMock()
    return c


class TestUsesHeaderAuth:
    def test_versioned_paths_use_header(self):
        assert uses_header_auth(ORDER_SEARCH_PATH) is True
        assert uses_header_auth("/authorization/202309/shops") is True

    def test_legacy_api_paths_use_query_token(self):
        assert uses_header_auth("/api/orders/search") is False
        assert uses_header_auth("/api/v2/token/get") is False


class TestTikTokClientAuthTransport:
    def test_versioned_post_sends_header_not_query_token(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post(ORDER_SEARCH_PATH, body={"order_status": "UNPAID"})

        _, kwargs = client._session.post.call_args
        headers = kwargs["headers"]
        params = kwargs["params"]
        assert headers["x-tts-access-token"] == "tok-abc"
        assert "access_token" not in params

    def test_legacy_post_keeps_query_token(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post("/api/v2/token/get", body={})

        _, kwargs = client._session.post.call_args
        assert "access_token" in kwargs["params"]
        assert kwargs["headers"] == {}

    def test_product_inventory_search_uses_header(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {}}
        mock_resp.raise_for_status = MagicMock()
        client._session.post.return_value = mock_resp

        client.post(INVENTORY_SEARCH_PATH, body={})

        _, kwargs = client._session.post.call_args
        assert kwargs["headers"]["x-tts-access-token"] == "tok-abc"
        assert "access_token" not in kwargs["params"]

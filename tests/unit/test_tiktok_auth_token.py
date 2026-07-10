"""Unit tests for TikTokAuth token exchange HTTP contract."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from juli_backend.integrations.tiktok.auth import (
    DEFAULT_AUTH_BASE_URL,
    TikTokAuth,
)
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET)


class TestTikTokAuthTokenRequest:
    def test_exchange_code_uses_auth_base_url_get(self, tiktok_auth):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "at",
                "refresh_token": "rt",
                "access_token_expire_in": 604800,
                "open_id": "seller_1",
            },
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("juli_backend.integrations.tiktok.auth.requests.get", return_value=mock_resp) as mock_get:
            result = tiktok_auth.exchange_code("auth_code_xyz")

        mock_get.assert_called_once()
        called_url, = mock_get.call_args[0]
        assert called_url == f"{DEFAULT_AUTH_BASE_URL}/api/v2/token/get"
        assert mock_get.call_args.kwargs["params"] == {
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "auth_code": "auth_code_xyz",
            "grant_type": "authorized_code",
        }
        assert result["open_id"] == "seller_1"

    def test_exchange_code_maps_http_error_to_authentication_error(self, tiktok_auth):
        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            side_effect=requests.HTTPError("404 Client Error"),
        ):
            with pytest.raises(AuthenticationError, match="TikTok token request failed"):
                tiktok_auth.exchange_code("bad_code")

    def test_exchange_code_maps_tiktok_error_response(self, tiktok_auth):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 36004004,
            "message": "invalid auth code",
            "request_id": "req-1",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            return_value=mock_resp,
        ):
            with pytest.raises(AuthenticationError) as exc_info:
                tiktok_auth.exchange_code("expired_code")

        assert exc_info.value.code == 36004004

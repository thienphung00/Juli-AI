"""TikTok Shop OAuth 2.0 authentication service.

Handles authorization URL generation, auth-code-to-token exchange,
and token refresh.  Does NOT handle encrypted storage — that is the
responsibility of the persistence layer.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import requests

from src.modules.catalog.domain.integrations.tiktok.exceptions import AuthenticationError, error_from_response

logger = logging.getLogger(__name__)

PARTNER_AUTH_URL = "https://services.tiktokshop.com/open/authorize"


class TikTokAuth:
    """Manages the OAuth 2.0 lifecycle for a TikTok Shop Partner app."""

    def __init__(self, app_key: str, app_secret: str, base_url: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")

    def generate_auth_url(self, redirect_uri: str, state: str) -> str:
        """Build the URL a seller is redirected to for OAuth consent."""
        params = urlencode({
            "app_key": self._app_key,
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"{PARTNER_AUTH_URL}?{params}"

    def exchange_code(self, auth_code: str) -> dict:
        """Exchange an authorization code for access + refresh tokens.

        Raises AuthenticationError when TikTok returns a non-zero code.
        """
        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "auth_code": auth_code,
            "grant_type": "authorized_code",
        }
        return self._token_request("/api/v2/token/get", payload)

    def refresh_access_token(self, refresh_token: str) -> dict:
        """Use a refresh token to obtain a new access + refresh token pair.

        Raises AuthenticationError when the refresh token is expired or invalid.
        """
        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return self._token_request("/api/v2/token/refresh", payload)

    def _token_request(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            if not isinstance(err, AuthenticationError):
                raise AuthenticationError(
                    code=err.code,
                    message=err.message,
                    request_id=err.request_id,
                )
            raise err

        return data.get("data", {})

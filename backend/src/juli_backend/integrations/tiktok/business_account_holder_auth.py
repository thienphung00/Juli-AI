"""TikTok Business Marketing API account-holder OAuth client.

Handles auth_code → token exchange for the TikTok account holder redirect URL
(personal TikTok identity / posts scopes). Uses ``business-api.tiktok.com``, not
the Shop Partner host.
"""

from __future__ import annotations

import logging

import requests

from juli_backend.integrations.tiktok.exceptions import AuthenticationError, error_from_response

logger = logging.getLogger(__name__)

DEFAULT_BUSINESS_API_BASE_URL = "https://business-api.tiktok.com"
ACCESS_TOKEN_PATH = "/open_api/v1.3/oauth2/access_token/"


class TikTokBusinessAccountHolderAuth:
    """OAuth token exchange for TikTok Business account-holder authorization."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = (base_url or DEFAULT_BUSINESS_API_BASE_URL).rstrip("/")

    def exchange_auth_code(self, auth_code: str) -> dict:
        """Exchange a Business OAuth ``auth_code`` for access + refresh tokens."""
        url = f"{self._base_url}{ACCESS_TOKEN_PATH}"
        payload = {
            "app_id": self._app_id,
            "secret": self._app_secret,
            "auth_code": auth_code,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "tiktok_business_account_holder_token_request_failed",
                extra={"path": ACCESS_TOKEN_PATH, "error": str(exc)},
            )
            raise AuthenticationError(
                code=0, message="TikTok Business token request failed"
            ) from exc

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

        token_data = data.get("data", {})
        if not isinstance(token_data, dict):
            raise AuthenticationError(
                code=0, message="TikTok Business token response missing data"
            )
        return token_data

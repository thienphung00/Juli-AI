"""OAuth 2.0 Client Credentials authentication for KiotViet.

Handles token acquisition, proactive renewal, and thread-safe access.
Credentials are read from environment variables by default.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import requests

from .exceptions import AuthenticationError

logger = logging.getLogger(__name__)

TOKEN_URL = "https://id.kiotviet.vn/connect/token"
RENEWAL_BUFFER_SECONDS = 300  # renew 5 min before expiry


class TokenManager:
    """Thread-safe OAuth 2.0 token manager for KiotViet.

    Acquires tokens via Client Credentials and proactively refreshes
    before expiry.  There is no refresh-token flow — we simply
    re-authenticate with the same credentials.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_url: str = TOKEN_URL,
    ) -> None:
        self._client_id = client_id or os.environ["KIOTVIET_CLIENT_ID"]
        self._client_secret = client_secret or os.environ["KIOTVIET_CLIENT_SECRET"]
        self._token_url = token_url

        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._is_token_valid():
            assert self._access_token is not None
            return self._access_token
        return self._refresh()

    def _is_token_valid(self) -> bool:
        return (
            self._access_token is not None
            and time.monotonic() < self._expires_at
        )

    def _refresh(self) -> str:
        with self._lock:
            # Double-check: another thread may have refreshed while we waited
            if self._is_token_valid():
                assert self._access_token is not None
                return self._access_token
            return self._authenticate()

    def _authenticate(self) -> str:
        logger.info("kiotviet_auth_requesting_token")
        try:
            resp = requests.post(
                self._token_url,
                data={
                    "scopes": "PublicApi.Access",
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error("kiotviet_auth_request_failed", exc_info=True)
            raise AuthenticationError(
                f"Token request failed: {exc}",
                status_code=None,
            ) from exc

        if resp.status_code != 200:
            logger.error(
                "kiotviet_auth_bad_status",
                extra={"status": resp.status_code, "body": resp.text[:500]},
            )
            raise AuthenticationError(
                f"Token endpoint returned HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        data: dict[str, Any] = resp.json()
        self._access_token = data["access_token"]
        expires_in: int = data.get("expires_in", 86400)
        self._expires_at = time.monotonic() + expires_in - RENEWAL_BUFFER_SECONDS

        logger.info(
            "kiotviet_auth_token_acquired",
            extra={"expires_in": expires_in},
        )
        return self._access_token

    def invalidate(self) -> None:
        """Force next call to re-authenticate (e.g. after a 401)."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

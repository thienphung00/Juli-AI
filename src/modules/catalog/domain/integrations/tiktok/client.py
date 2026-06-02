"""TikTok Shop Partner API HTTP client.

Handles request signing, common query parameters, error mapping,
and cursor-based pagination.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import requests

from src.modules.catalog.domain.integrations.tiktok.exceptions import error_from_response
from src.modules.catalog.domain.integrations.tiktok.signing import sign_request

logger = logging.getLogger(__name__)


class TikTokClient:
    """Low-level HTTP client for the TikTok Shop Partner API."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        access_token: str,
        base_url: str = "https://open-api.tiktokglobalshop.com",
        shop_cipher: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._shop_cipher = shop_cipher
        self._timeout = timeout
        self._session = requests.Session()

    def get(self, path: str, params: Optional[dict[str, str]] = None) -> dict:
        """Signed GET request. Returns the ``data`` payload."""
        all_params = self._build_params(params)
        all_params["sign"] = sign_request(
            app_secret=self._app_secret,
            path=path,
            params=all_params,
        )

        resp = self._session.get(
            f"{self._base_url}{path}",
            params=all_params,
            timeout=self._timeout,
        )
        return self._handle_response(resp)

    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict:
        """Signed POST request with JSON body. Returns the ``data`` payload."""
        body = body or {}
        body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)

        all_params = self._build_params(params)
        all_params["sign"] = sign_request(
            app_secret=self._app_secret,
            path=path,
            params=all_params,
            body=body_str,
        )

        resp = self._session.post(
            f"{self._base_url}{path}",
            params=all_params,
            json=body,
            timeout=self._timeout,
        )
        return self._handle_response(resp)

    def get_all_pages(
        self,
        path: str,
        body: dict[str, Any],
        items_key: str,
        page_size: int = 50,
    ) -> list[dict]:
        """Auto-paginate a POST endpoint using cursor-based page_token."""
        all_items: list[dict] = []
        page_body = {**body, "page_size": page_size}

        while True:
            data = self.post(path, body=page_body)
            items = data.get(items_key, [])
            all_items.extend(items)

            page_token = data.get("page_token")
            if not page_token:
                break
            page_body["page_token"] = page_token

        return all_items

    def _build_params(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        params: dict[str, str] = {
            "app_key": self._app_key,
            "timestamp": str(int(time.time())),
            "access_token": self._access_token,
        }
        if self._shop_cipher:
            params["shop_cipher"] = self._shop_cipher
        if extra:
            params.update(extra)
        return params

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        resp.raise_for_status()
        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            raise err
        return data.get("data", {})

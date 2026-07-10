"""TikTok Shop Partner API HTTP client.

Handles request signing, common query parameters, error mapping,
and cursor-based pagination.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional, TypeVar, overload

import requests
from pydantic import BaseModel

from juli_backend.integrations.tiktok.exceptions import error_from_response
from juli_backend.integrations.tiktok.schemas import validate_data
from juli_backend.integrations.tiktok.signing import sign_request

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_HEADER = "x-tts-access-token"


def uses_header_auth(path: str) -> bool:
    """Versioned Partner API routes use header token transport, not query param."""
    return not path.startswith("/api/")


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

    @overload
    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: Optional[type[BaseModel]] = None,
    ) -> dict[str, Any] | BaseModel:
        """Signed GET request. Returns the ``data`` payload (optionally validated)."""
        all_params = self._build_params(path, params)
        all_params["sign"] = sign_request(
            app_secret=self._app_secret,
            path=path,
            params=all_params,
        )

        resp = self._session.get(
            f"{self._base_url}{path}",
            params=all_params,
            headers=self._auth_headers(path),
            timeout=self._timeout,
        )
        data = self._handle_response(resp)
        if response_model is not None:
            return validate_data(response_model, data)
        return data

    @overload
    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: Optional[type[BaseModel]] = None,
    ) -> dict[str, Any] | BaseModel:
        """Signed POST request with JSON body. Returns the ``data`` payload."""
        body = body or {}
        body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)

        all_params = self._build_params(path, params)
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
            headers=self._auth_headers(path),
            timeout=self._timeout,
        )
        data = self._handle_response(resp)
        if response_model is not None:
            return validate_data(response_model, data)
        return data

    def get_all_pages(
        self,
        path: str,
        body: dict[str, Any],
        items_key: str,
        page_size: int = 50,
    ) -> list[dict]:
        """Auto-paginate a POST endpoint using ``page_token`` query param.

        Official responses expose the next cursor as ``next_page_token``; legacy
        testing-tool aliases may return ``page_token`` instead.
        """
        all_items: list[dict] = []
        query_params: dict[str, str] = {"page_size": str(page_size)}
        page_body = dict(body)

        while True:
            data = self.post(path, body=page_body, params=query_params)
            if not isinstance(data, dict):
                break
            items = data.get(items_key, [])
            all_items.extend(items)

            next_token = data.get("next_page_token") or data.get("page_token")
            if not next_token:
                break
            query_params = {
                "page_size": str(page_size),
                "page_token": str(next_token),
            }

        return all_items

    def get_all_pages_get(
        self,
        path: str,
        params: dict[str, str],
        items_key: str,
        page_size: int = 50,
    ) -> list[dict]:
        """Auto-paginate a GET endpoint using ``page_token`` query param."""
        all_items: list[dict] = []
        query_params: dict[str, str] = {**params, "page_size": str(page_size)}

        while True:
            data = self.get(path, params=query_params)
            if not isinstance(data, dict):
                break
            items = data.get(items_key, [])
            all_items.extend(items)

            next_token = data.get("next_page_token") or data.get("page_token")
            if not next_token:
                break
            query_params = {**params, "page_size": str(page_size), "page_token": str(next_token)}

        return all_items

    def _build_params(
        self, path: str, extra: Optional[dict[str, str]] = None
    ) -> dict[str, str]:
        params: dict[str, str] = {
            "app_key": self._app_key,
            "timestamp": str(int(time.time())),
        }
        if not uses_header_auth(path):
            params["access_token"] = self._access_token
        if self._shop_cipher:
            params["shop_cipher"] = self._shop_cipher
        if extra:
            params.update(extra)
        return params

    def _auth_headers(self, path: str) -> dict[str, str]:
        if uses_header_auth(path):
            return {_ACCESS_TOKEN_HEADER: self._access_token}
        return {}

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        resp.raise_for_status()
        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            raise err
        return data.get("data", {})

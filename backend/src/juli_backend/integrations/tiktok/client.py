"""TikTok Shop Partner API HTTP client.

Handles request signing, common query parameters, error mapping,
and cursor-based pagination.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, TypeVar, overload

import requests
from pydantic import BaseModel

from juli_backend.integrations.tiktok.exceptions import error_from_response
from juli_backend.integrations.tiktok.schemas import validate_data
from juli_backend.integrations.tiktok.signing import sign_request

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_HEADER = "x-tts-access-token"
# Maximum pages per paginated fetch. Prevents infinite loops if an API endpoint
# echoes the page_token back in its response, creating an unbounded cursor.
# Env-overridable via TIKTOK_MAX_PAGES. A low double-digit cap is appropriate
# since real fetches (with page_size=50) rarely need more than a few pages.
_DEFAULT_MAX_PAGES = 20


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
        shop_cipher: str | None = None,
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
        params: dict[str, str] | None = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        response_model: type[BaseModel] | None = None,
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
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: type[BaseModel] | None = None,
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
            # Send the exact bytes that were signed. Passing json=body lets requests
            # re-serialize with its own separators and key order, so the body TikTok
            # hashes differs from the one we signed and every non-empty body is
            # rejected with code 106001 "the 'sign' query parameter is invalid".
            data=body_str,
            headers=self._json_auth_headers(path),
            timeout=self._timeout,
        )
        data = self._handle_response(resp)
        if response_model is not None:
            return validate_data(response_model, data)
        return data

    def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Signed POST with multipart form data (empty JSON body for signing)."""
        all_params = self._build_params(path, params)
        all_params["sign"] = sign_request(
            app_secret=self._app_secret,
            path=path,
            params=all_params,
            body="",
        )

        resp = self._session.post(
            f"{self._base_url}{path}",
            params=all_params,
            data=data or {},
            files=files,
            headers=self._auth_headers(path),
            timeout=self._timeout,
        )
        return self._handle_response(resp)

    @overload
    def put(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def put(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def put(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any] | BaseModel:
        """Signed PUT request with JSON body. Returns the ``data`` payload."""
        body = body or {}
        body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)

        all_params = self._build_params(path, params)
        all_params["sign"] = sign_request(
            app_secret=self._app_secret,
            path=path,
            params=all_params,
            body=body_str,
        )

        resp = self._session.put(
            f"{self._base_url}{path}",
            params=all_params,
            # See post(): the signed bytes must be sent verbatim.
            data=body_str,
            headers=self._json_auth_headers(path),
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

        Stops early if:
        - Maximum page count is reached (prevents infinite loops on echoed cursors)
        - The returned token equals the sent token (non-advancing cursor detection)
        """
        all_items: list[dict] = []
        query_params: dict[str, str] = {"page_size": str(page_size)}
        page_body = dict(body)
        page_count = 0
        last_token: str | None = None

        max_pages = int(os.getenv("TIKTOK_MAX_PAGES", str(_DEFAULT_MAX_PAGES)))

        while True:
            page_count += 1

            # Guard 1: Maximum page count
            if page_count > max_pages:
                logger.warning(
                    "tiktok_pagination_max_pages_reached",
                    extra={
                        "path": path,
                        "page_count": page_count - 1,
                        "reason": "max_pages_exceeded",
                    },
                )
                break

            data = self.post(path, body=page_body, params=query_params)
            if not isinstance(data, dict):
                break
            items = data.get(items_key, [])
            all_items.extend(items)

            next_token = data.get("next_page_token") or data.get("page_token")
            if not next_token:
                break

            # Guard 2: Non-advancing cursor detection
            if next_token == last_token:
                logger.warning(
                    "tiktok_pagination_non_advancing_cursor",
                    extra={
                        "path": path,
                        "page_count": page_count,
                        "reason": "cursor_not_advancing",
                    },
                )
                break

            last_token = next_token
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
        """Auto-paginate a GET endpoint using ``page_token`` query param.

        Stops early if:
        - Maximum page count is reached (prevents infinite loops on echoed cursors)
        - The returned token equals the sent token (non-advancing cursor detection)
        """
        all_items: list[dict] = []
        query_params: dict[str, str] = {**params, "page_size": str(page_size)}
        page_count = 0
        last_token: str | None = None

        max_pages = int(os.getenv("TIKTOK_MAX_PAGES", str(_DEFAULT_MAX_PAGES)))

        while True:
            page_count += 1

            # Guard 1: Maximum page count
            if page_count > max_pages:
                logger.warning(
                    "tiktok_pagination_max_pages_reached",
                    extra={
                        "path": path,
                        "page_count": page_count - 1,
                        "reason": "max_pages_exceeded",
                    },
                )
                break

            data = self.get(path, params=query_params)
            if not isinstance(data, dict):
                break
            items = data.get(items_key, [])
            all_items.extend(items)

            next_token = data.get("next_page_token") or data.get("page_token")
            if not next_token:
                break

            # Guard 2: Non-advancing cursor detection
            if next_token == last_token:
                logger.warning(
                    "tiktok_pagination_non_advancing_cursor",
                    extra={
                        "path": path,
                        "page_count": page_count,
                        "reason": "cursor_not_advancing",
                    },
                )
                break

            last_token = next_token
            query_params = {**params, "page_size": str(page_size), "page_token": str(next_token)}

        return all_items

    def _build_params(self, path: str, extra: dict[str, str] | None = None) -> dict[str, str]:
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

    def _json_auth_headers(self, path: str) -> dict[str, str]:
        """Auth headers plus an explicit JSON content type.

        Needed because the signed body is sent as raw bytes via ``data=``; requests
        only sets Content-Type automatically for ``json=``.
        """
        headers = self._auth_headers(path)
        headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        resp.raise_for_status()
        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            raise err
        return data.get("data", {})

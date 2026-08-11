"""TikTok Shop Partner API HTTP client.

Handles request signing, common query parameters, error mapping,
and cursor-based pagination.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any, TypeVar, overload

import requests
from pydantic import BaseModel

from juli_backend.integrations.tiktok.exceptions import TikTokAPIError, error_from_response
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

# Enough to carry a Partner API error envelope without flooding logs on an HTML 5xx page.
_ERROR_BODY_LIMIT = 800

# Transient-retry policy. TikTok tunnels application errors over HTTP 500 (#855's
# invalid-sign arrived as a 500), so a status code alone can never justify a retry —
# only the application code in the body can. 100005 is the documented rate limit and
# 100006 the documented transient system error; everything else deterministic until
# proven otherwise, because retrying a deterministic error just triples the noise
# and the latency of every real failure.
# 36009003 was captured live on 2026-08-08 (request_id 202608081300060C6F542C42A3ED1E4CE0),
# the first orders/search 500 body ever seen: "Internal error. Please try again. If the
# issue persists after multiple attempts, please contact platform support." The vendor's
# own remedy is retry, so it belongs here.
_RETRYABLE_APP_CODES = frozenset({100005, 100006, 36009003})
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF_SECONDS = (1.0, 3.0)


def transient_partner_error(exc: Exception) -> bool:
    """True only when a retry can plausibly change the outcome."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, TikTokAPIError):
        return exc.code in _RETRYABLE_APP_CODES
    if isinstance(exc, requests.HTTPError):
        resp = exc.response
        if resp is None:
            return True
        try:
            code = resp.json().get("code")
        except ValueError:
            # No parseable envelope at all — an HTML page from an edge or load
            # balancer, not the API explaining itself. Retry only server-side ones.
            return resp.status_code >= 500
        return code in _RETRYABLE_APP_CODES
    return False


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

        def send() -> dict[str, Any]:
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
            return self._handle_response(resp)

        data = self._request_with_retry(path, send)
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
        retry_transient: bool = False,
    ) -> T: ...

    @overload
    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: None = None,
        retry_transient: bool = False,
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        response_model: type[BaseModel] | None = None,
        retry_transient: bool = False,
    ) -> dict[str, Any] | BaseModel:
        """Signed POST request with JSON body. Returns the ``data`` payload.

        ``retry_transient`` is opt-in because POST serves both searches and writes.
        Search endpoints are reads and pass True; write endpoints keep the single
        attempt — a retried write after an ambiguous 5xx could execute twice.
        """
        body = body or {}
        body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)

        def send() -> dict[str, Any]:
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
                # Send the exact bytes that were signed. Passing json=body lets
                # requests re-serialize with its own separators and key order, so
                # the body TikTok hashes differs from the one we signed and every
                # non-empty body is rejected with code 106001 "the 'sign' query
                # parameter is invalid".
                data=body_str,
                headers=self._json_auth_headers(path),
                timeout=self._timeout,
            )
            return self._handle_response(resp)

        data = self._request_with_retry(path, send) if retry_transient else send()
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
        retry_transient: bool = False,
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
        total_count: int | None = None
        truncated = False

        max_pages = int(os.getenv("TIKTOK_MAX_PAGES", str(_DEFAULT_MAX_PAGES)))

        while True:
            page_count += 1

            # Guard 1: Maximum page count
            if page_count > max_pages:
                truncated = True
                logger.warning(
                    "tiktok_pagination_max_pages_reached",
                    extra={
                        "path": path,
                        "page_count": page_count - 1,
                        "reason": "max_pages_exceeded",
                    },
                )
                break

            data = self.post(
                path, body=page_body, params=query_params, retry_transient=retry_transient
            )
            if not isinstance(data, dict):
                break
            items = data.get(items_key, [])
            all_items.extend(items)
            if total_count is None and isinstance(data.get("total_count"), int):
                total_count = data["total_count"]

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

        # The vendor-side backlog is invisible without this: the fetch caps at
        # max_pages, so "how far behind are we" is total_count minus what landed.
        logger.info(
            "tiktok_pagination_summary",
            extra={
                "path": path,
                "pages": page_count - 1 if truncated else page_count,
                "items": len(all_items),
                "total_count": total_count,
                "truncated": truncated,
            },
        )
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
            # creds-url-guard: allow -- TikTok Shop's non-header-auth endpoints
            # require access_token as a signed query parameter (open-api spec);
            # header-auth endpoints use _auth_headers() instead and never hit this.
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

    def _request_with_retry(
        self,
        path: str,
        send: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run ``send`` with bounded backoff on transient Partner failures.

        ``send`` re-executes the whole build-sign-dispatch, never re-sends stale
        bytes — the signing timestamp must stay within TikTok's 5-minute window.
        """
        for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
            try:
                return send()
            except (requests.RequestException, TikTokAPIError) as exc:
                final = attempt == _TRANSIENT_RETRY_ATTEMPTS - 1
                if final or not transient_partner_error(exc):
                    raise
                delay = _TRANSIENT_RETRY_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "tiktok_transient_retry",
                    extra={
                        "path": path,
                        "attempt": attempt + 1,
                        "delay_seconds": delay,
                        "error": str(exc)[:200],
                    },
                )
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            # Bare raise_for_status() reports only the status line and URL, so the
            # Partner API's own explanation is thrown away exactly when it is needed.
            # Re-raise the same exception type with the body appended; the body is the
            # vendor's error envelope, never our credentials, and the signed request is
            # not echoed back.
            detail = resp.text[:_ERROR_BODY_LIMIT].strip()
            if detail:
                raise requests.HTTPError(
                    f"{exc} — response body: {detail}",
                    response=resp,
                    request=exc.request,
                ) from exc
            raise
        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            raise err
        return data.get("data", {})

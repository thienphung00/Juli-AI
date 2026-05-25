"""Low-level HTTP client for the KiotViet Public API.

Responsibilities:
- Automatic Bearer-token injection via TokenManager
- Retry with exponential backoff + jitter for 429 / 5xx
- Transparent re-authentication on 401
- Offset-based pagination helper
- Structured error normalization via exceptions module
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Iterator

import requests

from .auth import TokenManager
from .exceptions import (
    AuthenticationError,
    KiotVietError,
    RateLimitError,
    raise_for_status,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://public.kiotapi.com"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100
MAX_RETRIES = 5
BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0
JITTER_MAX = 0.5


class KiotVietClient:
    """HTTP client wrapping requests with auth, retry, and pagination."""

    def __init__(
        self,
        token_manager: TokenManager,
        retailer: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._token = token_manager
        self._retailer = retailer or os.environ["KIOTVIET_RETAILER"]
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Exhaust an offset-paginated endpoint and return all records."""
        return list(self.iter_pages(path, params=params, page_size=page_size))

    def iter_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Yield individual records across all pages."""
        page_size = min(page_size, MAX_PAGE_SIZE)
        current_item = 0
        while True:
            query = {**(params or {}), "pageSize": page_size, "currentItem": current_item}
            page = self.get(path, params=query)
            for record in page.get("data", []):
                yield record
            current_item += page_size
            if current_item >= page.get("total", 0):
                break

    # ------------------------------------------------------------------
    # Internal request engine
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            headers = self._build_headers()
            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "kiotviet_request_error",
                    extra={"attempt": attempt, "error": str(exc)},
                )
                self._backoff(attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 401 and attempt < self._max_retries - 1:
                logger.info("kiotviet_token_expired_retrying")
                self._token.invalidate()
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "kiotviet_retryable_error",
                    extra={"status": resp.status_code, "attempt": attempt},
                )
                if attempt < self._max_retries - 1:
                    self._backoff(attempt)
                    continue

            body = self._safe_json(resp)
            raise_for_status(resp.status_code, body)

        if last_exc is not None:
            raise KiotVietError(f"Request failed after {self._max_retries} retries: {last_exc}")
        raise KiotVietError(f"Request to {url} failed after {self._max_retries} retries")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Retailer": self._retailer,
            "Authorization": f"Bearer {self._token.access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
        jitter = random.uniform(0, JITTER_MAX)
        time.sleep(delay + jitter)

    @staticmethod
    def _safe_json(resp: requests.Response) -> dict[str, Any] | None:
        try:
            return resp.json()
        except ValueError:
            return None

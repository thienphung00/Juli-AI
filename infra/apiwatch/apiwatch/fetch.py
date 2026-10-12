"""Polite HTTP GET for public doc endpoints: one request at a time, a minimum gap
between requests, bounded retries with backoff on transient failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

USER_AGENT = "juli-apiwatch/1 (public API docs change watcher)"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A URL could not be fetched (after retries) or did not return JSON."""


class Fetcher:
    def __init__(
        self,
        *,
        delay: float = 0.35,
        retries: int = 4,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._sleep = sleep
        self._clock = clock
        self._last = 0.0
        self.requests = 0

    def _wait_turn(self) -> None:
        gap = self._clock() - self._last
        if gap < self.delay:
            self._sleep(self.delay - gap)
        self._last = self._clock()

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error = "no attempt"
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(min(30.0, 1.5 * 2 ** (attempt - 1)))
            self._wait_turn()
            self.requests += 1
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if resp.status_code in _RETRY_STATUS:
                last_error = f"HTTP {resp.status_code}"
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    self._sleep(min(60.0, float(retry_after)))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"{url}: HTTP {resp.status_code}")
            try:
                return resp.json()
            except ValueError as exc:
                raise FetchError(f"{url}: response is not JSON") from exc
        raise FetchError(f"{url}: {last_error} after {self.retries + 1} attempts")

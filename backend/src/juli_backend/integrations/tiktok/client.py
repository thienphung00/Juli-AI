"""TikTok Shop Partner API HTTP client.

Handles request signing, common query parameters, error mapping,
and cursor-based pagination.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

import requests
from pydantic import BaseModel

from juli_backend.integrations.tiktok.exceptions import TikTokAPIError, error_from_response
from juli_backend.integrations.tiktok.schemas import validate_data
from juli_backend.integrations.tiktok.signing import sign_request

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_HEADER = "x-tts-access-token"

# Seam for tests; the wall-clock budget below must not move with the system clock.
_monotonic = time.monotonic

# Two page budgets, because there are two jobs (#1969).
#
# `_DEFAULT_MAX_PAGES` bounds a routine INCREMENTAL poll. It exists to stop an
# infinite loop when an endpoint echoes `page_token` back, creating a cursor
# that never advances, and a low double-digit cap is right for that: an
# incremental fetch filtered by `update_time_ge` rarely needs more than a few
# pages, and quietly dropping the 21st page of a five-minute delta is cheap.
#
# `_DEFAULT_BACKFILL_MAX_PAGES` bounds a COLD-START backfill -- the onboarding's
# first read of a shop with no watermark (ADR-103 d.10). Applying the
# incremental cap there truncated a new seller's entire history at 20 pages and
# said so in a `logger.warning` nobody reads. The backfill budget is therefore
# both far larger and, critically, *enforced by raising*: a truncated first read
# is a failed first read, never a warning. It stays finite so an echoed cursor
# still terminates -- 400 pages at page_size=50 is 20,000 rows.
_DEFAULT_MAX_PAGES = 20
_DEFAULT_BACKFILL_MAX_PAGES = 400

# Wall-clock budget for one paginated fetch. Checked BETWEEN pages, which is the
# only place this layer can check anything: `requests` is synchronous, so while a
# page is in flight no other code in this process runs. See `pagination_scope`.
_DEFAULT_FETCH_BUDGET_SECONDS = 600.0

MAX_PAGES_ENV = "TIKTOK_MAX_PAGES"
BACKFILL_MAX_PAGES_ENV = "TIKTOK_BACKFILL_MAX_PAGES"
FETCH_BUDGET_SECONDS_ENV = "TIKTOK_FETCH_BUDGET_SECONDS"


class TikTokPaginationError(RuntimeError):
    """A paginated fetch could not be completed as asked.

    Deliberately NOT a `TikTokAPIError`: the vendor answered every request
    correctly. Subclassing `TikTokAPIError` would route these into the
    `except TikTokAPIError` arms in `workers/services/polling/sync.py`, which
    log a warning and return -- exactly the silence this class exists to break.
    """


class TikTokPaginationTruncatedError(TikTokPaginationError):
    """A cold-start backfill hit its page budget before the cursor ran out."""

    def __init__(
        self,
        *,
        path: str,
        pages: int,
        items: int,
        max_pages: int,
        total_count: int | None = None,
    ) -> None:
        self.path = path
        self.pages = pages
        self.items = items
        self.max_pages = max_pages
        self.total_count = total_count
        super().__init__(
            f"backfill of {path} truncated at {pages} pages ({items} items) "
            f"with the cursor still advancing; budget={max_pages} pages, "
            f"vendor total_count={total_count}"
        )


class TikTokPaginationTimeoutError(TikTokPaginationError):
    """A paginated fetch outran its wall-clock budget."""

    def __init__(
        self,
        *,
        path: str,
        pages: int,
        items: int,
        budget_seconds: float,
        elapsed_seconds: float,
    ) -> None:
        self.path = path
        self.pages = pages
        self.items = items
        self.budget_seconds = budget_seconds
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"fetch of {path} exceeded its {budget_seconds:.0f}s budget after "
            f"{pages} pages ({items} items) in {elapsed_seconds:.1f}s"
        )


@dataclass
class PaginationScope:
    """Per-fetch pagination policy, and the progress counters it fills in.

    The mode cannot live on the client: the client is built by
    `ProductionReadClientFactory` several layers below the code that knows
    whether this is a shop's first read, and the resource wrappers in
    `resources/` take no such argument. It cannot live on the endpoint either --
    the same endpoint serves both jobs. It is a property of the *call context*,
    so it travels in a `ContextVar`, and the same object carries `pages` and
    `items` back out so the caller can log what its fetch actually did without
    reaching into the client.
    """

    backfill: bool = False
    budget_seconds: float | None = None
    # Injected rather than patched: a wall-clock assertion that reaches for the
    # real clock is the flakiest kind of test there is.
    clock: Callable[[], float] = _monotonic
    pages: int = 0
    items: int = 0
    truncated: bool = False
    paths: list[str] = field(default_factory=list)


_PAGINATION_SCOPE: ContextVar[PaginationScope | None] = ContextVar(
    "tiktok_pagination_scope", default=None
)


def max_pages() -> int:
    """Page cap for a routine incremental fetch."""
    return int(os.getenv(MAX_PAGES_ENV, str(_DEFAULT_MAX_PAGES)))


def backfill_max_pages() -> int:
    """Page budget for a cold-start backfill."""
    return int(os.getenv(BACKFILL_MAX_PAGES_ENV, str(_DEFAULT_BACKFILL_MAX_PAGES)))


def default_fetch_budget_seconds() -> float:
    """Wall-clock budget applied to a fetch that does not name its own."""
    return float(os.getenv(FETCH_BUDGET_SECONDS_ENV, str(_DEFAULT_FETCH_BUDGET_SECONDS)))


def current_pagination_scope() -> PaginationScope | None:
    """The scope the calling context opened, if any."""
    return _PAGINATION_SCOPE.get()


@contextmanager
def pagination_scope(
    *,
    backfill: bool = False,
    budget_seconds: float | None = None,
    clock: Callable[[], float] = _monotonic,
) -> Iterator[PaginationScope]:
    """Declare how the fetches inside this block should be budgeted.

    `backfill=True` swaps the incremental page cap for the backfill budget and
    turns exhausting it into `TikTokPaginationTruncatedError` instead of a
    warning. `budget_seconds` bounds the wall clock; it defaults to
    `TIKTOK_FETCH_BUDGET_SECONDS`.

    Scopes nest, and an inner scope can never be more generous than the scope
    enclosing it. `workers/services/polling/orchestrate.py` opens an outer scope
    carrying the cycle's REMAINING wall clock, so a per-fetch budget is capped
    by what is left of the cycle. Without that the two budgets composed by
    addition -- a 1800s cycle could still start a 600s fetch at 1799s -- and the
    worst case was ~40 minutes, which is the duration this issue was filed for.

    What the budget can interrupt: the gap between two pages. What it cannot:
    a page already in flight. `requests` blocks the thread, so nothing -- not
    this, not `asyncio.wait_for` one layer up -- can preempt it. The per-request
    socket timeout (`TikTokClient(timeout=...)`, 15s by default) is the only
    bound on a single call, so the real worst case is `budget_seconds` plus one
    socket timeout, not `budget_seconds`.
    """
    resolved = budget_seconds if budget_seconds is not None else default_fetch_budget_seconds()
    enclosing = _PAGINATION_SCOPE.get()
    if enclosing is not None and enclosing.budget_seconds is not None:
        resolved = min(resolved, enclosing.budget_seconds)
    scope = PaginationScope(backfill=backfill, budget_seconds=resolved, clock=clock)
    token = _PAGINATION_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _PAGINATION_SCOPE.reset(token)


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

    @property
    def access_token(self) -> str:
        """Current bearer token used to authorize requests.

        Settable so a credential-aware caller one level up (e.g.
        ``integrations/tiktok/reactive_refresh.py``) can swap in a freshly
        refreshed token on an existing client instance after a ``105002``/
        ``401`` auth-expiry signal, without reconstructing the client (and
        therefore its underlying ``requests.Session``) mid-retry.
        """
        return self._access_token

    @access_token.setter
    def access_token(self, value: str) -> None:
        self._access_token = value

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
        """Auto-paginate a POST endpoint using the ``page_token`` query param.

        Official responses expose the next cursor as ``next_page_token``; legacy
        testing-tool aliases may return ``page_token`` instead.

        Budgeting and the truncation verdict come from the caller's
        ``pagination_scope`` -- see ``_paginate``.
        """
        page_body = dict(body)

        def fetch_page(query_params: dict[str, str]) -> Any:
            return self.post(
                path, body=page_body, params=query_params, retry_transient=retry_transient
            )

        return self._paginate(
            path=path,
            items_key=items_key,
            page_size=page_size,
            base_params={},
            fetch_page=fetch_page,
        )

    def get_all_pages_get(
        self,
        path: str,
        params: dict[str, str],
        items_key: str,
        page_size: int = 50,
    ) -> list[dict]:
        """Auto-paginate a GET endpoint using the ``page_token`` query param."""

        def fetch_page(query_params: dict[str, str]) -> Any:
            return self.get(path, params=query_params)

        return self._paginate(
            path=path,
            items_key=items_key,
            page_size=page_size,
            base_params=dict(params),
            fetch_page=fetch_page,
        )

    def _paginate(
        self,
        *,
        path: str,
        items_key: str,
        page_size: int,
        base_params: dict[str, str],
        fetch_page: Callable[[dict[str, str]], Any],
    ) -> list[dict]:
        """Walk a cursor to exhaustion, or to the budget the caller declared.

        One loop for both verbs (#1969). The POST and GET paginators had drifted
        apart -- only the POST one emitted a summary, so half the fetches in a
        poll cycle were invisible -- and every rule below had to be stated twice
        to change once.

        Stops when: the cursor runs out; the cursor stops advancing (an endpoint
        echoing the token back); the page budget is spent; or the wall-clock
        budget is spent. The last two are the interesting ones:

        - page budget spent during an INCREMENTAL fetch -> warn and return what
          landed. Dropping the tail of a delta is survivable and the next cycle
          picks it up from the same watermark.
        - page budget spent during a BACKFILL -> raise. There is no next cycle
          that fixes a half-read history; the seller would simply be missing
          data forever, which is what happened.
        - wall-clock budget spent -> raise, either way. A fetch that will not
          finish must end loudly rather than hold a worker slot (#1969 defect 3).
        """
        scope = current_pagination_scope()
        backfill = scope.backfill if scope is not None else False
        # `pagination_scope` resolves the budget on entry, including the cap from
        # any enclosing scope; a fetch with no scope at all falls back here.
        budget_seconds = (
            scope.budget_seconds
            if scope is not None and scope.budget_seconds is not None
            else default_fetch_budget_seconds()
        )
        page_budget = backfill_max_pages() if backfill else max_pages()
        clock = scope.clock if scope is not None else _monotonic

        started_at = clock()
        all_items: list[dict] = []
        query_params: dict[str, str] = {**base_params, "page_size": str(page_size)}
        pages = 0
        last_token: str | None = None
        total_count: int | None = None
        truncated = False

        try:
            while True:
                elapsed = clock() - started_at
                if elapsed > budget_seconds:
                    logger.error(
                        "tiktok_pagination_budget_exceeded",
                        extra={
                            "path": path,
                            "pages": pages,
                            "items": len(all_items),
                            "budget_seconds": budget_seconds,
                            "elapsed_seconds": round(elapsed, 3),
                            "backfill": backfill,
                        },
                    )
                    raise TikTokPaginationTimeoutError(
                        path=path,
                        pages=pages,
                        items=len(all_items),
                        budget_seconds=budget_seconds,
                        elapsed_seconds=elapsed,
                    )

                if pages >= page_budget:
                    if backfill:
                        logger.error(
                            "tiktok_backfill_truncated",
                            extra={
                                "path": path,
                                "pages": pages,
                                "items": len(all_items),
                                "max_pages": page_budget,
                                "total_count": total_count,
                                "reason": "max_pages_exceeded",
                            },
                        )
                        raise TikTokPaginationTruncatedError(
                            path=path,
                            pages=pages,
                            items=len(all_items),
                            max_pages=page_budget,
                            total_count=total_count,
                        )
                    truncated = True
                    logger.warning(
                        "tiktok_pagination_max_pages_reached",
                        extra={
                            "path": path,
                            "page_count": pages,
                            "reason": "max_pages_exceeded",
                        },
                    )
                    break

                data = fetch_page(query_params)
                pages += 1
                if not isinstance(data, dict):
                    break

                items = data.get(items_key) or []
                all_items.extend(items)
                if total_count is None and isinstance(data.get("total_count"), int):
                    total_count = data["total_count"]

                # Defect 2 was a 47-minute cycle that emitted nothing between
                # start and the truncation warning. One line per page is what
                # makes a working fetch distinguishable from a wedged one.
                logger.info(
                    "tiktok_pagination_page",
                    extra={
                        "path": path,
                        "page": pages,
                        "page_items": len(items),
                        "items_total": len(all_items),
                        "total_count": total_count,
                        "elapsed_seconds": round(clock() - started_at, 3),
                        "backfill": backfill,
                    },
                )

                next_token = data.get("next_page_token") or data.get("page_token")
                if not next_token:
                    break

                if next_token == last_token:
                    logger.warning(
                        "tiktok_pagination_non_advancing_cursor",
                        extra={
                            "path": path,
                            "page_count": pages,
                            "reason": "cursor_not_advancing",
                        },
                    )
                    break

                last_token = next_token
                query_params = {
                    **base_params,
                    "page_size": str(page_size),
                    "page_token": str(next_token),
                }
        finally:
            if scope is not None:
                scope.pages += pages
                scope.items += len(all_items)
                scope.truncated = scope.truncated or truncated
                scope.paths.append(path)

        # The vendor-side backlog is invisible without this: a truncated fetch
        # leaves total_count minus what landed still sitting at the vendor.
        logger.info(
            "tiktok_pagination_summary",
            extra={
                "path": path,
                "pages": pages,
                "items": len(all_items),
                "total_count": total_count,
                "truncated": truncated,
                "backfill": backfill,
                "elapsed_seconds": round(clock() - started_at, 3),
            },
        )
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

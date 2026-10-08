"""Pace the diagnosis fetch through the poll path's Redis rate limiter (fast track P7-A debt).

The daily report reads the same TikTok endpoints the production poll reads
(A-34 product list, orders search, promotions, LIVE / video lists, product
details). The poll gates every logical call with
``integrations.tiktok.RateLimiter.acquire(app_key, tiktok_shop_id, endpoint,
max_requests=10, window_seconds=60)`` and SKIPS the step when the window is
spent (``workers/services/polling/sync.py``). Before this module, the
diagnosis fetch only slept 0.4 s between calls, so a 60-call A-34 walk could
spend a minute's budget the poll was counting on and push it into 429s.

``RateLimitedResources`` wraps the production-read resources object and, before
each read the fetch makes, takes a token from the SAME Redis window (same key:
app key, TikTok shop id, endpoint path). Unlike the poll it never skips -- it
waits for the window to reset -- and it stops taking tokens at
``DIAGNOSIS_MAX_REQUESTS`` (8 of the poll's 10) so a poll step arriving in the
same minute still finds headroom. A wait longer than ``max_wait_seconds`` raises
``RateLimitWaitExceeded``; the fetch treats it like any other failed read.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from juli_backend.integrations.tiktok import (
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
    ORDER_SEARCH_PATH,
    PROMOTION_ACTIVITIES_SEARCH_PATH,
    PROMOTION_COUPONS_SEARCH_PATH,
    RateLimiter,
    analytics_shop_live_products_performance_path,
    analytics_shop_video_performance_path,
    analytics_shop_video_products_performance_path,
    product_detail_path,
    promotion_activity_path,
)

logger = logging.getLogger(__name__)

#: The poll's per-endpoint window (``sync.py``: ``max_requests=10, window_seconds=60``).
POLL_MAX_REQUESTS = 10
WINDOW_SECONDS = 60
#: The diagnosis stops at 8 so a poll step in the same window keeps 2 tokens.
DIAGNOSIS_MAX_REQUESTS = 8
DEFAULT_MAX_WAIT_SECONDS = 180.0


def shared_rate_limiter(redis_client: Any) -> RateLimiter:
    """The poll path's limiter on ``redis_client`` (one Redis, one window per key)."""
    return RateLimiter(redis_client)


class RateLimitWaitExceeded(RuntimeError):
    """The shared window stayed spent for longer than the fetch may wait."""


def _first_arg(args: tuple[Any, ...], kwargs: dict[str, Any], name: str) -> str:
    return str(kwargs[name] if name in kwargs else args[0])


#: (resource group, method) -> endpoint path, exactly as the poll keys its window.
ENDPOINTS: dict[tuple[str, str], Callable[[tuple[Any, ...], dict[str, Any]], str]] = {
    ("analytics", "list_product_performance_all"): (
        lambda _a, _k: ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH
    ),
    ("analytics", "list_live_performance_all"): lambda _a, _k: ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ("analytics", "get_live_products_performance"): lambda a, k: (
        analytics_shop_live_products_performance_path(_first_arg(a, k, "live_id"))
    ),
    ("analytics", "list_video_performance_all"): (
        lambda _a, _k: ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH
    ),
    ("analytics", "get_video_products_performance"): lambda a, k: (
        analytics_shop_video_products_performance_path(_first_arg(a, k, "video_id"))
    ),
    ("analytics", "get_video_performance"): lambda a, k: analytics_shop_video_performance_path(
        _first_arg(a, k, "video_id")
    ),
    ("orders", "search_all"): lambda _a, _k: ORDER_SEARCH_PATH,
    ("promotion", "search_activities_all"): lambda _a, _k: PROMOTION_ACTIVITIES_SEARCH_PATH,
    ("promotion", "search_coupons_all"): lambda _a, _k: PROMOTION_COUPONS_SEARCH_PATH,
    ("promotion", "get_activity"): lambda a, k: promotion_activity_path(
        _first_arg(a, k, "activity_id")
    ),
    ("products", "get_details"): lambda a, k: product_detail_path(_first_arg(a, k, "product_id")),
}


class SharedWindowGate:
    """Blocks until the poll's Redis window for ``endpoint`` has room, then takes a token."""

    def __init__(
        self,
        limiter: Any,
        *,
        app_id: str,
        shop_key: str,
        sleep: Callable[[float], Any] = time.sleep,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self._limiter = limiter
        self._app_id = app_id
        self._shop_key = shop_key
        self._sleep = sleep
        self._max_wait = max_wait_seconds
        self.waited_seconds = 0.0

    def __call__(self, endpoint: str) -> None:
        waited = 0.0
        while True:
            # Read-only check first: a refused `acquire` still INCRs the shared
            # counter, which would eat the headroom left for the poll.
            if not self._limiter.is_exhausted(
                self._app_id, self._shop_key, endpoint, DIAGNOSIS_MAX_REQUESTS
            ) and self._limiter.acquire(
                self._app_id,
                self._shop_key,
                endpoint,
                max_requests=POLL_MAX_REQUESTS,
                window_seconds=WINDOW_SECONDS,
            ):
                return
            if waited >= self._max_wait:
                raise RateLimitWaitExceeded(
                    f"rate-limit window for {endpoint} stayed spent for {waited:.0f}s"
                )
            delay = float(
                max(1, self._limiter.time_until_reset(self._app_id, self._shop_key, endpoint))
            )
            delay = min(delay, max(1.0, self._max_wait - waited))
            logger.info(
                "shop_diagnosis_rate_limit_wait",
                extra={"endpoint": endpoint, "wait_seconds": delay},
            )
            self._sleep(delay)
            waited += delay
            self.waited_seconds += delay


class _GatedGroup:
    def __init__(self, group: str, target: Any, gate: Callable[[str], None]) -> None:
        self._group = group
        self._target = target
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        endpoint_of = ENDPOINTS.get((self._group, name))
        if endpoint_of is None or not callable(attr):
            return attr

        def gated(*args: Any, **kwargs: Any) -> Any:
            self._gate(endpoint_of(args, kwargs))
            return attr(*args, **kwargs)

        return gated


class RateLimitedResources:
    """The resources object the fetch sees: every mapped read takes a shared token first."""

    def __init__(self, resources: Any, gate: Callable[[str], None]) -> None:
        self._resources = resources
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        return _GatedGroup(name, getattr(self._resources, name), self._gate)


__all__ = [
    "DIAGNOSIS_MAX_REQUESTS",
    "ENDPOINTS",
    "POLL_MAX_REQUESTS",
    "WINDOW_SECONDS",
    "RateLimitWaitExceeded",
    "RateLimitedResources",
    "SharedWindowGate",
    "shared_rate_limiter",
]

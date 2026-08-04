"""Bounded Partner resource sync for targeted fetch — no workers imports (#627).

Only normalizes and hands off rows for resources with bronze persistence in the
Shared Compute medallion foundation (orders, returns). Other domains are deferred
at the executor layer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from juli_backend.integrations.tiktok import (
    CANCELLATION_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    RateLimiter,
    TikTokAPIError,
    normalize_cancellation,
    normalize_order,
    normalize_return,
)
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)


async def sync_orders(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    """Fetch orders since last sync and hand off normalized rows to bronze handoff."""
    if not rate_limiter.acquire(
        app_id, shop_key, ORDER_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info(
            "targeted_fetch_rate_limited",
            extra={"resource": "orders", "correlation_id": correlation_id},
        )
        return

    update_from = sync_state.get("orders_last_update_time")

    try:
        orders = resource.search_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning(
            "targeted_fetch_orders_failed",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return

    max_update_time = update_from or 0
    for order in orders:
        normalized = normalize_order(order)
        await handoff_fn(
            "tiktok.orders.raw",
            shop_key,
            json.dumps(normalized).encode(),
        )
        max_update_time = max(max_update_time, order.get("update_time", 0))

    if orders:
        sync_state["orders_last_update_time"] = max_update_time


async def sync_returns(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    """Fetch returns since last sync and hand off normalized rows to bronze handoff."""
    if not rate_limiter.acquire(
        app_id, shop_key, RETURN_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info(
            "targeted_fetch_rate_limited",
            extra={"resource": "returns", "correlation_id": correlation_id},
        )
        return

    update_from = sync_state.get("returns_last_update_time")

    try:
        returns = resource.search_returns_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning(
            "targeted_fetch_returns_failed",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return

    max_update_time = update_from or 0
    for ret in returns:
        await handoff_fn(
            "tiktok.returns.raw",
            shop_key,
            json.dumps(normalize_return(ret)).encode(),
        )
        max_update_time = max(
            max_update_time,
            ret.get("update_time") or ret.get("create_time") or 0,
        )

    if returns:
        sync_state["returns_last_update_time"] = max_update_time


async def sync_cancellations(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    """Fetch cancellations since last sync and hand off normalized rows to bronze handoff.

    Cancellations are treated as returns with a distinct type marker,
    using the same bronze table and silver.returns for idempotent natural-key merge.
    """
    if not rate_limiter.acquire(
        app_id, shop_key, CANCELLATION_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info(
            "targeted_fetch_rate_limited",
            extra={"resource": "cancellations", "correlation_id": correlation_id},
        )
        return

    update_from = sync_state.get("cancellations_last_update_time")

    try:
        cancellations = resource.search_cancellations_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning(
            "targeted_fetch_cancellations_failed",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return

    max_update_time = update_from or 0
    for cancellation in cancellations:
        await handoff_fn(
            "tiktok.returns.raw",
            shop_key,
            json.dumps(normalize_cancellation(cancellation)).encode(),
        )
        max_update_time = max(
            max_update_time,
            cancellation.get("update_time") or cancellation.get("create_time") or 0,
        )

    if cancellations:
        sync_state["cancellations_last_update_time"] = max_update_time

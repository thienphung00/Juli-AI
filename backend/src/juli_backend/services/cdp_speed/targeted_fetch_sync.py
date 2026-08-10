"""Bounded Partner resource sync for targeted fetch — no workers imports (#627).

Only normalizes and hands off rows for resources with bronze persistence in the
Shared Compute medallion foundation (orders, returns). Other domains are deferred
at the executor layer.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from juli_backend.integrations.tiktok import (
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    CANCELLATION_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    RateLimiter,
    TikTokAPIError,
    analytics_snapshot_key,
    expand_analytics_live_session,
    expand_analytics_product_list_item,
    normalize_cancellation,
    normalize_order,
    normalize_return,
)
from juli_backend.services.analytics_backfill.live_partition import (
    compute_live_hours,
    compute_live_sessions_count,
    sum_live_impressions,
    sum_live_views,
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

    # The Partner API fails in two disjoint ways and a bronze fetch must survive both:
    # _handle_response calls raise_for_status() before it inspects the JSON body, so a
    # transport or 5xx failure arrives as requests.RequestException and only an
    # application-level code (e.g. 106001) arrives as TikTokAPIError. Catching just the
    # latter let an upstream 500 abort the whole Shared Compute job, taking the silver
    # and gold stages with it — including ctor and live_hours, which read local rows and
    # need nothing from TikTok at all.
    try:
        orders = resource.search_all(update_time_from=update_from)
    except (TikTokAPIError, requests.RequestException):
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
    except (TikTokAPIError, requests.RequestException):
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
    except (TikTokAPIError, requests.RequestException):
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


def _today_window() -> tuple[str, str, int]:
    """Today's UTC date window plus a unix ``synced_at`` for analytics list APIs.

    A-34/A-28 are date-windowed list endpoints (``start_date_ge``/``end_date_lt``),
    not update_time cursors like orders/returns — each targeted-fetch trigger
    re-fetches today's window and upserts by ``snapshot_key``, so replays are
    idempotent rather than incremental.
    """
    now = datetime.now(tz=UTC)
    today = now.date()
    start_date_ge = today.isoformat()
    end_date_lt = (today + timedelta(days=1)).isoformat()
    return start_date_ge, end_date_lt, int(now.timestamp())


async def sync_ctor_performance(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    """Fetch today's A-34 product performance and hand off product-grain rows.

    ctor (Demo Main KPI) is GMV-weighted click_order_rate across product-grain
    ``analytics_performance_intervals`` rows (#880) — one bronze/silver row per
    product per day, upserted idempotently by ``snapshot_key``.
    """
    if not rate_limiter.acquire(
        app_id,
        shop_key,
        ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
        max_requests=10,
        window_seconds=60,
    ):
        logger.info(
            "targeted_fetch_rate_limited",
            extra={"resource": "ctor", "correlation_id": correlation_id},
        )
        return

    start_date_ge, end_date_lt, synced_at = _today_window()

    try:
        products = resource.list_product_performance_all(
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )
    except (TikTokAPIError, requests.RequestException):
        logger.warning(
            "targeted_fetch_ctor_failed",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return

    for item in products:
        row = expand_analytics_product_list_item(
            item,
            start_date=start_date_ge,
            end_date=end_date_lt,
            synced_at=synced_at,
        )
        if row is None:
            continue
        await handoff_fn(
            "tiktok.analytics.product.raw",
            shop_key,
            json.dumps(row).encode(),
        )

    sync_state["ctor_last_synced_at"] = synced_at


async def sync_live_hours(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    """Fetch today's A-28 LIVE performance and hand off session + shop rollup rows.

    live_hours (Demo Main KPI) sums ``live_hours`` across shop-grain
    ``analytics_performance_intervals`` rows (#880). A-29 LIVE overview is
    quota-guarded (unbounded detail fan-out) so this domain never calls it —
    the shop-grain rollup is computed purely from the A-28 session list, same
    as ``compute_live_hours`` in the historical backfill LIVE partition.
    """
    if not rate_limiter.acquire(
        app_id,
        shop_key,
        ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
        max_requests=10,
        window_seconds=60,
    ):
        logger.info(
            "targeted_fetch_rate_limited",
            extra={"resource": "live_hours", "correlation_id": correlation_id},
        )
        return

    start_date_ge, end_date_lt, synced_at = _today_window()
    partition_date = datetime.now(tz=UTC).date()

    try:
        sessions = resource.list_live_performance_all(
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )
    except (TikTokAPIError, requests.RequestException):
        logger.warning(
            "targeted_fetch_live_hours_failed",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return

    for session in sessions:
        row = expand_analytics_live_session(
            session,
            start_date=start_date_ge,
            end_date=end_date_lt,
            synced_at=synced_at,
        )
        if row is None:
            continue
        await handoff_fn(
            "tiktok.analytics.live.raw",
            shop_key,
            json.dumps(row).encode(),
        )

    shop_rollup = {
        "grain": "shop",
        "start_date": start_date_ge,
        "end_date": end_date_lt,
        "update_time": synced_at,
        "snapshot_key": analytics_snapshot_key(
            grain="shop",
            start_date=start_date_ge,
            end_date=end_date_lt,
        ),
        "live_hours": str(compute_live_hours(sessions, partition_date)),
        "live_sessions": compute_live_sessions_count(sessions),
        "visitors": sum_live_views(sessions),
        "impressions": sum_live_impressions(sessions),
    }
    await handoff_fn(
        "tiktok.analytics.live.raw",
        shop_key,
        json.dumps(shop_rollup).encode(),
    )

    sync_state["live_hours_last_synced_at"] = synced_at

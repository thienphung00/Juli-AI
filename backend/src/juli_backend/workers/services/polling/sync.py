"""Polling sync workers for TikTok Shop data.

Each worker:
1. Checks the rate limiter before calling the API
2. Fetches data via the resource module (incremental by update_time)
3. Hands each record to the ingest pipeline (ETL)
4. Updates sync state with the latest timestamp

Creator workers surface PermissionDeniedError (scope_missing) rather than
swallowing it, so the caller can trigger re-consent flows.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from juli_backend.integrations.tiktok.constants import (
    MARKETPLACE_CREATORS_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from juli_backend.integrations.tiktok.exceptions import PermissionDeniedError, TikTokAPIError
from juli_backend.integrations.tiktok.mapping import (
    expand_order_line_items,
    normalize_creator,
    normalize_order,
    normalize_product,
    normalize_return,
)
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)


async def sync_orders(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch orders since last sync and hand off to ETL."""
    if not rate_limiter.acquire(
        app_id, shop_id, ORDER_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "orders"})
        return

    update_from = sync_state.get("orders_last_update_time")

    try:
        orders = resource.search_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning("sync_orders_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = update_from or 0
    for order in orders:
        normalized = normalize_order(order)
        await handoff_fn(
            "tiktok.orders.raw",
            shop_id,
            json.dumps(normalized).encode(),
        )
        for line_item in expand_order_line_items(normalized):
            await handoff_fn(
                "tiktok.order_items.raw",
                shop_id,
                json.dumps(line_item).encode(),
            )
        max_update_time = max(max_update_time, order.get("update_time", 0))

    if orders:
        sync_state["orders_last_update_time"] = max_update_time


async def sync_products(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch products since last sync and hand off to ETL."""
    if not rate_limiter.acquire(
        app_id, shop_id, PRODUCT_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "products"})
        return

    update_from = sync_state.get("products_last_update_time")

    try:
        products = resource.search_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning("sync_products_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = update_from or 0
    for product in products:
        await handoff_fn(
            "tiktok.products.raw",
            shop_id,
            json.dumps(normalize_product(product)).encode(),
        )
        max_update_time = max(max_update_time, product.get("updated_at", 0))

    if products:
        sync_state["products_last_update_time"] = max_update_time


async def sync_returns(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch returns since last sync and hand off to ETL."""
    if not rate_limiter.acquire(
        app_id, shop_id, RETURN_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "returns"})
        return

    update_from = sync_state.get("returns_last_update_time")

    try:
        returns = resource.search_returns_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning("sync_returns_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = update_from or 0
    for ret in returns:
        await handoff_fn(
            "tiktok.returns.raw",
            shop_id,
            json.dumps(normalize_return(ret)).encode(),
        )
        max_update_time = max(
            max_update_time,
            ret.get("update_time") or ret.get("create_time") or 0,
        )

    if returns:
        sync_state["returns_last_update_time"] = max_update_time


async def sync_creators(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch creators and hand off to ETL.

    Raises PermissionDeniedError (scope_missing) instead of swallowing it —
    the Affiliate API requires separate per-seller scope approval.
    """
    if not rate_limiter.acquire(
        app_id, shop_id, MARKETPLACE_CREATORS_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "creators"})
        return

    try:
        creators = resource.list_all()
    except PermissionDeniedError:
        raise
    except TikTokAPIError:
        logger.warning("sync_creators_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = sync_state.get("creators_last_update_time") or 0
    for creator in creators:
        await handoff_fn(
            "tiktok.creators.raw",
            shop_id,
            json.dumps(normalize_creator(creator)).encode(),
        )
        max_update_time = max(max_update_time, creator.get("update_time", 0))

    if creators:
        sync_state["creators_last_update_time"] = max_update_time


async def backfill_shop(
    *,
    creators_resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
) -> dict[str, Any]:
    """Run initial creator backfill for a newly connected shop.

    Returns the resulting sync_state for subsequent incremental syncs.
    """
    sync_state: dict[str, Any] = {}

    await sync_creators(
        resource=creators_resource,
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        app_id=app_id,
        shop_id=shop_id,
        sync_state=sync_state,
    )

    return sync_state

"""Polling sync workers for TikTok Shop data.

Each worker:
1. Checks the rate limiter before calling the API
2. Fetches data via the resource module (incremental by update_time)
3. Hands each record to the ingest pipeline (ETL)
4. Updates sync state with the latest timestamp

Creator and livestream workers surface PermissionDeniedError (scope_missing)
rather than swallowing it, so the caller can trigger re-consent flows.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.modules.ordering.api.ingestion.handoff import HandoffFn, PublishFn
from src.modules.catalog.domain.integrations.tiktok.exceptions import PermissionDeniedError, TikTokAPIError
from src.modules.catalog.domain.integrations.tiktok.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BACKFILL_WINDOW_SECONDS = 90 * 24 * 3600  # 90 days


def _resolve_handoff(
    handoff_fn: HandoffFn | None,
    publish_fn: PublishFn | None,
) -> HandoffFn:
    resolved = handoff_fn or publish_fn
    if resolved is None:
        raise TypeError("sync worker requires handoff_fn= or publish_fn=")
    return resolved


async def sync_orders(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch orders since last sync and hand off to ETL."""
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/orders/search", max_requests=10, window_seconds=60):
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
        await handoff(
            "tiktok.orders.raw",
            shop_id,
            json.dumps(order).encode(),
        )
        max_update_time = max(max_update_time, order.get("update_time", 0))

    if orders:
        sync_state["orders_last_update_time"] = max_update_time


async def sync_products(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch products since last sync and hand off to ETL."""
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/products/search", max_requests=10, window_seconds=60):
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
        await handoff(
            "tiktok.products.raw",
            shop_id,
            json.dumps(product).encode(),
        )
        max_update_time = max(max_update_time, product.get("updated_at", 0))

    if products:
        sync_state["products_last_update_time"] = max_update_time


async def sync_inventory(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch current inventory levels and hand off to ETL."""
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/inventory/search", max_requests=10, window_seconds=60):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "inventory"})
        return

    try:
        data = resource.search()
    except TikTokAPIError:
        logger.warning("sync_inventory_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    items = data.get("inventory", [])
    for item in items:
        await handoff(
            "tiktok.inventory.raw",
            shop_id,
            json.dumps(item).encode(),
        )


async def sync_creators(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch creators and hand off to ETL.

    Raises PermissionDeniedError (scope_missing) instead of swallowing it —
    the Affiliate API requires separate per-seller scope approval.
    """
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/affiliate/creators/search", max_requests=10, window_seconds=60):
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
        await handoff(
            "tiktok.creators.raw",
            shop_id,
            json.dumps(creator).encode(),
        )
        max_update_time = max(max_update_time, creator.get("update_time", 0))

    if creators:
        sync_state["creators_last_update_time"] = max_update_time


async def sync_livestreams(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch livestream post-stream summaries and hand off to ETL.

    Raises PermissionDeniedError (scope_missing) instead of swallowing it —
    the Affiliate API requires separate per-seller scope approval.
    """
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/affiliate/livestreams/search", max_requests=10, window_seconds=60):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "livestreams"})
        return

    start_time = sync_state.get("livestreams_last_update_time")

    try:
        livestreams = resource.list_all(start_time=start_time)
    except PermissionDeniedError:
        raise
    except TikTokAPIError:
        logger.warning("sync_livestreams_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = start_time or 0
    for ls in livestreams:
        await handoff(
            "tiktok.livestreams.raw",
            shop_id,
            json.dumps(ls).encode(),
        )
        max_update_time = max(max_update_time, ls.get("update_time", 0))

    if livestreams:
        sync_state["livestreams_last_update_time"] = max_update_time


async def sync_settlements(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch settlements and hand off to ETL.

    Settlement values may be pending for 7-14 days before confirming;
    update_time is the reconciliation key.
    """
    handoff = _resolve_handoff(handoff_fn, publish_fn)
    if not rate_limiter.acquire(app_id, shop_id, "/api/finance/settlements/search", max_requests=10, window_seconds=60):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "settlements"})
        return

    settle_time_from = sync_state.get("settlements_last_update_time")

    try:
        settlements = resource.list_all(settle_time_from=settle_time_from)
    except TikTokAPIError:
        logger.warning("sync_settlements_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    max_update_time = settle_time_from or 0
    for settlement in settlements:
        await handoff(
            "tiktok.settlements.raw",
            shop_id,
            json.dumps(settlement).encode(),
        )
        max_update_time = max(max_update_time, settlement.get("update_time", 0))

    if settlements:
        sync_state["settlements_last_update_time"] = max_update_time


async def backfill_shop(
    *,
    creators_resource: Any,
    livestreams_resource: Any,
    settlements_resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn | None = None,
    publish_fn: PublishFn | None = None,
    app_id: str,
    shop_id: str,
) -> dict[str, Any]:
    """Run initial 90-day backfill for a newly connected shop.

    Calls sync_creators, sync_livestreams, and sync_settlements sequentially
    with a lookback window of BACKFILL_WINDOW_SECONDS. The caller is
    responsible for staggering backfill calls across shops to respect
    per-(app x shop x endpoint) rate limits.

    Returns the resulting sync_state for subsequent incremental syncs.
    """
    now = int(time.time())
    lookback = now - BACKFILL_WINDOW_SECONDS

    sync_state: dict[str, Any] = {
        "livestreams_last_update_time": lookback,
        "settlements_last_update_time": lookback,
    }

    handoff = _resolve_handoff(handoff_fn, publish_fn)

    await sync_creators(
        resource=creators_resource,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
        app_id=app_id,
        shop_id=shop_id,
        sync_state=sync_state,
    )

    await sync_livestreams(
        resource=livestreams_resource,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
        app_id=app_id,
        shop_id=shop_id,
        sync_state=sync_state,
    )

    await sync_settlements(
        resource=settlements_resource,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
        app_id=app_id,
        shop_id=shop_id,
        sync_state=sync_state,
    )

    return sync_state

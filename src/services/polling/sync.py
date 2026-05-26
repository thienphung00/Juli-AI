"""Polling sync workers for TikTok Shop data.

Each worker:
1. Checks the rate limiter before calling the API
2. Fetches data via the resource module (incremental by update_time)
3. Publishes each record to Kafka
4. Updates sync state with the latest timestamp
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from src.integrations.tiktok.exceptions import TikTokAPIError
from src.integrations.tiktok.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

PublishFn = Callable[[str, str, bytes], Awaitable[None]]


async def sync_orders(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    publish_fn: PublishFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch orders since last sync and publish to Kafka."""
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
        await publish_fn(
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
    publish_fn: PublishFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch products since last sync and publish to Kafka."""
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
        await publish_fn(
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
    publish_fn: PublishFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch current inventory levels and publish to Kafka."""
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
        await publish_fn(
            "tiktok.inventory.raw",
            shop_id,
            json.dumps(item).encode(),
        )

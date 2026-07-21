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

import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    MARKETPLACE_CREATORS_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)
from juli_backend.integrations.tiktok.exceptions import PermissionDeniedError, TikTokAPIError
from juli_backend.integrations.tiktok.mapping import (
    analytics_snapshot_key,
    expand_analytics_live_session,
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    expand_analytics_shop_performance,
    expand_analytics_shop_performance_per_hour,
    expand_analytics_sku_detail,
    expand_analytics_sku_list_item,
    expand_inventory_search,
    expand_order_line_items,
    normalize_creator,
    normalize_inventory,
    normalize_order,
    normalize_product,
    normalize_return,
)
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)


def _inventory_snapshot_event_id(shop_id: str, payload: dict[str, Any]) -> str:
    """Stable idempotency key for unchanged poll inventory snapshots."""
    parts = (
        str(payload.get("sku_id") or ""),
        str(payload.get("product_id") or ""),
        str(payload.get("warehouse_id") or ""),
        str(payload.get("available_quantity") or ""),
    )
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"poll-inventory:{shop_id}:{payload.get('sku_id')}:{digest}"


_ANALYTICS_CHANNEL_BY_GRAIN = {
    "shop": "tiktok.analytics.shop.raw",
    "product": "tiktok.analytics.product.raw",
    "sku": "tiktok.analytics.sku.raw",
    "live": "tiktok.analytics.live.raw",
}


def _analytics_event_id(shop_id: str, payload: dict[str, Any]) -> str:
    snapshot_key = payload.get("snapshot_key")
    if not snapshot_key:
        snapshot_key = analytics_snapshot_key(
            grain=str(payload.get("grain") or ""),
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload["end_date"]) if payload.get("end_date") else None,
            hour_index=payload.get("hour_index"),
            product_id=str(payload["product_id"]) if payload.get("product_id") else None,
            sku_id=str(payload["sku_id"]) if payload.get("sku_id") else None,
            live_id=str(payload["live_id"]) if payload.get("live_id") else None,
        )
    update_time = payload.get("update_time", "")
    return f"poll-analytics:{shop_id}:{snapshot_key}:{update_time}"


async def _handoff_analytics_rows(
    handoff_fn: HandoffFn,
    shop_id: str,
    rows: list[dict[str, Any]],
) -> None:
    for row in rows:
        channel = _ANALYTICS_CHANNEL_BY_GRAIN.get(str(row.get("grain")))
        if channel is None:
            continue
        row.setdefault("event_id", _analytics_event_id(shop_id, row))
        await handoff_fn(channel, shop_id, json.dumps(row).encode())


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
        max_update_time = max(
            max_update_time,
            product.get("update_time") or product.get("updated_at") or 0,
        )

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


async def sync_inventory(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch inventory snapshot, flatten SKUs, and hand off to ETL.

    Search Inventory has no ``update_time`` filter — this is a full-snapshot
    reconciliation backstop. Incremental changes arrive via webhook #68.
    """
    if not rate_limiter.acquire(
        app_id, shop_id, INVENTORY_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "inventory"})
        return

    try:
        response = resource.search()
    except TikTokAPIError:
        logger.warning("sync_inventory_failed", extra={"shop_id": shop_id}, exc_info=True)
        return

    if not isinstance(response, dict):
        logger.warning(
            "sync_inventory_invalid_response",
            extra={"shop_id": shop_id, "type": type(response).__name__},
        )
        return

    rows = expand_inventory_search(response)
    synced_at = int(time.time())

    for row in rows:
        payload = normalize_inventory(row)
        payload["event_id"] = _inventory_snapshot_event_id(shop_id, payload)
        payload.setdefault("update_time", synced_at)
        await handoff_fn(
            "tiktok.inventory.raw",
            shop_id,
            json.dumps(payload).encode(),
        )

    if rows:
        sync_state["inventory_last_sync_at"] = synced_at


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


def _analytics_date_window(
    *,
    now: datetime | None = None,
) -> tuple[str, str, str]:
    """Return ``(start_date_ge, end_date_lt, day)`` for a one-day UTC window.

    ``end_date_lt`` is exclusive (Partner API identifier catalog).
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    end = current.date()
    start = end - timedelta(days=1)
    day = start.isoformat()
    return start.isoformat(), end.isoformat(), day


def _acquire(
    rate_limiter: RateLimiter,
    *,
    app_id: str,
    shop_id: str,
    endpoint: str,
) -> bool:
    return rate_limiter.acquire(
        app_id, shop_id, endpoint, max_requests=10, window_seconds=60
    )


async def sync_analytics(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
    promotion_resource: Any | None = None,
    now: datetime | None = None,
) -> None:
    """Fetch Analytics GET targets for the current date window (#424).

    Invokes A-31–A-34, A-36–A-39 with ``start_date_ge`` / ``end_date_lt`` (or
    ``date`` / ``time_slot``) and Redis ``RateLimiter`` acquire per endpoint.
    A-25 Get Activity runs when ``promotion_activity_ids`` is present in
    ``sync_state``. LIVE A-28 list sessions hand off via
    ``expand_analytics_live_session`` (#425).

    Analytics ETL persistence hands normalized rows to ingest channels (#425).
    """
    start_date_ge, end_date_lt, day = _analytics_date_window(now=now)
    synced_at = int((now or datetime.now(UTC)).timestamp())

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    ):
        try:
            skus = resource.list_sku_performance_all(
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
            )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_sku_list_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )
            skus = None
        if isinstance(skus, list):
            sync_state["shop_sku_performance_last_sync_at"] = synced_at
            for sku in skus:
                if not isinstance(sku, dict):
                    continue
                sku_id = sku.get("id")
                if not sku_id:
                    continue
                detail_path = analytics_shop_sku_performance_path(str(sku_id))
                if not _acquire(
                    rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=detail_path
                ):
                    list_row = expand_analytics_sku_list_item(
                        sku,
                        start_date=start_date_ge,
                        end_date=end_date_lt,
                        synced_at=synced_at,
                    )
                    if list_row is not None:
                        await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                    break
                try:
                    detail = resource.get_sku_performance(
                        sku_id=str(sku_id),
                        start_date_ge=start_date_ge,
                        end_date_lt=end_date_lt,
                    )
                    if isinstance(detail, dict):
                        await _handoff_analytics_rows(
                            handoff_fn,
                            shop_id,
                            expand_analytics_sku_detail(detail, synced_at=synced_at),
                        )
                    else:
                        list_row = expand_analytics_sku_list_item(
                            sku,
                            start_date=start_date_ge,
                            end_date=end_date_lt,
                            synced_at=synced_at,
                        )
                        if list_row is not None:
                            await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                except TikTokAPIError:
                    list_row = expand_analytics_sku_list_item(
                        sku,
                        start_date=start_date_ge,
                        end_date=end_date_lt,
                        synced_at=synced_at,
                    )
                    if list_row is not None:
                        await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                    logger.warning(
                        "sync_analytics_sku_detail_failed",
                        extra={"shop_id": shop_id, "sku_id": sku_id},
                        exc_info=True,
                    )

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ):
        try:
            products = resource.list_product_performance_all(
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
            )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_product_list_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )
            products = None
        if isinstance(products, list):
            sync_state["shop_product_performance_last_sync_at"] = synced_at
            for product in products:
                if not isinstance(product, dict):
                    continue
                product_id = product.get("id")
                if not product_id:
                    continue
                detail_path = analytics_shop_product_performance_path(str(product_id))
                if not _acquire(
                    rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=detail_path
                ):
                    list_row = expand_analytics_product_list_item(
                        product,
                        start_date=start_date_ge,
                        end_date=end_date_lt,
                        synced_at=synced_at,
                    )
                    if list_row is not None:
                        await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                    break
                try:
                    detail = resource.get_product_performance(
                        product_id=str(product_id),
                        start_date_ge=start_date_ge,
                        end_date_lt=end_date_lt,
                    )
                    if isinstance(detail, dict):
                        await _handoff_analytics_rows(
                            handoff_fn,
                            shop_id,
                            expand_analytics_product_detail(
                                detail,
                                synced_at=synced_at,
                                product_id=str(product_id),
                            ),
                        )
                    else:
                        list_row = expand_analytics_product_list_item(
                            product,
                            start_date=start_date_ge,
                            end_date=end_date_lt,
                            synced_at=synced_at,
                        )
                        if list_row is not None:
                            await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                except TikTokAPIError:
                    list_row = expand_analytics_product_list_item(
                        product,
                        start_date=start_date_ge,
                        end_date=end_date_lt,
                        synced_at=synced_at,
                    )
                    if list_row is not None:
                        await _handoff_analytics_rows(handoff_fn, shop_id, [list_row])
                    logger.warning(
                        "sync_analytics_product_detail_failed",
                        extra={"shop_id": shop_id, "product_id": product_id},
                        exc_info=True,
                    )

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ):
        try:
            live_sessions = resource.list_live_performance_all(
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
            )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_live_list_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )
            live_sessions = None
        if isinstance(live_sessions, list):
            live_rows: list[dict[str, Any]] = []
            for session in live_sessions:
                if not isinstance(session, dict):
                    continue
                row = expand_analytics_live_session(
                    session,
                    start_date=start_date_ge,
                    end_date=end_date_lt,
                    synced_at=synced_at,
                )
                if row is not None:
                    live_rows.append(row)
            if live_rows:
                await _handoff_analytics_rows(handoff_fn, shop_id, live_rows)
                sync_state["shop_live_performance_last_sync_at"] = synced_at

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_SHOP_PERFORMANCE_PATH,
    ):
        try:
            shop_performance = resource.get_shop_performance(
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
            )
            sync_state["shop_performance_last_sync_at"] = synced_at
            if isinstance(shop_performance, dict):
                await _handoff_analytics_rows(
                    handoff_fn,
                    shop_id,
                    expand_analytics_shop_performance(
                        shop_performance, synced_at=synced_at
                    ),
                )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_shop_performance_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )

    per_hour_path = analytics_shop_performance_per_hour_path(day)
    if _acquire(
        rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=per_hour_path
    ):
        try:
            per_hour = resource.get_shop_performance_per_hour(date=day)
            sync_state["shop_performance_per_hour_last_sync_at"] = synced_at
            if isinstance(per_hour, dict):
                await _handoff_analytics_rows(
                    handoff_fn,
                    shop_id,
                    expand_analytics_shop_performance_per_hour(
                        per_hour, date=day, synced_at=synced_at
                    ),
                )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_shop_performance_per_hour_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ):
        try:
            resource.get_bestselling_products(date=day, time_slot="1D")
            sync_state["bestselling_products_last_sync_at"] = synced_at
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_bestselling_products_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )

    if _acquire(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ):
        try:
            resource.get_bestselling_videos(date=day, time_slot="1D")
            sync_state["bestselling_videos_last_sync_at"] = synced_at
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_bestselling_videos_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )

    activity_ids = sync_state.get("promotion_activity_ids") or []
    if promotion_resource is not None and activity_ids:
        fetched_any = False
        for activity_id in activity_ids:
            path = promotion_activity_path(str(activity_id))
            if not _acquire(
                rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=path
            ):
                break
            try:
                promotion_resource.get_activity(str(activity_id))
                fetched_any = True
            except TikTokAPIError:
                logger.warning(
                    "sync_analytics_promotion_activity_failed",
                    extra={"shop_id": shop_id, "activity_id": activity_id},
                    exc_info=True,
                )
        if fetched_any:
            sync_state["promotion_activity_last_sync_at"] = synced_at


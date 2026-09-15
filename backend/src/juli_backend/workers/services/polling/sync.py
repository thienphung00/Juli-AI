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
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import (
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
    PermissionDeniedError,
    RateLimiter,
    TikTokAPIError,
    TikTokPaginationError,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
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
    pagination_scope,
    promotion_activity_path,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(frozen=True)
class SyncOutcome:
    """What one poll step actually did (#1950's triple, #1969's instance of it).

    Before this, every step returned ``None``. A step that fetched 3,581 rows
    and persisted zero was byte-for-byte indistinguishable from a step with
    nothing to do, and that is how two production data-loss bugs survived for
    months.

    ``persisted`` is counted at the boundary this module can actually see: a
    row the ETL handoff accepted without raising. It is NOT proof of a committed
    Postgres row -- ``HandoffFn`` is typed ``-> None`` and ``make_etl_handoff``
    discards ``EtlConsumer.ingest``'s ``ProcessOutcome``, so a row routed to the
    DLQ still counts as accepted here. Widening that contract belongs to #1950
    in ``services/ingestion/handoff.py``, which this issue does not own. What
    this number does catch -- and what was silently broken -- is the whole-step
    failure: handoff raising for every row.
    """

    resource: str
    shop_id: str
    fetched: int = 0
    persisted: int = 0
    failed: int = 0
    pages: int = 0
    backfill: bool = False
    skipped: bool = False
    error: str | None = None

    @property
    def dropped_everything(self) -> bool:
        """Rows came back from the vendor and not one of them landed."""
        return self.fetched > 0 and self.persisted == 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.failed == 0 and not self.dropped_everything

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "shop_id": self.shop_id,
            "fetched": self.fetched,
            "persisted": self.persisted,
            "failed": self.failed,
            "pages": self.pages,
            "backfill": self.backfill,
            "skipped": self.skipped,
            "error": self.error,
            "ok": self.ok,
        }


class PollStepDroppedRowsError(RuntimeError):
    """A poll step fetched rows from the vendor and persisted none of them."""

    def __init__(self, outcome: SyncOutcome) -> None:
        self.outcome = outcome
        super().__init__(
            f"{outcome.resource} sync fetched {outcome.fetched} rows for shop "
            f"{outcome.shop_id} and persisted none ({outcome.failed} rejected)"
        )


class _CountingHandoff:
    """A ``HandoffFn`` that counts what the ETL took and what it refused.

    Signature-identical to ``HandoffFn`` on purpose -- it is substituted for the
    real one inside a step, including in ``sync_analytics`` where fourteen call
    sites reach for the same local name.

    A rejected row is counted and logged rather than re-raised on the spot. That
    is not a swallow: the step's verdict is computed from these counters right
    after the loop and raises if nothing landed. Failing on row 1 would report
    "one row failed" for what is usually "the ETL is down and all 3,581 failed",
    and the second sentence is the one worth paging on.
    """

    def __init__(
        self,
        inner: HandoffFn,
        *,
        resource: str,
        shop_id: str,
        log_every: int = 200,
    ) -> None:
        self._inner = inner
        self._resource = resource
        self._shop_id = shop_id
        self._log_every = log_every
        self.offered = 0
        self.persisted = 0
        self.failed = 0
        self.first_error: str | None = None

    async def __call__(self, channel: str, shop_key: str, value: bytes) -> None:
        self.offered += 1
        try:
            await self._inner(channel, shop_key, value)
        except Exception as exc:
            self.failed += 1
            if self.first_error is None:
                self.first_error = repr(exc)
            logger.error(
                "poll_step_handoff_failed",
                extra={
                    "resource": self._resource,
                    "shop_id": self._shop_id,
                    "channel": channel,
                    "offered": self.offered,
                    "failed": self.failed,
                },
                exc_info=True,
            )
            return
        self.persisted += 1
        if self.persisted % self._log_every == 0:
            logger.info(
                "poll_step_progress",
                extra={
                    "resource": self._resource,
                    "shop_id": self._shop_id,
                    "offered": self.offered,
                    "persisted": self.persisted,
                    "failed": self.failed,
                },
            )


class _StepRun:
    """One poll step's budget, counters, and its single outcome record.

    Exists so all four search steps plus analytics report identically. Before
    #1969 a cycle could run 47 minutes emitting nothing at all, so "is this
    poll working" was unanswerable from outside; now every step emits
    ``poll_step_started`` on entry and exactly one ``poll_step_outcome`` on
    exit, whichever way it exits.
    """

    def __init__(
        self,
        resource: str,
        shop_id: str,
        *,
        backfill: bool,
        handoff_fn: HandoffFn,
        update_time_from: int | None = None,
    ) -> None:
        self.resource = resource
        self.shop_id = shop_id
        self.backfill = backfill
        self.handoff = _CountingHandoff(handoff_fn, resource=resource, shop_id=shop_id)
        self.fetched = 0
        self.pages = 0
        logger.info(
            "poll_step_started",
            extra={
                "resource": resource,
                "shop_id": shop_id,
                "backfill": backfill,
                "update_time_from": update_time_from,
            },
        )

    def fetch(self, call: Callable[[], _T]) -> _T:
        """Run the synchronous vendor fetch under the right pagination budget.

        A step with no watermark is the shop's first read, so it fetches under
        the cold-start backfill budget, where exhausting the page budget raises
        instead of warning (see ``integrations/tiktok/client.py``).
        """
        with pagination_scope(backfill=self.backfill) as scope:
            try:
                return call()
            finally:
                self.pages = scope.pages

    def outcome(self, *, error: BaseException | None = None, skipped: bool = False) -> SyncOutcome:
        return SyncOutcome(
            resource=self.resource,
            shop_id=self.shop_id,
            fetched=self.fetched,
            persisted=self.handoff.persisted,
            failed=self.handoff.failed,
            pages=self.pages,
            backfill=self.backfill,
            skipped=skipped,
            error=repr(error) if error is not None else self.handoff.first_error,
        )

    def report(self, *, error: BaseException | None = None, skipped: bool = False) -> SyncOutcome:
        """Log the triple, then fail the step if it dropped everything it fetched."""
        outcome = self.outcome(error=error, skipped=skipped)
        log = logger.info if outcome.ok else logger.error
        log("poll_step_outcome", extra=outcome.as_log_fields())
        if outcome.dropped_everything:
            raise PollStepDroppedRowsError(outcome)
        return outcome


def _skipped(resource: str, shop_id: str) -> SyncOutcome:
    """A step the rate limiter turned away still has to say so."""
    outcome = SyncOutcome(resource=resource, shop_id=shop_id, skipped=True)
    logger.info("poll_step_outcome", extra=outcome.as_log_fields())
    return outcome


# Logger for structured warnings about credential mismatches
mismatch_logger = logging.getLogger(__name__ + ".sandbox_write_catalog_identity_mismatch")


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
) -> SyncOutcome:
    """Fetch orders since last sync, hand off to ETL, and report the triple."""
    if not rate_limiter.acquire(
        app_id, shop_id, ORDER_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "orders"})
        return _skipped("orders", shop_id)

    update_from = sync_state.get("orders_last_update_time")
    step = _StepRun(
        "orders",
        shop_id,
        backfill=update_from is None,
        handoff_fn=handoff_fn,
        update_time_from=update_from,
    )

    try:
        orders = step.fetch(lambda: resource.search_all(update_time_from=update_from))
    except TikTokPaginationError as exc:
        # A truncated or timed-out backfill is a failed read, not a partial one.
        # The exception must reach `report` too, or the step logs `ok=True` on
        # its way out and only the traceback disagrees -- which is the same
        # "reported success while dropping data" shape this issue exists to kill.
        step.report(error=exc)
        raise
    except TikTokAPIError as exc:
        logger.error("sync_orders_failed", extra={"shop_id": shop_id}, exc_info=True)
        return step.report(error=exc)

    step.fetched = len(orders)
    max_update_time = update_from or 0
    for order in orders:
        normalized = normalize_order(order)
        await step.handoff(
            "tiktok.orders.raw",
            shop_id,
            json.dumps(normalized).encode(),
        )
        for line_item in expand_order_line_items(normalized):
            await step.handoff(
                "tiktok.order_items.raw",
                shop_id,
                json.dumps(line_item).encode(),
            )
        max_update_time = max(max_update_time, order.get("update_time", 0))

    outcome = step.report()
    # The watermark follows the rows, never the fetch (#1950): advancing it over
    # rows that never landed is how 3,581 orders were skipped with a healthy
    # looking timestamp on every run.
    if orders and outcome.persisted:
        sync_state["orders_last_update_time"] = max_update_time
    return outcome


async def sync_products(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> SyncOutcome:
    """Fetch products since last sync, hand off to ETL, and report the triple."""
    if not rate_limiter.acquire(
        app_id, shop_id, PRODUCT_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "products"})
        return _skipped("products", shop_id)

    update_from = sync_state.get("products_last_update_time")
    step = _StepRun(
        "products",
        shop_id,
        backfill=update_from is None,
        handoff_fn=handoff_fn,
        update_time_from=update_from,
    )

    try:
        products = step.fetch(lambda: resource.search_all(update_time_from=update_from))
    except TikTokPaginationError as exc:
        step.report(error=exc)
        raise
    except TikTokAPIError as exc:
        logger.error("sync_products_failed", extra={"shop_id": shop_id}, exc_info=True)
        return step.report(error=exc)

    step.fetched = len(products)
    max_update_time = update_from or 0
    for product in products:
        await step.handoff(
            "tiktok.products.raw",
            shop_id,
            json.dumps(normalize_product(product)).encode(),
        )
        max_update_time = max(
            max_update_time,
            product.get("update_time") or product.get("updated_at") or 0,
        )

    outcome = step.report()
    if products and outcome.persisted:
        sync_state["products_last_update_time"] = max_update_time
    return outcome


async def sync_products_with_local_upsert(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    products_repo: Any,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> None:
    """Fetch products and upsert to local shop products table (for sandbox catalog sync).

    Unlike sync_products which only hands off to ETL, this function also
    upserts products directly to the products table for immediate availability
    in product binding. Used for sandbox_write catalog sync where products
    must be immediately queryable by the approval path.

    Idempotent: re-running produces no duplicates; pre-existing rows
    (from other credentials) are preserved.
    """
    if not rate_limiter.acquire(
        app_id, shop_id, PRODUCT_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info(
            "rate_limited",
            extra={"shop_id": shop_id, "resource": "products_with_upsert"},
        )
        return

    update_from = sync_state.get("products_last_update_time")

    try:
        products = resource.search_all(update_time_from=update_from)
    except TikTokAPIError:
        logger.warning(
            "sync_products_with_upsert_failed",
            extra={"shop_id": shop_id},
            exc_info=True,
        )
        return

    try:
        shop_uuid = uuid.UUID(shop_id)
    except (ValueError, AttributeError):
        logger.warning(
            "sync_products_invalid_shop_id",
            extra={"shop_id": shop_id},
        )
        return

    max_update_time = update_from or 0
    upsert_failures = 0
    for product in products:
        normalized = normalize_product(product)

        # Hand off to ETL (existing pattern)
        await handoff_fn(
            "tiktok.products.raw",
            shop_id,
            json.dumps(normalized).encode(),
        )

        # Upsert to local products table (new for sandbox sync). Field
        # names must come from the NORMALIZED dict: TikTok's raw payload
        # keys the product id as "id" and has no "name"; normalize_product
        # maps id -> product_id and title -> name. Upserting from the raw
        # dict stored empty tiktok_product_ids that deduped every product
        # into one unusable row (seen live 2026-08-25, run e79b4c8d).
        tiktok_product_id = str(normalized.get("product_id") or "")
        if not tiktok_product_id:
            upsert_failures += 1
            logger.warning(
                "sync_products_local_upsert_skipped_no_product_id",
                extra={"shop_id": shop_id},
            )
        else:
            try:
                await products_repo.upsert(
                    shop_id=shop_uuid,
                    tiktok_product_id=tiktok_product_id,
                    name=normalized.get("name", "") or normalized.get("title", ""),
                    status=normalized.get("status", "unknown"),
                    title=normalized.get("title", "") or normalized.get("name", ""),
                    # products.update_time is TIMESTAMP WITHOUT TIME ZONE —
                    # asyncpg rejects aware datetimes (naive-UTC convention,
                    # same as OrdersRepo at repos.py).
                    update_time=datetime.now(UTC).replace(tzinfo=None),
                )
            except Exception:
                upsert_failures += 1
                logger.warning(
                    "sync_products_local_upsert_failed",
                    extra={"shop_id": shop_id, "product_id": tiktok_product_id},
                    exc_info=True,
                )

        max_update_time = max(
            max_update_time,
            product.get("update_time") or product.get("updated_at") or 0,
        )

    if products:
        sync_state["products_last_update_time"] = max_update_time
    sync_state["products_upserted"] = len(products) - upsert_failures
    sync_state["products_upsert_failed"] = upsert_failures


async def sync_returns(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> SyncOutcome:
    """Fetch returns since last sync, hand off to ETL, and report the triple."""
    if not rate_limiter.acquire(
        app_id, shop_id, RETURN_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "returns"})
        return _skipped("returns", shop_id)

    update_from = sync_state.get("returns_last_update_time")
    step = _StepRun(
        "returns",
        shop_id,
        backfill=update_from is None,
        handoff_fn=handoff_fn,
        update_time_from=update_from,
    )

    try:
        returns = step.fetch(lambda: resource.search_returns_all(update_time_from=update_from))
    except TikTokPaginationError as exc:
        step.report(error=exc)
        raise
    except TikTokAPIError as exc:
        logger.error("sync_returns_failed", extra={"shop_id": shop_id}, exc_info=True)
        return step.report(error=exc)

    step.fetched = len(returns)
    max_update_time = update_from or 0
    for ret in returns:
        await step.handoff(
            "tiktok.returns.raw",
            shop_id,
            json.dumps(normalize_return(ret)).encode(),
        )
        max_update_time = max(
            max_update_time,
            ret.get("update_time") or ret.get("create_time") or 0,
        )

    outcome = step.report()
    if returns and outcome.persisted:
        sync_state["returns_last_update_time"] = max_update_time
    return outcome


async def sync_inventory(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    sync_state: dict[str, Any],
) -> SyncOutcome:
    """Fetch inventory snapshot, flatten SKUs, hand off to ETL, report the triple.

    Search Inventory has no ``update_time`` filter — this is a full-snapshot
    reconciliation backstop. Incremental changes arrive via webhook #68.
    """
    if not rate_limiter.acquire(
        app_id, shop_id, INVENTORY_SEARCH_PATH, max_requests=10, window_seconds=60
    ):
        logger.info("rate_limited", extra={"shop_id": shop_id, "resource": "inventory"})
        return _skipped("inventory", shop_id)

    step = _StepRun(
        "inventory",
        shop_id,
        # No watermark has ever been written for this shop, so this snapshot is
        # the first one — the same cold-start condition as the other steps.
        backfill=sync_state.get("inventory_last_sync_at") is None,
        handoff_fn=handoff_fn,
    )

    try:
        response = step.fetch(resource.search)
    except TikTokPaginationError as exc:
        step.report(error=exc)
        raise
    except TikTokAPIError as exc:
        logger.error("sync_inventory_failed", extra={"shop_id": shop_id}, exc_info=True)
        return step.report(error=exc)

    if not isinstance(response, dict):
        logger.error(
            "sync_inventory_invalid_response",
            extra={"shop_id": shop_id, "type": type(response).__name__},
        )
        return step.report(
            error=ValueError(f"inventory search returned {type(response).__name__}, not a dict")
        )

    rows = expand_inventory_search(response)
    step.fetched = len(rows)
    synced_at = int(time.time())

    for row in rows:
        payload = normalize_inventory(row)
        payload["event_id"] = _inventory_snapshot_event_id(shop_id, payload)
        payload.setdefault("update_time", synced_at)
        await step.handoff(
            "tiktok.inventory.raw",
            shop_id,
            json.dumps(payload).encode(),
        )

    outcome = step.report()
    if rows and outcome.persisted:
        sync_state["inventory_last_sync_at"] = synced_at
    return outcome


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
    return rate_limiter.acquire(app_id, shop_id, endpoint, max_requests=10, window_seconds=60)


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
) -> SyncOutcome:
    """Fetch Analytics GET targets for the current date window (#424).

    Invokes A-31–A-34, A-36–A-39 with ``start_date_ge`` / ``end_date_lt`` (or
    ``date`` / ``time_slot``) and Redis ``RateLimiter`` acquire per endpoint.
    A-25 Get Activity runs when ``promotion_activity_ids`` is present in
    ``sync_state``. LIVE A-28 list sessions hand off via
    ``expand_analytics_live_session`` (#425).

    Analytics ETL persistence hands normalized rows to ingest channels (#425).
    """
    # Analytics reports the same triple as the four search steps, counted over
    # every row it offers the ETL. `fetched` here is rows offered rather than a
    # vendor row count: the step fans out across ~10 endpoints with per-endpoint
    # rate-limit breaks, so there is no single number the vendor returned. It is
    # never a cold-start backfill — the window is always one day (#424).
    step = _StepRun("analytics", shop_id, backfill=False, handoff_fn=handoff_fn)
    handoff_fn = step.handoff

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
                if not _acquire(rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=detail_path):
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
                if not _acquire(rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=detail_path):
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
                    expand_analytics_shop_performance(shop_performance, synced_at=synced_at),
                )
        except TikTokAPIError:
            logger.warning(
                "sync_analytics_shop_performance_failed",
                extra={"shop_id": shop_id},
                exc_info=True,
            )

    per_hour_path = analytics_shop_performance_per_hour_path(day)
    if _acquire(rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=per_hour_path):
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
            if not _acquire(rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=path):
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

    step.fetched = step.handoff.offered
    return step.report()


async def sync_sandbox_write_products(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Sync sandbox_write seller's products to shop with rate limiting.

    Respects TikTok API rate limits via real RateLimiter backed by Redis.
    Skips gracefully if Redis is unavailable (named log for operator).

    This is the cohesive entry point for task-layer sandbox catalog sync;
    it handles rate limiter creation, credential resolution, and client assembly.
    """
    import os

    from juli_backend.integrations.tiktok import (
        SANDBOX_AUTH_ID,
        ClientFactoryConfig,
        SandboxWriteClientFactory,
    )
    from juli_backend.repositories.repos import ProductsRepo

    # Check for Redis (required for rate limiter)
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        logger.info(
            "sandbox_write_catalog_sync_skipped",
            extra={"shop_id": str(shop_id), "reason": "redis_url_not_configured"},
        )
        return

    # Check for TikTok app credentials
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()

    if not app_key or not app_secret:
        logger.info(
            "sandbox_write_catalog_sync_skipped",
            extra={"shop_id": str(shop_id), "reason": "tiktok_app_credentials_missing"},
        )
        return

    # Resolve the sandbox_write credential through the repo-backed resolver:
    # the raw column is enc:v1 ciphertext, and only the repo path hydrates a
    # decrypted, lazily-refreshed token the client can actually send.
    from juli_backend.core.security import resolve_sandbox_write_credential

    try:
        sandbox_write_cred = await resolve_sandbox_write_credential(session)
    except Exception:
        logger.info(
            "sandbox_write_catalog_sync_skipped",
            extra={"shop_id": str(shop_id), "reason": "no_sandbox_write_credential"},
        )
        return

    if sandbox_write_cred is None or sandbox_write_cred.shop_id != shop_id:
        logger.info(
            "sandbox_write_catalog_sync_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "shop_has_no_sandbox_write_credential",
            },
        )
        return

    try:
        # RateLimiter is synchronous (incr/expire return values, not
        # coroutines) — it needs the sync redis client, same as the
        # constructions in refresh.py and targeted_fetch_executor.py.
        import redis

        rate_limiter = RateLimiter(redis.from_url(redis_url))

        # Create client config and resources
        config = ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=sandbox_write_cred.access_token,
            merchant_auth_id=SANDBOX_AUTH_ID,
            shop_cipher=sandbox_write_cred.shop_cipher,
        )
        resources = SandboxWriteClientFactory().create_resources(config)

        # Create products repo and sync state
        products_repo = ProductsRepo(session)
        sync_state: dict[str, Any] = {}

        # Empty handoff (we only care about local upsert in task)
        async def noop_handoff(channel: str, shop_key: str, value: bytes) -> None:
            pass

        # Run the sync with local upsert
        await sync_products_with_local_upsert(
            resource=resources.products,
            rate_limiter=rate_limiter,
            handoff_fn=noop_handoff,
            products_repo=products_repo,
            app_id="refresh_task",
            shop_id=str(shop_id),
            sync_state=sync_state,
        )

        upserted = sync_state.get("products_upserted", 0)
        failed = sync_state.get("products_upsert_failed", 0)
        if failed:
            logger.warning(
                "sandbox_write_catalog_sync_completed_with_failures",
                extra={
                    "shop_id": str(shop_id),
                    "products_upserted": upserted,
                    "products_upsert_failed": failed,
                },
            )
        else:
            logger.info(
                "sandbox_write_catalog_sync_completed",
                extra={"shop_id": str(shop_id), "products_upserted": upserted},
            )

    except Exception:
        logger.warning(
            "sandbox_write_catalog_sync_failed",
            extra={"shop_id": str(shop_id)},
            exc_info=True,
        )


async def check_sandbox_write_catalog_identity_mismatch(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> None:
    """Log a structured warning if sandbox_write and seller_connect have different merchant IDs.

    When a shop has both sandbox_write (write capability) and seller_connect (read capability)
    credentials with different merchant authorizations, product binding cannot succeed because
    the write credential is scoped to a different seller than the catalog source.

    Issues a named log event for operator visibility without aborting the flow.
    """
    # Get all credentials for this shop
    stmt = select(TikTokCredential).where(TikTokCredential.shop_id == shop_id)
    result = await session.execute(stmt)
    credentials = result.scalars().all()

    if not credentials:
        return

    # Find sandbox_write and seller_connect credentials
    sandbox_write_cred = None
    seller_connect_cred = None

    for cred in credentials:
        if cred.capability == "sandbox_write":
            sandbox_write_cred = cred
        elif cred.capability == "production_read":
            # Seller_connect uses production_read capability
            seller_connect_cred = cred

    # Check if we have both and they differ
    if sandbox_write_cred and seller_connect_cred:
        if (
            sandbox_write_cred.merchant_authorization_id
            != seller_connect_cred.merchant_authorization_id
        ):
            mismatch_logger.warning(
                "sandbox_write_catalog_identity_mismatch",
                extra={
                    "shop_id": str(shop_id),
                    "sandbox_write_merchant_id": sandbox_write_cred.merchant_authorization_id,
                    "catalog_source_merchant_id": seller_connect_cred.merchant_authorization_id,
                },
            )

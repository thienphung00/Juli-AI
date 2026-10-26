"""Rebuild a shop's stored orders-sourced report when an order changes (B12, P68).

``shop_diagnosis_daily`` is a snapshot built at 00:15 for days up to yesterday. When
an order of a day that snapshot already covers is cancelled / returned / refunded
(or a new paid order for such a day lands), the stored GMV is stale until the next
00:15 build -- Trang chủ kept showing 904k / 6 đơn after all six were cancelled.

The ETL consumer (the single order writer, polling and webhook alike) calls
:func:`maybe_refresh_stored_report` after each committed order upsert. It enqueues
the SAME builder the daily job uses (``build_shop_diagnosis``, ``refresh=True``) for
that shop only -- no second GMV computation.

Only reports with ``metrics_source == "orders"`` are refreshed: they are the ones
computed from the local orders. An analytics-sourced report comes from TikTok A-34
and would not change by a rebuild from local order state.

DEBOUNCE. The first qualifying change takes a Redis key ``ingest:diagnosis-refresh:{shop}``
(``SET NX EX``) and enqueues one build with a countdown of the same length; further
changes inside the window find the key and do nothing, because the delayed build
reads the order table when it runs. A change after the key expired schedules the
next build. Never raises: a stale report must not fail ingestion.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shop_diagnosis import RANKING_60D
from juli_backend.repositories import ShopDiagnosisReportsRepo
from juli_backend.services.shop_diagnosis_daily.fetch import DAYS
from juli_backend.services.shop_diagnosis_daily.orders_source import (
    METRICS_SOURCE_ORDERS,
    PAID_ORDER_STATUSES,
    SHOP_UTC_OFFSET,
)

logger = logging.getLogger(__name__)

#: Seconds a change waits before the rebuild runs; also the debounce window.
REFRESH_DEBOUNCE_SECONDS = 120
#: Statuses that take an order out of GMV.
REVERSED_STATUSES: frozenset[str] = frozenset({"cancelled", "canceled", "returned", "refunded"})

ClaimFn = Callable[[str], bool]
EnqueueFn = Callable[[str], Any]


def refresh_key(shop_id: str) -> str:
    return f"ingest:diagnosis-refresh:{shop_id}"


_redis_client: Any = None
_redis_url: str = ""


def _client(url: str) -> Any:
    """One Redis client per process (lazy), rebuilt only if the URL changes."""
    global _redis_client, _redis_url
    if _redis_client is None or _redis_url != url:
        import redis

        _redis_client = redis.from_url(url)
        _redis_url = url
    return _redis_client


def _default_claim() -> ClaimFn | None:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    client = _client(url)

    def claim(shop_id: str) -> bool:
        return bool(client.set(refresh_key(shop_id), "1", nx=True, ex=REFRESH_DEBOUNCE_SECONDS))

    return claim


#: shop id -> (expires at monotonic seconds, report end date, metrics_source); a shop
#: with no stored report caches ``(None, None)``. Keeps a backfill of thousands of
#: orders from reading the report JSON once per order.
REPORT_CACHE_TTL_SECONDS = 60.0
_report_cache: dict[uuid.UUID, tuple[float, date | None, str | None]] = {}


def clear_report_cache() -> None:
    _report_cache.clear()


async def _stored_report_facts(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[date | None, str | None]:
    cached = _report_cache.get(shop_id)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]
    async with with_shop_scope(session, shop_id):
        stored = await ShopDiagnosisReportsRepo(session).latest(shop_id, RANKING_60D)
    await session.commit()
    end: date | None = None
    source: str | None = None
    if stored is not None:
        end = stored.end_date
        if isinstance(stored.report, dict):
            raw = stored.report.get("metrics_source")
            source = raw if isinstance(raw, str) else None
    _report_cache[shop_id] = (now + REPORT_CACHE_TTL_SECONDS, end, source)
    return end, source


_enqueuer: EnqueueFn | None = None


def set_report_refresh_enqueuer(enqueuer: EnqueueFn | None) -> None:
    """Bound by ``workers/dispatch_binding`` at API / worker startup (services must not import
    workers). Unbound, the hook is a no-op."""
    global _enqueuer
    _enqueuer = enqueuer


def _qualifies(status: str | None) -> bool:
    value = (status or "").lower()
    return value in REVERSED_STATUSES or value in PAID_ORDER_STATUSES


def _local_day(created_at: datetime) -> date:
    return (created_at + SHOP_UTC_OFFSET).date()


async def maybe_refresh_stored_report(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    status: str | None,
    created_at: datetime | None,
    claim: ClaimFn | None = None,
    enqueue: EnqueueFn | None = None,
) -> bool:
    """Enqueue one debounced rebuild when this order change touches the stored report.

    ``created_at`` is the order's naive-UTC TikTok create time; unknown counts as
    "inside the window" (the debounce bounds the cost). Returns whether a rebuild
    was enqueued.
    """
    try:
        if not _qualifies(status):
            return False
        enqueue_fn = enqueue or _enqueuer
        if enqueue_fn is None:
            return False
        claim_fn = claim or _default_claim()
        if claim_fn is None:
            return False
        end_date, source = await _stored_report_facts(session, shop_id)
        if end_date is None or source != METRICS_SOURCE_ORDERS:
            return False
        if created_at is not None:
            day = _local_day(created_at)
            if day > end_date or day < end_date - timedelta(days=DAYS - 1):
                return False
        key = str(shop_id)
        if not claim_fn(key):
            return False
        enqueue_fn(key)
        logger.info(
            "shop_diagnosis_refresh_enqueued",
            extra={"shop_id": key, "status": status, "end_date": end_date.isoformat()},
        )
        return True
    except Exception:
        logger.warning(
            "shop_diagnosis_refresh_failed", extra={"shop_id": str(shop_id)}, exc_info=True
        )
        return False


__all__ = [
    "REFRESH_DEBOUNCE_SECONDS",
    "maybe_refresh_stored_report",
    "refresh_key",
    "set_report_refresh_enqueuer",
]

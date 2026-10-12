"""Run baselines at approval and at execution start (D30.1c).

``capture_run_baseline`` freezes what the card's product looked like: the
14-day daily pre-series per metric (``analytics_performance_intervals``,
product grain, the 14 shop-local days before today), the current price (the
latest snapshot's SKUs, else ``products.price``), the activities running now
with their SKU prices, the content hash, and listing codes when the caller has
them. ``quality_score`` is left NULL for the D30.2 algorithm.

A handful of indexed reads (the product, its 14 daily rows, its latest
snapshot, its running activities) and one insert, inside a SAVEPOINT so a
failure is logged and never fails the caller. Idempotent per (run, phase).

Never in the approval request itself: at ~200 ms per statement through the
production pooler that would add a second. The approve route enqueues
``capture_run_baseline_task`` after its commit (zero extra queries on the
request; ``captured_at`` is the approval instant), and the agent-run task
captures the ``execution`` phase in its own session before the runner starts.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.history import BASELINE_PHASES, RunBaseline
from juli_backend.models.models import AnalyticsPerformanceInterval, Product
from juli_backend.repositories import utc_now_naive
from juli_backend.services.product_history.normalize import local_day
from juli_backend.services.product_history.promotions import active_promotions_for
from juli_backend.services.product_history.store import latest_snapshots

logger = logging.getLogger(__name__)

PRE_DAYS = 14
#: Daily metrics in the pre-series (impressions / clicks fall back to A34_TOTAL).
METRICS: tuple[str, ...] = (
    "impressions",
    "clicks",
    "ctr",
    "sku_orders",
    "items_sold",
    "gmv",
    "conversion_rate",
    "add_cart_count",
)
_A34_TOTAL = "A34_TOTAL"


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (ArithmeticError, ValueError):
        return None


def _metric(row: AnalyticsPerformanceInterval, metric: str) -> float | None:
    a34 = (row.traffic_breakdown or {}).get(_A34_TOTAL)
    block = a34 if isinstance(a34, dict) else {}
    if metric == "impressions":
        return _num(row.impressions if row.impressions is not None else block.get("impressions"))
    if metric == "clicks":
        return _num(row.clicks if row.clicks is not None else block.get("clicks"))
    if metric == "add_cart_count":
        return _num(block.get("add_cart_count"))
    if metric == "conversion_rate":
        value = row.conversion_rate
        return _num(value if value is not None else row.click_to_order_rate)
    return _num(getattr(row, metric, None))


def pre_series(
    rows: Sequence[AnalyticsPerformanceInterval], days: Sequence[date]
) -> dict[str, Any]:
    """``{"days": [...], "series": {metric: [value | None per day]}}`` (daily rows only)."""
    by_day: dict[date, AnalyticsPerformanceInterval] = {}
    for row in rows:
        start = row.start_date
        end = row.end_date
        if end is not None and (end - start).days > 1:
            continue
        by_day.setdefault(start, row)
    return {
        "days": [day.isoformat() for day in days],
        "series": {
            metric: [_metric(by_day[day], metric) if day in by_day else None for day in days]
            for metric in METRICS
        },
    }


def _price_from_skus(skus: list[dict[str, Any]], source: str) -> dict[str, Any]:
    def low(key: str) -> str | None:
        values = [Decimal(str(s[key])) for s in skus if s.get(key) not in (None, "")]
        return str(min(values)) if values else None

    currency = next((s.get("currency") for s in skus if s.get("currency")), None)
    return {
        "skus": skus,
        "min_list_price": low("list_price"),
        "min_sale_price": low("sale_price"),
        "currency": currency,
        "source": source,
    }


async def capture_run_baseline(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID,
    product_id: uuid.UUID | None,
    phase: str,
    action_card_id: uuid.UUID | None = None,
    listing_codes: list[Any] | None = None,
    now: datetime | None = None,
) -> RunBaseline | None:
    """Store the run's baseline for ``phase``; ``None`` when it exists or capture failed.

    Never raises (a baseline must not fail an approval or a run); the caller's
    transaction is untouched on failure (SAVEPOINT).
    """
    if phase not in BASELINE_PHASES:
        raise ValueError(f"unknown baseline phase {phase!r}")
    try:
        async with session.begin_nested():
            return await _capture(
                session,
                shop_id=shop_id,
                workflow_run_id=workflow_run_id,
                product_id=product_id,
                phase=phase,
                action_card_id=action_card_id,
                listing_codes=listing_codes,
                now=now or utc_now_naive(),
            )
    except Exception:
        logger.warning(
            "run_baseline_capture_failed",
            extra={"shop_id": str(shop_id), "run_id": str(workflow_run_id), "phase": phase},
            exc_info=True,
        )
        return None


async def _capture(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID,
    product_id: uuid.UUID | None,
    phase: str,
    action_card_id: uuid.UUID | None,
    listing_codes: list[Any] | None,
    now: datetime,
) -> RunBaseline | None:
    existing = await session.execute(
        select(RunBaseline.id).where(
            RunBaseline.workflow_run_id == workflow_run_id, RunBaseline.phase == phase
        )
    )
    if existing.first() is not None:
        return None
    product = await session.get(Product, product_id) if product_id is not None else None
    if product is not None and product.shop_id != shop_id:
        product = None
    tiktok_id = product.tiktok_product_id if product is not None else None

    metrics: dict[str, Any] | None = None
    price: dict[str, Any] | None = None
    active: list[dict[str, Any]] | None = None
    content_hash: str | None = None
    if tiktok_id is not None:
        today = local_day(now)
        days = [today - timedelta(days=offset) for offset in range(PRE_DAYS, 0, -1)]
        rows = (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop_id,
                    AnalyticsPerformanceInterval.grain == "product",
                    AnalyticsPerformanceInterval.tiktok_product_id == tiktok_id,
                    AnalyticsPerformanceInterval.hour_index.is_(None),
                    AnalyticsPerformanceInterval.start_date >= days[0],
                    AnalyticsPerformanceInterval.start_date <= days[-1],
                )
            )
        ).scalars()
        metrics = pre_series(list(rows), days)
        snapshot = (await latest_snapshots(session, shop_id, [tiktok_id])).get(tiktok_id)
        if snapshot is not None:
            content_hash = snapshot.content_hash
            price = _price_from_skus(list(snapshot.skus or []), "snapshot")
        elif product is not None and product.price is not None:
            price = {
                "skus": [],
                "min_list_price": str(product.price),
                "min_sale_price": None,
                "currency": product.price_currency,
                "source": "products",
            }
        active = await active_promotions_for(session, shop_id, tiktok_id, at=now)

    row = RunBaseline(
        shop_id=shop_id,
        workflow_run_id=workflow_run_id,
        action_card_id=action_card_id,
        tiktok_product_id=tiktok_id,
        phase=phase,
        captured_at=now,
        metrics_pre=metrics,
        price=price,
        active_promotions=active,
        content_hash=content_hash,
        listing_codes=listing_codes,
    )
    session.add(row)
    await session.flush()
    return row


async def capture_for_run(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID,
    phase: str,
    now: datetime | None = None,
) -> RunBaseline | None:
    """Load the run's product and card, then :func:`capture_run_baseline`."""
    from juli_backend.models.models import WorkflowRun

    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None or run.shop_id != shop_id:
        return None
    return await capture_run_baseline(
        session,
        shop_id=shop_id,
        workflow_run_id=run.id,
        product_id=run.product_id,
        phase=phase,
        action_card_id=run.action_card_id,
        now=now,
    )


__all__ = ["METRICS", "PRE_DAYS", "capture_for_run", "capture_run_baseline", "pre_series"]

"""Async DB reads/writes for the daily impact-reader beat task (#1044).

``services/impact`` is a pure library (no I/O, no wall-clock reads, by
design — see its package docstring) — every function here builds the
plain-data inputs (``RawDailyRecord`` series, ``ControlCandidate``s, a
``confounded: bool``) that package expects, or persists its outputs.
Nothing in this module computes a reading itself.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    ImpactReading,
    Product,
    ToolExecution,
)
from juli_backend.services.impact import ControlCandidate, RawDailyRecord

#: The only tool this reader knows how to classify mutations for today (see
#: ``classify.py``) — the single source of truth so the "due executions"
#: scan and the "did another run touch this product" confounding check both
#: filter on exactly the same tool-name set.
MEASURABLE_TOOL_NAMES = frozenset({"listing.optimize_product"})

#: ``AnalyticsPerformanceInterval.grain`` value for per-product daily rows
#: (see ``services/analytics_backfill/product_partition.py``'s
#: ``PRODUCT_BUCKET`` / ``coverage.py``'s ``grain == "product"`` queries —
#: the same convention this reader's target/control-candidate series reuse).
_DAILY_PRODUCT_GRAIN = "product"

#: Soft cap on same-shop sibling candidates considered per reading, to bound
#: query cost on shops with large catalogs — ADR-077 decision 3 only ever
#: needs the top 5 by correlation, so a candidate pool far past that is pure
#: query overhead, never a better answer.
_MAX_CANDIDATE_PRODUCTS = 50

TERMINAL_SUCCEEDED = "succeeded"


async def load_measurable_executions(session: AsyncSession) -> Sequence[ToolExecution]:
    """Every terminal (succeeded) execution of a tool this reader can
    classify mutations for — the raw candidate pool the pipeline then
    filters by elapsed time and already-written kinds."""
    stmt = select(ToolExecution).where(
        ToolExecution.status == TERMINAL_SUCCEEDED,
        ToolExecution.tool_name.in_(MEASURABLE_TOOL_NAMES),
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def load_written_kinds(session: AsyncSession, tool_execution_id: uuid.UUID) -> set[str]:
    """Which ``kind``s already have at least one ``ImpactReading`` row for
    this execution — the coarse idempotency gate: a ``kind`` is (re)computed
    at most once per execution, never per-metric partial-recompute."""
    stmt = select(ImpactReading.kind).where(ImpactReading.tool_execution_id == tool_execution_id)
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def load_existing_metric_pairs(
    session: AsyncSession, tool_execution_id: uuid.UUID
) -> set[tuple[str, str]]:
    """Every ``(metric, kind)`` pair already written for this execution —
    the fine-grained idempotency guard applied at insert time, independent
    of (and in addition to) :func:`load_written_kinds`'s coarser per-kind
    gate, so a crash partway through writing one kind's metrics never
    produces a duplicate on the next run."""
    stmt = select(ImpactReading.metric, ImpactReading.kind).where(
        ImpactReading.tool_execution_id == tool_execution_id
    )
    result = await session.execute(stmt)
    return {(row[0], row[1]) for row in result.all()}


def execution_t(execution: ToolExecution) -> date:
    """The write's execution date — ADR-077 decision 2's ``T``.

    ``ToolExecution`` has no dedicated ``executed_at`` column (#305/#1040
    predate this need); ``updated_at`` is the best available proxy: it is
    bumped by ``onupdate=func.now()`` on the very update that flips
    ``status`` to ``succeeded``
    (``services.execution.dispatch.mark_execution_finished`` ->
    ``ToolExecutionsRepo.update_status``), so it reads as "when the TikTok
    write actually completed," not merely "when the row was first queued"
    (``created_at``). A genuine schema gap, flagged in the PR body rather
    than silently worked around.
    """
    return execution.updated_at.date()


def extract_payload(execution: ToolExecution) -> dict:
    return json.loads(execution.payload_json or "{}")


async def load_daily_series(
    session: AsyncSession,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    start: date,
    end: date,
) -> dict[date, RawDailyRecord]:
    """One product's daily series over ``[start, end]``, keyed by calendar day.

    Absent entirely (no rows at all — the reference-shop-only daily topup
    gap this task must degrade gracefully against, PLAN.md's flagged gaps)
    simply returns ``{}``; ``services.impact`` treats a missing day as "no
    information," never zero, and reports a below-floor/suppressed outcome
    rather than raising.
    """
    stmt = select(AnalyticsPerformanceInterval).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == _DAILY_PRODUCT_GRAIN,
        AnalyticsPerformanceInterval.tiktok_product_id == tiktok_product_id,
        AnalyticsPerformanceInterval.start_date >= start,
        AnalyticsPerformanceInterval.start_date <= end,
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    def _dec(value: int | Decimal | None) -> Decimal | None:
        return None if value is None else Decimal(value)

    out: dict[date, RawDailyRecord] = {}
    for row in rows:
        out[row.start_date] = RawDailyRecord(
            impressions=_dec(row.impressions),
            ctr=row.ctr,
            conversion_rate=row.conversion_rate,
            items_sold=_dec(row.items_sold),
            gmv=row.gmv,
            sku_orders=_dec(row.sku_orders),
            visitors=_dec(row.visitors),
        )
    return out


async def load_touch_dates(
    session: AsyncSession,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    exclude_execution_id: uuid.UUID,
) -> list[date]:
    """Execution dates of every *other* succeeded, classifiable execution
    against this product — the raw input both the confounding check
    (ADR-077 decision 2) and the control-candidate ``touched`` flag
    (decision 3) derive from."""
    stmt = select(ToolExecution).where(
        ToolExecution.shop_id == shop_id,
        ToolExecution.status == TERMINAL_SUCCEEDED,
        ToolExecution.tool_name.in_(MEASURABLE_TOOL_NAMES),
        ToolExecution.id != exclude_execution_id,
    )
    result = await session.execute(stmt)
    dates: list[date] = []
    for row in result.scalars().all():
        payload = extract_payload(row)
        if str(payload.get("product_id")) == tiktok_product_id:
            dates.append(execution_t(row))
    return dates


def _resolve_first_active_date(product: Product, t: date) -> date:
    """``ControlCandidate.first_active_date`` — ``Product.tiktok_created_at``
    when known, else ``t`` itself, which fails ADR-077 decision 3's "active
    < 14 days" disqualifier safely: an unknown activation date is never
    treated as long-active."""
    if product.tiktok_created_at is not None:
        return product.tiktok_created_at.date()
    return t


async def load_control_candidates(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    target_tiktok_product_id: str,
    exclude_execution_id: uuid.UUID,
    series_start: date,
    series_end: date,
    t: date,
) -> list[ControlCandidate]:
    """Same-shop sibling products as raw ``ControlCandidate``s.

    ``services.impact.control_pool.select_control_pool`` (#1042) applies
    every eligibility/quality rule (touched, active < 14 days, pre-window
    completeness, volume floor, correlation quality bar) — this function
    only fetches the plain-data inputs that decision requires.
    """
    stmt = (
        select(Product)
        .where(
            Product.shop_id == shop_id,
            Product.tiktok_product_id != target_tiktok_product_id,
        )
        .limit(_MAX_CANDIDATE_PRODUCTS)
    )
    result = await session.execute(stmt)
    candidates: list[ControlCandidate] = []
    for product in result.scalars().all():
        daily = await load_daily_series(
            session, shop_id, product.tiktok_product_id, series_start, series_end
        )
        touch_dates = await load_touch_dates(
            session, shop_id, product.tiktok_product_id, exclude_execution_id
        )
        touched = any(series_start <= d <= series_end for d in touch_dates)
        candidates.append(
            ControlCandidate(
                product_id=product.tiktok_product_id,
                daily=daily,
                touched=touched,
                first_active_date=_resolve_first_active_date(product, t),
            )
        )
    return candidates


def build_reading_row(
    *,
    tool_execution_id: uuid.UUID,
    metric: str,
    kind: str,
    pre: Decimal | None,
    post: Decimal | None,
    expected: Decimal | None,
    incremental: Decimal | None,
    impact_pct: Decimal | None,
    confidence: str,
    control_set_json: str,
    computed_at: datetime,
) -> ImpactReading:
    """Build (but do not add/flush) one ``ImpactReading`` row — the caller
    owns the session lifecycle so it can batch every metric for one
    ``(execution, kind)`` into a single flush."""
    return ImpactReading(
        id=uuid.uuid4(),
        run_id=None,
        tool_execution_id=tool_execution_id,
        metric=metric,
        kind=kind,
        pre=pre,
        post=post,
        expected=expected,
        incremental=incremental,
        impact_pct=impact_pct,
        confidence=confidence,
        control_set_json=control_set_json,
        computed_at=computed_at,
    )

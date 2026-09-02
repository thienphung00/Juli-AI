"""Daily impact-reader orchestration — ADR-077 decision 5 (#1044).

Scans terminal ``listing.optimize_product`` executions whose T+7/T+14 has
elapsed with unwritten ``impact_readings``, computes them via the pure
``services.impact`` package, and persists them — idempotently, by
construction: the ``(tool_execution_id, metric, kind)`` unique constraint
(#1040) is the backstop, but this module does not rely on hitting it. Every
write path first checks :func:`queries.load_written_kinds` (coarse, per
execution+kind) and then :func:`queries.load_existing_metric_pairs` (fine,
per execution+metric+kind) before ever constructing a row, so a re-run over
identical state issues zero INSERTs and never touches the unique index at
all.

Elapse boundaries (ADR-077 decision 2's post windows, ``T+1..T+7`` /
``T+1..T+14``): a reading is due once ``(reference_date - T).days`` reaches
the window length, so ``T+6`` is not yet due for ``preliminary`` but ``T+7``
is, and ``T+13`` is not yet due for ``final`` but ``T+14`` is.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import ToolExecution
from juli_backend.services.impact import (
    METRIC_MAP,
    ControlPoolResult,
    MetricReading,
    MutationKind,
    WindowKind,
    compute_confidence,
    compute_run_readings,
    compute_windows,
    resolve_metric,
    select_control_pool,
    volume_floor_for,
    volume_indicator_for,
)
from juli_backend.workers.impact_reader.classify import classify_mutation_kinds, rollup_metric_for
from juli_backend.workers.impact_reader.queries import (
    build_reading_row,
    execution_t,
    extract_payload,
    load_control_candidates,
    load_daily_series,
    load_existing_metric_pairs,
    load_measurable_executions,
    load_touch_dates,
    load_written_kinds,
)

logger = logging.getLogger(__name__)

_ALL_KINDS: tuple[WindowKind, ...] = ("preliminary", "final")

#: ADR-077 decision 2's post-window lengths. Duplicated here from
#: ``services.impact.windows.POST_WINDOW_DAYS`` deliberately, as a plain
#: literal ``int`` map, rather than imported directly: the elapsed-time
#: comparison this module makes (``(reference_date - t).days >= N``) is a
#: distinct calculation from what ``POST_WINDOW_DAYS`` feeds (window
#: construction inside ``services.impact``), so re-declaring here keeps this
#: module's own boundary tests (``tests/unit/
#: test_worker_impact_reader_pipeline.py``) pinned to a literal ``7``/``14``
#: rather than to a value that could silently drift if the upstream
#: constant's *meaning* ever changed independently of this one.
_ELAPSE_DAYS: dict[WindowKind, int] = {"preliminary": 7, "final": 14}

#: ``services.impact.confidence.TierOutcome`` has six values;
#: ``impact_readings.confidence`` only allows five (see the model's
#: ``CheckConstraint``) — no ``below_floor``. ``below_floor`` is itself a
#: form of suppression in the persisted vocabulary: "not enough pre-period
#: traffic to trust any estimate" must land as ``suppressed``, never a write
#: failure and never a fabricated number (the below-floor/missing-daily-rows
#: case this reader must degrade gracefully against).
_PERSISTED_CONFIDENCE: dict[str, str] = {
    "cao": "cao",
    "trung_binh": "trung_binh",
    "thap": "thap",
    "below_floor": "suppressed",
    "suppressed": "suppressed",
    "confounded": "confounded",
}


@dataclass(frozen=True, slots=True)
class ImpactReaderRunResult:
    executions_scanned: int
    readings_written: int
    executions_skipped_unclassified: int


def _due_kinds(reference_date: date, t: date) -> list[WindowKind]:
    elapsed = (reference_date - t).days
    return [kind for kind in _ALL_KINDS if elapsed >= _ELAPSE_DAYS[kind]]


async def _is_confounded(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    exclude_execution_id: uuid.UUID,
    pre_start: date,
    post_end: date,
) -> bool:
    dates = await load_touch_dates(session, shop_id, tiktok_product_id, exclude_execution_id)
    return any(pre_start <= d <= post_end for d in dates)


def _metrics_needed(mutations: list[MutationKind], rollup_metric_key: str) -> set[str]:
    metrics = {rollup_metric_key}
    for mutation in mutations:
        mapping = METRIC_MAP[mutation]
        metrics.add(mapping.primary.key)
        metrics.update(spec.key for spec in mapping.secondary)
    return metrics


async def _process_kind(
    session: AsyncSession,
    *,
    execution: ToolExecution,
    tiktok_product_id: str,
    kind: WindowKind,
    t: date,
    mutations: list[MutationKind],
    rollup_metric_key: str,
    computed_at: datetime,
) -> int:
    """Compute and persist every not-yet-written metric reading for one
    ``(execution, kind)`` pair. Returns the number of rows written."""
    windows = compute_windows(t, kind)

    target_daily = await load_daily_series(
        session, execution.shop_id, tiktok_product_id, windows.pre_start, windows.post_end
    )
    confounded = await _is_confounded(
        session,
        shop_id=execution.shop_id,
        tiktok_product_id=tiktok_product_id,
        exclude_execution_id=execution.id,
        pre_start=windows.pre_start,
        post_end=windows.post_end,
    )
    candidates = await load_control_candidates(
        session,
        execution.shop_id,
        target_tiktok_product_id=tiktok_product_id,
        exclude_execution_id=execution.id,
        series_start=windows.pre_start,
        series_end=windows.post_end,
        t=t,
    )

    # One control-pool selection per distinct metric this run needs — the
    # correlated siblings that qualify as a control for `gmv` need not
    # qualify for `ctr` (control_pool.py's own contract).
    control_pool_by_metric: dict[str, ControlPoolResult] = {}
    control_daily_by_metric = {}
    for metric_key in _metrics_needed(mutations, rollup_metric_key):
        spec = resolve_metric(metric_key)
        result = select_control_pool(
            spec,
            target_daily,
            candidates,
            t,
            kind,
            volume_floor_for(spec),
            # The floor is calibrated in counts (orders / impressions /
            # visitors), so candidates must be screened on the family's
            # volume indicator, not on the metric itself — passing the
            # metric for a rate would disqualify every candidate (the
            # #1062 defect; see control_pool.py's module docstring).
            volume_of=volume_indicator_for(spec),
        )
        control_pool_by_metric[metric_key] = result
        control_daily_by_metric[metric_key] = result.control_daily

    run_readings = compute_run_readings(
        mutations, rollup_metric_key, target_daily, control_daily_by_metric, t, kind, confounded
    )

    readings_by_metric: dict[str, MetricReading] = {}
    for mutation_readings in run_readings.per_mutation:
        for reading in mutation_readings.all_readings():
            readings_by_metric.setdefault(reading.metric, reading)
    readings_by_metric.setdefault(run_readings.rollup.metric, run_readings.rollup)

    existing_pairs = await load_existing_metric_pairs(session, execution.id)

    written = 0
    for metric_key, reading in readings_by_metric.items():
        if (metric_key, kind) in existing_pairs:
            continue
        spec = resolve_metric(metric_key)
        control_result = control_pool_by_metric[metric_key]
        confidence_result = compute_confidence(spec, target_daily, control_result, reading)
        db_confidence = _PERSISTED_CONFIDENCE[confidence_result.tier]

        row = build_reading_row(
            tool_execution_id=execution.id,
            metric=metric_key,
            kind=kind,
            pre=reading.pre,
            post=reading.post,
            expected=reading.expected,
            incremental=reading.incremental,
            impact_pct=reading.impact_pct,
            confidence=db_confidence,
            control_set_json=json.dumps(control_result.as_control_set_json()),
            computed_at=computed_at,
        )
        session.add(row)
        written += 1

    if written:
        await session.flush()
    return written


async def run_daily_impact_reader(
    session: AsyncSession, reference_date: date
) -> ImpactReaderRunResult:
    """Scan every measurable terminal execution and compute+persist any
    ``impact_readings`` whose elapse boundary has passed and are not yet
    written. Does not commit — the caller (the Celery task) owns the
    transaction boundary.

    Per ADR-089 decision 2:
    - Enumerates via SECURITY DEFINER function (cross-tenant, identifiers only)
    - Loops over results, setting per-execution context
    - Fetches and processes each execution under its own shop scope
    """
    enumerated = await load_measurable_executions(session)
    computed_at = datetime.now(UTC)

    scanned = 0
    written_total = 0
    skipped_unclassified = 0

    for enum_result in enumerated:
        scanned += 1

        # Set per-execution context: this execution's shop (ADR-089 decision 2)
        async with with_shop_scope(session, enum_result.shop_id):
            # Fetch the full execution row under shop scope
            stmt = select(ToolExecution).where(ToolExecution.id == enum_result.execution_id)
            result = await session.execute(stmt)
            execution = result.scalar_one_or_none()

            # Should always exist (enumeration returned it), but fail safe
            if execution is None:
                logger.warning(
                    "impact_reader_execution_vanished",
                    extra={"execution_id": str(enum_result.execution_id)},
                )
                continue

            t = execution_t(execution)
            due = _due_kinds(reference_date, t)
            if not due:
                continue

            written_kinds = await load_written_kinds(session, execution.id)
            pending_kinds = [kind for kind in due if kind not in written_kinds]
            if not pending_kinds:
                continue

            payload = extract_payload(execution)
            tiktok_product_id = str(payload.get("product_id") or "")
            mutations = classify_mutation_kinds(payload)
            if not mutations or not tiktok_product_id:
                skipped_unclassified += 1
                logger.info(
                    "impact_reader_execution_unclassified",
                    extra={"execution_id": str(execution.id), "tool_name": execution.tool_name},
                )
                continue

            rollup_metric_key = rollup_metric_for(mutations).key

            for kind in pending_kinds:
                written_total += await _process_kind(
                    session,
                    execution=execution,
                    tiktok_product_id=tiktok_product_id,
                    kind=kind,
                    t=t,
                    mutations=mutations,
                    rollup_metric_key=rollup_metric_key,
                    computed_at=computed_at,
                )

    return ImpactReaderRunResult(
        executions_scanned=scanned,
        readings_written=written_total,
        executions_skipped_unclassified=skipped_unclassified,
    )

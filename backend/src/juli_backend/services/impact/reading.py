"""Per-metric, per-mutation, and run-level readings — orchestrates
``metric_map.py`` (ADR-077 decision 1) and ``compute.py`` (decision 2) into
the shapes a future beat task (#1044) will map onto ``ImpactReading`` rows.

This module does not select or pool control products (ADR-077 decision 3,
#1042) and does not assign confidence tiers or enforce volume floors
(decision 4, #1043) — it accepts an already-resolved control series per
metric and reports only what decision 2's formula and the ``confounded`` rule
define: a plain ``status`` of ``"ok"`` or ``"confounded"``. Callers that need
a full ``cao``/``trung_binh``/``thap`` confidence tier compose #1043's output
on top of this module's ``MetricReading``, they do not get it from here.

**Confounded runs (ADR-077 decision 2).** A second Juli run on the same
product inside either the pre or post window marks the reading confounded
(suppressed) — detecting *that* condition means querying ``tool_executions``
for other runs against the same product, which is I/O this pure package does
not perform. The caller passes the already-decided ``confounded: bool`` in;
when set, every numeric field on the resulting reading is ``None`` and
``status`` is ``"confounded"`` — the reading is not trustworthy at all, not
merely percent-suppressed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from juli_backend.services.impact.compute import (
    PercentSuppressedReason,
    compute_expected,
    compute_growth,
    compute_impact_pct,
    compute_incremental,
    compute_post,
    compute_pre,
)
from juli_backend.services.impact.metric_map import (
    METRIC_MAP,
    MetricSpec,
    MutationKind,
    RawDailyRecord,
    resolve_metric,
)
from juli_backend.services.impact.windows import WindowKind

ReadingStatus = Literal["ok", "confounded"]

DailySeries = Mapping[date, RawDailyRecord]


@dataclass(frozen=True, slots=True)
class MetricReading:
    """One ``(metric, kind)`` reading — the shape a future beat task maps
    onto one ``ImpactReading`` row's numeric columns. ``confidence`` (the
    ``cao``/``trung_binh``/``thap``/``suppressed``/``confounded`` tier the
    ORM column requires) is deliberately not produced here — #1043 owns tier
    assignment; ``status`` only distinguishes the one tier this slice can
    determine on its own (``confounded``) from everything else (``"ok"``,
    including percent-suppressed cases, which are reported via
    ``percent_suppressed_reason`` instead of collapsing into ``status``)."""

    metric: str
    kind: WindowKind
    pre: Decimal | None
    post: Decimal | None
    growth: Decimal | None
    expected: Decimal | None
    incremental: Decimal | None
    impact_pct: Decimal | None
    percent_suppressed_reason: PercentSuppressedReason | None
    status: ReadingStatus


@dataclass(frozen=True, slots=True)
class MutationReadings:
    """One mutation's primary + secondary readings."""

    mutation: MutationKind
    primary: MetricReading
    secondary: tuple[MetricReading, ...]

    def all_readings(self) -> tuple[MetricReading, ...]:
        return (self.primary, *self.secondary)


@dataclass(frozen=True, slots=True)
class RunReadings:
    """One run's per-mutation readings plus the run-level rollup reading
    keyed on the ActionCard's ``expected_impact.metric`` (acceptance
    criterion: multi-mutation runs produce per-mutation readings **plus** a
    run-level rollup)."""

    per_mutation: tuple[MutationReadings, ...]
    rollup: MetricReading


def _extract_series(daily: DailySeries, metric: MetricSpec) -> dict[date, Decimal | None]:
    return {day: metric.extractor(record) for day, record in daily.items()}


def compute_metric_reading(
    metric: MetricSpec,
    target_daily: DailySeries,
    control_daily: DailySeries,
    t: date,
    kind: WindowKind,
    confounded: bool = False,
) -> MetricReading:
    """Compute the full DiD reading for one metric.

    ``target_daily``/``control_daily`` cover whatever calendar range the
    caller has data for — this function reads only the days its windows
    need and is silent (returns ``None`` fields, never raises) about gaps.
    """
    if confounded:
        return MetricReading(
            metric=metric.key,
            kind=kind,
            pre=None,
            post=None,
            growth=None,
            expected=None,
            incremental=None,
            impact_pct=None,
            percent_suppressed_reason=None,
            status="confounded",
        )

    target_series = _extract_series(target_daily, metric)
    control_series = _extract_series(control_daily, metric)

    pre = compute_pre(target_series, t)
    post = compute_post(target_series, t, kind)
    control_pre = compute_pre(control_series, t)
    control_post = compute_post(control_series, t, kind)

    growth = compute_growth(control_pre, control_post)
    expected = compute_expected(pre, growth)
    incremental = compute_incremental(post, expected)
    impact_pct, reason = compute_impact_pct(pre, incremental, expected)

    return MetricReading(
        metric=metric.key,
        kind=kind,
        pre=pre,
        post=post,
        growth=growth,
        expected=expected,
        incremental=incremental,
        impact_pct=impact_pct,
        percent_suppressed_reason=reason,
        status="ok",
    )


def compute_mutation_readings(
    mutation: MutationKind,
    target_daily: DailySeries,
    control_daily_by_metric: Mapping[str, DailySeries],
    t: date,
    kind: WindowKind,
    confounded: bool = False,
) -> MutationReadings:
    """Compute the primary + secondary readings for one mutation, per the
    ``METRIC_MAP`` (ADR-077 decision 1).

    ``control_daily_by_metric`` is keyed by metric key because control
    selection (#1042) is per-metric — the correlation that qualifies a
    sibling product as a control for ``gmv`` need not qualify it for ``ctr``.
    """
    mapping = METRIC_MAP[mutation]

    def _reading(metric: MetricSpec) -> MetricReading:
        control_daily = control_daily_by_metric[metric.key]
        return compute_metric_reading(metric, target_daily, control_daily, t, kind, confounded)

    primary_reading = _reading(mapping.primary)
    secondary_readings = tuple(_reading(metric) for metric in mapping.secondary)
    return MutationReadings(
        mutation=mutation, primary=primary_reading, secondary=secondary_readings
    )


def compute_run_readings(
    mutations: Sequence[MutationKind],
    rollup_metric: str,
    target_daily: DailySeries,
    control_daily_by_metric: Mapping[str, DailySeries],
    t: date,
    kind: WindowKind,
    confounded: bool = False,
) -> RunReadings:
    """Compute every per-mutation reading for a run plus one run-level
    rollup reading keyed on ``rollup_metric`` (the ActionCard's
    ``expected_impact.metric``).

    ``rollup_metric`` need not be distinct from any per-mutation metric — a
    single-mutation run's rollup is typically the same metric as that
    mutation's primary, which is expected and not deduplicated here; the
    persistence layer (#1044), which knows the ``impact_readings`` unique
    constraint, owns whether that becomes one row or two identical-valued
    ones.

    Raises ``ValueError`` if ``mutations`` is empty and ``KeyError`` (via
    ``resolve_metric``) if ``rollup_metric`` is not a metric this package
    knows how to compute — both are caller-configuration bugs worth failing
    loudly on.
    """
    if not mutations:
        raise ValueError("compute_run_readings requires at least one mutation")

    per_mutation = tuple(
        compute_mutation_readings(
            mutation, target_daily, control_daily_by_metric, t, kind, confounded
        )
        for mutation in mutations
    )

    rollup_spec = resolve_metric(rollup_metric)
    rollup_control = control_daily_by_metric[rollup_spec.key]
    rollup_reading = compute_metric_reading(
        rollup_spec, target_daily, rollup_control, t, kind, confounded
    )

    return RunReadings(per_mutation=per_mutation, rollup=rollup_reading)

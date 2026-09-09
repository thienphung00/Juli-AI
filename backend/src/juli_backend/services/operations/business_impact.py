"""Business impact — the fourth unconflated metric, and what it says when
nothing has been measured (issue #1657 / W8-E / P10-5, parent PRD #1652,
ADR-077).

The question is "did the action actually improve the target metric?", and the
answer is the control-adjusted before/after delta the impact reader already
computed and stored on ``impact_readings``. This module does not compute a
reading, does not schedule one and does not write one; producing a real
reading is #1339's gate and an owner decision, not engineering. It reads.

**The absence is the load-bearing case.** With no countable reading, this
module returns :class:`NoReadings` — its own type, which does not compare
equal to ``0``, to ``0.0``, to ``Decimal(0)``, to ``None`` or to any string.
``0`` is a claim about the world ("we measured no change"); :class:`NoReadings`
is a statement about our knowledge of it ("we measured nothing"). #1226 is the
incident where those two shared a representation, and the whole point of this
slice is that they structurally cannot here: they are different Python types,
so the inequality holds without anybody remembering to preserve it.

**What counts as a reading is not decided here.** A reading with confidence
``suppressed`` (insufficient signal) or ``confounded`` (a competing change) is
not an incremental impact — #1226's rule, made structural at the read surface
by #1338's ``impact_honesty.COUNTABLE_CONFIDENCES``. This module does not
re-apply that rule and does not restate the tier list: it consumes
``outcome_chain``'s already-partitioned link, which applies it once. The
excluded rows still travel, each under its OWN ``confidence`` value, so
"two suppressed and one confounded" never degrades into a single collapsed
category and never into zero impact.

**The chain is consumed, not rebuilt.** Exactly one call to
:func:`~juli_backend.services.operations.outcome_chain.load_outcome_chain`,
which is itself one database statement. This module imports no query builder
and no model, so a second client-side join across ``action_cards`` /
``tool_executions`` / ``workflow_outcome_records`` / ``impact_readings`` — the
thing #1655 removed — is not merely discouraged here, it is unavailable.

**No threshold is declared here.** The volume floors, tier multipliers and
control-set minimum live once, in ``services/impact`` (``confidence.py``,
``control_pool.py``), and are applied upstream by the reader when it assigns a
row's tier. The one ``services/impact`` decision this module makes for itself
— which ``kind`` supersedes which — reads ``windows.POST_WINDOW_DAYS`` rather
than restating ADR-077 decision 2's window lengths.

**Per metric, never summed across metrics.** ``incremental`` carries the raw
metric on its own scale (``Numeric(18, 2)``), so adding a GMV delta to an
impressions delta produces a number with no unit. The result therefore holds
one :class:`MetricImpact` per metric, each with its own ``n``; the run-level
``n`` is a count of readings, which is unit-free and therefore addable. There
is deliberately no single blended score: a good number on one metric hiding a
bad one on another is the exact artefact PRD #1652 exists to prevent.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.impact.windows import POST_WINDOW_DAYS, WindowKind
from juli_backend.services.operations.outcome_chain import (
    CountableReading,
    EmptyLink,
    ExcludedReading,
    LinkReason,
    load_outcome_chain,
)

#: Which ``impact_readings.kind`` supersedes which, most authoritative first.
#:
#: ``uq_impact_readings_execution_metric_kind`` is ``(tool_execution_id,
#: metric, kind)``, so ONE execution can legitimately hold both a preliminary
#: and a final reading for one metric — an aggregate that does not choose
#: counts the same measurement twice. The choice is the longer post window:
#: ADR-077 decision 2 reads preliminary early so a seller is not left staring
#: at "pending" for two weeks, and final later over more days of evidence, so
#: final supersedes preliminary once it exists. Derived from
#: ``services/impact/windows.POST_WINDOW_DAYS`` rather than restated, so the
#: window lengths keep their single declaration and a future kind cannot be
#: silently dropped by a hardcoded pair.
KIND_PRECEDENCE: tuple[WindowKind, ...] = tuple(
    sorted(POST_WINDOW_DAYS, key=lambda kind: POST_WINDOW_DAYS[kind], reverse=True)
)


@dataclass(frozen=True, slots=True)
class UnmeasuredReading:
    """A reading whose confidence tier IS countable but which carries no
    ``incremental`` value.

    ``impact_readings.incremental`` is nullable, and a null one is not a zero
    delta — coercing it would be the same dishonesty as reporting ``0`` for no
    readings at all, one row further down. So such a row is never counted in
    ``n``, never added into a delta, and is reported here under its own name.
    """

    reading_id: uuid.UUID
    metric: str
    kind: str
    confidence: str


@dataclass(frozen=True, slots=True)
class MetricImpact:
    """One metric's measured business impact — a delta that never travels
    without its denominator.

    ``kind`` is the kind actually counted for this metric (see
    :data:`KIND_PRECEDENCE`), stated rather than left implicit. ``n`` is the
    number of readings the delta is the sum of, so a single observation cannot
    read as a trend. ``pct`` is the mean ``impact_pct`` and is ``None`` unless
    every counted reading carries one — a partial mean is a made-up number.
    """

    metric: str
    kind: str
    n: int
    delta: Decimal
    pct: Decimal | None
    confidences: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BusinessImpact:
    """The measured answer: at least one countable reading exists.

    ``excluded`` and ``unmeasured`` ride alongside even when metrics are
    populated, so an audit surface never has to ask a second question to learn
    that three of five metrics were suppressed.
    """

    workflow_run_id: uuid.UUID
    metrics: tuple[MetricImpact, ...]
    n: int
    excluded: tuple[ExcludedReading, ...] = ()
    unmeasured: tuple[UnmeasuredReading, ...] = ()

    def delta_for(self, metric: str) -> Decimal | None:
        """This metric's delta, or ``None`` when it was not measured.

        ``None`` here means "not among the measured metrics", which is why
        there is no run-level ``delta`` property to ask instead: a single
        number across metrics of different units would have no meaning.
        """
        for entry in self.metrics:
            if entry.metric == metric:
                return entry.delta
        return None


@dataclass(frozen=True, slots=True)
class NoReadings:
    """The honest answer when nothing countable has been measured.

    Deliberately a distinct type from :class:`BusinessImpact`, so
    ``no_readings != measured_zero`` holds by construction rather than by
    convention. It compares equal to no number and to no string: a frozen
    dataclass returns ``NotImplemented`` for a foreign operand, and Python's
    fallback makes the comparison ``False``. It is also truthy, so a caller
    writing ``if not result`` cannot accidentally read it as a zero.

    ``reason`` and ``because`` are #1655's vocabulary carried through
    unchanged — ``pending`` (the window has not closed), ``unavailable`` (no
    write was measured) or ``missing`` (the reading should exist and does
    not). An absence without a reason is a bare null wearing a name.
    """

    workflow_run_id: uuid.UUID
    reason: LinkReason
    because: str
    excluded: tuple[ExcludedReading, ...] = ()
    unmeasured: tuple[UnmeasuredReading, ...] = ()


BusinessImpactResult = BusinessImpact | NoReadings


async def business_impact(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> BusinessImpactResult:
    """Business impact for one run: the measured delta per metric, or an
    explicit :class:`NoReadings`.

    ``now`` is passed straight through to the chain so the ``pending`` vs
    ``missing`` boundary stays testable at the exact window edge. Raises
    :class:`~juli_backend.services.operations.outcome_chain.RunNotFoundError`
    when no run exists — an absent run is not an unmeasured one.
    """
    chain = await load_outcome_chain(session, workflow_run_id, now=now)
    link = chain.incremental_impact

    if isinstance(link, EmptyLink):
        # No countable reading at all. The chain already knows whether that is
        # because none is due yet, none can ever exist, or one should exist and
        # does not — and whether excluded rows are the reason.
        return NoReadings(
            workflow_run_id=workflow_run_id,
            reason=link.reason,
            because=link.because,
            excluded=link.excluded_readings,
        )

    counted = _at_the_superseding_kind(link.readings)
    measured = tuple(r for r in counted if r.incremental is not None)
    unmeasured = tuple(
        UnmeasuredReading(
            reading_id=r.reading_id,
            metric=r.metric,
            kind=r.kind,
            confidence=r.confidence,
        )
        for r in counted
        if r.incremental is None
    )

    if not measured:
        labels = ", ".join(f"{r.metric}={r.kind}" for r in unmeasured)
        return NoReadings(
            workflow_run_id=workflow_run_id,
            reason=LinkReason.MISSING,
            because=(
                f"{len(unmeasured)} countable impact_readings row(s) exist for this run "
                f"({labels}) but none carries an incremental value. A null incremental is "
                "not a zero delta: the row says a measurement was attempted, not that the "
                "measurement came back at zero."
            ),
            excluded=link.excluded_readings,
            unmeasured=unmeasured,
        )

    return BusinessImpact(
        workflow_run_id=workflow_run_id,
        metrics=_per_metric(measured),
        n=len(measured),
        excluded=link.excluded_readings,
        unmeasured=unmeasured,
    )


def _grouped_by_metric(
    readings: tuple[CountableReading, ...],
) -> dict[str, list[CountableReading]]:
    """Readings bucketed by ``metric``, in first-seen order.

    Both the kind choice and the per-metric delta partition the same way, and a
    metric is the unit both are about — ADR-077 decision 1 reports per-mutation
    readings, and ``incremental`` is on the metric's own scale.
    """
    grouped: dict[str, list[CountableReading]] = defaultdict(list)
    for reading in readings:
        grouped[reading.metric].append(reading)
    return grouped


def _at_the_superseding_kind(
    readings: tuple[CountableReading, ...],
) -> tuple[CountableReading, ...]:
    """Keep, for each metric, only the readings at its most authoritative
    available ``kind``.

    Applied per metric rather than per ``(execution, metric)`` because
    ``CountableReading`` does not carry ``tool_execution_id`` — see this
    module's note in ``MODULE.md``. For the one-write-per-run shape the runner
    produces today the two are the same partition; where a run holds several
    writes touching the same metric, a metric answered ``final`` by one write
    and only ``preliminary`` by another counts the final ones. That is the
    conservative direction: it can under-count readings, never double-count
    one measurement.
    """
    kept: list[CountableReading] = []
    for group in _grouped_by_metric(readings).values():
        for kind in KIND_PRECEDENCE:
            at_kind = [r for r in group if r.kind == kind]
            if at_kind:
                kept.extend(at_kind)
                break
        else:
            # A kind outside `POST_WINDOW_DAYS` cannot reach here through the
            # `ck_impact_readings_kind` CHECK; keeping the group whole rather
            # than dropping it silently is the honest fallback if it ever does.
            kept.extend(group)
    return tuple(kept)


def _per_metric(measured: tuple[CountableReading, ...]) -> tuple[MetricImpact, ...]:
    """One :class:`MetricImpact` per metric, in metric order, each carrying
    its own ``n``. Never a cross-metric sum — see the module docstring."""
    by_metric = _grouped_by_metric(measured)
    impacts: list[MetricImpact] = []
    for metric in sorted(by_metric):
        group = by_metric[metric]
        deltas = [r.incremental for r in group if r.incremental is not None]
        pcts = [r.impact_pct for r in group if r.impact_pct is not None]
        impacts.append(
            MetricImpact(
                metric=metric,
                kind=group[0].kind,
                n=len(group),
                delta=sum(deltas, Decimal(0)),
                pct=(sum(pcts, Decimal(0)) / len(pcts) if len(pcts) == len(group) else None),
                confidences=tuple(r.confidence for r in group),
            )
        )
    return tuple(impacts)


__all__ = [
    "KIND_PRECEDENCE",
    "BusinessImpact",
    "BusinessImpactResult",
    "MetricImpact",
    "NoReadings",
    "UnmeasuredReading",
    "business_impact",
]

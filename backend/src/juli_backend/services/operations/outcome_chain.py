"""The five-link outcome chain, in one query — issue #1655 (W8-C / P10-3),
parent PRD #1652, ADR-077.

Given a ``workflow_run_id`` this module answers the whole post-hoc question:

1. **Recommendation** — the ``ActionCard`` whose approval created the run,
   reached through ``workflow_runs.action_card_id`` (the FK migration 040 /
   #1269 added and which nothing has read until now).
2. **Action** — the ``ToolExecution`` ledger rows on
   ``tool_executions.workflow_run_id``.
3. **TikTok state change** — the ``WorkflowOutcomeRecord`` rows joined
   ``workflow_outcome_records.execution_id -> tool_executions.id``.
4. **Observed outcome** — the KPI window after the change: the ``post``
   values of this run's ``impact_readings``, which are by ADR-077 decision 2
   the mean of the target's own series over the post window ``[T+1, T+7]``
   (preliminary) or ``[T+1, T+14]`` (final).
5. **Incremental impact** — the control-adjusted ``incremental``, from
   *countable* readings only.

Links 4 and 5 both read ``impact_readings`` and are deliberately NOT the same
link: link 4 is what was observed, link 5 is how much of it Juli caused. A
suppressed reading can have an honest observed value and no incremental one.

**Why this module lives in ``services/operations/``.** The three tables past
the ledger already have their owners here: ``outcome_tracking.py`` owns
``workflow_outcome_records`` and ``impact_honesty.py`` owns the read-side
honesty rule this module must not re-implement. ``services/impact`` is a
deliberately pure library (no I/O, no wall-clock reads — see its package
docstring), so a module that both queries a session and reads a clock cannot
live there; and ``workers/impact_reader`` is a worker package that
``services`` may not import at all (``.importlinter.toml``:
``services -> workers`` is not an allowed edge). ``operations`` is the one
existing home that already owns "what happened after an approved execution",
which is exactly this question.

**Three reasons, never a bare null.** An empty link always says why:
``pending`` (the fact has not happened yet), ``unavailable`` (the fact cannot
happen for this run) or ``missing`` (it should exist and does not). An
operator taught that ``null`` means nothing learns to ignore nulls, which is
how #1226's dishonesty returns in a different costume. There is no fourth
reason and no alias.

**The honesty rule at link 5.** A reading whose ``confidence`` is
``suppressed`` or ``confounded`` is never an incremental impact (#1226,
#1338). This module does not re-declare that rule: it reads
``impact_honesty.COUNTABLE_CONFIDENCES`` / ``EXCLUDED_CONFIDENCES``, the same
values ``list_impact_readings_honest`` filters on. Excluded readings are
carried on the empty link under their OWN names, so ``suppressed``
(insufficient signal) and ``confounded`` (a competing change) stay
distinguishable from each other and neither is ever rendered as zero impact.

**One database call.** The chain is a single ``SELECT`` with four outer joins,
executed once — not four fetches assembled in Python. A client-side join is
exactly the hand-joining-by-eye this slice exists to remove, and it is also
where a partially-failed fetch silently becomes an empty link with no reason.
Classification (which reason a given empty link carries) is then pure Python
over that one result set plus the clock — that is reading the answer, not
asking a second question.

Read-only: this module never writes, and adds no schema.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Row, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    ActionCard,
    ImpactReading,
    ToolExecution,
    WorkflowOutcomeRecord,
    WorkflowRun,
)
from juli_backend.services.agent.status import NON_TERMINAL_STATUSES, WorkflowRunStatus
from juli_backend.services.impact.windows import WindowKind, post_window
from juli_backend.services.operations.impact_honesty import (
    COUNTABLE_CONFIDENCES,
    EXCLUDED_CONFIDENCES,
)

#: The ledger status a `ToolExecution` carries once its vendor write completed
#: — `runner/ledger.py::LedgerStatus.SUCCEEDED`, and also
#: `workers/impact_reader/queries.py::TERMINAL_SUCCEEDED`. Referenced by value
#: rather than imported because `LedgerStatus` and the legacy Celery-approval
#: vocabulary are two distinct enums over the same column (see
#: `ToolExecution`'s docstring), and this module must recognise a completed
#: write from either writer.
_SUCCEEDED = "succeeded"

#: `impact_readings.kind` this module's readiness clock is calibrated against.
#: ADR-077 decision 2 reads *preliminary* first (T+7) so a seller is not left
#: staring at "pending" for two weeks — so the preliminary window is the one
#: whose elapse decides `pending` vs `missing`. The boundary itself is never
#: re-declared here: it comes from `services/impact/windows.post_window`.
_READINESS_KIND: WindowKind = "preliminary"


class RunNotFoundError(LookupError):
    """No ``workflow_runs`` row for the requested id.

    Distinct in kind from every empty link below: an absent *run* has no
    chain to explain at all, so it is an error rather than five reasons.
    Carries a machine-readable ``error_code`` so a caller can map it without
    string-matching the message.
    """

    error_code = "workflow_run_not_found"

    def __init__(self, workflow_run_id: uuid.UUID) -> None:
        self.workflow_run_id = workflow_run_id
        super().__init__(f"No workflow_runs row for id {workflow_run_id!s}.")


class LinkReason(StrEnum):
    """Why a link is empty. Exactly three members, pairwise distinct, and
    none of them is ``None`` — an empty link always carries one of these,
    never a bare null, and never a fourth value."""

    #: The fact has not happened yet — T+7 has not elapsed, the webhook has
    #: not arrived, the run is still going.
    PENDING = "pending"
    #: The fact CANNOT happen for this run — the run declined, no write was
    #: attempted, the legacy row carries no `action_card_id`.
    UNAVAILABLE = "unavailable"
    #: The fact SHOULD exist and does not — the write completed and the
    #: window elapsed, but nobody wrote the row.
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class ExcludedReading:
    """A reading that exists but is not an incremental impact, under its own
    name. ``confidence`` is the row's own ``suppressed``/``confounded`` value
    — never normalised, never collapsed into the other, never zero."""

    reading_id: uuid.UUID
    metric: str
    kind: str
    confidence: str


@dataclass(frozen=True, slots=True)
class EmptyLink:
    """An empty link and its explanation.

    ``excluded_readings`` is only ever non-empty on the incremental-impact
    link, where readings DO exist but none is countable: it carries each
    non-countable reading under its own label so that "two suppressed and one
    confounded" never degrades into "no impact" or into a single collapsed
    category. Every other link leaves it at ``()``.
    """

    reason: LinkReason
    because: str
    excluded_readings: tuple[ExcludedReading, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationLink:
    """Link 1 — the ``ActionCard`` whose approval created this run."""

    action_card_id: uuid.UUID
    workflow_key: str
    title: str
    severity: str
    priority: int
    status: str


@dataclass(frozen=True, slots=True)
class ActionExecution:
    """One ``tool_executions`` ledger row belonging to this run."""

    tool_execution_id: uuid.UUID
    tool_name: str
    operation: str | None
    tool_call_id: str | None
    status: str
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class ActionLink:
    """Link 2 — what this run actually dispatched."""

    executions: tuple[ActionExecution, ...]


@dataclass(frozen=True, slots=True)
class StateChangeRecord:
    """One ``workflow_outcome_records`` row: the recorded TikTok state change
    for one execution."""

    record_id: uuid.UUID
    execution_id: uuid.UUID
    workflow_id: str
    execution_status: str
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class StateChangeLink:
    """Link 3 — the state change TikTok recorded."""

    records: tuple[StateChangeRecord, ...]


@dataclass(frozen=True, slots=True)
class ObservedMetric:
    """One metric's observed KPI window after the change — ADR-077 decision
    2's post-window value, exactly as the impact reader computed it."""

    reading_id: uuid.UUID
    metric: str
    kind: str
    pre: Decimal | None
    post: Decimal


@dataclass(frozen=True, slots=True)
class ObservedOutcomeLink:
    """Link 4 — what the KPI window said after the change."""

    observations: tuple[ObservedMetric, ...]


@dataclass(frozen=True, slots=True)
class CountableReading:
    """One countable incremental-impact reading — confidence guaranteed to be
    in :data:`~juli_backend.services.operations.impact_honesty.COUNTABLE_CONFIDENCES`
    by construction."""

    reading_id: uuid.UUID
    metric: str
    kind: str
    confidence: str
    incremental: Decimal | None
    impact_pct: Decimal | None
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class IncrementalImpactLink:
    """Link 5 — how much of the observed change Juli caused.

    ``excluded_readings`` rides alongside even when countable readings exist,
    so an audit surface never has to go and ask a second question to learn
    that three of five metrics were suppressed.
    """

    readings: tuple[CountableReading, ...]
    excluded_readings: tuple[ExcludedReading, ...] = ()


Link = (
    RecommendationLink
    | ActionLink
    | StateChangeLink
    | ObservedOutcomeLink
    | IncrementalImpactLink
    | EmptyLink
)


@dataclass(frozen=True, slots=True)
class OutcomeChain:
    """The complete post-hoc chain for one run: five links, each populated or
    carrying an explicit reason."""

    workflow_run_id: uuid.UUID
    status: str
    stop_reason: str | None
    recommendation: RecommendationLink | EmptyLink
    action: ActionLink | EmptyLink
    state_change: StateChangeLink | EmptyLink
    observed_outcome: ObservedOutcomeLink | EmptyLink
    incremental_impact: IncrementalImpactLink | EmptyLink

    @property
    def links(self) -> tuple[tuple[str, Link], ...]:
        """The five links in chain order, each under its name. Exactly five,
        always — a link is never omitted, only explained."""
        return (
            ("recommendation", self.recommendation),
            ("action", self.action),
            ("state_change", self.state_change),
            ("observed_outcome", self.observed_outcome),
            ("incremental_impact", self.incremental_impact),
        )

    @property
    def countable_readings(self) -> tuple[CountableReading, ...]:
        """The gate-closing answer to "what was the impact": zero rows when
        no countable reading exists, no matter how many suppressed or
        confounded ones do (#1226, #1338)."""
        if isinstance(self.incremental_impact, EmptyLink):
            return ()
        return self.incremental_impact.readings


# --------------------------------------------------------------------------
# The one query
# --------------------------------------------------------------------------


def _chain_statement(workflow_run_id: uuid.UUID):
    """One ``SELECT`` over the whole chain: four LEFT OUTER JOINs from
    ``workflow_runs``, so a run with no card / no execution / no outcome
    record / no reading still returns its own row with NULLs rather than no
    row at all. That NULL-vs-row distinction is what makes an empty link
    explainable instead of indistinguishable from a missing run.

    ``impact_readings`` is reached by EITHER key ADR-077 decision 5 names —
    ``run_id`` (migration 034's FK) or ``tool_execution_id`` — because the
    two writers populate different ones: the daily reader writes
    ``run_id = NULL`` (``workers/impact_reader/queries.py::build_reading_row``)
    and attributes by execution, while a run-attributed reading carries
    ``run_id``. Requiring either alone would silently drop half the readings.
    """
    return (
        select(
            WorkflowRun.status.label("run_status"),
            WorkflowRun.stop_reason.label("run_stop_reason"),
            WorkflowRun.action_card_id.label("run_action_card_id"),
            ActionCard.id.label("card_id"),
            ActionCard.workflow_key.label("card_workflow_key"),
            ActionCard.title.label("card_title"),
            ActionCard.severity.label("card_severity"),
            ActionCard.priority.label("card_priority"),
            ActionCard.status.label("card_status"),
            ToolExecution.id.label("execution_id"),
            ToolExecution.tool_name.label("execution_tool_name"),
            ToolExecution.operation.label("execution_operation"),
            ToolExecution.tool_call_id.label("execution_tool_call_id"),
            ToolExecution.status.label("execution_status"),
            ToolExecution.updated_at.label("execution_updated_at"),
            WorkflowOutcomeRecord.id.label("record_id"),
            WorkflowOutcomeRecord.execution_id.label("record_execution_id"),
            WorkflowOutcomeRecord.workflow_id.label("record_workflow_id"),
            WorkflowOutcomeRecord.execution_status.label("record_execution_status"),
            WorkflowOutcomeRecord.executed_at.label("record_executed_at"),
            ImpactReading.id.label("reading_id"),
            ImpactReading.metric.label("reading_metric"),
            ImpactReading.kind.label("reading_kind"),
            ImpactReading.confidence.label("reading_confidence"),
            ImpactReading.pre.label("reading_pre"),
            ImpactReading.post.label("reading_post"),
            ImpactReading.incremental.label("reading_incremental"),
            ImpactReading.impact_pct.label("reading_impact_pct"),
            ImpactReading.computed_at.label("reading_computed_at"),
        )
        .select_from(WorkflowRun)
        .outerjoin(ActionCard, ActionCard.id == WorkflowRun.action_card_id)
        .outerjoin(ToolExecution, ToolExecution.workflow_run_id == WorkflowRun.id)
        .outerjoin(
            WorkflowOutcomeRecord,
            WorkflowOutcomeRecord.execution_id == ToolExecution.id,
        )
        .outerjoin(
            ImpactReading,
            or_(
                ImpactReading.run_id == WorkflowRun.id,
                ImpactReading.tool_execution_id == ToolExecution.id,
            ),
        )
        .where(WorkflowRun.id == workflow_run_id)
    )


async def load_outcome_chain(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> OutcomeChain:
    """The complete five-link chain for one run, in ONE database call.

    ``now`` is injectable so the ``pending`` vs ``missing`` boundary is
    testable at the exact window edge; it defaults to the wall clock. Raises
    :class:`RunNotFoundError` when no ``workflow_runs`` row exists — an
    absent run is not an empty link, it is an absent subject.
    """
    at = now or datetime.now(UTC)
    rows = (await session.execute(_chain_statement(workflow_run_id))).all()
    if not rows:
        raise RunNotFoundError(workflow_run_id)

    # Everything below is classification over the single result set already
    # in hand — no second fetch, and no fetch at all past this point.
    first = rows[0]
    executions = _collect_executions(rows)
    records = _collect_records(rows)
    readings = _collect_readings(rows)

    action = _classify_action(first, executions)
    recommendation = _classify_recommendation(first)
    state_change = _classify_state_change(first, executions, records, action)
    observed, incremental = _classify_impact(executions, readings, action, at)

    return OutcomeChain(
        workflow_run_id=workflow_run_id,
        status=first.run_status,
        stop_reason=first.run_stop_reason,
        recommendation=recommendation,
        action=action,
        state_change=state_change,
        observed_outcome=observed,
        incremental_impact=incremental,
    )


# --------------------------------------------------------------------------
# Row collection — the outer joins produce a cartesian product, so each
# entity is deduplicated by its own primary key, in first-seen order.
# --------------------------------------------------------------------------


def _collect_executions(rows: Sequence[Row]) -> tuple[ActionExecution, ...]:
    seen: dict[uuid.UUID, ActionExecution] = {}
    for row in rows:
        if row.execution_id is None or row.execution_id in seen:
            continue
        seen[row.execution_id] = ActionExecution(
            tool_execution_id=row.execution_id,
            tool_name=row.execution_tool_name,
            operation=row.execution_operation,
            tool_call_id=row.execution_tool_call_id,
            status=row.execution_status,
            executed_at=row.execution_updated_at,
        )
    return tuple(seen.values())


def _collect_records(rows: Sequence[Row]) -> tuple[StateChangeRecord, ...]:
    seen: dict[uuid.UUID, StateChangeRecord] = {}
    for row in rows:
        if row.record_id is None or row.record_id in seen:
            continue
        seen[row.record_id] = StateChangeRecord(
            record_id=row.record_id,
            execution_id=row.record_execution_id,
            workflow_id=row.record_workflow_id,
            execution_status=row.record_execution_status,
            executed_at=row.record_executed_at,
        )
    return tuple(seen.values())


@dataclass(frozen=True, slots=True)
class _ReadingRow:
    """One deduplicated ``impact_readings`` row, before it is split into the
    observed-outcome and incremental-impact links."""

    reading_id: uuid.UUID
    metric: str
    kind: str
    confidence: str
    pre: Decimal | None
    post: Decimal | None
    incremental: Decimal | None
    impact_pct: Decimal | None
    computed_at: datetime


def _collect_readings(rows: Sequence[Row]) -> tuple[_ReadingRow, ...]:
    seen: dict[uuid.UUID, _ReadingRow] = {}
    for row in rows:
        if row.reading_id is None or row.reading_id in seen:
            continue
        seen[row.reading_id] = _ReadingRow(
            reading_id=row.reading_id,
            metric=row.reading_metric,
            kind=row.reading_kind,
            confidence=row.reading_confidence,
            pre=row.reading_pre,
            post=row.reading_post,
            incremental=row.reading_incremental,
            impact_pct=row.reading_impact_pct,
            computed_at=row.reading_computed_at,
        )
    return tuple(seen.values())


# --------------------------------------------------------------------------
# Classification — why each empty link is empty
# --------------------------------------------------------------------------


def _classify_recommendation(first: Row) -> RecommendationLink | EmptyLink:
    """``action_card_id IS NULL`` is honest data, not a gap: runs created
    before migration 040 have no card and none was invented (there is
    deliberately no backfill), so no card can ever appear for them —
    ``unavailable``, never ``missing``. A card id that names no row is the
    opposite case: it SHOULD resolve and does not.
    """
    if first.run_action_card_id is None:
        return EmptyLink(
            reason=LinkReason.UNAVAILABLE,
            because=(
                "workflow_runs.action_card_id is NULL: this run predates the "
                "migration-040 link (#1269) and is deliberately never backfilled, "
                "so no recommendation can ever be resolved for it."
            ),
        )
    if first.card_id is None:
        return EmptyLink(
            reason=LinkReason.MISSING,
            because=(
                f"workflow_runs.action_card_id names card {first.run_action_card_id!s}, "
                "but no action_cards row with that id exists."
            ),
        )
    return RecommendationLink(
        action_card_id=first.card_id,
        workflow_key=first.card_workflow_key,
        title=first.card_title,
        severity=first.card_severity,
        priority=first.card_priority,
        status=first.card_status,
    )


def _run_is_terminal(status: str) -> bool:
    """Whether the run can still gain new facts. ``NON_TERMINAL_STATUSES``
    (``services/agent/status.py``) is the vocabulary's own answer; an
    unrecognised status is treated as non-terminal, which yields ``pending``
    — the conservative direction, since claiming ``unavailable`` for a run
    that is in fact still going would be a false negative an operator cannot
    detect."""
    try:
        return WorkflowRunStatus(status) not in NON_TERMINAL_STATUSES
    except ValueError:
        return False


def _classify_action(first: Row, executions: tuple[ActionExecution, ...]) -> ActionLink | EmptyLink:
    """An empty action link means the run dispatched no write.

    While the run is still live (``queued``/``running``/``waiting_approval``)
    a write may still arrive: ``pending``. Once it is terminal, no write will
    ever arrive: ``unavailable``, with the ``stop_reason`` named, so a
    declined run says "declined" rather than "not yet".
    """
    if executions:
        return ActionLink(executions=executions)
    if not _run_is_terminal(first.run_status):
        return EmptyLink(
            reason=LinkReason.PENDING,
            because=(
                f"the run is still {first.run_status!r}; no tool_executions row "
                "exists yet, and one may still be dispatched."
            ),
        )
    reason_text = (
        f"stop_reason={first.run_stop_reason!r}"
        if first.run_stop_reason
        else "no stop_reason recorded"
    )
    return EmptyLink(
        reason=LinkReason.UNAVAILABLE,
        because=(
            f"the run reached terminal status {first.run_status!r} ({reason_text}) "
            "with zero tool_executions rows: no write was dispatched, and none can be."
        ),
    )


def _classify_state_change(
    first: Row,
    executions: tuple[ActionExecution, ...],
    records: tuple[StateChangeRecord, ...],
    action: ActionLink | EmptyLink,
) -> StateChangeLink | EmptyLink:
    """A state change cannot exist without an action, so an empty action link
    propagates its own reason here — a declined run's state change is
    ``unavailable`` (declining is a choice, not a delay), a live run's is
    ``pending``.

    With executions present: a succeeded write SHOULD have produced an
    outcome record, so its absence is ``missing``. A write still in flight is
    ``pending``. A write that only ever failed changed nothing on TikTok, so
    no record can exist: ``unavailable``.
    """
    if records:
        return StateChangeLink(records=records)
    if isinstance(action, EmptyLink):
        return EmptyLink(
            reason=action.reason,
            because=(
                "no tool_executions row for this run, so no TikTok state change "
                f"can be recorded — {action.because}"
            ),
        )
    if any(execution.status == _SUCCEEDED for execution in executions):
        return EmptyLink(
            reason=LinkReason.MISSING,
            because=(
                "a write completed (a tool_executions row is 'succeeded') but no "
                "workflow_outcome_records row joins to it on execution_id — the fact "
                "should exist and does not."
            ),
        )
    if not _run_is_terminal(first.run_status):
        return EmptyLink(
            reason=LinkReason.PENDING,
            because=(
                f"the run is still {first.run_status!r} and no dispatched write has "
                "completed yet, so no state change has been recorded."
            ),
        )
    return EmptyLink(
        reason=LinkReason.UNAVAILABLE,
        because=(
            "every dispatched write for this terminal run ended without succeeding "
            f"(statuses: {sorted({e.status for e in executions})}), so no TikTok "
            "state change occurred."
        ),
    )


def _readiness_date(executions: tuple[ActionExecution, ...]) -> date | None:
    """The day the preliminary impact window closes for this run, or ``None``
    when no write has completed (so there is no ``T`` at all).

    ``T`` is the write's execution date. ``ToolExecution`` has no dedicated
    ``executed_at`` column (a genuine schema gap, #1040), so ``updated_at`` is
    the proxy — bumped by ``onupdate=func.now()`` on the very update that
    flips ``status`` to ``succeeded``. That is the same proxy
    ``workers/impact_reader/queries.py::execution_t`` reads, and this module
    mirrors rather than imports it because ``.importlinter.toml`` does not
    allow ``services -> workers``.

    The boundary itself is ``services/impact/windows.post_window``'s — the
    single declaration of ADR-077 decision 2's window lengths. Nothing here
    re-declares ``7``. The LATEST completed write wins: the chain is not ready
    until every write's own window has closed.
    """
    completed = [e.executed_at for e in executions if e.status == _SUCCEEDED]
    if not completed:
        return None
    t = max(completed).date()
    _, window_end = post_window(t, _READINESS_KIND)
    return window_end


def _classify_impact(
    executions: tuple[ActionExecution, ...],
    readings: tuple[_ReadingRow, ...],
    action: ActionLink | EmptyLink,
    at: datetime,
) -> tuple[ObservedOutcomeLink | EmptyLink, IncrementalImpactLink | EmptyLink]:
    """Links 4 and 5, which share a subject (``impact_readings``) and a clock
    but not a rule.

    Link 4 counts any reading carrying a ``post`` value — that IS the observed
    KPI window, whatever confidence the reader assigned it. Link 5 counts only
    readings whose confidence is in ``COUNTABLE_CONFIDENCES``; a ``suppressed``
    or ``confounded`` row is never an incremental impact (#1226, #1338), it is
    its own labelled outcome and is returned as one.
    """
    observed_rows = tuple(r for r in readings if r.post is not None)
    countable = tuple(
        CountableReading(
            reading_id=r.reading_id,
            metric=r.metric,
            kind=r.kind,
            confidence=r.confidence,
            incremental=r.incremental,
            impact_pct=r.impact_pct,
            computed_at=r.computed_at,
        )
        for r in readings
        if r.confidence in COUNTABLE_CONFIDENCES
    )
    excluded = tuple(
        ExcludedReading(
            reading_id=r.reading_id,
            metric=r.metric,
            kind=r.kind,
            confidence=r.confidence,
        )
        for r in readings
        if r.confidence in EXCLUDED_CONFIDENCES
    )

    empty = _empty_impact_reason(executions, action, at)

    if observed_rows:
        observed: ObservedOutcomeLink | EmptyLink = ObservedOutcomeLink(
            observations=tuple(
                ObservedMetric(
                    reading_id=r.reading_id,
                    metric=r.metric,
                    kind=r.kind,
                    pre=r.pre,
                    post=r.post,
                )
                for r in observed_rows
                if r.post is not None
            )
        )
    else:
        observed = EmptyLink(
            reason=empty.reason,
            because=f"no impact_readings row carries a post-window value — {empty.because}",
            excluded_readings=excluded,
        )

    if countable:
        incremental: IncrementalImpactLink | EmptyLink = IncrementalImpactLink(
            readings=countable, excluded_readings=excluded
        )
    elif excluded:
        labels = ", ".join(f"{r.metric}={r.confidence}" for r in excluded)
        incremental = EmptyLink(
            reason=LinkReason.UNAVAILABLE,
            because=(
                f"{len(excluded)} impact_readings row(s) exist for this run but none is "
                f"countable ({labels}). A suppressed reading (insufficient signal) and a "
                "confounded one (a competing change) are each their own labelled "
                "outcome, never an incremental impact and never zero impact "
                "(#1226, #1338); a countable reading cannot be derived from them."
            ),
            excluded_readings=excluded,
        )
    else:
        incremental = EmptyLink(reason=empty.reason, because=empty.because, excluded_readings=())

    return observed, incremental


def _empty_impact_reason(
    executions: tuple[ActionExecution, ...],
    action: ActionLink | EmptyLink,
    at: datetime,
) -> EmptyLink:
    """Why "no reading at all" is empty: the shared derivation behind both
    impact links.

    No write means no measurement subject, so the action link's own reason
    carries straight through — a declined run is ``unavailable``, a live one
    ``pending``. With a completed write the answer comes from the CLOCK, not
    from row absence: while the preliminary window is still open the reading
    cannot exist yet (``pending``); once it has closed the reader should have
    produced one (``missing``).
    """
    if isinstance(action, EmptyLink):
        return EmptyLink(
            reason=action.reason,
            because=(f"no write was measured for this run — {action.because}"),
        )
    window_end = _readiness_date(executions)
    if window_end is None:
        return EmptyLink(
            reason=LinkReason.PENDING,
            because=(
                "no dispatched write has completed yet, so the impact window has no "
                "start date T and no reading can have been computed."
            ),
        )
    if at.date() <= window_end:
        return EmptyLink(
            reason=LinkReason.PENDING,
            because=(
                f"the {_READINESS_KIND} impact window closes on {window_end.isoformat()} "
                f"and today is {at.date().isoformat()}: the reading is not due yet."
            ),
        )
    return EmptyLink(
        reason=LinkReason.MISSING,
        because=(
            f"the {_READINESS_KIND} impact window closed on {window_end.isoformat()}, "
            f"before {at.date().isoformat()}, but no impact_readings row exists for "
            "this run — the reading should exist and does not."
        ),
    )

"""Three metrics, three sources, three denominators — never averaged.
Issue #1656 (W8-D / P10-4), parent PRD #1652, ADR-077.

Three of P10's four questions, each answered from its OWN source and over its
OWN denominator:

===================  ===============================  =============================
Question             Source                           Denominator
===================  ===============================  =============================
Was Juli right?      the scoring signal against the   recommendations WITH an
                     observed KPI window, reached     observed outcome
                     through #1655's outcome chain
Did sellers agree?   ``action_cards`` seller          cards surfaced
                     decisions
Did Juli do the      ``workflow_runs.stop_reason``    runs started
job?                 plus ``required_steps_completed``
===================  ===============================  =============================

**The refusal is the requirement.** There is deliberately NO function, field
or return value here that blends the three into one number, and no two of them
share a denominator. A single blended score is the one artefact that lets a
good approval rate hide a bad outcome, and it is the first thing a stakeholder
asks for; `tests/unit/test_agent_quality_metrics.py::TestNoBlendedFigure`
enforces the absence structurally over :data:`__all__` so the refusal survives
a reviewer having a busy day. Nothing below computes a combined, composite,
overall, weighted or "health" figure — not as a return value, not as a private
helper, and not as an example.

**Numerator and denominator, never a bare ratio.** Every result carries both
terms, because "80%" over an n of 5 and "80%" over an n of 5000 are different
claims and a float cannot tell them apart. :attr:`ratio` is a convenience over
the two terms the result already exposes, never a replacement for them.

**An empty denominator is :class:`NoData`, never ``0``.** "We measured
nothing" and "we measured no successes" are different facts; zero-as-a-number
is a claim about the world and an absent measurement is not — the dishonesty
#1226 forbids by name. :class:`NoData` is a value of its own type, so it can
never compare equal to ``0`` or ``0.0``, and the counts are summed in Python
from row groups rather than by a SQL ``SUM`` precisely so Postgres's
NULL-over-zero-rows can never be coerced into a ``0`` on the way out.

**The seller-decision mapping, against the vocabulary that EXISTS.**
``action_cards.status`` has exactly four values in the tree —
``active``/``approved``/``dismissed``/``executing``
(``services/action_cards/persist.py::IN_FLIGHT_STATUSES`` plus the ``active``
candidate status it upserts). There is NO ``rejected`` and NO ``expired`` card
status, and **card-level expiry does not exist at all**. So:

- ``approved``/``executing`` -> the seller agreed (``executing`` is downstream
  of an approval, never a separate decision)
- ``dismissed`` -> the seller's explicit negative
- ``active`` -> no decision recorded yet
- expiry -> the RUN-level :data:`EXPIRY_STOP_REASON`
  (``StopReason.CONFIRMATION_EXPIRED``, the 4h reaper on ``RunConfirmation``),
  the only expiry signal the tree has

A seller who ran out of time did not disagree with Juli, so an expiry is its
own bucket and is counted as NEITHER an approval nor a dismissal — collapsing
it into the dismissal count is the exact error #1656's criterion 5 names, and
counting it as an approval would overstate agreement the same way in the other
direction. Expiry therefore takes precedence over the card's own status, which
still reads ``approved`` from the moment the seller approved the card that
created the run. **This is the one place a metric reads a column outside its
own table**, and it is a reported gap rather than a design choice: adding an
``expired`` card status is a five-place change (Python vocabulary, DB CHECK,
the TS union, the totality tests, the non-terminal set) owned by another lane,
not a metric's business. Approval rate reads exactly ONE fact from
``workflow_runs`` — whether a run created from this card stopped with that
stop reason — and never its status, its distribution or its required steps.

**``required_steps_completed`` is its own fact (#1220).** Execution quality
reads it directly and never derives it from ``stop_reason`` or folds one into
the other: a run that stopped on ``final_response`` with
``required_steps_completed=False`` is a run that did not do the job, and that
is honest data rather than a synthetic failure. ``NULL`` means "not yet
determined" — a different fact from "determined: not completed" — so it is
counted as neither a success nor a failure and is named in the result under
:attr:`ExecutionQuality.undetermined` instead of being folded into either.

**Recommendation quality consumes #1655's chain.** One
``load_outcome_chain`` call per candidate run; never a second client-side join
across ``action_cards``, ``tool_executions``, ``workflow_outcome_records`` and
``impact_readings``. A ``suppressed`` or ``confounded`` reading is never an
observed outcome (#1226, #1338): the exclusion is read off the chain's own
``excluded_readings``, which is derived from
``impact_honesty.EXCLUDED_CONFIDENCES``, so this module holds no second copy of
that rule. "Borne out" is ``post > pre`` on at least one countable
observation, which is the whole direction fact an ``ObservedMetric`` carries;
every metric in ``services/impact/metric_map.py::ALL_METRICS`` today is one
where higher is better, and an observation with no ``pre`` is not comparable
at all rather than a failure, so it is named under
:attr:`RecommendationQuality.not_comparable`.

Read-only: this module never writes, adds no schema, and — per PRD #1652 —
computes without judging. No trends, no thresholds, no alerting, no rendering.
Business impact is #1657 and is deliberately absent here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, WorkflowRun
from juli_backend.services.agent.status import StopReason
from juli_backend.services.operations.outcome_chain import (
    EmptyLink,
    ObservedMetric,
    OutcomeChain,
    load_outcome_chain,
)

__all__ = [
    "APPROVED_STATUSES",
    "ApprovalRate",
    "CARDS_SURFACED",
    "DISMISSED_STATUSES",
    "EXPIRY_STOP_REASON",
    "ExecutionQuality",
    "NoData",
    "PENDING_STATUSES",
    "RECOMMENDATIONS_WITH_AN_OBSERVED_OUTCOME",
    "RUNS_STARTED",
    "RecommendationQuality",
    "StopReasonCount",
    "approval_rate",
    "execution_quality",
    "recommendation_quality",
]

#: The seller agreed. ``executing`` is downstream of an approval — the card
#: moved on because the approved run started — never a second decision.
APPROVED_STATUSES: frozenset[str] = frozenset({"approved", "executing"})

#: The seller's explicit negative, and the ONLY explicit negative the card
#: vocabulary has: there is no ``rejected`` status.
DISMISSED_STATUSES: frozenset[str] = frozenset({"dismissed"})

#: Surfaced, and no decision recorded yet.
PENDING_STATUSES: frozenset[str] = frozenset({"active"})

#: The only expiry signal in the tree, and it lives on the RUN, not the card
#: (``services/agent/status.py``; the 4h reaper on ``RunConfirmation``).
EXPIRY_STOP_REASON: StopReason = StopReason.CONFIRMATION_EXPIRED

#: The three denominators, named. They are three different populations and are
#: never divided into one another — dividing two of them by one shared count
#: would make both answers wrong.
RECOMMENDATIONS_WITH_AN_OBSERVED_OUTCOME = "recommendations with an observed outcome"
CARDS_SURFACED = "cards surfaced"
RUNS_STARTED = "runs started"


@dataclass(frozen=True, slots=True)
class NoData:
    """An absent measurement, under its own type.

    Returned by :attr:`ratio` when the denominator is empty. It is a distinct
    value rather than ``0``, ``0.0``, ``None`` or ``"0%"`` so that "we
    measured nothing" can never be read as "we measured no successes"; being
    its own type, it cannot compare equal to a number by accident. It
    deliberately defines no ``__bool__``, so a caller writing ``if
    result.ratio:`` sees it as truthy and cannot silently conflate it with a
    genuine ``0.0``.
    """

    #: Which population was empty, in the denominator's own words.
    population: str


def _ratio(numerator: int, denominator: int, population: str) -> float | NoData:
    if denominator == 0:
        return NoData(population=population)
    return numerator / denominator


@dataclass(frozen=True, slots=True)
class RecommendationQuality:
    """Was Juli right? Over recommendations that HAVE an observed outcome."""

    #: The observed KPI window improved on the value before the change.
    borne_out: int
    #: It was comparable and did not improve.
    not_borne_out: int
    #: An observed outcome exists but carries no ``pre`` value, so there is
    #: nothing to compare it against. Neither right nor wrong — named rather
    #: than silently counted as a failure.
    not_comparable: int
    denominator: int

    @property
    def numerator(self) -> int:
        """Recommendations the observed outcome bore out."""
        return self.borne_out

    @property
    def ratio(self) -> float | NoData:
        return _ratio(self.numerator, self.denominator, RECOMMENDATIONS_WITH_AN_OBSERVED_OUTCOME)


@dataclass(frozen=True, slots=True)
class ApprovalRate:
    """Did sellers agree with Juli? Over cards surfaced."""

    approved: int
    #: The seller's explicit negative — never merged with :attr:`expired`.
    dismissed: int
    #: The seller ran out of time at the confirmation gate
    #: (:data:`EXPIRY_STOP_REASON`). Not agreement and not disagreement.
    expired: int
    #: Surfaced, still awaiting a decision.
    pending: int
    denominator: int

    @property
    def numerator(self) -> int:
        """Cards the seller agreed with."""
        return self.approved

    @property
    def ratio(self) -> float | NoData:
        return _ratio(self.numerator, self.denominator, CARDS_SURFACED)


@dataclass(frozen=True, slots=True)
class StopReasonCount:
    """One entry of the ``stop_reason`` distribution. ``None`` is a run that
    has not stopped yet, and is reported as ``None`` rather than bucketed
    under a made-up label."""

    stop_reason: str | None
    count: int


@dataclass(frozen=True, slots=True)
class ExecutionQuality:
    """Did Juli perform the task? Over runs started."""

    #: ``required_steps_completed IS TRUE``.
    completed_with_required_steps: int
    #: ``required_steps_completed IS FALSE`` — determined, and it did not do
    #: the job, whatever the ``stop_reason`` says (#1220).
    did_not_complete: int
    #: ``required_steps_completed IS NULL`` — not yet determined. Neither a
    #: success nor a failure; excluded from the numerator and named here.
    undetermined: int
    #: The ``stop_reason`` distribution, an independent view of the same runs
    #: — never derived from, and never folded into, the three counts above.
    stop_reasons: tuple[StopReasonCount, ...]
    denominator: int

    @property
    def numerator(self) -> int:
        """Runs that completed every required step."""
        return self.completed_with_required_steps

    @property
    def ratio(self) -> float | NoData:
        return _ratio(self.numerator, self.denominator, RUNS_STARTED)


def _aware_utc(value: datetime) -> datetime:
    """For ``TIMESTAMPTZ`` columns (``action_cards.surfaced_at``)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _naive_utc(value: datetime) -> datetime:
    """For ``TIMESTAMP WITHOUT TIME ZONE`` columns (``workflow_runs
    .created_at``), which asyncpg refuses aware values on (#1138)."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value


# --------------------------------------------------------------------------
# Approval rate — source: action_cards
# --------------------------------------------------------------------------


async def approval_rate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ApprovalRate:
    """Seller decisions over CARDS SURFACED, for one shop.

    A card that was scored but never surfaced (``surfaced_at IS NULL`` — the
    emission budget suppressed it, #716) is not a card any seller was asked
    about, so it is outside the denominator entirely rather than counted as a
    non-approval.

    The window is over ``surfaced_at``, the moment the card was put in front
    of the seller, which is the event the denominator is named after.
    """
    surfacing = ActionCard.surfaced_at
    statement = (
        select(
            ActionCard.status.label("card_status"),
            func.bool_or(WorkflowRun.stop_reason == EXPIRY_STOP_REASON.value).label("any_expired"),
        )
        .select_from(ActionCard)
        .outerjoin(WorkflowRun, WorkflowRun.action_card_id == ActionCard.id)
        .where(ActionCard.shop_id == shop_id, surfacing.is_not(None))
        .group_by(ActionCard.id, ActionCard.status)
    )
    if since is not None:
        statement = statement.where(surfacing >= _aware_utc(since))
    if until is not None:
        statement = statement.where(surfacing < _aware_utc(until))

    approved = dismissed = expired = pending = 0
    for row in (await session.execute(statement)).all():
        # `bool_or` over a card with no runs at all is NULL, not False, so the
        # comparison is explicit rather than a truthiness test.
        if row.any_expired is True:
            expired += 1
        elif row.card_status in DISMISSED_STATUSES:
            dismissed += 1
        elif row.card_status in APPROVED_STATUSES:
            approved += 1
        else:
            # `active`, and any status this module has not been taught yet:
            # counted as "no decision recorded" so the four buckets always sum
            # to the denominator. A new status silently landing here is what
            # the totality test over the card vocabulary exists to catch.
            pending += 1

    return ApprovalRate(
        approved=approved,
        dismissed=dismissed,
        expired=expired,
        pending=pending,
        denominator=approved + dismissed + expired + pending,
    )


# --------------------------------------------------------------------------
# Execution quality — source: workflow_runs
# --------------------------------------------------------------------------


async def execution_quality(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ExecutionQuality:
    """The did-the-job outcome over RUNS STARTED, for one shop.

    Every ``workflow_runs`` row is a run that started: a run is only ever
    inserted already ``queued`` (ADR-073), so the denominator is the row count
    and needs no status filter — filtering it would quietly answer a different
    question than the one the denominator is named after.
    """
    started = WorkflowRun.created_at
    statement = (
        select(
            WorkflowRun.stop_reason.label("stop_reason"),
            WorkflowRun.required_steps_completed.label("required_steps_completed"),
            func.count().label("runs"),
        )
        .where(WorkflowRun.shop_id == shop_id)
        .group_by(WorkflowRun.stop_reason, WorkflowRun.required_steps_completed)
    )
    if since is not None:
        statement = statement.where(started >= _naive_utc(since))
    if until is not None:
        statement = statement.where(started < _naive_utc(until))

    completed = did_not_complete = undetermined = 0
    by_stop_reason: dict[str | None, int] = {}
    for row in (await session.execute(statement)).all():
        runs = int(row.runs)
        # `required_steps_completed` is read as itself, never inferred from
        # `stop_reason`: NULL is "not yet determined", which is a third
        # answer, not a False (#1220).
        if row.required_steps_completed is True:
            completed += runs
        elif row.required_steps_completed is False:
            did_not_complete += runs
        else:
            undetermined += runs
        by_stop_reason[row.stop_reason] = by_stop_reason.get(row.stop_reason, 0) + runs

    return ExecutionQuality(
        completed_with_required_steps=completed,
        did_not_complete=did_not_complete,
        undetermined=undetermined,
        stop_reasons=tuple(
            StopReasonCount(stop_reason=reason, count=count)
            for reason, count in sorted(
                by_stop_reason.items(), key=lambda item: (item[0] is not None, item[0] or "")
            )
        ),
        denominator=completed + did_not_complete + undetermined,
    )


# --------------------------------------------------------------------------
# Recommendation quality — source: the observed outcomes behind #1655's chain
# --------------------------------------------------------------------------


def _countable_observations(chain: OutcomeChain) -> tuple[ObservedMetric, ...]:
    """The chain's observed outcomes with the excluded readings removed.

    The exclusion is not re-declared here: it is read off the chain's own
    ``excluded_readings``, which ``outcome_chain`` derives from
    ``impact_honesty.EXCLUDED_CONFIDENCES``. ``ObservedMetric`` does not carry
    a ``confidence``, so filtering by reading id off that list is how a
    suppressed or confounded row is kept out of "observed outcome" without a
    second copy of the rule (#1226, #1338) and without a second query.
    """
    if isinstance(chain.observed_outcome, EmptyLink):
        return ()
    excluded = {reading.reading_id for reading in chain.incremental_impact.excluded_readings}
    return tuple(
        observation
        for observation in chain.observed_outcome.observations
        if observation.reading_id not in excluded
    )


async def _candidate_run_ids(
    session: AsyncSession,
    shop_id: uuid.UUID,
    since: datetime | None,
    until: datetime | None,
) -> Sequence[uuid.UUID]:
    """Runs that carry a recommendation, oldest first.

    A single-table scan of ``workflow_runs``, deliberately NOT a join across
    the chain's four tables: the chain is #1655's to walk, one call per run.
    """
    started = WorkflowRun.created_at
    statement = (
        select(WorkflowRun.id)
        .where(WorkflowRun.shop_id == shop_id, WorkflowRun.action_card_id.is_not(None))
        .order_by(started)
    )
    if since is not None:
        statement = statement.where(started >= _naive_utc(since))
    if until is not None:
        statement = statement.where(started < _naive_utc(until))
    return list((await session.execute(statement)).scalars().all())


async def recommendation_quality(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> RecommendationQuality:
    """Was Juli right? Over RECOMMENDATIONS WITH AN OBSERVED OUTCOME.

    A recommendation with no observed outcome yet is outside the denominator
    rather than inside it as a failure — "not measured" is not "wrong", and
    putting it in the denominator would make the metric fall every time the
    impact reader ran late.

    Each candidate run's chain comes from ``load_outcome_chain`` — one call
    per run. That is deliberately not one big join: #1655 owns the walk across
    the four tables, and re-deriving it here is precisely the hand-joining
    this wave exists to remove.
    """
    borne_out = not_borne_out = not_comparable = 0

    for run_id in await _candidate_run_ids(session, shop_id, since, until):
        chain = await load_outcome_chain(session, run_id)
        if isinstance(chain.recommendation, EmptyLink):
            continue
        observations = _countable_observations(chain)
        if not observations:
            continue
        comparable = [o for o in observations if o.pre is not None]
        if not comparable:
            not_comparable += 1
        elif any(o.post > o.pre for o in comparable if o.pre is not None):
            borne_out += 1
        else:
            not_borne_out += 1

    return RecommendationQuality(
        borne_out=borne_out,
        not_borne_out=not_borne_out,
        not_comparable=not_comparable,
        denominator=borne_out + not_borne_out + not_comparable,
    )

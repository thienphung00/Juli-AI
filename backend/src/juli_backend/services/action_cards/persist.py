"""Persist scoring pipeline output to action_cards — ADR-021, #715 (B-3), #716 (B-4).

Subject-scoped since #1703 (ADR-087 decisions 1, 3 and 6). Emission used to
upsert exactly one row per ``(shop_id, workflow_key)``; it now resolves what
each card is *about* (``services/action_cards/subjects.py``), keys the row on
that subject, and either emits a chained successor or suppresses with a named
reason (``services/action_cards/basis.py`` decides which).

**Two suppression vocabularies, kept apart on purpose.**
``ActionCard.suppressed_reason`` belongs to the emission *budget*
(``emission_budget.py``: ``active_cap`` / ``cooldown`` /
``weekly_novelty_cap``) and answers "was this candidate surfaced?". The two
reasons introduced here -- ``basis_unchanged`` and ``active_card_exists`` --
answer a different question, "was a row written at all?", and are reported on
the emission outcome and in the structured log. **They are never written to
that column.** That is not a convenience: it is what makes ADR-087's
requirement that the two vocabularies stay distinguishable a structural fact
rather than a naming convention nobody can enforce.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import DecisionEmissionConfig, decision_emission_config
from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.basis import (
    BASIS_METADATA_KEY,
    basis_unchanged,
    compute_card_basis,
    stored_basis,
)
from juli_backend.services.action_cards.subjects import (
    SUBJECT_TYPE_UNSCOPED,
    CardSubject,
    resolve_card_subject,
)
from juli_backend.services.scoring.types import (
    DailyScoringResult,
    KpiId,
    Severity,
    WorkflowReasoningSummary,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "warning": 3,
    "healthy": 2,
    "not_applicable": 1,
}

# In-flight / terminal card statuses that a re-scoring candidate must not
# clobber (#715, B-3). A candidate row only ever proposes "active"; once a
# seller (or dry-run flow) has moved a card past that — approved, dismissed,
# or executing — continuous re-scoring must not silently reset it back.
IN_FLIGHT_STATUSES: frozenset[str] = frozenset({"approved", "dismissed", "executing"})

_ACTIVE_STATUS = "active"

#: Nothing material moved for this subject since the card we already emitted
#: for it, so there is nothing new to offer (ADR-087 decision 6). The
#: reference revision is the newest row for the subject: when that row has
#: been executed this is literally the ADR's "changed since the last executed
#: revision's snapshot"; when it is still standing, the same comparison
#: answers "has anything changed since the offer already on the seller's
#: desk?".
SUPPRESSED_REASON_BASIS_UNCHANGED = "basis_unchanged"

#: The basis *did* move, and normally that would earn a successor -- but a
#: card for this subject is still standing, so the successor is withheld
#: rather than written (ADR-087 decision 2: at most one live card per
#: subject per workflow, which the partial unique index enforces and this
#: gate keeps the pipeline from ever testing).
#:
#: "Standing" is the seller's-desk sense: a card that has actually reached
#: the seller and has not finished. That is a *surfaced* ``active`` row (the
#: emission budget put it in front of them), an ``approved``/``executing``
#: row (they acted on it and the outcome is not in yet), or a ``dismissed``
#: row inside its cooldown (they said no recently). The latter two were
#: frozen against re-scoring before this slice (#715 B-3, #716 B-4
#: "Collision 2") and stay frozen; naming the reason is the only thing that
#: changed. A row with ``executed_at`` set never stands -- that is the
#: revision a successor follows.
#:
#: An ``active`` row the budget has **not** surfaced is not an offer, it is a
#: draft, and #716's Collision 1 contract says a draft keeps getting
#: recomputed while it waits for a slot. Rewriting a draft destroys nothing
#: the seller was ever shown, so it is recomputation rather than a revision
#: and ADR-087 decision 3 does not reach it.
SUPPRESSED_REASON_ACTIVE_CARD_EXISTS = "active_card_exists"

#: The complete revision-suppression vocabulary. Disjoint from
#: ``emission_budget.SUPPRESSED_REASONS`` by construction -- different
#: question, different carrier (see the module docstring).
REVISION_SUPPRESSED_REASONS: frozenset[str] = frozenset(
    {
        SUPPRESSED_REASON_BASIS_UNCHANGED,
        SUPPRESSED_REASON_ACTIVE_CARD_EXISTS,
    }
)


@dataclass(frozen=True, slots=True)
class CardEmission:
    """What emission decided for one ranked recommendation.

    ``card`` is the row the recommendation resolves to: the newly written
    revision when one was emitted, or the standing row that caused the
    suppression. It is ``None`` only when there was nothing to emit and
    nothing standing, which cannot happen today. ``suppressed_reason`` is
    ``None`` exactly when a row was written.
    """

    workflow_key: str
    subject_type: str
    subject_id: str
    card: ActionCard | None
    revision: int | None
    suppressed_reason: str | None
    supersedes_card_id: uuid.UUID | None = None

    @property
    def emitted(self) -> bool:
        return self.suppressed_reason is None


@dataclass(frozen=True, slots=True)
class ScoringEmissionReport:
    """Every emission decision from one scoring run, in ranking order."""

    decisions: tuple[CardEmission, ...]

    @property
    def cards(self) -> list[ActionCard]:
        """Every card this run resolved to -- emitted or already standing.

        The back-compatible shape ``persist_scoring_result`` has always
        returned: callers use it to see the full candidate set for the run,
        which includes rows this run deliberately left untouched.
        """
        return [d.card for d in self.decisions if d.card is not None]

    @property
    def emitted(self) -> list[ActionCard]:
        return [d.card for d in self.decisions if d.emitted and d.card is not None]

    @property
    def suppressed(self) -> dict[str, list[CardEmission]]:
        by_reason: dict[str, list[CardEmission]] = {}
        for decision in self.decisions:
            if decision.suppressed_reason is not None:
                by_reason.setdefault(decision.suppressed_reason, []).append(decision)
        return by_reason


def _reasoning_for(
    summaries: tuple[WorkflowReasoningSummary, ...],
    workflow_key: str,
) -> WorkflowReasoningSummary | None:
    for item in summaries:
        if item.workflow_key == workflow_key:
            return item
    return None


def _severity_for_recommendation(
    result: DailyScoringResult,
    workflow_key: str,
    source_kpi_ids: tuple[str, ...],
) -> Severity:
    severities: list[Severity] = []
    for kpi_id in source_kpi_ids:
        signal = result.signals.kpis.get(cast(KpiId, kpi_id))
        if signal is not None:
            severities.append(signal.severity)
    if not severities:
        return "healthy"
    return max(severities, key=lambda value: _SEVERITY_RANK.get(value, 0))


def _build_payload(
    result: DailyScoringResult,
    recommendation,
    reasoning: WorkflowReasoningSummary | None,
    subject: CardSubject,
) -> dict:
    """The card's content, built from *this* run's scoring output only.

    ADR-087 decision 3 is enforced here by construction: a successor's
    payload is assembled from the recommendation and the reasoning summary,
    and this function never reads the predecessor row. The previous
    revision's information is reached by ``supersedes_card_id``, never
    copied -- *"a duplicated fact that can drift is the failure ADR-085
    rejected on the same grounds."*
    """
    payload = {
        "workflow_key": recommendation.workflow_key,
        "workflow_name": recommendation.workflow_name,
        "priority": recommendation.priority,
        "rationale": recommendation.rationale,
        "expected_impact": {
            "metric": recommendation.expected_impact.metric,
            "value": recommendation.expected_impact.value,
            "confidence": recommendation.expected_impact.confidence,
        },
        "preconditions_met": recommendation.preconditions_met,
        "user_action_required": recommendation.user_action_required,
        "source_kpi_ids": list(recommendation.source_kpi_ids),
        "computed_at": result.signals.computed_at.isoformat(),
        # What this card is about (#1703, ADR-087 d.1). Carried in the payload
        # as well as on the columns so the verbatim `action_card_approvals.
        # card_snapshot` records the subject the seller was shown, and so
        # W9-D has a label to render. `demo_decisions/read.py`'s allowlist
        # drops it from the public, unauthenticated Demo envelope.
        "subject": {
            "type": subject.subject_type,
            "id": subject.subject_id,
            "label": subject.label,
        },
    }
    if reasoning is not None:
        payload["reasoning"] = {
            "copy_source": reasoning.copy.copy_source,
            "why": reasoning.copy.why,
            "expected_impact": reasoning.copy.expected_impact,
            "next_steps": list(reasoning.copy.next_steps),
            "source_kpi_ids": list(reasoning.copy.source_kpi_ids),
        }
    return payload


def _dismiss_cooldown_expired(
    existing: ActionCard,
    *,
    now: datetime,
    cooldown_days: int,
) -> bool:
    """Whether a ``dismissed`` row's per-workflow cooldown has fully elapsed.

    Resolves Collision 2 (#716, B-4): B-3's ``IN_FLIGHT_STATUSES`` skip froze
    ``dismissed`` rows forever, so a cooldown that starts on a dismiss could
    never finish — nothing would ever produce a fresh candidate for that
    ``workflow_key`` again. Only ``dismissed`` gets this time-boxed escape
    hatch; ``approved``/``executing`` remain frozen indefinitely by design —
    resetting those requires an explicit outcome, not just a clock (see
    MODULE.md "Collision 2").

    Falls back to ``updated_at`` when ``dismissed_at`` was never stamped
    (e.g. a row dismissed before #716 added the column) — the same fallback
    already documented pre-B-4 for the surfacing signal.

    Under #1703 this is the churn floor ADR-087 decision 6 permits as a
    *secondary* cap ("a time-based rule is admissible only as a secondary cap
    on churn, never as the primary trigger"): the clock cannot cause a
    revision, it can only delay one the basis already justified.
    """
    marker = existing.dismissed_at or existing.updated_at
    if marker is None:
        return False
    if marker.tzinfo is None:
        marker = marker.replace(tzinfo=UTC)
    return now - marker >= timedelta(days=cooldown_days)


def _card_still_stands(
    card: ActionCard,
    *,
    now: datetime,
    cooldown_days: int,
) -> bool:
    """Whether *card* is still the shop's live answer for its subject.

    See ``SUPPRESSED_REASON_ACTIVE_CARD_EXISTS`` for what "standing" covers
    and why. An executed row is the one thing that never stands: ADR-087
    decision 6 defines a successor as following the last **executed**
    revision, so ``executed_at`` being set is precisely the condition that
    opens the subject to a new one.
    """
    if card.executed_at is not None:
        return False
    if card.status == "dismissed":
        return not _dismiss_cooldown_expired(card, now=now, cooldown_days=cooldown_days)
    if card.status == _ACTIVE_STATUS:
        return card.surfaced_at is not None
    return True


def _is_unsurfaced_draft(card: ActionCard) -> bool:
    """Whether *card* is a candidate the seller has never been shown.

    The complement of ``_card_still_stands`` for an ``active`` row, kept as
    its own named predicate because it selects the one case emission still
    writes **in place**: #716 (B-4, Collision 1) requires a budget-suppressed
    candidate to keep being recomputed so that the copy is current on the day
    a slot finally opens for it.
    """
    return card.status == _ACTIVE_STATUS and card.surfaced_at is None and card.executed_at is None


async def _latest_revision(
    session: AsyncSession,
    shop_id: uuid.UUID,
    workflow_key: str,
    subject: CardSubject,
) -> ActionCard | None:
    """The newest revision in this subject's chain, if the chain exists.

    Deliberately bypasses ``ActionCardsRepo.upsert``, whose natural key is
    ``(shop_id, workflow_key)`` alone: with chained revisions that key matches
    several rows and would update an arbitrary one. Emission writes rows
    directly from here on, and the repo's upsert is no longer part of this
    path (see MODULE.md).
    """
    stmt = (
        select(ActionCard)
        .where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == workflow_key,
            ActionCard.subject_type == subject.subject_type,
            ActionCard.subject_id == subject.subject_id,
        )
        .order_by(ActionCard.revision.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _adoptable_unscoped_candidate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    workflow_key: str,
) -> ActionCard | None:
    """A live pre-#1703 card for *workflow_key* that has no subject yet.

    The coexistence bridge for #1701's backfill. Every row on the deployed
    database carries ``subject_type='unscoped'`` because no producer wrote a
    subject; the moment this one does, a shop would otherwise hold two live
    cards for the same workflow -- the legacy unscoped row and the new
    subject-scoped one -- because the partial unique index keys on the
    subject and those two subjects differ.

    Stamping the resolved subject onto the standing candidate is **not** an
    in-place revision (ADR-087 decision 3 forbids those): nothing is
    superseded and no predecessor information is destroyed, because the row
    never carried a subject to overwrite. It is the completion of a row
    #1701 deliberately left incomplete, and it happens at most once per
    ``(shop, workflow_key)``.

    Only an ``active`` row is adopted. An approved/executing/dismissed
    unscoped row is history: the seller acted on a card that named nothing,
    and rewriting what it was about after the fact would falsify the record.
    """
    stmt = (
        select(ActionCard)
        .where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == workflow_key,
            ActionCard.subject_type == SUBJECT_TYPE_UNSCOPED,
            ActionCard.status == _ACTIVE_STATUS,
        )
        .order_by(ActionCard.revision.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


def _log_suppressed(shop_id: uuid.UUID, decision: CardEmission) -> None:
    """One structured record per suppressed emission.

    Mirrors ``emission_budget._log_suppressed`` and carries the same
    constraint: system identifiers only -- shop, workflow key, subject and
    reason -- never card copy, which can hold seller-identifying or financial
    content (PRD security stories 22/23).
    """
    logger.info(
        "action_card_emission_suppressed",
        extra={
            "shop_id": str(shop_id),
            "workflow_key": decision.workflow_key,
            "subject_type": decision.subject_type,
            "subject_id": decision.subject_id,
            "suppressed_reason": decision.suppressed_reason,
        },
    )


async def emit_scoring_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    result: DailyScoringResult,
    *,
    emission_config: DecisionEmissionConfig | None = None,
) -> ScoringEmissionReport:
    """Emit one subject-scoped Action Card per ranked recommendation.

    For each recommendation, in ranking order:

    1. **Resolve the subject** (``subjects.resolve_card_subject``). A product
       for ``optimize_product_2``; ``unscoped`` for every other key, because
       the rows their subjects would point at do not exist yet. A subject is
       never invented to satisfy a downstream guard.
    2. **Adopt a pre-#1703 candidate** for this workflow if one is standing
       and this is the subject's first scoped emission
       (``_adoptable_unscoped_candidate``).
    3. **Compute the basis** for the subject under this workflow key
       (``basis.compute_card_basis``) -- the KPI severity buckets behind the
       recommendation plus the subject's own material fields.
    4. **Decide**: no chain yet → revision 1; basis unchanged →
       ``basis_unchanged``; basis changed but a card is still standing →
       ``active_card_exists``; basis changed and the newest row is a draft
       the seller has never been shown → recomputed in place (#716's
       Collision 1 contract, unchanged); otherwise a chained successor at
       ``revision + 1`` with ``supersedes_card_id`` pointing at its
       predecessor and a payload built from this run alone.

    Emission-budget columns (``surfaced_at`` / ``suppressed_reason``) are
    never written here — recomputation and surfacing run on independent
    cadences (see ``services.action_cards.emission_budget``); the reasons this
    function produces live on the returned report and in the log, never on
    that column.

    Freshness metadata: ``computed_at`` from the scoring run's
    ``ScoringSignals`` is persisted on a real, queryable column — aligned with
    Analytics envelope freshness semantics (ADR-038) — in addition to the
    ``metadata_json`` / payload copies kept for backward-compatible reads.
    ``metadata_json`` additionally carries the basis fingerprint under
    ``basis.BASIS_METADATA_KEY``; no new column, and no migration.

    No commit: every write lands on the caller's session, exactly as before.
    """
    decisions: list[CardEmission] = []
    computed_at = result.signals.computed_at
    computed_at_iso = computed_at.isoformat()
    config = emission_config or decision_emission_config()

    for recommendation in result.recommendations.recommended_workflows:
        workflow_key = recommendation.workflow_key
        subject = await resolve_card_subject(session, shop_id, workflow_key)

        latest = await _latest_revision(session, shop_id, workflow_key, subject)
        adopted: ActionCard | None = None
        if latest is None and subject.is_resolved:
            adopted = await _adoptable_unscoped_candidate(session, shop_id, workflow_key)

        current_basis = await compute_card_basis(
            session,
            shop_id,
            workflow_key=workflow_key,
            subject=subject,
            source_kpi_ids=recommendation.source_kpi_ids,
            result=result,
        )

        if latest is not None:
            if basis_unchanged(stored_basis(latest), current_basis):
                decision = CardEmission(
                    workflow_key=workflow_key,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=latest,
                    revision=latest.revision,
                    suppressed_reason=SUPPRESSED_REASON_BASIS_UNCHANGED,
                )
                decisions.append(decision)
                _log_suppressed(shop_id, decision)
                continue
            if _card_still_stands(latest, now=computed_at, cooldown_days=config.cooldown_days):
                decision = CardEmission(
                    workflow_key=workflow_key,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=latest,
                    revision=latest.revision,
                    suppressed_reason=SUPPRESSED_REASON_ACTIVE_CARD_EXISTS,
                )
                decisions.append(decision)
                _log_suppressed(shop_id, decision)
                continue

        reasoning = _reasoning_for(result.reasoning_summaries, workflow_key)
        severity = _severity_for_recommendation(result, workflow_key, recommendation.source_kpi_ids)
        description = reasoning.copy.why if reasoning is not None else recommendation.rationale
        payload = _build_payload(result, recommendation, reasoning, subject)
        metadata = json.dumps({"computed_at": computed_at_iso, BASIS_METADATA_KEY: current_basis})

        # Two in-place cases, and neither is a revision: the pre-#1703 row
        # being completed (`adopted`), and a draft the seller has never been
        # shown (#716 Collision 1). Both rewrite a row that was never an
        # offer, so no predecessor information is destroyed.
        in_place = (
            adopted
            if adopted is not None
            else (latest if latest is not None and _is_unsurfaced_draft(latest) else None)
        )
        if in_place is not None:
            in_place.subject_type = subject.subject_type
            in_place.subject_id = subject.subject_id
            in_place.priority = recommendation.priority
            in_place.severity = severity
            in_place.title = recommendation.workflow_name
            in_place.description = description
            in_place.recommendation_payload = json.dumps(payload)
            in_place.metadata_json = metadata
            in_place.computed_at = computed_at
            await session.flush()
            decisions.append(
                CardEmission(
                    workflow_key=workflow_key,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=in_place,
                    revision=in_place.revision,
                    suppressed_reason=None,
                )
            )
            continue

        revision = 1 if latest is None else latest.revision + 1
        supersedes_card_id = None if latest is None else latest.id
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key=workflow_key,
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
            revision=revision,
            supersedes_card_id=supersedes_card_id,
            priority=recommendation.priority,
            severity=severity,
            title=recommendation.workflow_name,
            description=description,
            recommendation_payload=json.dumps(payload),
            status=_ACTIVE_STATUS,
            metadata_json=metadata,
            computed_at=computed_at,
        )
        session.add(card)
        await session.flush()
        decisions.append(
            CardEmission(
                workflow_key=workflow_key,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=card,
                revision=revision,
                suppressed_reason=None,
                supersedes_card_id=supersedes_card_id,
            )
        )

    return ScoringEmissionReport(decisions=tuple(decisions))


async def persist_scoring_result(
    session: AsyncSession,
    shop_id: uuid.UUID,
    result: DailyScoringResult,
    *,
    emission_config: DecisionEmissionConfig | None = None,
) -> list[ActionCard]:
    """``emit_scoring_cards`` with the historic ``list[ActionCard]`` shape.

    The single production entry point for both callers
    (``action_cards.refresh`` and ``cdp_speed.decision_rules_scoring``) and
    the only function this module has ever exported for them. It delegates --
    it is not a second implementation -- so anything proven through
    ``emit_scoring_cards`` is proven about this path too; the report is
    available to callers that want the suppression reasons.

    The returned list holds every card the run resolved to: rows written by
    this run, and rows it deliberately left standing.
    """
    report = await emit_scoring_cards(session, shop_id, result, emission_config=emission_config)
    return report.cards

"""Reconstruct past cards' ``card_events`` for one shop (ADR-107 amendment §5, P60-1a).

``backfill_shop(session, shop_id)`` reads the tables that already hold each
stage and inserts the events the amendment marks reconstructable, with
``source = 'backfill'`` and the same ``dedup_key`` the live writers use -- so a
second run, or a run after the live writers started, inserts nothing twice
(``ON CONFLICT DO NOTHING``). Resumable by construction: a run cut short is
finished by running it again.

- ``proposed`` -- ``action_cards`` (text, payload, subject); ``model_version``
  from ``metadata_json`` else ``'unknown'``; readiness and features NULL (never
  recorded, not recomputed: no retroactive pre-registration).
- ``superseded`` -- the successor's ``supersedes_card_id``, at its
  ``computed_at`` / ``created_at``.
- ``shown`` -- ``action_cards.surfaced_at`` (NULL -> none; a dismissal clears
  it, so a dismissed card has none).
- ``accepted`` -- ``action_card_approvals`` (one per approval) and the run
  created with it.
- ``dismissed`` -- ``action_cards.dismissed_at``, ``reason_code =
  'unspecified'``; not for a card closed by a run decline or revert
  (``decision_reasons``).
- ``executed`` / ``not_executed`` -- the run's terminal ``workflow_run_events``
  row + ``workflow_runs.status`` / ``stop_reason``; a lever flow's
  ``applied_at`` as the apply time.
- ``reverted`` -- a finished revert run (``workflow_runs.reverts_run_id``).
- ``impact_preliminary`` / ``impact_final`` -- ``impact_readings`` by run and
  kind, then ``run_measurement_finals``.

Not reconstructed (amendment §5): ``edited``, ``expired``, ``seller_done``,
``shadow``. ``seller_change`` is left to P60-1b: it needs the per-field
attribution of §8, and an unattributed row written now would hold the dedup
key a correct one needs (the table is append-only) -- DEBT P60-1a.

Runs on the caller's session under the shop's scope (ADR-089); no commit.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_SELLER,
    ACTOR_SYSTEM,
    EVENT_ACCEPTED,
    EVENT_DISMISSED,
    EVENT_PROPOSED,
    EVENT_SHOWN,
    EVENT_SUPERSEDED,
    SOURCE_BACKFILL,
)
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.outcomes import TERMINAL_RUN_STATUSES
from juli_backend.services.card_events.writer import (
    REASON_UNSPECIFIED,
    EventSpec,
    card_payload,
    impact_event_type,
    insert_event,
    measurement_final_payload,
    metadata_model_version,
    readings_payload,
    run_outcome_spec,
)

UNKNOWN_MODEL_VERSION = "unknown"
#: An approval and the run it created are written in one transaction; their
#: timestamps (Python clock vs ``now()``) differ by well under this.
APPROVAL_RUN_MATCH_WINDOW = timedelta(minutes=10)
TERMINAL_EVENT_TYPES = ("workflow.completed", "workflow.failed")
#: ``decision_reasons.action`` values that close a card without it being dismissed.
_RUN_CLOSING_ACTIONS = ("decline", "revert")


@dataclass
class BackfillReport:
    shop_id: uuid.UUID
    considered: dict[str, int] = field(default_factory=dict)
    inserted: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shop_id": str(self.shop_id),
            "considered": dict(self.considered),
            "inserted": dict(self.inserted),
            "inserted_total": sum(self.inserted.values()),
        }


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _subject(card: Any, tiktok_ids: dict[uuid.UUID, str]) -> tuple[str, str]:
    from juli_backend.services.action_cards.subjects import card_product_uuid

    product_uuid = card_product_uuid(card)
    if product_uuid is not None and product_uuid in tiktok_ids:
        return card.subject_type, tiktok_ids[product_uuid]
    return card.subject_type, card.subject_id or ""


def _spec(card: Any, subject: tuple[str, str], **kw: Any) -> EventSpec:
    return EventSpec(
        shop_id=card.shop_id,
        card_id=card.id,
        workflow_key=card.workflow_key,
        subject_type=subject[0],
        subject_id=subject[1],
        source=SOURCE_BACKFILL,
        **kw,
    )


# -- pure mappings (one source row -> one event) ----------------------------------------


def proposed_spec(card: Any, subject: tuple[str, str]) -> EventSpec:
    return _spec(
        card,
        subject,
        event_type=EVENT_PROPOSED,
        actor="juli",
        occurred_at=card.computed_at or card.created_at,
        dedup_key=keys.proposed(card.id),
        model_version=metadata_model_version(card) or UNKNOWN_MODEL_VERSION,
        payload=card_payload(card),
    )


def superseded_spec(predecessor: Any, successor: Any, subject: tuple[str, str]) -> EventSpec:
    return _spec(
        predecessor,
        subject,
        event_type=EVENT_SUPERSEDED,
        actor=ACTOR_SYSTEM,
        occurred_at=successor.computed_at or successor.created_at,
        dedup_key=keys.superseded(predecessor.id),
        payload={"successor_card_id": successor.id, "revision": successor.revision},
    )


def shown_spec(card: Any, subject: tuple[str, str]) -> EventSpec | None:
    if card.surfaced_at is None:
        return None
    return _spec(
        card,
        subject,
        event_type=EVENT_SHOWN,
        actor=ACTOR_SYSTEM,
        occurred_at=card.surfaced_at,
        dedup_key=keys.shown(card.id),
    )


def accepted_spec(
    card: Any, subject: tuple[str, str], approval: Any, run_id: uuid.UUID | None
) -> EventSpec:
    return _spec(
        card,
        subject,
        event_type=EVENT_ACCEPTED,
        actor=ACTOR_SELLER,
        occurred_at=approval.approved_at,
        dedup_key=keys.accepted(approval.id),
        workflow_run_id=run_id,
        payload={"approval_id": approval.id, "approved_by_user_id": approval.approved_by_user_id},
    )


def dismissed_spec(card: Any, subject: tuple[str, str], reasons: Sequence[Any]) -> EventSpec | None:
    """``None`` when the card was not dismissed, or was closed by a run decline / revert."""
    if card.dismissed_at is None:
        return None
    if any(r.action in _RUN_CLOSING_ACTIONS for r in reasons):
        return None
    reject = next((r for r in reasons if r.action == "reject"), None)
    return _spec(
        card,
        subject,
        event_type=EVENT_DISMISSED,
        actor=ACTOR_SELLER,
        occurred_at=card.dismissed_at,
        dedup_key=keys.dismissed(card.id),
        reason_code=REASON_UNSPECIFIED,
        payload={
            "decision_reason_code": reject.reason_code if reject is not None else None,
            "decision_reason_id": reject.id if reject is not None else None,
        },
    )


def match_run(approved_at: datetime, runs: Iterable[Any]) -> uuid.UUID | None:
    """The run created with an approval: nearest ``created_at`` inside the window."""
    best: tuple[timedelta, uuid.UUID] | None = None
    for run in runs:
        if run.created_at is None:
            continue
        gap = abs(_naive(run.created_at) - _naive(approved_at))
        if gap <= APPROVAL_RUN_MATCH_WINDOW and (best is None or gap < best[0]):
            best = (gap, run.id)
    return best[1] if best else None


def terminal_events(rows: Iterable[Any]) -> dict[uuid.UUID, Any]:
    """Per run, its last terminal ``workflow_run_events`` row."""
    last: dict[uuid.UUID, Any] = {}
    for row in rows:
        current = last.get(row.workflow_run_id)
        if current is None or row.sequence_number > current.sequence_number:
            last[row.workflow_run_id] = row
    return last


def run_outcome_backfill_spec(
    card: Any,
    subject: tuple[str, str],
    run: Any,
    terminal: Any | None,
    applied_at: datetime | None,
) -> EventSpec | None:
    if run.status not in TERMINAL_RUN_STATUSES:
        return None
    occurred_at = (
        terminal.timestamp if terminal is not None and terminal.timestamp else run.completed_at
    )
    if occurred_at is None:
        return None
    return run_outcome_spec(
        card,
        subject,
        run,
        status=run.status,
        stop_reason=run.stop_reason,
        occurred_at=occurred_at,
        source=SOURCE_BACKFILL,
        applied_at=applied_at,
    )


def impact_specs(card: Any, subject: tuple[str, str], run: Any, readings: Sequence[Any]) -> list:
    """One event per kind from one run's ``impact_readings``."""
    by_kind: dict[str, list[Any]] = defaultdict(list)
    for reading in readings:
        by_kind[reading.kind].append(reading)
    specs = []
    for kind in sorted(by_kind):
        event_type = impact_event_type(kind)
        if event_type is None:
            continue
        rows = by_kind[kind]
        specs.append(
            _spec(
                card,
                subject,
                event_type=event_type,
                actor=ACTOR_SYSTEM,
                occurred_at=min(r.computed_at for r in rows),
                dedup_key=keys.impact(event_type, run.id),
                workflow_run_id=run.id,
                payload={"source_table": "impact_readings", **readings_payload(rows)},
            )
        )
    return specs


def final_spec(card: Any, subject: tuple[str, str], run: Any, final: Any) -> EventSpec:
    event_type = impact_event_type("final")
    assert event_type is not None
    return _spec(
        card,
        subject,
        event_type=event_type,
        actor=ACTOR_SYSTEM,
        occurred_at=final.computed_at,
        dedup_key=keys.impact(event_type, run.id),
        workflow_run_id=run.id,
        payload={"source_table": "run_measurement_finals", **measurement_final_payload(final)},
    )


# -- the job ----------------------------------------------------------------------------


async def _product_tiktok_ids(
    session: AsyncSession, shop_id: uuid.UUID, cards: Iterable[Any]
) -> dict[uuid.UUID, str]:
    from juli_backend.models.models import Product
    from juli_backend.services.action_cards.subjects import card_product_uuid

    wanted = {pid for pid in (card_product_uuid(c) for c in cards) if pid is not None}
    if not wanted:
        return {}
    rows = await session.execute(
        select(Product.id, Product.tiktok_product_id).where(
            Product.shop_id == shop_id, Product.id.in_(list(wanted))
        )
    )
    return {pid: str(tid) for pid, tid in rows.all() if tid}


async def collect_specs(session: AsyncSession, shop_id: uuid.UUID) -> list[EventSpec]:
    """Every reconstructable event of the shop, in stage order."""
    from juli_backend.models.decision_reasons import DecisionReason
    from juli_backend.models.lever_flows import RunLeverFlow, RunMeasurementFinal
    from juli_backend.models.models import (
        ActionCard,
        ActionCardApproval,
        ImpactReading,
        WorkflowRun,
        WorkflowRunEvent,
    )

    cards = list(
        (
            await session.execute(
                select(ActionCard)
                .where(ActionCard.shop_id == shop_id)
                .order_by(ActionCard.created_at, ActionCard.id)
            )
        ).scalars()
    )
    if not cards:
        return []
    by_id = {card.id: card for card in cards}
    tiktok_ids = await _product_tiktok_ids(session, shop_id, cards)
    subjects = {card.id: _subject(card, tiktok_ids) for card in cards}
    card_ids = list(by_id)

    all_runs = list(
        (
            await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.shop_id == shop_id, WorkflowRun.action_card_id.isnot(None))
                .order_by(WorkflowRun.created_at, WorkflowRun.id)
            )
        ).scalars()
    )
    #: Only runs of this shop's cards (typed loosely: ``action_card_id`` is checked here).
    runs: list[Any] = [run for run in all_runs if run.action_card_id in by_id]
    run_ids = [run.id for run in runs]
    runs_by_card: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for run in runs:
        if run.reverts_run_id is None:
            runs_by_card[run.action_card_id].append(run)

    approvals = list(
        (
            await session.execute(
                select(ActionCardApproval)
                .where(ActionCardApproval.action_card_id.in_(card_ids))
                .order_by(ActionCardApproval.approved_at, ActionCardApproval.id)
            )
        ).scalars()
    )
    reasons: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for reason in (
        await session.execute(
            select(DecisionReason).where(
                DecisionReason.shop_id == shop_id, DecisionReason.action_card_id.in_(card_ids)
            )
        )
    ).scalars():
        if reason.action_card_id is not None:
            reasons[reason.action_card_id].append(reason)

    terminal: dict[uuid.UUID, Any] = {}
    applied: dict[uuid.UUID, datetime] = {}
    readings: dict[uuid.UUID, list[Any]] = defaultdict(list)
    finals: dict[uuid.UUID, Any] = {}
    if run_ids:
        terminal = terminal_events(
            (
                await session.execute(
                    select(WorkflowRunEvent).where(
                        WorkflowRunEvent.workflow_run_id.in_(run_ids),
                        WorkflowRunEvent.event_type.in_(TERMINAL_EVENT_TYPES),
                    )
                )
            ).scalars()
        )
        for flow in (
            await session.execute(
                select(RunLeverFlow).where(
                    RunLeverFlow.shop_id == shop_id, RunLeverFlow.workflow_run_id.in_(run_ids)
                )
            )
        ).scalars():
            if flow.applied_at is not None:
                applied[flow.workflow_run_id] = flow.applied_at
        for reading in (
            await session.execute(
                select(ImpactReading)
                .where(ImpactReading.run_id.in_(run_ids))
                .order_by(ImpactReading.computed_at, ImpactReading.id)
            )
        ).scalars():
            if reading.run_id is not None:
                readings[reading.run_id].append(reading)
        for final in (
            await session.execute(
                select(RunMeasurementFinal).where(
                    RunMeasurementFinal.shop_id == shop_id,
                    RunMeasurementFinal.workflow_run_id.in_(run_ids),
                )
            )
        ).scalars():
            finals[final.workflow_run_id] = final

    specs: list[EventSpec] = []
    for card in cards:
        specs.append(proposed_spec(card, subjects[card.id]))
    for card in cards:
        predecessor = by_id.get(card.supersedes_card_id) if card.supersedes_card_id else None
        if predecessor is not None:
            specs.append(superseded_spec(predecessor, card, subjects[predecessor.id]))
    for card in cards:
        shown = shown_spec(card, subjects[card.id])
        if shown is not None:
            specs.append(shown)
    for approval in approvals:
        card = by_id[approval.action_card_id]
        run_id = match_run(approval.approved_at, runs_by_card.get(card.id, ()))
        specs.append(accepted_spec(card, subjects[card.id], approval, run_id))
    for card in cards:
        dismissed = dismissed_spec(card, subjects[card.id], reasons.get(card.id, ()))
        if dismissed is not None:
            specs.append(dismissed)
    for run in runs:
        card = by_id[run.action_card_id]
        outcome = run_outcome_backfill_spec(
            card, subjects[card.id], run, terminal.get(run.id), applied.get(run.id)
        )
        if outcome is not None:
            specs.append(outcome)
    for run in runs:
        if run.reverts_run_id is not None:
            continue
        card = by_id[run.action_card_id]
        specs.extend(impact_specs(card, subjects[card.id], run, readings.get(run.id, ())))
        if run.id in finals:
            specs.append(final_spec(card, subjects[card.id], run, finals[run.id]))
    return specs


async def backfill_shop(session: AsyncSession, shop_id: uuid.UUID) -> BackfillReport:
    """Insert every reconstructable event of one shop; idempotent. No commit."""
    report = BackfillReport(shop_id=shop_id)
    for spec in await collect_specs(session, shop_id):
        report.considered[spec.event_type] = report.considered.get(spec.event_type, 0) + 1
        if await insert_event(session, spec):
            report.inserted[spec.event_type] = report.inserted.get(spec.event_type, 0) + 1
    return report


__all__ = [
    "APPROVAL_RUN_MATCH_WINDOW",
    "UNKNOWN_MODEL_VERSION",
    "BackfillReport",
    "accepted_spec",
    "backfill_shop",
    "collect_specs",
    "dismissed_spec",
    "final_spec",
    "impact_specs",
    "match_run",
    "proposed_spec",
    "run_outcome_backfill_spec",
    "shown_spec",
    "superseded_spec",
    "terminal_events",
]

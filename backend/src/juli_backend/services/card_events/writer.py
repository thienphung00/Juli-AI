"""Write ``card_events`` rows (ADR-107 amended 2026-10-20 §1-§3, fast track P60-1a).

Two layers:

- :func:`insert_event` -- one ``INSERT ... ON CONFLICT DO NOTHING`` of an
  :class:`EventSpec`; ``True`` when a row was written. Raises on a database
  error. The backfill uses it directly.
- the ``record_*`` functions -- one per event kind a live code path produces
  today. Each runs on the caller's session, in the caller's transaction (the
  amendment: "their writers also write the event in the same transaction"),
  inside a SAVEPOINT on Postgres, and **never raises**: a failure is logged as
  ``card_event_write_failed`` and rolled back to the savepoint, so the card,
  approval, run or reading it accompanies is never lost because its log row
  could not be written. Nothing here commits.

Every row carries a deterministic ``dedup_key`` shared with the backfill
(:mod:`.keys`), so a retried writer, a re-run backfill, or a backfill after a
live write inserts nothing twice.

Under Postgres the caller holds the shop's scope (request scope, or
``with_shop_scope`` in a fleet job, ADR-089); RLS refuses a row for another
shop, which lands here as a logged failure, not an exception.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from juli_backend.models.card_events import (
    ACTOR_JULI,
    ACTOR_SELLER,
    ACTOR_SYSTEM,
    EVENT_ACCEPTED,
    EVENT_DISMISSED,
    EVENT_EXECUTED,
    EVENT_EXPIRED,
    EVENT_IMPACT_FINAL,
    EVENT_IMPACT_PRELIMINARY,
    EVENT_NOT_EXECUTED,
    EVENT_PROPOSED,
    EVENT_REVERTED,
    EVENT_SHOWN,
    EVENT_SUPERSEDED,
    SCHEMA_VERSION,
    SOURCE_LIVE,
    CardEvent,
)
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.outcomes import (
    TERMINAL_RUN_STATUSES,
    is_executed,
    not_executed_group,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juli_backend.models.models import ActionCard, WorkflowRun

logger = logging.getLogger(__name__)

#: The rule path's version prefix (amendment §3: ``rules:<ADR+amendment>:<config_hash>``).
RULES_VERSION_PREFIX = "rules:ADR-107am2026-10-20"
#: ``dismissed`` with no seller choice (the reject dialog does not send one yet).
REASON_UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class EventSpec:
    """One ``card_events`` row to write."""

    shop_id: uuid.UUID
    card_id: uuid.UUID | None
    event_type: str
    actor: str
    occurred_at: datetime
    workflow_key: str
    subject_type: str
    subject_id: str
    dedup_key: str
    source: str = SOURCE_LIVE
    workflow_run_id: uuid.UUID | None = None
    model_version: str | None = None
    readiness_level: int | None = None
    feature_snapshot_id: uuid.UUID | None = None
    reason_code: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


def as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive value is taken as UTC (the branch stores naive UTC in places)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


def jsonable(value: Any) -> Any:
    """``value`` as plain JSON types (uuid / datetime / Decimal -> strings)."""
    return json.loads(json.dumps(value, default=_default, ensure_ascii=False))


def values_of(spec: EventSpec) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "card_id": spec.card_id,
        "shop_id": spec.shop_id,
        "workflow_key": spec.workflow_key[:64],
        "subject_type": spec.subject_type[:32],
        "subject_id": spec.subject_id[:100],
        "event_type": spec.event_type,
        "actor": spec.actor,
        "occurred_at": as_utc(spec.occurred_at),
        "source": spec.source,
        "workflow_run_id": spec.workflow_run_id,
        "model_version": spec.model_version[:128] if spec.model_version else spec.model_version,
        "readiness_level": spec.readiness_level,
        "feature_snapshot_id": spec.feature_snapshot_id,
        "reason_code": spec.reason_code,
        "payload": jsonable(dict(spec.payload)),
        "schema_version": SCHEMA_VERSION,
        "dedup_key": spec.dedup_key[:255],
    }


def _dialect(session: AsyncSession) -> str:
    try:
        bind = session.get_bind()
    except Exception:
        return "unknown"
    return str(getattr(getattr(bind, "dialect", None), "name", "unknown"))


async def insert_event(session: AsyncSession, spec: EventSpec) -> bool:
    """Insert one event unless its ``dedup_key`` (or single-per-card slot) is taken."""
    insert = postgresql.insert if _dialect(session) == "postgresql" else sqlite.insert
    stmt = insert(CardEvent).values(**values_of(spec)).on_conflict_do_nothing()
    result = await session.execute(stmt)
    return bool(getattr(result, "rowcount", 0) == 1)


@asynccontextmanager
async def _guarded(session: AsyncSession, what: str, **extra: Any) -> AsyncIterator[None]:
    """A savepoint (Postgres) around the body; any failure is logged, never raised."""
    try:
        if _dialect(session) == "postgresql":
            async with session.begin_nested():
                yield
        else:
            yield
    except Exception as exc:
        logger.warning(
            "card_event_write_failed",
            extra={
                "event": what,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
                **{k: str(v) for k, v in extra.items()},
            },
            exc_info=True,
        )


# -- card context -------------------------------------------------------------------------


async def card_subject(session: AsyncSession, card: ActionCard) -> tuple[str, str]:
    """``(subject_type, subject_id)``: the TikTok product id for a product card.

    Falls back to the card's own ``subject_id`` (a ``products.id``, a lever-scoped
    ref, or ``""`` for an unscoped card) when the product row is not found.
    """
    from juli_backend.models.models import Product
    from juli_backend.services.action_cards.subjects import card_product_uuid

    product_uuid = card_product_uuid(card)
    if product_uuid is not None:
        found = await session.execute(
            select(Product.tiktok_product_id).where(
                Product.id == product_uuid, Product.shop_id == card.shop_id
            )
        )
        tiktok_id = found.scalar_one_or_none()
        if tiktok_id:
            return card.subject_type, str(tiktok_id)
    return card.subject_type, card.subject_id or ""


def _card_spec(
    card: ActionCard, subject: tuple[str, str], *, event_type: str, actor: str, **kw: Any
) -> EventSpec:
    return EventSpec(
        shop_id=card.shop_id,
        card_id=card.id,
        event_type=event_type,
        actor=actor,
        workflow_key=card.workflow_key,
        subject_type=subject[0],
        subject_id=subject[1],
        **kw,
    )


def card_payload(card: ActionCard) -> dict[str, Any]:
    """What a ``proposed`` row freezes of the card (amendment §3, §5: text and subject)."""
    try:
        recommendation = json.loads(card.recommendation_payload or "{}")
    except (TypeError, ValueError):
        recommendation = {"raw": card.recommendation_payload}
    return {
        "title": card.title,
        "description": card.description,
        "recommendation_payload": recommendation,
        "revision": card.revision,
        "supersedes_card_id": card.supersedes_card_id,
        "card_subject_id": card.subject_id,
        "priority": card.priority,
        "severity": card.severity,
    }


def metadata_model_version(card: ActionCard) -> str | None:
    """A ``model_version`` the card's ``metadata_json`` already carries, if any."""
    try:
        meta = json.loads(card.metadata_json or "{}")
    except (TypeError, ValueError):
        return None
    value = meta.get("model_version") if isinstance(meta, dict) else None
    return str(value) if value else None


def rules_model_version(config: Any) -> str:
    """``rules:<ADR+amendment>:<config_hash>`` for the rule path (amendment §3)."""
    try:
        body = json.dumps(jsonable(config), sort_keys=True)
    except (TypeError, ValueError):
        body = repr(config)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return f"{RULES_VERSION_PREFIX}:{digest}"


# -- live writers -------------------------------------------------------------------------


async def record_proposed(
    session: AsyncSession,
    card: ActionCard,
    *,
    occurred_at: datetime,
    model_version: str,
) -> None:
    """``proposed`` for a card emission (nightly scoring, quick scan, ADR-087 revision)."""
    async with _guarded(session, EVENT_PROPOSED, card_id=card.id):
        subject = await card_subject(session, card)
        await insert_event(
            session,
            _card_spec(
                card,
                subject,
                event_type=EVENT_PROPOSED,
                actor=ACTOR_JULI,
                occurred_at=occurred_at,
                dedup_key=keys.proposed(card.id),
                model_version=metadata_model_version(card) or model_version,
                payload=card_payload(card),
            ),
        )


async def record_superseded(
    session: AsyncSession,
    predecessor_id: uuid.UUID,
    successor: ActionCard,
    *,
    occurred_at: datetime,
) -> None:
    """``superseded`` on the predecessor when its successor revision is emitted (ADR-087)."""
    from juli_backend.models.models import ActionCard as ActionCardRow

    async with _guarded(session, EVENT_SUPERSEDED, card_id=predecessor_id):
        predecessor = await session.get(ActionCardRow, predecessor_id)
        if predecessor is None or predecessor.shop_id != successor.shop_id:
            return
        subject = await card_subject(session, predecessor)
        await insert_event(
            session,
            _card_spec(
                predecessor,
                subject,
                event_type=EVENT_SUPERSEDED,
                actor=ACTOR_SYSTEM,
                occurred_at=occurred_at,
                dedup_key=keys.superseded(predecessor_id),
                payload={"successor_card_id": successor.id, "revision": successor.revision},
            ),
        )


async def record_emissions(
    session: AsyncSession,
    decisions: Iterable[Any],
    *,
    occurred_at: datetime,
    config: Any,
) -> None:
    """``proposed`` (+ ``superseded``) for every card an emission pass wrote.

    *decisions* are ``persist.CardEmission``: only ``emitted`` ones with a card.
    An in-place rewrite of a never-shown draft keeps its first ``proposed`` row
    (single per card) -- DEBT P60-1a.
    """
    version = rules_model_version(config)
    for decision in decisions:
        card = getattr(decision, "card", None)
        if card is None or getattr(decision, "suppressed_reason", None) is not None:
            continue
        await record_proposed(session, card, occurred_at=occurred_at, model_version=version)
        predecessor = getattr(decision, "supersedes_card_id", None)
        if predecessor is not None:
            await record_superseded(session, predecessor, card, occurred_at=occurred_at)


async def record_budget_outcome(
    session: AsyncSession,
    *,
    newly_surfaced: Sequence[ActionCard],
    expired: Sequence[ActionCard],
    now: datetime,
) -> None:
    """``shown`` (first display only) and ``expired`` from one emission-budget pass."""
    for card in newly_surfaced:
        async with _guarded(session, EVENT_SHOWN, card_id=card.id):
            subject = await card_subject(session, card)
            await insert_event(
                session,
                _card_spec(
                    card,
                    subject,
                    event_type=EVENT_SHOWN,
                    actor=ACTOR_SYSTEM,
                    occurred_at=card.surfaced_at or now,
                    dedup_key=keys.shown(card.id),
                ),
            )
    for card in expired:
        async with _guarded(session, EVENT_EXPIRED, card_id=card.id):
            subject = await card_subject(session, card)
            await insert_event(
                session,
                _card_spec(
                    card,
                    subject,
                    event_type=EVENT_EXPIRED,
                    actor=ACTOR_SYSTEM,
                    occurred_at=now,
                    dedup_key=keys.expired(card.id),
                    payload={"surfaced_at": card.surfaced_at},
                ),
            )


async def record_accepted(
    session: AsyncSession,
    card: ActionCard,
    *,
    approval_id: uuid.UUID,
    run_id: uuid.UUID | None,
    approved_by_user_id: uuid.UUID | None,
    occurred_at: datetime,
) -> None:
    """``accepted`` from the approve route (once per approval)."""
    async with _guarded(session, EVENT_ACCEPTED, card_id=card.id):
        subject = await card_subject(session, card)
        await insert_event(
            session,
            _card_spec(
                card,
                subject,
                event_type=EVENT_ACCEPTED,
                actor=ACTOR_SELLER,
                occurred_at=occurred_at,
                dedup_key=keys.accepted(approval_id),
                workflow_run_id=run_id,
                payload={"approval_id": approval_id, "approved_by_user_id": approved_by_user_id},
            ),
        )


async def record_dismissed(
    session: AsyncSession,
    card: ActionCard,
    *,
    occurred_at: datetime,
    decision_reason_code: str | None = None,
    decision_reason_id: uuid.UUID | None = None,
) -> None:
    """``dismissed`` from the "Từ chối" route.

    The route's reason codes (P10-A ``decision_reasons``) are not the amendment's
    five dismiss reasons, so ``reason_code`` is ``unspecified`` and the route's
    own code rides in the payload until the dismiss sheet sends one (DEBT P60-1a).
    """
    async with _guarded(session, EVENT_DISMISSED, card_id=card.id):
        subject = await card_subject(session, card)
        await insert_event(
            session,
            _card_spec(
                card,
                subject,
                event_type=EVENT_DISMISSED,
                actor=ACTOR_SELLER,
                occurred_at=occurred_at,
                dedup_key=keys.dismissed(card.id),
                reason_code=REASON_UNSPECIFIED,
                payload={
                    "decision_reason_code": decision_reason_code,
                    "decision_reason_id": decision_reason_id,
                },
            ),
        )


def run_outcome_spec(
    card: ActionCard,
    subject: tuple[str, str],
    run: WorkflowRun,
    *,
    status: str,
    stop_reason: str | None,
    occurred_at: datetime,
    source: str = SOURCE_LIVE,
    applied_at: datetime | None = None,
) -> EventSpec | None:
    """The ``executed`` / ``not_executed`` / ``reverted`` row a terminal run implies.

    ``None`` for a non-terminal status, and for a revert run that did not finish
    (a failed revert is not a card stage).
    """
    if status not in TERMINAL_RUN_STATUSES:
        return None
    executed = is_executed(status, stop_reason)
    if run.reverts_run_id is not None:
        if not executed:
            return None
        return _card_spec(
            card,
            subject,
            event_type=EVENT_REVERTED,
            actor=ACTOR_SELLER,
            occurred_at=occurred_at,
            source=source,
            dedup_key=keys.reverted(run.id),
            workflow_run_id=run.id,
            payload={"reverts_run_id": run.reverts_run_id},
        )
    payload: dict[str, Any] = {"status": status, "stop_reason": stop_reason}
    if executed:
        if applied_at is not None:
            payload["applied_at"] = applied_at
        return _card_spec(
            card,
            subject,
            event_type=EVENT_EXECUTED,
            actor=ACTOR_JULI,
            occurred_at=applied_at or occurred_at,
            source=source,
            dedup_key=keys.run_outcome(run.id),
            workflow_run_id=run.id,
            payload=payload,
        )
    payload["group"] = not_executed_group(stop_reason)
    return _card_spec(
        card,
        subject,
        event_type=EVENT_NOT_EXECUTED,
        actor=ACTOR_JULI,
        occurred_at=occurred_at,
        source=source,
        dedup_key=keys.run_outcome(run.id),
        workflow_run_id=run.id,
        payload=payload,
    )


async def record_run_outcome(
    session: AsyncSession,
    run: WorkflowRun,
    *,
    status: Any,
    stop_reason: Any,
    occurred_at: datetime | None = None,
) -> None:
    """``executed`` / ``not_executed`` (or ``reverted``) from a run's terminal writer.

    Called beside ``card_reactivation.reactivate_card_for_ended_run`` by every
    terminal writer (runner persist, crash handler, reaper) and by the lever-flow
    seller decline. A run with no card writes nothing.
    """
    from juli_backend.models.models import ActionCard as ActionCardRow

    status_value = str(getattr(status, "value", status))
    if status_value not in TERMINAL_RUN_STATUSES or not getattr(run, "action_card_id", None):
        return
    reason_value = None if stop_reason is None else str(getattr(stop_reason, "value", stop_reason))
    async with _guarded(session, "run_outcome", run_id=run.id):
        card = await session.get(ActionCardRow, run.action_card_id)
        if card is None or card.shop_id != run.shop_id:
            return
        subject = await card_subject(session, card)
        spec = run_outcome_spec(
            card,
            subject,
            run,
            status=status_value,
            stop_reason=reason_value,
            occurred_at=occurred_at or run.completed_at or datetime.now(UTC),
        )
        if spec is not None:
            await insert_event(session, spec)


def impact_event_type(kind: str) -> str | None:
    return {"preliminary": EVENT_IMPACT_PRELIMINARY, "final": EVENT_IMPACT_FINAL}.get(kind)


async def record_impact(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None,
    kind: str,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    source_table: str,
) -> None:
    """``impact_preliminary`` / ``impact_final`` for a run's card (once per run and kind).

    From the ADR-077 impact reader (``impact_readings``) and the day-14
    ``run_measurement_finals`` writers; whichever lands first for a run is kept.
    Revert runs (which carry the original card) are not credited to the card.
    """
    from juli_backend.models.models import ActionCard as ActionCardRow
    from juli_backend.models.models import WorkflowRun as WorkflowRunRow

    event_type = impact_event_type(kind)
    if run_id is None or event_type is None:
        return
    async with _guarded(session, event_type, run_id=run_id):
        run = await session.get(WorkflowRunRow, run_id)
        if run is None or not run.action_card_id or run.reverts_run_id is not None:
            return
        card = await session.get(ActionCardRow, run.action_card_id)
        if card is None or card.shop_id != run.shop_id:
            return
        subject = await card_subject(session, card)
        await insert_event(
            session,
            _card_spec(
                card,
                subject,
                event_type=event_type,
                actor=ACTOR_SYSTEM,
                occurred_at=occurred_at,
                dedup_key=keys.impact(event_type, run_id),
                workflow_run_id=run_id,
                payload={"source_table": source_table, **dict(payload)},
            ),
        )


async def record_impact_readings(
    session: AsyncSession, *, run_id: uuid.UUID | None, kind: str, occurred_at: datetime
) -> None:
    """``impact_*`` from the ADR-077 impact reader, with the run's readings of that kind."""
    from juli_backend.models.models import ImpactReading

    if run_id is None or impact_event_type(kind) is None:
        return
    async with _guarded(session, "impact_readings", run_id=run_id):
        rows = (
            (
                await session.execute(
                    select(ImpactReading).where(
                        ImpactReading.run_id == run_id, ImpactReading.kind == kind
                    )
                )
            )
            .scalars()
            .all()
        )
        await record_impact(
            session,
            run_id=run_id,
            kind=kind,
            occurred_at=occurred_at,
            payload=readings_payload(rows),
            source_table="impact_readings",
        )


def measurement_final_payload(row: Any) -> dict[str, Any]:
    """The ``impact_final`` payload of one ``run_measurement_finals`` row."""
    return {
        "measurement_final_id": row.id,
        "label": row.label,
        "lever": row.lever,
        "pct_of_expected": row.pct_of_expected,
        "gmv_actual_per_day": row.gmv_actual_per_day,
    }


async def record_measurement_final(session: AsyncSession, row: Any) -> None:
    """``impact_final`` from a just-written ``run_measurement_finals`` row."""
    await record_impact(
        session,
        run_id=row.workflow_run_id,
        kind="final",
        # ``computed_at`` is a server default, unloaded right after the flush (an
        # attribute load here would be lazy I/O on an async session).
        occurred_at=row.__dict__.get("computed_at") or datetime.now(UTC),
        payload=measurement_final_payload(row),
        source_table="run_measurement_finals",
    )


def readings_payload(rows: Iterable[Any]) -> dict[str, Any]:
    """The impact payload of one run's ``impact_readings`` rows of one kind."""
    readings = [
        {
            "reading_id": r.id,
            "tool_execution_id": r.tool_execution_id,
            "metric": r.metric,
            "pre": r.pre,
            "post": r.post,
            "expected": r.expected,
            "incremental": r.incremental,
            "impact_pct": r.impact_pct,
            "confidence": r.confidence,
            "series_source": r.series_source,
        }
        for r in rows
    ]
    readings.sort(key=lambda r: (str(r["tool_execution_id"]), str(r["metric"])))
    return {"readings": readings}


__all__ = [
    "REASON_UNSPECIFIED",
    "RULES_VERSION_PREFIX",
    "EventSpec",
    "as_utc",
    "card_payload",
    "card_subject",
    "impact_event_type",
    "insert_event",
    "jsonable",
    "measurement_final_payload",
    "metadata_model_version",
    "readings_payload",
    "record_accepted",
    "record_budget_outcome",
    "record_dismissed",
    "record_emissions",
    "record_impact",
    "record_impact_readings",
    "record_measurement_final",
    "record_proposed",
    "record_run_outcome",
    "record_superseded",
    "rules_model_version",
    "run_outcome_spec",
    "values_of",
]

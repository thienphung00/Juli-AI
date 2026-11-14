"""Persistence of recommendation cards and their learning state (no business rules here).

A card is three rows sharing ONE id: an ``action_cards`` row (the id ``card_events`` needs;
status ``shopee_reco`` keeps it out of the TikTok Decision feed, which reads ``active``), a
``shop_proposals`` row (the change and its approval / execution / result cycle, ADR-118) and a
``proposed`` event in ``card_events`` freezing the whole payload (ADR-121 d.3). Everything runs
on the caller's session under the shop's scope and never commits.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_JULI,
    EVENT_ACCEPTED,
    EVENT_DISMISSED,
    EVENT_EXPIRED,
    EVENT_PROPOSED,
    EVENT_WHATIF_ADJUSTED,
    CardEvent,
)
from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    STATUS_SENT,
    ShopProposal,
    ShopProposalExecution,
)
from juli_backend.models.shopee_recommendations import (
    SIM_STATUS_ACTIVE,
    SIM_STATUS_SUPERSEDED,
    ShopeeRecoCalibration,
    ShopeeSimPriorRun,
)
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.writer import EventSpec, insert_event
from juli_backend.services.shopee_recommendations import codes, config, result_store
from juli_backend.services.shopee_recommendations.cards import proposal_fields
from juli_backend.services.shopee_recommendations.learning import (
    AcceptanceStats,
    CalibrationState,
    Observation,
    acceptance_from_events,
)
from juli_backend.services.shopee_recommendations.sim_priors import SimPriors

CARD_STATUS = "shopee_reco"
ORIGIN_ENGINE = "engine"
WORKFLOW_PREFIX = "shopee_reco"
#: Proposal statuses that hold their products against a new card.
LOCKING_STATUSES = (
    STATUS_SENT,
    STATUS_CHANGES_REQUESTED,
    STATUS_PLANNED,
    STATUS_APPROVED,
    STATUS_EXECUTED,
)


def workflow_key(card: Mapping[str, Any], card_id: uuid.UUID) -> str:
    return f"{WORKFLOW_PREFIX}:{card['change_kind']}:{card_id.hex[:12]}"[:64]


def _subject(card: Mapping[str, Any], card_id: uuid.UUID) -> tuple[str, str]:
    items = card["scope"]["product_ids"]
    if items:
        return "item", str(items[0])[:64]
    return card["scope"]["level"] if card["scope"]["level"] in ("shop", "campaign") else "shop", (
        card["scope"].get("campaign_key") or ""
    )[:64]


async def save_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card: dict[str, Any],
    *,
    cycle: str,
    position: int,
    now: datetime,
    supersedes: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    card_id: uuid.UUID | None = None,
    existing: ShopProposal | None = None,
    product_queue: int | None = None,
) -> uuid.UUID:
    """Write a new card as a ``draft`` proposal (Ops publishes it) and freeze it. ``existing``
    is a proposal ADR-118's ``revise`` already created (its id is the card id). The card gets
    its code here (P91 D-5) and, for a card that replaces another, ``supersedes_code``."""
    cid = existing.id if existing is not None else (card_id or uuid.uuid4())
    card["id"] = str(cid)
    code = await codes.assign_code(session, shop_id, now)
    card["code"] = code
    for v in card.get("versions") or []:
        v["code"] = codes.version_code(code, int(v["version"]))
    old_id = supersedes or (existing.supersedes_id if existing is not None else None)
    if old_id is not None:
        card["supersedes_id"] = str(old_id)
        card["supersedes_code"] = await session.scalar(
            select(ShopProposal.code).where(ShopProposal.id == old_id)
        )
    subj_type, subj_id = _subject(card, cid)
    fields = proposal_fields(card, "")
    locked = sorted({*card["scope"]["product_ids"], *card.get("locked_items", [])})
    meta = {
        "source": "shopee_reco",
        "change_kind": card["change_kind"],
        "family": card["family"],
        "plan_days": card["measurement_plan"]["planned_days"],
        "locked_items": locked,
        "stale": False,
        "cycle": cycle,
        "lock_until": (card.get("lock") or {}).get("until"),
        "rank_score": (card.get("rank") or {}).get("score"),
        "code": code,
    }
    session.add(
        ActionCard(
            id=cid,
            shop_id=shop_id,
            workflow_key=workflow_key(card, cid),
            subject_type=subj_type,
            subject_id=subj_id,
            revision=1,
            priority=position,
            severity="info",
            title=card["title"][:255],
            description=(card.get("reason") or "")[:2000],
            recommendation_payload=json.dumps(
                {"change_kind": card["change_kind"], "rank": card.get("rank")}
            ),
            status=CARD_STATUS,
            metadata_json=json.dumps(meta),
            computed_at=now,
        )
    )
    if existing is not None:
        existing.code = code
    if existing is None:
        session.add(
            ShopProposal(
                id=cid,
                shop_id=shop_id,
                platform="shopee",
                cycle=cycle,
                kind=fields["kind"],
                subject_type=fields["subject_type"],
                item_id=fields["item_id"] if fields["subject_type"] == "item" else None,
                subject_label=fields["subject_label"],
                change_before=fields["change_before"],
                change_after=fields["change_after"],
                reason=fields["reason"],
                status=STATUS_DRAFT,
                revision=1,
                supersedes_id=supersedes,
                code=code,
                product_queue=product_queue,
                proposed_by_staff_id=staff_id,
                created_at=now,
                updated_at=now,
            )
        )
    await session.flush()
    await insert_event(
        session,
        EventSpec(
            shop_id=shop_id,
            card_id=cid,
            event_type=EVENT_PROPOSED,
            actor=ACTOR_JULI,
            occurred_at=now,
            workflow_key=f"{WORKFLOW_PREFIX}:{card['family']}",
            subject_type=subj_type,
            subject_id=subj_id or str(cid),
            dedup_key=keys.proposed(cid),
            model_version=config.RULES_VERSION,
            payload=card,
        ),
    )
    return cid


async def card_payload(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any] | None:
    """The frozen ``proposed`` payload of a card, with its newest stored results laid over it
    (``result_store.apply``: a recomputed result lives in the card's metadata)."""
    ev = await session.scalar(
        select(CardEvent).where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_PROPOSED,
        )
    )
    if ev is None:
        return None
    meta = await session.scalar(
        select(ActionCard.metadata_json).where(
            ActionCard.id == card_id, ActionCard.shop_id == shop_id
        )
    )
    return result_store.apply(copy.deepcopy(dict(ev.payload)), json.loads(meta or "{}"))


async def list_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    statuses: Sequence[str] | None = None,
    cycle: str | None = None,
) -> list[tuple[ShopProposal, dict[str, Any]]]:
    """Proposals of this package (``action_cards.status = shopee_reco`` ids) with their frozen
    payload, newest first."""
    stmt = (
        select(ShopProposal)
        .join(ActionCard, ActionCard.id == ShopProposal.id)
        .where(ShopProposal.shop_id == shop_id, ActionCard.status == CARD_STATUS)
    )
    if statuses:
        stmt = stmt.where(ShopProposal.status.in_(list(statuses)))
    if cycle:
        stmt = stmt.where(ShopProposal.cycle == cycle)
    proposals = list((await session.scalars(stmt.order_by(ShopProposal.created_at.desc()))).all())
    if not proposals:
        return []
    events = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.shop_id == shop_id,
                CardEvent.event_type == EVENT_PROPOSED,
                CardEvent.card_id.in_([p.id for p in proposals]),
            )
        )
    ).all()
    rows = await session.execute(
        select(ActionCard.id, ActionCard.metadata_json).where(
            ActionCard.id.in_([p.id for p in proposals])
        )
    )
    metas: dict[uuid.UUID, str | None] = {r[0]: r[1] for r in rows.all()}
    by_card = {
        e.card_id: result_store.apply(
            copy.deepcopy(dict(e.payload)),
            json.loads((metas.get(e.card_id) if e.card_id else None) or "{}"),
        )
        for e in events
    }
    return [(p, by_card[p.id]) for p in proposals if p.id in by_card]


async def card_meta(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any]:
    row = await session.scalar(
        select(ActionCard).where(ActionCard.id == card_id, ActionCard.shop_id == shop_id)
    )
    return {} if row is None or not row.metadata_json else json.loads(row.metadata_json)


async def set_meta(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, patch: Mapping[str, Any]
) -> None:
    row = await session.scalar(
        select(ActionCard).where(ActionCard.id == card_id, ActionCard.shop_id == shop_id)
    )
    if row is None:
        return
    meta = json.loads(row.metadata_json or "{}")
    meta.update(patch)
    row.metadata_json = json.dumps(meta)


def provenance(card: Mapping[str, Any]) -> dict[str, Any]:
    """``{origin, created_by?}`` of a card: ``engine`` unless a person built it by hand."""
    out: dict[str, Any] = {"origin": card.get("origin") or ORIGIN_ENGINE}
    if card.get("created_by"):
        out["created_by"] = dict(card["created_by"])
    return out


async def write_event(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    event_type: str,
    actor: str,
    occurred_at: datetime,
    dedup_key: str,
    payload: Mapping[str, Any],
    family: str,
    change_kind: str,
    subject: tuple[str, str],
    reason_code: str | None = None,
    code: str | None = None,
    card: Mapping[str, Any] | None = None,
) -> bool:
    """Write one journey event. ``card`` (the frozen payload) adds who made the card
    (``origin`` engine / manual, and ``created_by`` for a manual one), so the learning
    statistics can be split by origin (P91 D-3)."""
    if card is not None:
        payload = {**provenance(card), **payload}
    if code is not None:
        payload = {"code": code, **payload}
    return await insert_event(
        session,
        EventSpec(
            shop_id=shop_id,
            card_id=card_id,
            event_type=event_type,
            actor=actor,
            occurred_at=occurred_at,
            workflow_key=f"{WORKFLOW_PREFIX}:{family}",
            subject_type=subject[0],
            subject_id=subject[1] or str(card_id),
            dedup_key=dedup_key,
            reason_code=reason_code,
            payload={"change_kind": change_kind, **payload},
        ),
    )


# ------------------------------------------------------------------------------- locks


async def locked_products(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime | None
) -> dict[str, str]:
    """Products held by an open plan: sent / approved cards, and executed ones until the
    measurement plan ends (14 days when the card has no plan). A product inside an active
    mega_sale window is held the same way (the mega_sale card lists its children's products)."""
    rows = (
        await session.execute(
            select(ShopProposal.id, ShopProposal.status, ActionCard.metadata_json)
            .join(ActionCard, ActionCard.id == ShopProposal.id)
            .where(
                ShopProposal.shop_id == shop_id,
                ActionCard.status == CARD_STATUS,
                ShopProposal.status.in_(LOCKING_STATUSES),
            )
        )
    ).all()
    executed_at: dict[uuid.UUID, datetime] = {}
    executed_ids = [r.id for r in rows if r.status == STATUS_EXECUTED]
    if executed_ids:
        for ex in await session.execute(
            select(ShopProposalExecution.proposal_id, ShopProposalExecution.executed_at).where(
                ShopProposalExecution.proposal_id.in_(executed_ids)
            )
        ):
            executed_at[ex.proposal_id] = max(
                ex.executed_at, executed_at.get(ex.proposal_id, ex.executed_at)
            )
    out: dict[str, str] = {}
    for r in rows:
        meta = json.loads(r.metadata_json or "{}")
        if r.status == STATUS_EXECUTED and meta.get("measure_cut_at"):
            continue  # a newer change cut this measurement: the product is free again
        until = meta.get("lock_until")
        if (
            until
            and now is not None
            and r.status != STATUS_EXECUTED
            and now > datetime.fromisoformat(until)
        ):
            continue  # the mega_sale window is over
        if r.status == STATUS_EXECUTED and now is not None:
            started = executed_at.get(r.id)
            days = int(meta.get("plan_days") or 14)
            if started is not None and now > started + timedelta(days=days):
                continue
        for item in meta.get("locked_items", []):
            out.setdefault(str(item), f"{r.status}:{r.id}")
    return out


# ---------------------------------------------------------------------------- sim priors


async def load_sim(session: AsyncSession, shop_id: uuid.UUID) -> SimPriors | None:
    run = await session.scalar(
        select(ShopeeSimPriorRun)
        .where(ShopeeSimPriorRun.shop_id == shop_id, ShopeeSimPriorRun.status == SIM_STATUS_ACTIVE)
        .order_by(ShopeeSimPriorRun.imported_at.desc())
    )
    if run is None:
        return None
    return SimPriors.from_stored(
        {
            "run_id": run.run_id,
            "shop_alias": run.shop_alias,
            "model_version": run.model_version,
            "priors_version": run.priors_version,
            "gate": run.gate,
        },
        run.rows,
    )


async def save_sim(
    session: AsyncSession,
    shop_id: uuid.UUID,
    priors: SimPriors,
    *,
    sha256: str,
    staff_id: uuid.UUID | None,
    now: datetime,
) -> ShopeeSimPriorRun:
    """Store a run as the shop's active one; older runs become ``superseded``."""
    existing = await session.scalar(
        select(ShopeeSimPriorRun).where(
            ShopeeSimPriorRun.shop_id == shop_id, ShopeeSimPriorRun.run_id == priors.run_id[:64]
        )
    )
    await session.execute(
        update(ShopeeSimPriorRun)
        .where(
            ShopeeSimPriorRun.shop_id == shop_id,
            ShopeeSimPriorRun.status == SIM_STATUS_ACTIVE,
            ShopeeSimPriorRun.run_id != priors.run_id[:64],
        )
        .values(status=SIM_STATUS_SUPERSEDED)
    )
    run = existing or ShopeeSimPriorRun(id=uuid.uuid4(), shop_id=shop_id, run_id=priors.run_id[:64])
    # importing the same run again replaces it (a new gate override, a corrected file)
    run.shop_alias = priors.shop_alias[:64]
    run.model_version = priors.model_version[:64]
    run.priors_version = priors.priors_version[:64]
    run.gate = priors.gate
    run.rows = priors.to_stored()
    run.row_count = len(priors.rows)
    run.source_sha256 = sha256
    run.status = SIM_STATUS_ACTIVE
    run.imported_by_staff_id = staff_id
    run.imported_at = now
    session.add(run)
    await session.flush()
    return run


# ----------------------------------------------------------------------- calibration


async def load_calibrations(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[tuple[str, str], CalibrationState]:
    rows = (
        await session.scalars(
            select(ShopeeRecoCalibration).where(ShopeeRecoCalibration.shop_id == shop_id)
        )
    ).all()
    return {
        (r.change_kind, r.metric): CalibrationState(
            r.change_kind,
            r.metric,
            r.n_results,
            None if r.pooled_ratio is None else float(r.pooled_ratio),
            r.coverage_n,
            r.coverage_hits,
            float(r.range_scale),
            r.n_bundle_excluded,
            dict(r.sources or {}),
        )
        for r in rows
    }


async def load_observations(session: AsyncSession, shop_id: uuid.UUID) -> list[Observation]:
    rows = (
        await session.scalars(
            select(ShopeeRecoCalibration).where(ShopeeRecoCalibration.shop_id == shop_id)
        )
    ).all()
    return [Observation.from_json(o) for r in rows for o in (r.observations or [])]


async def save_calibrations(
    session: AsyncSession,
    shop_id: uuid.UUID,
    states: Mapping[tuple[str, str], CalibrationState],
    observations: Iterable[Observation],
    *,
    now: datetime,
) -> int:
    """Upsert one row per (change_kind, metric) with the scored observations behind it."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for o in observations:
        by_key.setdefault((o.change_kind, o.metric), []).append(o.json())
    existing = {
        (r.change_kind, r.metric): r
        for r in (
            await session.scalars(
                select(ShopeeRecoCalibration).where(ShopeeRecoCalibration.shop_id == shop_id)
            )
        ).all()
    }
    n = 0
    for key, st in states.items():
        row = existing.get(key)
        if row is None:
            row = ShopeeRecoCalibration(
                id=uuid.uuid4(), shop_id=shop_id, change_kind=key[0], metric=key[1]
            )
            session.add(row)
        row.n_results = st.n_results
        row.pooled_ratio = (
            None if st.pooled_ratio is None else Decimal(str(round(st.pooled_ratio, 6)))
        )
        row.coverage_n = st.coverage_n
        row.coverage_hits = st.coverage_hits
        row.range_scale = Decimal(str(round(st.range_scale, 4)))
        row.n_bundle_excluded = st.n_bundle_excluded
        row.sources = dict(st.sources)
        row.observations = by_key.get(key, [])
        row.computed_at = now
        n += 1
    await session.flush()
    return n


# ------------------------------------------------------------------------ acceptance


async def load_acceptance(
    session: AsyncSession, shop_id: uuid.UUID, *, origin: str | None = "engine"
) -> AcceptanceStats:
    """The decision statistics of the cards made by ``origin`` (default the engine's)."""
    rows = (
        await session.execute(
            select(CardEvent.event_type, CardEvent.reason_code, CardEvent.payload).where(
                CardEvent.shop_id == shop_id,
                CardEvent.workflow_key.like(f"{WORKFLOW_PREFIX}:%"),
                CardEvent.event_type.in_(
                    [EVENT_ACCEPTED, EVENT_DISMISSED, EVENT_EXPIRED, EVENT_WHATIF_ADJUSTED]
                ),
            )
        )
    ).all()
    return acceptance_from_events(
        (
            {"event_type": r.event_type, "reason_code": r.reason_code, "payload": r.payload}
            for r in rows
        ),
        origin,
    )


__all__ = ["and_"]

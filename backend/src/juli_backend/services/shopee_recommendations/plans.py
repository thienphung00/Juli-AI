"""The draft plan ("Kế hoạch", P91 D-6): approve without executing, see the aggregate, confirm
all at once.

- A shop has at most one **draft** plan. "Thêm vào kế hoạch" puts a card (a chosen version) in it:
  the card becomes ``planned`` (out of its product's queue, so the next card moves up); nothing is
  executed and nothing reaches the team. Cards can be removed (back to the status they had), their
  version switched or their what-if inputs moved; every change re-aggregates at once
  (:mod:`.plan_aggregate`: joint, not summed).
- **Confirm never blocks.** A floor or spend-cap breach in the plan needs ``acknowledge_breaches``
  (422 listing them otherwise); who, when and which breaches is recorded on the plan and in each
  card's ``accepted`` event. On confirm the plan gets ``KH-<yymm>-<seq3>``, every card becomes
  ``approved`` with the plan id (``shop_proposals.lever_plan_id``), the chosen version and ONE
  planned execution date (``planned_start``); an approval row is written per card exactly as an
  in-app decision (seller) or a recorded decision (staff, evidence ``plan:<code>``).
- The plan is ``executed`` when every card of it is (``on_executed``); the cards run through the
  assisted execution of the cards (``service.mark_executed``) and their change sets
  (:mod:`.change_sets`).
- The measurement window (default for the plan, override per product) is stored on the plan and
  copied onto the change sets at execution; the confirm response lists the products whose running
  measurement the execution will cut.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_JULI,
    ACTOR_SELLER,
    EVENT_ACCEPTED,
    EVENT_WHATIF_ADJUSTED,
)
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    STATUS_SENT,
    ShopProposal,
    ShopProposalApproval,
)
from juli_backend.models.shopee_plans import (
    PLAN_CONFIRMED,
    PLAN_DRAFT,
    PLAN_EXECUTED,
    ShopRecoPlan,
    ShopRecoPlanCard,
)
from juli_backend.services.card_events import keys
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import (
    change_sets,
    config,
    manual,
    plan_codes,
    product_queue,
    service,
    store,
    versions,
)
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.plan_aggregate import (
    Entry,
    aggregate,
    evaluate_entry,
)

ERROR_UNKNOWN_PLAN = "reco_plan_not_found"
ERROR_NOT_DRAFT = "reco_plan_not_draft"
ERROR_EMPTY = "reco_plan_empty"
ERROR_CARD_STATE = "reco_card_not_plannable"
ERROR_NOT_IN_PLAN = "reco_card_not_in_plan"
ERROR_BREACH = "reco_plan_breach_unacknowledged"
ERROR_DATE = "reco_plan_date_invalid"
#: statuses a card may be added to the plan from: the seller can see and decide on it
ADDABLE = (STATUS_SENT, STATUS_CHANGES_REQUESTED)


class PlanBreachNotAcknowledged(ProposalError):
    """The plan (or the card being added) breaks a floor or the spend cap and the request did not
    acknowledge it. Never a disabled button: the caller shows the warning and asks again."""

    def __init__(self, breaches: list[dict[str, Any]], what: str = "the plan") -> None:
        super().__init__(
            ERROR_BREACH, 422, f"{what} breaks a floor price or the spend cap; acknowledge it"
        )
        self.breaches = breaches


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


# ----------------------------------------------------------------------------- storage


async def draft_of(session: AsyncSession, shop_id: uuid.UUID) -> ShopRecoPlan | None:
    return await session.scalar(
        select(ShopRecoPlan).where(
            ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.status == PLAN_DRAFT
        )
    )


async def get_plan_row(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID
) -> ShopRecoPlan:
    row = await session.scalar(
        select(ShopRecoPlan).where(ShopRecoPlan.id == plan_id, ShopRecoPlan.shop_id == shop_id)
    )
    if row is None:
        raise ProposalError(ERROR_UNKNOWN_PLAN, 404)
    return row


async def _require_draft(session: AsyncSession, shop_id: uuid.UUID) -> ShopRecoPlan:
    plan = await draft_of(session, shop_id)
    if plan is None:
        raise ProposalError(ERROR_UNKNOWN_PLAN, 404, "the shop has no draft plan")
    return plan


async def _ensure_draft(
    session: AsyncSession, shop_id: uuid.UUID, actor: manual.Actor, now: datetime
) -> ShopRecoPlan:
    plan = await draft_of(session, shop_id)
    if plan is None:
        plan = ShopRecoPlan(
            id=uuid.uuid4(),
            shop_id=shop_id,
            status=PLAN_DRAFT,
            product_windows={},
            created_by=actor.json(),
            created_at=now,
            updated_at=now,
        )
        session.add(plan)
        await session.flush()
    return plan


async def _rows(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID, *, active: bool = True
) -> list[tuple[ShopRecoPlanCard, ShopProposal]]:
    stmt = (
        select(ShopRecoPlanCard, ShopProposal)
        .join(ShopProposal, ShopProposal.id == ShopRecoPlanCard.proposal_id)
        .where(ShopRecoPlanCard.shop_id == shop_id, ShopRecoPlanCard.plan_id == plan_id)
        .order_by(ShopRecoPlanCard.position, ShopRecoPlanCard.added_at, ShopRecoPlanCard.id)
    )
    if active:
        stmt = stmt.where(ShopRecoPlanCard.removed_at.is_(None))
    return [(r[0], r[1]) for r in (await session.execute(stmt)).all()]


async def _row_of(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[ShopRecoPlanCard, ShopProposal]:
    for row, p in await _rows(session, shop_id, plan_id):
        if p.id == card_id:
            return row, p
    raise ProposalError(ERROR_NOT_IN_PLAN, 404, "the card is not in the draft plan")


async def _entries(
    session: AsyncSession, shop_id: uuid.UUID, rows: list[tuple[ShopRecoPlanCard, ShopProposal]]
) -> list[Entry]:
    out: list[Entry] = []
    for row, p in rows:
        payload = await store.card_payload(session, shop_id, p.id)
        if payload is None:
            continue
        base = {**payload, "code": p.code, "product_queue": p.product_queue}
        out.append(Entry(str(p.id), p.code, base, int(row.chosen_version), dict(row.inputs or {})))
    return out


def _actor_event(actor: manual.Actor) -> str:
    return ACTOR_SELLER if actor.kind == "seller" else ACTOR_JULI


# --------------------------------------------------------------------------------- read


def _windows_block(plan: ShopRecoPlan, agg: Mapping[str, Any]) -> dict[str, Any]:
    per_product = []
    for block in agg.get("products", []):
        pid = block["product_id"]
        days, source = change_sets.resolve_window(plan, dict(agg), pid, {})
        per_product.append(
            {
                "product_id": pid,
                "name": block.get("name"),
                "days": days,
                "source": source,
                "recommended_days": block["window"]["recommended_days"],
                "options": block["window"],
                "orders_per_day": block["orders_per_day"],
                "hard": block["window"]["recommended_days"] is None
                and days in config.WINDOW_PRESETS,
            }
        )
    return {
        "plan_default_days": plan.window_days,
        "plan_default_source": "plan" if plan.window_days else "auto",
        "min_days": config.WINDOW_MIN_DAYS,
        "max_days": config.WINDOW_MAX_DAYS,
        "presets": list(config.WINDOW_PRESETS),
        "per_product": per_product,
    }


def _plan_json(plan: ShopRecoPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "status": plan.status,
        "code": plan.code,
        "as_of": None if plan.as_of is None else plan.as_of.isoformat(),
        "window_days": plan.window_days,
        "product_windows": dict(plan.product_windows or {}),
        "planned_date": None if plan.planned_date is None else plan.planned_date.isoformat(),
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "confirmed_by": plan.confirmed_by,
        "confirmed_at": None if plan.confirmed_at is None else plan.confirmed_at.isoformat(),
        "executed_at": None if plan.executed_at is None else plan.executed_at.isoformat(),
        "acknowledged_breaches": plan.acknowledged_breaches,
        "measurement_cut": plan.cut_measurements or [],
    }


async def get_plan(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan_id: uuid.UUID | None = None,
    *,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    """The plan with its cards and the aggregate. ``plan_id`` None = the shop's draft (an empty
    answer when there is none). A draft is re-aggregated on today's numbers; a confirmed plan
    returns the aggregate it was confirmed with."""
    now = _naive(now)
    plan = await draft_of(session, shop_id) if plan_id is None else None
    if plan_id is not None:
        plan = await get_plan_row(session, shop_id, plan_id)
    if plan is None:
        return {"plan": None, "cards": [], "aggregate": None, "windows": None, "change_sets": []}
    rows = await _rows(session, shop_id, plan.id)
    agg: dict[str, Any]
    if plan.status == PLAN_DRAFT:
        env = await load_env(session, shop_id, now=now)
        if env is None:
            raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
        agg, _ = aggregate(env, await _entries(session, shop_id, rows), now=now)
        names = {b["product_id"]: b.get("name") for b in agg.get("products", [])}
        cut = await change_sets.cut_preview(
            session, shop_id, [b["product_id"] for b in agg.get("products", [])],
            plan.planned_date or now.date(), names,
        )  # fmt: skip
    else:
        agg = dict(plan.aggregate or {})
        cut = list(plan.cut_measurements or [])
    blocks = {c["card_id"]: c for c in agg.get("cards", [])}
    cards: list[dict[str, Any]] = []
    for row, p in rows:
        payload = await store.card_payload(session, shop_id, p.id) or {}
        vlist = versions.versions_of({**payload, "code": p.code})
        chosen = vlist[min(row.chosen_version, len(vlist)) - 1]
        cards.append(
            {
                "card_id": str(p.id),
                "code": p.code,
                "plan_code": plan.code,
                "status": p.status,
                "product_id": p.item_id,
                "title": payload.get("title"),
                "family": payload.get("family"),
                "change_kind": payload.get("change_kind"),
                "chosen_version": row.chosen_version,
                "chosen_version_code": chosen.get("code"),
                "versions": [service._version_brief(v) for v in vlist],
                "what_if": dict(row.inputs or {}),
                "added_at": row.added_at.isoformat() if row.added_at else None,
                "added_by": row.added_by,
                "acknowledged_breaches": row.acknowledged_breaches,
                "evaluation": blocks.get(str(p.id)),
            }
        )
    sets = await change_sets.sets_for(session, shop_id, plan_id=plan.id)
    out = {
        "plan": {**_plan_json(plan), "measurement_cut": cut},
        "cards": cards,
        "aggregate": agg,
        "windows": _windows_block(plan, agg) if agg.get("n_cards") else None,
        "change_sets": [change_sets.to_json(s, now=now) for s in sets],
    }
    if audience == "seller":
        out["aggregate"] = _seller_aggregate(agg)
    return out


def _seller_aggregate(agg: dict[str, Any]) -> dict[str, Any]:
    """Nothing in the aggregate names the model, the calibration or the simulation; the window
    options carry alpha / power which the seller does not need."""
    out = dict(agg)
    products = []
    for block in agg.get("products", []):
        window = {k: v for k, v in block["window"].items() if k not in ("alpha", "power")}
        products.append({**block, "window": window})
    if "products" in out:
        out["products"] = products
    return out


async def list_plans(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ShopRecoPlan)
            .where(ShopRecoPlan.shop_id == shop_id)
            .order_by(ShopRecoPlan.created_at.desc(), ShopRecoPlan.id)
        )
    ).all()
    out = []
    for plan in rows:
        n = len(await _rows(session, shop_id, plan.id))
        out.append({**_plan_json(plan), "n_cards": n})
    return out


async def plan_by_code(
    session: AsyncSession, shop_id: uuid.UUID, code: str, *, now: datetime, audience: str = "ops"
) -> dict[str, Any]:
    norm = plan_codes.parse_plan_code(code)
    row = (
        None
        if norm is None
        else await session.scalar(
            select(ShopRecoPlan).where(ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.code == norm)
        )
    )
    if row is None:
        raise ProposalError(ERROR_UNKNOWN_PLAN, 404)
    return await get_plan(session, shop_id, row.id, now=now, audience=audience)


# -------------------------------------------------------------------------------- edit


async def add_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    chosen_version: int = 1,
    actor: manual.Actor,
    now: datetime,
    acknowledge_breaches: bool = False,
) -> dict[str, Any]:
    """ "Thêm vào kế hoạch": the card (this version) joins the draft plan, status ``planned``."""
    now = _naive(now)
    p, payload = await service._proposal(session, shop_id, card_id)
    if p.status not in ADDABLE:
        raise ProposalError(ERROR_CARD_STATE, 409, f"a {p.status} card cannot be added to a plan")
    vlist = versions.versions_of({**payload, "code": p.code})
    if not 1 <= chosen_version <= len(vlist):
        raise ProposalError("reco_version_unknown", 422, f"the card has {len(vlist)} version(s)")
    if vlist[chosen_version - 1].get("status") == versions.STATUS_REFUSED:
        raise ProposalError("reco_version_unavailable", 422, "this version cannot be evaluated")
    plan = await _ensure_draft(session, shop_id, actor, now)
    current = await _rows(session, shop_id, plan.id)
    if len(current) >= config.PLAN_MAX_CARDS:
        raise ProposalError("reco_plan_full", 409, f"a plan holds at most {config.PLAN_MAX_CARDS}")
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    entry = Entry(str(p.id), p.code, {**payload, "code": p.code}, chosen_version, {})
    ev = evaluate_entry(env, entry, now=now)
    if ev is None:
        raise ProposalError(service.ERROR_BAD_INPUT, 422, "this version cannot be evaluated")
    breaches = manual.breaches_of(ev.card)
    if breaches and not acknowledge_breaches:
        raise PlanBreachNotAcknowledged(breaches, "this card")
    acknowledged = {"by": actor.json(), "at": now.isoformat(), "breaches": breaches}
    session.add(
        ShopRecoPlanCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            plan_id=plan.id,
            proposal_id=p.id,
            chosen_version=chosen_version,
            inputs={},
            prior_status=p.status,
            position=len(current) + 1,
            added_by=actor.json(),
            acknowledged_breaches=acknowledged if breaches else None,
            added_at=now,
        )
    )
    p.status = STATUS_PLANNED
    p.lever_plan_id = plan.id
    p.updated_at = now
    plan.as_of = env.as_of
    plan.updated_at = now
    await store.set_meta(session, shop_id, p.id, {"plan_id": str(plan.id)})
    await session.flush()
    if p.item_id:
        await product_queue.requeue_products(session, shop_id, [p.item_id], now)
    return await get_plan(session, shop_id, plan.id, now=now)


async def remove_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    actor: manual.Actor,
    now: datetime,
) -> dict[str, Any]:
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    row, p = await _row_of(session, shop_id, plan.id, card_id)
    row.removed_at = now
    p.status = row.prior_status
    p.lever_plan_id = None
    p.updated_at = now
    plan.updated_at = now
    await store.set_meta(session, shop_id, p.id, {"plan_id": None})
    await session.flush()
    if p.item_id:
        await product_queue.requeue_products(session, shop_id, [p.item_id], now)
    return await get_plan(session, shop_id, plan.id, now=now)


async def switch_version(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    version: int,
    *,
    actor: manual.Actor,
    now: datetime,
) -> dict[str, Any]:
    """Choose another version of a planned card. Its what-if inputs belong to the old version and
    are cleared."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    row, p = await _row_of(session, shop_id, plan.id, card_id)
    payload = await store.card_payload(session, shop_id, p.id) or {}
    vlist = versions.versions_of({**payload, "code": p.code})
    if not 1 <= version <= len(vlist):
        raise ProposalError("reco_version_unknown", 422, f"the card has {len(vlist)} version(s)")
    if vlist[version - 1].get("status") == versions.STATUS_REFUSED:
        raise ProposalError("reco_version_unavailable", 422, "this version cannot be evaluated")
    before = row.chosen_version
    row.chosen_version = version
    row.inputs = {}
    plan.updated_at = now
    await store.write_event(
        session,
        shop_id,
        p.id,
        event_type=EVENT_WHATIF_ADJUSTED,
        actor=_actor_event(actor),
        occurred_at=now,
        dedup_key=f"plan-switch:{p.id}:{uuid.uuid4()}",
        code=p.code,
        payload={
            "plan_id": str(plan.id),
            "version": version,
            "before_version": before,
            "switched_in_plan": True,
        },
        family=payload["family"],
        change_kind=payload["change_kind"],
        subject=service._subject_of(payload, p.id),
        card=payload,
    )
    await session.flush()
    return await get_plan(session, shop_id, plan.id, now=now)


async def whatif(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    inputs: dict[str, Any],
    *,
    actor: manual.Actor,
    now: datetime,
) -> dict[str, Any]:
    """Move what-if inputs on the chosen version of a planned card; the plan re-aggregates."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    row, p = await _row_of(session, shop_id, plan.id, card_id)
    payload = await store.card_payload(session, shop_id, p.id) or {}
    service.check_title_input(payload, inputs)
    merged = {**(row.inputs or {}), **inputs}
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    entry = Entry(str(p.id), p.code, {**payload, "code": p.code}, int(row.chosen_version), merged)
    ev = evaluate_entry(env, entry, now=now)
    if ev is None:
        raise ProposalError(service.ERROR_BAD_INPUT, 422, "these inputs cannot be evaluated")
    vlist = versions.versions_of({**payload, "code": p.code})
    row.inputs = merged
    plan.updated_at = now
    await store.write_event(
        session,
        shop_id,
        p.id,
        event_type=EVENT_WHATIF_ADJUSTED,
        actor=_actor_event(actor),
        occurred_at=now,
        dedup_key=f"plan-whatif:{p.id}:{uuid.uuid4()}",
        code=p.code,
        payload={
            "plan_id": str(plan.id),
            "version": row.chosen_version,
            "inputs": inputs,
            "before_inputs": vlist[row.chosen_version - 1].get("inputs") or payload["inputs"],
            "dprofit_month_p50": ev.card["rank_inputs"]["dprofit_p50"],
            "floor_ok": ev.card["floor"]["ok"],
        },
        family=payload["family"],
        change_kind=payload["change_kind"],
        subject=service._subject_of(payload, p.id),
        card=payload,
    )
    await session.flush()
    return await get_plan(session, shop_id, plan.id, now=now)


async def set_window(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    days: int | None,
    product_id: str | None = None,
    now: datetime,
) -> dict[str, Any]:
    """The plan's measurement window: ``days`` for all its cards (None = automatic per product), or
    for one ``product_id`` (None removes the override). 3..90 days, before the cards run."""
    now = _naive(now)
    plan = await draft_of(session, shop_id)
    if plan is None:
        plan = await session.scalar(
            select(ShopRecoPlan)
            .where(ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.status == PLAN_CONFIRMED)
            .order_by(ShopRecoPlan.confirmed_at.desc())
        )
    if plan is None:
        raise ProposalError(ERROR_UNKNOWN_PLAN, 404, "the shop has no draft or confirmed plan")
    n = None if days is None else change_sets.check_days(days)
    if product_id is None:
        plan.window_days = n
    else:
        windows = dict(plan.product_windows or {})
        if n is None:
            windows.pop(product_id, None)
        else:
            windows[product_id] = n
        plan.product_windows = windows
    plan.updated_at = now
    await session.flush()
    return await get_plan(session, shop_id, plan.id, now=now)


# ----------------------------------------------------------------------------- confirm


def _all_breaches(agg: Mapping[str, Any], evs: list[Any]) -> list[dict[str, Any]]:
    """The aggregate's breaches plus any card's own floor breach the stack did not name."""
    out = [dict(b) for b in agg.get("breaches", [])]
    named = {str(b.get("sku")) for b in out if b["type"] == "floor"}
    for e in evs:
        for b in e.card["floor"]["breaches"]:
            if str(b.get("sku")) not in named:
                out.append({"type": "floor", "card_id": e.entry.card_id, **b})
    return out


async def confirm(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    actor: manual.Actor,
    now: datetime,
    acknowledge_breaches: bool = False,
    planned_date: date | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """ "Xác nhận kế hoạch". Never blocked: a breach needs ``acknowledge_breaches`` (422 with the
    list otherwise). Every card becomes ``approved`` with the plan id and the one planned date."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    rows = await _rows(session, shop_id, plan.id)
    if not rows:
        raise ProposalError(ERROR_EMPTY, 422, "the plan has no card")
    when = planned_date or now.date()
    if when < now.date():
        raise ProposalError(ERROR_DATE, 422, "the planned date is in the past")
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    agg, evs = aggregate(env, await _entries(session, shop_id, rows), now=now)
    if agg.get("unavailable_cards"):
        bad = agg["unavailable_cards"]
        raise ProposalError(service.ERROR_BAD_INPUT, 422, f"cards that cannot be evaluated: {bad}")
    breaches = _all_breaches(agg, evs)
    if breaches and not acknowledge_breaches:
        raise PlanBreachNotAcknowledged(breaches)
    acknowledged = (
        {"by": actor.json(), "at": now.isoformat(), "breaches": breaches} if breaches else None
    )
    names = {b["product_id"]: b.get("name") for b in agg.get("products", [])}
    cut = await change_sets.cut_preview(
        session, shop_id, [b["product_id"] for b in agg.get("products", [])], when, names
    )
    code = await plan_codes.assign_plan_code(session, shop_id, now)
    by_id = {e.entry.card_id: e for e in evs}
    for row, p in rows:
        ev = by_id[str(p.id)]
        await _approve(
            session, shop_id, plan, code, row, p, ev, actor, now, when, acknowledged, note
        )
    plan.status = PLAN_CONFIRMED
    plan.code = code
    plan.as_of = env.as_of
    plan.planned_date = when
    plan.confirmed_at = now
    plan.confirmed_by = actor.json()
    plan.acknowledged_breaches = acknowledged
    plan.cut_measurements = cut
    plan.aggregate = {**agg, "plan_code": code}
    plan.updated_at = now
    await session.flush()
    await product_queue.requeue_products(
        session, shop_id, {p.item_id for _, p in rows if p.item_id}, now
    )
    out = await get_plan(session, shop_id, plan.id, now=now)
    out["measurement_cut"] = cut
    return out


async def _approve(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: ShopRecoPlan,
    code: str,
    row: ShopRecoPlanCard,
    p: ShopProposal,
    ev: Any,
    actor: manual.Actor,
    now: datetime,
    when: date,
    acknowledged: dict[str, Any] | None,
    note: str | None,
) -> None:
    card = ev.card
    payload = ev.entry.base
    chosen = row.chosen_version
    vcode = (card.get("versions") or [{}])[chosen - 1].get("code") or (
        p.code and f"{p.code}-V{chosen}"
    )
    in_app = actor.kind == "seller"
    snapshot = {
        **proposals.snapshot(p),
        "code": p.code,
        "chosen_version": chosen,
        "chosen_version_code": vcode,
        "chosen_inputs": card["inputs"],
        "chosen_change": card["change"],
        "acknowledged_breaches": acknowledged,
        "plan_id": str(plan.id),
        "plan_code": code,
        "planned_date": when.isoformat(),
    }
    approval = ShopProposalApproval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        proposal_id=p.id,
        decision=STATUS_APPROVED,
        channel="in_app" if in_app else "document",
        decided_by_user_id=actor.id if in_app else None,
        recorded_by_staff_id=None if in_app else (actor.staff_id or actor.id),
        evidence_ref=None if in_app else f"plan:{code}",
        proposal_snapshot=snapshot,
        note=note,
        decided_at=now,
        created_at=now,
    )
    session.add(approval)
    p.status = STATUS_APPROVED
    p.lever_plan_id = plan.id
    p.planned_start = when
    p.updated_at = now
    await session.flush()
    changed = bool(row.inputs) or chosen != 1
    final = {
        "inputs": card["inputs"],
        "execution_sheet": card["execution_sheet"],
        "change": card["change"],
    }
    await store.write_event(
        session,
        shop_id,
        p.id,
        event_type=EVENT_ACCEPTED,
        actor=_actor_event(actor),
        occurred_at=now,
        dedup_key=keys.accepted(approval.id),
        code=p.code,
        payload={
            "approval_id": str(approval.id),
            "code": p.code,
            "plan_id": str(plan.id),
            "plan_code": code,
            "planned_date": when.isoformat(),
            "chosen_version": chosen,
            "chosen_version_code": vcode,
            "acknowledged_breaches": acknowledged,
            "final": final if changed else None,
            "approved_with": {
                "inputs": card["inputs"],
                "execution_sheet": card["execution_sheet"],
            },
            "final_vs_default": service._final_vs_default(payload, dict(row.inputs or {})),
        },
        family=payload["family"],
        change_kind=payload["change_kind"],
        subject=service._subject_of(payload, p.id),
        card=payload,
    )
    await store.set_meta(
        session,
        shop_id,
        p.id,
        {
            "approved_at": now.isoformat(),
            "plan_id": str(plan.id),
            "plan_code": code,
            "planned_date": when.isoformat(),
        },
    )


# ---------------------------------------------------------------------------- executed


async def on_executed(
    session: AsyncSession, shop_id: uuid.UUID, proposal: ShopProposal, *, now: datetime
) -> bool:
    """A card of a confirmed plan was executed: the plan is ``executed`` once all its cards are.
    Returns True when this execution completed the plan."""
    if proposal.lever_plan_id is None:
        return False
    plan = await session.get(ShopRecoPlan, proposal.lever_plan_id)
    if plan is None or plan.status != PLAN_CONFIRMED:
        return False
    rows = await _rows(session, shop_id, plan.id)
    if rows and all(p.status == STATUS_EXECUTED for _, p in rows):
        plan.status = PLAN_EXECUTED
        plan.executed_at = _naive(now)
        plan.updated_at = _naive(now)
        await session.flush()
        return True
    return False


__all__ = [
    "ADDABLE",
    "PlanBreachNotAcknowledged",
    "add_card",
    "confirm",
    "get_plan",
    "list_plans",
    "on_executed",
    "plan_by_code",
    "remove_card",
    "set_window",
    "switch_version",
    "whatif",
]

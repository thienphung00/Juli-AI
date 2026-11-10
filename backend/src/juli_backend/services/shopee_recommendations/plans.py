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
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
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
    GROUP_APPROVED,
    PLAN_CONFIRMED,
    PLAN_DRAFT,
    PLAN_EXECUTED,
    ShopRecoPlan,
    ShopRecoPlanCard,
)
from juli_backend.services.card_events import keys
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_recommendations import (
    change_sets,
    codes,
    config,
    fill_queue_port,
    manual,
    plan_base,
    plan_codes,
    plan_groups,
    plan_steps,
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
ADS_NEW_KIND = "ads_new_campaign"
#: an Ads card nobody has read back yet: a state, never zeros
ADS_READBACK_NOT_READ: dict[str, Any] = {
    "state": "not_found",
    "label": "Chưa đọc kết quả chiến dịch",
    "reason": "not_read_yet",
    "reason_text": "Chưa đọc lại số liệu quảng cáo cho thẻ này.",
    "matched_by": None,
    "campaign": None,
    "candidates": [],
    "started_before_card": None,
    "actual": None,
}
ERROR_NOT_DRAFT = "reco_plan_not_draft"
ERROR_EMPTY = "reco_plan_empty"
ERROR_CARD_STATE = "reco_card_not_plannable"
ERROR_NOT_IN_PLAN = "reco_card_not_in_plan"
ERROR_BREACH = "reco_breach_not_acknowledged"
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


#: the shop's calendar (Asia/Ho_Chi_Minh, UTC+7): "today" of the plan's horizon
SHOP_TZ = timezone(timedelta(hours=7))


def plan_today(now: datetime) -> date:
    """P99b: the first day of the plan's 30-day horizon -- today in the shop's calendar."""
    return now.astimezone(SHOP_TZ).date() if now.tzinfo else now.date()


#: fields only one value of which can be live at a time (P94 "one live value per exclusive field"):
#: see :data:`plan_groups.EXCLUSIVE_FIELDS`; a second option on one moves to the next group
EXCLUSIVE_FIELDS = plan_groups.EXCLUSIVE_FIELDS


def exclusive_key(payload: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """``(field, subject, Vietnamese field name)`` of the first exclusive field the card writes."""
    keys = plan_groups.exclusive_keys(payload)
    return keys[0] if keys else None


async def _env_for(
    session: AsyncSession, shop_id: uuid.UUID, plan: ShopRecoPlan | None, now: datetime
) -> Any:
    """The environment a plan is evaluated on (P99b, owner 2026-11-10): a draft is recomputed live
    on the newest data -- never on a stale frozen ``as_of``. A confirmed plan keeps the aggregate
    it was confirmed with and is not evaluated again."""
    live = plan is None or plan.status == PLAN_DRAFT
    return await load_env(
        session, shop_id, as_of=None if live or plan is None else plan.as_of, now=now
    )


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


async def _aggregate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    env: Any,
    entries: list[Entry],
    *,
    now: datetime,
    base: Mapping[str, Any] | None,
    today: date | None = None,
    default_start: date | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """``aggregate`` with the variations of the cards' products: the option results (P98 / ADR-122
    d.2) rebuild a price lever's builder spec from them."""
    items = list(
        dict.fromkeys(
            i for e in entries for i in (e.base.get("scope") or {}).get("product_ids", [])
        )
    )
    variations: dict[str, list[dict[str, Any]]] = {}
    if items:
        from juli_backend.services.shopee_builder.service import variation_rows_for

        variations = await variation_rows_for(session, shop_id, env, items)
    return aggregate(
        env,
        entries,
        now=now,
        base=base,
        variations=variations,
        today=today,
        default_start=default_start,
    )


def missing_aggregate(exc: RowsNotMaterialized, today: date, n_cards: int) -> dict[str, Any]:
    """The draft plan's aggregate while its window has data days without stored daily rows: the
    state and the horizon, no figure (P99b)."""
    return {
        "data_missing": exc.json(),
        "horizon": {"from": today.isoformat(), "days": 30},
        "n_cards": n_cards,
        "today": None,
        "after": None,
        "cost": None,
        "cards": [],
        "products": [],
        "result_basis": None,
    }


def ads_readback_of(meta: Mapping[str, Any]) -> dict[str, Any]:
    """The Ads card's read-back as the read-back lane stored it (``card_meta["ads_readback"]``),
    passed through; missing = ``not_found`` / ``not_read_yet`` (never zeros)."""
    found = meta.get("ads_readback")
    return (
        dict(found)
        if isinstance(found, Mapping) and found.get("state")
        else dict(ADS_READBACK_NOT_READ)
    )


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
    """The plan with its cards, its groups and the aggregates. ``plan_id`` None = the shop's draft
    (an empty answer when there is none). A draft is re-aggregated on its frozen base; a confirmed
    plan returns the aggregates it was confirmed with.

    ``aggregate`` is the plan math over the cards that are in no group; each group in ``groups``
    carries its own (the same math over its members: one joint lift per product, order independent),
    so a group is judged on its own period (P94).

    P99b: a draft is recomputed live on the newest data, as the expected outcome over the next
    30 days from today (``aggregate.horizon``); the stored base snapshot is no longer used."""
    today = plan_today(now)
    now = _naive(now)
    plan = await draft_of(session, shop_id) if plan_id is None else None
    if plan_id is not None:
        plan = await get_plan_row(session, shop_id, plan_id)
    if plan is None:
        return {
            "plan": None,
            "cards": [],
            "aggregate": None,
            "groups": [],
            "windows": None,
            "change_sets": [],
        }
    rows = await _rows(session, shop_id, plan.id)
    group_rows = await plan_groups.active_groups(session, shop_id, plan.id)
    by_group = await plan_groups.members_by_group(session, shop_id, plan.id)
    grouped = plan_groups.grouped_card_ids(by_group)
    agg: dict[str, Any]
    group_aggs: dict[uuid.UUID, dict[str, Any] | None] = {}
    base_block: dict[str, Any] | None = None
    missing: RowsNotMaterialized | None = None
    if plan.status == PLAN_DRAFT:
        try:
            env = await _env_for(session, shop_id, plan, now)
        except RowsNotMaterialized as exc:  # P99b: the plan shows the state, never numbers
            env, missing = None, exc
    if missing is not None:
        agg = missing_aggregate(missing, today, len(rows))
        for g in group_rows:
            group_aggs[g.id] = None
        cut = []
    elif plan.status == PLAN_DRAFT:
        if env is None:
            raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
        base_block = plan_base.live_block(env, today)
        base = None
        agg, _ = await _aggregate(
            session,
            shop_id,
            env,
            await _entries(session, shop_id, [(r, p) for r, p in rows if r.id not in grouped]),
            now=now,
            base=base,
            today=today,
        )
        group_periods = plan_groups.periods(plan, group_rows, today=today)
        for g in group_rows:
            entries = await plan_groups.entries_of(session, shop_id, by_group.get(g.id, []))
            group_aggs[g.id] = None
            if entries:
                group_aggs[g.id] = (
                    await _aggregate(
                        session, shop_id, env, entries, now=now, base=base, today=today,
                        default_start=group_periods[g.id][0],
                    )
                )[0]  # fmt: skip
        products = [*agg.get("products", []), *_group_products(group_aggs.values())]
        names = {b["product_id"]: b.get("name") for b in products}
        cut = await change_sets.cut_preview(
            session, shop_id, list(names), plan.planned_date or now.date(), names,
        )  # fmt: skip
    else:
        frozen = dict(plan.aggregate or {})
        agg = {k: v for k, v in frozen.items() if k != "groups"}
        for g in group_rows:
            group_aggs[g.id] = (frozen.get("groups") or {}).get(g.letter)
        cut = list(plan.cut_measurements or [])
    blocks = {c["card_id"]: c for c in agg.get("cards", [])}
    group_blocks: dict[str, dict[str, Any]] = {}
    for gagg in group_aggs.values():
        for c in (gagg or {}).get("cards", []):
            group_blocks.setdefault(plan_groups.split_entry_id(c["card_id"])[0], c)
    cards: list[dict[str, Any]] = []
    member_of: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for g in group_rows:
        for m, c, p in by_group.get(g.id, []):
            member_of.setdefault(c.id, []).append({"letter": g.letter, "version": int(m.version)})
    payloads: dict[uuid.UUID, dict[str, Any]] = {}
    for row, p in rows:
        payload = await store.card_payload(session, shop_id, p.id) or {}
        payloads[p.id] = payload
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
                "groups": member_of.get(row.id, []),
                "n_targets": len(payload.get("targets") or []),
                "evaluation": blocks.get(str(p.id)) or group_blocks.get(str(p.id)),
            }
        )
        if payload.get("change_kind") == ADS_NEW_KIND:
            meta = await store.card_meta(session, shop_id, p.id)
            cards[-1]["ads_readback"] = ads_readback_of(meta)
    windows_of = plan_groups.periods(plan, group_rows, today=now.date())
    groups: list[dict[str, Any]] = []
    for g in group_rows:
        members = [
            plan_groups.member_json(m, c, p, payloads.get(p.id) or {})
            for m, c, p in by_group.get(g.id, [])
        ]
        groups.append(
            plan_groups.group_json(g, windows_of[g.id], members, aggregate=group_aggs.get(g.id))
        )
    sets = await change_sets.sets_for(session, shop_id, plan_id=plan.id)
    n_all = int(agg.get("n_cards") or 0) + sum(
        int((a or {}).get("n_cards") or 0) for a in group_aggs.values()
    )
    windows_agg = {
        **agg,
        "products": [*agg.get("products", []), *_group_products(group_aggs.values())],
    }
    out = {
        "plan": {**_plan_json(plan), "measurement_cut": cut, "base": base_block},
        "cards": cards,
        "aggregate": agg,
        "groups": groups,
        "windows": _windows_block(plan, windows_agg) if n_all else None,
        "change_sets": [change_sets.to_json(s, now=now) for s in sets],
    }
    if audience == "seller":
        out["aggregate"] = _seller_aggregate(agg)
        for g_json in groups:
            if g_json["aggregate"] is not None:
                g_json["aggregate"] = _seller_aggregate(g_json["aggregate"])
    return out


def _group_products(aggs: Iterable[Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """The per-product blocks of the groups' aggregates (a product once)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for gagg in aggs:
        for block in (gagg or {}).get("products", []):
            if block["product_id"] not in seen:
                seen.add(block["product_id"])
                out.append(block)
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
    chosen_version: int | None = None,
    actor: manual.Actor,
    now: datetime,
    acknowledge_breaches: bool = False,
) -> dict[str, Any]:
    """ "Thêm vào kế hoạch": the card (this version) joins the draft plan, status ``planned``.

    ``chosen_version`` None = the version and what-if inputs the card had when it was last removed
    from this plan (remove then re-add restores them, D85.4), else version 1.

    A card that writes a field the plan already has another card write (giá bán, tên, ảnh bìa ...
    of the same product, one campaign's budget / ROAS) cannot share a group with it: the two are
    put in groups that run one after the other (P94 / D85.14), said in the answer's ``notice``."""
    now = _naive(now)
    plan, row, p, payload, vlist, others = await _add_row(
        session,
        shop_id,
        card_id,
        chosen_version=chosen_version,
        actor=actor,
        now=now,
        acknowledge_breaches=acknowledge_breaches,
    )
    notice = None
    if others:
        notice = await _separate(session, shop_id, plan, row, p, payload, others, actor, now)
    out = await get_plan(session, shop_id, plan.id, now=now)
    if notice is not None:
        out["notice"] = notice
    return out


async def _add_row(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    chosen_version: int | None,
    actor: manual.Actor,
    now: datetime,
    acknowledge_breaches: bool,
) -> tuple[
    ShopRecoPlan,
    ShopRecoPlanCard,
    ShopProposal,
    dict[str, Any],
    list[dict[str, Any]],
    list[tuple[ShopRecoPlanCard, ShopProposal, dict[str, Any]]],
]:
    """Put the card in the draft plan as a ``planned`` row. The last item lists the cards of the
    plan that write one of the same exclusive fields."""
    p, payload = await service._proposal(session, shop_id, card_id)
    if p.status not in ADDABLE:
        raise ProposalError(ERROR_CARD_STATE, 409, f"a {p.status} card cannot be added to a plan")
    existing = await draft_of(session, shop_id)
    restored = None
    if existing is not None:
        restored = await session.scalar(
            select(ShopRecoPlanCard)
            .where(
                ShopRecoPlanCard.plan_id == existing.id,
                ShopRecoPlanCard.proposal_id == p.id,
                ShopRecoPlanCard.removed_at.is_not(None),
            )
            .order_by(ShopRecoPlanCard.removed_at.desc(), ShopRecoPlanCard.added_at.desc())
            .limit(1)
        )
    restored_inputs: dict[str, Any] = {}
    if chosen_version is None:
        chosen_version = int(restored.chosen_version) if restored is not None else 1
        restored_inputs = dict(restored.inputs or {}) if restored is not None else {}
    elif restored is not None and int(restored.chosen_version) == chosen_version:
        restored_inputs = dict(restored.inputs or {})
    vlist = versions.versions_of({**payload, "code": p.code})
    if not 1 <= chosen_version <= len(vlist):
        raise ProposalError("reco_version_unknown", 422, f"the card has {len(vlist)} version(s)")
    if vlist[chosen_version - 1].get("status") == versions.STATUS_REFUSED:
        raise ProposalError("reco_version_unavailable", 422, "this version cannot be evaluated")
    plan = await _ensure_draft(session, shop_id, actor, now)
    current = await _rows(session, shop_id, plan.id)
    if len(current) >= config.PLAN_MAX_CARDS:
        raise ProposalError("reco_plan_full", 409, f"a plan holds at most {config.PLAN_MAX_CARDS}")
    others = await _same_field(session, shop_id, current, p, payload)
    env = await _env_for(session, shop_id, plan, now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    entry = Entry(
        str(p.id), p.code, {**payload, "code": p.code}, chosen_version, dict(restored_inputs)
    )
    ev = evaluate_entry(env, entry, now=now)
    if ev is None:
        raise ProposalError(service.ERROR_BAD_INPUT, 422, "this version cannot be evaluated")
    breaches = manual.breaches_of(ev.card)
    if breaches and not acknowledge_breaches:
        raise PlanBreachNotAcknowledged(breaches, "this card")
    acknowledged = {"by": actor.json(), "at": now.isoformat(), "breaches": breaches}
    new_row = ShopRecoPlanCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        plan_id=plan.id,
        proposal_id=p.id,
        chosen_version=chosen_version,
        inputs=restored_inputs,
        prior_status=p.status,
        position=len(current) + 1,
        added_by=actor.json(),
        acknowledged_breaches=acknowledged if breaches else None,
        added_at=now,
    )
    session.add(new_row)
    await _place_at_slot(session, shop_id, current, new_row, p, payload)
    p.status = STATUS_PLANNED
    p.lever_plan_id = plan.id
    p.updated_at = now
    if plan.as_of is None:  # the base is pinned when the first card joins (D85.4)
        plan.as_of = env.as_of
        await plan_base.write(session, shop_id, plan.id, env, actor.json(), now)
    plan.updated_at = now
    await store.set_meta(session, shop_id, p.id, {"plan_id": str(plan.id)})
    await session.flush()
    if p.item_id:
        await product_queue.requeue_products(session, shop_id, [p.item_id], now)
    return plan, new_row, p, payload, vlist, others


async def _same_field(
    session: AsyncSession,
    shop_id: uuid.UUID,
    current: list[tuple[ShopRecoPlanCard, ShopProposal]],
    proposal: ShopProposal,
    payload: Mapping[str, Any],
) -> list[tuple[ShopRecoPlanCard, ShopProposal, dict[str, Any]]]:
    """The cards of the plan that write an exclusive field this card writes too (same product or
    campaign)."""
    mine = {(f, s) for f, s, _ in plan_groups.exclusive_keys(payload)}
    if not mine:
        return []
    out: list[tuple[ShopRecoPlanCard, ShopProposal, dict[str, Any]]] = []
    for row, other in current:
        if other.id == proposal.id:
            continue
        theirs_payload = await store.card_payload(session, shop_id, other.id) or {}
        if mine & {(f, s) for f, s, _ in plan_groups.exclusive_keys(theirs_payload)}:
            out.append((row, other, theirs_payload))
    return out


async def _separate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: ShopRecoPlan,
    row: ShopRecoPlanCard,
    proposal: ShopProposal,
    payload: dict[str, Any],
    others: list[tuple[ShopRecoPlanCard, ShopProposal, dict[str, Any]]],
    actor: manual.Actor,
    now: datetime,
) -> dict[str, Any]:
    """P97 D85.14: ``proposal`` writes a field the cards in ``others`` already write. They cannot
    run in one group, so the earlier cards go to a group (A) and this one to the next group; it
    never refuses. Returns the notice shown to the person."""
    by_group = await plan_groups.members_by_group(session, shop_id, plan.id)
    in_group = plan_groups.grouped_card_ids(by_group)
    ungrouped = [
        plan_groups.Placement(r, o, pl, int(r.chosen_version))
        for r, o, pl in others
        if r.id not in in_group
    ]
    if ungrouped:
        await plan_groups.place(session, shop_id, plan, ungrouped, actor=actor.json(), now=now)
    groups = await plan_groups.active_groups(session, shop_id, plan.id)
    by_group = await plan_groups.members_by_group(session, shop_id, plan.id)
    holding = {r.id for r, _, _ in others}
    last = max(
        (
            i
            for i, g in enumerate(groups)
            if any(c.id in holding for _, c, _ in by_group.get(g.id, []))
        ),
        default=0,
    )
    placed = await plan_groups.place(
        session,
        shop_id,
        plan,
        [plan_groups.Placement(row, proposal, payload, int(row.chosen_version))],
        actor=actor.json(),
        now=now,
        after_index=last,
    )
    letter = placed[0].group.letter
    label = ", ".join(sorted({lbl for _, _, lbl in plan_groups.exclusive_keys(payload)}))
    codes_ = ", ".join(sorted({o.code or "" for _, o, _ in others if o.code}))
    return {
        "type": "moved_to_group",
        "group": letter,
        "message": f"Thẻ {proposal.code} cũng đổi {label} của cùng đối tượng với thẻ {codes_}. "
        f"Mỗi lần chỉ giữ một giá trị cho {label}, nên thẻ này chạy ở Nhóm {letter}, "
        "sau nhóm có thẻ kia.",
    }


async def refresh_base(
    session: AsyncSession, shop_id: uuid.UUID, *, actor: manual.Actor, now: datetime
) -> dict[str, Any]:
    """ "Cập nhật số": move the draft plan's base to the newest complete day (the only way the
    base moves); writes the next snapshot version."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    plan.as_of = env.as_of
    plan.updated_at = now
    await plan_base.write(session, shop_id, plan.id, env, actor.json(), now)
    await session.flush()
    return await get_plan(session, shop_id, plan.id, now=now)


async def _place_at_slot(
    session: AsyncSession,
    shop_id: uuid.UUID,
    current: list[tuple[ShopRecoPlanCard, ShopProposal]],
    new_row: ShopRecoPlanCard,
    proposal: ShopProposal,
    payload: Mapping[str, Any],
) -> None:
    """P92 B-10: a new card joins its product's sequence at its canonical step slot (price ->
    giảm giá -> voucher -> combo -> ads); a card of another product, or of no product, goes last.
    Positions are renumbered 1..n."""
    ordered = [row for row, _ in current]
    same = [
        (i, (await store.card_payload(session, shop_id, p.id) or {}).get("change_kind", ""))
        for i, (row, p) in enumerate(current)
        if proposal.item_id and p.item_id == proposal.item_id
    ]
    target = len(ordered)
    if same:
        slot = plan_steps.slot_for([kind for _, kind in same], str(payload.get("change_kind", "")))
        target = same[slot][0] if slot < len(same) else same[-1][0] + 1
    ordered.insert(target, new_row)
    for index, row in enumerate(ordered, start=1):
        row.position = index


async def move_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    position: int,
    *,
    actor: manual.Actor,
    now: datetime,
) -> dict[str, Any]:
    """Reorder: the card takes ``position`` (1-based, clamped) among the plan's cards; the steps
    of its product are re-evaluated in the new order (:mod:`.plan_steps`)."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    rows = await _rows(session, shop_id, plan.id)
    row, _ = await _row_of(session, shop_id, plan.id, card_id)
    ordered = [r for r, _ in rows if r.id != row.id]
    ordered.insert(min(max(position, 1), len(ordered) + 1) - 1, row)
    for index, r in enumerate(ordered, start=1):
        r.position = index
    plan.updated_at = now
    await session.flush()
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
    await plan_groups.drop_members(
        session, shop_id, plan_card_id=row.id, version=None, group_id=None, now=now
    )
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
    env = await _env_for(session, shop_id, plan, now)
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
    list otherwise). Every card becomes ``approved`` with the plan id; a card in a group takes the
    group's start as its planned date and the group's code, the others the plan's one date. One
    approval queues the fill of every approved version (D85.6, D85.14)."""
    today = plan_today(now)
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    rows = await _rows(session, shop_id, plan.id)
    if not rows:
        raise ProposalError(ERROR_EMPTY, 422, "the plan has no card")
    when = planned_date or now.date()
    if when < now.date():
        raise ProposalError(ERROR_DATE, 422, "the planned date is in the past")
    env = await _env_for(session, shop_id, plan, now)
    if env is None:
        raise ProposalError(service.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    base = None  # P99b: live on the newest data, never the frozen snapshot
    group_rows = await plan_groups.active_groups(session, shop_id, plan.id)
    by_group = await plan_groups.members_by_group(session, shop_id, plan.id)
    grouped = plan_groups.grouped_card_ids(by_group)
    plan.planned_date = when
    windows_of = plan_groups.periods(plan, group_rows, today=when)
    agg, evs = await _aggregate(
        session,
        shop_id,
        env,
        await _entries(session, shop_id, [(r, p) for r, p in rows if r.id not in grouped]),
        now=now,
        base=base,
        today=today,
    )
    group_aggs: dict[str, dict[str, Any]] = {}
    group_evs: dict[str, Any] = {}
    unavailable = list(agg.get("unavailable_cards") or [])
    breaches = _all_breaches(agg, evs) if evs else []
    for g in group_rows:
        entries = await plan_groups.entries_of(session, shop_id, by_group.get(g.id, []))
        if not entries:
            continue
        gagg, gev = await _aggregate(
            session, shop_id, env, entries, now=now, base=base, today=today,
            default_start=windows_of[g.id][0],
        )  # fmt: skip
        group_aggs[g.letter] = gagg
        group_evs.update({e.entry.card_id: e for e in gev})
        unavailable += gagg.get("unavailable_cards") or []
        breaches += [{**b, "group": g.letter} for b in _all_breaches(gagg, gev)]
    if unavailable:
        raise ProposalError(
            service.ERROR_BAD_INPUT, 422, f"cards that cannot be evaluated: {unavailable}"
        )
    if breaches and not acknowledge_breaches:
        raise PlanBreachNotAcknowledged(breaches)
    acknowledged = (
        {"by": actor.json(), "at": now.isoformat(), "breaches": breaches} if breaches else None
    )
    names = {
        b["product_id"]: b.get("name")
        for b in [
            *agg.get("products", []),
            *_group_products(group_aggs.values()),
        ]
    }
    cut = await change_sets.cut_preview(session, shop_id, list(names), when, names)
    code = await plan_codes.assign_plan_code(session, shop_id, now)
    by_id = {e.entry.card_id: e for e in evs}
    card_groups: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for g in group_rows:
        mrows = by_group.get(g.id, [])
        if not mrows:
            continue
        first_code = next((p.code for _, _, p in mrows if p.code), None)
        g.code = codes.group_code(first_code, g.letter) if first_code else None
        g.status = GROUP_APPROVED
        g.updated_at = now
        start, end = windows_of[g.id]
        for m, c, p in mrows:
            vcode = p.code and codes.version_code(p.code, int(m.version))
            card_groups.setdefault(c.id, []).append(
                {
                    "name": g.letter,
                    "letter": g.letter,
                    "code": g.code,
                    "versions": [int(m.version)],
                    "version_codes": [vcode],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "days": int(g.days),
                }
            )
    for row, p in rows:
        if row.id in grouped:
            infos = card_groups[row.id]
            first_ev = group_evs[plan_groups.entry_id(p.id, infos[0]["versions"][0])]
            await _approve(
                session, shop_id, plan, code, row, p, first_ev, actor, now,
                date.fromisoformat(infos[0]["start"]), acknowledged, note,
                chosen=infos[0]["versions"][0], groups=infos,
            )  # fmt: skip
        else:
            await _approve(
                session, shop_id, plan, code, row, p, by_id[str(p.id)], actor, now, when,
                acknowledged, note,
            )  # fmt: skip
    plan.status = PLAN_CONFIRMED
    plan.code = code
    plan.as_of = env.as_of
    plan.planned_date = when
    plan.confirmed_at = now
    plan.confirmed_by = actor.json()
    plan.acknowledged_breaches = acknowledged
    plan.cut_measurements = cut
    plan.aggregate = {**agg, "plan_code": code, "groups": group_aggs}
    plan.updated_at = now
    await session.flush()
    await _queue_fills(session, shop_id, rows, card_groups)
    await product_queue.requeue_products(
        session, shop_id, {p.item_id for _, p in rows if p.item_id}, now
    )
    out = await get_plan(session, shop_id, plan.id, now=now)
    out["measurement_cut"] = cut
    return out


async def _queue_fills(
    session: AsyncSession,
    shop_id: uuid.UUID,
    rows: list[tuple[ShopRecoPlanCard, ShopProposal]],
    card_groups: Mapping[uuid.UUID, list[dict[str, Any]]],
) -> None:
    """One approval queues the fill of every version that was approved: one job per version of
    a grouped card (with its group code), one for a card with no group (T3's fill queue; it reads
    the card's ``targets`` for a many-target card)."""
    for row, p in rows:
        infos = card_groups.get(row.id)
        if not infos:
            await fill_queue_port.enqueue_for_approval(
                session,
                shop_id=shop_id,
                proposal_id=p.id,
                version=int(row.chosen_version),
                group_code=None,
            )
            continue
        for info in infos:
            for version in info["versions"]:
                await fill_queue_port.enqueue_for_approval(
                    session,
                    shop_id=shop_id,
                    proposal_id=p.id,
                    version=int(version),
                    group_code=info["code"],
                )


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
    *,
    chosen: int | None = None,
    groups: list[dict[str, Any]] | None = None,
) -> None:
    card = ev.card
    payload = ev.entry.base
    chosen = chosen if chosen is not None else row.chosen_version
    vcode = (card.get("versions") or [{}])[chosen - 1].get("code") or (
        p.code and f"{p.code}-V{chosen}"
    )
    in_app = actor.kind == "seller"
    group = None if not groups else {**groups[0]}
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
        **({"group": group, "groups": groups} if groups else {}),
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
            **({"group": group, "groups": groups} if groups else {}),
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
            "chosen_version": chosen,
            "acknowledged_breaches": acknowledged,
            "plan_id": str(plan.id),
            "plan_code": code,
            "planned_date": when.isoformat(),
            **({"group": group, "groups": groups} if groups else {}),
        },
    )


# ------------------------------------------------------------------------------- groups


async def run_together(
    session: AsyncSession,
    shop_id: uuid.UUID,
    members: Sequence[tuple[uuid.UUID, int]],
    *,
    days: int = plan_groups.DEFAULT_DAYS,
    start: date | None = None,
    actor: manual.Actor,
    now: datetime,
    acknowledge_breaches: bool = False,
    audience: str = "ops",
) -> dict[str, Any]:
    """ "Chạy cùng nhau" (D85.14): these versions (of one card or of several, any kinds) become one
    group with one period. A card not yet in the draft plan joins it (a floor breach needs
    ``acknowledge_breaches``); a version whose exclusive field is already taken in the group moves
    to the next group, never refused. Answers with the plan, ``placed`` (where each version went)
    and a ``notice`` when something moved."""
    now = _naive(now)
    if not members:
        raise ProposalError(ERROR_EMPTY, 422, "choose at least one version to run together")
    plan_groups.check_days(days)
    if start is not None and start < now.date():
        raise ProposalError(plan_groups.ERROR_GROUP_DATE, 422, "Ngày bắt đầu không được ở quá khứ.")
    seen: dict[uuid.UUID, tuple[ShopRecoPlanCard, ShopProposal, dict[str, Any]]] = {}
    placements: list[plan_groups.Placement] = []
    plan: ShopRecoPlan | None = await draft_of(session, shop_id)
    for card_id, version in dict.fromkeys(members):
        if card_id not in seen:
            current = [] if plan is None else await _rows(session, shop_id, plan.id)
            held = next(((r, p) for r, p in current if p.id == card_id), None)
            if held is not None:
                payload = await store.card_payload(session, shop_id, card_id) or {}
                seen[card_id] = (held[0], held[1], payload)
            else:
                plan, row, p, payload, _, _ = await _add_row(
                    session,
                    shop_id,
                    card_id,
                    chosen_version=version,
                    actor=actor,
                    now=now,
                    acknowledge_breaches=acknowledge_breaches,
                )
                seen[card_id] = (row, p, payload)
        row, p, payload = seen[card_id]
        vlist = versions.versions_of({**payload, "code": p.code})
        if not 1 <= version <= len(vlist):
            raise ProposalError(
                "reco_version_unknown", 422, f"the card has {len(vlist)} version(s)"
            )
        if vlist[version - 1].get("status") == versions.STATUS_REFUSED:
            raise ProposalError("reco_version_unavailable", 422, "this version cannot be evaluated")
        placements.append(plan_groups.Placement(row, p, payload, version))
    assert plan is not None
    for item in placements:
        await plan_groups.drop_members(
            session,
            shop_id,
            plan_card_id=item.row.id,
            version=item.version,
            group_id=None,
            now=now,
        )
    placed = await plan_groups.place(
        session, shop_id, plan, placements, actor=actor.json(), now=now, days=days, start=start
    )
    plan.updated_at = now
    await session.flush()
    out = await get_plan(session, shop_id, plan.id, now=now, audience=audience)
    out["placed"] = [
        {
            "card_id": str(x.placement.proposal.id),
            "code": x.placement.proposal.code,
            "version": x.placement.version,
            "group": x.group.letter,
            "moved": x.moved_because is not None,
        }
        for x in placed
    ]
    moved = [x for x in placed if x.moved_because]
    if moved:
        out["notice"] = {
            "type": "moved_to_group",
            "group": moved[0].group.letter,
            "message": "Các phương án cùng đổi "
            + ", ".join(sorted({x.moved_because for x in moved if x.moved_because}))
            + " của cùng một đối tượng không chạy chung một nhóm được (mỗi lần chỉ một giá trị): "
            f"{len(moved)} phương án chuyển sang nhóm sau, chạy lần lượt.",
        }
    return out


async def set_group_period(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    days: int | None,
    start: date | None,
    clear_start: bool = False,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    group = await plan_groups.get_group(session, shop_id, group_id)
    if group.plan_id != plan.id:
        raise ProposalError(plan_groups.ERROR_GROUP, 404, "the group is not in the draft plan")
    await plan_groups.set_period(
        session,
        shop_id,
        group_id,
        days=days,
        start=start,
        clear_start=clear_start,
        today=now.date(),
        now=now,
    )
    plan.updated_at = now
    return await get_plan(session, shop_id, plan.id, now=now, audience=audience)


async def remove_group_member(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group_id: uuid.UUID,
    card_id: uuid.UUID,
    version: int,
    *,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    """Take one version out of a group; the card stays in the plan (ungrouped when it was its last
    membership)."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    group = await plan_groups.get_group(session, shop_id, group_id)
    if group.plan_id != plan.id:
        raise ProposalError(plan_groups.ERROR_GROUP, 404, "the group is not in the draft plan")
    row, _ = await _row_of(session, shop_id, plan.id, card_id)
    n = await plan_groups.drop_members(
        session, shop_id, plan_card_id=row.id, version=version, group_id=group_id, now=now
    )
    if n == 0:
        raise ProposalError(plan_groups.ERROR_GROUP, 404, "the version is not in the group")
    plan.updated_at = now
    return await get_plan(session, shop_id, plan.id, now=now, audience=audience)


async def cancel_group(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    """Drop a group: its cards stay in the plan, ungrouped."""
    now = _naive(now)
    plan = await _require_draft(session, shop_id)
    group = await plan_groups.get_group(session, shop_id, group_id)
    if group.plan_id != plan.id:
        raise ProposalError(plan_groups.ERROR_GROUP, 404, "the group is not in the draft plan")
    await plan_groups.cancel_group(session, shop_id, group_id, now=now)
    plan.updated_at = now
    return await get_plan(session, shop_id, plan.id, now=now, audience=audience)


async def export_workbook(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID | None, *, now: datetime
) -> tuple[str, bytes]:
    """The plan's Excel export: group, versions, period, one row per version. Returns
    ``(file name, .xlsx bytes)``."""
    out = await get_plan(session, shop_id, plan_id, now=now)
    if out["plan"] is None:
        raise ProposalError(ERROR_UNKNOWN_PLAN, 404, "the shop has no draft plan")
    name = f"ke-hoach-{out['plan'].get('code') or 'nhap'}.xlsx"
    return name, plan_groups.export_workbook(out)


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
    "cancel_group",
    "confirm",
    "export_workbook",
    "get_plan",
    "list_plans",
    "on_executed",
    "plan_by_code",
    "refresh_base",
    "remove_card",
    "remove_group_member",
    "run_together",
    "set_group_period",
    "set_window",
    "switch_version",
    "whatif",
]

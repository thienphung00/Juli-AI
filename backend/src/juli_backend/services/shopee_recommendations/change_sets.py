"""Change sets: the unit of measurement when changes run together (P91 D-7, D-8).

A **product change set** is every card of one product executed the same day; a **shop change
set** is every shop-wide card (shop voucher, shop ads budget, ...) executed the same day. A set is
measured against the product's (or the shop's) baseline and compared with the plan's joint
prediction for it (``predicted``, copied from the plan when the set is created).

- **Window.** Chosen per plan (default) and overridable per product before execution and per
  change set after: minimum 3, maximum 90 days, presets 7 / 14 / 28; when nobody chose, the
  shortest preset whose MDE is within 30 % for the product's volume (``plan.window_options``,
  frozen in the plan's aggregate). ``measure.py`` reads the card's ``window_days`` (set from the
  change set) instead of the card's own ``measurement_plan.planned_days``.
- **Executing on a product that is still being measured** is allowed. The running set is cut that
  day: measured for at least ``CUT_MIN_DAYS`` (3) days it keeps its result as "đo được N ngày"
  (lower confidence, never calibrates), fewer: "không kết luận". The confirm of a plan lists the
  products this will happen to (:func:`cut_preview`).
- **Shop-wide cards** are measured at shop level; a product set that overlaps a shop-wide set
  carries ``with_shop_wide`` ("kèm thay đổi toàn shop") and does not calibrate any kind.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import (
    SCOPE_PRODUCT,
    SCOPE_SHOP,
    SET_CUT,
    SET_DONE,
    SET_MEASURING,
    ShopRecoChangeSet,
    ShopRecoPlan,
)
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import config, plan, store

ERROR_WINDOW = "reco_window_invalid"
ERROR_UNKNOWN_SET = "reco_change_set_not_found"
STATE_RUNNING = "running"
STATE_MEASURED = "measured"
STATE_KEPT = "kept_partial"
STATE_INCONCLUSIVE = "inconclusive"
LABEL_INCONCLUSIVE = "Không kết luận"


def kept_label(days: int) -> str:
    return f"Đo được {days} ngày"


def check_days(days: Any) -> int:
    try:
        return plan.check_window(days)
    except ValueError as exc:
        raise ProposalError(ERROR_WINDOW, 422, str(exc)) from None


def _day(when: datetime) -> date:
    return when.date()


def cut_outcome(days_measured: int) -> dict[str, Any]:
    """What a cut measurement keeps: ``>= CUT_MIN_DAYS`` -> "đo được N ngày" (lower confidence),
    fewer -> "không kết luận". Pure."""
    days = max(days_measured, 0)
    if days >= config.CUT_MIN_DAYS:
        return {
            "state": STATE_KEPT,
            "label": kept_label(days),
            "days": days,
            "low_confidence": True,
        }
    return {
        "state": STATE_INCONCLUSIVE,
        "label": LABEL_INCONCLUSIVE,
        "days": days,
        "low_confidence": True,
    }


# ------------------------------------------------------------------------------ the window


def resolve_window(
    plan_row: ShopRecoPlan | None,
    plan_aggregate: dict[str, Any] | None,
    product_id: str | None,
    card: dict[str, Any],
) -> tuple[int, str]:
    """``(days, source)``: the product's override in the plan, the plan's default, the auto
    recommendation frozen in the plan's aggregate, else the card's own measurement plan (a card
    that was not in a plan) or the default window."""
    if plan_row is not None:
        override = (plan_row.product_windows or {}).get(product_id or "")
        if override:
            return int(override), "custom"
        if plan_row.window_days:
            return int(plan_row.window_days), "plan"
        for block in (plan_aggregate or {}).get("products", []):
            if block["product_id"] == product_id:
                return int(block["window"]["default_days"]), "auto"
    planned = (card.get("measurement_plan") or {}).get("planned_days")
    return int(planned or config.QUEUE_DEFAULT_PLAN_DAYS), "auto"


def predicted_for(
    plan_row: ShopRecoPlan | None, plan_aggregate: dict[str, Any] | None, product_id: str | None
) -> dict[str, Any]:
    """The plan's joint prediction for this product (or its shop-wide cards), copied onto a set."""
    if plan_row is None or not plan_aggregate:
        return {}
    base = {"plan_id": str(plan_row.id), "plan_code": plan_row.code}
    if product_id is None:
        block = plan_aggregate.get("shop_wide")
        return {**base, "joint": block["joint"], "cards": block["cards"]} if block else base
    for block in plan_aggregate.get("products", []):
        if block["product_id"] == product_id:
            return {
                **base,
                "joint": block["joint"],
                "rel_gmv": block["predicted_rel_gmv"],
                "base_gmv_30d": block["base_gmv_30d"],
                "cards": block["cards"],
            }
    return base


# ------------------------------------------------------------------------------- storage


async def sets_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    status: Sequence[str] | None = None,
    product_id: str | None = None,
    scope: str | None = None,
    plan_id: uuid.UUID | None = None,
) -> list[ShopRecoChangeSet]:
    stmt = select(ShopRecoChangeSet).where(ShopRecoChangeSet.shop_id == shop_id)
    if status:
        stmt = stmt.where(ShopRecoChangeSet.status.in_(list(status)))
    if product_id is not None:
        stmt = stmt.where(ShopRecoChangeSet.product_id == product_id)
    if scope is not None:
        stmt = stmt.where(ShopRecoChangeSet.scope == scope)
    if plan_id is not None:
        stmt = stmt.where(ShopRecoChangeSet.plan_id == plan_id)
    return list(
        await session.scalars(stmt.order_by(ShopRecoChangeSet.started_at, ShopRecoChangeSet.id))
    )


async def get(session: AsyncSession, shop_id: uuid.UUID, set_id: uuid.UUID) -> ShopRecoChangeSet:
    row = await session.scalar(
        select(ShopRecoChangeSet).where(
            ShopRecoChangeSet.id == set_id, ShopRecoChangeSet.shop_id == shop_id
        )
    )
    if row is None:
        raise ProposalError(ERROR_UNKNOWN_SET, 404)
    return row


def to_json(cs: ShopRecoChangeSet, *, now: datetime | None = None) -> dict[str, Any]:
    end = cs.started_at + timedelta(days=cs.window_days)
    left = None
    if cs.status == SET_MEASURING and now is not None:
        left = max((end.date() - now.date()).days, 0)
    return {
        "id": str(cs.id),
        "scope": cs.scope,
        "product_id": cs.product_id,
        "plan_id": None if cs.plan_id is None else str(cs.plan_id),
        "executed_on": cs.executed_on.isoformat(),
        "started_at": cs.started_at.isoformat(),
        "card_ids": list(cs.card_ids or []),
        "n_cards": len(cs.card_ids or []),
        "window_days": cs.window_days,
        "window_source": cs.window_source,
        "until": end.date().isoformat(),
        "days_left": left,
        "status": cs.status,
        "with_shop_wide": cs.with_shop_wide,
        "with_shop_wide_label": "Kèm thay đổi toàn shop" if cs.with_shop_wide else None,
        "predicted": cs.predicted,
        "result": cs.result,
        "cut_at": None if cs.cut_at is None else cs.cut_at.isoformat(),
        "cut_days": cs.cut_days,
    }


async def _member_meta(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: Iterable[str], patch: dict[str, Any]
) -> None:
    for cid in card_ids:
        await store.set_meta(session, shop_id, uuid.UUID(str(cid)), patch)


# ------------------------------------------------------------------------------ cutting


async def cut(
    session: AsyncSession, cs: ShopRecoChangeSet, *, at: datetime, by: str | None = None
) -> dict[str, Any]:
    """End a running measurement on ``at``: the days measured so far decide whether the result is
    kept ("đo được N ngày") or "không kết luận". The member cards stop holding the product."""
    days = max((at.date() - cs.started_at.date()).days, 0)
    outcome = cut_outcome(days)
    cs.status = SET_CUT
    cs.cut_at = at
    cs.cut_days = days
    cs.result = {**outcome, "cut_by_change_set": by, "cut_on": at.date().isoformat()}
    cs.updated_at = at
    await _member_meta(session, cs.shop_id, cs.card_ids or [], {"measure_cut_at": at.isoformat()})
    await session.flush()
    return outcome


async def cut_preview(
    session: AsyncSession,
    shop_id: uuid.UUID,
    products: Iterable[str],
    on: date,
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The running measurements an execution on ``on`` would cut, per product (the confirm
    dialog lists them): the days measured so far and what is kept."""
    wanted = sorted({p for p in products if p})
    if not wanted:
        return []
    out: list[dict[str, Any]] = []
    for cs in await sets_for(session, shop_id, status=[SET_MEASURING], scope=SCOPE_PRODUCT):
        if cs.product_id not in wanted or cs.executed_on >= on:
            continue
        days = (on - cs.started_at.date()).days
        out.append(
            {
                "product_id": cs.product_id,
                "name": (names or {}).get(str(cs.product_id)),
                "change_set": str(cs.id),
                "started_on": cs.started_at.date().isoformat(),
                "days_measured": days,
                "window_days": cs.window_days,
                **cut_outcome(days),
            }
        )
    return out


# ---------------------------------------------------------------------------- attaching


async def _shop_wide_flag(
    session: AsyncSession, shop_id: uuid.UUID, product_on: date, exclude: uuid.UUID | None = None
) -> bool:
    """A product set executed on ``product_on`` is "kèm thay đổi toàn shop" when a shop-wide set
    is inside its window then (started on or before that day, not ended)."""
    for cs in await sets_for(session, shop_id, scope=SCOPE_SHOP):
        if (
            cs.id == exclude
            or cs.status == SET_CUT
            and (cs.cut_at or cs.started_at).date() < product_on
        ):
            continue
        if cs.executed_on <= product_on <= cs.executed_on + timedelta(days=cs.window_days):
            return True
    return False


async def attach_execution(
    session: AsyncSession,
    shop_id: uuid.UUID,
    proposal: ShopProposal,
    card: dict[str, Any],
    *,
    executed_at: datetime,
    now: datetime,
) -> ShopRecoChangeSet:
    """A card was executed: put it in the change set of its product (or the shop) for that day,
    creating the set (and cutting the product's running measurement) when it is the first."""
    product = proposal.item_id if proposal.subject_type == "item" else None
    scope = SCOPE_PRODUCT if product else SCOPE_SHOP
    day = _day(executed_at)
    plan_row = None
    aggregate = None
    if proposal.lever_plan_id is not None:
        plan_row = await session.get(ShopRecoPlan, proposal.lever_plan_id)
        aggregate = None if plan_row is None else plan_row.aggregate
    existing = [
        cs
        for cs in await sets_for(session, shop_id, product_id=product, scope=scope)
        if cs.executed_on == day and cs.status == SET_MEASURING
    ]
    cid = str(proposal.id)
    if existing:
        cs = existing[0]
        if cid not in (cs.card_ids or []):
            cs.card_ids = [*(cs.card_ids or []), cid]
            cs.updated_at = now
    else:
        days, source = resolve_window(plan_row, aggregate, product, card)
        cs = ShopRecoChangeSet(
            id=uuid.uuid4(),
            shop_id=shop_id,
            plan_id=proposal.lever_plan_id,
            scope=scope,
            product_id=product,
            executed_on=day,
            started_at=executed_at,
            card_ids=[cid],
            window_days=days,
            window_source=source,
            status=SET_MEASURING,
            with_shop_wide=False,
            predicted=predicted_for(plan_row, aggregate, product),
            created_at=now,
            updated_at=now,
        )
        session.add(cs)
        await session.flush()
        for running in await sets_for(
            session, shop_id, status=[SET_MEASURING], product_id=product, scope=scope
        ):
            if running.id != cs.id and running.executed_on < day:
                await cut(session, running, at=executed_at, by=str(cs.id))
        if scope == SCOPE_PRODUCT:
            cs.with_shop_wide = await _shop_wide_flag(session, shop_id, day)
        else:  # product sets started inside this shop-wide set's window now carry the flag
            for other in await sets_for(session, shop_id, scope=SCOPE_PRODUCT):
                if day <= other.executed_on <= day + timedelta(days=cs.window_days):
                    other.with_shop_wide = True
    await _member_meta(
        session,
        shop_id,
        [cid],
        {"change_set": str(cs.id), "window_days": cs.window_days, "plan_days": cs.window_days},
    )
    await session.flush()
    return cs


async def set_window(
    session: AsyncSession, shop_id: uuid.UUID, set_id: uuid.UUID, days: int, *, now: datetime
) -> ShopRecoChangeSet:
    """Override the window of one running change set (3..90 days)."""
    n = check_days(days)
    cs = await get(session, shop_id, set_id)
    if cs.status != SET_MEASURING:
        raise ProposalError(
            "reco_change_set_closed", 409, f"a {cs.status} change set has no window"
        )
    cs.window_days = n
    cs.window_source = "custom"
    cs.updated_at = now
    await _member_meta(session, shop_id, cs.card_ids or [], {"window_days": n, "plan_days": n})
    await session.flush()
    return cs


__all__ = [
    "SET_CUT",
    "SET_DONE",
    "SET_MEASURING",
    "attach_execution",
    "check_days",
    "cut",
    "cut_outcome",
    "cut_preview",
    "kept_label",
    "resolve_window",
    "set_window",
    "sets_for",
    "to_json",
]

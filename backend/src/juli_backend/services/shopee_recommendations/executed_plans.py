"""Executed Kế hoạch built after the fact (owner decision 2026-11-16, "Option B": the Kế hoạch is
the single source of the client report).

Two callers put a card that never went through a draft plan into an already ``executed`` plan,
the way a normal executed plan holds its cards (``shop_reco_plan_cards`` rows, the card's
``lever_plan_id``, its change set's ``plan_id``, a frozen ``aggregate`` with one evaluation block
per card), so ``plans.get_plan``, the month plan view and the Kế hoạch export read it unchanged:

- the outside-Juli import ("Nhập thẻ đã làm ngoài Juli"): ONE plan per imported file, each card
  at its own past start date and run days (``allow_past=True``, ``origin == "external"`` only);
- a card executed from Thực hiện without a plan (``service.mark_executed(auto_plan=True)``): it
  joins the plan of the month it was executed in.

A past date is refused here exactly as ``plans.confirm`` refuses it, unless the caller passes
``allow_past`` AND the card's origin is ``external``: the general planning check is untouched.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import PLAN_EXECUTED, ShopRecoPlan, ShopRecoPlanCard
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import (
    manual,
    plan_codes,
    plans,
    result_store,
    store,
)

ORIGIN_EXTERNAL = "external"
KEY_EXTERNAL = "external_import"
KEY_MONTH = "month"
_METRICS = (("dgmv", "dgmv"), ("dprofit", "dprofit"), ("dorders", "dorders"))


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


async def _find(session: AsyncSession, shop_id: uuid.UUID, key: str) -> ShopRecoPlan | None:
    rows = await session.scalars(
        select(ShopRecoPlan).where(
            ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.status == PLAN_EXECUTED
        )
    )
    for plan in rows:
        if (plan.aggregate or {}).get("plan_key") == key:
            return plan
    return None


async def attach_executed(
    session: AsyncSession,
    shop_id: uuid.UUID,
    p: ShopProposal,
    *,
    key: str,
    on: date,
    actor: manual.Actor,
    now: datetime,
    allow_past: bool = False,
) -> ShopRecoPlan:
    """Put card ``p`` (executed on ``on``) in the executed plan ``key``, creating it on first use.
    Idempotent: a card already in a plan is left there. Call before the card's approval so its
    change set takes the plan id; call :func:`refresh` after it is executed."""
    now = _naive(now)
    if on < now.date():
        payload = await store.card_payload(session, shop_id, p.id) or {}
        if not (allow_past and payload.get("origin") == ORIGIN_EXTERNAL):
            raise ProposalError(plans.ERROR_DATE, 422, "the planned date is in the past")
    if p.lever_plan_id is not None:
        return await plans.get_plan_row(session, shop_id, p.lever_plan_id)
    at = datetime.combine(on, time.min)
    plan = await _find(session, shop_id, key)
    if plan is None:
        plan = ShopRecoPlan(
            id=uuid.uuid4(),
            shop_id=shop_id,
            status=PLAN_EXECUTED,
            code=await plan_codes.assign_plan_code(session, shop_id, now),
            product_windows={},
            planned_date=on,
            created_by=actor.json(),
            confirmed_by=actor.json(),
            confirmed_at=at,
            executed_at=at,
            aggregate={"plan_key": key, "cards": [], "n_cards": 0},
            created_at=now,
            updated_at=now,
        )
        session.add(plan)
        await session.flush()
    n = len(await plans._rows(session, shop_id, plan.id))
    session.add(
        ShopRecoPlanCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            plan_id=plan.id,
            proposal_id=p.id,
            chosen_version=1,
            inputs={},
            prior_status=p.status,
            position=n + 1,
            added_by=actor.json(),
            added_at=at,
        )
    )
    p.lever_plan_id = plan.id
    await store.set_meta(
        session,
        shop_id,
        p.id,
        {"plan_id": str(plan.id), "plan_code": plan.code, "planned_date": on.isoformat()},
    )
    await session.flush()
    return plan


def _start_of(meta: dict[str, Any], p: ShopProposal) -> date | None:
    ext = meta.get("external") or {}
    raw = meta.get("executed_at") or ext.get("started_on")
    if raw:
        return date.fromisoformat(str(raw)[:10])
    return p.planned_start


async def refresh(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID, *, now: datetime
) -> None:
    """Re-freeze the plan's aggregate from its cards: one evaluation block each (the Dự kiến
    frozen at approval, on the card's real start date and run days), the plan's date and name."""
    plan = await plans.get_plan_row(session, shop_id, plan_id)
    blocks: list[dict[str, Any]] = []
    starts: list[date] = []
    ends: list[date] = []
    for row, p in await plans._rows(session, shop_id, plan.id):
        meta = await store.card_meta(session, shop_id, p.id)
        payload = await store.card_payload(session, shop_id, p.id) or {}
        frozen = meta.get(result_store.AT_APPROVAL) or result_store.version_result(payload, 1)
        start = _start_of(meta, p)
        summary = result_store.summary(frozen)
        run = int((meta.get("external") or {}).get("run_days") or 0)
        days = int(summary.get("effect_days") or run or 1)
        own = None
        if start is not None:
            end = start + timedelta(days=days - 1)
            est = bool(summary["estimable"])
            own = {
                "dates": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
                "days": days,
                "delta": {
                    q: {m: summary[src][q] for m, src in _METRICS} for q in ("p10", "p50", "p90")
                }
                if est
                else None,
                "cost_total": (frozen or {}).get("cost_total"),
            }
        if start is not None:
            starts.append(start)
            ends.append(start + timedelta(days=max(days, run, 1) - 1))
        blocks.append(
            {
                "card_id": str(p.id),
                "code": p.code,
                "title": payload.get("title"),
                "family": payload.get("family"),
                "change_kind": payload.get("change_kind"),
                "product_id": p.item_id,
                "version": row.chosen_version,
                "result": {"estimable": bool(summary["estimable"]), "own": own},
            }
        )
    key = str((plan.aggregate or {}).get("plan_key") or "")
    name: str | None
    first, last = (min(starts), max(ends)) if starts else (None, None)
    if key.startswith(KEY_EXTERNAL) and first and last:
        name = f"Đã làm ngoài Juli {first:%d/%m}–{last:%d/%m}"
    elif first:
        name = f"Thẻ làm trực tiếp {first:%m/%Y}"
    else:
        name = str((plan.aggregate or {}).get("name") or "") or None
    plan.aggregate = {
        "plan_key": key,
        "name": name,
        "plan_code": plan.code,
        "n_cards": len(blocks),
        "cards": blocks,
        "products": [],
    }
    if first:
        plan.planned_date = first
    plan.updated_at = _naive(now)
    await session.flush()


__all__ = ["KEY_EXTERNAL", "KEY_MONTH", "ORIGIN_EXTERNAL", "attach_executed", "refresh"]

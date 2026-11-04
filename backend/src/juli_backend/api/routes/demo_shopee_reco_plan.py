"""Seller scope: the draft plan "Kế hoạch", its aggregate, the measurement window and the change
sets (P91 D-6, D-7, D-8), under ``/v1/demo/shopee/recommendations``.

- ``GET  /plan`` -- the shop's draft plan with its cards and the JOINT aggregate (today -> after,
  chi phí vs trần, floor breaches, per-card contribution and "bỏ thẻ này thì", windows).
- ``GET  /plan/aggregate`` -- the aggregate alone. ``GET /plans`` | ``/plans/{id}`` |
  ``/plans/code/{KH-...}`` -- plans of the shop (confirmed ones return the aggregate they were
  confirmed with).
- ``POST /plan/cards`` (add a card + version) | ``/plan/cards/{id}/remove`` | ``/version`` |
  ``/whatif`` -- each answers with the re-aggregated plan.
- ``POST /plan/confirm`` -- never blocked; a breach needs ``acknowledge_breaches``.
- ``POST /plan/window`` -- the plan's default window (3..90 days) or one product's.
- ``GET  /change-sets`` | ``POST /change-sets/{id}/window`` -- the unit of measurement.

Registered before the card routes: ``/plan`` must not be read as a ``{card_id}``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.api.routes.shopee_reco_plan_common import (
    AddCardBody,
    ChangeSetStatus,
    ConfirmBody,
    PlanWhatIfBody,
    SetWindowBody,
    SwitchVersionBody,
    WindowBody,
    breach_refusal,
)
from juli_backend.api.routes.shopee_recommendations_common import refused
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import change_sets, manual, plans

router = APIRouter(prefix="/demo/shopee/recommendations", tags=["demo-shopee"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/plan")
async def get_plan(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    try:
        return await plans.get_plan(session, _shopee(shop), now=_now(), audience="seller")
    except ProposalError as exc:
        raise refused(exc) from None


@router.get("/plan/aggregate")
async def get_aggregate(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    try:
        out = await plans.get_plan(session, _shopee(shop), now=_now(), audience="seller")
    except ProposalError as exc:
        raise refused(exc) from None
    return {"plan": out["plan"], "aggregate": out["aggregate"], "windows": out["windows"]}


@router.get("/plans")
async def list_plans(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return {"plans": await plans.list_plans(session, _shopee(shop))}


@router.get("/plans/code/{code}")
async def plan_by_code(
    code: str,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await plans.plan_by_code(session, _shopee(shop), code, now=_now(), audience="seller")
    except ProposalError as exc:
        raise refused(exc) from None


@router.get("/plans/{plan_id}")
async def get_plan_by_id(
    plan_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await plans.get_plan(session, _shopee(shop), plan_id, now=_now(), audience="seller")
    except ProposalError as exc:
        raise refused(exc) from None


async def _write(session: AsyncSession, call: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        out: dict[str, Any] = await call(session, *args, **kwargs)
        await session.commit()
    except plans.PlanBreachNotAcknowledged as exc:
        await session.rollback()
        raise breach_refusal(exc) from None
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out


@router.post("/plan/cards", status_code=201)
async def add_card(
    body: AddCardBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.add_card,
        _shopee(shop),
        body.card_id,
        chosen_version=body.chosen_version,
        actor=manual.Actor("seller", user.id),
        now=_now(),
        acknowledge_breaches=body.acknowledge_breaches,
    )


@router.post("/plan/cards/{card_id}/remove")
async def remove_card(
    card_id: uuid.UUID,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.remove_card,
        _shopee(shop),
        card_id,
        actor=manual.Actor("seller", user.id),
        now=_now(),
    )


@router.post("/plan/cards/{card_id}/version")
async def switch_version(
    card_id: uuid.UUID,
    body: SwitchVersionBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.switch_version,
        _shopee(shop),
        card_id,
        body.version,
        actor=manual.Actor("seller", user.id),
        now=_now(),
    )


@router.post("/plan/cards/{card_id}/whatif")
async def plan_whatif(
    card_id: uuid.UUID,
    body: PlanWhatIfBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.whatif,
        _shopee(shop),
        card_id,
        body.inputs,
        actor=manual.Actor("seller", user.id),
        now=_now(),
    )


@router.post("/plan/confirm")
async def confirm_plan(
    body: ConfirmBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.confirm,
        _shopee(shop),
        actor=manual.Actor("seller", user.id),
        now=_now(),
        acknowledge_breaches=body.acknowledge_breaches,
        planned_date=body.planned_date,
        note=body.note,
    )


@router.post("/plan/window")
async def plan_window(
    body: WindowBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session,
        plans.set_window,
        _shopee(shop),
        days=body.days,
        product_id=body.product_id,
        now=_now(),
    )


@router.get("/change-sets")
async def list_change_sets(
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    status: ChangeSetStatus = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    now = _now()
    rows = await change_sets.sets_for(
        session, _shopee(shop), status=None if status is None else [status], product_id=product_id
    )
    return {"change_sets": [change_sets.to_json(r, now=now) for r in rows]}


@router.post("/change-sets/{set_id}/window")
async def change_set_window(
    set_id: uuid.UUID,
    body: SetWindowBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    now = _now()
    try:
        cs = await change_sets.set_window(session, _shopee(shop), set_id, body.days, now=now)
        out = change_sets.to_json(cs, now=now)
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out

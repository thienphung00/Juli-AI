"""Juli Ops: the draft plan "Kế hoạch", its aggregate, the measurement window and the change sets
of one shop (P91 D-6, D-7, D-8). Same mount, auth and PII-masking route class as
``ops_shopee_recommendations``; reads are Xem+, writes Vận hành and audited in ``ops_audit_log``.

- ``GET  /shops/{id}/shopee/recommendations/plan`` | ``/plan/aggregate`` | ``/plans`` |
  ``/plans/{plan_id}`` | ``/plans/code/{code}`` | ``/change-sets``
- ``POST .../plan/cards`` | ``/plan/cards/{card_id}/remove`` | ``/version`` | ``/whatif``
- ``POST .../plan/confirm`` (``acknowledge_breaches``) | ``/plan/window`` |
  ``/change-sets/{id}/window``

Registered before the card routes so ``/plan`` is not read as a ``{card_id}``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_reco_plan_common import (
    AddCardBody,
    ChangeSetStatus,
    ConfirmBody,
    MoveCardBody,
    PlanWhatIfBody,
    SetWindowBody,
    SwitchVersionBody,
    WindowBody,
    breach_refusal,
)
from juli_backend.api.routes.shopee_recommendations_common import refused
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops import audit
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import change_sets, manual, plans

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee/recommendations"

ACTION_ADD = "reco_plan_add_card"
ACTION_REMOVE = "reco_plan_remove_card"
ACTION_VERSION = "reco_plan_switch_version"
ACTION_MOVE = "reco_plan_move_card"
ACTION_WHATIF = "reco_plan_whatif"
ACTION_CONFIRM = "reco_plan_confirm"
ACTION_REFRESH = "reco_plan_refresh_base"
ACTION_WINDOW = "reco_plan_window"
ACTION_SET_WINDOW = "reco_change_set_window"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _actor(ctx: OpsContext) -> manual.Actor:
    return manual.Actor("staff", ctx.staff.id, staff_id=ctx.staff.id)


async def _read(
    session: AsyncSession, shop_id: uuid.UUID, call: Any, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            body: dict[str, Any] = await call(session, shop_id, *args, **kwargs)
    except ProposalError as exc:
        raise refused(exc) from None
    return body


async def _write(
    session: AsyncSession,
    ctx: OpsContext,
    shop_id: uuid.UUID,
    action: str,
    after: dict[str, Any],
    call: Any,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            out: dict[str, Any] = await call(session, shop_id, *args, **kwargs)
        await audit.record(session, ctx.staff.actor, action, shop_id=shop_id, after=after)
        await session.commit()
    except plans.PlanBreachNotAcknowledged as exc:
        await session.rollback()
        raise breach_refusal(exc) from None
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out


@router.get(BASE + "/plan")
async def ops_get_plan(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _read(session, shop_id, plans.get_plan, now=_now(), audience="ops")


@router.get(BASE + "/plan/aggregate")
async def ops_get_aggregate(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    out = await _read(session, shop_id, plans.get_plan, now=_now(), audience="ops")
    return {"plan": out["plan"], "aggregate": out["aggregate"], "windows": out["windows"]}


@router.get(BASE + "/plans")
async def ops_list_plans(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def call(s: AsyncSession, sid: uuid.UUID) -> dict[str, Any]:
        return {"plans": await plans.list_plans(s, sid)}

    return await _read(session, shop_id, call)


@router.get(BASE + "/plans/code/{code}")
async def ops_plan_by_code(
    shop_id: uuid.UUID,
    code: str,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _read(session, shop_id, plans.plan_by_code, code, now=_now(), audience="ops")


@router.get(BASE + "/plans/{plan_id}")
async def ops_get_plan_by_id(
    shop_id: uuid.UUID,
    plan_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _read(session, shop_id, plans.get_plan, plan_id, now=_now(), audience="ops")


@router.get(BASE + "/change-sets")
async def ops_list_change_sets(
    shop_id: uuid.UUID,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    status: ChangeSetStatus = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    now = _now()

    async def call(s: AsyncSession, sid: uuid.UUID) -> dict[str, Any]:
        rows = await change_sets.sets_for(
            s, sid, status=None if status is None else [status], product_id=product_id
        )
        return {"change_sets": [change_sets.to_json(r, now=now) for r in rows]}

    return await _read(session, shop_id, call)


@router.post(BASE + "/plan/cards", status_code=201)
async def ops_add_card(
    shop_id: uuid.UUID,
    body: AddCardBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_ADD,
        {"card_id": str(body.card_id), "chosen_version": body.chosen_version},
        plans.add_card, body.card_id,
        chosen_version=body.chosen_version, actor=_actor(ctx), now=_now(),
        acknowledge_breaches=body.acknowledge_breaches,
    )  # fmt: skip


@router.post(BASE + "/plan/cards/{card_id}/move")
async def ops_move_card(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    body: MoveCardBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_MOVE,
        {"card_id": str(card_id), "position": body.position},
        plans.move_card, card_id, body.position, actor=_actor(ctx), now=_now(),
    )  # fmt: skip


@router.post(BASE + "/plan/refresh-base")
async def ops_refresh_base(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_REFRESH, {},
        plans.refresh_base, actor=_actor(ctx), now=_now(),
    )  # fmt: skip


@router.post(BASE + "/plan/cards/{card_id}/remove")
async def ops_remove_card(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_REMOVE, {"card_id": str(card_id)},
        plans.remove_card, card_id, actor=_actor(ctx), now=_now(),
    )  # fmt: skip


@router.post(BASE + "/plan/cards/{card_id}/version")
async def ops_switch_version(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    body: SwitchVersionBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_VERSION,
        {"card_id": str(card_id), "version": body.version},
        plans.switch_version, card_id, body.version, actor=_actor(ctx), now=_now(),
    )  # fmt: skip


@router.post(BASE + "/plan/cards/{card_id}/whatif")
async def ops_plan_whatif(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    body: PlanWhatIfBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_WHATIF,
        {"card_id": str(card_id), "keys": sorted(body.inputs)},
        plans.whatif, card_id, body.inputs, actor=_actor(ctx), now=_now(),
    )  # fmt: skip


@router.post(BASE + "/plan/confirm")
async def ops_confirm_plan(
    shop_id: uuid.UUID,
    body: ConfirmBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_CONFIRM,
        {
            "acknowledge_breaches": body.acknowledge_breaches,
            "planned_date": None if body.planned_date is None else body.planned_date.isoformat(),
        },
        plans.confirm, actor=_actor(ctx), now=_now(),
        acknowledge_breaches=body.acknowledge_breaches, planned_date=body.planned_date,
        note=body.note,
    )  # fmt: skip


@router.post(BASE + "/plan/window")
async def ops_plan_window(
    shop_id: uuid.UUID,
    body: WindowBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _write(
        session, ctx, shop_id, ACTION_WINDOW,
        {"days": body.days, "product_id": body.product_id},
        plans.set_window, days=body.days, product_id=body.product_id, now=_now(),
    )  # fmt: skip


@router.post(BASE + "/change-sets/{set_id}/window")
async def ops_change_set_window(
    shop_id: uuid.UUID,
    set_id: uuid.UUID,
    body: SetWindowBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    now = _now()

    async def call(s: AsyncSession, sid: uuid.UUID) -> dict[str, Any]:
        return change_sets.to_json(
            await change_sets.set_window(s, sid, set_id, body.days, now=now), now=now
        )

    return await _write(
        session, ctx, shop_id, ACTION_SET_WINDOW, {"set_id": str(set_id), "days": body.days}, call
    )

"""Juli Ops: Thực hiện and Đo lường of one shop (viewer role, read-only), the sibling of
``demo_shopee_reco_execution`` under ``/v1/ops/shops/{shop_id}/shopee/recommendations``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_recommendations_common import refused
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops import audit
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import connector_state, execution_state

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee/recommendations"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get(BASE + "/execution")
async def ops_execution(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await execution_state.execution_states(session, shop_id, now=_now())


@router.get(BASE + "/measurements")
async def ops_measurements(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await execution_state.measurement_states(session, shop_id, now=_now())


@router.post(BASE + "/execution/reconcile")
async def ops_reconcile(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            out = await connector_state.request_reconcile(session, shop_id, now=_now())
        await audit.record(session, ctx.staff.actor, "reco_reconcile", shop_id=shop_id, after=out)
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out

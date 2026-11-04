"""Juli Ops: manual offers and the comparison of variants for one shop (p91 D-3).

Same mount, auth and PII-masking route class as ``ops_shopee_recommendations``:

- ``POST /shops/{id}/shopee/recommendations/compare`` (Xem+) -- 2-4 variants side by side with
  the deltas between them and against today; records nothing.
- ``POST /shops/{id}/shopee/recommendations/manual`` (Vận hành) -- saves the chosen variant as
  a card with ``origin = "manual"`` (a draft Ops publishes), the other variants as its
  versions; audited in ``ops_audit_log``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_reco_manual_common import CompareBody, ManualBody
from juli_backend.api.routes.shopee_recommendations_common import refused
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops import audit
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import manual
from juli_backend.services.shopee_recommendations.loader import load_env

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee/recommendations"
ACTION_MANUAL = "reco_manual_create"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.post(BASE + "/compare")
async def ops_compare(
    shop_id: uuid.UUID,
    body: CompareBody,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    now = _now()
    try:
        async with with_shop_scope(session, shop_id):
            env = await load_env(session, shop_id, as_of=body.as_of, now=now)
            if env is None:
                raise ProposalError(manual.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
            return manual.compare(env, [v.as_dict() for v in body.variants], now=now)
    except ProposalError as exc:
        raise refused(exc) from None


@router.post(BASE + "/manual", status_code=201)
async def ops_create_manual(
    shop_id: uuid.UUID,
    body: ManualBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            out = await manual.create_manual(
                session,
                shop_id,
                [v.as_dict() for v in body.variants],
                body.chosen,
                body.primary,
                manual.Actor("staff", ctx.staff.id, staff_id=ctx.staff.id),
                now=_now(),
                as_of=body.as_of,
            )
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_MANUAL,
            shop_id=shop_id,
            after={
                "card_id": out["id"],
                "change_kind": out["card"]["change_kind"],
                "versions": len(out["versions"]),
                "primary": body.primary,
            },
        )
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out

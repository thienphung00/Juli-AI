"""Juli Ops: Cài đặt shop › Đề xuất kế hoạch (P91 D-13), the mirror of
``demo_planned_changes.py`` for the Juli team importing a shop's planned listing changes on its
behalf. Reads are Xem+, preview / apply are Vận hành, and every apply lands in ``ops_audit_log``
in the same transaction as the cards (counts and the file hash, never the values). The shop's
decision is recorded as an approval "document" with the import as its evidence reference.

- ``GET  /v1/ops/shops/{id}/planned-changes``            columns, kinds, reasons
- ``GET  /v1/ops/shops/{id}/planned-changes/template``   the empty .xlsx
- ``POST /v1/ops/shops/{id}/planned-changes/preview``    checks, no write
- ``POST /v1/ops/shops/{id}/planned-changes/apply``      cards + version, audited
- ``GET  /v1/ops/shops/{id}/planned-changes/versions``   applied files
- ``GET  /v1/ops/shops/{id}/planned-changes/versions/{number}``
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import planned_changes_common as common
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import planned_changes as pc
from juli_backend.services.ops import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/planned-changes"
ACTION_APPLY = "planned_changes_apply"


@router.get(BASE)
async def ops_overview(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    return common.overview()


@router.get(BASE + "/template")
async def ops_template(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _shopee_shop(session, shop_id)
    return common.template_response()


@router.post(BASE + "/preview")
async def ops_preview(
    shop_id: uuid.UUID,
    body: common.ImportBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.run_preview(session, shop_id, body)


@router.post(BASE + "/apply")
async def ops_apply(
    shop_id: uuid.UUID,
    body: common.ApplyBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The cards, the version and the audit row commit together."""
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        result = await common.run_apply(
            session, shop_id, body, actor=pc.Actor("staff", staff_id=ctx.staff.id)
        )
    try:
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_APPLY,
            shop_id=shop_id,
            after={
                "number": result.number,
                "file_hash": result.file_hash,
                "reason": result.reason,
                "created": result.created,
                "advanced": result.advanced,
                "executed": result.executed,
                "rejected": result.rejected,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "ops_planned_changes_applied",
        extra={"shop_id": str(shop_id), "staff_id": str(ctx.staff.id), "number": result.number},
    )
    return common.apply_json(result)


@router.get(BASE + "/versions")
async def ops_versions(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.read_versions(session, shop_id)


@router.get(BASE + "/versions/{number}")
async def ops_version(
    shop_id: uuid.UUID,
    number: int,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.read_version(session, shop_id, number)

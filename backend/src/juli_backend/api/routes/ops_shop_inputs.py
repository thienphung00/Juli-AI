"""Juli Ops: Cài đặt shop › Thông số shop (P90 step 4, ADR-120 d.12).

The Ops mirror of ``demo_shop_inputs.py`` -- same read model, same template, same checks
and the same versioned writes -- for the Juli team filling a shop's inputs in on the
seller's behalf (``set_by = team``). Reads are Xem+, writes are Vận hành, and every write
also lands in ``ops_audit_log`` in the same transaction as the versions: a failure between
them rolls both back (counts and the file hash are logged, never the values).

- ``GET  /v1/ops/shops/{id}/inputs``            overview
- ``GET  /v1/ops/shops/{id}/inputs/template``   the pre-filled .xlsx
- ``POST /v1/ops/shops/{id}/inputs/preview``    checks, no write
- ``POST /v1/ops/shops/{id}/inputs/apply``      versioned write (``inputs_apply``)
- ``GET  /v1/ops/shops/{id}/inputs/versions``   history / per-SKU change sets
- ``POST /v1/ops/shops/{id}/inputs/restore``    restore a SKU version (``inputs_restore``)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import demo_shop_inputs as seller
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _view_shop, operator, viewer
from juli_backend.database import get_session
from juli_backend.services import shop_inputs
from juli_backend.services.ops import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_APPLY = "inputs_apply"
ACTION_RESTORE = "inputs_restore"


@router.get("/shops/{shop_id}/inputs")
async def ops_inputs_overview(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop = await _view_shop(session, shop_id)
    return await seller.read_overview(session, shop.id)


@router.get("/shops/{shop_id}/inputs/template")
async def ops_inputs_template(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Response:
    shop = await _view_shop(session, shop_id)
    return await seller.make_template(session, shop.id)


@router.post("/shops/{shop_id}/inputs/preview")
async def ops_inputs_preview(
    shop_id: uuid.UUID,
    body: seller.ImportBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop = await _view_shop(session, shop_id)
    return await seller.run_preview(session, shop.id, body)


@router.post("/shops/{shop_id}/inputs/apply")
async def ops_inputs_apply(
    shop_id: uuid.UUID,
    body: seller.ApplyBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The versions and the audit row commit together."""
    shop = await _view_shop(session, shop_id)
    result = await seller.run_apply(
        session, shop.id, body, actor=shop_inputs.Actor(set_by="team", user_id=ctx.user.id)
    )
    try:
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_APPLY,
            shop_id=shop_id,
            after={
                "file_hash": result.preview.file_hash,
                "reason": result.reason,
                "versions_written": result.versions_written,
                "skus_changed": result.skus_changed,
                "months_changed": result.months_changed,
                "rejected_rows": len(result.preview.rejections),
                "affected_recommendations": result.affected.total,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "ops_shop_inputs_applied",
        extra={"shop_id": str(shop_id), "staff_id": str(ctx.staff.id)},
    )
    return seller.apply_json(result)


@router.get("/shops/{shop_id}/inputs/versions")
async def ops_inputs_versions(
    shop_id: uuid.UUID,
    scope_ref: str | None = Query(default=None, min_length=1, max_length=100),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop = await _view_shop(session, shop_id)
    return await seller.read_versions(session, shop.id, scope_ref)


@router.post("/shops/{shop_id}/inputs/restore")
async def ops_inputs_restore(
    shop_id: uuid.UUID,
    body: seller.RestoreBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop = await _view_shop(session, shop_id)
    result = await seller.run_restore(
        session, shop.id, body, actor=shop_inputs.Actor(set_by="team", user_id=ctx.user.id)
    )
    try:
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_RESTORE,
            shop_id=shop_id,
            after={
                "scope_ref": body.scope_ref,
                "restored_from": body.version,
                "versions_written": result["data"]["versions_written"],
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return result

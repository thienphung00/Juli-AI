"""Cài đặt › Đề xuất kế hoạch, the seller's side (P91 D-13).

The shop's owner downloads the sheet, lists the listing changes it plans or has made (title,
first line of the description, cover image, variation table, hide, relist), uploads it, reads
the rejected rows and the cards each valid row would become, and applies it with a reason.
Every valid row becomes a manual card (``origin = "import"``, JC code, ``external_ref``); a row
marked "hoàn thành" is recorded as executed on its date. Every apply is a numbered version.

- ``GET  /v1/demo/shop-inputs/planned-changes``            columns, kinds, suggested reasons.
- ``GET  /v1/demo/shop-inputs/planned-changes/template``   the empty ``.xlsx``.
- ``POST /v1/demo/shop-inputs/planned-changes/preview``    ``{"file_b64"}`` -> rows; writes nothing.
- ``POST /v1/demo/shop-inputs/planned-changes/apply``      ``{"file_b64", "reason", "file_hash"?}``.
- ``GET  /v1/demo/shop-inputs/planned-changes/versions``   applied files, newest first.
- ``GET  /v1/demo/shop-inputs/planned-changes/versions/{number}``  one file's per-row outcome.

The Ops mirror is ``ops_planned_changes.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes import planned_changes_common as common
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import planned_changes as pc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/shop-inputs/planned-changes", tags=["demo"])


@router.get("")
async def get_overview(shop: Shop = Depends(get_active_shop)) -> dict[str, Any]:
    _shopee(shop)
    return common.overview()


@router.get("/template")
async def download_template(shop: Shop = Depends(get_active_shop)) -> Response:
    _shopee(shop)
    return common.template_response()


@router.post("/preview")
async def preview(
    body: common.ImportBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.run_preview(session, _shopee(shop), body)


@router.post("/apply")
async def apply(
    body: common.ApplyBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    result = await common.run_apply(
        session, shop_id, body, actor=pc.Actor("seller", user_id=user.id)
    )
    await session.commit()
    logger.info(
        "planned_changes_applied",
        extra={
            "shop_id": str(shop_id),
            "user_id": str(user.id),
            "number": result.number,
            "cards_created": result.created,
            "file_hash": result.file_hash,
        },
    )
    return common.apply_json(result)


@router.get("/versions")
async def list_versions(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await common.read_versions(session, _shopee(shop))


@router.get("/versions/{number}")
async def get_version(
    number: int,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.read_version(session, _shopee(shop), number)

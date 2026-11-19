"""Juli Ops: Cài đặt shop › Báo cáo tồn kho (batch-1119-f5, F5.O1).

The Ops mirror of ``scripts/stock_alert_status.py``: the shop's stock e-mail switch and its alert
days, written through ``services.stock_alert.settings`` (same validation, same ``shop_rules`` rows,
``set_by = team``). Reads are Xem+, the write is Vận hành and lands in ``ops_audit_log`` in the same
transaction. The reviewer's sample shop refuses anything but ``off``.

- ``GET /v1/ops/shops/{id}/stock-alert``  ``{status, days}``
- ``PUT /v1/ops/shops/{id}/stock-alert``  ``{status?, days?}``
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _view_shop, operator, viewer
from juli_backend.database import get_session
from juli_backend.repositories import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.stock_alert import settings as stock_settings

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_STOCK_ALERT_SET = "stock_alert_set"


class StockAlertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    days: int | None = None


def _json(conf: stock_settings.ShopSettings) -> dict[str, Any]:
    return {"status": conf.status, "days": conf.days}


@router.get("/shops/{shop_id}/stock-alert")
async def ops_stock_alert_get(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop = await _view_shop(session, shop_id)
    return _json(await stock_settings.load_settings(session, shop.id))


@router.put("/shops/{shop_id}/stock-alert")
async def ops_stock_alert_put(
    shop_id: uuid.UUID,
    body: StockAlertBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The settings row and the audit row commit together."""
    shop = await _view_shop(session, shop_id)
    before = await stock_settings.load_settings(session, shop.id)
    new_status = body.status if body.status is not None else before.status
    try:
        after = await stock_settings.set_status(
            session, shop.id, new_status, now=utc_now_naive(), days=body.days
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "bad_stock_alert_setting", "message": str(exc)},
        ) from exc
    try:
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_STOCK_ALERT_SET,
            shop_id=shop_id,
            before=_json(before),
            after=_json(after),
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return _json(after)

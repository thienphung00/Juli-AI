"""Juli Ops: the Shopee funnel's accuracy checks of one shop (P98 / ADR-122 d.11.3, d.11.4).

- ``GET /v1/ops/shops/{id}/shopee/funnel-check?days=N&as_of=`` (Xem+) -- ``funnel_check`` over the
  last N days: every gap between the stored source funnel and Shopee's raw numbers ("lệch số liệu").
  Read only; nothing is corrected.
- ``GET /v1/ops/shops/{id}/shopee/prediction-coverage`` (Xem+) -- per family, the share of scored
  predictions whose measured result fell inside low-high (target about 80 %), from the calibration
  rows the learning job stores.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops import shopee_funnel_ops as svc

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

DEFAULT_DAYS = 14


@router.get("/shops/{shop_id}/shopee/funnel-check")
async def ops_funnel_check(
    shop_id: uuid.UUID,
    days: Annotated[int, Query(ge=1, le=60)] = DEFAULT_DAYS,
    as_of: Annotated[date | None, Query()] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    end = as_of or datetime.now(UTC).date()
    async with with_shop_scope(session, shop_id):
        return await svc.funnel_check_report(session, shop_id, days=days, as_of=end)


@router.get("/shops/{shop_id}/shopee/prediction-coverage")
async def ops_prediction_coverage(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await svc.prediction_coverage(session, shop_id)

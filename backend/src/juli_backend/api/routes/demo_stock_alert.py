"""Stock alert routes (P100 Part S).

Seller (``get_current_user`` + ``get_active_shop``, the caller's shop only):

- ``GET /v1/demo/shopee/stock`` -- Sản phẩm (list + product page): one row per variation with
  its stock, units / day, days left, the day it runs out and its "Theo dõi" switch. ``enabled``
  false on the reviewer's sample shop (no rows, no switch).
- ``PUT /v1/demo/shopee/stock/{sku_key}/tracking`` -- body ``{"tracked": bool}``; any member may
  switch (who and when are kept). Off withdraws / tags the open cards that target only stopped
  variations (``stock_alert.cards``). 403 on the sample shop.

Public, no sign-in (the signed link of the e-mail is the credential):

- ``POST /v1/stock-alert/unsubscribe`` -- body ``{"token"}``; unsubscribes only the member the
  token names from that shop's stock e-mail. There is no GET that changes anything.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.stock_alert import (
    cards,
    data,
    eligibility,
    links,
    settings,
    unsubscribe,
)
from juli_backend.services.stock_alert import stock_basis as sb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/shopee/stock", tags=["demo-shopee"])
public_router = APIRouter(prefix="/stock-alert", tags=["stock-alert"])

SKU_KEY = r"^[0-9]{1,64}(:[0-9]{1,64})?$"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _shopee(shop: Shop) -> uuid.UUID:
    if shop.platform != "shopee":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "not_a_shopee_shop", "message": "this shop is not on Shopee"},
        )
    return shop.id


def _row(
    state: data.SkuState, tracked: bool, eligible: bool, today: Any, days: int
) -> dict[str, Any]:
    f = state.facts
    fc = None
    out_since = None
    if state.stock is not None:
        alert = eligibility.evaluate(f, today, alert_days=10**6)
        if alert is not None:
            fc = alert.forecast
            out_since = alert.out_since
    return {
        "key": f.key,
        "item_id": f.item_id,
        "model_id": f.model_id,
        "product_name": f.product_name,
        "variation_name": f.variation_name,
        "sku_code": f.sku_code,
        "stock": None if state.stock is None else state.stock.stock,
        "units_per_day": round(f.base, 2) if state.stock is not None else None,
        "days_left": None if fc is None else fc.days_left,
        "runs_out_on": None if fc is None or fc.runs_out_on is None else fc.runs_out_on.isoformat(),
        "out_of_stock": state.stock is not None and state.stock.stock <= 0,
        "out_since": None if out_since is None else out_since.isoformat(),
        "read_at": None if state.stock is None else state.stock.read_at.isoformat() + "Z",
        "tracked": tracked,
        "eligible": eligible,
        "soon": fc is not None and fc.days_left is not None and fc.days_left <= days,
    }


@router.get("")
async def stock_list(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    conf = await settings.load_settings(session, shop_id)
    if conf.sample:
        return {"data": {"enabled": False, "rows": []}}
    now = _now()
    today = sb.local_day(now)
    states, _ = await data.load_states(session, shop_id, today, now)
    stored = await settings.tracking_rows(session, shop_id)
    rows = []
    for s in states:
        eligible = s.stock is not None and eligibility.is_eligible(s.facts, today)
        tracked = settings.effective(stored.get(s.facts.key), eligible)
        rows.append(_row(s, tracked, eligible, today, conf.days))
    rows.sort(key=lambda r: (r["product_name"], r["variation_name"] or "", r["key"]))
    return {"data": {"enabled": True, "alert_days": conf.days, "rows": rows}}


class TrackingBody(BaseModel):
    tracked: bool


@router.put("/{sku_key}/tracking")
async def set_tracking(
    body: TrackingBody,
    sku_key: str = Path(pattern=SKU_KEY),
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    if (await settings.load_settings(session, shop_id)).sample:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "sample_shop"})
    now = _now()
    row = await settings.set_tracked(
        session, shop_id, sku_key, body.tracked, user_id=user.id, now=now
    )
    counts = await cards.apply(session, shop_id, now=now)
    await session.commit()
    return {
        "data": {
            "key": sku_key,
            "tracked": row.tracked,
            "set_at": row.set_at.isoformat() + "Z",
            "cards": counts,
        }
    }


class UnsubscribeBody(BaseModel):
    token: str = Field(min_length=10, max_length=400)


@public_router.post("/unsubscribe")
async def unsubscribe_member(
    body: UnsubscribeBody, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    try:
        who = links.verify(body.token)
    except links.BadToken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "bad_token"}) from None
    async with with_shop_scope(session, who.shop_id):
        await unsubscribe.unsubscribe(session, who.shop_id, who.user_id, now=_now())
        await session.commit()
    logger.info("stock_alert_unsubscribed", extra={"shop_id": str(who.shop_id)})
    return {"data": {"unsubscribed": True}}


__all__ = ["public_router", "router"]

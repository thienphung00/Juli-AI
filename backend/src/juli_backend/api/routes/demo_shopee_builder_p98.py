"""Seller scope: the P98 builders' read-only setup endpoints under ``/v1/demo/shopee/builder``.

``POST /combo/options`` (products + variations + packs + rules + price rule -> priced rows, both
margins, limit warnings, per-row inputs), ``POST /kol/setup`` (KOLs + products + commission +
samples -> validated setups with the KOLs' measured numbers) and ``POST /ads/setup`` (new Hiển thị
Sản phẩm setups -> validated setups with the products' measured ad numbers). POST only because the
body is large; nothing is written. Only the seller of that shop (active shop). Logic:
``services/shopee_builder/{combo,kol,ads}_builder``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.database import Shop, get_session
from juli_backend.services.shopee_builder import ads_builder, combo_builder, kol_builder, service
from juli_backend.services.shopee_builder.specs_p98 import (
    AdsRequest,
    BuilderInputError,
    ComboRequest,
    KolRequest,
)

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _refused(exc: BuilderInputError) -> HTTPException:
    return HTTPException(exc.status, detail=common.detail(exc.code, exc.message, **exc.more))


@router.post("/builder/combo/options")
async def combo_options(
    body: ComboRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await combo_builder.build(session, _shopee(shop), body, now=_now())
    except service.NoShopeeData:
        raise common.no_data() from None
    except BuilderInputError as exc:
        raise _refused(exc) from None


@router.post("/builder/kol/setup")
async def kol_setup(
    body: KolRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await kol_builder.build(session, _shopee(shop), body, now=_now())
    except service.NoShopeeData:
        raise common.no_data() from None
    except BuilderInputError as exc:
        raise _refused(exc) from None


@router.post("/builder/ads/setup")
async def ads_setup(
    body: AdsRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await ads_builder.build(session, _shopee(shop), body, now=_now())
    except service.NoShopeeData:
        raise common.no_data() from None
    except BuilderInputError as exc:
        raise _refused(exc) from None

"""Seller scope: "Tự tạo phương án" (P92) and Cài đặt › Loại trừ sản phẩm, under
``/v1/demo/shopee``.

Builder (``/builder``): the product picker, a product's variations (price and margin), "hay mua
cùng", the keyword table, the ads campaigns, ``/evaluate`` and ``/compare`` (1-4 / 2-4 versions of
mixed kinds, nothing saved), ``/choose`` (the chosen version becomes the seller's own manual card,
already sent) and the LLM drafts (titles, cover overlays, description first lines; 503 "LLM tắt"
when the model is off). Exclusions (``/exclusions``): list, add, undo, each a versioned shop-input
change. Only the seller of that shop. The logic is ``services/shopee_builder``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shop_inputs
from juli_backend.services.shopee_recommendations import manual, seller_view

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])

AsOf = Annotated[date | None, Query()]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/builder/products")
async def builder_products(
    q: Annotated[str | None, Query(max_length=100)] = None,
    include_excluded: bool = False,
    sort: Annotated[str, Query(pattern=common.SORT_PATTERN)] = "gmv_90d",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_products(
        session,
        _shopee(shop),
        as_of=as_of,
        q=q,
        include_excluded=include_excluded,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/builder/products/{item_id}/variations")
async def builder_variations(
    item_id: common.ItemPath,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_variations(session, _shopee(shop), item_id, as_of=as_of, now=_now())


@router.get("/builder/products/{item_id}/co-purchase")
async def builder_co_purchase(
    item_id: common.ItemPath,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_co_purchase(session, _shopee(shop), item_id, as_of=as_of)


@router.get("/builder/products/{item_id}/keywords")
async def builder_keywords(
    item_id: common.ItemPath,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_keywords(session, _shopee(shop), item_id, as_of=as_of, now=_now())


@router.get("/builder/ads/campaigns")
async def builder_campaigns(
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_campaigns(session, _shopee(shop), as_of=as_of, now=_now())


@router.post("/builder/evaluate")
async def builder_evaluate(
    body: common.EvaluateBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_evaluate(session, _shopee(shop), body, now=_now())


@router.post("/builder/compare")
async def builder_compare(
    body: common.CompareBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_evaluate(session, _shopee(shop), body, now=_now())


@router.post("/builder/choose", status_code=201)
async def builder_choose(
    body: common.ChooseBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        out = await common.h_choose(
            session, shop_id, body, manual.Actor("seller", user.id), now=_now()
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    versions = [{k: v for k, v in row.items() if k != "card"} for row in out["versions"]]
    return {**out, "card": seller_view(out["card"]), "versions": versions}


@router.post("/builder/group", status_code=201)
async def builder_group(
    body: common.GroupBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """ "Chạy cùng nhau": the ticked versions become one group (Nhóm) of the draft plan."""
    shop_id = _shopee(shop)
    try:
        out = await common.h_group(
            session, shop_id, body, manual.Actor("seller", user.id), now=_now(), audience="seller"
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return out


@router.post("/builder/drafts/title")
async def builder_title_drafts(
    body: common.TitleDraftBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    client = await common.get_client(session, shop_id)
    try:
        out = await common.h_title_drafts(session, shop_id, body, client, now=_now())
    finally:
        await session.commit()  # keeps the gate's llm_call_log row
    return out


@router.post("/builder/drafts/cover")
async def builder_cover_drafts(
    body: common.DraftBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    client = await common.get_client(session, shop_id)
    try:
        out = await common.h_cover_drafts(session, shop_id, body, client, now=_now())
    finally:
        await session.commit()  # keeps the gate's llm_call_log row
    return out


@router.post("/builder/drafts/description")
async def builder_description_drafts(
    body: common.DraftBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    client = await common.get_client(session, shop_id)
    try:
        out = await common.h_description_drafts(session, shop_id, body, client, now=_now())
    finally:
        await session.commit()  # keeps the gate's llm_call_log row
    return out


# ----------------------------------------------------------------------------- exclusions


@router.get("/exclusions")
async def list_exclusions(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await common.h_exclusions(session, _shopee(shop))


@router.put("/exclusions/{item_id}")
async def add_exclusion(
    item_id: common.ItemPath,
    body: common.ExclusionBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        row = await shop_inputs.add_exclusion(
            session,
            shop_id,
            item_id,
            body.reason,
            actor=shop_inputs.Actor("seller", user.id),
            note=body.note,
        )
        await session.commit()
    except shop_inputs.ExclusionError as exc:
        await session.rollback()
        raise common.exclusion_error(exc) from None
    return row.json()


@router.delete("/exclusions/{item_id}", status_code=204)
async def undo_exclusion(
    item_id: common.ItemPath,
    note: Annotated[str | None, Query(max_length=500)] = None,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    shop_id = _shopee(shop)
    existed = await shop_inputs.undo_exclusion(
        session, shop_id, item_id, actor=shop_inputs.Actor("seller", user.id), note=note
    )
    if not existed:
        await session.rollback()
        raise common.HTTPException(
            404, detail=common.detail("exclusion_not_found", "Sản phẩm này chưa bị loại trừ")
        )
    await session.commit()
    return Response(status_code=204)

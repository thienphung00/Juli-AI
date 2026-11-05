"""Juli Ops: the P92 builder and Cài đặt › Loại trừ sản phẩm for one shop.

The Ops mirror of ``demo_shopee_builder`` -- same bodies, same answers -- under
``/v1/ops/shops/{id}/shopee``: reads, ``/builder/evaluate`` and ``/builder/compare`` are Xem+;
``/builder/choose`` (a draft manual card Ops publishes), the LLM drafts (they spend the shop's
OpenAI budget) and the exclusion writes are Vận hành, and every write lands in ``ops_audit_log``
in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shop_inputs
from juli_backend.services.ops import audit
from juli_backend.services.shopee_recommendations import manual

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee"
ACTION_CHOOSE = "builder_choose"
ACTION_EXCLUDE = "exclusion_add"
ACTION_UNEXCLUDE = "exclusion_undo"

AsOf = Annotated[date | None, Query()]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get(BASE + "/builder/products")
async def ops_products(
    shop_id: uuid.UUID,
    q: Annotated[str | None, Query(max_length=100)] = None,
    include_excluded: bool = False,
    sort: Annotated[str, Query(pattern=common.SORT_PATTERN)] = "gmv_90d",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_products(
            session,
            shop_id,
            as_of=as_of,
            q=q,
            include_excluded=include_excluded,
            sort=sort,
            limit=limit,
            offset=offset,
        )


@router.get(BASE + "/builder/products/{item_id}/variations")
async def ops_variations(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_variations(session, shop_id, item_id, as_of=as_of, now=_now())


@router.get(BASE + "/builder/products/{item_id}/co-purchase")
async def ops_co_purchase(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_co_purchase(session, shop_id, item_id, as_of=as_of)


@router.get(BASE + "/builder/products/{item_id}/keywords")
async def ops_keywords(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_keywords(session, shop_id, item_id, as_of=as_of, now=_now())


@router.get(BASE + "/builder/ads/campaigns")
async def ops_campaigns(
    shop_id: uuid.UUID,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_campaigns(session, shop_id, as_of=as_of, now=_now())


@router.post(BASE + "/builder/evaluate")
async def ops_evaluate(
    shop_id: uuid.UUID,
    body: common.EvaluateBody,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_evaluate(session, shop_id, body, now=_now())


@router.post(BASE + "/builder/compare")
async def ops_compare(
    shop_id: uuid.UUID,
    body: common.CompareBody,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_evaluate(session, shop_id, body, now=_now())


@router.post(BASE + "/builder/choose", status_code=201)
async def ops_choose(
    shop_id: uuid.UUID,
    body: common.ChooseBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            out = await common.h_choose(
                session,
                shop_id,
                body,
                manual.Actor("staff", ctx.staff.id, staff_id=ctx.staff.id),
                now=_now(),
            )
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_CHOOSE,
            shop_id=shop_id,
            after={
                "card_id": out["id"],
                "change_kind": out["card"]["change_kind"],
                "versions": len(out["versions"]),
                "kinds": [v.kind for v in body.versions],
                "primary": body.primary,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return out


async def _draft(shop_id: uuid.UUID, session: AsyncSession, run: Any) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            client = await common.get_client(session, shop_id)
            return await run(client)
    finally:
        await session.commit()  # the gate's llm_call_log row is kept whatever the answer


@router.post(BASE + "/builder/drafts/title")
async def ops_title_drafts(
    shop_id: uuid.UUID,
    body: common.TitleDraftBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _draft(
        shop_id,
        session,
        lambda client: common.h_title_drafts(session, shop_id, body, client, now=_now()),
    )


@router.post(BASE + "/builder/drafts/cover")
async def ops_cover_drafts(
    shop_id: uuid.UUID,
    body: common.DraftBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _draft(
        shop_id,
        session,
        lambda client: common.h_cover_drafts(session, shop_id, body, client, now=_now()),
    )


@router.post(BASE + "/builder/drafts/description")
async def ops_description_drafts(
    shop_id: uuid.UUID,
    body: common.DraftBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _draft(
        shop_id,
        session,
        lambda client: common.h_description_drafts(session, shop_id, body, client, now=_now()),
    )


# ----------------------------------------------------------------------------- exclusions


@router.get(BASE + "/exclusions")
async def ops_list_exclusions(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await common.h_exclusions(session, shop_id)


@router.put(BASE + "/exclusions/{item_id}")
async def ops_add_exclusion(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    body: common.ExclusionBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            row = await shop_inputs.add_exclusion(
                session,
                shop_id,
                item_id,
                body.reason,
                actor=shop_inputs.Actor("team", ctx.staff.id),
                note=body.note,
            )
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_EXCLUDE,
            shop_id=shop_id,
            after={"item_id": item_id, "reason": body.reason},
        )
        await session.commit()
    except shop_inputs.ExclusionError as exc:
        await session.rollback()
        raise common.exclusion_error(exc) from None
    except Exception:
        await session.rollback()
        raise
    return row.json()


@router.delete(BASE + "/exclusions/{item_id}", status_code=204)
async def ops_undo_exclusion(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    note: Annotated[str | None, Query(max_length=500)] = None,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            existed = await shop_inputs.undo_exclusion(
                session,
                shop_id,
                item_id,
                actor=shop_inputs.Actor("team", ctx.staff.id),
                note=note,
            )
        if not existed:
            await session.rollback()
            raise common.HTTPException(
                404, detail=common.detail("exclusion_not_found", "Sản phẩm này chưa bị loại trừ")
            )
        await audit.record(
            session, ctx.staff.actor, ACTION_UNEXCLUDE, shop_id=shop_id, after={"item_id": item_id}
        )
        await session.commit()
    except common.HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise
    return Response(status_code=204)

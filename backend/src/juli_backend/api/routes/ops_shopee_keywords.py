"""Juli Ops: Shopee keywords -- "Từ khóa" (ADR-119, owner grill D81.4-D81.8).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth dependencies
(Cloudflare Access → Supabase → active staff row → role) and PII-masking route class.

- ``GET  /v1/ops/shops/{id}/shopee/keywords[?min_volume=]`` (Xem+) -- the board: keyword
  combinations, latest metrics, weekly volume, related keywords, coverage, and products with
  no keyword above ``min_volume`` (title-proposal candidates).
- ``POST /v1/ops/shops/{id}/shopee/keywords/seeds/generate`` (Vận hành) -- "Tạo từ khóa từ
  tiêu đề": decompose the shop's item titles into ``shop_keyword_seeds``. Audited
  ``keyword_seeds_generate``.
- ``PUT  /v1/ops/shops/{id}/shopee/keywords/seeds/{seed_id}`` (Vận hành) -- keep or drop one
  combination (``enabled``). Audited ``keyword_seed_toggle``.
- ``POST /v1/ops/market/keyword-metrics`` (Vận hành) -- the owner's weekly upload of
  shopeeanalytics.com lookups in the collection format (public lane, no shop). Audited
  ``keyword_metrics_upload`` with counts only.

A shop that is not on Shopee answers 409 ``not_a_shopee_shop``. The service is
``services/shop_keywords``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shop_keywords
from juli_backend.services.ops import audit

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

PLATFORM = "shopee"
ACTION_SEEDS_GENERATE = "keyword_seeds_generate"
ACTION_SEED_TOGGLE = "keyword_seed_toggle"
ACTION_METRICS_UPLOAD = "keyword_metrics_upload"
MAX_MIN_VOLUME = 10_000_000


class GenerateWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str | None = Field(default=None, max_length=shop_keywords.MAX_BRAND)


class SeedWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MetricsUpload(BaseModel):
    """The collection file's lines, decoded by the page; each is checked by the format."""

    model_config = ConfigDict(extra="forbid")
    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/shops/{shop_id}/shopee/keywords")
async def ops_shopee_keywords(
    shop_id: uuid.UUID,
    min_volume: Annotated[int, Query(ge=0, le=MAX_MIN_VOLUME)] = shop_keywords.DEFAULT_MIN_VOLUME,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    payload = await shop_keywords.board(session, shop_id, PLATFORM, min_volume=min_volume)
    await session.commit()
    return payload


@router.post("/shops/{shop_id}/shopee/keywords/seeds/generate")
async def ops_generate_keyword_seeds(
    shop_id: uuid.UUID,
    body: GenerateWrite | None = None,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    brand = ((body.brand or "").strip() or None) if body else None
    async with with_shop_scope(session, shop_id):
        result = await shop_keywords.generate(
            session, shop_id, PLATFORM, brand=brand, staff_id=ctx.staff.id, now=_now()
        )
    after = {
        "titles": result.titles,
        "candidates": result.candidates,
        "created": result.created,
        "updated": result.updated,
        "brand_given": brand is not None,
    }
    await audit.record(
        session, ctx.staff.actor, ACTION_SEEDS_GENERATE, shop_id=shop_id, after=after
    )
    await session.commit()
    return after


@router.put("/shops/{shop_id}/shopee/keywords/seeds/{seed_id}")
async def ops_set_keyword_seed(
    shop_id: uuid.UUID,
    seed_id: uuid.UUID,
    body: SeedWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            seed = await shop_keywords.set_enabled(
                session, shop_id, seed_id, body.enabled, now=_now()
            )
            after = shop_keywords.seed_json(seed)
    except shop_keywords.SeedNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail={"code": "keyword_seed_not_found"}) from None
    await audit.record(
        session,
        ctx.staff.actor,
        ACTION_SEED_TOGGLE,
        shop_id=shop_id,
        after={"keyword": after["keyword"], "enabled": after["enabled"]},
    )
    await session.commit()
    return {"seed": after}


@router.post("/market/keyword-metrics")
async def ops_upload_keyword_metrics(
    body: MetricsUpload,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        records = shop_keywords.parse_records(body.records)
    except shop_keywords.CollectionError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_keyword_collection",
                "message": str(exc),
                "errors": exc.errors[:20],
            },
        ) from None
    result = await shop_keywords.store_records(session, records, now=_now())
    after = {
        "records": result.records,
        "rows_written": result.rows_written,
        "rows_kept": result.rows_kept,
        "by_status": result.by_status,
        "collected_on": result.collected_on,
    }
    await audit.record(session, ctx.staff.actor, ACTION_METRICS_UPLOAD, after=after)
    await session.commit()
    return after

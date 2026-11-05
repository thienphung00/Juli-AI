"""Juli Ops: Shopee order export upload -- "Đơn hàng" (P90 step 2, G-03).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth dependencies
(Cloudflare Access → Supabase → active staff row → role) and PII-masking route class.

The buyer's data never reaches this API. The page reads the order export in the browser, keeps
only the allowlisted columns, replaces the order id by a keyed hash and posts the lines; the
row model has no field for a name, a contact number, an address, a comment or a tracking id
and refuses an unknown one (422), so a client that forgot to strip fails loudly instead of
storing it.

- ``GET  /v1/ops/shops/{id}/shopee/orders/ref-key`` (Vận hành) -- the shop's ``order_ref`` key
  for ONE upload: ``Cache-Control: no-store``, a short ``expires_at``, audited
  ``order_ref_key_issue`` WITHOUT the key. 503 ``order_ref_key_not_configured`` when the master
  key is not set. See ``services/ingest/order_ref``.
- ``POST /v1/ops/shops/{id}/shopee/orders/upload`` (Vận hành) -- up to 1 000 PII-free order
  lines (one chunk of the browser's posts) through the ingest gateway as dataset
  ``order_lines``. Audited ``orders_upload`` with counts only.

A shop that is not on Shopee answers 409 ``not_a_shopee_shop``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_analytics_common import (
    REFUSALS,
    DateQ,
    MonthQ,
    PeriodQ,
    refusal,
    window_args,
)
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ingest import order_ref
from juli_backend.services.ops import audit
from juli_backend.services.shopee_analytics import orders as order_view
from juli_backend.services.shopee_analytics import queries

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

PLATFORM = "shopee"
DATASET = "order_lines"
SOURCE_VERSION = "ops-browser-1"
ACTION_KEY_ISSUE = "order_ref_key_issue"
ACTION_UPLOAD = "orders_upload"
MAX_LINES = 1_000


class OrderLinesUpload(BaseModel):
    """PII-stripped lines as the browser module built them; each is checked by the row model."""

    model_config = ConfigDict(extra="forbid")
    lines: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_LINES)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _period(lines: list[dict[str, Any]]) -> tuple[date, date]:
    days: list[date] = []
    for line in lines:
        try:
            days.append(date.fromisoformat(str(line["ordered_at"])[:10]))
        except (KeyError, ValueError):
            raise HTTPException(
                status_code=422, detail={"code": "invalid_order_lines", "message": "ordered_at"}
            ) from None
    return min(days), max(days)


@router.get("/shops/{shop_id}/shopee/orders/ref-key")
async def ops_order_ref_key(
    shop_id: uuid.UUID,
    response: Response,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    now = _now()
    try:
        issued = order_ref.issue(shop_id, now)
    except order_ref.OrderRefKeyUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "order_ref_key_not_configured"}
        ) from None
    await audit.record(
        session,
        ctx.staff.actor,
        ACTION_KEY_ISSUE,
        shop_id=shop_id,
        after={
            "key_version": issued.key_version,
            "ttl_seconds": int(order_ref.KEY_TTL.total_seconds()),
        },
    )
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "order_ref_key": issued.key_hex,
        "algorithm": issued.algorithm,
        "key_version": issued.key_version,
        "expires_at": issued.expires_at.isoformat() + "Z",
    }


@router.post("/shops/{shop_id}/shopee/orders/upload")
async def ops_upload_order_lines(
    shop_id: uuid.UUID,
    body: OrderLinesUpload,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    start, end = _period(body.lines)
    now = _now()
    posted = ingest_service.IngestBody.model_validate(
        {
            "source": "file",
            "source_version": SOURCE_VERSION,
            "captured_at": now.replace(tzinfo=UTC).isoformat(),
            "period": {"start": start.isoformat(), "end": end.isoformat(), "granularity": "period"},
            "rows": body.lines,
        }
    )
    try:
        async with with_shop_scope(session, shop_id):
            result = await ingest_service.ingest(
                session,
                shop_id=shop_id,
                platform=PLATFORM,
                dataset=DATASET,
                body=posted,
                token_id=None,
                now=now,
            )
    except ingest_service.IngestRejected as exc:
        await session.rollback()
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "errors": exc.errors}
        ) from None
    after = {"lines": result.rows, "duplicate": result.duplicate}
    await audit.record(session, ctx.staff.actor, ACTION_UPLOAD, shop_id=shop_id, after=after)
    await session.commit()
    return after


@router.get("/shops/{shop_id}/shopee/orders")
async def ops_orders(
    shop_id: uuid.UUID,
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    status: Annotated[str | None, Query(pattern=f"^({'|'.join(order_view.STATUSES)})$")] = None,
    lever: Annotated[
        str | None, Query(pattern="^(promotion|flash_sale|voucher|combo|affiliate)$")
    ] = None,
    sort: Annotated[str, Query(pattern=f"^({'|'.join(order_view.SORTS)})$")] = "date",
    limit: Annotated[int, Query(ge=1, le=order_view.MAX_LIMIT)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Đơn hàng, the same read the seller has: hashed keys, no buyer data."""
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            return await queries.orders(
                session,
                shop_id,
                status=status,
                lever=lever,
                sort=sort,
                limit=limit,
                offset=offset,
                **window_args(period, month, start, end, as_of),
            )
    except REFUSALS as exc:
        raise refusal(exc) from None

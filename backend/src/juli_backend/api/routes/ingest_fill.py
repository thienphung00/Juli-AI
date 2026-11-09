"""P97 D85.6 adds the fill queue: ``GET /v1/ingest/fill-jobs`` (the token's shop only),
``POST /v1/ingest/fill-jobs/{id}`` (progress, captured id) and the seller's
``GET /v1/demo/shopee/fill-jobs?card_id=`` / ``POST .../{id}/cancel``.

``GET /v1/ingest/fill/{code}`` -- the text the Connector may type into a product edit page
for one approved card (p91 D-13, flag ``fill_listing``). Ingest-token auth like the rest of
the Connector's calls; shop-scoped; read-only. See ``services.shopee_recommendations.fill``."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.database import Shop, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as ingest_service
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import fill, fill_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest/fill", tags=["ingest"])


@router.get("/{code}")
async def get_fill_request(
    code: str,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    try:
        async with with_shop_scope(session, principal.shop_id):
            out = await fill.fill_request(session, principal.shop_id, code[:40])
    except ProposalError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
    await session.commit()
    logger.info(
        "connector_fill_requested", extra={"shop_id": str(principal.shop_id), "card": out["code"]}
    )
    return out


@router.get("")
async def get_fill_flag(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
) -> dict[str, Any]:
    """Whether the server allows fill-in (the Connector's popup / banner may ask)."""
    return {"enabled": fill.enabled(), "platform": principal.platform}


jobs_router = APIRouter(prefix="/ingest/fill-jobs", tags=["ingest"])


class JobReport(BaseModel):
    status: str = Field(pattern="^(opened|filled|saved|captured|failed)$")
    captured_ref: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, max_length=64)


@jobs_router.get("")
async def list_fill_jobs(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The open fill jobs of the TOKEN's shop (never another shop's; kill switch =
    ``CONNECTOR_FILL_LISTING``). The Connector opens one page at a time."""
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    if not fill_queue.enabled():
        return {"enabled": False, "jobs": []}
    async with with_shop_scope(session, principal.shop_id):
        jobs = await fill_queue.jobs_for_shop(session, principal.shop_id)
    await session.commit()
    return {"enabled": True, "jobs": jobs}


@jobs_router.post("/{job_id}")
async def report_fill_job(
    job_id: uuid.UUID,
    body: JobReport,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    if not fill_queue.enabled():
        raise HTTPException(status_code=404, detail={"code": fill.ERROR_DISABLED})
    try:
        async with with_shop_scope(session, principal.shop_id):
            out = await fill_queue.report(
                session,
                principal.shop_id,
                job_id,
                status=body.status,
                captured_ref=body.captured_ref,
                error=body.error,
            )
    except ProposalError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
    await session.commit()
    logger.info(
        "connector_fill_job",
        extra={"shop_id": str(principal.shop_id), "job": str(job_id), "status": body.status},
    )
    return out


seller_router = APIRouter(prefix="/demo/shopee/fill-jobs", tags=["demo-shopee"])


@seller_router.get("")
async def seller_fill_jobs(
    card_id: uuid.UUID = Query(),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The fill checklist of one approved card: one row per target page."""
    shop_id = _shopee(shop)
    jobs = await fill_queue.jobs_of_card(session, shop_id, card_id)
    await session.commit()
    return {"data": {"enabled": fill_queue.enabled(), "jobs": jobs}}


@seller_router.post("/{job_id}/cancel")
async def seller_cancel_fill_job(
    job_id: uuid.UUID,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        out = await fill_queue.cancel(session, shop_id, job_id)
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
    return {"data": out}

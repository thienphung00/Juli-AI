"""``GET /v1/ingest/fill/{code}`` -- the text the Connector may type into a product edit page
for one approved card (p91 D-13, flag ``fill_listing``). Ingest-token auth like the rest of
the Connector's calls; shop-scoped; read-only. See ``services.shopee_recommendations.fill``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as ingest_service
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import fill

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

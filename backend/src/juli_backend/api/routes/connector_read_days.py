"""``GET /v1/connector/shopee/read-days``: the days the Connector still has to read (F4.2).

Same ingest-token auth as the Connector's other calls (the token names exactly one shop);
read-only. See ``services.ingest.read_days``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ingest import read_days

router = APIRouter(prefix="/connector/shopee", tags=["ingest"])


@router.get("/read-days")
async def get_read_days(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    async with with_shop_scope(session, principal.shop_id):
        return await read_days.read_days(session, principal.shop_id, principal.platform)

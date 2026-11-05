"""``GET /v1/ingest/market/keywords`` -- which public Shopee searches the Connector should read
this week (P92 B-10). Ingest-token auth like the rest of the Connector's calls; shop-scoped,
read-only. See ``services.ingest.market``. The searches themselves are posted as the
``market_search`` dataset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.repositories import utc_now_naive
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ingest import market
from juli_backend.services.ingest.gateway import platform_today

router = APIRouter(prefix="/ingest/market", tags=["ingest"])


@router.get("/keywords")
async def get_market_keywords(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    if not market.enabled(principal.shop_id):
        return {
            "enabled": False,
            "max_per_product": market.MAX_KEYWORDS_PER_PRODUCT,
            "products": [],
            "due_keywords": [],
            "last_collected": {},
        }
    async with with_shop_scope(session, principal.shop_id):
        per_item = await market.shop_keywords(session, principal.shop_id)
        every = sorted({k for ks in per_item.values() for k in ks})
        last = await market.last_collected(session, every)
    await session.commit()
    today = platform_today(utc_now_naive())
    return {
        "enabled": True,
        "max_per_product": market.MAX_KEYWORDS_PER_PRODUCT,
        "due_after_days": market.DUE_AFTER_DAYS,
        "products": [{"item_id": i, "keywords": ks} for i, ks in per_item.items() if ks],
        "due_keywords": market.due(every, last, today),
        "last_collected": {k: d.isoformat() for k, d in sorted(last.items())},
        "as_of": today.isoformat(),
    }

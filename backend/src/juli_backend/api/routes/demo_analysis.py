"""Demo Phân tích read API (fast track P7-A, AC-7.2, D21).

``GET /v1/demo/analysis`` returns the latest stored ADR-108 shop diagnosis
report for the authenticated caller's own shop. Auth and shop scope are the
same as ``GET /v1/demo/decisions`` (``api/routes/demo_decisions.py``):
``get_current_user`` + ``get_active_shop``, so the shop comes from the
ownership-checked ``X-Shop-Id`` header and its tenant GUC is set for the
request. There is no ``shop_id`` parameter.

Response: ``{"as_of", "built_at", "ranking", "report"}`` where ``report`` is
exactly the ``report.json`` dict the shop diagnosis package produces -- the
contract the Phân tích screen renders. 404 when the shop has no report yet
(also the answer for any other shop's data: nothing here can name one).

``?ranking=60d`` (default) or ``30d`` picks the hero ranking mode; both are
built from the same snapshot by the daily job, so the switch costs nothing.

Read-only: it reads ``shop_diagnosis_reports`` rows and computes nothing live.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.services.shop_diagnosis import Ranking
from juli_backend.services.shop_diagnosis_daily import latest_shop_diagnosis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/analysis", tags=["demo"])


class DemoAnalysisResponse(BaseModel):
    as_of: date
    built_at: datetime
    ranking: str
    report: dict[str, Any]


@router.get("", response_model=DemoAnalysisResponse)
async def get_demo_analysis(
    ranking: Ranking = Query(Ranking.COMBINED_60D),
    session: AsyncSession = Depends(get_session),
    shop: Shop = Depends(get_active_shop),
) -> DemoAnalysisResponse:
    """The latest shop diagnosis report for the caller's own shop, or 404."""
    try:
        stored = await latest_shop_diagnosis(session, shop.id, ranking)
    except Exception:
        logger.exception("demo_analysis_read_failed", extra={"shop_id": str(shop.id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read the shop analysis",
        ) from None
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No analysis yet")
    logger.info(
        "demo_analysis_read",
        extra={"shop_id": str(shop.id), "as_of": stored.as_of.isoformat(), "ranking": ranking},
    )
    return DemoAnalysisResponse(
        as_of=stored.as_of, built_at=stored.built_at, ranking=stored.ranking, report=stored.report
    )

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

``GET /v1/demo/analysis/rankings?stream=&metric=`` (fast track P8-A, AC-8.1,
ADR-109 d.5) returns the latest stored ranking table for one stream × clickable
metric of the same shop, same guards: ``{"as_of", "built_at", "stream",
"metric", "ranking"}`` where ``ranking`` is the ``shop_diagnosis.rankings``
payload (stream figures, ``down`` / ``up`` rows, ``closing`` rows). 422 for a
metric that is not clickable on that stream (ADR-109 d.4), 404 when none is
stored.

Read-only: it reads ``shop_diagnosis_reports`` / ``shop_metric_rankings`` rows
and computes nothing live.
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
from juli_backend.services.shop_diagnosis import STREAM_METRICS, Channel, Metric, Ranking
from juli_backend.services.shop_diagnosis_daily import (
    latest_metric_ranking,
    latest_shop_diagnosis,
)

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


class DemoMetricRankingResponse(BaseModel):
    as_of: date
    built_at: datetime
    stream: str
    metric: str
    ranking: dict[str, Any]


@router.get("/rankings", response_model=DemoMetricRankingResponse)
async def get_demo_metric_ranking(
    stream: Channel = Query(...),
    metric: Metric = Query(...),
    session: AsyncSession = Depends(get_session),
    shop: Shop = Depends(get_active_shop),
) -> DemoMetricRankingResponse:
    """The latest ADR-109 ranking of ``stream`` × ``metric`` for the caller's own shop, or 404."""
    if metric not in STREAM_METRICS.get(stream, ()):
        raise HTTPException(
            status_code=422,  # the same code FastAPI uses for an invalid query
            detail=f"metric {metric.value!r} is not ranked on stream {stream.value!r}",
        )
    try:
        stored = await latest_metric_ranking(session, shop.id, stream, metric)
    except Exception:
        logger.exception("demo_metric_ranking_read_failed", extra={"shop_id": str(shop.id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read the metric ranking",
        ) from None
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ranking yet")
    logger.info(
        "demo_metric_ranking_read",
        extra={
            "shop_id": str(shop.id),
            "as_of": stored.as_of.isoformat(),
            "stream": stream.value,
            "metric": metric.value,
        },
    )
    return DemoMetricRankingResponse(
        as_of=stored.as_of,
        built_at=stored.built_at,
        stream=stored.stream,
        metric=stored.metric,
        ranking=stored.ranking,
    )

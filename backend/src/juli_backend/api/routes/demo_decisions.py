"""Public Demo Decisions read API (#718, B-6) — unauthenticated GET list/detail.

Unauthenticated, server-bound reference shop — same `DEMO_REFERENCE_SHOP_ID`
pattern as `GET /v1/demo/analytics` (#531) and
`POST /v1/demo/decisions/{id}/approve` (#717, B-5) via
`api.routes.demo_analytics.get_demo_reference_shop_id`. No `X-Shop-Id`
header, no bearer token, and no client-controllable `shop_id` anywhere — not
a query param (explicitly rejected, mirroring `GET /v1/demo/analytics`), not
a header (simply never read), not a path segment (none exists).

"Emission-gated" means `ActionCard.surfaced_at`-gated (#716, B-4): only the
active set `apply_emission_budget` most recently surfaced for the reference
shop is returned. A suppressed candidate, or a card belonging to any other
shop, is never distinguishable from a nonexistent id — detail lookup 404s
for all three cases identically (see `services/demo_decisions/read.py`).

This module never computes anything live — it only reads already-persisted
`ActionCard` rows (Postgres, sole source of truth per ADR-038). There is no
Redis dependency and no code path that turns a query failure into a
silently-invented empty list; an unhandled exception here surfaces as a
500, same pattern as `api/routes/action_cards.py` /
`api/routes/demo_execution.py`.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.demo_analytics import get_demo_reference_shop_id
from juli_backend.database import get_session
from juli_backend.services.demo_decisions import (
    DecisionNotFound,
    get_surfaced_decision,
    list_surfaced_decisions,
    mask_decision_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/decisions", tags=["demo"])


class DemoDecisionExpectedImpact(BaseModel):
    metric: str
    value: float
    confidence: str


class DemoDecisionReasoning(BaseModel):
    copy_source: str | None = None
    why: str | None = None
    expected_impact: str | None = None
    next_steps: list[str] = []
    source_kpi_ids: list[str] = []


class DemoDecisionRecommendation(BaseModel):
    workflow_name: str | None = None
    priority: int | None = None
    rationale: str | None = None
    expected_impact: DemoDecisionExpectedImpact | None = None
    preconditions_met: bool | None = None
    user_action_required: bool | None = None
    source_kpi_ids: list[str] = []
    reasoning: DemoDecisionReasoning | None = None


class DemoDecisionItem(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    severity: str
    priority: int
    computed_at: str | None = None
    surfaced_at: str | None = None
    recommendation: DemoDecisionRecommendation


class DemoDecisionListResponse(BaseModel):
    success: bool = True
    data: list[DemoDecisionItem]
    error: str | None = None


class DemoDecisionDetailResponse(BaseModel):
    success: bool = True
    data: DemoDecisionItem | None = None
    error: str | None = None


def _reject_visitor_shop_id(shop_id: str | None) -> None:
    if shop_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shop_id is not accepted on public demo endpoints",
        )


@router.get("", response_model=DemoDecisionListResponse)
async def list_demo_decisions(
    shop_id: str | None = Query(None, description="Rejected — reference shop is server-bound"),
    session: AsyncSession = Depends(get_session),
    reference_shop_id: uuid.UUID = Depends(get_demo_reference_shop_id),
) -> DemoDecisionListResponse:
    """Ranked, emission-gated active Decision set for the reference shop."""
    _reject_visitor_shop_id(shop_id)

    try:
        cards = await list_surfaced_decisions(session, reference_shop_id)
    except Exception:
        logger.exception(
            "demo_decisions_list_failed",
            extra={"reference_shop_id": str(reference_shop_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read demo decisions",
        ) from None

    items = [DemoDecisionItem(**mask_decision_payload(card)) for card in cards]
    logger.info(
        "demo_decisions_list_read",
        extra={"reference_shop_id": str(reference_shop_id), "count": len(items)},
    )
    return DemoDecisionListResponse(data=items)


@router.get("/{action_card_id}", response_model=DemoDecisionDetailResponse)
async def get_demo_decision(
    action_card_id: uuid.UUID,
    shop_id: str | None = Query(None, description="Rejected — reference shop is server-bound"),
    session: AsyncSession = Depends(get_session),
    reference_shop_id: uuid.UUID = Depends(get_demo_reference_shop_id),
) -> DemoDecisionDetailResponse:
    """Single emission-gated Decision. 404 (safe default) for a suppressed
    candidate, a nonexistent id, or a card belonging to another shop —
    tenant existence is never leaked through this endpoint."""
    _reject_visitor_shop_id(shop_id)

    try:
        card = await get_surfaced_decision(session, reference_shop_id, action_card_id)
    except DecisionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        ) from exc
    except Exception:
        logger.exception(
            "demo_decisions_detail_failed",
            extra={"reference_shop_id": str(reference_shop_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read demo decision",
        ) from None

    return DemoDecisionDetailResponse(data=DemoDecisionItem(**mask_decision_payload(card)))

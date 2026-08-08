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
Redis dependency and no code path that turns a *query* failure into a
silently-invented empty list; an unhandled exception from the `list`/`get`
query itself surfaces as a 500, same pattern as `api/routes/action_cards.py`
/ `api/routes/demo_execution.py`.

Row-level resilience (#718 Review finding 1): the list endpoint is
per-row resilient to a *persisted row* whose shape the strict response
schema rejects — one malformed `recommendation_payload` is dropped (logged,
never leaked) rather than 500ing the whole public feed, since a partial
result (every other row) is both safe and strictly better than none. The
detail endpoint is deliberately **not** row-resilient the same way: a
single lookup has no partial result to preserve, so a malformed row there
surfaces as a 500 rather than a misleading 404 (see
`get_demo_decision`'s docstring for the full reasoning).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.demo_analytics import get_demo_reference_shop_id
from juli_backend.database import get_session
from juli_backend.models.models import ActionCard
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


def _build_masked_item(card: ActionCard, reference_shop_id: uuid.UUID) -> DemoDecisionItem | None:
    """Validate one card's masked envelope against the strict typed response
    schema; return ``None`` (never raise) if the persisted payload doesn't
    match the expected shape.

    ``mask_decision_payload`` is an allowlist *copy*, not a type check — it
    happily forwards a key with the wrong shape (e.g. ``source_kpi_ids`` as
    a list of dicts instead of ``list[str]``). ``DemoDecisionItem``'s
    pydantic schema is what actually rejects that shape, which is the
    correct security outcome (nothing malformed is ever serialized into the
    public response). This function is what turns that rejection into a
    per-row drop instead of a whole-response 500 (#718 Review finding 1).

    Observable via a structured log carrying only ``reference_shop_id`` (the
    server-bound demo shop, never visitor-controlled) and the card's own
    opaque ``id`` plus a structural validation reason (field path + pydantic
    error type/message) — never the raw ``recommendation_payload``, never
    ``title``/``description`` (may carry seller content), and never
    ``workflow_key``, matching the no-PII/no-raw-payload/no-workflow_key
    discipline ``services/action_cards/emission_budget.py``'s suppression
    logging follows.
    """
    try:
        return DemoDecisionItem(**mask_decision_payload(card))
    except ValidationError as exc:
        logger.warning(
            "demo_decisions_row_dropped_invalid_shape",
            extra={
                "reference_shop_id": str(reference_shop_id),
                "action_card_id": str(card.id),
                "validation_errors": exc.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            },
        )
        return None


@router.get("", response_model=DemoDecisionListResponse)
async def list_demo_decisions(
    shop_id: str | None = Query(None, description="Rejected — reference shop is server-bound"),
    session: AsyncSession = Depends(get_session),
    reference_shop_id: uuid.UUID = Depends(get_demo_reference_shop_id),
) -> DemoDecisionListResponse:
    """Ranked, emission-gated active Decision set for the reference shop.

    Per-row resilient (#718 Review finding 1): a single persisted row whose
    ``recommendation_payload`` doesn't match the strict response schema is
    dropped — logged, never serialized, never leaked — rather than failing
    the entire feed. This is a public, unauthenticated surface; one
    malformed row must not blank out every other seller's legitimately
    surfaced Decision.
    """
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

    items = [
        item for card in cards if (item := _build_masked_item(card, reference_shop_id)) is not None
    ]
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
    tenant existence is never leaked through this endpoint.

    Deliberately *not* row-resilient like the list endpoint (#718 Review
    finding 1): a detail lookup has no partial result to preserve, so if the
    one row the caller asked for fails the strict response schema, there is
    nothing safe to "serve the rest of". Degrading that to a 404 would
    misrepresent a genuine data-integrity problem as "this Decision doesn't
    exist" — a strictly worse signal for on-call debugging than an honest,
    logged 500 (the caller already has this id from a prior list response,
    so 404 here would look like a resource that vanished, not one that's
    malformed). A malformed row is therefore surfaced through the same
    ``except Exception`` -> 500 contract as any other unexpected read
    failure on this route, not silently downgraded to 404.
    """
    _reject_visitor_shop_id(shop_id)

    try:
        card = await get_surfaced_decision(session, reference_shop_id, action_card_id)
        item = DemoDecisionItem(**mask_decision_payload(card))
    except DecisionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        ) from exc
    except Exception:
        logger.exception(
            "demo_decisions_detail_failed",
            extra={
                "reference_shop_id": str(reference_shop_id),
                "action_card_id": str(action_card_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read demo decision",
        ) from None

    return DemoDecisionDetailResponse(data=item)

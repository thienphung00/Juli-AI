"""Demo Decisions read API (#1283, AGT-W5A) — authenticated GET list/detail,
scoped to the caller's own shop.

**Posture changed here.** Originally (#718, B-6) these routes were
unauthenticated and resolved a server-bound `DEMO_REFERENCE_SHOP_ID` — same
pattern as `GET /v1/demo/analytics` (#531), via
`api.routes.demo_analytics.get_demo_reference_shop_id`. On the deployed host
that reference shop was a real merchant's production shop, so the routes
served a live seller's recommendations — titles, descriptions, rationales,
expected-impact figures — to any caller who could reach the URL, with no
credentials at all (#1283). Separately, the routes ignored `X-Shop-Id`
entirely while `POST /v1/demo/decisions/{id}/approve`
(`api/routes/demo_execution.py`) already honoured it via `get_active_shop` —
so a card a caller could *see* was not necessarily a card that caller could
*approve*.

Both problems close the same way: `get_current_user` + `get_active_shop`,
exactly the auth `POST /v1/demo/decisions/{id}/approve` already requires
(ADR-075 decision 3). ADR-075 decision 3 deliberately left these two
read-only routes as "P-UI's call" while bringing every route that can
create/watch/steer/confirm a run under auth; this is that call (#1283).
`get_demo_reference_shop_id` / `DEMO_REFERENCE_SHOP_ID` are no longer
involved on this surface — shop scope comes from the authenticated caller's
`X-Shop-Id` header, resolved and ownership-checked by `get_active_shop`, the
same channel every other authenticated `/v1/*` read route uses (e.g.
`api/routes/action_cards.py`, `api/routes/products.py`). There is no more
`shop_id` query param on either route — that guard existed specifically to
stop a caller from redirecting the old server-bound routes off the
reference shop, and its rationale evaporates once shop scope is a real,
ownership-checked per-caller value.

"Emission-gated" means `ActionCard.surfaced_at`-gated (#716, B-4): only the
active set `apply_emission_budget` most recently surfaced for the caller's
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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
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


def _build_masked_item(card: ActionCard, shop_id: uuid.UUID) -> DemoDecisionItem | None:
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

    Observable via a structured log carrying only ``shop_id`` (the
    authenticated caller's own shop, server-resolved from ``X-Shop-Id`` —
    never a raw request value) and the card's own opaque ``id`` plus a
    structural validation reason (field path + pydantic error type/message)
    — never the raw ``recommendation_payload``, never ``title``/
    ``description`` (may carry seller content), and never ``workflow_key``,
    matching the no-PII/no-raw-payload/no-workflow_key discipline
    ``services/action_cards/emission_budget.py``'s suppression logging
    follows.
    """
    try:
        return DemoDecisionItem(**mask_decision_payload(card))
    except ValidationError as exc:
        logger.warning(
            "demo_decisions_row_dropped_invalid_shape",
            extra={
                "shop_id": str(shop_id),
                "action_card_id": str(card.id),
                "validation_errors": exc.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            },
        )
        return None


@router.get("", response_model=DemoDecisionListResponse)
async def list_demo_decisions(
    session: AsyncSession = Depends(get_session),
    shop: Shop = Depends(get_active_shop),
) -> DemoDecisionListResponse:
    """Ranked, emission-gated active Decision set for the authenticated
    caller's own shop (resolved from ``X-Shop-Id`` via ``get_active_shop``,
    #1283).

    Per-row resilient (#718 Review finding 1): a single persisted row whose
    ``recommendation_payload`` doesn't match the strict response schema is
    dropped — logged, never serialized, never leaked — rather than failing
    the entire feed. One malformed row must not blank out every other
    legitimately surfaced Decision for this caller's shop.
    """
    shop_id = shop.id

    try:
        cards = await list_surfaced_decisions(session, shop_id)
    except Exception:
        logger.exception(
            "demo_decisions_list_failed",
            extra={"shop_id": str(shop_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read demo decisions",
        ) from None

    items = [item for card in cards if (item := _build_masked_item(card, shop_id)) is not None]
    logger.info(
        "demo_decisions_list_read",
        extra={"shop_id": str(shop_id), "count": len(items)},
    )
    return DemoDecisionListResponse(data=items)


@router.get("/{action_card_id}", response_model=DemoDecisionDetailResponse)
async def get_demo_decision(
    action_card_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    shop: Shop = Depends(get_active_shop),
) -> DemoDecisionDetailResponse:
    """Single emission-gated Decision for the authenticated caller's own
    shop (resolved from ``X-Shop-Id`` via ``get_active_shop``, #1283). 404
    (safe default) for a suppressed candidate, a nonexistent id, or a card
    belonging to another shop — tenant existence is never leaked through
    this endpoint.

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
    shop_id = shop.id

    try:
        card = await get_surfaced_decision(session, shop_id, action_card_id)
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
                "shop_id": str(shop_id),
                "action_card_id": str(action_card_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read demo decision",
        ) from None

    return DemoDecisionDetailResponse(data=item)

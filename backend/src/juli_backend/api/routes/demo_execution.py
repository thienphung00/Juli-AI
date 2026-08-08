"""Public Demo approve -> execute API (#717, B-5) — local dry-run records only.

Unauthenticated, server-bound reference shop — same `DEMO_REFERENCE_SHOP_ID`
pattern as `GET /v1/demo/analytics` (#531). No `X-Shop-Id` header, no bearer
token, and no TikTok credentials are ever required (ADR-037 Demo no-auth,
ADR-038 §9 dry-run). This is the write counterpart to the (not-yet-built,
#718 B-6) public Demo Decisions read API — this module owns only the approve
action's record/state, not a Decisions listing/detail read surface.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.demo_analytics import get_demo_reference_shop_id
from juli_backend.database import get_session
from juli_backend.services.demo_execution import (
    DecisionNotFound,
    approve_decision_dry_run,
    narrative_steps,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/decisions", tags=["demo"])


class DemoExecutionNarrativeStep(BaseModel):
    state: str
    message: str
    at: str


class DemoDecisionApproveData(BaseModel):
    execution_id: uuid.UUID
    action_card_id: uuid.UUID
    status: str
    narrative: list[DemoExecutionNarrativeStep]


class DemoDecisionApproveResponse(BaseModel):
    success: bool = True
    data: DemoDecisionApproveData | None = None
    error: str | None = None


@router.post("/{action_card_id}/approve", response_model=DemoDecisionApproveResponse)
async def approve_demo_decision(
    action_card_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    reference_shop_id: uuid.UUID = Depends(get_demo_reference_shop_id),
) -> DemoDecisionApproveResponse:
    """Approve a Decision on public Demo and run its dry-run execution.

    Never calls a real Partner write client and never requires Partner auth —
    see `services/demo_execution/MODULE.md` and
    `tests/unit/test_demo_execution_import_boundary.py` (AC3) for the static
    guarantee behind that.
    """
    try:
        record = await approve_decision_dry_run(
            session,
            shop_id=reference_shop_id,
            action_card_id=action_card_id,
        )
        await session.commit()
    except DecisionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        ) from exc
    except Exception:
        logger.exception(
            "demo_decision_approve_failed",
            extra={"reference_shop_id": str(reference_shop_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve decision",
        ) from None

    return DemoDecisionApproveResponse(
        data=DemoDecisionApproveData(
            execution_id=record.id,
            action_card_id=record.action_card_id,
            status=record.status,
            narrative=[DemoExecutionNarrativeStep(**step) for step in narrative_steps(record)],
        )
    )

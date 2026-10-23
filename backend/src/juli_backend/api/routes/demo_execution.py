"""Approve-is-run-creation -- POST /v1/demo/decisions/{action_card_id}/approve
(ADR-075 decision 1, ADR-082, #1222).

**Retired here (owner decision 2026-08-21, parent-cache Option A).** This
route used to be public/unauthenticated dry-run record creation (#717, B-5):
it called `services.demo_execution.approve_decision_dry_run`, flipped the
card, created a `DemoExecutionRecord`, and drove it `queued -> running ->
done` synchronously in-process -- never a real `workflow_runs` row, never
`run_agent_workflow.delay(...)`. Approve-is-run-creation TAKES OVER this
route; the dry-run behaviour on this path is retired. `services.
demo_execution` itself (module, table, tests) is left in place, registered
but unreachable from HTTP -- see `services/demo_execution/MODULE.md`'s
"Routing note" section (updated by #1222) for why deleting it outright was
rejected.

This is now real, authenticated run creation: `get_current_user` +
`get_active_shop`, the exact auth every other agent route already requires
(ADR-075 decision 3) -- `#1217` deliberately left this one route
unauthenticated because bringing it under auth was always this slice's job.
The transaction itself (verify + flip + derive product + insert run +
insert audit row) lives in `services/agent/approval.py`, not here and not in
`services/demo_execution/` (see that module's own docstring for the import-
boundary reason) -- this route is a thin translation of
`approval_module.approve_action_card`'s three fail-closed exceptions plus
`IntegrityError` into HTTP responses, then the post-commit
`run_agent_workflow` enqueue (issue #1145 Gap 2's ordering: never before the
commit that makes the run id real).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.reviewer import audit_reviewer_run_action, reviewer_context
from juli_backend.api.routes.agent_runs import _enqueue_run_agent_workflow
from juli_backend.api.routes.demo_run_changes import SellerReasonRequest, invalid_reason
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.models.decision_reasons import ACTION_REJECT
from juli_backend.models.history import PHASE_APPROVAL
from juli_backend.repositories import utc_now_naive
from juli_backend.services import card_events, decision_reasons
from juli_backend.services.agent import abuse_limits as agent_abuse_limits
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.demo_decisions import DecisionNotFound, get_surfaced_decision
from juli_backend.services.ops import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/decisions", tags=["demo"])


class DemoDecisionApproveData(BaseModel):
    run_id: uuid.UUID
    action_card_id: uuid.UUID
    product_id: uuid.UUID
    status: str
    celery_task_id: str


class DemoDecisionApproveResponse(BaseModel):
    success: bool = True
    data: DemoDecisionApproveData | None = None
    error: str | None = None


def _enqueue_approval_baseline(shop_id: uuid.UUID, run_id: uuid.UUID) -> str | None:
    """Imported lazily so the Celery app is not a route import (like ``agent_runs``)."""
    from juli_backend.workers.tasks import product_history as product_history_tasks

    return product_history_tasks.enqueue_run_baseline(
        shop_id, run_id, PHASE_APPROVAL, utc_now_naive()
    )


@router.post(
    "/{action_card_id}/approve",
    response_model=DemoDecisionApproveResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_writable_shop)],
)
async def approve_demo_decision(
    action_card_id: uuid.UUID,
    request: Request,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DemoDecisionApproveResponse:
    """Approve is run creation, atomically (ADR-075 decision 1).

    404 -- cross-tenant card and nonexistent card alike (no existence
    oracle, never 403). 409 -- a non-`active` card (covers a sequential or
    concurrent double-approve: the loser always finds the card already
    flipped), a shop with zero `products` to bind the run to (ADR-082
    decision 4), a card whose `workflow_key` has no registered playbook
    (ADR-084 decision 3), or a raced concurrent second active run for the
    derived product (`uq_workflow_runs_active_shop_product`, translated the
    same way `agent_runs.py::create_run` already did before this route
    replaced it as the run-creation path). `202` with the created run's id,
    its derived `product_id`, and the Celery task id on success.
    """
    shop_id = shop.id

    # ADR-075 decision 4 / #1223: approve is run creation, so it carries the
    # "approve / run creation" bucket -- 5/hour, burst 2, per shop, checked
    # before the ActionCard is even resolved (an attacker probing
    # nonexistent card ids must still be throttled, not just successful
    # approvals). Cancel (`api/routes/agent_runs.py::cancel_run`) never
    # calls this module at all -- see `services.agent.abuse_limits`'s own
    # docstring for why that exemption is structural, not a fail-open
    # branch here.
    limit_decision = await agent_abuse_limits.get_agent_abuse_limit_gate().try_acquire_approve(
        str(shop_id)
    )
    if not limit_decision.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop_id),
            operation=agent_abuse_limits.OPERATION_APPROVE,
            retry_after_seconds=limit_decision.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many approve requests for this shop; "
                f"retry in {limit_decision.retry_after_seconds}s"
            ),
            headers={"Retry-After": str(limit_decision.retry_after_seconds)},
        )

    try:
        result = await approval_module.approve_action_card(
            session,
            shop_id=shop_id,
            action_card_id=action_card_id,
            approved_by_user_id=user.id,
            # P64 (D73.3): "Tạo sản phẩm" exists only for a partner reviewer, whose run
            # routes are reachable only on the writable sandbox pin (``api/reviewer.py``).
            allow_create_product=reviewer_context(request) is not None,
        )
        # P64 (D73.4): a reviewer's Duyệt on the sandbox pin is this same approve.
        await audit_reviewer_run_action(
            session,
            request,
            audit.ACTION_REVIEWER_SANDBOX_APPROVE,
            shop_id=shop_id,
            after={
                "action_card_id": str(action_card_id),
                "run_id": str(result.run_id),
                "workflow_key": result.workflow_key,
            },
        )
        await session.commit()
    except approval_module.ActionCardNotFound as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        ) from exc
    except approval_module.ActionCardNotActive as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision is not active",
        ) from exc
    except approval_module.CardSubjectNotApprovable as exc:
        # Replaces the NoProductsForShop branch (issue #1702): approve no
        # longer derives a product from the shop, so "this shop has no
        # products" stopped being a reason it can fail. The card's own
        # subject is now the binding, and a card that carries none is
        # refused with this 409 instead. Same status code, different and
        # honest reason.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This decision has no subject Juli can act on",
        ) from exc
    except approval_module.CreateProductDailyCapReached as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "create_product_daily_cap",
                "cap": approval_module.CREATE_PRODUCT_DAILY_CAP,
            },
        ) from exc
    except approval_module.CreatePromotionDailyCapReached as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "create_promotion_daily_cap",
                "cap": approval_module.CREATE_PROMOTION_DAILY_CAP,
            },
        ) from exc
    except approval_module.WorkflowNotExecutable as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This decision's workflow cannot be executed by Juli",
        ) from exc
    except IntegrityError:
        await session.rollback()
        # The one state-mutating conflict branch here that would otherwise
        # leave no trace -- an operator would go looking for exactly this
        # event. No token/credential/PII fields; shop_id/action_card_id are
        # both server-resolved identifiers, never request-body free text.
        logger.warning(
            "agent_run_approve_conflict",
            extra={"shop_id": str(shop_id), "action_card_id": str(action_card_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active run already exists for the bound product",
        ) from None

    celery_task_id = _enqueue_run_agent_workflow(result.run_id)
    # Fast track P23 (D30.1c): the approval baseline, captured off the request
    # (no extra query here); never fails the approval.
    _enqueue_approval_baseline(shop_id, result.run_id)

    logger.info(
        "agent_run_approved",
        extra={
            "shop_id": str(shop_id),
            "action_card_id": str(action_card_id),
            "run_id": str(result.run_id),
            "product_id": str(result.product_id),
            "celery_task_id": celery_task_id,
        },
    )

    return DemoDecisionApproveResponse(
        data=DemoDecisionApproveData(
            run_id=result.run_id,
            action_card_id=result.action_card_id,
            product_id=result.product_id,
            status=result.status,
            celery_task_id=celery_task_id,
        )
    )


# -- "Từ chối" (fast track P10-A, contract p10-quyet-dinh.md §2) ----------------


class DecisionRejectResponse(BaseModel):
    status: str
    cooldown_until: str


@router.post("/{action_card_id}/reject", response_model=DecisionRejectResponse)
async def reject_demo_decision(
    action_card_id: uuid.UUID,
    body: SellerReasonRequest,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionRejectResponse:
    """ "Từ chối" a surfaced card: store the reason, take the card off the desk.

    422 for a missing/unknown ``reason_code`` or a note over 300 characters;
    404 for another shop's card, a card not on the desk, or no such card. The
    same lever is not proposed again for that product for 7 days -- strictly,
    D24.21 (``services.decision_reasons``).

    IDEMPOTENT (fast track P61-D): rejecting a card this shop already rejected
    answers 200 with the first reject's status and cooldown, and writes nothing
    (no second reason row, no second ``dismissed`` event) -- a retried request
    or a double tap is not an error. The card row is locked before it is closed,
    so two concurrent rejects cannot both record.
    """
    try:
        decision_reasons.validate_reason(ACTION_REJECT, body.reason_code, body.note)
    except decision_reasons.InvalidReason as exc:
        raise invalid_reason(exc) from None
    try:
        card = await get_surfaced_decision(session, shop.id, action_card_id)
        # Re-read under a row lock: a concurrent reject that committed first
        # leaves this one looking at a closed card, answered as a repeat below.
        await session.refresh(card, with_for_update=True)
        if card.status == decision_reasons.DISMISSED_CARD_STATUS:
            raise DecisionNotFound(str(action_card_id))
    except DecisionNotFound:
        prior = await decision_reasons.card_reject_reason(session, shop.id, action_card_id)
        if prior is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found"
            ) from None
        logger.info(
            "demo_decision_reject_repeated",
            extra={"shop_id": str(shop.id), "action_card_id": str(action_card_id)},
        )
        return DecisionRejectResponse(
            status="rejected", cooldown_until=decision_reasons.cooldown_until_iso(prior)
        )
    reason = await decision_reasons.record_reason(
        session,
        shop_id=shop.id,
        action=ACTION_REJECT,
        reason_code=body.reason_code,
        note=body.note,
        decided_by_user_id=user.id,
        card=card,
        product_id=decision_reasons.product_id_of(card),
    )
    decision_reasons.close_card(card)
    # Fast track P60-1a: the card log's `dismissed` row (never raises).
    await card_events.record_dismissed(
        session,
        card,
        occurred_at=card.dismissed_at or datetime.now(UTC),
        decision_reason_code=body.reason_code,
        decision_reason_id=reason.id,
    )
    await session.commit()
    logger.info(
        "demo_decision_rejected",
        extra={
            "shop_id": str(shop.id),
            "action_card_id": str(action_card_id),
            "reason_code": body.reason_code,
            "lever_code": reason.lever_code,
        },
    )
    return DecisionRejectResponse(
        status="rejected", cooldown_until=decision_reasons.cooldown_until_iso(reason)
    )

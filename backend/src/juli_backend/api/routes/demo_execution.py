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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.agent_runs import _enqueue_run_agent_workflow
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services.agent import abuse_limits as agent_abuse_limits
from juli_backend.services.agent import approval as approval_module

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


@router.post(
    "/{action_card_id}/approve",
    response_model=DemoDecisionApproveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_demo_decision(
    action_card_id: uuid.UUID,
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
    except approval_module.NoProductsForShop as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shop has no products to bind this run to",
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

"""Agent run transport routes: SSE event stream, cancel, confirmation
decisions, and the polled run list (ADR-074, ADR-075, ADR-083).

This module is the HTTP skin. It resolves the tenant, applies the abuse-limit
gates, translates service outcomes into status codes, and enqueues Celery
work. The behaviour -- stream ordering, the consent-binding ladder, the read
model -- lives in ``services.agent_runs`` and is tested there without HTTP.

Two rules every handler here follows:

* **Tenant scoping first, and it 404s.** A run belonging to another shop is
  reported as missing, never forbidden -- no existence oracle (ADR-074
  decision 5). :func:`_resolve_owned_run` is the one place that check lives.
* **Cancel is never throttled.** The abuse-limit gates apply to the stream
  (a concurrency slot) and to confirmation decisions (a rate bucket). Cancel
  asks no gate at all, by construction (ADR-075 decision 4).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.database.database import ensure_worker_session_factory
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services import agent_runs
from juli_backend.services.agent import abuse_limits as agent_abuse_limits
from juli_backend.services.agent_runs import (
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DEFAULT_POLL_INTERVAL_S,
    ERROR_CONFIRMATION_ALREADY_DECIDED,
    ERROR_CONFIRMATION_EXPIRED,
    ERROR_CONFIRMATION_NOT_FOUND,
    ERROR_INVALID_DECISION,
    ERROR_OPTION_ID_REQUIRED,
    ERROR_PARAMS_SHA_MISMATCH,
    ERROR_RUN_NOT_AWAITING_CONFIRMATION,
    ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
    ERROR_UNKNOWN_OPTION_ID,
    TERMINAL_EVENT_TYPES,
    TERMINAL_RUN_STATUSES,
    EventSubscriber,
    event_stream,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/runs", tags=["agent-runs"])


# -- dependencies (each overridable via app.dependency_overrides) --------------


async def get_run_events_session_factory() -> async_sessionmaker[AsyncSession]:
    """Sessions for the stream's own reads; the request session closes too early."""
    return ensure_worker_session_factory(agent_runs.run_events_database_url())


def get_run_event_subscriber() -> EventSubscriber | None:
    return agent_runs.resolve_redis_event_subscriber()


def get_heartbeat_interval_s() -> float:
    return DEFAULT_HEARTBEAT_INTERVAL_S


def get_poll_interval_s() -> float:
    return DEFAULT_POLL_INTERVAL_S


# -- shared pieces -------------------------------------------------------------


async def _resolve_owned_run(
    run_id: uuid.UUID, shop: Shop, session: AsyncSession
) -> WorkflowRunRow:
    """404 for a missing run *and* for another shop's run (ADR-074 decision 5)."""
    run = await session.get(WorkflowRunRow, run_id)
    if run is None or run.shop_id != shop.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _too_many_requests(detail: str, retry_after_seconds: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"{detail}; retry in {retry_after_seconds}s",
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _enqueue_run_agent_workflow(run_id: uuid.UUID) -> str:
    """Enqueue ``run_agent_workflow``. Imported lazily so the Celery app is not a route import."""
    from juli_backend.workers.tasks import agent_workflow as agent_workflow_tasks

    return agent_workflow_tasks.run_agent_workflow.delay(str(run_id)).id


def _enqueue_resume_agent_workflow(run_id: uuid.UUID, *, approved: bool) -> str:
    from juli_backend.workers.tasks import agent_workflow as agent_workflow_tasks

    return agent_workflow_tasks.resume_agent_workflow.delay(str(run_id), approved).id


async def _sse_stream_with_concurrency_slot(
    generator: AsyncIterator[str],
    *,
    gate: agent_abuse_limits.AbuseLimitGate,
    shop_id: str,
) -> AsyncIterator[str]:
    """Release the SSE concurrency slot on every exit path (ADR-075 decision 4).

    A clean end and a run terminating mid-stream both exit through ``finally``
    synchronously. A client disconnect does not: Starlette abandons the
    generator at its last ``yield`` and release waits for the async-generator
    GC finalizer, which is real but not prompt. The gate's one-hour safety TTL
    on the slot bounds that case. ``test_agent_abuse_limits_routes.py`` proves
    the cancellation path by cancelling the consuming task, the mechanism the
    legacy ASGI path actually uses.
    """
    try:
        async for chunk in generator:
            yield chunk
    finally:
        await gate.release_stream(shop_id)


# -- routes --------------------------------------------------------------------


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_run_events_session_factory),
    subscriber: EventSubscriber | None = Depends(get_run_event_subscriber),
    heartbeat_interval_s: float = Depends(get_heartbeat_interval_s),
    poll_interval_s: float = Depends(get_poll_interval_s),
) -> StreamingResponse:
    run = await _resolve_owned_run(run_id, shop, session)

    # The slot is acquired only after tenant scoping: a 404 for someone else's
    # run must never consume one.
    gate = agent_abuse_limits.get_agent_abuse_limit_gate()
    slot = await gate.try_acquire_stream(str(shop.id))
    if not slot.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_SSE,
            retry_after_seconds=slot.retry_after_seconds,
        )
        raise _too_many_requests(
            "Too many concurrent event streams for this shop", slot.retry_after_seconds
        )

    generator = event_stream(
        run_id=run_id,
        after_seq=agent_runs.resolve_after_seq(request.headers.get("last-event-id"), after),
        run_is_terminal=run.status in TERMINAL_RUN_STATUSES,
        session_factory=session_factory,
        subscriber=subscriber,
        heartbeat_interval_s=heartbeat_interval_s,
        poll_interval_s=poll_interval_s,
    )
    # X-Accel-Buffering pairs with the stream's immediate first byte (#1292)
    # so nginx/Cloudflare never hold the response back.
    return StreamingResponse(
        _sse_stream_with_concurrency_slot(generator, gate=gate, shop_id=str(shop.id)),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Idempotent 202: sets ``cancel_requested`` unconditionally once the run resolves.

    Repeating the call, or cancelling a terminal run, is a harmless no-op write.
    The runner's ``cancel_check`` reads the column fresh on every checkpoint.
    """
    run = await _resolve_owned_run(run_id, shop, session)
    run.cancel_requested = True
    await session.commit()
    logger.info(
        "agent_run_cancel_requested", extra={"shop_id": str(shop.id), "run_id": str(run_id)}
    )


class ConfirmationDecisionRequest(BaseModel):
    decision: str
    option_id: str | None = None


class ConfirmationDecisionResponse(BaseModel):
    decision: str
    status: str
    celery_task_id: str


@router.post(
    "/{run_id}/confirmations/{tool_call_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ConfirmationDecisionResponse,
)
async def submit_confirmation_decision(
    run_id: uuid.UUID,
    tool_call_id: str,
    body: ConfirmationDecisionRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ConfirmationDecisionResponse:
    """Authorise and record a seller's decision, then enqueue the resume.

    Errors from the ladder carry ``{"detail": {"message", "error_code"}}`` so
    a client can tell "retry later" from "already decided" from "refused".
    """
    # Rate-limited before the run is even resolved: probing tool_call_ids on
    # runs one does not own must be throttled too.
    limit = await agent_abuse_limits.get_agent_abuse_limit_gate().try_acquire_confirmation(
        str(shop.id)
    )
    if not limit.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_CONFIRMATION,
            retry_after_seconds=limit.retry_after_seconds,
        )
        raise _too_many_requests(
            "Too many confirmation decisions for this shop", limit.retry_after_seconds
        )

    run = await _resolve_owned_run(run_id, shop, session)
    try:
        outcome = await agent_runs.decide_confirmation(
            session,
            run,
            tool_call_id=tool_call_id,
            decision=body.decision,
            option_id=body.option_id,
        )
    except agent_runs.ConfirmationRejected as rejected:
        raise HTTPException(
            status_code=rejected.http_status,
            detail={"message": rejected.message, "error_code": rejected.error_code},
        ) from None

    # Commit before enqueue: a worker must never see the row still pending (#1221).
    await session.commit()
    celery_task_id = _enqueue_resume_agent_workflow(run_id, approved=outcome.approved)

    logger.info(
        "agent_confirmation_decided",
        extra={
            "shop_id": str(shop.id),
            "run_id": str(run_id),
            "tool_call_id": tool_call_id,
            "decision": body.decision,
            "celery_task_id": celery_task_id,
        },
    )
    return ConfirmationDecisionResponse(
        decision=body.decision, status=outcome.new_status, celery_task_id=celery_task_id
    )


class PendingDecisionSummary(BaseModel):
    tool_call_id: str
    expires_at: str


class WorkflowRunListItem(BaseModel):
    id: uuid.UUID
    status: str
    stop_reason: str | None = None
    product_name: str
    created_at: str
    completed_at: str | None = None
    running_seconds_elapsed: int
    latest_narration: str | None = None
    decision_summary: PendingDecisionSummary | None = None


class WorkflowRunListResponse(BaseModel):
    success: bool = True
    data: list[WorkflowRunListItem]


@router.get("", response_model=WorkflowRunListResponse)
async def list_demo_runs(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=1000),
) -> WorkflowRunListResponse:
    """Polled read model over the shop's runs, newest first (ADR-083 T4).

    A read failure degrades to an empty list rather than a 5xx: the client
    polls, and the next poll will show the rows (#1310).
    """
    try:
        items = await agent_runs.list_runs(session, shop.id, limit=limit)
    except Exception:  # read-model boundary: degrade to empty rather than 5xx a poll
        logger.exception("agent_runs_list_failed", extra={"shop_id": str(shop.id)})
        return WorkflowRunListResponse(data=[])

    logger.info("agent_runs_list_read", extra={"shop_id": str(shop.id), "count": len(items)})
    return WorkflowRunListResponse(
        data=[
            WorkflowRunListItem(
                id=item.id,
                status=item.status,
                stop_reason=item.stop_reason,
                product_name=item.product_name,
                created_at=item.created_at,
                completed_at=item.completed_at,
                running_seconds_elapsed=item.running_seconds_elapsed,
                latest_narration=item.latest_narration,
                decision_summary=(
                    PendingDecisionSummary(
                        tool_call_id=item.decision_summary.tool_call_id,
                        expires_at=item.decision_summary.expires_at,
                    )
                    if item.decision_summary is not None
                    else None
                ),
            )
            for item in items
        ]
    )


# Re-exported for callers and tests that import the transport vocabulary from the route.
__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "DEFAULT_POLL_INTERVAL_S",
    "ERROR_CONFIRMATION_ALREADY_DECIDED",
    "ERROR_CONFIRMATION_EXPIRED",
    "ERROR_CONFIRMATION_NOT_FOUND",
    "ERROR_INVALID_DECISION",
    "ERROR_OPTION_ID_REQUIRED",
    "ERROR_PARAMS_SHA_MISMATCH",
    "ERROR_RUN_NOT_AWAITING_CONFIRMATION",
    "ERROR_RUN_STATE_NOT_RECONSTRUCTABLE",
    "ERROR_UNKNOWN_OPTION_ID",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_RUN_STATUSES",
    "EventSubscriber",
    "cancel_run",
    "event_stream",
    "get_heartbeat_interval_s",
    "get_poll_interval_s",
    "get_run_event_subscriber",
    "get_run_events_session_factory",
    "list_demo_runs",
    "router",
    "stream_run_events",
    "submit_confirmation_decision",
]

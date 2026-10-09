"""What a run changed, and "Hoàn tác" (fast track P8-C, AC-8.3, ADR-109 d.9/d.11).

- ``GET  /v1/demo/runs/{run_id}/changes`` -- per field, the value before and
  after the run's writes; whether a revert is available (and the Vietnamese
  reason when it is not); the run's revert runs; its day-7 question.
- ``POST /v1/demo/runs/{run_id}/revert`` -- start a revert run. 202 with the new
  run's id; its progress is the ordinary SSE stream
  (``GET /v1/demo/runs/{new_run_id}/events``) and it pauses for the ordinary
  confirmation (``POST /v1/demo/runs/{new_run_id}/confirmation``) before
  writing anything. 409 ``{"detail": {"code", "message", "fields"}}`` when the
  run cannot be reverted -- ``message`` is Vietnamese, for the seller.
- ``GET  /v1/demo/revert-questions`` -- open "Hoàn tác?" questions for the shop.
- ``POST /v1/demo/revert-questions/{id}/dismiss`` -- the seller keeps the change.

Auth and tenant scope as every ``/v1/demo`` route: ``get_current_user`` +
``get_active_shop`` (ownership-checked ``X-Shop-Id``). Another shop's run or
question is a 404, never a 403.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.agent_runs import _enqueue_run_agent_workflow
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import run_changes
from juli_backend.services.agent import abuse_limits as agent_abuse_limits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

_ACTIVE_RUN_MESSAGE_VI = (
    "Sản phẩm này đang có một lượt chạy khác. Hãy chờ lượt đó kết thúc rồi hoàn tác."
)


def get_live_product_reader() -> run_changes.LiveProductReader:
    """The TikTok read behind the S-FR-8 check; overridden in tests."""
    return run_changes.read_live_product


# -- response models -------------------------------------------------------------


class FieldChangeItem(BaseModel):
    field: str
    label: str
    #: Text fields carry the text; ``main_images`` carries ``{"count": n}``;
    #: ``price`` carries ``[{"sku_id", "amount", "currency"}]``.
    before: Any
    after: Any
    after_source: str
    recorded_at: datetime | None


class RevertRunItem(BaseModel):
    run_id: uuid.UUID
    status: str
    stop_reason: str | None


class RevertAvailability(BaseModel):
    available: bool
    reason_code: str | None = None
    message: str | None = None
    runs: list[RevertRunItem]


class BreachItem(BaseModel):
    metric: str
    impact_pct: float
    band_pct: float


class RevertQuestionItem(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    status: str
    breaches: list[BreachItem]
    created_at: datetime | None
    revert_run_id: uuid.UUID | None


class RunChangesResponse(BaseModel):
    run_id: uuid.UUID
    reverts_run_id: uuid.UUID | None
    changes: list[FieldChangeItem]
    revert: RevertAvailability
    question: RevertQuestionItem | None


class RevertStartedData(BaseModel):
    run_id: uuid.UUID
    reverts_run_id: uuid.UUID
    product_id: uuid.UUID | None
    status: str
    fields: list[str]
    celery_task_id: str


class RevertStartedResponse(BaseModel):
    success: bool = True
    data: RevertStartedData


class RevertQuestionListResponse(BaseModel):
    success: bool = True
    data: list[RevertQuestionItem]


# -- helpers ---------------------------------------------------------------------


def _display_value(field: str, value: Any) -> Any:
    if field == "main_images":
        return {"count": len(value) if isinstance(value, list) else 0}
    return value


def _question_item(question: Any) -> RevertQuestionItem:
    return RevertQuestionItem(
        id=question.id,
        run_id=question.workflow_run_id,
        status=question.status,
        breaches=[BreachItem(**breach) for breach in question.breaches or []],
        created_at=question.created_at,
        revert_run_id=question.revert_run_id,
    )


def _refused(exc: run_changes.RevertRefused) -> HTTPException:
    code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if exc.code == "live_read_failed"
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.message_vi, "fields": list(exc.fields)},
    )


# -- routes ----------------------------------------------------------------------


@router.get("/runs/{run_id}/changes", response_model=RunChangesResponse)
async def get_run_changes(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> RunChangesResponse:
    """Before/after per field for one of the caller's runs, and its revert state."""
    try:
        run = await run_changes.get_owned_run(session, shop.id, run_id)
    except run_changes.RevertRunNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from None
    changes = await run_changes.load_run_changes(session, shop.id, run.id)
    reason = await run_changes.revert_block_reason(session, run, changes)
    reverts = await run_changes.revert_runs_of(session, shop.id, run.id)
    question = await run_changes.question_for_run(session, shop.id, run.id)
    message = run_changes.refusal_message(reason) if reason is not None else None
    return RunChangesResponse(
        run_id=run.id,
        reverts_run_id=run.reverts_run_id,
        changes=[
            FieldChangeItem(
                field=change.field,
                label=run_changes.FIELD_LABELS_VI.get(change.field, change.field),
                before=_display_value(change.field, change.before),
                after=_display_value(change.field, change.after),
                after_source=change.after_source,
                recorded_at=change.recorded_at,
            )
            for change in changes
        ],
        revert=RevertAvailability(
            available=reason is None,
            reason_code=reason,
            message=message,
            runs=[
                RevertRunItem(run_id=r.id, status=r.status, stop_reason=r.stop_reason)
                for r in reverts
            ],
        ),
        question=_question_item(question) if question is not None else None,
    )


@router.post(
    "/runs/{run_id}/revert",
    response_model=RevertStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run_revert(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    read_live_product: run_changes.LiveProductReader = Depends(get_live_product_reader),
) -> RevertStartedResponse:
    """Start a "Hoàn tác" run (see module docstring). Throttled like approve."""
    limit = await agent_abuse_limits.get_agent_abuse_limit_gate().try_acquire_approve(str(shop.id))
    if not limit.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_APPROVE,
            retry_after_seconds=limit.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many run requests for this shop; retry in {limit.retry_after_seconds}s",
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )
    try:
        started = await run_changes.start_revert(
            session,
            shop_id=shop.id,
            run_id=run_id,
            started_by_user_id=user.id,
            read_live_product=read_live_product,
        )
        await session.commit()
    except run_changes.RevertRunNotFound:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from None
    except run_changes.RevertRefused as exc:
        await session.rollback()
        logger.info(
            "run_revert_refused",
            extra={"shop_id": str(shop.id), "run_id": str(run_id), "code": exc.code},
        )
        raise _refused(exc) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "active_run_exists", "message": _ACTIVE_RUN_MESSAGE_VI, "fields": []},
        ) from None

    celery_task_id = _enqueue_run_agent_workflow(started.run_id)
    logger.info(
        "run_revert_started",
        extra={
            "shop_id": str(shop.id),
            "run_id": str(started.run_id),
            "reverts_run_id": str(started.reverts_run_id),
            "fields": list(started.fields),
        },
    )
    return RevertStartedResponse(
        data=RevertStartedData(
            run_id=started.run_id,
            reverts_run_id=started.reverts_run_id,
            product_id=started.product_id,
            status=started.status,
            fields=list(started.fields),
            celery_task_id=celery_task_id,
        )
    )


@router.get("/revert-questions", response_model=RevertQuestionListResponse)
async def list_revert_questions(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> RevertQuestionListResponse:
    """The shop's open day-7 "Hoàn tác?" questions, newest first."""
    questions = await run_changes.list_open_questions(session, shop.id)
    return RevertQuestionListResponse(data=[_question_item(q) for q in questions])


@router.post("/revert-questions/{question_id}/dismiss", response_model=RevertQuestionItem)
async def dismiss_revert_question(
    question_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> RevertQuestionItem:
    """The seller keeps the change; the question closes."""
    try:
        question = await run_changes.dismiss_question(session, shop.id, question_id)
        await session.commit()
    except run_changes.QuestionNotFound:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Question not found"
        ) from None
    return _question_item(question)

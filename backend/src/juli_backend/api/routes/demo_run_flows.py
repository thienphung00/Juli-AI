"""Cover-image, Seller Center promotion and Đo lường routes (fast track P10-B, AC-10.2).

Contract ``fasttrack/contracts/p10-quyet-dinh.md`` §4-§6:

- ``GET  /v1/demo/runs/{run_id}`` -- one run, with ``awaiting`` (``photo`` /
  ``seller_action`` / ``null``) and the flow's photos or promotion.
- ``POST /v1/demo/runs/{run_id}/photo`` -- multipart ``file`` (JPG/PNG ≤ 5 MB).
  202 ``{checks}`` and the run continues to the consent step; 422 with the same
  list when a check fails (the run keeps waiting); 409 when the run is not
  waiting for a photo.
- ``GET  /v1/demo/photos/{shop_id}/{token}`` -- the stored before/after photo.
  No auth header (an ``<img>`` cannot send one): the random token is the
  capability; the shop id only scopes the lookup.
- ``GET  /v1/demo/runs/{run_id}/instructions`` -- the Seller Center steps (VI).
- ``POST /v1/demo/runs/{run_id}/applied`` -- "Tôi đã áp dụng": 202, the run
  verifies read-only on TikTok (``tool.*`` events); not found -> it keeps
  waiting with "Chưa tìm thấy trên TikTok".
- ``GET  /v1/demo/runs/{run_id}/measurement`` -- target, bands, day 7, day 14.

Same auth and tenant scope as every ``/v1/demo`` route (``get_active_shop``);
another shop's run is a 404, never a 403.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services import agent_runs, lever_flows
from juli_backend.services.agent import abuse_limits as agent_abuse_limits
from juli_backend.services.content_cards import measurement as content_measurement
from juli_backend.services.content_cards import run_state as content_run_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

#: Multipart overhead allowed above the 5 MB file limit before the body is read.
_BODY_SLACK = 64 * 1024

_NOT_AWAITING_PHOTO_VI = "Lượt chạy này không chờ ảnh từ bạn."
_NOT_AWAITING_SELLER_VI = "Lượt chạy này không chờ bạn áp dụng khuyến mãi."
_NOT_PROMOTION_VI = "Lượt chạy này không phải khuyến mãi trên Seller Center."
_NO_PROPOSAL_VI = "Juli chưa soạn xong hướng dẫn. Bạn thử lại sau ít giây."
_TOO_MANY_CHECKS_VI = (
    "Juli đã kiểm tra nhiều lần mà chưa thấy khuyến mãi. Bạn kiểm tra lại trên Seller Center."
)


def _enqueue_resume_lever_flow(run_id: uuid.UUID) -> str:
    """Enqueue ``resume_lever_flow``; imported lazily so Celery is not a route import."""
    from juli_backend.workers.tasks import agent_workflow as agent_workflow_tasks

    return agent_workflow_tasks.resume_lever_flow.delay(str(run_id)).id


async def _owned_run(session: AsyncSession, shop: Shop, run_id: uuid.UUID) -> WorkflowRunRow:
    run = await session.get(WorkflowRunRow, run_id)
    if run is None or run.shop_id != shop.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message}
    )


async def _rate_limited(shop: Shop) -> None:
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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests for this shop; retry in {limit.retry_after_seconds}s",
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )


# -- run detail --------------------------------------------------------------------


class PendingDecisionItem(BaseModel):
    tool_call_id: str
    expires_at: str


class PhotoCheckItem(BaseModel):
    key: str
    label: str
    ok: bool
    heuristic: bool = False
    detail: str = ""


class RunPhotos(BaseModel):
    before_url: str | None = None
    after_url: str | None = None
    before: dict[str, int] | None = None
    after: dict[str, int] | None = None
    checks: list[PhotoCheckItem] = []


class RunPromotion(BaseModel):
    lever: str
    proposal: dict[str, Any] | None = None
    applied_at: str | None = None
    verify_attempts: int = 0
    found: dict[str, Any] | None = None
    measurement_start: str | None = None


class RunLever(BaseModel):
    code: str
    kind: str


class RunDetail(BaseModel):
    id: uuid.UUID
    status: str
    stop_reason: str | None = None
    product_name: str
    created_at: str
    completed_at: str | None = None
    running_seconds_elapsed: int
    latest_narration: str | None = None
    decision_summary: PendingDecisionItem | None = None
    awaiting: str | None = None
    decision_id: uuid.UUID | None = None
    awaiting_expires_at: str | None = None
    lever: RunLever | None = None
    photo: RunPhotos | None = None
    promotion: RunPromotion | None = None
    #: Fast track P14-E (contract p14-content-cards.md §2.1): a content run's
    #: steps, script, waits and measuring line; ``None`` for every other run.
    content: dict[str, Any] | None = None


class RunDetailResponse(BaseModel):
    success: bool = True
    data: RunDetail


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_demo_run(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> RunDetailResponse:
    """One run, as the runs list shows it, plus what the seller must do next."""
    run = await _owned_run(session, shop, run_id)
    product = await session.get(Product, run.product_id) if run.product_id else None
    awaiting = lever_flows.awaiting_of(run)
    expires = None
    hours = lever_flows.wait_timeout_hours(awaiting)
    if awaiting is not None and hours is not None and run.waiting_external_since is not None:
        expires = run.waiting_external_since + timedelta(hours=hours)
    pending = await agent_runs.listing.pending_decision(session, run.id)
    flow = await lever_flows.get_flow(session, shop.id, run.id)
    photo = promotion = lever = None
    if flow is not None:
        lever = RunLever(code=flow.lever, kind=flow.kind)
        if flow.kind == "photo":
            before = await lever_flows.get_photo(session, shop.id, run.id, lever_flows.PHOTO_BEFORE)
            after = await lever_flows.get_photo(session, shop.id, run.id, lever_flows.PHOTO_AFTER)
            photo = RunPhotos(
                before_url=lever_flows.photo_url(before),
                after_url=lever_flows.photo_url(after),
                before={"width": before.width, "height": before.height} if before else None,
                after={"width": after.width, "height": after.height} if after else None,
                checks=[PhotoCheckItem(**check) for check in (after.checks if after else [])],
            )
        else:
            promotion = RunPromotion(
                lever=flow.lever,
                proposal=flow.proposal,
                applied_at=_iso(flow.applied_at),
                verify_attempts=flow.verify_attempts,
                found=flow.found,
                measurement_start=_iso(flow.measurement_start),
            )
    return RunDetailResponse(
        data=RunDetail(
            id=run.id,
            status=run.status,
            stop_reason=run.stop_reason,
            product_name=product.name if product is not None else "",
            created_at=_iso(run.created_at) or "",
            completed_at=_iso(run.completed_at),
            running_seconds_elapsed=run.running_seconds_elapsed,
            latest_narration=await agent_runs.listing.latest_narration(session, run.id),
            decision_summary=(
                PendingDecisionItem(
                    tool_call_id=pending.tool_call_id, expires_at=pending.expires_at
                )
                if pending is not None
                else None
            ),
            awaiting=awaiting,
            decision_id=run.action_card_id,
            awaiting_expires_at=_iso(expires),
            lever=lever,
            photo=photo,
            promotion=promotion,
            content=content_run_state.content_detail(run, awaiting=awaiting),
        )
    )


# -- cover image -------------------------------------------------------------------


class PhotoChecksResponse(BaseModel):
    checks: list[PhotoCheckItem]


def _checks_response(report: lever_flows.PhotoReport, *, code: int) -> JSONResponse:
    return JSONResponse(status_code=code, content={"checks": report.checks_json()})


@router.post(
    "/runs/{run_id}/photo",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PhotoChecksResponse,
    responses={422: {"model": PhotoChecksResponse}},
)
async def submit_run_photo(
    run_id: uuid.UUID,
    request: Request,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """The seller's cover photo: checked, stored, and the run continues to consent."""
    await _rate_limited(shop)
    run = await _owned_run(session, shop, run_id)
    if lever_flows.awaiting_of(run) != lever_flows.AWAITING_PHOTO:
        raise _conflict("not_awaiting_photo", _NOT_AWAITING_PHOTO_VI)

    declared = request.headers.get("content-length")
    if (
        declared
        and declared.isdigit()
        and int(declared) > lever_flows.MAX_PHOTO_BYTES + _BODY_SLACK
    ):
        return _checks_response(lever_flows.too_large_report(), code=422)
    body = await request.body()
    try:
        data = lever_flows.parse_multipart_file(request.headers.get("content-type"), body)
    except lever_flows.MultipartError:
        raise HTTPException(
            status_code=422,
            detail={"code": "multipart_file_required", "message": "Cần gửi ảnh trong trường file."},
        ) from None
    report = lever_flows.check_photo(data)
    if not report.ok:
        logger.info(
            "lever_photo_rejected",
            extra={
                "shop_id": str(shop.id),
                "run_id": str(run.id),
                "failed": [c.key for c in report.checks if not c.ok],
            },
        )
        return _checks_response(report, code=422)

    await lever_flows.save_photo(
        session,
        shop_id=shop.id,
        run_id=run.id,
        role=lever_flows.PHOTO_AFTER,
        data=data,
        report=report,
    )
    await session.commit()
    celery_task_id = _enqueue_resume_lever_flow(run.id)
    logger.info(
        "lever_photo_accepted",
        extra={"shop_id": str(shop.id), "run_id": str(run.id), "celery_task_id": celery_task_id},
    )
    return _checks_response(report, code=202)


@router.get("/photos/{shop_id}/{token}")
async def get_run_photo(
    shop_id: uuid.UUID,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """A stored before/after photo. The token is the capability (see module docstring)."""
    async with with_shop_scope(session, shop_id):
        photo = await lever_flows.photo_by_token(session, shop_id, token)
        if photo is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")
        return Response(
            content=photo.data,
            media_type=photo.content_type,
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )


# -- Seller Center promotion ---------------------------------------------------------


class InstructionsResponse(BaseModel):
    steps: list[str]
    deep_link: str
    summary: str


@router.get("/runs/{run_id}/instructions", response_model=InstructionsResponse)
async def get_run_instructions(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> InstructionsResponse:
    """The steps to create this run's promotion on Seller Center (VI)."""
    run = await _owned_run(session, shop, run_id)
    flow = await lever_flows.get_flow(session, shop.id, run.id)
    if flow is None or flow.kind != "promotion":
        raise _conflict("not_promotion", _NOT_PROMOTION_VI)
    proposal = lever_flows.PromotionProposal.from_json(flow.proposal)
    if proposal is None or not proposal.ok:
        reason = proposal.refusal_vi if proposal is not None else None
        raise _conflict("no_proposal", reason or _NO_PROPOSAL_VI)
    product = await session.get(Product, run.product_id) if run.product_id else None
    result = lever_flows.instructions(
        proposal, product_name=product.name if product is not None else ""
    )
    return InstructionsResponse(
        steps=result.steps, deep_link=result.deep_link, summary=result.summary
    )


class AppliedResponse(BaseModel):
    status: str
    verify_attempts: int
    celery_task_id: str


@router.post(
    "/runs/{run_id}/applied",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AppliedResponse,
)
async def mark_run_applied(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> AppliedResponse:
    """ "Tôi đã áp dụng": the run looks for the promotion on TikTok, read-only."""
    await _rate_limited(shop)
    run = await _owned_run(session, shop, run_id)
    flow = await lever_flows.get_flow(session, shop.id, run.id)
    if flow is None or flow.kind != "promotion":
        raise _conflict("not_promotion", _NOT_PROMOTION_VI)
    if lever_flows.awaiting_of(run) != lever_flows.AWAITING_SELLER_ACTION:
        raise _conflict("not_awaiting_seller_action", _NOT_AWAITING_SELLER_VI)
    if flow.verify_attempts >= lever_flows.MAX_VERIFY_ROUNDS:
        raise _conflict("too_many_checks", _TOO_MANY_CHECKS_VI)
    from datetime import UTC, datetime

    flow.applied_at = datetime.now(UTC).replace(tzinfo=None)
    lever_flows.touch(flow)
    await session.commit()
    celery_task_id = _enqueue_resume_lever_flow(run.id)
    logger.info(
        "lever_promotion_applied",
        extra={"shop_id": str(shop.id), "run_id": str(run.id), "celery_task_id": celery_task_id},
    )
    return AppliedResponse(
        status="verifying", verify_attempts=flow.verify_attempts, celery_task_id=celery_task_id
    )


# -- measurement ------------------------------------------------------------------------


@router.get("/runs/{run_id}/measurement")
async def get_run_measurement(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Contract §6. The day-14 verdict is stored (and calibrates the lever) once."""
    run = await _owned_run(session, shop, run_id)
    try:
        if content_measurement.is_content_run(run):
            # Fast track P14-E: video CTR / LIVE CTOR readings (contract §4).
            body = await content_measurement.measure_content_run(session, shop.id, run)
        else:
            body = await lever_flows.measure_run(session, shop.id, run)
    except lever_flows.NotMeasurable as exc:
        raise _conflict(exc.code, exc.message_vi) from None
    await session.commit()
    return body

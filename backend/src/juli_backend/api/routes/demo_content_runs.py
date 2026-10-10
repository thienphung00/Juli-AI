"""Content run seller steps (fast track P14-E, contract ``p14-content-cards.md`` §2.2).

- ``POST /v1/demo/runs/{run_id}/content/use`` -- Dùng kịch bản này
  ``{version, edited_blocks?}``: 202, the run goes on to wait for the video /
  the LIVE; 422 ``{code: "rule_violation", message, field}`` when an edited
  block breaks a rule.
- ``POST /v1/demo/runs/{run_id}/content/redraft`` -- Soạn lại: 202, one more
  model call (bản 2); 409 ``redraft_used`` after it.
- ``POST /v1/demo/runs/{run_id}/content/published`` -- "Tôi đã đăng video" /
  "Tôi đã LIVE xong": 202, the run looks for it on TikTok and starts measuring.

Every route answers 409 ``{code, message}`` when the run is not waiting for that
step. Không thực hiện is the existing ``POST /v1/demo/runs/{id}/decline``. Same
auth, tenant scope and per-shop rate limit as the other run routes.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import demo_run_flows as _flows
from juli_backend.database import Shop, get_session
from juli_backend.services.content_cards import actions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


class UseContentBody(BaseModel):
    version: int = Field(ge=1, le=2)
    edited_blocks: dict[str, str] | None = None


class ContentStepResponse(BaseModel):
    status: str
    celery_task_id: str


def _refused(exc: actions.ContentActionRefused) -> HTTPException:
    detail: dict[str, str] = {"code": exc.code, "message": exc.message_vi}
    if exc.field is not None:
        detail["field"] = exc.field
    return HTTPException(status_code=exc.status, detail=detail)


async def _resume(
    session: AsyncSession, shop: Shop, run_id: uuid.UUID, step: str
) -> ContentStepResponse:
    await session.commit()
    celery_task_id = _flows._enqueue_resume_lever_flow(run_id)
    logger.info(
        "content_run_step",
        extra={"shop_id": str(shop.id), "run_id": str(run_id), "step": step},
    )
    return ContentStepResponse(status=step, celery_task_id=celery_task_id)


@router.post(
    "/runs/{run_id}/content/use",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ContentStepResponse,
)
async def use_content_script(
    run_id: uuid.UUID,
    body: UseContentBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ContentStepResponse:
    """Dùng kịch bản này (optionally with the seller's own edits)."""
    await _flows._rate_limited(shop)
    run = await _flows._owned_run(session, shop, run_id)
    try:
        actions.use_script(run, version=body.version, edited_blocks=body.edited_blocks)
    except actions.ContentActionRefused as exc:
        raise _refused(exc) from None
    return await _resume(session, shop, run.id, "waiting_publish")


@router.post(
    "/runs/{run_id}/content/redraft",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ContentStepResponse,
)
async def redraft_content_script(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ContentStepResponse:
    """Soạn lại: Juli drafts bản 2 (one more model call)."""
    await _flows._rate_limited(shop)
    run = await _flows._owned_run(session, shop, run_id)
    try:
        actions.redraft(run)
    except actions.ContentActionRefused as exc:
        raise _refused(exc) from None
    return await _resume(session, shop, run.id, "drafting")


@router.post(
    "/runs/{run_id}/content/published",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ContentStepResponse,
)
async def mark_content_published(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ContentStepResponse:
    """ "Tôi đã đăng video" / "Tôi đã LIVE xong"."""
    await _flows._rate_limited(shop)
    run = await _flows._owned_run(session, shop, run_id)
    try:
        actions.mark_published(run)
    except actions.ContentActionRefused as exc:
        raise _refused(exc) from None
    return await _resume(session, shop, run.id, "verifying")

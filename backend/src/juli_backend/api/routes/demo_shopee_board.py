"""Thực hiện board sync with work done outside Juli (owner decision 2026-11-16): the HTTP skin.

The behaviour lives in ``services.shopee_recommendations.board_reset`` and
``services.planned_changes.external``; both check, in the service, that the caller owns the
shop (shop owner or business owner) and refuse the reviewer session and the sample shop.

- ``POST /v1/demo/shopee/board/reset``  ``{"confirm": true, "note"?}`` -> every open card of the
  shop is withdrawn with reason ``reset`` (``{withdrawn, by_status, card_ids, codes, ...}``).
- ``POST /v1/demo/shopee/board/external-import/preview``  ``{"file_b64"}`` -> the rows, the
  cards each becomes, the skipped rows with their reason and a ``token``; writes nothing.
- ``POST /v1/demo/shopee/board/external-import/commit``  ``{"file_b64", "token"}`` -> 202 with a
  job id; the import (idempotent per Mã) runs in the background (F6.2).
- ``GET /v1/demo/shopee/board/external-import/status`` -> the shop's last import job and, when
  done, its per-card result (``external.commit_json``).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.capability_gate import require_capability
from juli_backend.api.dependencies import require_writable_shop
from juli_backend.api.reviewer import reviewer_context
from juli_backend.api.routes import planned_changes_common as common
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.database import database as db
from juli_backend.services.planned_changes import external, import_job
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import board_reset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/shopee/board", tags=["demo-shopee"])

_gate_w = require_capability("read_shop_totals", shop_dependency=require_writable_shop)


class ResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: the owner confirmed the dialog ("Gỡ mọi thẻ đang mở khỏi bảng")
    confirm: Literal[True]
    note: str | None = Field(default=None, max_length=300)


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_b64: str = Field(min_length=4, max_length=common.MAX_B64_CHARS)


class CommitBody(PreviewBody):
    token: str = Field(min_length=8, max_length=64)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _refused(exc: ProposalError) -> HTTPException:
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.detail or exc.code}
    )


@router.post("/reset")
async def reset_board(
    body: ResetBody,
    request: Request,
    shop: Shop = Depends(_gate_w),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop.id
    try:
        out = await board_reset.reset_board(
            session,
            shop,
            user_id=user.id,
            reviewer=reviewer_context(request) is not None,
            now=_now(),
            note=body.note,
        )
    except ProposalError as exc:
        await session.rollback()
        raise _refused(exc) from None
    await session.commit()
    logger.info(
        "shopee_board_reset",
        extra={"shop_id": str(shop.id), "user_id": str(user.id), "withdrawn": out["withdrawn"]},
    )
    return {"data": out}


@router.post("/external-import/preview")
async def preview_external(
    body: PreviewBody,
    request: Request,
    shop: Shop = Depends(_gate_w),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop.id
    data = common.decode_file(body.file_b64)
    try:
        preview = await external.preview_import(
            session,
            shop,
            data,
            user_id=user.id,
            reviewer=reviewer_context(request) is not None,
            now=_now(),
        )
    except ProposalError as exc:
        raise _refused(exc) from None
    return {"data": external.preview_json(preview)}


@router.post("/external-import/commit", status_code=status.HTTP_202_ACCEPTED)
async def commit_external(
    body: CommitBody,
    request: Request,
    shop: Shop = Depends(_gate_w),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """F6.2: answers at once with the job; the import runs in the background (poll ``/status``)."""
    shop_id, user_id = shop.id, user.id
    data = common.decode_file(body.file_b64)
    try:
        await board_reset.require_owner(
            session, shop, user_id, reviewer=reviewer_context(request) is not None
        )
    except ProposalError as exc:
        raise _refused(exc) from None
    now = _now()
    job, started = await import_job.create(
        session, shop_id, user_id, file_hash=hashlib.sha256(data).hexdigest(), now=now
    )
    await session.commit()
    if started:
        factory = db._session_factory
        if factory is None:  # no session factory (never in the running API)
            raise HTTPException(status_code=503, detail={"code": "import_unavailable"})
        import_job.spawn(factory, shop_id, user_id, job, data, body.token)
        logger.info(
            "shopee_external_import_started",
            extra={"shop_id": str(shop_id), "user_id": str(user_id), "job_id": job["job_id"]},
        )
    return {"data": job}


@router.get("/external-import/status")
async def external_import_status(
    request: Request,
    shop: Shop = Depends(_gate_w),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The shop's last import job (running, done with the per-card result, or failed)."""
    try:
        await board_reset.require_owner(
            session, shop, user.id, reviewer=reviewer_context(request) is not None
        )
    except ProposalError as exc:
        raise _refused(exc) from None
    return {"data": await import_job.latest(session, shop.id, now=_now())}

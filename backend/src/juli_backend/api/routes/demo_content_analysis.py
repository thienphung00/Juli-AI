"""Seller-uploaded video / LIVE analysis routes (fast track P15).

Contract ``fasttrack/contracts/p15-content-analysis.md``.

- ``POST /v1/demo/content-analysis`` -- open an upload slot
  ``{kind, content_ref?, tiktok_product_id?, run_id?, file_name, content_type, size_bytes}``
  → 201 ``{data: {analysis, upload: {url, token, chunk_bytes, expires_at}}}``;
  413 / 415 / 422 / 409 ``too_many_uploads`` / 402 ``cost_cap_reached``.
- ``PUT /v1/demo/content-analysis/{id}/file?offset=N&token=…`` -- raw bytes
  (``Content-Type: application/octet-stream``), ≤ 32 MB per request, at the
  offset Juli already holds → 200 ``{data: analysis}``; the last chunk queues
  the analysis (``analyze_content_upload`` on the ``content_analysis`` queue).
  409 ``offset_mismatch`` carries ``expected_offset`` (resume there).
- ``GET /v1/demo/content-analysis?tiktok_product_id=&content_ref=&run_id=`` →
  ``{data: [analysis]}`` (newest first, ≤ 20).
- ``GET /v1/demo/content-analysis/{id}`` → ``{data: analysis}``.

Auth: the demo session (``get_current_user``) + ``X-Shop-Id``
(``get_active_shop``, which also sets the tenant scope, so RLS on
``content_analyses`` holds); the upload additionally needs the slot's signed
token. Another shop's analysis is a 404. Errors are ``{detail: {code, message
(VI)}}``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import demo_run_flows as _flows
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services.content_analysis import storage, uploads
from juli_backend.services.content_analysis.config import settings
from juli_backend.services.content_analysis.pipeline import STATUS_QUEUED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

BASE_PATH = "/v1/demo/content-analysis"


class CreateUploadBody(BaseModel):
    kind: str = Field(max_length=10)
    content_ref: str | None = Field(default=None, max_length=200)
    tiktok_product_id: str | None = Field(default=None, max_length=100)
    run_id: uuid.UUID | None = None
    file_name: str = Field(max_length=500)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)


def _refused(exc: uploads.UploadRefused) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message_vi, **exc.extra}
    return HTTPException(status_code=exc.status, detail=detail)


def _enqueue(analysis_id: uuid.UUID, shop_id: uuid.UUID) -> str | None:
    """Imported lazily so Celery is not a route import."""
    from juli_backend.workers.tasks.content_analysis import enqueue_analysis

    return enqueue_analysis(analysis_id, shop_id)


@router.post("/content-analysis", status_code=status.HTTP_201_CREATED)
async def create_content_upload(
    body: CreateUploadBody,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _flows._rate_limited(shop)
    conf = settings()
    try:
        row = await uploads.create_upload(
            session,
            shop_id=shop.id,
            user_id=getattr(user, "id", None),
            kind=body.kind,
            content_ref=body.content_ref,
            tiktok_product_id=body.tiktok_product_id,
            workflow_run_id=body.run_id,
            file_name=body.file_name,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            conf=conf,
        )
    except uploads.UploadRefused as exc:
        raise _refused(exc) from None
    token = storage.sign(row.id, shop.id, row.upload_expires_at)
    await session.commit()
    logger.info(
        "content_analysis_upload_opened",
        extra={
            "shop_id": str(shop.id),
            "analysis_id": str(row.id),
            "kind": row.kind,
            "size_bytes": row.size_bytes,
        },
    )
    return {
        "data": {
            "analysis": uploads.view(row),
            "upload": {
                "url": f"{BASE_PATH}/{row.id}/file",
                "token": token,
                "chunk_bytes": conf.chunk_bytes,
                "expires_at": row.upload_expires_at.isoformat() + "Z",
            },
        }
    }


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "chunk_too_large",
                "message": "Phần video quá lớn.",
                "max_bytes": limit,
            },
        )
    chunks: list[bytes] = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "chunk_too_large",
                    "message": "Phần video quá lớn.",
                    "max_bytes": limit,
                },
            )
        chunks.append(part)
    return b"".join(chunks)


@router.put("/content-analysis/{analysis_id}/file")
async def upload_content_chunk(
    analysis_id: uuid.UUID,
    request: Request,
    offset: int = Query(ge=0),
    token: str = Query(min_length=10, max_length=200),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conf = settings()
    try:
        signed = storage.verify(token, analysis_id, shop.id)
    except RuntimeError:
        signed = False
    if not signed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "bad_token",
                "message": "Liên kết tải lên không hợp lệ hoặc đã hết hạn.",
            },
        )
    try:
        row = await uploads.get_owned(session, shop.id, analysis_id)
    except uploads.UploadRefused as exc:
        raise _refused(exc) from None
    data = await _read_body(request, conf.chunk_bytes)
    try:
        uploads.receive_chunk(row, offset=offset, data=data, conf=conf)
    except uploads.UploadRefused as exc:
        await session.commit()  # keep an expiry / a refused first chunk
        raise _refused(exc) from None
    await session.commit()
    if row.status == STATUS_QUEUED:
        task_id = _enqueue(row.id, shop.id)
        logger.info(
            "content_analysis_upload_complete",
            extra={"shop_id": str(shop.id), "analysis_id": str(row.id), "task_id": task_id},
        )
    return {"data": uploads.view(row)}


@router.get("/content-analysis")
async def list_content_analyses(
    tiktok_product_id: str | None = Query(default=None, max_length=100),
    content_ref: str | None = Query(default=None, max_length=200),
    run_id: uuid.UUID | None = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await uploads.list_for(
        session,
        shop.id,
        tiktok_product_id=tiktok_product_id,
        content_ref=content_ref,
        workflow_run_id=run_id,
    )
    return {"data": [uploads.view(row) for row in rows]}


@router.get("/content-analysis/{analysis_id}")
async def get_content_analysis(
    analysis_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        row = await uploads.get_owned(session, shop.id, analysis_id)
    except uploads.UploadRefused as exc:
        raise _refused(exc) from None
    return {"data": uploads.view(row)}

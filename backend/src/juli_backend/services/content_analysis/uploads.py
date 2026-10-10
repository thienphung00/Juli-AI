"""Upload slots, chunks and the seller-facing view (fast track P15).

The routes (``api/routes/demo_content_analysis.py``) are thin: they resolve the
shop (session + ``X-Shop-Id``, tenant scope) and call these. Every refusal is an
``UploadRefused`` with an HTTP status, a code and a Vietnamese message.

Upload protocol (resumable, Cloudflare-safe):

1. ``create_upload`` -- the client declares kind, row, product, file name,
   type and size; Juli checks them (type, size, in-flight uploads, the monthly
   OpenAI cap) and opens a slot (``awaiting_upload``) with a signed token.
2. ``receive_chunk`` -- the raw bytes, at most ``chunk_bytes`` (32 MB) per
   request, each at the offset Juli already holds (a retry of the same chunk
   after a lost answer is refused with the expected offset, so the client
   resumes there). The first chunk must start with an MP4 / MOV box.
3. When the last byte arrives the slot becomes ``queued`` and the route
   enqueues the analysis.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.models import Product, WorkflowRun
from juli_backend.services.content_analysis import costs, storage
from juli_backend.services.content_analysis.config import (
    CONTENT_TYPES,
    EXTENSIONS,
    KINDS,
    LIVE,
    MB,
    AnalysisSettings,
    max_bytes,
)
from juli_backend.services.content_analysis.pipeline import (
    STATUS_AWAITING,
    STATUS_DONE,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_REFUSED,
)

_REF = re.compile(r"^(video|live):[0-9A-Za-z_-]{1,100}$")
_BOX_TYPES = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}
LIST_LIMIT = 20

STATUS_LABEL_VI = {
    STATUS_AWAITING: "Đang tải lên",
    STATUS_QUEUED: "Đang chờ phân tích",
    STATUS_PROCESSING: "Juli đang phân tích",
    STATUS_DONE: "Đã phân tích",
    STATUS_FAILED: "Chưa phân tích được",
    STATUS_REFUSED: "Đã đạt hạn mức tháng",
    STATUS_EXPIRED: "Tải lên chưa xong",
}


class UploadRefused(Exception):
    def __init__(self, status: int, code: str, message_vi: str, **extra: Any) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.message_vi = message_vi
        self.extra = extra


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def clean_file_name(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:200] or "video"


async def create_upload(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: str,
    content_ref: str | None,
    tiktok_product_id: str | None,
    workflow_run_id: uuid.UUID | None,
    file_name: str,
    content_type: str,
    size_bytes: int,
    conf: AnalysisSettings,
    now: datetime | None = None,
) -> ContentAnalysis:
    now = now or _now()
    if kind not in KINDS:
        raise UploadRefused(422, "bad_kind", "Loại nội dung không hợp lệ.")
    name = clean_file_name(file_name)
    if content_type not in CONTENT_TYPES or not name.lower().endswith(EXTENSIONS):
        raise UploadRefused(415, "unsupported_type", "Juli chỉ nhận video MP4 hoặc MOV.")
    limit = max_bytes(kind, conf)
    if size_bytes <= 0 or size_bytes > limit:
        what = "Bản ghi LIVE" if kind == LIVE else "Video"
        raise UploadRefused(
            413,
            "too_large",
            f"{what} lớn hơn {limit // MB} MB. Bạn xuất lại bản nhẹ hơn rồi tải lên.",
            max_bytes=limit,
        )
    if content_ref is not None:
        if not _REF.match(content_ref) or not content_ref.startswith(f"{kind}:"):
            raise UploadRefused(422, "bad_content_ref", "Dòng nội dung không hợp lệ.")
    if tiktok_product_id is not None and not re.fullmatch(
        r"[0-9A-Za-z_-]{1,100}", tiktok_product_id
    ):
        raise UploadRefused(422, "bad_product", "Sản phẩm không hợp lệ.")
    if workflow_run_id is not None:
        run = await session.get(WorkflowRun, workflow_run_id)
        if run is None or run.shop_id != shop_id:
            raise UploadRefused(404, "run_not_found", "Không tìm thấy lượt chạy này.")
        if tiktok_product_id is None and run.product_id is not None:
            # From a content run: the run's own product.
            product = await session.get(Product, run.product_id)
            tiktok_product_id = product.tiktok_product_id if product is not None else None
    in_flight = (
        await session.execute(
            select(func.count())
            .select_from(ContentAnalysis)
            .where(
                ContentAnalysis.shop_id == shop_id,
                ContentAnalysis.status.in_((STATUS_AWAITING, STATUS_QUEUED, STATUS_PROCESSING)),
                ContentAnalysis.upload_expires_at > now,
            )
        )
    ).scalar_one()
    if in_flight >= conf.max_in_flight:
        raise UploadRefused(
            409,
            "too_many_uploads",
            "Juli đang xử lý video khác của shop. Bạn đợi xong rồi tải tiếp.",
        )
    try:
        await costs.check(session, shop_id, now=now.replace(tzinfo=UTC))
    except costs.CostCapExceeded as exc:
        raise UploadRefused(402, exc.code, exc.message_vi) from None
    analysis_id = uuid.uuid4()
    row = ContentAnalysis(
        id=analysis_id,
        shop_id=shop_id,
        kind=kind,
        content_ref=content_ref,
        tiktok_product_id=tiktok_product_id,
        workflow_run_id=workflow_run_id,
        status=STATUS_AWAITING,
        file_name=name,
        content_type=content_type,
        size_bytes=size_bytes,
        received_bytes=0,
        storage_key=storage.storage_key(shop_id, analysis_id),
        upload_expires_at=now + timedelta(hours=conf.upload_ttl_hours),
        created_by_user_id=user_id,
        cost_usd=0,
        attempts=0,
    )
    session.add(row)
    await session.flush()
    return row


def expire_if_stale(
    row: ContentAnalysis, conf: AnalysisSettings, now: datetime | None = None
) -> bool:
    if row.status == STATUS_AWAITING and row.upload_expires_at <= (now or _now()):
        storage.delete(conf, row.storage_key)
        row.status = STATUS_EXPIRED
        row.storage_key = None
        row.file_deleted_at = now or _now()
        return True
    return False


def receive_chunk(
    row: ContentAnalysis,
    *,
    offset: int,
    data: bytes,
    conf: AnalysisSettings,
    now: datetime | None = None,
) -> ContentAnalysis:
    if expire_if_stale(row, conf, now):
        raise UploadRefused(410, "upload_expired", "Hết hạn tải lên. Bạn tải lên lại từ đầu.")
    if row.status != STATUS_AWAITING or not row.storage_key:
        raise UploadRefused(409, "not_uploading", "Video này đã tải lên xong.")
    if offset != row.received_bytes:
        raise UploadRefused(
            409,
            "offset_mismatch",
            "Phần video này không khớp. Juli tiếp tục từ phần đã nhận.",
            expected_offset=row.received_bytes,
        )
    if not data:
        raise UploadRefused(422, "empty_chunk", "Phần video trống.")
    if len(data) > conf.chunk_bytes:
        raise UploadRefused(
            413, "chunk_too_large", "Phần video quá lớn.", max_bytes=conf.chunk_bytes
        )
    if row.received_bytes + len(data) > row.size_bytes:
        raise UploadRefused(413, "size_mismatch", "Video lớn hơn kích thước đã khai báo.")
    if offset == 0 and (len(data) < 8 or data[4:8] not in _BOX_TYPES):
        storage.delete(conf, row.storage_key)
        row.status = STATUS_FAILED
        row.error_code = "not_a_video"
        row.error_message = (
            "Tệp không phải video MP4 / MOV. Bạn xuất lại video dạng MP4 rồi tải lên."
        )
        row.storage_key = None
        row.file_deleted_at = now or _now()
        raise UploadRefused(415, "not_a_video", row.error_message)
    try:
        row.received_bytes = storage.append_chunk(conf, row.storage_key, offset, data)
    except ValueError:
        # The disk and the row disagree (a crashed earlier write): resume from the disk.
        row.received_bytes = storage.size_of(conf, row.storage_key)
        raise UploadRefused(
            409,
            "offset_mismatch",
            "Phần video này không khớp. Juli tiếp tục từ phần đã nhận.",
            expected_offset=row.received_bytes,
        ) from None
    if row.received_bytes == row.size_bytes:
        row.status = STATUS_QUEUED
    return row


async def get_owned(
    session: AsyncSession, shop_id: uuid.UUID, analysis_id: uuid.UUID
) -> ContentAnalysis:
    row = await session.get(ContentAnalysis, analysis_id)
    if row is None or row.shop_id != shop_id:
        raise UploadRefused(404, "not_found", "Không tìm thấy phân tích này.")
    return row


async def list_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    tiktok_product_id: str | None = None,
    content_ref: str | None = None,
    workflow_run_id: uuid.UUID | None = None,
) -> list[ContentAnalysis]:
    query = select(ContentAnalysis).where(ContentAnalysis.shop_id == shop_id)
    if tiktok_product_id:
        query = query.where(ContentAnalysis.tiktok_product_id == tiktok_product_id)
    if content_ref:
        query = query.where(ContentAnalysis.content_ref == content_ref)
    if workflow_run_id:
        query = query.where(ContentAnalysis.workflow_run_id == workflow_run_id)
    rows = (
        await session.execute(query.order_by(ContentAnalysis.created_at.desc()).limit(LIST_LIMIT))
    ).scalars()
    return list(rows)


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


def view(row: ContentAnalysis, now: datetime | None = None) -> dict[str, Any]:
    """The seller-facing JSON of one analysis (contract §3)."""
    status = row.status
    if status == STATUS_AWAITING and row.upload_expires_at <= (now or _now()):
        status = STATUS_EXPIRED
    return {
        "id": str(row.id),
        "kind": row.kind,
        "content_ref": row.content_ref,
        "tiktok_product_id": row.tiktok_product_id,
        "run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
        "file_name": row.file_name,
        "status": status,
        "status_label": STATUS_LABEL_VI.get(status, status),
        "upload": {"received_bytes": row.received_bytes, "size_bytes": row.size_bytes},
        "duration_s": row.duration_s,
        "error": (
            {"code": row.error_code, "message": row.error_message} if row.error_code else None
        ),
        "result": row.result if status == STATUS_DONE else None,
        "cost_usd": float(row.cost_usd or 0),
        "file_deleted": row.storage_key is None,
        "created_at": _iso(row.created_at),
        "completed_at": _iso(row.completed_at),
    }


__all__ = [
    "LIST_LIMIT",
    "STATUS_LABEL_VI",
    "UploadRefused",
    "clean_file_name",
    "create_upload",
    "expire_if_stale",
    "get_owned",
    "list_for",
    "receive_chunk",
    "view",
]

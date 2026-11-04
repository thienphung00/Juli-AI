"""Request bodies, JSON shapes and the shared logic of the planned-changes import, for the
Demo (``demo_planned_changes``) and Ops (``ops_planned_changes``) routes (p91 D-13)."""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services import planned_changes as pc
from juli_backend.services.planned_changes import importer as imp
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shop_proposals import ProposalError

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_B64_CHARS = xlsx_io.MAX_FILE_BYTES * 4 // 3 + 8


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_b64: str = Field(min_length=4, max_length=MAX_B64_CHARS)


class ApplyBody(ImportBody):
    reason: str = Field(min_length=1, max_length=imp.MAX_REASON_CHARS)
    #: the ``file_hash`` the preview returned; a different file is refused
    file_hash: str | None = Field(default=None, max_length=64)


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def decode_file(file_b64: str) -> bytes:
    try:
        return base64.b64decode(file_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail(imp.ERROR_FILE, "Tệp không hợp lệ"),
        ) from None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def overview() -> dict[str, Any]:
    return {
        "data": {
            "sheet": pc.SHEET,
            "columns": [{"key": k, "label": label} for k, label, _ in pc.COLUMNS],
            "kinds": [{"key": k, "label": label} for k, label in pc.KIND_LABELS.items()],
            "reasons": list(pc.SUGGESTED_REASONS),
            "min_window_days": imp.pr.MIN_WINDOW_DAYS,
            "max_title_chars": imp.config.MAX_TITLE_CHARS,
        }
    }


def template_response() -> Response:
    stamp = datetime.now(UTC).strftime("%m%d")
    return Response(
        content=pc.build_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="de-xuat-ke-hoach-mau-{stamp}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


def _problem_json(p: imp.pr.Problem) -> dict[str, Any]:
    return {
        "row": p.row,
        "ref": p.ref,
        "kind": p.kind,
        "label": p.label,
        "column": p.column,
        "detail": p.detail,
    }


def row_json(plan: pc.RowPlan) -> dict[str, Any]:
    r = plan.row
    return {
        "row": r.row,
        "ref": r.ref,
        "item_id": r.item_id,
        "change_kind": r.kind,
        "change_label": pc.KIND_LABELS.get(r.kind or "", r.kind_text),
        "before": r.before_text,
        "after": r.after_text,
        "reason": r.reason,
        "cost": r.cost,
        "date": r.on.isoformat() if r.on else None,
        "window_days": r.window_days,
        "depends_on": list(r.depends_on),
        "decision": r.decision,
        "decision_label": imp.pr.DECISION_LABELS[r.decision],
        "status": r.status,
        "status_label": imp.pr.STATUS_LABELS[r.status],
        "action": plan.action,
        "problems": [_problem_json(p) for p in plan.problems],
        "warnings": [_problem_json(w) for w in plan.warnings],
        "card": imp._brief(plan.card),
    }


def preview_json(preview: pc.Preview) -> dict[str, Any]:
    return {
        "file_hash": preview.file_hash,
        "missing_columns": preview.missing_columns,
        "counts": preview.counts(),
        "rows": [row_json(p) for p in preview.plans],
        "order": preview.order,
    }


async def run_preview(
    session: AsyncSession, shop_id: uuid.UUID, body: ImportBody
) -> dict[str, Any]:
    try:
        preview = await pc.preview_import(session, shop_id, decode_file(body.file_b64), now=_now())
    except pc.ImportFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail(imp.ERROR_FILE, str(exc)),
        ) from None
    return {"data": preview_json(preview)}


async def run_apply(
    session: AsyncSession, shop_id: uuid.UUID, body: ApplyBody, *, actor: pc.Actor
) -> pc.ApplyResult:
    """Apply (no commit: the caller audits and commits); refusals roll back."""
    try:
        return await pc.apply_import(
            session,
            shop_id,
            decode_file(body.file_b64),
            actor=actor,
            reason=body.reason,
            expected_hash=body.file_hash,
            now=_now(),
        )
    except pc.ImportFileError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail(imp.ERROR_FILE, str(exc)),
        ) from None
    except pc.FileMismatch as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_detail(imp.ERROR_MISMATCH, str(exc))
        ) from None
    except pc.NothingToApply as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_detail(imp.ERROR_NOTHING, str(exc))
        ) from None
    except ProposalError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=exc.status, detail=_detail(exc.code, exc.detail or exc.code)
        ) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("concurrent_change", "Có người vừa nhập tệp khác. Tải lại rồi thử lại."),
        ) from None


def apply_json(result: pc.ApplyResult) -> dict[str, Any]:
    return {
        "data": {
            "number": result.number,
            "file_hash": result.file_hash,
            "reason": result.reason,
            "applied_at": result.applied_at.isoformat(),
            "created": result.created,
            "advanced": result.advanced,
            "executed": result.executed,
            "unchanged": result.unchanged,
            "rejected": result.rejected,
            "rows": result.rows,
        }
    }


async def read_versions(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    return {"data": {"imports": await pc.list_imports(session, shop_id)}}


async def read_version(session: AsyncSession, shop_id: uuid.UUID, number: int) -> dict[str, Any]:
    found = await pc.get_import(session, shop_id, number)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_detail("version_not_found", "Không có lần nhập này"),
        )
    return {"data": found}

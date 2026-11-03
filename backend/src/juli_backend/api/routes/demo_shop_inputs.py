"""Cài đặt › Thông số shop, the seller's side (P90 step 4, ADR-120 d.12).

The shop's owner downloads a template pre-filled from the product list, fills it in,
uploads it, reads the rejected rows and the old -> new diff, and applies it with a reason.
Every apply is a version (who, when, why, file hash) in ``shop_rule_versions``; the
``shop_rules`` projection stays what the readers use; any SKU can be restored to an earlier
version, which appends a new one.

- ``GET  /v1/demo/shop-inputs`` -- the screen's read model: catalogue size, SKUs on the 1/3
  cost fallback, targets so far, suggested reasons.
- ``GET  /v1/demo/shop-inputs/template`` -- the pre-filled ``.xlsx``.
- ``POST /v1/demo/shop-inputs/preview`` -- ``{"file_b64"}``: rejected rows, diff, goal
  warnings, how many open recommendations the valid rows would re-run. Writes nothing.
- ``POST /v1/demo/shop-inputs/apply`` -- ``{"file_b64", "reason", "file_hash"?}``: writes the
  valid rows as one change set; rejected rows write nothing.
- ``GET  /v1/demo/shop-inputs/versions`` -- SKUs with a history; with ``?scope_ref=`` that
  SKU's change sets, newest first, and how many recommendations a restore would re-run.
- ``POST /v1/demo/shop-inputs/restore`` -- ``{"scope_ref", "version"}``.

The file travels base64 inside JSON (no multipart dependency); the service re-reads it on
apply, so nothing about an upload is kept between calls. Auth and tenant scope as every
``/v1/demo`` route; ``set_by`` is ``seller``. The Ops mirror is ``ops_shop_inputs.py``.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shop_inputs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/shop-inputs", tags=["demo"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: Base64 length of the largest accepted file (``shop_inputs.MAX_FILE_BYTES``).
MAX_B64_CHARS = shop_inputs.MAX_FILE_BYTES * 4 // 3 + 8


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_b64: str = Field(min_length=4, max_length=MAX_B64_CHARS)


class ApplyBody(ImportBody):
    reason: str = Field(min_length=1, max_length=500)
    #: The ``file_hash`` the preview returned; a different file is refused.
    file_hash: str | None = Field(default=None, max_length=64)


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_ref: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)


def decode_file(file_b64: str) -> bytes:
    try:
        return base64.b64decode(file_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_file", "message": "Tệp không hợp lệ"},
        ) from None


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _diff_json(d: shop_inputs.FieldDiff) -> dict[str, Any]:
    return {
        "scope_ref": d.scope_ref,
        "item_id": d.item_id,
        "variation_id": d.variation_id,
        "sku": d.sku,
        "field": d.field,
        "label": d.label,
        "unit": d.unit,
        "rule_key": d.rule_key,
        "old": d.old,
        "new": d.new,
        "effect": d.effect,
    }


def _affected_json(a: shop_inputs.AffectedRecommendations) -> dict[str, Any]:
    return {
        "total": a.total,
        "proposals": a.proposals,
        "action_cards": a.action_cards,
        "item_ids": list(a.item_ids),
        "shop_wide": a.shop_wide,
    }


def preview_json(
    preview: shop_inputs.ImportPreview, affected: shop_inputs.AffectedRecommendations
) -> dict[str, Any]:
    return {
        "file_hash": preview.file_hash,
        "counts": {
            "sku_rows": preview.sku_rows,
            "sku_rows_valid": preview.sku_rows_valid,
            "sku_rows_rejected": preview.sku_rows_rejected,
            "sku_rows_unchanged": preview.sku_rows_unchanged,
            "goal_rows": preview.goal_rows,
            "goal_rows_rejected": preview.goal_rows_rejected,
            "changes": len(preview.diffs) + len(preview.goal_diffs),
            "skus_changed": len(preview.changed_scopes),
            "months_changed": len(preview.changed_months),
        },
        "rejections": [
            {
                "sheet": r.sheet,
                "row": r.row,
                "sku": r.sku,
                "column": r.column,
                "value": r.value,
                "reason": r.reason,
                "kind": r.kind,
                "kind_label": r.kind_label,
            }
            for r in preview.rejections
        ],
        "diffs": [_diff_json(d) for d in preview.diffs],
        "goal_diffs": [_diff_json(d) for d in preview.goal_diffs],
        "warnings": [
            {"month": w.month, "message": w.message, "deviation": w.deviation}
            for w in preview.warnings
        ],
        "affected": _affected_json(affected),
    }


def change_set_json(c: shop_inputs.ChangeSet) -> dict[str, Any]:
    return {
        "id": c.id,
        "number": c.number,
        "valid_from": c.valid_from.isoformat(),
        "set_by": c.set_by,
        "set_by_user_id": str(c.set_by_user_id) if c.set_by_user_id else None,
        "reason": c.reason,
        "import_file_hash": c.import_file_hash,
        "changes": c.changes,
        "state": c.state,
        "current": c.current,
    }


# -- the logic both routers share (the Ops router calls these inside its own scope) -------


async def read_overview(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    return {"data": await shop_inputs.build_overview(session, shop_id)}


async def make_template(session: AsyncSession, shop_id: uuid.UUID) -> Response:
    result = await shop_inputs.build_template(session, shop_id)
    stamp = datetime.now(UTC).strftime("%m%d")
    return Response(
        content=result.content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="thong-so-mau-{stamp}.xlsx"',
            "Cache-Control": "no-store",
            "X-Sku-Rows": str(result.sku_rows),
            "X-Items": str(result.item_count),
        },
    )


async def run_preview(
    session: AsyncSession, shop_id: uuid.UUID, body: ImportBody
) -> dict[str, Any]:
    try:
        preview = await shop_inputs.preview_import(session, shop_id, decode_file(body.file_b64))
    except shop_inputs.ImportFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("invalid_file", str(exc)),
        ) from None
    affected = await shop_inputs.preview_affected(session, shop_id, preview)
    return {"data": preview_json(preview, affected)}


async def run_apply(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: ApplyBody,
    *,
    actor: shop_inputs.Actor,
) -> shop_inputs.ApplyResult:
    """Apply and commit; the caller adds its own audit before that if it has one."""
    try:
        return await shop_inputs.apply_import(
            session,
            shop_id,
            decode_file(body.file_b64),
            actor=actor,
            reason=body.reason,
            expected_hash=body.file_hash,
        )
    except shop_inputs.ImportFileError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("invalid_file", str(exc)),
        ) from None
    except shop_inputs.FileMismatch as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_detail("file_changed", str(exc))
        ) from None
    except shop_inputs.NothingToApply as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_detail("nothing_to_apply", str(exc))
        ) from None
    except shop_inputs.VersionError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("invalid_reason", str(exc)),
        ) from None


def apply_json(result: shop_inputs.ApplyResult) -> dict[str, Any]:
    return {
        "data": {
            "file_hash": result.preview.file_hash,
            "reason": result.reason,
            "applied_at": result.applied_at.isoformat(),
            "versions_written": result.versions_written,
            "skus_changed": result.skus_changed,
            "months_changed": result.months_changed,
            "rejected": len(result.preview.rejections),
            "affected": _affected_json(result.affected),
        }
    }


async def read_versions(
    session: AsyncSession, shop_id: uuid.UUID, scope_ref: str | None
) -> dict[str, Any]:
    if scope_ref is None:
        return {"data": {"skus": await shop_inputs.versions_index(session, shop_id)}}
    history = await shop_inputs.sku_history(session, shop_id, scope_ref)
    item_id, _ = shop_inputs.split_scope(scope_ref)
    affected = await shop_inputs.affected_recommendations(session, shop_id, item_ids=[item_id])
    return {
        "data": {
            "scope_ref": scope_ref,
            "versions": [change_set_json(c) for c in reversed(history)],
            "restore_affects": _affected_json(affected),
        }
    }


async def run_restore(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: RestoreBody,
    *,
    actor: shop_inputs.Actor,
) -> dict[str, Any]:
    try:
        written = await shop_inputs.restore_sku_version(
            session, shop_id, scope_ref=body.scope_ref, number=body.version, actor=actor
        )
    except shop_inputs.VersionNotFound as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_detail("version_not_found", str(exc))
        ) from None
    except shop_inputs.VersionError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_detail("not_restorable", str(exc))
        ) from None
    item_id, _ = shop_inputs.split_scope(body.scope_ref)
    affected = await shop_inputs.affected_recommendations(session, shop_id, item_ids=[item_id])
    now = datetime.now(UTC)
    await shop_inputs.mark_stale(
        session,
        shop_id,
        shop_inputs.StaleRequest(
            item_ids=affected.item_ids,
            shop_wide=False,
            reason="seller_inputs_changed",
            changed_at=now,
        ),
    )
    history = await shop_inputs.sku_history(session, shop_id, body.scope_ref)
    return {
        "data": {
            "scope_ref": body.scope_ref,
            "restored_from": body.version,
            "new_version": history[-1].id if history else None,
            "versions_written": len(written),
            "affected": _affected_json(affected),
        }
    }


# -- routes -------------------------------------------------------------------------------


@router.get("")
async def get_shop_inputs(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await read_overview(session, shop.id)


@router.get("/template")
async def download_template(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> Response:
    return await make_template(session, shop.id)


@router.post("/preview")
async def preview_shop_inputs(
    body: ImportBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await run_preview(session, shop.id, body)


@router.post("/apply")
async def apply_shop_inputs(
    body: ApplyBody,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await run_apply(
        session, shop.id, body, actor=shop_inputs.Actor(set_by="seller", user_id=user.id)
    )
    await session.commit()
    logger.info(
        "shop_inputs_applied",
        extra={
            "shop_id": str(shop.id),
            "user_id": str(user.id),
            "versions": result.versions_written,
            "file_hash": result.preview.file_hash,
        },
    )
    return apply_json(result)


@router.get("/versions")
async def get_versions(
    scope_ref: str | None = Query(default=None, min_length=1, max_length=100),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await read_versions(session, shop.id, scope_ref)


@router.post("/restore")
async def restore_shop_input(
    body: RestoreBody,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await run_restore(
        session, shop.id, body, actor=shop_inputs.Actor(set_by="seller", user_id=user.id)
    )
    await session.commit()
    logger.info(
        "shop_inputs_restored",
        extra={"shop_id": str(shop.id), "user_id": str(user.id), "scope_ref": body.scope_ref},
    )
    return result

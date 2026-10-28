"""Seller-facing reason codes and Vietnamese copy (issue #1272 / W6-B/P-UI-3).

This module provides seller-facing copy for `ToolCompletedPayload.summary`
and other direct-to-seller messages. All strings are Vietnamese and reviewed
per ADR-072 (copy governance) and ADR-074 d.2 (seller-facing surface).

The module is deliberately separate from `core.py` so internal logging can
keep server-side detail while seller copy stays safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class SellerFacingRefusalReason(StrEnum):
    """Seller-facing reason codes for tool refusals.

    Each member is a Vietnamese string that never leaks internal identifiers
    (tool names, playbook keys, validation details). All strings are reviewed
    and drawn from the approved copy dictionary (dictionary.md).
    """

    # Tool refusal: unregistered tool
    TOOL_NOT_FOUND = "Công cụ không khả dụng."

    # Tool refusal: registered but not in playbook
    TOOL_NOT_ALLOWED = "Không thể thực hiện yêu cầu này vào lúc này."

    # Tool refusal: malformed parameters
    MALFORMED_PARAMS = "Yêu cầu chứa thông tin không hợp lệ. Vui lòng thử lại."


class SellerFacingCompletionReason(StrEnum):
    """Seller-facing reason codes for tool completion states.

    Each member is a Vietnamese string for the `ToolCompletedPayload.summary`
    field when a tool finishes.
    """

    # Tool completed successfully
    COMPLETED = "Hoàn tất"

    # Tool result blocked by inbound safety guard
    BLOCKED_BY_GUARD = "Yêu cầu không an toàn. Vui lòng thử lại."


class SellerFacingDeclinedReason(StrEnum):
    """Seller-facing reason codes for approval/confirmation decline."""

    # Seller declined the proposed change
    DECLINED_BY_SELLER = "Bạn đã từ chối thay đổi."


#: P70 (owner, 2026-10-28): the ``tool.completed`` summary of a tool call the model proposed in
#: its wrap-up turn after the seller declined (refused, never dispatched). The wrap-up turn is
#: offered no tool (``tool_choice="none"``), so this is only the defensive path; the demo shows
#: no row for it at all. The model-facing English reason stays in the conversation only.
DECLINE_WRAP_UP_REFUSED_SUMMARY = "Juli dừng lại theo lựa chọn của bạn."


#: Fast track P10-A (contract p10-quyet-dinh.md §3): the write ran with the
#: title / description the seller edited at the consent step.
EDITED_BY_SELLER_SUMMARY = "Hoàn tất theo bản bạn sửa"

_DIAGNOSES_TOOL = "get_product_diagnoses"
_DIAGNOSES_NONE_SUMMARY = "TikTok không báo lỗi nào"
_DIAGNOSES_SHOWN_LABELS = 3
_DIAGNOSES_UNAVAILABLE_SUMMARY = "Không đọc được chẩn đoán TikTok — tiếp tục với thông tin sản phẩm"

_PROMOTIONS_TOOL = "find_product_promotions"
_PROMOTIONS_UNAVAILABLE_SUMMARY = "Chưa đọc được khuyến mãi từ TikTok"


def _short_date(value: object) -> str:
    """``2026-10-09`` -> ``09/10``; anything else -> ``…``."""
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        return f"{value[8:10]}/{value[5:7]}"
    return "…"


def _promotions_summary(result: Mapping[str, Any]) -> str:
    """P10-B: what the read-only promotion check found, in the seller's words."""
    if result.get("unavailable") is True:
        return _PROMOTIONS_UNAVAILABLE_SUMMARY
    promotions = result.get("promotions")
    if not isinstance(promotions, list) or not promotions:
        return "Không có khuyến mãi loại này cho sản phẩm"
    first = promotions[0] if isinstance(promotions[0], Mapping) else {}
    label = first.get("type_label") if isinstance(first.get("type_label"), str) else "Khuyến mãi"
    span = f"{_short_date(first.get('begin_date'))} → {_short_date(first.get('end_date'))}"
    extra = f" (+{len(promotions) - 1})" if len(promotions) > 1 else ""
    return f"Có: {label} · {span}{extra}"


def tool_completed_summary(tool_name: str, result: Mapping[str, Any]) -> str:
    """The seller-facing `ToolCompletedPayload.summary` for a successful tool.

    `Hoàn tất` for every tool except `get_product_diagnoses`, whose summary
    names what TikTok flagged (AC-8.4) in plain words -- P41 (D47.7) dropped
    the internal "mã" wording: `Giá kém cạnh tranh` / `A, B, C và 2 lỗi khác`
    / `TikTok không báo lỗi nào`. Reads only the tool's own `label_vi` values,
    never a raw code or vendor text. Anything unexpected falls back to
    `Hoàn tất` -- a summary must never fail a run.
    """
    # Fast track P14-E: a tool that words its own seller-facing summary.
    own = result.get("summary_vi")
    if isinstance(own, str) and own.strip():
        return own.strip()
    if tool_name == _PROMOTIONS_TOOL:
        return _promotions_summary(result)
    if tool_name != _DIAGNOSES_TOOL:
        return SellerFacingCompletionReason.COMPLETED.value
    if result.get("unavailable") is True:
        return _DIAGNOSES_UNAVAILABLE_SUMMARY
    entries = result.get("codes")
    if not isinstance(entries, list):
        return SellerFacingCompletionReason.COMPLETED.value
    labels = [
        label
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(label := entry.get("label_vi"), str) and label
    ]
    if not labels:
        return _DIAGNOSES_NONE_SUMMARY
    shown = ", ".join(labels[:_DIAGNOSES_SHOWN_LABELS])
    extra = len(labels) - _DIAGNOSES_SHOWN_LABELS
    return shown + (f" và {extra} lỗi khác" if extra > 0 else "")


#: P64 (run 74aefd1a): the step label of a WRITE that changed nothing on TikTok --
#: the handler returned ``ok: false`` (TikTok refused it) or the call raised.
WRITE_FAILED_SUMMARY = "Không thành công"


def write_refused(result: Mapping[str, Any]) -> bool:
    """A WRITE result that says it changed nothing: the handler's own ``ok: false``.

    Only an explicit ``False`` counts -- a write tool whose output has no ``ok``
    field reports a vendor failure by raising instead.
    """
    return result.get("ok") is False


def write_failed_summary(
    result: Mapping[str, Any] | None = None, exc: BaseException | None = None
) -> str:
    """The seller-facing `ToolCompletedPayload.summary` of a failed WRITE.

    The tool's own ``summary_vi`` (it already words TikTok's reason, e.g. "TikTok
    từ chối tạo sản phẩm (mã lỗi 12052217): ...") when it returned one; for a call
    that raised, TikTok's numeric code only -- never the exception text.
    """
    if result is not None:
        own = result.get("summary_vi")
        if isinstance(own, str) and own.strip():
            return f"{WRITE_FAILED_SUMMARY} · {own.strip()}"
    code = getattr(exc, "code", None) if exc is not None else None
    if isinstance(code, int) and code:
        return f"{WRITE_FAILED_SUMMARY} · TikTok báo lỗi (mã lỗi {code})"
    return WRITE_FAILED_SUMMARY

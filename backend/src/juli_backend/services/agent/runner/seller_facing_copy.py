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


#: Fast track P10-A (contract p10-quyet-dinh.md §3): the write ran with the
#: title / description the seller edited at the consent step.
EDITED_BY_SELLER_SUMMARY = "Hoàn tất theo bản bạn sửa"

_DIAGNOSES_TOOL = "get_product_diagnoses"
_DIAGNOSES_NONE_SUMMARY = "Không có mã chẩn đoán"
_DIAGNOSES_SHOWN_LABELS = 3
_DIAGNOSES_UNAVAILABLE_SUMMARY = "Không đọc được chẩn đoán TikTok — tiếp tục với thông tin sản phẩm"


def tool_completed_summary(tool_name: str, result: Mapping[str, Any]) -> str:
    """The seller-facing `ToolCompletedPayload.summary` for a successful tool.

    `Hoàn tất` for every tool except `get_product_diagnoses`, whose summary
    names what TikTok flagged (AC-8.4): `Có mã: "Giá kém cạnh tranh"` /
    `Không có mã chẩn đoán`. Reads only the tool's own `label_vi` values,
    never a raw code or vendor text. Anything unexpected falls back to
    `Hoàn tất` -- a summary must never fail a run.
    """
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
    shown = ", ".join(f'"{label}"' for label in labels[:_DIAGNOSES_SHOWN_LABELS])
    extra = len(labels) - _DIAGNOSES_SHOWN_LABELS
    return f"Có mã: {shown}" + (f" và {extra} mã khác" if extra > 0 else "")

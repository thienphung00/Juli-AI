"""Seller-facing reason codes and Vietnamese copy (issue #1272 / W6-B/P-UI-3).

This module provides seller-facing copy for `ToolCompletedPayload.summary`
and other direct-to-seller messages. All strings are Vietnamese and reviewed
per ADR-072 (copy governance) and ADR-074 d.2 (seller-facing surface).

The module is deliberately separate from `core.py` so internal logging can
keep server-side detail while seller copy stays safe.
"""

from __future__ import annotations

from enum import StrEnum


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

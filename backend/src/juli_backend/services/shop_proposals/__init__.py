"""The manual cycle (ADR-118): proposals an operator writes, the client approves and a
person executes; results come from ``platform_daily_metrics``.

``api/routes/ops_proposals.py`` is the Ops skin over this package; the seller's in-app
approval is a later route over the same functions.
"""

from __future__ import annotations

from juli_backend.services.shop_proposals.cycle import (
    ERROR_BAD_STATE,
    ERROR_INVALID,
    ERROR_NOT_FOUND,
    ERROR_UNKNOWN_ITEM,
    ProposalDraft,
    ProposalError,
    create,
    get,
    list_cycle,
    record_approval,
    record_execution,
    revise,
    send,
    snapshot,
    verify_execution,
    withdraw,
)

__all__ = [
    "ERROR_BAD_STATE",
    "ERROR_INVALID",
    "ERROR_NOT_FOUND",
    "ERROR_UNKNOWN_ITEM",
    "ProposalDraft",
    "ProposalError",
    "create",
    "get",
    "list_cycle",
    "record_approval",
    "record_execution",
    "revise",
    "send",
    "snapshot",
    "verify_execution",
    "withdraw",
]

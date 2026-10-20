"""Run terminal status -> ``executed`` / ``not_executed`` and its group (ADR-107 decision 6).

``executed`` = the run completed with its final response (the change was
applied, or for a lever flow, verified). Every other terminal ending is
``not_executed``; the original ``stop_reason`` is kept on the event and the
group is derived here. Codes decision 6 does not list are placed by meaning
(``cancelled_by_seller`` -> declined, ``external_wait_expired`` -> the seller's
part never arrived, like an expired consent); anything unknown is
``system_error``.
"""

from __future__ import annotations

TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled", "timed_out"})

GROUP_SELLER_DECLINED = "seller_declined_confirmation"
GROUP_CONFIRMATION_EXPIRED = "confirmation_expired"
GROUP_TIKTOK_REJECTED = "tiktok_rejected"
GROUP_SHOP_PRECONDITION = "shop_precondition_missing"
GROUP_NOTHING_TO_CHANGE = "nothing_to_change"
GROUP_SYSTEM_ERROR = "system_error"

NOT_EXECUTED_GROUPS: dict[str, str] = {
    "declined": GROUP_SELLER_DECLINED,
    "confirmation_declined": GROUP_SELLER_DECLINED,
    "cancelled_by_seller": GROUP_SELLER_DECLINED,
    "confirmation_expired": GROUP_CONFIRMATION_EXPIRED,
    "external_wait_expired": GROUP_CONFIRMATION_EXPIRED,
    "price_lever_locked": GROUP_TIKTOK_REJECTED,
    "aov_lever_locked": GROUP_TIKTOK_REJECTED,
    "audit_rejected": GROUP_TIKTOK_REJECTED,
    "discount_cap_unset": GROUP_SHOP_PRECONDITION,
    "scope_unavailable": GROUP_SHOP_PRECONDITION,
    "no_diagnosis_codes": GROUP_NOTHING_TO_CHANGE,
    "concluded_without_changes": GROUP_NOTHING_TO_CHANGE,
}

EXECUTED_STOP_REASON = "final_response"


def is_executed(status: str, stop_reason: str | None) -> bool:
    return status == "completed" and stop_reason == EXECUTED_STOP_REASON


def not_executed_group(stop_reason: str | None) -> str:
    return NOT_EXECUTED_GROUPS.get(stop_reason or "", GROUP_SYSTEM_ERROR)

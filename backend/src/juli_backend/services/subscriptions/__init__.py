"""Shop subscription terms (fast track P20, DECISIONS D28.4 / D28.5).

``grant_period`` is the one way a period is added: Juli Ops (``source="contract"``)
today, the payment system (``source="payment"``) later -- idempotent on the
reference. ``shop_term`` is the state every reader shows; ``is_read_only`` is
the enforcement read used by card emission, agent runs and OpenAI drafting.
"""

from juli_backend.services.subscriptions.terms import (
    GRACE_DAYS,
    NO_TERM,
    READ_ONLY_CODE,
    READ_ONLY_DETAIL,
    SOON_DAYS,
    STATE_GRACE,
    STATE_NONE,
    STATE_OK,
    STATE_READ_ONLY,
    STATE_SOON,
    Grant,
    GrantError,
    ShopTerm,
    expiry,
    grant_period,
    is_read_only,
    list_periods,
    next_period_dates,
    period_json,
    shop_term,
    shop_today,
    term_for,
)

__all__ = [
    "GRACE_DAYS",
    "NO_TERM",
    "READ_ONLY_CODE",
    "READ_ONLY_DETAIL",
    "SOON_DAYS",
    "STATE_GRACE",
    "STATE_NONE",
    "STATE_OK",
    "STATE_READ_ONLY",
    "STATE_SOON",
    "Grant",
    "GrantError",
    "ShopTerm",
    "expiry",
    "grant_period",
    "is_read_only",
    "list_periods",
    "next_period_dates",
    "period_json",
    "shop_term",
    "shop_today",
    "term_for",
]

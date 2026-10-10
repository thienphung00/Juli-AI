"""Seller reasons and the 7-day per-lever cooldown (fast track P10-A, ADR-109 am. 1 d.7).

Contract ``fasttrack/contracts/p10-quyet-dinh.md`` §2. "Từ chối" (a card),
"Không thực hiện" (a run's consent step) and "Hoàn tác" (a finished run) each
require exactly one reason code from the action's own list, plus an optional
note of at most 300 characters. :func:`record_reason` stores it with who and
when, and the (product, lever) it cools down.

**Cooldown.** After any of the three actions the same lever is not proposed
again for that product for :data:`COOLDOWN_DAYS` days, unless the product's
data changed clearly. "Clearly", conservatively: the weak stage's rate the card
was proposed on (``basis_rate``, the CTR / CTOR / AOV of
``recoverable_gmv_basis``) moved by more than :data:`CLEAR_CHANGE_RELATIVE`
(20 %) relative to that value, in either direction. A move of 20 % or less --
ordinary day-to-day noise for a product's 14-day rate -- keeps the cooldown.
No stored rate, or no current rate, never lifts it: only the clock does.

Pure policy + two small queries; no commit (the routes commit).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.decision_reasons import (
    ACTION_DECLINE,
    ACTION_REJECT,
    ACTION_REVERT,
    NOTE_MAX_CHARS,
    DecisionReason,
)
from juli_backend.models.models import ActionCard

COOLDOWN_DAYS = 7
#: Relative move of the weak-stage rate that counts as a clear data change.
CLEAR_CHANGE_RELATIVE = Decimal("0.20")

#: The suppression reason card generation logs for a cooled-down proposal.
SUPPRESSED_REASON_DECISION_COOLDOWN = "decision_cooldown"

#: Reason codes per action, with the dialog's Vietnamese label (ADR-109 am. 1 d.7).
REASON_LABELS_VI: Mapping[str, Mapping[str, str]] = {
    ACTION_REJECT: {
        "brand_mismatch": "Không hợp thương hiệu hoặc giọng văn",
        "not_convincing": "Lý do hoặc số liệu chưa thuyết phục",
        "editing_myself": "Tôi đang tự sửa sản phẩm này",
        "discontinued": "Sắp ngừng bán hoặc hết hàng",
        "other_campaign": "Đang chạy chiến dịch khác",
        "other": "Khác",
    },
    ACTION_DECLINE: {
        "wrong_info": "Nội dung sai thông tin sản phẩm",
        "tone": "Văn phong chưa phù hợp",
        "too_much_change": "Thay đổi quá nhiều",
        "changed_mind": "Đổi ý",
        "other": "Khác",
    },
    ACTION_REVERT: {
        "metrics_dropped": "Doanh số hoặc chỉ số giảm",
        "bad_feedback": "Khách phản hồi không tốt",
        "wrong_info": "Nội dung sai thông tin sản phẩm",
        "off_brand": "Không hợp giọng thương hiệu",
        "tiktok_warning": "TikTok cảnh báo sản phẩm",
        "other": "Khác",
    },
}

#: Diagnosis stage code -> the rate the D22 estimate is built on.
_STAGE_RATE = {"card": "ctr", "page": "ctor", "basket": "aov"}


class InvalidReason(ValueError):
    """The reason code is not one of the action's codes, or the note is too long."""


def reason_codes(action: str) -> tuple[str, ...]:
    return tuple(REASON_LABELS_VI[action])


def validate_reason(action: str, reason_code: str | None, note: str | None) -> str | None:
    """Raise :class:`InvalidReason` unless ``reason_code`` is one of ``action``'s.

    Returns the note, stripped, or ``None`` when empty.
    """
    if not reason_code or reason_code not in REASON_LABELS_VI[action]:
        raise InvalidReason(f"reason_code must be one of {list(REASON_LABELS_VI[action])}")
    cleaned = (note or "").strip()
    if len(cleaned) > NOTE_MAX_CHARS:
        raise InvalidReason(f"note must be at most {NOTE_MAX_CHARS} characters")
    return cleaned or None


@dataclass(frozen=True)
class CardBasis:
    """What a card was proposed on: its lever and the weak stage's rate."""

    lever_code: str | None
    stage_rate: str | None
    rate: float | None


def _payload(card: ActionCard | None) -> Mapping[str, Any]:
    if card is None:
        return {}
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def card_basis(card: ActionCard | None) -> CardBasis:
    """The lever and weak-stage rate of an ADR-106 card (all ``None`` otherwise)."""
    diagnosis = _payload(card).get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        return CardBasis(None, None, None)
    lever = diagnosis.get("lever")
    lever_code = lever.get("code") if isinstance(lever, Mapping) else None
    basis = diagnosis.get("recoverable_gmv_basis")
    if isinstance(basis, Mapping) and basis.get("stage_rate"):
        rate = basis.get("current_rate")
        return CardBasis(
            str(lever_code) if lever_code else None,
            str(basis["stage_rate"]),
            float(rate) if isinstance(rate, int | float) else None,
        )
    stage = diagnosis.get("stage")
    stage_code = stage.get("code") if isinstance(stage, Mapping) else None
    stage_rate = _STAGE_RATE.get(str(stage_code)) if stage_code else None
    gaps = diagnosis.get("gaps")
    gap = gaps.get(stage_rate) if isinstance(gaps, Mapping) and stage_rate else None
    value = gap.get("value") if isinstance(gap, Mapping) else None
    return CardBasis(
        str(lever_code) if lever_code else None,
        stage_rate,
        float(value) if isinstance(value, int | float) else None,
    )


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)


async def record_reason(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    action: str,
    reason_code: str,
    note: str | None,
    decided_by_user_id: uuid.UUID | None,
    card: ActionCard | None = None,
    workflow_run_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> DecisionReason:
    """Insert one reason row (validated) and return it. Flush, no commit."""
    cleaned_note = validate_reason(action, reason_code, note)
    decided_at = _naive_utc(now)
    basis = card_basis(card)
    row = DecisionReason(
        shop_id=shop_id,
        action=action,
        reason_code=reason_code,
        note=cleaned_note,
        action_card_id=card.id if card is not None else None,
        workflow_run_id=workflow_run_id,
        product_id=product_id,
        lever_code=basis.lever_code,
        basis_stage_rate=basis.stage_rate,
        basis_rate=basis.rate,
        decided_by_user_id=decided_by_user_id,
        decided_at=decided_at,
        cooldown_until=decided_at + timedelta(days=COOLDOWN_DAYS),
    )
    session.add(row)
    await session.flush()
    return row


async def active_cooldowns(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> dict[tuple[str, str], DecisionReason]:
    """``(products.id, lever_code)`` -> the newest reason still inside its 7 days."""
    current = _naive_utc(now)
    rows = (
        (
            await session.execute(
                select(DecisionReason)
                .where(
                    DecisionReason.shop_id == shop_id,
                    DecisionReason.product_id.isnot(None),
                    DecisionReason.lever_code.isnot(None),
                    DecisionReason.cooldown_until > current,
                )
                .order_by(DecisionReason.decided_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {(str(row.product_id), str(row.lever_code)): row for row in rows}


def clearly_changed(reason: DecisionReason, current_rates: Mapping[str, Decimal | None]) -> bool:
    """Whether the weak stage's rate moved > 20 % relative since the reason (see module)."""
    if reason.basis_stage_rate is None or reason.basis_rate is None or reason.basis_rate <= 0:
        return False
    current = current_rates.get(reason.basis_stage_rate)
    if current is None:
        return False
    basis = Decimal(str(reason.basis_rate))
    return abs(Decimal(current) - basis) / basis > CLEAR_CHANGE_RELATIVE


#: D24.6: how long a seller reason keeps lowering its lever's priority, how
#: much a fresh one lowers it, and the floor (a lever is never buried).
PENALTY_WINDOW_DAYS = 60
PENALTY_PER_REASON = Decimal("0.2")
PENALTY_FLOOR = Decimal("0.4")

#: Reason codes about the seller's circumstances, not about the action itself;
#: they carry no penalty (the 7-day cooldown still applies).
CIRCUMSTANTIAL_REASON_CODES: frozenset[str] = frozenset(
    {"editing_myself", "discontinued", "other_campaign", "changed_mind"}
)


def reason_penalty(ages_days: list[float]) -> Decimal:
    """``max(0.4, 1 − 0.2 × Σ max(0, 1 − age ÷ 60))`` over the counted reasons.

    One fresh reason → 0.8; it fades linearly to no effect at 60 days; three
    fresh reasons reach the 0.4 floor.
    """
    total = Decimal(0)
    for age in ages_days:
        fade = Decimal(1) - Decimal(str(max(age, 0.0))) / Decimal(PENALTY_WINDOW_DAYS)
        if fade > 0:
            total += fade
    return max(PENALTY_FLOOR, Decimal(1) - PENALTY_PER_REASON * total).quantize(Decimal("0.0001"))


async def reason_penalties(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, Decimal]:
    """lever code -> :func:`reason_penalty` from the shop's last 60 days of reasons.

    Per (shop, lever), across products (D24.6: the reasons lower *that
    action's* priority for the shop). Levers without a counted reason are
    absent (neutral).
    """
    current = _naive_utc(now)
    since = current - timedelta(days=PENALTY_WINDOW_DAYS)
    rows = (
        (
            await session.execute(
                select(DecisionReason).where(
                    DecisionReason.shop_id == shop_id,
                    DecisionReason.lever_code.isnot(None),
                    DecisionReason.decided_at > since,
                )
            )
        )
        .scalars()
        .all()
    )
    ages: dict[str, list[float]] = {}
    for row in rows:
        if row.reason_code in CIRCUMSTANTIAL_REASON_CODES or row.lever_code is None:
            continue
        decided = row.decided_at.replace(tzinfo=None) if row.decided_at.tzinfo else row.decided_at
        age = (current - decided).total_seconds() / 86400
        ages.setdefault(str(row.lever_code), []).append(age)
    return {lever: reason_penalty(values) for lever, values in ages.items()}


def cooldown_until_iso(reason: DecisionReason) -> str:
    return reason.cooldown_until.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


#: Card statuses a seller action closes. ``approved`` / ``executing``: the card
#: a declined or reverted run came from -- left there it would stand forever
#: (``persist._card_still_stands`` never time-boxes them) and the 7 days could
#: never lift.
_CLOSABLE_CARD_STATUSES = frozenset({"active", "approved", "executing"})
DISMISSED_CARD_STATUS = "dismissed"


def close_card(card: ActionCard | None, *, now: datetime | None = None) -> None:
    """Mark the card dismissed (taken off the desk; the cooldown governs what follows)."""
    if card is None or card.status not in _CLOSABLE_CARD_STATUSES:
        return
    card.status = DISMISSED_CARD_STATUS
    card.dismissed_at = (now or datetime.now(UTC)).astimezone(UTC)
    card.surfaced_at = None


def product_id_of(card: ActionCard | None) -> uuid.UUID | None:
    """The ``products.id`` a product-subject card is about, else ``None``."""
    if card is None or card.subject_type != "product" or not card.subject_id:
        return None
    try:
        return uuid.UUID(card.subject_id)
    except ValueError:
        return None

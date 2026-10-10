"""The per-shop monthly OpenAI cost cap (D25.8), shared by P15 and P16.

ONE storage for every reader: a ``shop_rules`` row with ``rule_key =
"openai_monthly_cap_usd"`` (shop-wide, ``scope_ref = ''``), value a USD number.
No row = the default, ``OPENAI_MONTHLY_CAP_USD_DEFAULT`` (env, $5/month).

It is a TEAM setting, not a seller rule: it is deliberately NOT in
``rules.RULE_KEYS``, so the seller's ``/v1/demo/rules`` refuses it; Juli Ops
"Cài đặt shop" writes it (audited) through :func:`set_openai_monthly_cap`.
P15 content analysis (ASR / vision / scoring) and P16 drafting / agent runs read
it through :func:`openai_monthly_cap_usd`, under the shop's own scope.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRule

OPENAI_MONTHLY_CAP_USD = "openai_monthly_cap_usd"
DEFAULT_CAP_ENV = "OPENAI_MONTHLY_CAP_USD_DEFAULT"
FALLBACK_DEFAULT_USD = Decimal("5")
CAP_MAX_USD = Decimal("1000")


class CapValidationError(ValueError):
    pass


@dataclass(frozen=True)
class OpenAICap:
    usd: Decimal
    is_default: bool
    set_at: datetime | None = None


def default_cap_usd() -> Decimal:
    raw = os.environ.get(DEFAULT_CAP_ENV, "").strip()
    if not raw:
        return FALLBACK_DEFAULT_USD
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return FALLBACK_DEFAULT_USD
    return value if value.is_finite() and value >= 0 else FALLBACK_DEFAULT_USD


def validate_cap(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CapValidationError("openai_monthly_cap_usd must be a number")
    try:
        cap = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CapValidationError("openai_monthly_cap_usd must be a number") from None
    if not cap.is_finite() or not Decimal(0) <= cap <= CAP_MAX_USD:
        raise CapValidationError("openai_monthly_cap_usd must be between 0 and 1000")
    return cap.quantize(Decimal("0.01"))


async def _row(session: AsyncSession, shop_id: uuid.UUID) -> ShopRule | None:
    return (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == OPENAI_MONTHLY_CAP_USD,
                ShopRule.scope_ref == "",
            )
        )
    ).scalar_one_or_none()


async def openai_monthly_cap_usd(session: AsyncSession, shop_id: uuid.UUID) -> OpenAICap:
    """The shop's cap (its row, else the default). Caller holds the shop's scope."""
    row = await _row(session, shop_id)
    if row is not None:
        try:
            return OpenAICap(usd=validate_cap(row.value), is_default=False, set_at=row.set_at)
        except CapValidationError:
            pass
    return OpenAICap(usd=default_cap_usd(), is_default=True)


async def set_openai_monthly_cap(
    session: AsyncSession, shop_id: uuid.UUID, value: Any, *, set_by_user_id: uuid.UUID | None
) -> OpenAICap:
    cap = validate_cap(value)
    now = datetime.now(UTC).replace(tzinfo=None)
    row = await _row(session, shop_id)
    stored: int | float = int(cap) if cap == cap.to_integral_value() else float(cap)
    if row is None:
        session.add(
            ShopRule(
                shop_id=shop_id,
                rule_key=OPENAI_MONTHLY_CAP_USD,
                scope_ref="",
                value=stored,
                set_by="team",
                set_by_user_id=set_by_user_id,
                set_at=now,
            )
        )
    else:
        row.value = stored
        row.set_by = "team"
        row.set_by_user_id = set_by_user_id
        row.set_at = now
    await session.flush()
    return OpenAICap(usd=cap, is_default=False, set_at=now)


async def clear_openai_monthly_cap(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    row = await _row(session, shop_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True

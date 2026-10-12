"""Per-shop monthly OpenAI cost cap (fast track P15; D25.4 / D25.8).

The shop's OpenAI spend this month = the cost of its workflow runs
(``workflow_runs.cost_usd``, the drafting runs) + the cost of its content
analyses (``content_analyses.cost_usd``), from the first day of the shop's
month (UTC+7). Before every paid step (ASR, vision, scoring) the pipeline asks
``check`` whether ``spent + this step's estimate`` stays within the cap; over
it, the step is refused with a Vietnamese message and the analysis ends
``refused`` (nothing more is spent).

The cap and the month's spend come from ONE accessor shared with P16's
drafting / agent-run gates (``services/shop_rules/openai_cap.py``): the
``shop_rules`` row ``openai_monthly_cap_usd`` (written by Juli Ops), else
``OPENAI_MONTHLY_CAP_USD_DEFAULT`` (default 5 USD).

Fast track P20 adds a refusal checked first, with its own code:
``shop_read_only`` when the shop's term has run out past its grace (D28.4,
``services/subscriptions``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shop_rules import openai_cap

CAP_RULE_KEY = openai_cap.OPENAI_MONTHLY_CAP_USD

CAP_REACHED_CODE = "cost_cap_reached"
READ_ONLY_CODE = "shop_read_only"


def cap_message(spent: float, cap: float) -> str:
    return (
        f"Shop đã dùng hết hạn mức phân tích bằng AI của tháng này "
        f"({spent:.2f} / {cap:.2f} USD). Juli chưa phân tích thêm video cho tới tháng sau "
        "hoặc khi đội Juli nâng hạn mức."
    )


class CostCapExceeded(Exception):
    def __init__(
        self,
        spent: float,
        cap: float,
        estimate: float,
        *,
        code: str = CAP_REACHED_CODE,
        message_vi: str | None = None,
    ) -> None:
        super().__init__(f"{code}: spent {spent:.4f} + {estimate:.4f} > {cap:.4f}")
        self.spent = spent
        self.cap = cap
        self.estimate = estimate
        self.code = code
        self.message_vi = message_vi or cap_message(spent, cap)


@dataclass(frozen=True)
class Budget:
    spent_usd: float
    cap_usd: float

    @property
    def left_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)


def month_start_utc(now: datetime | None = None) -> datetime:
    """The first instant of the shop's (UTC+7) month, as naive UTC."""
    return openai_cap.month_start_utc(now)


async def monthly_cap_usd(session: AsyncSession, shop_id: uuid.UUID) -> float:
    return float((await openai_cap.openai_monthly_cap_usd(session, shop_id)).usd)


async def monthly_spend_usd(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> float:
    return float(await openai_cap.openai_spend_this_month(session, shop_id, now=now))


async def budget(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> Budget:
    return Budget(
        spent_usd=await monthly_spend_usd(session, shop_id, now=now),
        cap_usd=await monthly_cap_usd(session, shop_id),
    )


async def check(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    estimate_usd: float = 0.0,
    pending_usd: float = 0.0,
    now: datetime | None = None,
) -> Budget:
    """Raise ``CostCapExceeded`` unless ``spent + pending + estimate`` ≤ the cap.

    ``pending_usd`` is what the current analysis has spent but not stored yet.
    Refused first, with its own code: a read-only shop (D28.4).
    """
    from juli_backend.services.subscriptions import READ_ONLY_DETAIL, is_read_only

    if await is_read_only(session, shop_id):
        raise CostCapExceeded(
            0.0, 0.0, estimate_usd, code=READ_ONLY_CODE, message_vi=READ_ONLY_DETAIL
        )
    current = await budget(session, shop_id, now=now)
    spent = current.spent_usd + pending_usd
    if spent >= current.cap_usd or spent + estimate_usd > current.cap_usd:
        raise CostCapExceeded(spent, current.cap_usd, estimate_usd)
    return current


__all__ = [
    "CAP_REACHED_CODE",
    "CAP_RULE_KEY",
    "READ_ONLY_CODE",
    "Budget",
    "CostCapExceeded",
    "budget",
    "cap_message",
    "check",
    "month_start_utc",
    "monthly_cap_usd",
    "monthly_spend_usd",
]

"""Per-shop monthly OpenAI cost cap (fast track P15; D25.4 / D25.8).

The shop's OpenAI spend this month = the cost of its workflow runs
(``workflow_runs.cost_usd``, the drafting runs) + the cost of its content
analyses (``content_analyses.cost_usd``), from the first day of the shop's
month (UTC+7). Before every paid step (ASR, vision, scoring) the pipeline asks
``check`` whether ``spent + this step's estimate`` stays within the cap; over
it, the step is refused with a Vietnamese message and the analysis ends
``refused`` (nothing more is spent).

The cap: a per-shop override stored as the ``shop_rules`` row
``openai_monthly_cap_usd`` (a number; P16's Ops console owns writing it), else
``OPENAI_MONTHLY_COST_CAP_USD`` (default 5 USD).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.models import WorkflowRun
from juli_backend.models.run_changes import ShopRule
from juli_backend.services.content_analysis.config import settings

CAP_RULE_KEY = "openai_monthly_cap_usd"
_SHOP_TZ = timezone(timedelta(hours=7))

CAP_REACHED_CODE = "cost_cap_reached"


def cap_message(spent: float, cap: float) -> str:
    return (
        f"Shop đã dùng hết hạn mức phân tích bằng AI của tháng này "
        f"({spent:.2f} / {cap:.2f} USD). Juli chưa phân tích thêm video cho tới tháng sau "
        "hoặc khi đội Juli nâng hạn mức."
    )


class CostCapExceeded(Exception):
    def __init__(self, spent: float, cap: float, estimate: float) -> None:
        super().__init__(f"monthly OpenAI cap: spent {spent:.4f} + {estimate:.4f} > {cap:.4f}")
        self.spent = spent
        self.cap = cap
        self.estimate = estimate
        self.code = CAP_REACHED_CODE
        self.message_vi = cap_message(spent, cap)


@dataclass(frozen=True)
class Budget:
    spent_usd: float
    cap_usd: float

    @property
    def left_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)


def month_start_utc(now: datetime | None = None) -> datetime:
    """The first instant of the shop's (UTC+7) month, as naive UTC."""
    local = (now or datetime.now(UTC)).astimezone(_SHOP_TZ)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(UTC).replace(tzinfo=None)


async def monthly_cap_usd(session: AsyncSession, shop_id: uuid.UUID) -> float:
    row = (
        await session.execute(
            select(ShopRule.value).where(
                ShopRule.shop_id == shop_id, ShopRule.rule_key == CAP_RULE_KEY
            )
        )
    ).first()
    value = row[0] if row is not None else None
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("usd"), int | float):
        return max(0.0, float(value["usd"]))
    return settings().monthly_cap_usd


async def monthly_spend_usd(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> float:
    since = month_start_utc(now)
    runs = (
        await session.execute(
            select(func.coalesce(func.sum(WorkflowRun.cost_usd), 0)).where(
                WorkflowRun.shop_id == shop_id, WorkflowRun.created_at >= since
            )
        )
    ).scalar_one()
    analyses = (
        await session.execute(
            select(func.coalesce(func.sum(ContentAnalysis.cost_usd), 0)).where(
                ContentAnalysis.shop_id == shop_id, ContentAnalysis.created_at >= since
            )
        )
    ).scalar_one()
    return float(Decimal(str(runs or 0)) + Decimal(str(analyses or 0)))


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
    """
    current = await budget(session, shop_id, now=now)
    spent = current.spent_usd + pending_usd
    if spent >= current.cap_usd or spent + estimate_usd > current.cap_usd:
        raise CostCapExceeded(spent, current.cap_usd, estimate_usd)
    return current


__all__ = [
    "CAP_REACHED_CODE",
    "CAP_RULE_KEY",
    "Budget",
    "CostCapExceeded",
    "budget",
    "cap_message",
    "check",
    "month_start_utc",
    "monthly_cap_usd",
    "monthly_spend_usd",
]

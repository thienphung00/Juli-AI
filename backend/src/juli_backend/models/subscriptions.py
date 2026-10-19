"""Shop subscription periods (fast track P20, DECISIONS D28.4 / D28.5), migration 086.

One row per granted period. Expiry = the latest ``ends_on``. ``source`` is
``contract`` (an Admin in Juli Ops, ``reference`` = the contract number) or
``payment`` (the future payment system, ``reference`` = its transaction id);
``(source, reference)`` is unique, which makes the grant idempotent. A tenant
table (RLS by ``app_current_shop_id()``); the history is append-only.

Timestamps naive UTC; dates are the shop's (UTC+7) calendar days.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

PLAN_MONTH = "month"
PLAN_YEAR = "year"
PLAN_BY_DAYS: dict[int, str] = {30: PLAN_MONTH, 365: PLAN_YEAR}
SOURCE_CONTRACT = "contract"
SOURCE_PAYMENT = "payment"
SOURCES: tuple[str, ...] = (SOURCE_CONTRACT, SOURCE_PAYMENT)


class ShopSubscriptionPeriod(Base):
    __tablename__ = "shop_subscription_periods"
    __table_args__ = (
        UniqueConstraint("source", "reference", name="uq_shop_subscription_periods_ref"),
        CheckConstraint("plan IN ('month', 'year')", name="ck_shop_subscription_periods_plan"),
        CheckConstraint("days IN (30, 365)", name="ck_shop_subscription_periods_days"),
        CheckConstraint(
            "source IN ('contract', 'payment')", name="ck_shop_subscription_periods_source"
        ),
        Index("ix_shop_subscription_periods_shop_ends", "shop_id", "ends_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: NULL once the shop's owner deleted their account (P50-B, migration 094): the
    #: period is kept as a contract / payment record (D68.10) without the shop.
    shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    plan: Mapped[str] = mapped_column(String(16))
    days: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(120))
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

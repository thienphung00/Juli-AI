"""Card groups with a randomised delayed control (D34 / D39.3, fast track P30), migration 089.

Two tenant-direct tables (each row carries ``shop_id``; RLS by ``app_current_shop_id()``):

- ``card_groups`` -- one wave of Optimize Product cards that share a target
  metric × lever × KPI channel within a shop ("CTR · Ảnh bìa · Thẻ sản phẩm"):
  its launch day (the shop's day the arms were drawn), the day the control
  cards are released (launch + 14), the random seed the draw used, and -- once
  measured at day 14 -- the verdict (difference of medians, bootstrap
  interval, wording, per-product changes).
- ``card_group_members`` -- one product of a group: its arm (``treated`` /
  ``control``), the card it was drawn with, and when a control card was
  released. Intent-to-treat: the arm never changes after the draw.

Timestamps naive UTC; ``launched_on`` / ``release_on`` are the shop's (UTC+7) days.

Migration 092 (fast track P36, D45) adds ``card_groups.design`` (JSON, nullable):
who made the group (``source`` = ``cards`` -- drawn from Optimize Product drafts --
or ``ops`` -- created in Juli Ops for a lever Juli does not propose, e.g. a new pack
option), the optional one-line "lý do chọn thử nghiệm", and whether the
product-card CTR guard is read. ``NULL`` = a card-drawn group without a reason.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

ARM_TREATED = "treated"
ARM_CONTROL = "control"

GROUP_OPEN = "open"
GROUP_MEASURED = "measured"


class CardGroup(Base):
    """One wave of cards sharing metric × lever × channel, with its control draw."""

    __tablename__ = "card_groups"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'measured')", name="ck_card_groups_status"),
        Index("ix_card_groups_shop_key", "shop_id", "group_key", "launched_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    #: ``<metric>|<lever>|<channel>`` (e.g. ``ctr|cover_image|product_card``).
    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    lever: Mapped[str] = mapped_column(String(48), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    launched_on: Mapped[date] = mapped_column(Date, nullable=False)
    release_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: The seed the arms were drawn with (the draw is reproducible from it).
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=GROUP_OPEN)
    #: The day-14 verdict (``card_groups.verdict_json``); ``None`` until measured.
    verdict: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: D45 (P36, migration 092): ``{source, reason, guard, created_by}``; ``None`` = cards.
    design: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    measured_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class CardGroupMember(Base):
    """One product of a group and its arm (intent-to-treat)."""

    __tablename__ = "card_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "tiktok_product_id", name="uq_card_group_members_product"),
        CheckConstraint("arm IN ('treated', 'control')", name="ck_card_group_members_arm"),
        Index("ix_card_group_members_shop_product", "shop_id", "tiktok_product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("card_groups.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The card the product was drawn with (a later revision keeps the arm).
    action_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_cards.id"))
    arm: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(nullable=False)
    #: A control card's release (launch + 14 days); ``None`` for treated / not yet.
    released_at: Mapped[datetime | None] = mapped_column()


__all__ = [
    "ARM_CONTROL",
    "ARM_TREATED",
    "GROUP_MEASURED",
    "GROUP_OPEN",
    "CardGroup",
    "CardGroupMember",
]

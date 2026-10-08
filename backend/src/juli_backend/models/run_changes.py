"""Run write values, seller rules and revert questions (fast track P8-C, ADR-109 d.9-12).

Three tables, all tenant-direct (each row carries ``shop_id``):

- ``run_write_values`` -- for every field an agent WRITE changed on TikTok, the
  value read immediately before the write and the value after it, per run and
  per tool call. This is what a "Hoàn tác" run restores, and what it compares
  the live listing against before restoring (S-FR-8).
- ``shop_rules`` -- the seller-set rules of ADR-109 d.12 (stability band per
  metric, cost per product, minimum margin, maximum discount per SKU, maximum
  open cards, auto-executable levers, protected terms). One row per
  (shop, rule, scope); every value records who set it (``team`` or ``seller``),
  which user, and when.
- ``run_revert_questions`` -- the day-7 guardrail's "Hoàn tác?" question for a
  run whose non-target metrics left the seller's band (ADR-109 d.11). Juli asks;
  it never reverts on its own.

Kept in its own module, like ``models/shop_diagnosis.py``, and registered on
``Base.metadata`` through ``juli_backend.models.__init__``. Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: Who set a rule value (ADR-109 d.12: the operator phase has the Juli team
#: fill values on the seller's behalf; the seller takes over later).
SET_BY_TEAM = "team"
SET_BY_SELLER = "seller"
SET_BY_VALUES: tuple[str, ...] = (SET_BY_TEAM, SET_BY_SELLER)

#: Where a recorded after-value came from: read back from TikTok right after the
#: write, or -- when the read-back still showed the old value (a listing edit
#: under TikTok review) -- the value Juli sent.
AFTER_SOURCE_READ_BACK = "read_back"
AFTER_SOURCE_INTENDED = "intended"

QUESTION_OPEN = "open"
QUESTION_REVERTED = "reverted"
QUESTION_DISMISSED = "dismissed"
QUESTION_STATUSES: tuple[str, ...] = (QUESTION_OPEN, QUESTION_REVERTED, QUESTION_DISMISSED)


class RunWriteValue(Base):
    """One field one agent WRITE changed: its value before and after the write."""

    __tablename__ = "run_write_values"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "tool_call_id", "field", name="uq_run_write_values_call_field"
        ),
        Index("ix_run_write_values_run", "workflow_run_id"),
        CheckConstraint(
            "after_source IN ('read_back', 'intended')", name="ck_run_write_values_after_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The TikTok product the write touched (``products.tiktok_product_id``).
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    #: ``title`` / ``description`` / ``main_images`` / ``price``.
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    before_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    after_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    after_source: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ShopRule(Base):
    """One seller-set rule value (ADR-109 d.12) for one shop and scope."""

    __tablename__ = "shop_rules"
    __table_args__ = (
        UniqueConstraint("shop_id", "rule_key", "scope_ref", name="uq_shop_rules_key"),
        CheckConstraint("set_by IN ('team', 'seller')", name="ck_shop_rules_set_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    rule_key: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The rule's subject: a metric key, a TikTok product id, a TikTok SKU id, or
    #: ``""`` for a shop-wide rule.
    scope_ref: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    set_by: Mapped[str] = mapped_column(String(10), nullable=False)
    set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    set_at: Mapped[datetime] = mapped_column(nullable=False)


class RunRevertQuestion(Base):
    """The day-7 "Hoàn tác?" question for one run (ADR-109 d.11). One per run."""

    __tablename__ = "run_revert_questions"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", name="uq_run_revert_questions_run"),
        CheckConstraint(
            "status IN ('open', 'reverted', 'dismissed')", name="ck_run_revert_questions_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    #: ``[{metric, impact_pct, band_pct}]`` -- the metrics that left the band.
    breaches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=QUESTION_OPEN)
    revert_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column()

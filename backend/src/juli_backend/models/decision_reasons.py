"""Seller reasons for Từ chối / Không thực hiện / Hoàn tác (fast track P10-A, ADR-109 am. 1 d.7).

One ``decision_reasons`` row per seller action, tenant-direct (``shop_id``):

- ``reject``  -- "Từ chối" a recommendation card (``action_card_id`` set);
- ``decline`` -- "Không thực hiện" at a run's consent step (``workflow_run_id`` set);
- ``revert``  -- "Hoàn tác" a finished run (``workflow_run_id`` = the run reverted).

Each row records exactly one ``reason_code`` (the dialog's required radio), the
optional ``note`` (≤ 300 characters), who decided and when, and what the 7-day
cooldown is keyed on: the product (``product_id``) and the change type
(``lever_code``). ``basis_stage_rate`` / ``basis_rate`` are the weak stage's
rate the card was proposed on -- card generation compares the current rate with
it to decide whether the product's data "changed clearly" (see
``services/decision_reasons``). Rows are INSERT-only. Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

ACTION_REJECT = "reject"
ACTION_DECLINE = "decline"
ACTION_REVERT = "revert"
ACTIONS: tuple[str, ...] = (ACTION_REJECT, ACTION_DECLINE, ACTION_REVERT)

NOTE_MAX_CHARS = 300


class DecisionReason(Base):
    """One seller reason for rejecting, declining or reverting a change."""

    __tablename__ = "decision_reasons"
    __table_args__ = (
        CheckConstraint(
            "action IN ('reject', 'decline', 'revert')", name="ck_decision_reasons_action"
        ),
        Index(
            "ix_decision_reasons_cooldown",
            "shop_id",
            "product_id",
            "lever_code",
            "decided_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(NOTE_MAX_CHARS))
    action_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_cards.id"))
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    #: The ADR-106 lever code of the change (``title``, ``description``, ...).
    lever_code: Mapped[str | None] = mapped_column(String(32))
    #: ``ctr`` / ``ctor`` / ``aov`` -- the weak stage the card was proposed on.
    basis_stage_rate: Mapped[str | None] = mapped_column(String(8))
    basis_rate: Mapped[float | None] = mapped_column(Float)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    cooldown_until: Mapped[datetime] = mapped_column(nullable=False)

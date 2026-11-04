"""The manual cycle's records (ADR-118), migration 109.

Four tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``), client lane:

- ``shop_proposals`` -- one change an operator proposes for a platform item, the shop or
  a campaign. Keyed on the platform's item id (as ``platform_items``), never on
  ``products``: that table is TikTok-shaped (ADR-117). Status moves only forward;
  a change after sending is a new revision (``supersedes_id``).
- ``shop_proposal_approvals`` -- append-only: the client's decision, in the app
  (``decided_by_user_id``) or recorded by an operator from an email / document
  (``recorded_by_staff_id`` + ``evidence_ref``), with the proposal the client saw.
- ``shop_proposal_executions`` -- the change made on the shop, by a role or a Juli user
  id (never a name); only ``verified_*`` change afterwards (the export read-back).
- ``shop_proposal_results`` -- append-only measurement rows; latest ``computed_at`` wins.

Forecasts and expected effects stay Ops-only (``lever_plans``, ``kpi_forecasts``);
``lever_plan_id`` and the staff ids are plain uuids, not foreign keys into Ops tables.
Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

PLATFORMS: tuple[str, ...] = ("tiktok", "shopee")
KINDS: tuple[str, ...] = (
    "title",
    "images",
    "price",
    "voucher",
    "flash_sale",
    "ads",
    "bundle",
    "program",
    "stock",
    "other",
)
SUBJECT_ITEM = "item"
SUBJECT_TYPES: tuple[str, ...] = (SUBJECT_ITEM, "shop", "campaign")

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CHANGES_REQUESTED = "changes_requested"
STATUS_EXECUTED = "executed"
STATUS_MEASURED = "measured"
STATUS_WITHDRAWN = "withdrawn"
STATUS_SUPERSEDED = "superseded"
STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_CHANGES_REQUESTED,
    STATUS_EXECUTED,
    STATUS_MEASURED,
    STATUS_WITHDRAWN,
    STATUS_SUPERSEDED,
)

#: An approval's decision is also the status it moves the proposal to.
DECISIONS: tuple[str, ...] = (STATUS_APPROVED, STATUS_REJECTED, STATUS_CHANGES_REQUESTED)
CHANNEL_IN_APP = "in_app"
APPROVAL_CHANNELS: tuple[str, ...] = (CHANNEL_IN_APP, "email", "document")

EXECUTOR_PLATFORM_API = "platform_api"
EXECUTOR_ROLES: tuple[str, ...] = ("client_representative", "juli_operator", EXECUTOR_PLATFORM_API)
EXECUTION_CHANNELS: tuple[str, ...] = ("ops", CHANNEL_IN_APP, "api")
VERIFIED_HOW: tuple[str, ...] = ("export_readback", "sub_account_read", "api")

#: ``pre_post_vs_untested`` is the migration-109 pre/post method, kept for rows written
#: before D81.1; since then an item is measured against its own history
#: (``self_baseline``, migration 111).
METHOD_SELF_BASELINE = "self_baseline"
METHODS: tuple[str, ...] = ("pre_post_vs_untested", "contract_kpi", METHOD_SELF_BASELINE)
VERDICTS: tuple[str, ...] = ("dat", "khong_dat", "chua_ket_luan")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopProposal(Base):
    """One proposed change for a platform item, the shop or a campaign."""

    __tablename__ = "shop_proposals"
    __table_args__ = (
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_shop_proposals_platform"),
        CheckConstraint(f"kind IN ({_in(KINDS)})", name="ck_shop_proposals_kind"),
        CheckConstraint(
            f"subject_type IN ({_in(SUBJECT_TYPES)})", name="ck_shop_proposals_subject_type"
        ),
        CheckConstraint(
            "(subject_type = 'item') = (item_id IS NOT NULL)", name="ck_shop_proposals_item"
        ),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="ck_shop_proposals_status"),
        CheckConstraint("revision >= 1", name="ck_shop_proposals_revision"),
        Index("ix_shop_proposals_shop_cycle", "shop_id", "cycle"),
        Index("ix_shop_proposals_shop_status", "shop_id", "status"),
        Index("ix_shop_proposals_shop_item_queue", "shop_id", "item_id", "product_queue"),
        Index(
            "uq_shop_proposals_shop_code",
            "shop_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    cycle: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    subject_type: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_label: Mapped[str] = mapped_column(String(255))
    change_before: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    change_after: Mapped[dict[str, Any]] = mapped_column(JSONBType)
    reason: Mapped[str] = mapped_column(Text)
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), default=STATUS_DRAFT, server_default=STATUS_DRAFT
    )
    revision: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_proposals.id"), nullable=True
    )
    lever_plan_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    proposed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    #: P91 (migration 116). ``JC-<yymm>-<seq4>``, unique per shop, never reused; set when a
    #: Shopee recommendation card is first persisted (None for proposals made by hand before).
    code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: P91 (migration 116). Place in the product's queue of open cards (1 = the Quyết định
    #: card); None = closed, or not about one product. Written by ``product_queue``.
    product_queue: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class ShopProposalCodeCounter(Base):
    """P91 (migration 116): the last card-code sequence number handed out per shop."""

    __tablename__ = "shop_proposal_code_counters"
    __table_args__ = (CheckConstraint("last_seq >= 0", name="ck_shop_proposal_code_counters_seq"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopProposalApproval(Base):
    """The client's decision on one proposal (append-only)."""

    __tablename__ = "shop_proposal_approvals"
    __table_args__ = (
        CheckConstraint(
            f"decision IN ({_in(DECISIONS)})", name="ck_shop_proposal_approvals_decision"
        ),
        CheckConstraint(
            f"channel IN ({_in(APPROVAL_CHANNELS)})", name="ck_shop_proposal_approvals_channel"
        ),
        CheckConstraint(
            "(channel = 'in_app' AND decided_by_user_id IS NOT NULL) OR "
            "(channel <> 'in_app' AND recorded_by_staff_id IS NOT NULL "
            "AND evidence_ref IS NOT NULL)",
            name="ck_shop_proposal_approvals_who",
        ),
        Index("ix_shop_proposal_approvals_proposal", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_proposals.id"))
    decision: Mapped[str] = mapped_column(String(24))
    channel: Mapped[str] = mapped_column(String(16))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    recorded_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proposal_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopProposalExecution(Base):
    """The change made on the shop for one approved proposal."""

    __tablename__ = "shop_proposal_executions"
    __table_args__ = (
        CheckConstraint(
            f"executor_role IN ({_in(EXECUTOR_ROLES)})", name="ck_shop_proposal_executions_role"
        ),
        CheckConstraint(
            f"channel IN ({_in(EXECUTION_CHANNELS)})", name="ck_shop_proposal_executions_channel"
        ),
        CheckConstraint(
            f"verified_how IS NULL OR verified_how IN ({_in(VERIFIED_HOW)})",
            name="ck_shop_proposal_executions_verified_how",
        ),
        CheckConstraint(
            "executor_role = 'platform_api' OR recorded_by_staff_id IS NOT NULL "
            "OR recorded_by_user_id IS NOT NULL",
            name="ck_shop_proposal_executions_recorded_by",
        ),
        CheckConstraint(
            "(verified_at IS NULL) = (verified_how IS NULL)",
            name="ck_shop_proposal_executions_verified",
        ),
        Index("ix_shop_proposal_executions_proposal", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_proposals.id"))
    executed_at: Mapped[datetime] = mapped_column()
    executor_role: Mapped[str] = mapped_column(String(32))
    executed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    recorded_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    verified_how: Mapped[str | None] = mapped_column(String(24), nullable=True)
    verified_state: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopProposalResult(Base):
    """One measurement of one proposal (append-only; the latest ``computed_at`` wins)."""

    __tablename__ = "shop_proposal_results"
    __table_args__ = (
        CheckConstraint(f"method IN ({_in(METHODS)})", name="ck_shop_proposal_results_method"),
        CheckConstraint(f"verdict IN ({_in(VERDICTS)})", name="ck_shop_proposal_results_verdict"),
        Index("ix_shop_proposal_results_proposal", "proposal_id", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_proposals.id"))
    method: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    pre_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    pre_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    post_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    post_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    comparison: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    #: ``self_baseline_v1``: ``value`` / (max of the last 8 weekly values) - 1, clamped to
    #: ±999; the weekly max / median themselves are in ``detail``.
    band: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    verdict: Mapped[str] = mapped_column(String(16))
    data_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    job_version: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    computed_at: Mapped[datetime] = mapped_column()

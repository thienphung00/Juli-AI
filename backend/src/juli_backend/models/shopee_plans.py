"""The draft plan ("Kế hoạch") and the change sets of the Shopee recommendation cards (P91 D-6..D-8,
migration 117). Four tenant-direct tables:

- ``shop_reco_plans`` -- one plan of a shop: ``draft`` (at most one per shop, the partial unique
  index), ``confirmed`` (code ``KH-<yymm>-<seq3>``, one planned execution date, the aggregate
  frozen), ``executed`` (every card executed) or ``cancelled``. Plan-level measurement window
  default and per-product overrides; the acknowledged breaches (who, when, which) are recorded.
- ``shop_reco_plan_cards`` -- a card in a plan with its chosen version and what-if overrides. A
  removed card keeps its row (``removed_at``) so the plan's history is complete.
- ``shop_reco_plan_counters`` -- the last plan sequence number per shop (like the card counter).
- ``shop_reco_change_sets`` -- the unit of measurement: the cards of one product (or of the
  shop) executed the same day, with the measurement window chosen, the joint prediction they were
  planned with and the result.

Cards themselves stay ``shop_proposals`` rows (status ``planned`` while in a draft plan;
``lever_plan_id`` points at the plan). Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

PLAN_DRAFT = "draft"
PLAN_CONFIRMED = "confirmed"
PLAN_EXECUTED = "executed"
PLAN_CANCELLED = "cancelled"
PLAN_STATUSES: tuple[str, ...] = (PLAN_DRAFT, PLAN_CONFIRMED, PLAN_EXECUTED, PLAN_CANCELLED)

SCOPE_PRODUCT = "product"
SCOPE_SHOP = "shop"
SET_SCOPES: tuple[str, ...] = (SCOPE_PRODUCT, SCOPE_SHOP)
SET_MEASURING = "measuring"
SET_DONE = "done"
SET_CUT = "cut"
SET_STATUSES: tuple[str, ...] = (SET_MEASURING, SET_DONE, SET_CUT)
#: where a change set's window came from: the shortest preset with enough power, the plan's
#: default, or the person's own number for this set
WINDOW_SOURCES: tuple[str, ...] = ("auto", "plan", "custom")

WINDOW_MIN, WINDOW_MAX = 3, 90


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopRecoPlan(Base):
    __tablename__ = "shop_reco_plans"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(PLAN_STATUSES)})", name="ck_shop_reco_plans_status"),
        CheckConstraint(
            f"window_days IS NULL OR window_days BETWEEN {WINDOW_MIN} AND {WINDOW_MAX}",
            name="ck_shop_reco_plans_window",
        ),
        Index(
            "uq_shop_reco_plans_one_draft",
            "shop_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
            sqlite_where=text("status = 'draft'"),
        ),
        Index(
            "uq_shop_reco_plans_shop_code",
            "shop_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
            sqlite_where=text("code IS NOT NULL"),
        ),
        Index("ix_shop_reco_plans_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    status: Mapped[str] = mapped_column(String(16), default=PLAN_DRAFT, server_default=PLAN_DRAFT)
    code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: history window end the aggregate was last computed on
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: plan-level default measurement window (days); None = automatic per product
    window_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: ``{product_id: days}`` overrides of the plan default, before the cards are executed
    product_windows: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    confirmed_by: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    #: the breaches the confirming person acknowledged: ``{by, at, breaches[]}``
    acknowledged_breaches: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    #: products whose running measurement the confirm cut (listed in the confirm dialog)
    cut_measurements: Mapped[list[Any] | None] = mapped_column(JSONBType, nullable=True)
    #: the aggregate as it stood on confirm (what the change sets are compared with)
    aggregate: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ShopRecoPlanCard(Base):
    __tablename__ = "shop_reco_plan_cards"
    __table_args__ = (
        CheckConstraint("chosen_version BETWEEN 1 AND 4", name="ck_shop_reco_plan_cards_version"),
        Index(
            "uq_shop_reco_plan_cards_open",
            "plan_id",
            "proposal_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
            sqlite_where=text("removed_at IS NULL"),
        ),
        Index("ix_shop_reco_plan_cards_shop_proposal", "shop_id", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_reco_plans.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_proposals.id"))
    chosen_version: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    #: what-if inputs moved on the chosen version while planned (cleared when the version switches)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: the status the card had before it was planned (a removed card goes back to it)
    prior_status: Mapped[str] = mapped_column(String(24))
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    added_by: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: set when the card was added with a floor / spend-cap breach acknowledged
    acknowledged_breaches: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)


GROUP_DRAFT = "draft"
GROUP_APPROVED = "approved"
GROUP_CANCELLED = "cancelled"
GROUP_STATUSES: tuple[str, ...] = (GROUP_DRAFT, GROUP_APPROVED, GROUP_CANCELLED)
GROUP_MIN_DAYS, GROUP_MAX_DAYS = 3, 90


class ShopRecoPlanGroup(Base):
    """P97 D85.14 / P94: options of the plan that run together ("Nhóm A", "Nhóm B" ...), with one
    period -- ``start_date`` (None = right after the previous group ends, the first group from the
    plan's date) and ``days`` (at least 3). Inside a group the options are evaluated as one bundle
    on the same orders; the next group runs after it. Migration 125."""

    __tablename__ = "shop_reco_plan_groups"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in(GROUP_STATUSES)})", name="ck_shop_reco_plan_groups_status"
        ),
        CheckConstraint(
            f"days BETWEEN {GROUP_MIN_DAYS} AND {GROUP_MAX_DAYS}",
            name="ck_shop_reco_plan_groups_days",
        ),
        Index(
            "uq_shop_reco_plan_groups_letter",
            "plan_id",
            "letter",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
            sqlite_where=text("status <> 'cancelled'"),
        ),
        Index("ix_shop_reco_plan_groups_shop_plan", "shop_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_reco_plans.id"))
    #: "A", "B" ... in the order the groups run
    letter: Mapped[str] = mapped_column(String(2))
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days: Mapped[int] = mapped_column(SmallInteger, default=7, server_default="7")
    #: ``<card code>-G<letter>`` of the group's first card, frozen on confirm
    code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default=GROUP_DRAFT, server_default=GROUP_DRAFT)
    created_by: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopRecoPlanGroupMember(Base):
    """One version of one planned card inside a group. A card may sit in several groups with
    different versions (the second option of an exclusive field runs in the next group); a removed
    member keeps its row (``removed_at``)."""

    __tablename__ = "shop_reco_plan_group_members"
    __table_args__ = (
        CheckConstraint("version BETWEEN 1 AND 4", name="ck_shop_reco_plan_group_members_version"),
        Index(
            "uq_shop_reco_plan_group_members_open",
            "group_id",
            "plan_card_id",
            "version",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
            sqlite_where=text("removed_at IS NULL"),
        ),
        Index("ix_shop_reco_plan_group_members_shop_group", "shop_id", "group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_reco_plan_groups.id"))
    plan_card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_reco_plan_cards.id"))
    version: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ShopRecoPlanCounter(Base):
    __tablename__ = "shop_reco_plan_counters"
    __table_args__ = (CheckConstraint("last_seq >= 0", name="ck_shop_reco_plan_counters_seq"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopRecoChangeSet(Base):
    __tablename__ = "shop_reco_change_sets"
    __table_args__ = (
        CheckConstraint(f"scope IN ({_in(SET_SCOPES)})", name="ck_shop_reco_change_sets_scope"),
        CheckConstraint(f"status IN ({_in(SET_STATUSES)})", name="ck_shop_reco_change_sets_status"),
        CheckConstraint(
            f"window_source IN ({_in(WINDOW_SOURCES)})", name="ck_shop_reco_change_sets_source"
        ),
        CheckConstraint(
            f"window_days BETWEEN {WINDOW_MIN} AND {WINDOW_MAX}",
            name="ck_shop_reco_change_sets_window",
        ),
        CheckConstraint(
            "(scope = 'product') = (product_id IS NOT NULL)",
            name="ck_shop_reco_change_sets_scope_id",
        ),
        Index(
            "uq_shop_reco_change_sets_product_day",
            "shop_id",
            "product_id",
            "executed_on",
            unique=True,
            postgresql_where=text("scope = 'product'"),
            sqlite_where=text("scope = 'product'"),
        ),
        Index(
            "uq_shop_reco_change_sets_shop_day",
            "shop_id",
            "executed_on",
            unique=True,
            postgresql_where=text("scope = 'shop'"),
            sqlite_where=text("scope = 'shop'"),
        ),
        Index("ix_shop_reco_change_sets_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_reco_plans.id"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(8))
    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_on: Mapped[date] = mapped_column(Date)
    #: when the clock started (the first execution of the set)
    started_at: Mapped[datetime] = mapped_column()
    card_ids: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    window_days: Mapped[int] = mapped_column(SmallInteger)
    window_source: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")
    status: Mapped[str] = mapped_column(
        String(12), default=SET_MEASURING, server_default=SET_MEASURING
    )
    #: the product set was executed with a shop-wide change ("kèm thay đổi toàn shop")
    with_shop_wide: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: the plan's joint prediction for this product / the shop when it was confirmed
    predicted: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    cut_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cut_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

"""Stored opportunities: one row per candidate per daily run (batch-1124-c-data, track OPP).

``shopee_opportunities`` is a tenant-direct table (``shop_id``, RLS by ``app_current_shop_id()``).
The DDL is written by migration 140 (track FACT); this module is the ORM model the code uses.

One row = one candidate the engine found on ``run_date`` and what happened to it:

- ``published`` -- saved as a card (``card_code`` set);
- ``ranked_out`` -- cut by the ranking or the daily card cap (``score`` set, ``reason`` the cause);
- ``below_band`` -- an opportunity card that did not clear the forecast band;
- ``refused`` -- the engine could not price it (``reason`` is a short code);
- ``duplicate`` -- the same change is already open (``card_code`` of the open card).

``item_key`` is the sorted product ids joined by ``,`` (``''`` = the whole shop) and
``variant_key`` is ``'<campaign_key>|<version point>'`` or ``''``: both are NOT NULL so the unique
key is idempotent. ``source`` tells the daily run's rows from an on-demand ``generate_for``; an
on-demand write never replaces a daily row. Estimates are NULL when unknown, never 0.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.models.shopee_profit import UTC_TIME
from juli_backend.orm_base import Base

SCOPES: tuple[str, ...] = ("shop", "product")
OUTCOMES: tuple[str, ...] = ("published", "ranked_out", "below_band", "refused", "duplicate")
SOURCES: tuple[str, ...] = ("daily", "on_demand")
_MONEY = Numeric(18, 2)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopeeOpportunity(Base):
    __tablename__ = "shopee_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "run_date",
            "kind",
            "item_key",
            "variant_key",
            name="uq_shopee_opportunities_key",
        ),
        CheckConstraint(f"scope IN ({_in(SCOPES)})", name="ck_shopee_opportunities_scope"),
        CheckConstraint(f"outcome IN ({_in(OUTCOMES)})", name="ck_shopee_opportunities_outcome"),
        CheckConstraint(f"source IN ({_in(SOURCES)})", name="ck_shopee_opportunities_source"),
        Index("ix_shopee_opportunities_shop_run", "shop_id", "run_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    run_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16))
    item_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    variant_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    item_ids: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    delta_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    delta_profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    outcome: Mapped[str] = mapped_column(String(16))
    score: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    derivation_version: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16), default="daily", server_default="daily")
    created_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())

"""Planned listing changes imported from a file (P91 D-13, migration 120).

The cards themselves are ordinary manual cards (``action_cards`` + ``shop_proposals`` +
``card_events``, ``origin = "import"``). Two tenant-direct tables keep what those rows cannot:

- ``planned_change_imports`` -- one row per applied file (who, when, why, file hash, the
  per-row outcome), numbered per shop: the version history of the Cài đặt › Đề xuất kế hoạch
  screen. Append-only.
- ``planned_change_refs`` -- the ``external_ref`` ("TD1", "XM3" ...) of each imported row and the
  card it became, with a hash of the row's content so a re-import of the same file creates
  nothing twice. Unique per shop.

Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base


class PlannedChangeImport(Base):
    __tablename__ = "planned_change_imports"
    __table_args__ = (
        UniqueConstraint("shop_id", "number", name="uq_planned_change_imports_number"),
        CheckConstraint("number >= 1", name="ck_planned_change_imports_number"),
        CheckConstraint("set_by IN ('seller', 'staff')", name="ck_planned_change_imports_set_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    number: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    set_by: Mapped[str] = mapped_column(String(8))
    set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    set_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    #: ``{"counts": {...}, "rows": [{ref, item_id, change_kind, card_id, code, action, ...}]}``
    summary: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlannedChangeRef(Base):
    __tablename__ = "planned_change_refs"
    __table_args__ = (
        UniqueConstraint("shop_id", "external_ref", name="uq_planned_change_refs_ref"),
        Index("ix_planned_change_refs_card", "shop_id", "card_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    external_ref: Mapped[str] = mapped_column(String(64))
    card_id: Mapped[uuid.UUID] = mapped_column()
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planned_change_imports.id"))
    #: Hash of the row's content (kind, item, before, after, reason, cost, window, depends_on).
    content_hash: Mapped[str] = mapped_column(String(64))
    #: The decision / status / date last applied: ``{"decision", "status", "executed_on"}``.
    state: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

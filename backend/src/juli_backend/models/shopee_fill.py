"""The fill queue (P97 D85.6, migration 124): what the Connector opens and fills after an approval.

One row per target of an approved card version (a voucher, a campaign, a product edit page, a bulk
commission edit). Tenant-direct: ``shop_id`` + RLS by ``app_current_shop_id()``; ``juli_app`` may
SELECT, INSERT and UPDATE (a job is cancelled or finished by status, never deleted).

``status``: ``queued`` -> ``opened`` (the Connector opened the page) -> ``filled`` (every field is
typed and highlighted) -> ``saved`` (the person pressed Shopee's own save; seen by the Connector on
the page's answer) -> ``captured`` (the new id is posted: ``captured_ref``). ``failed`` and
``cancelled`` end a job. The Connector never saves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

STATUS_QUEUED = "queued"
STATUS_OPENED = "opened"
STATUS_FILLED = "filled"
STATUS_SAVED = "saved"
STATUS_CAPTURED = "captured"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUSES: tuple[str, ...] = (
    STATUS_QUEUED,
    STATUS_OPENED,
    STATUS_FILLED,
    STATUS_SAVED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
#: Statuses the Connector may still work on / the person may still act on.
OPEN_STATUSES: tuple[str, ...] = (STATUS_QUEUED, STATUS_OPENED, STATUS_FILLED, STATUS_SAVED)
KINDS: tuple[str, ...] = (
    "title",
    "description_first_line",
    "voucher",
    "ads_edit",
    "affiliate_commission",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopeeFillJob(Base):
    __tablename__ = "shopee_fill_jobs"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "proposal_id", "version", "target_key", name="uq_shopee_fill_jobs_target"
        ),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="ck_shopee_fill_jobs_status"),
        Index("ix_shopee_fill_jobs_shop_status", "shop_id", "status", "created_at"),
        Index("ix_shopee_fill_jobs_proposal", "shop_id", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_proposals.id"))
    #: The approved version of the card (V1, V2, ...).
    version: Mapped[int] = mapped_column(Integer, default=1)
    #: Nhóm A / B ... when the approval is a group (P94); None for a single card.
    group_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    #: What the page is about: ``{item_id}``, ``{campaign_id}``, ``{product_ids}`` ...
    target: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: A stable key of the target inside the approval (idempotent enqueue).
    target_key: Mapped[str] = mapped_column(String(80))
    #: Position inside the approval (the Connector works through them in this order).
    seq: Mapped[int] = mapped_column(Integer, default=0)
    #: Exactly what the Connector types (validated server-side; no buyer data).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_QUEUED)
    #: The id Shopee gave the saved thing (voucher_id, ...), posted by the Connector.
    captured_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

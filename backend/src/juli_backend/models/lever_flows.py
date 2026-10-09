"""Lever flows: cover-image photos, Seller Center promotions, measurement (fast track P10-B).

Four tenant-direct tables (each row carries ``shop_id``), migration 080:

- ``run_lever_flows`` -- the extra state of a run whose lever is not a plain
  listing write: ``photo`` (cover image, waits for the seller's photo) or
  ``promotion`` (Seller Center: waits for the seller to apply it, then verifies
  it read-only on TikTok). One per run.
- ``run_lever_photos`` -- the cover image before the change and the seller's
  photo, served by our API under an unguessable ``public_token``.
- ``lever_calibrations`` -- per shop and lever, realised ÷ expected GMV
  (D16/D22), 0.5 until the first conclusive day-14 reading.
- ``run_measurement_finals`` -- a run's day-14 verdict, written once.

Timestamps naive UTC, like ``models/run_changes.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

FLOW_PHOTO = "photo"
FLOW_PROMOTION = "promotion"
FLOW_KINDS: tuple[str, ...] = (FLOW_PHOTO, FLOW_PROMOTION)

PHOTO_BEFORE = "before"
PHOTO_AFTER = "after"

FINAL_LABELS: tuple[str, ...] = ("dat", "gan_dat", "khong_dat", "chua_ket_luan")


class RunLeverFlow(Base):
    """The cover-image / promotion state of one run (contract §4-§5)."""

    __tablename__ = "run_lever_flows"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", name="uq_run_lever_flows_run"),
        CheckConstraint("kind IN ('photo', 'promotion')", name="ck_run_lever_flows_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    #: ``photo`` | ``promotion``.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The card's ADR-106 lever code (``cover_image``, ``product_discount``, ...).
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Promotion only: the proposal the run checked against the seller's rules
    #: (``services.lever_flows.promotion.PromotionProposal.to_json``).
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: Promotion only: the last "Tôi đã áp dụng".
    applied_at: Mapped[datetime | None] = mapped_column()
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Promotion only: the promotion found on TikTok (type, title, dates).
    found: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: Promotion only: day 0 of the day-7/day-14 clock (the promotion's start).
    measurement_start: Mapped[date | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class RunLeverPhoto(Base):
    """One image of a cover-image run: ``before`` (current cover) or ``after`` (the seller's)."""

    __tablename__ = "run_lever_photos"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "role", name="uq_run_lever_photos_run_role"),
        UniqueConstraint("public_token", name="uq_run_lever_photos_token"),
        CheckConstraint("role IN ('before', 'after')", name="ck_run_lever_photos_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(8), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ``[{key, label, ok, heuristic, detail}]`` -- see ``photo_checks``.
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    #: Capability token in the served URL (no auth header on an ``<img>``).
    public_token: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``after`` only: the TikTok image URI once ``upload_product_image`` staged it.
    tiktok_uri: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class LeverCalibration(Base):
    """Realised ÷ expected GMV for one lever in one shop (D16/D22)."""

    __tablename__ = "lever_calibrations"
    __table_args__ = (UniqueConstraint("shop_id", "lever", name="uq_lever_calibrations_lever"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    coefficient: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    readings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class RunMeasurementFinal(Base):
    """A run's day-14 verdict (contract §6 ``final``), written once."""

    __tablename__ = "run_measurement_finals"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", name="uq_run_measurement_finals_run"),
        CheckConstraint(
            "label IN ('dat', 'gan_dat', 'khong_dat', 'chua_ket_luan')",
            name="ck_run_measurement_finals_label",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    lever: Mapped[str | None] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(16), nullable=False)
    gmv_actual_per_day: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    pct_of_expected: Mapped[int | None] = mapped_column(Integer)
    calibration_from: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    calibration_to: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

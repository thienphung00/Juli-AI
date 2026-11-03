"""Shopee recommendation state that no existing table fits (ADR-121, migration 115).

Cards themselves reuse ``action_cards`` (the card id), ``shop_proposals`` (same id: the change,
its approvals, executions and results, ADR-118) and ``card_events`` (the journey log). Two
tenant-direct tables are new:

- ``shopee_sim_prior_runs`` -- one row per imported `juli-sim/priors/v1` run of THIS shop
  (the simulation's prior for the lift model, with its per change_kind gate). Never merged across
  shops (ADR-116). The rows live in one JSONB array: they are read whole by the prediction.
- ``shopee_reco_calibrations`` -- one row per (change_kind, metric) of THIS shop: the
  calibration state the lift model reads (pooled measured / predicted, coverage, range scale)
  and the scored observations it was computed from (cards at the plan end and the one-off
  natural-experiment backfill). Recomputable; kept so the backfill's coverage is auditable.

Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

SIM_STATUS_ACTIVE = "active"
SIM_STATUS_SUPERSEDED = "superseded"
SIM_STATUSES: tuple[str, ...] = (SIM_STATUS_ACTIVE, SIM_STATUS_SUPERSEDED)


class ShopeeSimPriorRun(Base):
    __tablename__ = "shopee_sim_prior_runs"
    __table_args__ = (
        UniqueConstraint("shop_id", "run_id", name="uq_shopee_sim_prior_runs_run"),
        CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_shopee_sim_prior_runs_status"
        ),
        Index("ix_shopee_sim_prior_runs_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    run_id: Mapped[str] = mapped_column(String(64))
    shop_alias: Mapped[str] = mapped_column(String(64), default="", server_default="")
    model_version: Mapped[str] = mapped_column(String(64), default="", server_default="")
    priors_version: Mapped[str] = mapped_column(String(64), default="", server_default="")
    #: change_kind -> {weight, status, reason, ...}; the weight multiplies the prior's influence
    gate: Mapped[dict[str, Any]] = mapped_column(JSONBType)
    #: compact rows, see ``services/shopee_recommendations/sim_priors.STORED``
    rows: Mapped[list[Any]] = mapped_column(JSONBType)
    row_count: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    imported_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    imported_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopeeRecoCalibration(Base):
    __tablename__ = "shopee_reco_calibrations"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "change_kind", "metric", name="uq_shopee_reco_calibrations_key"
        ),
        Index("ix_shopee_reco_calibrations_shop", "shop_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    change_kind: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(16))
    n_results: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pooled_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    coverage_n: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    coverage_hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    range_scale: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal(1), server_default="1"
    )
    n_bundle_excluded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sources: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    observations: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())

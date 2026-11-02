"""Contract KPIs, lever plans and forecasts (ADR-117 §4), migration 108.

None of these is a tenant table. Contract terms, Juli's internal change assumptions and
forecasts are never shown to a seller (disclosure rule; simulator scope D42 G4), so like
the 083 ops tables they are read and written only through the ops path under the
``juli_ops`` role; ``juli_app`` has no grant on any of them.

- ``kpi_contracts`` -- one row per VERSION of a shop's contract KPI appendix. An
  adjustment never edits a row: it inserts version n+1 and marks n ``superseded`` (G7).
- ``kpi_targets`` -- per version x flow x metric: role, baseline, ±D, pass / target levels.
- ``kpi_adjustments`` -- append-only: what changed from the previous version, with the
  confirming email.
- ``kpi_exclusions`` -- per version x day: days left out of the baseline and why.
- ``lever_plans`` -- one editable row per lever effect (wave, start, lag, low / high).
- ``kpi_forecasts`` -- append-only: one row per job run x flow x metric x milestone.

Per-client parameters and forecasts are client data (ADR-116 §3, C9): offboarding deletes
them with the shop's data. Timestamps naive UTC, like ``models/ops.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

CONTRACT_DRAFT = "draft"
CONTRACT_SENT = "sent"
CONTRACT_SIGNED = "signed"
CONTRACT_SUPERSEDED = "superseded"
CONTRACT_STATUSES: tuple[str, ...] = (
    CONTRACT_DRAFT,
    CONTRACT_SENT,
    CONTRACT_SIGNED,
    CONTRACT_SUPERSEDED,
)

TARGET_KPI = "kpi"
TARGET_TRACKING = "tracking"
TARGET_ROLES: tuple[str, ...] = (TARGET_KPI, TARGET_TRACKING)


class KpiContract(Base):
    __tablename__ = "kpi_contracts"
    __table_args__ = (
        UniqueConstraint("shop_id", "contract_ref", "version", name="uq_kpi_contracts_ver"),
        CheckConstraint(
            "status IN ('draft', 'sent', 'signed', 'superseded')", name="ck_kpi_contracts_status"
        ),
        CheckConstraint("version >= 1", name="ck_kpi_contracts_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    contract_ref: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    signed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    measure_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: The appendix parameters: pass / target levels, D clamp, data-sufficiency
    #: thresholds, stability windows, exclusion rules.
    params: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: The confirming email (date + subject); required from version 2 on by the service.
    email_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ops_staff.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class KpiTarget(Base):
    __tablename__ = "kpi_targets"
    __table_args__ = (
        UniqueConstraint("contract_id", "flow", "metric", name="uq_kpi_targets_key"),
        CheckConstraint("role IN ('kpi', 'tracking')", name="ck_kpi_targets_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kpi_contracts.id"))
    flow: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    baseline: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    d_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    pass_level: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    target_level: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KpiAdjustment(Base):
    __tablename__ = "kpi_adjustments"
    __table_args__ = (Index("ix_kpi_adjustments_contract", "contract_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The NEW version this adjustment produced.
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kpi_contracts.id"))
    flow: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metric: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    effective_on: Mapped[date] = mapped_column(Date)
    email_ref: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ops_staff.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KpiExclusion(Base):
    __tablename__ = "kpi_exclusions"
    __table_args__ = (UniqueConstraint("contract_id", "day", name="uq_kpi_exclusions_day"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kpi_contracts.id"))
    day: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(64))


class LeverPlan(Base):
    __tablename__ = "lever_plans"
    __table_args__ = (
        CheckConstraint("high >= low", name="ck_lever_plans_range"),
        CheckConstraint("lag_days >= 0", name="ck_lever_plans_lag"),
        Index("ix_lever_plans_shop", "shop_id", "scenario_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ops_sim_scenarios.id"), nullable=True
    )
    lever_key: Mapped[str] = mapped_column(String(32))
    wave: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(String(255))
    starts_on: Mapped[date] = mapped_column(Date)
    lag_days: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    flow: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(32))
    #: Relative change at flow level, uniform on [low, high].
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class KpiForecast(Base):
    __tablename__ = "kpi_forecasts"
    __table_args__ = (
        CheckConstraint(
            "p_pass IS NULL OR (p_pass >= 0 AND p_pass <= 1)", name="ck_kpi_forecasts_p"
        ),
        CheckConstraint("length(inputs_sha256) = 64", name="ck_kpi_forecasts_sha256"),
        Index("ix_kpi_forecasts_run", "shop_id", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kpi_contracts.id"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ops_sim_scenarios.id"), nullable=True
    )
    run_at: Mapped[datetime] = mapped_column()
    flow: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(32))
    milestone: Mapped[int] = mapped_column(SmallInteger)
    window_end: Mapped[date] = mapped_column(Date)
    expected: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    lo90: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    hi90: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    p_pass: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    trend_weight: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    inputs_sha256: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(32))

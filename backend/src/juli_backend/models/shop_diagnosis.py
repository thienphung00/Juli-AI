"""Stored shop diagnosis reports (fast track P7-A, ADR-108, D21).

One row per (shop, report end date, hero ranking mode). ``report`` is exactly
the dict ``ShopDiagnosis.to_dict()`` produces -- the ``report.json`` the
operator build writes and the shape ``GET /v1/demo/analysis`` serves. It holds
aggregates only (daily averages, rates, product titles, promotion bands); the
buyer-level orders the build reads are never stored.

Kept in its own module, like ``models/ingestion.py``, so it lands beside
concurrent model changes without touching ``models.py``. Registered on
``Base.metadata`` through ``juli_backend.models.__init__``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: Hero ranking modes (``shop_diagnosis.heroes.Ranking`` values).
RANKING_60D = "60d"
RANKING_30D = "30d"
RANKINGS: tuple[str, ...] = (RANKING_60D, RANKING_30D)


class ShopDiagnosisReport(Base):
    """The ADR-108 report for one shop, end date and ranking. Timestamps naive UTC."""

    __tablename__ = "shop_diagnosis_reports"
    __table_args__ = (
        UniqueConstraint("shop_id", "end_date", "ranking", name="uq_shop_diagnosis_reports_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    #: The report's ``as_of``: the last local (UTC+7) day of its 60-day window.
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    ranking: Mapped[str] = mapped_column(String(4), nullable=False, default=RANKING_60D)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    built_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

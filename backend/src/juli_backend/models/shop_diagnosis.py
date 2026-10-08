"""Stored shop diagnosis reports and metric rankings (fast track P7-A / P8-A, D21).

``ShopDiagnosisReport`` (ADR-108): one row per (shop, report end date, hero
ranking mode). ``report`` is exactly
the dict ``ShopDiagnosis.to_dict()`` produces -- the ``report.json`` the
operator build writes and the shape ``GET /v1/demo/analysis`` serves. It holds
aggregates only (daily averages, rates, product titles, promotion bands); the
buyer-level orders the build reads are never stored.

``ShopMetricRanking`` (ADR-109 d.5): one row per (shop, end date, stream,
clicked metric), built by the same daily job from the same snapshot.

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


#: ADR-109 d.4 streams and metrics a stored ranking can name
#: (``shop_diagnosis.rankings.STREAM_METRICS``); the migration checks them.
RANKING_STREAMS: tuple[str, ...] = ("product_card", "shop_tab", "seller_live", "seller_video")
RANKING_METRICS: tuple[str, ...] = (
    "impressions",
    "ctr",
    "ctor",
    "add_to_cart_rate",
    "orders_per_cart",
    "aov",
)


class ShopMetricRanking(Base):
    """One ADR-109 d.5 ranking table: shop × end date × stream × clicked metric.

    ``ranking`` is the JSON-ready payload of ``shop_diagnosis.rankings``: the
    stream's figures, the kéo xuống / kéo lên rows and the three closing rows
    (aggregates and product / LIVE / video titles only). Timestamps naive UTC.
    """

    __tablename__ = "shop_metric_rankings"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "end_date", "stream", "metric", name="uq_shop_metric_rankings_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    #: The last local (UTC+7) day of the 60-day window, as for the report.
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    stream: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    ranking: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    built_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

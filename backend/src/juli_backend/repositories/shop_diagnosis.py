"""Stored shop diagnosis reports and metric rankings (fast track P7-A, P8-A).

Thin by the package contract: it reads and writes rows for one shop and never
commits. Building the report (TikTok fetch, analysis) lives in
``services/shop_diagnosis_daily``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from juli_backend.models.shop_diagnosis import ShopDiagnosisReport, ShopMetricRanking
from juli_backend.repositories._base import ShopScopedRepo


class ShopDiagnosisReportsRepo(ShopScopedRepo[ShopDiagnosisReport]):
    """One row per (shop, end date, ranking)."""

    _model = ShopDiagnosisReport

    async def find(
        self, shop_id: uuid.UUID, end_date: date, ranking: str
    ) -> ShopDiagnosisReport | None:
        return await self._one_or_none(
            self._scoped(
                shop_id,
                ShopDiagnosisReport.end_date == end_date,
                ShopDiagnosisReport.ranking == ranking,
            )
        )

    async def latest(self, shop_id: uuid.UUID, ranking: str) -> ShopDiagnosisReport | None:
        """The newest end date stored for the shop in that ranking mode."""
        stmt = (
            self._scoped(shop_id, ShopDiagnosisReport.ranking == ranking)
            .order_by(ShopDiagnosisReport.end_date.desc(), ShopDiagnosisReport.built_at.desc())
            .limit(1)
        )
        return await self._one_or_none(stmt)

    async def save(
        self,
        shop_id: uuid.UUID,
        *,
        end_date: date,
        ranking: str,
        report: dict[str, Any],
        built_at: datetime,
    ) -> ShopDiagnosisReport:
        """Insert, or replace the report of the same (shop, end date, ranking); flush."""
        row = await self.find(shop_id, end_date, ranking)
        if row is None:
            row = ShopDiagnosisReport(
                shop_id=shop_id,
                end_date=end_date,
                ranking=ranking,
                report=report,
                built_at=built_at,
            )
            return await self._add(row)
        row.report = report
        row.built_at = built_at
        await self._session.flush()
        return row


class ShopMetricRankingsRepo(ShopScopedRepo[ShopMetricRanking]):
    """One row per (shop, end date, stream, metric) — ADR-109 d.5 rankings."""

    _model = ShopMetricRanking

    async def find(
        self, shop_id: uuid.UUID, end_date: date, stream: str, metric: str
    ) -> ShopMetricRanking | None:
        return await self._one_or_none(
            self._scoped(
                shop_id,
                ShopMetricRanking.end_date == end_date,
                ShopMetricRanking.stream == stream,
                ShopMetricRanking.metric == metric,
            )
        )

    async def latest(
        self, shop_id: uuid.UUID, stream: str, metric: str
    ) -> ShopMetricRanking | None:
        """The newest end date stored for the shop's stream × metric."""
        stmt = (
            self._scoped(
                shop_id, ShopMetricRanking.stream == stream, ShopMetricRanking.metric == metric
            )
            .order_by(ShopMetricRanking.end_date.desc(), ShopMetricRanking.built_at.desc())
            .limit(1)
        )
        return await self._one_or_none(stmt)

    async def save(
        self,
        shop_id: uuid.UUID,
        *,
        end_date: date,
        stream: str,
        metric: str,
        ranking: dict[str, Any],
        built_at: datetime,
    ) -> ShopMetricRanking:
        """Insert, or replace the ranking of the same (shop, end date, stream, metric); flush."""
        row = await self.find(shop_id, end_date, stream, metric)
        if row is None:
            row = ShopMetricRanking(
                shop_id=shop_id,
                end_date=end_date,
                stream=stream,
                metric=metric,
                ranking=ranking,
                built_at=built_at,
            )
            return await self._add(row)
        row.ranking = ranking
        row.built_at = built_at
        await self._session.flush()
        return row

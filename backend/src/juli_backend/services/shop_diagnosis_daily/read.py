"""Read the stored shop diagnosis report for one shop (``GET /v1/demo/analysis``).

The caller's request scope (``get_active_shop``) has already set the shop GUC;
the repository also filters on ``shop_id`` structurally, so a shop can only
ever read its own rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import ShopDiagnosisReportsRepo
from juli_backend.services.shop_diagnosis import Ranking


@dataclass(frozen=True)
class StoredDiagnosis:
    as_of: date
    built_at: datetime
    ranking: str
    report: dict[str, Any]


async def latest_shop_diagnosis(
    session: AsyncSession, shop_id: uuid.UUID, ranking: Ranking = Ranking.COMBINED_60D
) -> StoredDiagnosis | None:
    """The newest stored report for the shop in ``ranking`` mode, or ``None``."""
    row = await ShopDiagnosisReportsRepo(session).latest(shop_id, ranking.value)
    if row is None:
        return None
    return StoredDiagnosis(
        as_of=row.end_date, built_at=row.built_at, ranking=row.ranking, report=row.report
    )


__all__ = ["StoredDiagnosis", "latest_shop_diagnosis"]

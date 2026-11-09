"""The shop's ad campaigns as Seller Centre last showed them (Connector 0.3.7).

``ads_campaign_settings`` (every campaign on the Quảng cáo list) and ``ads_campaign_detail`` (the
edit-page limits of the ongoing / scheduled ones) are daily snapshots in
``platform_period_metrics``. :func:`ads_campaign_settings` returns, per campaign, the newest
settings and, when the Connector read its edit page, the newest detail -- what the builder needs
to offer "Chiến dịch đang chạy" with Shopee's own limits. Read-only; the caller holds the shop's
scope.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformPeriodMetric

SETTINGS_DATASET = "ads_campaign_settings"
DETAIL_DATASET = "ads_campaign_detail"


async def _newest(
    session: AsyncSession, shop_id: uuid.UUID, dataset: str
) -> dict[str, PlatformPeriodMetric]:
    """The newest snapshot row of ``dataset`` per campaign id."""
    rows = (
        await session.execute(
            select(PlatformPeriodMetric)
            .where(
                PlatformPeriodMetric.shop_id == shop_id,
                PlatformPeriodMetric.platform == "shopee",
                PlatformPeriodMetric.dataset == dataset,
            )
            .order_by(PlatformPeriodMetric.period_end)
        )
    ).scalars()
    newest: dict[str, PlatformPeriodMetric] = {}
    for row in rows:
        campaign_id = (row.extra or {}).get("campaign_id")
        if isinstance(campaign_id, str):
            newest[campaign_id] = row  # ordered by day: the last one wins
    return newest


async def ads_campaign_settings(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per campaign: its newest settings (``captured_on`` = that snapshot's day), with
    ``campaign_name`` and ``detail`` (the newest edit-page limits, or None when never read)."""
    settings = await _newest(session, shop_id, SETTINGS_DATASET)
    details = await _newest(session, shop_id, DETAIL_DATASET)
    out: list[dict[str, Any]] = []
    for campaign_id, row in sorted(settings.items()):
        detail = details.get(campaign_id)
        out.append(
            {
                **(row.extra or {}),
                "campaign_id": campaign_id,
                "campaign_name": row.platform_source,
                "captured_on": row.period_end.isoformat(),
                "detail": None
                if detail is None
                else {**(detail.extra or {}), "captured_on": detail.period_end.isoformat()},
            }
        )
    return out

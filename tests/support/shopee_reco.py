"""A synthetic Shopee shop with healthy margins for the recommendation tests (P90 step 8).

``seed_reco_shop`` builds on ``tests/support/shopee_analytics`` (three products, seven days of
orders, a group ads campaign, vouchers) and adds the seller's costs, a margin target of 10 %,
a daily marketing cap, month targets that the shop is behind, item snapshots with stock and the
campaign's live ROAS target / budget. Every figure is invented.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.run_changes import ShopRule
from tests.support.shopee_analytics import (
    CUR_END,
    CUR_START,
    ITEMS,
    NOW,
    Seeded,
    _src,
    seed_shopee_shop,
    snapshot,
)

AS_OF = CUR_END
MONTH = "2026-10"
COSTS = {"G1": 30_000, "N1": 20_000, "T1": 15_000}


def rule(shop_id: uuid.UUID, key: str, scope: str, value: Any) -> ShopRule:
    return ShopRule(
        shop_id=shop_id, rule_key=key, scope_ref=scope, value=value, set_by="seller", set_at=NOW
    )


async def seed_reco_shop(
    session: AsyncSession,
    *,
    margin_target: float = 10,
    cap: int = 500_000,
    targets: bool = True,
    stock: int = 120,
    materialized: bool = True,
) -> Seeded:
    seeded = await seed_shopee_shop(session, rules=False, materialized=False)
    sid = seeded.shop_id
    for sku, cogs in COSTS.items():
        session.add(rule(sid, "sku_cost", sku, cogs))
        session.add(rule(sid, "packaging_cost", sku, 1_000))
    session.add(rule(sid, "min_margin_pct", "", margin_target))
    session.add(rule(sid, "daily_marketing_cap", "", cap))
    if targets:
        session.add(rule(sid, "monthly_gmv_target", MONTH, 20_000_000))
        session.add(rule(sid, "monthly_orders_target", MONTH, 300))
    for item in ITEMS:
        session.add(
            snapshot(
                sid, item, stock=stock, list_price=Decimal(100_000), current_price=Decimal(90_000)
            )
        )
    # the group campaign's live settings (what the Connector reads each day)
    for day in (CUR_END,):
        session.add(
            PlatformDailyMetric(
                shop_id=sid,
                dataset="ads_campaign_daily",
                day=day,
                item_id="",
                stream="ads",
                segment="cgroup1",
                order_type="placed",
                platform_source="Chiến dịch nhóm",
                impressions=Decimal(1000),
                clicks=Decimal(30),
                orders=Decimal(2),
                gmv=Decimal(100_000),
                extra={"daily_budget": 30_000, "roi_two_target": 3.0, "cost": 14_000},
                confidence="high",
                **_src(),
            )
        )
    await session.flush()
    if materialized:  # P99b: the stored daily rows, as the ingest hook builds them
        from juli_backend.services.shopee_analytics import materialize

        await materialize.backfill_shop(session, sid)
        await session.flush()
    return seeded


__all__ = ["AS_OF", "CUR_START", "MONTH", "NOW", "datetime", "seed_reco_shop"]

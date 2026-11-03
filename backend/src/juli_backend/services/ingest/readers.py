"""Stored rows → the Step 6 resolvers (file vs Connector at read time).

``gateway.py`` decides who wins a SAME key (rank: file > Connector). Two questions cross datasets
and cannot be a key: which source answers an ad campaign-day (G-07), and which stored voucher
settings row belongs to which voucher export row (G-14). The pure rules are in
``shopee_profit.ads_sources`` and ``shopee_profit.vouchers``; this module only loads their input.

The caller holds the shop's scope (as in the gateway); nothing here writes or commits.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformPeriodMetric, PlatformPromotion
from juli_backend.services.ingest.mapping import SHOPEE_PROMO_TYPES, STREAM_ADS
from juli_backend.services.shopee_profit.ads_sources import (
    AdDay,
    AdSpendResult,
    AdWindow,
    resolve_ad_spend,
)
from juli_backend.services.shopee_profit.vouchers import (
    VoucherExport,
    VoucherJoin,
    VoucherSetting,
    join_vouchers,
)

PLATFORM = "shopee"
DAILY_ADS = "ads_campaign_daily"
PERIOD_ADS = "ads_campaign_period"
VOUCHER = SHOPEE_PROMO_TYPES["Voucher"]
#: The voucher export posts one row per order type; the confirmed one is the contract basis.
EXPORT_ORDER_TYPE = "confirmed"


def _number(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


async def load_ad_spend(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> AdSpendResult:
    """Ad spend over ``start..end``: Connector days where it read, CSV windows for the rest."""
    d = PlatformDailyMetric
    daily_rows = (
        (
            await session.execute(
                select(d).where(
                    d.shop_id == shop_id,
                    d.platform == PLATFORM,
                    d.dataset == DAILY_ADS,
                    d.stream == STREAM_ADS,
                    d.day >= start,
                    d.day <= end,
                )
            )
        )
        .scalars()
        .all()
    )
    # The shop-level ROAS-target row (segment ``all``) proves the day was read; it has no spend.
    covered = {row.day for row in daily_rows}
    days = [
        AdDay(
            campaign=row.platform_source or "",
            day=row.day,
            spend=_number((row.extra or {}).get("cost")) or Decimal(0),
            gmv=row.gmv,
            orders=row.orders,
            order_basis=row.order_type,
        )
        for row in daily_rows
        if row.segment != "all"
    ]
    p = PlatformPeriodMetric
    period_rows = (
        (
            await session.execute(
                select(p).where(
                    p.shop_id == shop_id,
                    p.platform == PLATFORM,
                    p.dataset == PERIOD_ADS,
                    p.stream == STREAM_ADS,
                    p.period_start <= end,
                    p.period_end >= start,
                )
            )
        )
        .scalars()
        .all()
    )
    windows = [
        AdWindow(
            campaign=row.platform_source or "",
            start=row.period_start,
            end=row.period_end,
            spend=_number((row.extra or {}).get("ads_expense")) or Decimal(0),
            item_id=row.item_id or None,
            gmv=row.gmv,
            orders=row.orders,
            order_basis=row.order_type,
        )
        for row in period_rows
    ]
    return resolve_ad_spend(days, windows, start, end, covered_days=covered)


async def load_voucher_join(session: AsyncSession, shop_id: uuid.UUID) -> VoucherJoin:
    """The shop's voucher export rows joined to its Connector settings rows (refs are the
    ``platform_promotions`` ids)."""
    m = PlatformPromotion
    rows = (
        (
            await session.execute(
                select(m).where(
                    m.shop_id == shop_id, m.platform == PLATFORM, m.promo_type == VOUCHER
                )
            )
        )
        .scalars()
        .all()
    )
    exports: dict[tuple[str, date, int], VoucherExport] = {}
    latest: dict[int, PlatformPromotion] = {}
    for row in rows:
        extra = row.extra or {}
        if "voucher_id" in extra:  # a settings snapshot (the Connector): one per day, newest wins
            voucher_id = int(extra["voucher_id"])
            if voucher_id not in latest or row.period_end > latest[voucher_id].period_end:
                latest[voucher_id] = row
        elif row.order_type == EXPORT_ORDER_TYPE:
            key = (row.program_name, row.starts_at.date(), row.ordinal)
            exports.setdefault(
                key, VoucherExport(str(row.id), row.program_name, row.starts_at.date())
            )
    settings = [
        VoucherSetting(
            str(row.id),
            row.program_name,
            row.starts_at.date(),
            _number(
                (row.extra or {}).get("discount_amount")
                or (row.extra or {}).get("discount_percent")
            ),
        )
        for row in latest.values()
    ]
    return join_vouchers(list(exports.values()), settings)

"""Q3 release gate (batch-1124-c-data, owner #74): for every registry metric a surface reads x
{shop, product, channel} x {7, 30, 90 days} on the synthetic fixture shop, ``query()`` over the
stored rows = ``query()`` over the same rows built from the raw tables (the post-deploy
fallback) = the screen payload = the export cell.

Synthetic shop only (``tests.support.shopee_analytics``, SQLite, invented figures).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from juli_backend.services.metrics.components import InvalidSum
from juli_backend.services.metrics.query import Scope, query
from juli_backend.services.shopee_analytics import facts_reads, facts_source, levels
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

#: every metric id a switched surface reads (Tổng quan KPI row + channel table, product level,
#: Phân tích, the picker, the export)
SURFACE_IDS: tuple[str, ...] = tuple(
    sorted(
        {
            *facts_reads.KPI_METRICS,
            *facts_reads.SPLIT_METRICS.values(),
            *(i for ids in levels.SURFACE_METRICS.values() for i in ids),
            "aov",
            "units",
            "net_revenue",
            "views",
            "clicks",
            "ctr",
            "ctor",
            "roas",
            "cost_coverage",
        }
    )
)
ITEM = "1001"


def _scope(kind: str) -> Scope:
    if kind == "shop":
        return Scope.shop()
    if kind == "product":
        return Scope.product(ITEM)
    return Scope.channel_of("organic")


@pytest.fixture
async def shop(session: Any) -> Any:
    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    return seeded


@pytest.mark.parametrize("days", [7, 30, 90])
@pytest.mark.parametrize("kind", ["shop", "product", "channel"])
async def test_q3_stored_equals_the_raw_fallback(session: Any, shop: Any, kind: str, days: int):
    window = (CUR_END - timedelta(days=days - 1), CUR_END)
    assert await facts_source.facts_ready(
        session, shop.shop_id, window[0], window[1], "confirmed"
    ), "the fixture's stored rows are current"
    checked = 0
    for mid in SURFACE_IDS:
        try:
            stored = await query(
                session, shop.shop_id, [mid], scope=_scope(kind), window=window, mode="stored"
            )
        except InvalidSum:
            continue  # a sum the registry refuses at this grain (e.g. đơn over channels)
        raw = await query(
            session, shop.shop_id, [mid], scope=_scope(kind), window=window, mode="raw"
        )
        assert raw.origin == "raw" and stored.origin == "stored"
        assert stored.values[mid] == raw.values[mid], (mid, kind, days)
        assert stored.coverage[mid] == raw.coverage[mid], (mid, kind, days)
        checked += 1
    assert checked >= 20  # never a gate that checked nothing


async def test_q3_auto_reads_raw_until_the_stored_rows_are_current(session: Any, shop: Any):
    from sqlalchemy import update

    from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily

    window = (CUR_END - timedelta(days=6), CUR_END)
    before = await query(session, shop.shop_id, ["gmv", "profit"], scope=Scope.shop(),
                         window=window)  # fmt: skip
    assert before.origin == "stored"
    await session.execute(
        update(ShopeeShopMetricsDaily)
        .where(ShopeeShopMetricsDaily.shop_id == shop.shop_id)
        .values(derivation_version=None)
    )
    after = await query(session, shop.shop_id, ["gmv", "profit"], scope=Scope.shop(),
                        window=window)  # fmt: skip
    assert after.origin == "raw"
    assert after.values == before.values
    assert after.values["gmv"] is not None and after.values["gmv"] > Decimal(0)


#: KPI key on the screen -> registry id (``channel_split.kpis_of``)
KPI_KEYS = {
    "gmv": "gmv",
    "orders": "orders",
    "profit": "profit",
    "cost_ads": "cost_ads",
    "cost_affiliate": "cost_affiliate",
    "cost_offers": "cost_offers",
    "cost_total": "cost_total",
    "gross_profit": "gross_profit",
    "contribution": "contribution",
    "margin_pct": "margin",
    "margin_gross_pct": "margin_gross",
    "margin_contribution_pct": "margin_contribution",
}
#: export Figures field -> registry id
EXPORT_KEYS = {
    "gmv": "gmv",
    "orders": "orders",
    "profit": "profit",
    "ads_cost": "cost_ads",
    "aff_cost": "cost_affiliate",
    "offer_cost": "cost_offers",
    "cost_total": "cost_total",
    "gross_profit": "gross_profit",
    "contribution": "contribution",
    "net_revenue_known": "net_revenue_known",
    "coverage": "cost_coverage",
}


def _same(a: Any, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(Decimal(str(a)) - b) < Decimal("0.01")


@pytest.mark.parametrize("days", [7, 30, 90])
@pytest.mark.parametrize("kind", ["shop", "product"])
async def test_q3_screen_and_export_equal_query(session: Any, shop: Any, kind: str, days: int):
    from datetime import UTC, datetime

    from juli_backend.services.exports import collect
    from juli_backend.services.shopee_analytics import channel_split

    start, end = CUR_END - timedelta(days=days - 1), CUR_END
    pid = None if kind == "shop" else ITEM
    ids = sorted(set(KPI_KEYS.values()) | set(EXPORT_KEYS.values()))
    q = await query(session, shop.shop_id, ids, scope=_scope(kind), window=(start, end))
    screen = await channel_split.channel_split(
        session, shop.shop_id, period="custom", start=start, end=end, product_id=pid
    )
    for key, mid in KPI_KEYS.items():
        assert _same(screen["kpis"][key], q.values[mid]), (key, kind, days)
    data = await collect.collect_tong_quan(
        session, shop.shop_id, shop_name="Shop mẫu", now=datetime.now(UTC),
        period="custom", start=start, end=end, product_id=pid,
    )  # fmt: skip
    for field_, mid in EXPORT_KEYS.items():
        assert _same(getattr(data.now, field_), q.values[mid]), (field_, kind, days)


@pytest.mark.parametrize("days", [7, 30, 90])
async def test_q3_channel_table_equals_query(session: Any, shop: Any, days: int):
    from juli_backend.services.shopee_analytics import channel_split

    start, end = CUR_END - timedelta(days=days - 1), CUR_END
    q = await query(
        session, shop.shop_id, ["gmv", "orders", "contribution", "profit"],
        scope=Scope.shop(), window=(start, end), group_by="channel",
    )  # fmt: skip
    screen = await channel_split.channel_split(
        session, shop.shop_id, period="custom", start=start, end=end
    )
    rows = screen["profit_split"]["rows"]
    by = {r["channel"]: r for r in q.rows}
    for ch in ("organic", "ads", "affiliate"):
        for key in ("gmv", "orders", "contribution", "profit"):
            assert _same(rows[ch][key], by.get(ch, {}).get(key) or Decimal(0)), (ch, key, days)

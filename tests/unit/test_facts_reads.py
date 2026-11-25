"""Q2 / A8 (batch-1124-c-data): Tổng quan's KPI row, channel table and product channel GMV from
the stored facts, in the shapes the screens read today. Synthetic shop, synthetic numbers."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.metrics.query import MemoryRowSource
from juli_backend.services.shopee_analytics import facts_reads
from juli_backend.services.shopee_analytics.channel_split import SPLIT_COLUMNS

SHOP = uuid.UUID("00000000-0000-4000-8000-0000000000dd")
D0 = date(2026, 4, 1)
D = Decimal


def _d(i: int) -> date:
    return D0 + timedelta(days=i)


def _costs(gmv: int) -> dict[str, Any]:
    g = D(gmv)
    return {
        "net_revenue": g * D("0.9"),
        "net_revenue_known": g * D("0.9"),
        "cogs": g * D("0.3"),
        "cogs_known_gmv": g,
        "packaging": D(0),
        "fees": g * D("0.1"),
        "shipping_net": D(0),
        "offer_promo": g * D("0.05"),
        "offer_voucher": D(0),
        "offer_combo": D(0),
    }


def _shop(i: int, gmv: int = 1000, orders: int = 10) -> dict[str, Any]:
    return {
        "shop_id": SHOP,
        "day": _d(i),
        "order_type": "confirmed",
        "gmv": D(gmv),
        "orders": orders,
        "line_gmv": D(gmv),
        "line_orders": orders,
        "ads_spend": D(60),
        "affiliate_commission": D(20),
        "other_marketing": D(10),
        **_costs(gmv),
    }


def _cell(i: int, channel: str, gmv: int, orders: int, item: str | None = None, **kw: Any):
    row: dict[str, Any] = {
        "shop_id": SHOP,
        "day": _d(i),
        "channel": channel,
        "discounted": "without",
        "gmv": D(gmv),
        "orders": orders,
        "units": orders,
        **_costs(gmv),
        # FACT read rule: a structural 0 on another channel's cell (NULL = unknown)
        "ads_spend": D(0),
        "affiliate_commission": D(0),
    }
    if item is not None:
        row["item_id"] = item
    row.update(kw)
    return row


def _source() -> MemoryRowSource:
    shop = [_shop(i) for i in range(14)]
    cells = []
    for i in range(14):
        cells += [
            _cell(i, "organic", 500, 5),
            _cell(i, "ads", 300, 3, ads_spend=D(50)),
            _cell(i, "affiliate", 200, 2, affiliate_commission=D(20)),
        ]
    return MemoryRowSource({"shop_metrics_daily": shop, "shop_channel_metrics_daily": cells})


async def test_kpi_row_is_net_and_has_the_old_keys() -> None:
    now, prev = await facts_reads.kpis(None, SHOP, (_d(7), _d(13)), source=_source())
    assert now["gmv"] == 7000
    assert now["orders"] == 70
    # contribution/day = 900 - 300 - 100 = 500; profit = 500 - 60 - 20 - 10 = 410
    assert now["contribution"] == 3500
    assert now["profit"] == 2870
    assert now["cost_marketing"] == 7 * (60 + 20 + 50)
    assert now["margin_pct"] == float(D("45.6"))
    assert now["margin_contribution_pct"] == float(D("55.6"))
    assert now["roi"] is not None
    assert prev is not None and prev["gmv"] == 7000


async def test_kpi_previous_window_with_a_missing_day_is_none() -> None:
    src = _source()
    src.tables["shop_metrics_daily"] = [
        r for r in src.tables["shop_metrics_daily"] if r["day"] != _d(2)
    ]
    _, prev = await facts_reads.kpis(None, SHOP, (_d(7), _d(13)), source=src)
    assert prev is None


async def test_channel_table_adds_up_and_keeps_the_unattributed_row() -> None:
    split = await facts_reads.profit_split(None, SHOP, (_d(0), _d(6)), source=_source())
    assert split["columns"] == list(SPLIT_COLUMNS)
    rows = split["rows"]
    assert rows["organic"]["gmv"] == 3500
    assert rows["ads"]["cost_ads"] == 350
    assert rows["organic"]["cost_ads"] == 0  # no ads spend on the Organic cells is 0 there
    assert rows["affiliate"]["cost_affiliate"] == 140
    # organic profit = its contribution (no ads, no AFF)
    assert rows["organic"]["profit"] == rows["organic"]["contribution"]
    un = split["unattributed"]
    assert un["cost_ads"] == 7 * 60 - 350
    assert un["other_marketing"] == 70
    assert split["total"]["gmv"] == 7000
    assert split["total"]["profit"] == sum(r["profit"] for r in rows.values()) + un["profit"]


async def test_a8_zeros_are_zero_and_no_row_is_a_dash() -> None:
    src = _source()
    src.tables["product_metrics_daily"] = [
        {"shop_id": SHOP, "day": _d(0), "order_type": "confirmed", "item_id": "p0",
         "gmv": D(0), "orders": 0},
        {"shop_id": SHOP, "day": _d(0), "order_type": "confirmed", "item_id": "p1",
         "gmv": D(300), "orders": 3},
    ]  # fmt: skip
    src.tables["product_channel_metrics_daily"] = [
        _cell(0, "organic", 200, 2, item="p1"),
        _cell(0, "affiliate", 100, 1, item="p1"),
    ]
    got = await facts_reads.product_channel_gmv(
        None, SHOP, (_d(0), _d(0)), ["p0", "p1", "p9"], source=src
    )
    assert got["p0"] == {"gmv": D(0), "organic_gmv": D(0), "ads_gmv": D(0), "affiliate_gmv": D(0)}
    assert got["p1"]["organic_gmv"] == D(200)
    assert got["p1"]["ads_gmv"] == D(0)
    assert got["p9"] == {"gmv": None, "organic_gmv": None, "ads_gmv": None, "affiliate_gmv": None}

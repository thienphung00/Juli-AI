"""Q1 (batch-1124-c-data): ``metrics.query`` over stored daily facts.

The rows use the contract's column names (CONTRACT-parallel §1 / §6) and live in a
``MemoryRowSource`` until Track FACT's tables merge. Synthetic shop, synthetic numbers.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.metrics import query as q
from juli_backend.services.metrics.compute import evaluate
from juli_backend.services.metrics.query import InvalidSum, MemoryRowSource, Scope

SHOP = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
D0 = date(2026, 3, 1)
D = Decimal


def _day(i: int) -> date:
    return D0 + timedelta(days=i)


def _shop_row(i: int, **kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "shop_id": SHOP,
        "day": _day(i),
        "order_type": "confirmed",
        "gmv": D(1000),
        "orders": 10,
        "units": 12,
        "views": 500,
        "product_clicks": 100,
        "ads_spend": D(50),
        "ads_gmv": D(300),
        "line_gmv": D(1000),
        "line_orders": 10,
        "net_revenue": D(900),
        "net_revenue_known": D(800),
        "cogs": D(300),
        "cogs_known_gmv": D(800),
        "packaging": D(10),
        "fees": D(90),
        "shipping_net": D(20),
        "offer_promo": D(30),
        "offer_voucher": D(10),
        "offer_combo": D(0),
        "affiliate_commission": D(40),
        "affiliate_gmv": D(200),
        "other_marketing": D(5),
        "built_at": datetime(2026, 3, 20, 1, 0, i),
    }
    row.update(kw)
    return row


def _product_row(i: int, item: str, **kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "shop_id": SHOP,
        "day": _day(i),
        "order_type": "confirmed",
        "item_id": item,
        "variation_id": None,
        "gmv": D(400),
        "orders": 4,
        "units": 5,
        "views": 200,
        "clicks": 40,
        "ads_spend": D(20),
        "ads_gmv": D(100),
        "line_gmv": D(400),
        "line_orders": 4,
        "net_revenue": D(360),
        "net_revenue_known": D(360),
        "cogs": D(120),
        "cogs_known_gmv": D(400),
        "packaging": D(4),
        "fees": D(36),
        "shipping_net": D(8),
        "offer_promo": D(12),
        "offer_voucher": D(4),
        "offer_combo": D(0),
        "affiliate_commission": D(16),
        "affiliate_gmv": D(80),
    }
    row.update(kw)
    return row


def _source(days: int = 7, **tables: list[dict[str, object]]) -> MemoryRowSource:
    shop = tables.pop("shop", None)
    src = MemoryRowSource(
        {"shop_metrics_daily": shop if shop is not None else [_shop_row(i) for i in range(days)]}
    )
    for name, rows in tables.items():
        src.tables[name] = rows
    return src


async def test_shop_window_sums_components_and_evaluates_through_the_registry() -> None:
    src = _source(7)
    res = await q.query(
        None,
        SHOP,
        ["gmv", "orders", "aov", "profit", "margin", "contribution"],
        scope=Scope.shop(),
        window=(_day(0), _day(6)),
        source=src,
    )
    assert res.grain == "shop"
    assert res.values["gmv"] == D(7000)
    assert res.values["orders"] == D(70)
    comps = {k: v for k, v in res.components.items()}
    comps["window_days"] = D(7)
    for mid in ("aov", "profit", "margin", "contribution"):
        assert res.values[mid] == evaluate(mid, comps).value
    # contribution = 800 - 300 - 10 - 90 - 20 = 380/day; profit = 380 - 50 - 40 - 5 = 285/day
    assert res.values["contribution"] == D(2660)
    assert res.values["profit"] == D(1995)
    assert res.coverage["profit"] == D("0.8")
    assert res.partial is True  # coverage below 100 %
    assert res.built_at == datetime(2026, 3, 20, 1, 0, 6)
    assert res.missing_days == ()


async def test_a_missing_day_gives_none_with_the_reason_never_zero() -> None:
    src = _source(shop=[_shop_row(i) for i in range(7) if i != 3])
    res = await q.query(
        None, SHOP, ["gmv", "orders"], scope=Scope.shop(), window=(_day(0), _day(6)), source=src
    )
    assert res.values == {"gmv": None, "orders": None}
    assert res.reasons == {"gmv": q.REASON_DAY_MISSING, "orders": q.REASON_DAY_MISSING}
    assert res.missing_days == (_day(3),)
    assert res.partial is True


async def test_allow_partial_sums_the_days_there_and_marks_partial() -> None:
    src = _source(shop=[_shop_row(i) for i in range(7) if i != 3])
    res = await q.query(
        None,
        SHOP,
        ["gmv"],
        scope=Scope.shop(),
        window=(_day(0), _day(6)),
        allow_partial=True,
        source=src,
    )
    assert res.values["gmv"] == D(6000)
    assert res.partial is True
    assert res.missing_days == (_day(3),)


async def test_group_by_day_has_one_row_per_window_day_and_none_on_the_missing_one() -> None:
    src = _source(shop=[_shop_row(i) for i in range(3) if i != 1])
    res = await q.query(
        None,
        SHOP,
        ["gmv", "aov"],
        scope=Scope.shop(),
        window=(_day(0), _day(2)),
        group_by="day",
        source=src,
    )
    assert [r["day"] for r in res.rows] == [_day(0), _day(1), _day(2)]
    assert res.rows[0]["gmv"] == D(1000)
    assert res.rows[0]["aov"] == evaluate("aov", {"gmv": D(1000), "orders": D(10)}).value
    assert res.rows[1]["gmv"] is None
    assert res.rows[1]["aov"] is None


async def test_a_null_component_is_not_known_and_a_component_no_row_knows_is_none() -> None:
    rows = [_shop_row(0, cogs=None), _shop_row(1), _shop_row(2, other_marketing=None)]
    rows = [{**r, "other_marketing": None} for r in rows]
    src = _source(shop=rows)
    res = await q.query(
        None,
        SHOP,
        ["cost_cogs", "cost_other", "profit"],
        scope=Scope.shop(),
        window=(_day(0), _day(2)),
        source=src,
    )
    assert res.values["cost_cogs"] == D(600)
    assert res.values["cost_other"] is None
    assert res.values["profit"] is None  # a missing operand is never 0
    assert res.reasons["cost_other"] == q.REASON_NO_ROWS


async def test_compare_returns_the_previous_window_of_the_same_length_from_one_read() -> None:
    calls: list[q.Read] = []

    class Spy(MemoryRowSource):
        async def rows(self, session: AsyncSession | None, read: q.Read) -> list[Mapping[str, Any]]:
            calls.append(read)
            return await super().rows(session, read)

    src = Spy(_source(14).tables)
    res = await q.query(
        None,
        SHOP,
        ["gmv"],
        scope=Scope.shop(),
        window=(_day(7), _day(13)),
        compare=True,
        source=src,
    )
    assert len(calls) == 1
    assert (calls[0].start, calls[0].end) == (_day(0), _day(13))
    assert res.values["gmv"] == D(7000)
    assert res.previous is not None
    assert res.previous.window == (_day(0), _day(6))
    assert res.previous.values["gmv"] == D(7000)


async def test_product_scope_reads_product_rows_and_no_row_is_none_but_zeros_are_zero() -> None:
    src = _source(
        3,
        product_metrics_daily=[
            *[_product_row(i, "p1") for i in range(3)],
            *[
                _product_row(i, "p0", gmv=D(0), orders=0, units=0, line_gmv=D(0), line_orders=0)
                for i in range(3)
            ],
        ],
    )
    win = (_day(0), _day(2))
    p1 = await q.query(None, SHOP, ["gmv", "orders"], scope=Scope.product("p1"), window=win,
                       source=src)  # fmt: skip
    assert p1.grain == "product"
    assert p1.values == {"gmv": D(1200), "orders": D(12)}
    zero = await q.query(None, SHOP, ["gmv"], scope=Scope.product("p0"), window=win, source=src)
    assert zero.values["gmv"] == D(0)  # A8: a report row of zeros is 0đ
    none = await q.query(None, SHOP, ["gmv"], scope=Scope.product("p9"), window=win, source=src)
    assert none.values["gmv"] is None  # no row = "—"
    assert none.reasons["gmv"] == q.REASON_NO_ROWS


async def test_summing_product_orders_into_more_than_one_product_is_refused() -> None:
    src = _source(3, product_metrics_daily=[_product_row(0, "p1"), _product_row(0, "p2")])
    with pytest.raises(InvalidSum) as excinfo:
        await q.query(
            None,
            SHOP,
            ["aov"],
            scope=Scope.products(["p1", "p2"]),
            window=(_day(0), _day(2)),
            source=src,
        )
    assert excinfo.value.component_id == "orders"
    assert "item" in excinfo.value.refused
    # money adds over products
    res = await q.query(
        None,
        SHOP,
        ["gmv"],
        scope=Scope.products(["p1", "p2"]),
        window=(_day(0), _day(2)),
        source=src,
    )
    assert res.values["gmv"] == D(800)


async def test_group_by_item_ranks_products_with_their_own_orders() -> None:
    src = _source(
        2,
        product_metrics_daily=[
            _product_row(0, "p1"),
            _product_row(1, "p1"),
            _product_row(0, "p2", gmv=D(100), orders=1),
        ],
    )
    res = await q.query(
        None,
        SHOP,
        ["gmv", "orders", "margin_contribution"],
        scope=Scope.shop(),
        window=(_day(0), _day(1)),
        group_by="item",
        source=src,
    )
    assert res.grain == "product"
    by = {r["item"]: r for r in res.rows}
    assert by["p1"]["gmv"] == D(800)
    assert by["p2"]["orders"] == D(1)
    assert (
        by["p1"]["margin_contribution"]
        == evaluate(
            "margin_contribution",
            {
                "net_revenue_known": D(720),
                "cogs": D(240),
                "packaging": D(8),
                "fees": D(72),
                "shipping_net": D(16),
                "cogs_known_gmv": D(800),
                "line_gmv": D(800),
            },
        ).value
    )


def _cell(item: str | None, channel: str, discounted: str, gmv: int, orders: int) -> dict:
    row = {
        "shop_id": SHOP,
        "day": _day(0),
        "channel": channel,
        "discounted": discounted,
        "gmv": D(gmv),
        "orders": orders,
        "units": orders,
        "net_revenue_known": D(gmv) * D("0.9"),
        "cogs": D(gmv) * D("0.3"),
    }
    if item is not None:
        row["item_id"] = item
    return row


async def test_channel_grains_shop_and_product() -> None:
    src = _source(
        1,
        shop_channel_metrics_daily=[
            _cell(None, "organic", "without", 500, 5),
            _cell(None, "organic", "with", 100, 1),
            _cell(None, "ads", "without", 300, 3),
            _cell(None, "affiliate", "with", 100, 1),
        ],
        product_channel_metrics_daily=[
            _cell("p1", "organic", "without", 200, 2),
            _cell("p1", "affiliate", "with", 100, 1),
        ],
    )
    win = (_day(0), _day(0))
    shop = await q.query(
        None, SHOP, ["gmv", "orders"], scope=Scope.shop(), window=win, group_by="channel",
        source=src,
    )  # fmt: skip
    assert shop.grain == "shop_channel"
    by = {r["channel"]: r for r in shop.rows}
    assert by["organic"]["gmv"] == D(600)
    assert by["organic"]["orders"] == D(6)  # đơn over the discount split: allowed
    one = await q.query(None, SHOP, ["gmv"], scope=Scope.channel_of("ads"), window=win, source=src)
    assert one.values["gmv"] == D(300)
    prod = await q.query(
        None, SHOP, ["gmv", "orders"], scope=Scope.product("p1"), window=win,
        group_by="discounted", source=src,
    )  # fmt: skip
    assert prod.grain == "product_channel"
    assert {r["discounted"]: r["gmv"] for r in prod.rows} == {"with": D(100), "without": D(200)}


async def test_campaign_and_source_grains() -> None:
    src = _source(
        1,
        campaign_metrics_daily=[
            {"shop_id": SHOP, "day": _day(0), "campaign_id": "c1", "spend": D(10),
             "gmv": D(80), "orders": 2, "impressions": 100, "clicks": 5},
            {"shop_id": SHOP, "day": _day(0), "campaign_id": "c2", "spend": D(30),
             "gmv": D(60), "orders": 1, "impressions": 50, "clicks": 5},
        ],
        source_metrics_daily=[
            {"shop_id": SHOP, "day": _day(0), "item_id": None, "source": "product_card",
             "views": 100, "clicks": 10, "orders": 2, "gmv": D(200)},
            {"shop_id": SHOP, "day": _day(0), "item_id": None, "source": "shop_tab",
             "views": 50, "clicks": 5, "orders": 1, "gmv": D(100)},
            {"shop_id": SHOP, "day": _day(0), "item_id": "p1", "source": "shop_tab",
             "views": 9, "clicks": 1, "orders": 0, "gmv": D(0)},
        ],
    )  # fmt: skip
    win = (_day(0), _day(0))
    camp = await q.query(
        None, SHOP, ["roas", "cost_ads"], scope=Scope.campaigns(["c1", "c2"]), window=win,
        source=src,
    )  # fmt: skip
    assert camp.grain == "campaign"
    assert camp.values["cost_ads"] == D(40)
    assert (
        camp.values["roas"]
        == evaluate("roas", {"ads_gmv_platform": D(140), "ads_spend": D(40)}).value
    )
    srcs = await q.query(
        None, SHOP, ["views", "clicks"], scope=Scope.shop(), window=win, group_by="source",
        source=src,
    )  # fmt: skip
    assert {r["source"]: r["views"] for r in srcs.rows} == {
        "product_card": D(100),
        "shop_tab": D(50),
    }


async def test_a_sum_over_traffic_sources_is_refused() -> None:
    with pytest.raises(InvalidSum) as excinfo:
        q.summed_dims(q.SOURCE, Scope.shop(), None)
    assert excinfo.value.refused == frozenset({"source"})


async def test_basis_picks_the_order_type() -> None:
    rows = [_shop_row(0), _shop_row(0, order_type="placed", gmv=D(1500))]
    src = _source(shop=rows)
    win = (_day(0), _day(0))
    confirmed = await q.query(None, SHOP, ["gmv"], scope=Scope.shop(), window=win, source=src)
    placed = await q.query(
        None, SHOP, ["gmv"], scope=Scope.shop(), window=win, basis="placed", source=src
    )
    assert (confirmed.values["gmv"], placed.values["gmv"]) == (D(1000), D(1500))


async def test_unknown_metric_and_group_by_are_refused() -> None:
    src = _source(1)
    with pytest.raises(KeyError) as k:
        await q.query(None, SHOP, ["nope"], scope=Scope.shop(), window=(D0, D0), source=src)
    assert "nope" in str(k.value)
    with pytest.raises(ValueError) as v:
        q.grain_of(Scope.shop(), "week")
    assert "week" in str(v.value)


def test_grain_is_picked_from_scope_and_group_by() -> None:
    cases = {
        (Scope.shop(), None): "shop",
        (Scope.shop(), "day"): "shop",
        (Scope.shop(), "item"): "product",
        (Scope.shop(), "variation"): "product",
        (Scope.product("p"), None): "product",
        (Scope.product("p"), "day"): "product",
        (Scope.shop(), "channel"): "shop_channel",
        (Scope.shop(), "discounted"): "shop_channel",
        (Scope.channel_of("ads"), None): "shop_channel",
        (Scope.product("p"), "channel"): "product_channel",
        (Scope.channel_of("ads", ["p"]), None): "product_channel",
        (Scope.campaigns(["c"]), None): "campaign",
        (Scope.shop(), "campaign"): "campaign",
        (Scope.shop(), "source"): "source",
    }
    assert {k: q.grain_of(*k).name for k in cases} == cases


def test_every_component_a_grain_maps_to_is_a_registry_component() -> None:
    from juli_backend.services.metrics.components import COMPONENTS

    future = {"affiliate_commission_known", "ads_spend_known"}  # FACT, CONTRACT §6
    for grain in q.GRAINS.values():
        for comps in grain.columns.values():
            for comp in comps:
                assert comp in COMPONENTS or comp in future, (grain.name, comp)

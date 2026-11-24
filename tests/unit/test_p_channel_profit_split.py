"""Track P (P7, owner decisions #42 / #46 / #49): Organic / Quảng cáo / TTLK of the profit at shop
AND product level. TTLK = the affiliate lines; s = min(1, GMV_QC ÷ GMV_N) splits the rest; every
column adds up, and Σ products = shop per channel with the unattributed remainder as its own row.
Synthetic lines only."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from juli_backend.services.shopee_analytics.channel_split import (
    SPLIT_CHANNELS,
    SPLIT_COLUMNS,
    profit_split,
    split_scope,
)
from juli_backend.services.shopee_profit.order_profit import line_profit
from juli_backend.services.shopee_profit.shop_profit import AdsFigures, product_profits
from tests.unit.test_shopee_profit import COST, SCHEDULE, line


def _pair(oid: str, product: str = "P1", **kw):
    ln = line(oid, product_id=product, **kw)
    return ln, line_profit(ln, COST, schedule=SCHEDULE)


def _pairs():
    return [
        _pair("a1"),
        _pair("a2", deal_price=D(180000)),  # a 20.000đ programme price
        _pair("a3"),
        _pair("f1", affiliate=True, commission=D(9000)),
        _pair("b1", "P2"),
        _pair("b2", "P2", affiliate=True, commission=D(8000)),
    ]


def test_ttlk_is_the_affiliate_lines_and_the_rest_splits_by_the_ads_share():
    pairs = [p for p in _pairs() if p[0].product_id == "P1"]
    rows = split_scope(pairs, ads_gmv=D(190000), ads_spend=D(30000))
    aff = [pb for ln, pb in pairs if ln.affiliate]
    assert rows["affiliate"]["gmv"] == D(200000) and rows["affiliate"]["orders"] == 1
    assert rows["affiliate"]["cost_affiliate"] == D(9000)
    assert rows["affiliate"]["contribution"] == aff[0].organic_contribution
    rest_gmv = D(200000) + D(180000) + D(200000)
    s = D(190000) / rest_gmv
    assert rows["ads"]["gmv"] == pytest.approx(D(190000))
    assert rows["ads"]["orders"] == pytest.approx(3 * s)
    assert rows["ads"]["cost_ads"] == D(30000)
    # Ưu đãi of the rest (the 20.000 programme price) split by the same share
    assert rows["ads"]["cost_offers"] == pytest.approx(D(20000) * s)
    assert rows["organic"]["cost_offers"] == pytest.approx(D(20000) * (1 - s))
    for r in rows.values():
        assert r["profit"] == r["contribution"] - r["cost_ads"] - r["cost_affiliate"]


def test_every_column_adds_up_at_product_level_incl_the_cap_and_no_ads():
    pairs = [p for p in _pairs() if p[0].product_id == "P1"]
    whole = split_scope(pairs, ads_gmv=None, ads_spend=None)  # no ads report row: s = 0
    assert all(v == 0 for v in whole["ads"].values())
    capped = split_scope(pairs, ads_gmv=D(10**9), ads_spend=D(50000))  # s = 1
    assert capped["organic"]["gmv"] == 0 and capped["organic"]["orders"] == 0
    for rows in (whole, capped):
        total = {c: sum(rows[ch][c] for ch in SPLIT_CHANNELS) for c in SPLIT_COLUMNS}
        all_gmv = sum(ln.order_value for ln, _ in pairs)
        assert total["gmv"] == all_gmv and total["orders"] == len(pairs)
        assert total["cost_offers"] == sum(pb.offer_cost for _, pb in pairs)
        assert total["contribution"] == sum(pb.organic_contribution for _, pb in pairs)
        assert (
            total["profit"] == total["contribution"] - total["cost_ads"] - total["cost_affiliate"]
        )


def _view(pairs, *, total_ads: D, other: D):
    spend = {"P1": D(30000), "P2": D(0)}
    return NS(
        pairs=pairs,
        ads=NS(product_figures={"P1": AdsFigures(D(30000), D(400000), D(190000))}),
        profit=NS(
            products=product_profits(pairs, spend),
            total_ad_spend=total_ads,
            other_marketing_costs=other,
        ),
    )


def test_products_add_up_to_the_shop_per_channel_and_the_remainder_is_its_own_row():
    pairs = _pairs()
    view = _view(pairs, total_ads=D(50000), other=D(5000))
    shop = profit_split(view)
    p1, p2 = profit_split(view, "P1"), profit_split(view, "P2")
    for ch in SPLIT_CHANNELS:
        for col in SPLIT_COLUMNS:
            assert shop["rows"][ch][col] == pytest.approx(
                p1["rows"][ch][col] + p2["rows"][ch][col]
            ), (ch, col)
    rest = shop["unattributed"]
    assert rest["cost_ads"] == 20000  # 50.000 of campaigns − 30.000 the products own
    assert rest["profit"] == -20000 - 5000  # never dropped
    for split in (shop, p1, p2):
        rows = {**split["rows"], **({"u": split["unattributed"]} if split["unattributed"] else {})}
        for col in SPLIT_COLUMNS:
            assert sum(r[col] for r in rows.values()) == pytest.approx(split["total"][col]), col
    # the shop's lợi nhuận ròng = đóng góp − all ads − AFF − other marketing
    contribution = sum(pb.organic_contribution for _, pb in pairs)
    commission = sum(pb.commission for _, pb in pairs)
    assert shop["total"]["profit"] == pytest.approx(contribution - 50000 - commission - 5000)
    assert p2["rows"]["ads"]["gmv"] == 0  # a product with no ads report row

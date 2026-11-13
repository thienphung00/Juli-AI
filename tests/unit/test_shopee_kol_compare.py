"""P100 (2026-11-13): affiliate comparison -- channel / campaign-type labels, the groups built from
the KOL table's own rows, the Affiliate vs Ads vs shop-flows strip, and the routes.

Synthetic creators (``kol_one`` ...), order ids and numbers; no real handle, shop or buyer.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics import kol, kol_compare, queries
from juli_backend.services.shopee_analytics.kol_labels import (
    campaign_type_label,
    channel_label,
    options,
)
from juli_backend.services.shopee_profit.flows import Flow, FlowMetrics, FlowTable
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shopee_kol import _seed

# ============================================================================ labels


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("0", "Ngoài Shopee (chưa rõ kênh)"),
        ("1", "Trong Shopee (Video/Live)"),
        ("2", "Trong Shopee (Live)"),
        ("Shopeevideo", "Shopee Video"),
        ("Shopee Video", "Shopee Video"),
        ("shopee_live", "Shopee Live"),
        ("Facebook", "Facebook"),
        ("Zalo", "Zalo"),
        ("Code Sharing", "Chia sẻ mã"),
        ("Websites", "Website"),
        ("Others", "Khác"),
        ("TikTok", "TikTok"),
        ("7", "7"),
    ],
)
def test_channel_labels_cover_legacy_codes_and_report_texts(raw, label):
    assert channel_label(raw) == label


def test_campaign_type_labels():
    assert campaign_type_label("5") == "Chiến dịch mở"
    assert campaign_type_label("9") == "Loại chiến dịch 9"
    assert campaign_type_label("Chiến dịch mục tiêu") == "Chiến dịch mục tiêu"
    assert campaign_type_label(None) is None and campaign_type_label(" ") is None
    assert channel_label(None) is None


def test_options_keep_the_raw_value_beside_the_label_once_each():
    got = options(["1", "Facebook", "1", "0"], channel_label)
    assert got == [
        {"value": "Facebook", "label": "Facebook"},
        {"value": "0", "label": "Ngoài Shopee (chưa rõ kênh)"},
        {"value": "1", "label": "Trong Shopee (Video/Live)"},
    ]


# ============================================================================ groups (pure)


def _row(key, channel, item, orders, *, campaign="5", gmv=100_000, commission=1_500, net=20_000,
         sample=None, sample_qty=0, start=0):  # fmt: skip
    r = kol.KolRow(key, f"kol_{key}", channel, item, f"Sản phẩm {item}")
    r.order_ids = {f"o{start + i}" for i in range(orders)}
    r.orders = r.profit_orders = r.pair_orders = orders
    r.units = orders
    r.gmv = Decimal(gmv * orders)
    r.commission = Decimal(commission * orders)
    r.net_profit = Decimal(net * orders)
    r.campaign_type = campaign
    r.sample_cost = None if sample is None else Decimal(sample)
    r.sample_qty = sample_qty
    return r


def _model(rows):
    return kol.KolModel(
        window={"from": "2026-10-01", "to": "2026-10-30", "days": 30},
        rows=rows,
        pool=kol.KolPool(window_days=30),
        untagged_lines=0,
        missing_commission_lines=0,
        partner_period=None,
    )


ROWS = [
    # legacy code "1" and the new text label for inside-Shopee video sit side by side
    _row("one", "1", "A", 6, start=0),
    _row("one", "Shopeevideo", "B", 6, start=100, sample=50_000, sample_qty=2),
    _row("two", "1", "A", 3, start=200),
    _row("three", "0", "A", 2, campaign="Chiến dịch mục tiêu", start=300),
    _row("four", "Facebook", "C", 1, campaign=None, start=400),
]


def test_channel_groups_sum_the_kol_rows_and_flag_low_data():
    body = kol_compare.groups_json(_model(ROWS), "channel")
    by = {g["label"]: g for g in body["rows"]}
    assert set(by) == {
        "Trong Shopee (Video/Live)",
        "Shopee Video",
        "Ngoài Shopee (chưa rõ kênh)",
        "Facebook",
    }
    inside = by["Trong Shopee (Video/Live)"]
    assert (inside["orders"], inside["kols"], inside["gmv"]) == (9, 2, 900_000)
    assert inside["cost"] == 13_500 and inside["cost_pct_gmv"] == 1.5
    assert inside["net_profit"] == 180_000 and inside["profit_per_order"] == 20_000
    assert inside["low_data"] is True and inside["low_data_label"] == "Ít dữ liệu"
    video = by["Shopee Video"]
    assert video["sample_cost"] == 50_000 and video["profit_after_samples"] == 70_000
    assert video["roi_incl_samples"] == pytest.approx(70_000 / (9_000 + 50_000), abs=1e-4)
    assert body["total"]["orders"] == 18 and body["total"]["gmv"] == 1_800_000
    assert sum(g["share_gmv_pct"] for g in body["rows"]) == pytest.approx(100, abs=0.2)
    assert body["rows"][0]["label"] == "Trong Shopee (Video/Live)"  # biggest GMV first


def test_campaign_and_kol_groups():
    camp = {g["label"]: g for g in kol_compare.groups_json(_model(ROWS), "campaign_type")["rows"]}
    assert camp["Chiến dịch mở"]["orders"] == 15 and camp["Chiến dịch mở"]["low_data"] is False
    assert camp["Chiến dịch mục tiêu"]["orders"] == 2
    assert camp["Không rõ loại chiến dịch"]["orders"] == 1
    kols = {g["key"]: g for g in kol_compare.groups_json(_model(ROWS), "kol")["rows"]}
    assert kols["one"]["label"] == "kol_one" and kols["one"]["orders"] == 12
    assert kols["one"]["products"] == 2 and kols["one"]["low_data"] is False


def test_an_unpriced_sample_makes_the_group_sample_cost_unknown():
    rows = [_row("five", "1", "A", 2, sample=None, sample_qty=3)]
    g = kol_compare.groups_json(_model(rows), "channel")["rows"][0]
    assert g["sample_cost"] is None and g["roi_incl_samples"] == pytest.approx(1 / 0.075, 1e-3)
    with pytest.raises(ValueError):
        kol_compare.groups_json(_model(rows), "item")


# ============================================================================ stream strip (pure)


def _view(*, ads_days=30, spend=Decimal(300_000), flows=True):
    rows = (
        FlowMetrics(Flow.THE_SAN_PHAM_KHAC.value, "", None, None, 40, Decimal(4_000_000)),
        FlowMetrics(Flow.TRANG_SHOP.value, "", None, None, 5, Decimal(500_000)),
        FlowMetrics(Flow.VIDEO.value, "", None, None, 3, Decimal(300_000)),
        FlowMetrics(Flow.LIVE.value, "", None, None, 2, Decimal(200_000)),
        FlowMetrics(Flow.LIEN_KET.value, "", None, None, 15, Decimal(1_500_000)),
    )
    table = FlowTable(rows, Decimal(6_500_000), 65)
    daily = SimpleNamespace(
        days_covered=ads_days, window_days=30, gmv=Decimal(1_200_000), orders=Decimal(12)
    )
    return SimpleNamespace(
        flows=SimpleNamespace(shop=table) if flows else None,
        ads=SimpleNamespace(total_spend=spend if ads_days else Decimal(0), campaigns=[]),
        data=SimpleNamespace(ads_daily=daily),
    )


def test_the_stream_strip_names_each_basis_and_never_mixes_them():
    strip = kol_compare.stream_strip(_view(), _model(ROWS))
    aff, ads, organic = strip["rows"]
    # GMV / orders from the traffic stream; cost and its % from the conversion report
    assert (aff["gmv"], aff["orders"]) == (1_500_000, 15)
    assert aff["basis"]["label"] == "Theo nguồn lưu lượng"
    assert aff["cost_basis"]["label"] == "Theo báo cáo chuyển đổi KOL"
    assert aff["cost"] == 27_000 + 50_000
    assert aff["cost_pct_gmv"] == pytest.approx(77_000 / 1_800_000 * 100, abs=0.1)
    assert aff["conversion_report"] == {"gmv": 1_800_000, "orders": 18}
    assert aff["profit_after_cost"] == 360_000 - 50_000
    assert (ads["cost"], ads["gmv"], ads["cost_pct_gmv"]) == (300_000, 1_200_000, 25.0)
    assert ads["profit_after_cost"] is None and ads["profit_reason"]
    assert (organic["gmv"], organic["orders"], organic["cost"]) == (5_000_000, 50, 0)
    assert organic["profit_after_cost"] is None and organic["profit_reason"]


def test_missing_sources_are_null_with_a_reason():
    strip = kol_compare.stream_strip(_view(ads_days=0, flows=False), _model(ROWS))
    aff, ads, organic = strip["rows"]
    assert aff["gmv"] is None and aff["reason"] and aff["cost"] == 77_000
    assert ads["cost"] is None and ads["reason"] == kol_compare.NO_ADS
    assert organic["gmv"] is None and organic["cost"] is None and organic["reason"]


# ============================================================================ read model + routes


@pytest.fixture
async def shop(session):
    return await _seed(session)


async def test_compare_reuses_the_kol_table_rows(shop, session):
    table = await queries.kol_table(session, shop.shop_id, as_of=AS_OF)
    body = await queries.kol_compare(session, shop.shop_id, as_of=AS_OF, group="channel")
    assert body["basis"]["label"] == "Theo báo cáo chuyển đổi KOL"
    assert body["total"]["orders"] == table["totals"]["orders"]
    assert body["total"]["gmv"] == table["totals"]["gmv"]
    assert body["total"]["cost"] == table["totals"]["commission"]
    assert body["total"]["net_profit"] == table["totals"]["net_profit"]
    assert [r["label"] for r in body["streams"]["rows"]] == [
        "Tiếp thị liên kết",
        "Quảng cáo (Dịch vụ hiển thị)",
        "Thẻ sản phẩm + Video/Live của shop",
    ]
    row = table["rows"][0]
    assert row["channel_label"] == channel_label(row["channel"])
    assert "campaign_type_label" in row
    assert table["filters"]["channel_options"][0].keys() == {"value", "label"}
    assert "order_ref" not in str(body)


async def test_the_compare_routes_for_seller_and_ops(session, monkeypatch, shop):
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    params = {"as_of": AS_OF.isoformat()}
    async with client_for(app) as client:
        seller = await client.get("/v1/demo/shopee/kols/compare", params={**params, "group": "kol"})
        bad = await client.get("/v1/demo/shopee/kols/compare", params={**params, "group": "item"})
    app.dependency_overrides.clear()
    assert seller.status_code == 200, seller.text
    assert seller.json()["group"] == "kol" and bad.status_code == 422
    ops = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{shop.shop_id}/shopee/analytics/kols/compare"
    async with client_for(ops) as client:
        got = await client.get(base, params={**params, "group": "kol"})
        camp = await client.get(base, params={**params, "group": "campaign_type"})
    ops.dependency_overrides.clear()
    assert got.status_code == 200 and got.json()["rows"] == seller.json()["rows"]
    assert camp.status_code == 200 and camp.json()["group_label"] == "Loại chiến dịch"
    for ref in shop.order_refs:
        assert ref not in seller.text and ref not in got.text


def test_campaign_code_5_is_an_open_campaign_when_picking_the_rate():
    # The Connector posts the conversion report's campaign type as a code; "5" = Seller Open
    # Campaign (Seller Centre, 2026-11-13). Without the report's own cost the open rate wins.
    from datetime import date as _date
    from decimal import Decimal as _D

    from juli_backend.services.shopee_analytics.kol_rates import (
        SRC_OPEN,
        SRC_TARGETED,
        RateBook,
        TermsRow,
    )

    book = RateBook(
        targeted={"i1": [TermsRow(_date(2026, 10, 1), _D("0.12"), True, "t")]},
        open_rate={"i1": _D("0.02")},
    )
    assert book.rate("i1", _date(2026, 10, 5), "5") == (_D("0.02"), SRC_OPEN)
    assert book.rate("i1", _date(2026, 10, 5), "1") == (_D("0.12"), SRC_TARGETED)

"""Per-shop optimization report: 30-day tables, 14/28-day cards, HTML (shop_report).

The snapshot below is synthetic but shaped like A-34 rows with the channel
blocks the live response carries: seven live products (six healthy peers and
one weak-CTR product with a clean listing), one gift listing and one
``SELLER_DEACTIVATED`` product that would otherwise top the GMV ranking.
Expectations are derived from the fixture rows, not restated as literals
(ADR-101).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.shop_report import (
    STATUS_NEEDS_CAP,
    STATUS_NOT_ASKED,
    STATUS_OWNER,
    STATUS_RULE,
    TOP_N,
    ShopReport,
    build_shop_report,
    fmt_value,
    render_html,
    window_metrics,
)

CONFIG = StageDiagnosisConfig()
TECH_HEADING = "Chú thích kỹ thuật"
CARD_HEADERS = ["#", "Sản phẩm", "Chỉ số chính", "Lý do", "Thay đổi đề xuất", "Trạng thái"]
TRICKY_TITLE = 'Kem <b>X</b> & Co "Premium" chống nắng cao cấp SPF50 dung tích lớn'
PSORIASIS = "MAIN_IMG_FIRST_IMG_PSORIASIS"
IN_WINDOW = 1_790_000_000  # 2026-09-21 UTC+7


def _row(pid: str, impressions: int, ctr: str, ctor: str, aov: int) -> dict:
    """An A-34 row: totals plus the product-card and shop-tab blocks (60 / 40 split)."""
    clicks = Decimal(impressions) * Decimal(ctr)
    orders = clicks * Decimal(ctor)
    gmv = orders * aov

    return {
        "id": pid,
        "total_performance": {
            "sku_orders": str(orders),
            "items_sold": str(orders * Decimal("1.2")),
            "gmv": {"amount": str(gmv), "currency": "VND"},
            "product_impressions": impressions,
            "product_clicks": str(clicks),
            "add_cart_count": str(clicks * Decimal("0.07")),
            "refunds": {"amount": str(gmv / 10), "currency": "VND"},
        },
        "seller_product_card_performance": {
            "product_impressions": str(Decimal(impressions) * Decimal("0.6")),
            "product_clicks": str(clicks * Decimal("0.6")),
            "attributed_sku_orders": str(orders * Decimal("0.6")),
            "attributed_sold_items": str(orders * Decimal("0.6")),
            "attributed_gmv": {"amount": str(gmv * Decimal("0.6")), "currency": "VND"},
        },
        "shop_tab_performance": {
            "shop_tab_product_impressions": str(Decimal(impressions) * Decimal("0.4")),
            "shop_tab_product_clicks": str(clicks * Decimal("0.4")),
            "shop_tab_ctor_sku": ctor,
            "shop_tab_sold_items": str(orders * Decimal("0.4")),
            "shop_tab_gmv": {"amount": str(gmv * Decimal("0.4")), "currency": "VND"},
        },
        "seller_video_performance": {"attributed_sku_orders": 0},
        "seller_live_performance": {"attributed_sku_orders": str(orders * Decimal("0.1"))},
        "affiliate_total_performance": {"attributed_sku_orders": str(orders * Decimal("0.3"))},
    }


def _fixture_rows() -> dict[str, dict[str, dict]]:
    """Rows per window per product id. Volumes differ so the GMV ranking is strict."""
    healthy = [f"peer-{i}" for i in range(6)]
    windows: dict[str, dict[str, dict]] = {k: {} for k in ("c14", "p28", "l28", "c30", "p30")}
    spec: dict[str, tuple[str, str, int]] = {pid: ("0.08", "0.10", 200000) for pid in healthy}
    spec["weak"] = ("0.03", "0.10", 200000)
    spec["gift"] = ("0.08", "0.10", 200000)
    spec["dead"] = ("0.08", "0.10", 200000)
    # Impressions per 30 days: gift and dead out-sell everyone, so exclusion is observable.
    volume30 = {pid: 20000 * (i + 1) for i, pid in enumerate(healthy)}
    volume30.update({"weak": 70000, "gift": 900000, "dead": 800000})
    for pid, (ctr, ctor, aov) in spec.items():
        windows["c14"][pid] = _row(pid, 10000, ctr, ctor, aov)
        windows["p28"][pid] = _row(pid, 20000, "0.08" if pid == "weak" else ctr, ctor, aov)
        windows["l28"][pid] = _row(pid, 20000, ctr, ctor, aov)
        windows["c30"][pid] = _row(pid, volume30[pid], ctr, ctor, aov)
        windows["p30"][pid] = _row(pid, int(volume30[pid] * 0.8), ctr, ctor, aov)
    return windows


def _product_payload(pid: str, title: str, status: str, *, clean_listing: bool) -> dict:
    description = "Mô tả chi tiết sản phẩm.\n" * 30 if clean_listing else "Ngắn."
    images = 6 if clean_listing else 1
    return {
        "id": pid,
        "title": title,
        "status": status,
        "description": description,
        "main_images": [
            {"uri": f"img-{pid}-{i}", "width": 800, "height": 800} for i in range(images)
        ],
    }


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))


def _snapshot(tmp_path: Path, *, with_diagnosis: bool) -> tuple[Path, dict[str, dict[str, dict]]]:
    snap = tmp_path / "snapshot"
    rows = _fixture_rows()
    names = {"c14": "a34_current", "p28": "a34_prior", "l28": "a34_last28"}
    names.update({"c30": "a34_30d_current", "p30": "a34_30d_previous"})
    for key, name in names.items():
        _write(snap / f"{name}.json", {"products": list(rows[key].values())})
    _write(snap / "meta.json", {"as_of": "2026-10-05", "shop_name": "Cửa hàng thử <1>"})
    for pid in rows["c30"]:
        title = (
            TRICKY_TITLE if pid == "weak" else f"Sản phẩm {pid} chính hãng dung tích lớn loại một"
        )
        status = "SELLER_DEACTIVATED" if pid == "dead" else "ACTIVATE"
        if pid == "gift":
            title = "[Quà tặng] Chai xịt thử không bán kèm đơn hàng của shop"
        clean = pid == "weak" or pid.startswith("peer")
        _write(
            snap / "products" / f"{pid}.json",
            _product_payload(pid, title, status, clean_listing=clean),
        )
    if with_diagnosis:
        _write(
            snap / "diagnoses" / "weak.json",
            {
                "id": "weak",
                "diagnoses": [
                    {
                        "field": "IMAGE",
                        "diagnosis_results": [
                            {"code": PSORIASIS, "how_to_solve": "Ảnh bìa không được có logo chìm."}
                        ],
                        "suggestion": {"images": [{"uri": "a"}, {"uri": "b"}]},
                    }
                ],
            },
        )
    return snap, rows


def _gmv(row: dict) -> Decimal:
    return Decimal(row["total_performance"]["gmv"]["amount"])


def _live_ids() -> list[str]:
    return [pid for pid in _fixture_rows()["c30"] if pid not in {"gift", "dead"}]


@pytest.fixture
def pending_report(tmp_path: Path) -> ShopReport:
    snap, _ = _snapshot(tmp_path, with_diagnosis=False)
    return build_shop_report(snap)


@pytest.fixture
def rule_report(tmp_path: Path) -> ShopReport:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    return build_shop_report(snap)


def test_top_five_by_gmv_excludes_gift_and_inactive(pending_report: ShopReport) -> None:
    rows = _fixture_rows()["c30"]
    expected = sorted(_live_ids(), key=lambda pid: _gmv(rows[pid]), reverse=True)[:TOP_N]
    assert [p.product_id for p in pending_report.top_products] == expected
    assert "gift" not in expected and "dead" not in expected
    shares = [p.gmv_share.current for p in pending_report.top_products]
    assert all(s is not None for s in shares)
    assert sum(s for s in shares if s is not None) <= Decimal(1)
    live_total = sum(_gmv(rows[pid]) for pid in _live_ids())
    first = pending_report.top_products[0]
    assert first.gmv_share.current == _gmv(rows[first.product_id]) / live_total


def test_exclusions_are_counted(pending_report: ShopReport) -> None:
    assert pending_report.exclusions == {"gift": 1, "inactive": 1, "no_detail": 0}
    html_text = render_html(pending_report)
    assert "1 sản phẩm bị loại vì tiêu đề" in html_text


def test_shop_average_math_is_sums_then_ratios(pending_report: ShopReport) -> None:
    rows = _fixture_rows()
    by_key = {r.key: r.delta for r in pending_report.shop_rows}
    for window, field_name in (("c30", "current"), ("p30", "previous")):
        live = [rows[window][pid]["total_performance"] for pid in _live_ids()]
        gmv = sum(Decimal(t["gmv"]["amount"]) for t in live)
        orders = sum(Decimal(t["sku_orders"]) for t in live)
        clicks = sum(Decimal(t["product_clicks"]) for t in live)
        items = sum(Decimal(t["items_sold"]) for t in live)
        assert getattr(by_key["aov"], field_name) == gmv / orders
        assert getattr(by_key["ctor"], field_name) == orders / clicks
        assert getattr(by_key["items_per_order"], field_name) == items / orders
        assert getattr(by_key["orders_per_day"], field_name) == orders / 30
    aov = by_key["aov"]
    assert aov.current is not None and aov.previous is not None
    assert aov.abs == aov.current - aov.previous


def test_group_table_splits_top_five_from_the_rest(pending_report: ShopReport) -> None:
    rows = _fixture_rows()["c30"]
    top = {p.product_id for p in pending_report.top_products}
    share = next(r for r in pending_report.group_rows if r.key == "gmv_share")
    live_total = sum(_gmv(rows[pid]) for pid in _live_ids())
    assert share.top.current is not None
    assert share.top.current == sum(_gmv(rows[pid]) for pid in top) / live_total
    assert share.rest.current is not None
    assert share.top.current + share.rest.current == Decimal(1)
    assert {r.product_id for r in pending_report.rest_products} == set(_live_ids()) - top


def test_channel_share_uses_attributed_orders(pending_report: ShopReport) -> None:
    rows = _fixture_rows()["c30"]
    block = pending_report.top_products[0]
    item = rows[block.product_id]
    orders = Decimal(item["total_performance"]["sku_orders"])
    live = Decimal(item["seller_live_performance"]["attributed_sku_orders"])
    shares = dict(block.channels)
    attributed = sum(
        Decimal(item[name]["attributed_sku_orders"])
        for name in ("seller_live_performance", "affiliate_total_performance")
    ) + Decimal(item["seller_product_card_performance"]["attributed_sku_orders"])
    attributed += Decimal(item["shop_tab_performance"]["shop_tab_product_clicks"]) * Decimal(
        item["shop_tab_performance"]["shop_tab_ctor_sku"]
    )
    assert attributed > orders  # the fixture over-attributes, as TikTok does
    assert shares["LIVE của shop"] == live / attributed * 100
    assert sum(shares.values()) == 100  # normalised over the five blocks
    assert "Video của shop" not in shares  # zero channels are not shown


def test_not_asked_card_when_gap_fires_without_evidence(pending_report: ShopReport) -> None:
    weak = next(c for c in pending_report.cards if c.product_id == "weak")
    assert weak.status == STATUS_NOT_ASKED
    assert weak.main_kpi == "CTOR"
    assert weak.reason.startswith("CTR thẻ sản phẩm ước tính thấp hơn")
    assert weak.change == "Thay ảnh bìa, nếu TikTok chỉ ra lỗi"
    assert len(pending_report.cards) <= CONFIG.max_open_cards_per_shop


def test_card_becomes_a_rule_card_with_the_unlisted_image_code(rule_report: ShopReport) -> None:
    weak = next(c for c in rule_report.cards if c.product_id == "weak")
    assert weak.status == STATUS_RULE
    assert weak.change == "Thay ảnh bìa"
    assert [r.part for r in rule_report.diagnoses] == ["Ảnh bìa"]
    assert rule_report.diagnoses[0].suggested_images == 2
    assert rule_report.diagnoses[0].code == PSORIASIS
    ranks = [c.rank for c in rule_report.cards]
    assert ranks == list(range(1, len(ranks) + 1))


def test_html_is_a_fragment_with_the_card_columns(rule_report: ShopReport) -> None:
    text = render_html(rule_report)
    assert text.startswith("<title>Báo cáo tối ưu ")
    assert not re.search(r"<!doctype|<html[\s>]|<head[\s>]|<body[\s>]", text, re.IGNORECASE)
    assert "fonts.googleapis.com" in text and "<style>" in text
    for header in CARD_HEADERS:
        assert f"<th>{header}</th>" in text
    assert text.count(TECH_HEADING) == 1
    assert text.index("Chỉ số trung bình của shop") < text.index(TECH_HEADING)
    assert text.count('<div class="tablewrap">') >= 5


def test_technical_terms_stay_below_the_technical_heading(rule_report: ShopReport) -> None:
    text = render_html(rule_report)
    above, below = text.split(TECH_HEADING)
    assert "/product/" not in above and "MAIN_IMG" not in above
    assert "/product/" in below and "MAIN_IMG" in below
    visible = re.sub(r"<style>.*?</style>", "", above, flags=re.DOTALL)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert not re.search(r"\b(rule|slot|floor|gap|endpoint)\b|ADR-|_performance", visible)


def test_titles_are_escaped(rule_report: ShopReport) -> None:
    text = render_html(rule_report)
    assert "<b>X</b>" not in text
    assert "&lt;b&gt;X&lt;/b&gt; &amp; Co" in text
    assert "<1>" not in text  # shop name is escaped too


def test_vietnamese_number_format() -> None:
    assert fmt_value("money", Decimal("1234567.5")) == "1.234.568 ₫"
    assert fmt_value("ratio", Decimal("0.05346")) == "5,35 %"
    assert fmt_value("dec2", Decimal("1234.567")) == "1.234,57"
    assert fmt_value("ratio", None) == "—"


def test_report_json_roundtrips(rule_report: ShopReport) -> None:
    data = json.loads(rule_report.to_json())
    assert data["as_of"] == "2026-10-05"
    assert data["windows"]["current_30d"] == ["2026-09-06", "2026-10-05"]
    assert data["windows"]["previous_30d"] == ["2026-08-07", "2026-09-05"]
    assert [c["rank"] for c in data["cards"]] == [c.rank for c in rule_report.cards]


def test_window_metrics_accepts_string_money() -> None:
    row = _row("p", 1000, "0.1", "0.1", 100)
    row["total_performance"]["gmv"] = "1000"
    assert window_metrics(row, days=10)["aov"] == Decimal(1000) / Decimal(10)


def test_wrapper_script_keeps_import_discipline() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "shop_optimization_report.py"
    spec = importlib.util.spec_from_file_location("shop_optimization_report", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    top_level = [
        line for line in script.read_text().splitlines() if line.startswith(("import ", "from "))
    ]
    assert not any("juli_backend" in line for line in top_level)
    assert "juli_backend.workers" not in script.read_text()


def _with_files(tmp_path: Path, *, diagnosis: bool = True, **files: object) -> ShopReport:
    snap, _ = _snapshot(tmp_path, with_diagnosis=diagnosis)
    for name, payload in files.items():
        _write(snap / f"{name}.json", payload)
    return build_shop_report(snap)


def _order(product_id: str, quantity: int, status: str = "COMPLETED") -> dict:
    return {
        "status": status,
        "create_time": IN_WINDOW,  # inside the current 30 days of the fixture's as_of
        "line_items": [{"product_id": product_id, "is_gift": False}] * quantity,
    }


def test_channel_shares_total_one_hundred_and_copy_says_so(rule_report: ShopReport) -> None:
    for block in rule_report.top_products:
        assert sum(share for _, share in block.channels) == 100
    text = render_html(rule_report)
    above, below = text.split(TECH_HEADING)
    assert "Tỷ trọng kênh" in above and "Kênh ra đơn" not in text
    assert "chồng lên nhau" not in above
    assert "chuẩn hóa" in below


def test_ratings_below_four_stars_block_every_card(tmp_path: Path) -> None:
    ratings = {"weak": {"rating": 3.6, "review_count": 8}, "peer-0": {"rating": 4.8}}
    report = _with_files(tmp_path, ratings=ratings)
    assert all(c.product_id != "weak" for c in report.cards)
    [row] = [w for w in report.watch if w.product_id == "weak"]
    assert row.reason == "Điểm đánh giá 3,6 sao, cần cải thiện sản phẩm trước"
    assert report.technical["ratings_applied"] is True
    text = render_html(report)
    assert "Sản phẩm cần theo dõi" in text and "nhập tay / FastMoss" in text.split(TECH_HEADING)[1]


def test_absent_ratings_file_applies_no_filter(rule_report: ShopReport) -> None:
    assert any(c.product_id == "weak" for c in rule_report.cards)
    assert rule_report.technical["ratings_applied"] is False
    assert "không áp dụng" in render_html(rule_report).split(TECH_HEADING)[1]


def test_owner_tests_become_cards_after_rule_cards(tmp_path: Path) -> None:
    orders = [_order("peer-0", q) for q in [1] * 20 + [2] * 5] + [_order("peer-0", 4, "CANCELLED")]
    tests = [
        {"product_id": "peer-0", "angle": "mua nhiều giảm nhiều"},
        {
            "product_id": "peer-1",
            "angle": "quà tặng kèm",
            "gift_product_id": "peer-2",
            "note": "Thử quà cho khách mua nhiều",
        },
        {"product_id": "peer-3", "angle": "ảnh bìa"},
    ]
    report = _with_files(tmp_path, orders={"orders": orders}, owner_tests=tests)
    statuses = [c.status for c in report.cards]
    assert (
        statuses
        == [STATUS_RULE, STATUS_OWNER, STATUS_OWNER, STATUS_OWNER, STATUS_NOT_ASKED][
            : len(statuses)
        ]
    )
    assert statuses[0] == STATUS_RULE and statuses.count(STATUS_OWNER) == 3
    bmsm, gift, cover = (c for c in report.cards if c.status == STATUS_OWNER)
    assert (bmsm.main_kpi, gift.main_kpi, cover.main_kpi) == ("AOV", "AOV", "CTOR")
    assert bmsm.change == "Mua nhiều giảm nhiều, từ 2 món"  # median 1 + 1
    assert "20 %" in bmsm.reason  # 5 of 25 orders; neutral reason from the orders
    assert "AOV 30 ngày qua" in bmsm.reason
    assert gift.reason == "Thử quà cho khách mua nhiều"
    assert "Sản phẩm peer-2" in gift.change and "từ 2 món" in gift.change
    assert cover.change == "Thay ảnh bìa"
    assert [c.rank for c in report.cards] == list(range(1, len(report.cards) + 1))


def test_rule_card_wins_over_an_owner_test_on_the_same_product(tmp_path: Path) -> None:
    tests = [{"product_id": "weak", "angle": "tiêu đề"}]
    report = _with_files(tmp_path, owner_tests=tests)
    assert [c.status for c in report.cards if c.product_id == "weak"] == [STATUS_RULE]
    assert report.technical["owner_tests_dropped_rule_card_wins"] == ["weak"]
    assert "card của Juli thắng" in render_html(report).split(TECH_HEADING)[1]


def test_extra_cards_go_to_the_watch_list(tmp_path: Path) -> None:
    tests = [{"product_id": f"peer-{i}", "angle": "tiêu đề"} for i in range(6)]
    report = _with_files(tmp_path, diagnosis=False, owner_tests=tests)
    assert len(report.cards) == CONFIG.max_open_cards_per_shop
    assert [c.status for c in report.cards] == [STATUS_OWNER] * 5
    # The sixth owner test and the "Chưa hỏi TikTok" card both lose their row.
    overflow = {w.product_id for w in report.watch if w.reason.startswith("Đủ điều kiện")}
    assert overflow == {"peer-5", "weak"}


def test_discount_cap_needed_card_when_ctr_is_healthy(tmp_path: Path) -> None:
    snap, rows = _snapshot(tmp_path, with_diagnosis=True)
    # Weak CTOR, healthy CTR on a product whose diagnosis file lists no description code.
    for name in ("a34_current", "a34_prior", "a34_last28"):
        data = json.loads((snap / f"{name}.json").read_text())
        data["products"] = [
            _row("weak", 10000 if name == "a34_current" else 20000, "0.08", "0.04", 200000)
            if p["id"] == "weak"
            else p
            for p in data["products"]
        ]
        _write(snap / f"{name}.json", data)
    report = build_shop_report(snap)
    [card] = [c for c in report.cards if c.product_id == "weak"]
    assert card.status == STATUS_NEEDS_CAP
    assert card.change == "Giảm giá sản phẩm, sau khi shop đặt mức giảm giá tối đa"
    assert card.reason.startswith("CTOR ước tính")
    _write(snap / "meta.json", {"as_of": "2026-10-05", "max_discount_percent": 15})
    capped = build_shop_report(snap)
    [card] = [c for c in capped.cards if c.product_id == "weak"]
    assert card.status == STATUS_RULE and card.change == "Tạo giảm giá sản phẩm 30 ngày"


def test_legend_lists_only_statuses_that_occur(tmp_path: Path) -> None:
    report = _with_files(
        tmp_path, diagnosis=False, owner_tests=[{"product_id": "peer-0", "angle": "tiêu đề"}]
    )
    above = render_html(report).split(TECH_HEADING)[0]
    assert "Chưa hỏi TikTok" in above and "Thử nghiệm theo kế hoạch của bạn" in above
    assert "Cần mức giảm giá tối đa" not in above and "Chờ TikTok" not in above
    assert "công cụ chẩn đoán của TikTok chưa được chạy" in above


def test_bad_owner_test_angle_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="owner test"):
        _with_files(tmp_path, owner_tests=[{"product_id": "weak", "angle": "đổi tên"}])

"""Shipping discount, gift fallback, guarded flash sale, Seller Center cards, order windows.

ADR-106 amendment 5. Scenarios start from the synthetic shop of
``test_shop_optimization_report`` (as_of 2026-10-05: current 30 days
2026-09-06..2026-10-05, previous 2026-08-07..2026-09-05) and add exactly the data a
lever needs; expectations come from the fixture numbers, not from restated rules.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from juli_backend.integrations.tiktok.resources.orders import OrdersResource
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.levers import (
    bundle_pairs,
    find_gift,
    flash_eval,
    min_spend_eval,
    product_stock,
    shipping_eval,
)
from juli_backend.services.optimize_product.order_windows import (
    orders_between,
    summarize,
)
from juli_backend.services.optimize_product.promotions import parse_promotions
from juli_backend.services.optimize_product.shop_report import (
    NO_ORDERS_IN_WINDOW,
    STATUS_NEEDS_CAP,
    STATUS_OWNER,
    STATUS_RULE,
    STATUS_SC,
    WATCH_DISCOUNT_RUNNING,
    WATCH_NO_GIFT,
    ShopReport,
    build_shop_report,
    render_html,
)
from tests.unit.test_shop_optimization_report import (
    TECH_HEADING,
    _row,
    _snapshot,
    _write,
)

CONFIG = StageDiagnosisConfig()
ZONE = timezone(timedelta(hours=7))
AS_OF = date(2026, 10, 5)
SKU = "sku-1"
LIST_PRICE = "200000"
_ids = itertools.count(1)


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=ZONE).timestamp())


def _order(
    day: date,
    *products: str,
    ship: str = "0",
    price: str = "200000",
    platform: str = "0",
    status: str = "COMPLETED",
) -> dict:
    return {
        "id": str(next(_ids)),
        "status": status,
        "create_time": _ts(day),
        "payment": {"shipping_fee": ship},
        "line_items": [
            {
                "product_id": pid,
                "sku_id": SKU,
                "sale_price": price,
                "platform_discount": platform,
                "is_gift": False,
            }
            for pid in products
        ],
    }


def _detail(pid: str, *, price: str, stock: int, warehouse: str = "W1") -> dict:
    return {
        "id": pid,
        "title": f"Sản phẩm {pid} chính hãng dung tích lớn loại một",
        "status": "ACTIVATE",
        "description": "Mô tả chi tiết sản phẩm.\n" * 30,
        "main_images": [{"uri": f"i{i}", "width": 800, "height": 800} for i in range(6)],
        "skus": [
            {
                "id": SKU,
                "price": {"sale_price": price},
                "inventory": [{"quantity": stock, "warehouse_id": warehouse}],
            }
        ],
    }


def _page_shop(tmp_path: Path, *, cap: int | None = 30) -> Path:
    """peer-5 has a CTOR gap with a healthy CTR and a clean listing: a page-branch product."""
    snap, _ = _snapshot(tmp_path, with_diagnosis=False)
    for name, impressions in (("a34_current", 10000),):
        path = snap / f"{name}.json"
        rows = [r for r in __import__("json").loads(path.read_text())["products"]]
        rows = [r for r in rows if r["id"] != "peer-5"]
        rows.append(_row("peer-5", impressions, "0.08", "0.05", 200000))
        _write(path, {"products": rows})
    meta = {"as_of": AS_OF.isoformat(), "shop_name": "Shop"}
    if cap is not None:
        meta["max_discount_percent"] = cap
    _write(snap / "meta.json", meta)
    _write(snap / "products" / "peer-5.json", _detail("peer-5", price=LIST_PRICE, stock=500))
    _write(snap / "diagnoses" / "peer-5.json", {"id": "peer-5", "diagnoses": []})  # TikTok asked
    return snap


def _promotions(snap: Path, pid: str, *, flash_days_ago: int | None = None) -> None:
    def at(day: date) -> int:
        return _ts(day)

    activities = [
        {
            "id": "d1",
            "status": "ONGOING",
            "activity_type": "FIXED_PRICE",
            "title": "Giảm giá",
            "begin_time": at(AS_OF - timedelta(days=10)),
            "end_time": at(AS_OF + timedelta(days=10)),
        }
    ]
    details = {"d1": {"products": [{"id": pid, "discount": 10}]}}
    if flash_days_ago is not None:
        start = AS_OF - timedelta(days=flash_days_ago)
        activities.append(
            {
                "id": "f1",
                "status": "EXPIRED",
                "activity_type": "FLASHSALE",
                "title": "Flash",
                "begin_time": at(start),
                "end_time": at(start + timedelta(days=2)),
            }
        )
        details["f1"] = {"products": [{"id": pid}]}
    _write(snap / "promotions" / "activities.json", {"activities": activities})
    _write(snap / "promotions" / "coupons.json", {"coupons": []})
    _write(snap / "promotions" / "activity_details.json", details)


def _shipping_orders(pid: str, total: int, paid: int) -> list[dict]:
    day = AS_OF - timedelta(days=20)  # outside the last 14 days
    return [
        _order(day, pid, ship="30000" if i < paid else "0", price="190000") for i in range(total)
    ]


def _card(report: ShopReport, pid: str):
    return next((c for c in report.cards if c.product_id == pid), None)


def _build(snap: Path, orders: list[dict] | None = None) -> ShopReport:
    if orders is not None:
        _write(snap / "orders.json", {"orders": orders})
    return build_shop_report(snap)


# --------------------------------------------------------------------------- shipping


def test_product_discount_still_comes_first(tmp_path: Path) -> None:
    snap = _page_shop(tmp_path)
    report = _build(snap, _shipping_orders("peer-5", 25, 10))
    card = _card(report, "peer-5")
    assert card is not None and card.status == STATUS_RULE
    assert card.change == "Tạo giảm giá sản phẩm 30 ngày"


def test_shipping_discount_when_buyers_pay_shipping(tmp_path: Path) -> None:
    snap = _page_shop(tmp_path)
    _promotions(snap, "peer-5", flash_days_ago=5)  # discount taken, flash blocked
    report = _build(snap, _shipping_orders("peer-5", 25, 10))
    card = _card(report, "peer-5")
    assert card is not None
    assert card.change == "Giảm phí vận chuyển 30 ngày, trong mức giảm tối đa của shop"
    assert "40 % đơn khách tự trả phí vận chuyển" in card.reason
    assert report.technical["shipping_lever"]["passed"]["peer-5"]["orders"] == 25


def test_shipping_gate_needs_the_paid_share(tmp_path: Path) -> None:
    snap = _page_shop(tmp_path)
    _promotions(snap, "peer-5", flash_days_ago=5)
    report = _build(snap, _shipping_orders("peer-5", 25, 5))  # 20 % < 30 %
    assert _card(report, "peer-5") is None
    [row] = [w for w in report.watch if w.product_id == "peer-5"]
    assert row.reason == WATCH_DISCOUNT_RUNNING
    assert "đã có flash sale trong 14 ngày qua" in row.detail


def test_shipping_gate_needs_enough_orders(tmp_path: Path) -> None:
    eval_ = shipping_eval(_shipping_orders("p", CONFIG.shipping_lever_min_orders - 1, 19), CONFIG)
    assert eval_.verdict == "insufficient_orders" and not eval_.ok
    edge = shipping_eval(_shipping_orders("p", 20, 6), CONFIG)
    assert edge.ok and edge.share == Decimal("0.3")


# --------------------------------------------------------------------------- flash sale


def _recent_orders(pid: str, price: str, n: int = 12) -> list[dict]:
    return [_order(AS_OF - timedelta(days=3), pid, price=price) for _ in range(n)]


def test_flash_sale_replaces_the_blocked_discount(tmp_path: Path) -> None:
    snap = _page_shop(tmp_path)
    _promotions(snap, "peer-5")
    orders = [*_recent_orders("peer-5", "180000"), *_recent_orders("peer-5", "190000")]
    report = _build(snap, orders)
    card = _card(report, "peer-5")
    assert card is not None and card.status == STATUS_RULE
    assert card.change.startswith("Flash sale 3 ngày, giá 178.200 ₫")
    assert "bạn cần xác nhận shop đủ điều kiện tham gia flash sale" in card.change
    assert "36" not in card.change  # the violation-point note is technical only
    tech = render_html(report).split(TECH_HEADING)[1]
    assert "cần xác nhận điểm vi phạm &lt; 36 trước khi chạy" in tech
    chosen = report.technical["flash_sale"]["chosen"]["peer-5"]
    assert chosen["proposed_price"] == 178200 and chosen["days"] == 3


def _flash(**overrides: object):
    stock = product_stock("p", _detail("p", price=LIST_PRICE, stock=100))
    args: dict = {
        "product_id": "p",
        "orders_low_window": _recent_orders("p", "180000"),
        "stock": stock,
        "promotions": parse_promotions({"activities": []}, {"coupons": []}, {}, (AS_OF, AS_OF)),
        "as_of": AS_OF,
        "max_discount_percent": Decimal(30),
        "config": CONFIG,
    }
    args.update(overrides)
    return flash_eval(**args)


def test_flash_guard_all_pass() -> None:
    result = _flash()
    assert result.ok and result.failed == () and result.proposed_price == Decimal(178200)
    assert result.discount is not None and result.discount < Decimal("0.3")


def test_flash_never_without_promotion_data() -> None:
    result = _flash(promotions=None)
    assert not result.ok and "promotion_data_missing" in result.failed


def test_flash_blocked_by_a_flash_sale_in_the_last_14_days() -> None:
    start = _ts(AS_OF - timedelta(days=13))
    activities = {
        "activities": [
            {
                "id": "f",
                "status": "EXPIRED",
                "activity_type": "FLASHSALE",
                "begin_time": start,
                "end_time": start + 86400,
            }
        ]
    }
    index = parse_promotions(
        activities,
        {"coupons": []},
        {"f": {"products": [{"id": "p"}]}},
        (
            AS_OF - timedelta(days=29),
            AS_OF,
        ),
    )
    assert "flash_sale_in_last_14_days" in _flash(promotions=index).failed
    # A flash sale that ended before the 14-day look-back does not block.
    old = _ts(AS_OF - timedelta(days=20))
    activities["activities"][0].update(begin_time=old, end_time=old + 86400)
    index = parse_promotions(
        activities,
        {"coupons": []},
        {"f": {"products": [{"id": "p"}]}},
        (
            AS_OF - timedelta(days=29),
            AS_OF,
        ),
    )
    assert _flash(promotions=index).ok


def test_flash_blocked_when_the_cut_exceeds_the_maximum_discount() -> None:
    result = _flash(orders_low_window=_recent_orders("p", "100000"))  # 50 % below list
    assert "discount_over_maximum" in result.failed and not result.ok
    assert "max_discount_not_set" in _flash(max_discount_percent=None).failed


def test_flash_blocked_without_orders_in_the_window_or_a_list_price() -> None:
    assert "no_orders_in_window" in _flash(orders_low_window=[]).failed
    assert "list_price_unknown" in _flash(stock=None).failed


def test_flash_duration_must_stay_within_one_to_three_days() -> None:
    config = StageDiagnosisConfig(flash_default_days=5)
    assert "duration_out_of_range" in _flash(config=config).failed


def test_flash_price_uses_the_lowest_paid_price_net_of_platform_discount() -> None:
    orders = [_order(AS_OF, "p", price="190000", platform="20000"), *_recent_orders("p", "180000")]
    result = _flash(orders_low_window=orders)
    assert result.low_price == Decimal(170000)


def test_flash_blocked_card_goes_to_the_watch_list(tmp_path: Path) -> None:
    snap = _page_shop(tmp_path, cap=5)  # 5 % cap, the cut would be about 11 %
    _promotions(snap, "peer-5")
    report = _build(snap, _recent_orders("peer-5", "180000"))
    assert _card(report, "peer-5") is None
    [row] = [w for w in report.watch if w.product_id == "peer-5"]
    assert "mức giảm cần có vượt mức giảm giá tối đa của shop" in row.detail


# --------------------------------------------------------------------------- gift fallback


def _gift_shop(tmp_path: Path, *, with_skus: bool = True, ratings: dict | None = None) -> Path:
    """peer-4 has an AOV gap and a basket nobody grows; peers 0-3 and 5 are gift candidates."""
    snap, _ = _snapshot(tmp_path, with_diagnosis=False)
    path = snap / "a34_current.json"
    import json

    rows = [r for r in json.loads(path.read_text())["products"] if r["id"] != "peer-4"]
    rows.append(_row("peer-4", 10000, "0.08", "0.10", 100000))
    _write(path, {"products": rows})
    _write(snap / "meta.json", {"as_of": AS_OF.isoformat(), "max_discount_percent": 30})
    if with_skus:
        spec = {
            "peer-4": ("200000", 500, "W1"),
            "peer-0": ("25000", 100, "W1"),
            "peer-1": ("20000", 100, "W1"),
            "peer-2": ("10000", 10, "W1"),  # not enough stock
            "peer-3": ("10000", 100, "W2"),  # other warehouse
            "peer-5": ("90000", 100, "W1"),  # above 15 % of the AOV
        }
        for pid, (price, stock, wh) in spec.items():
            _write(
                snap / "products" / f"{pid}.json",
                _detail(pid, price=price, stock=stock, warehouse=wh),
            )
    _write(snap / "ratings.json", ratings or {})
    if ratings is None:
        (snap / "ratings.json").unlink()
    _write(
        snap / "orders.json",
        {"orders": [_order(AS_OF - timedelta(days=i % 25), "peer-4") for i in range(30)]},
    )
    return snap


def test_gift_fallback_picks_the_cheapest_without_ratings(tmp_path: Path) -> None:
    report = build_shop_report(_gift_shop(tmp_path))
    card = _card(report, "peer-4")
    assert card is not None and card.status == STATUS_RULE and card.main_kpi == "AOV"
    assert card.change.startswith("Tặng kèm Sản phẩm peer-1 ") and "từ 2 món" in card.change
    detail = report.technical["gift"]["products"]["peer-4"]
    assert detail["gift_product_id"] == "peer-1"
    # peer-2 and the unstocked "weak" listing fail on stock; peer-3 on warehouse; peer-5 on price.
    assert detail["rejected"] == {"stock": 2, "warehouse": 1, "price": 1}


def test_gift_fallback_prefers_the_fewest_reviews(tmp_path: Path) -> None:
    ratings = {
        "peer-0": {"rating": 4.8, "review_count": 3},
        "peer-1": {"rating": 4.8, "review_count": 50},
        "peer-4": {"rating": 4.8, "review_count": 60},
    }
    report = build_shop_report(_gift_shop(tmp_path, ratings=ratings))
    card = _card(report, "peer-4")
    assert card is not None and card.change.startswith("Tặng kèm Sản phẩm peer-0 ")


def test_no_gift_candidate_goes_to_the_watch_list(tmp_path: Path) -> None:
    report = build_shop_report(_gift_shop(tmp_path, with_skus=False))
    assert _card(report, "peer-4") is None
    [row] = [w for w in report.watch if w.product_id == "peer-4"]
    assert row.reason == WATCH_NO_GIFT == "Không có sản phẩm phù hợp làm quà"


def test_gift_limits_are_hard_caps() -> None:
    main = product_stock("m", _detail("m", price="1", stock=500))
    rich = product_stock("c", _detail("c", price="1600000", stock=500))
    assert main is not None and rich is not None
    # 15 % of a 20.000.000 AOV is 3.000.000, but the cap is 1.500.000.
    miss = find_gift(main, Decimal(20_000_000), [rich], None, CONFIG)
    assert miss.choice is None and miss.max_price == Decimal(1_500_000)
    assert find_gift(None, Decimal(1), [rich], None, CONFIG).choice is None


# --------------------------------------------------------------------------- Seller Center


def _sc_shop(tmp_path: Path, **ratings: int) -> Path:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    if ratings:
        _write(
            snap / "ratings.json",
            {pid: {"rating": 4.8, "review_count": n} for pid, n in ratings.items()},
        )
    return snap


def test_review_voucher_card(tmp_path: Path) -> None:
    report = build_shop_report(_sc_shop(tmp_path, **{"peer-1": 5, "peer-2": 400}))
    card = _card(report, "peer-1")
    assert card is not None and card.status == STATUS_SC
    assert (card.main_kpi, card.main_kpi_value) == ("Đánh giá", "5")
    assert card.change == "Tạo voucher đánh giá trên Seller Center cho sản phẩm này"
    assert "mới có 5 đánh giá" in card.reason
    assert _card(report, "peer-2") is None  # 400 reviews
    assert "ghi lại ngày bắt đầu" in render_html(report).split(TECH_HEADING)[1]


def test_review_voucher_is_silent_without_the_ratings_file(tmp_path: Path) -> None:
    report = build_shop_report(_sc_shop(tmp_path))
    assert not any(c.status == STATUS_SC for c in report.cards)
    assert report.technical["seller_center"]["review_voucher"]["status"] == "skipped"


def _together(first: str, second: str, together: int) -> list[dict]:
    day = AS_OF - timedelta(days=4)
    return [
        *(_order(day, first, second) for _ in range(together)),
        *(_order(day, first) for _ in range(40)),
        *(_order(day, second) for _ in range(40)),
    ]


def test_bundle_card_from_co_purchase(tmp_path: Path) -> None:
    report = _build(_sc_shop(tmp_path), _together("peer-1", "peer-2", 4))
    card = next(c for c in report.cards if "+" in c.title)
    assert card.status == STATUS_SC and card.main_kpi == "AOV"
    assert card.change.startswith("Tạo ưu đãi theo gói Sản phẩm peer-")
    assert card.change.endswith("trên Seller Center")
    assert report.technical["seller_center"]["bundle"]["pairs_found"] == 1


def test_bundle_pair_thresholds() -> None:
    live = {"a", "b"}
    assert bundle_pairs(_together("a", "b", 2), live, CONFIG) == []  # under 3 orders
    assert bundle_pairs(_together("a", "b", 3), live, CONFIG)[0].together == 3
    thin = [*_together("a", "b", 3), *[_order(AS_OF, "a") for _ in range(100)]]
    # 3 of 143 is 2 % for a, but 3 of 43 is 7 % for b: either product is enough.
    assert bundle_pairs(thin, live, CONFIG)
    thick = [*thin, *[_order(AS_OF, "b") for _ in range(100)]]
    assert bundle_pairs(thick, live, CONFIG) == []


def _falling_aov(snap: Path) -> None:
    import json

    rows = json.loads((snap / "a34_30d_previous.json").read_text())["products"]
    rebuilt = [
        _row(r["id"], int(r["total_performance"]["product_impressions"]), "0.08", "0.10", 250000)
        for r in rows
    ]
    _write(snap / "a34_30d_previous.json", {"products": rebuilt})


def _multi(multi: int, single: int) -> list[dict]:
    day = AS_OF - timedelta(days=2)
    return [
        *(_order(day, "peer-1", "peer-2") for _ in range(multi)),
        *(_order(day, "peer-3") for _ in range(single)),
    ]


def test_min_spend_voucher_card(tmp_path: Path) -> None:
    snap = _sc_shop(tmp_path)
    _falling_aov(snap)
    report = _build(snap, _multi(10, 90))
    card = next(c for c in report.cards if c.kind == "voucher_chi_tieu_toi_thieu")
    assert card.title == "Toàn shop" and card.status == STATUS_SC and card.main_kpi == "AOV"
    assert card.change == "Tạo voucher giảm khi đơn từ 240.000 ₫"  # AOV 200.000 × 1,2
    assert "AOV của shop giảm 20 %" in card.reason
    assert "10 % số đơn" in card.reason


def test_min_spend_needs_both_conditions(tmp_path: Path) -> None:
    snap = _sc_shop(tmp_path)  # AOV flat: no fall
    flat = _build(snap, _multi(10, 90))
    assert flat.technical["seller_center"]["min_spend"]["verdict"] == "aov_not_down"
    _falling_aov(snap)
    few = _build(snap, _multi(2, 98))  # 2 % of orders
    assert few.technical["seller_center"]["min_spend"]["verdict"] == "few_multi"
    assert not any(c.kind == "voucher_chi_tieu_toi_thieu" for c in few.cards)
    direct = min_spend_eval(_multi(10, 90), Decimal(200000), Decimal(250000), CONFIG)
    assert direct.ok and direct.level == Decimal(240000)
    rounded = min_spend_eval(_multi(10, 90), Decimal(203000), Decimal(250000), CONFIG)
    assert rounded.level == Decimal(240000)  # 243.600 rounds to the nearest 10.000


# --------------------------------------------------------------------------- order and overflow


def test_card_order_and_overflow(tmp_path: Path) -> None:
    snap = _sc_shop(tmp_path, **{"peer-1": 5})
    tests = [{"product_id": f"peer-{i}", "angle": "tiêu đề"} for i in (2, 3, 4)]
    _write(snap / "owner_tests.json", tests)
    report = build_shop_report(snap)
    statuses = [c.status for c in report.cards]
    assert statuses == [STATUS_RULE, STATUS_OWNER, STATUS_OWNER, STATUS_OWNER, STATUS_SC]
    # One more owner test pushes the Seller Center card out of the five.
    _write(snap / "owner_tests.json", [*tests, {"product_id": "peer-5", "angle": "tiêu đề"}])
    crowded = build_shop_report(snap)
    assert [c.status for c in crowded.cards] == [STATUS_RULE, *[STATUS_OWNER] * 4]
    [row] = [w for w in crowded.watch if w.product_id == "peer-1"]
    assert row.reason == "Đủ điều kiện nhưng đã đủ 5 card"
    assert STATUS_NEEDS_CAP not in {c.status for c in crowded.cards}


def test_legend_explains_the_seller_center_status(tmp_path: Path) -> None:
    report = build_shop_report(_sc_shop(tmp_path, **{"peer-1": 5}))
    text = render_html(report).split(TECH_HEADING)[0]
    assert "Bạn tự làm trên Seller Center" in text
    assert "Juli không tạo được công cụ này qua API" in text
    assert "Seller Center" in text and "/promotion/" not in text


# --------------------------------------------------------------------------- create-time windows


def test_orders_between_reads_creation_time_in_utc_plus_7() -> None:
    first, last = date(2026, 9, 6), date(2026, 10, 5)
    edge_in = {"create_time": int(datetime(2026, 10, 5, 23, 59, tzinfo=ZONE).timestamp())}
    edge_out = {"create_time": int(datetime(2026, 10, 6, 0, 1, tzinfo=ZONE).timestamp())}
    utc_late = {"create_time": int(datetime(2026, 10, 5, 18, 0, tzinfo=UTC).timestamp())}
    # 18:00 UTC on the 5th is 01:00 on the 6th in Vietnam: outside.
    assert orders_between([edge_in, edge_out, utc_late, {}], first, last) == [edge_in]


def test_out_of_window_orders_are_never_counted_silently(tmp_path: Path) -> None:
    old = [
        _order(date(2026, 1, 10) + timedelta(days=i % 30), "peer-1", ship="30000")
        for i in range(60)
    ]
    report = _build(_sc_shop(tmp_path), old)
    window = report.technical["order_window"]
    assert window["used"] == 0 and window["excluded_out_of_window"] == 60
    assert report.technical["orders_present"] is False
    assert report.technical["shipping_lever"]["passed"] == {}
    text = render_html(report).split(TECH_HEADING)[1]
    assert NO_ORDERS_IN_WINDOW in text
    assert "10/01/2026" in text  # the range of the orders left out


def test_technical_notes_print_the_range_of_the_orders_used(tmp_path: Path) -> None:
    orders = [
        _order(date(2026, 9, 10), "peer-1"),
        _order(date(2026, 10, 1), "peer-1"),
        _order(date(2026, 8, 20), "peer-1"),  # previous window, still part of the 60 days
        _order(date(2026, 5, 1), "peer-1"),  # far outside
    ]
    report = _build(_sc_shop(tmp_path), orders)
    window = report.technical["order_window"]
    assert (window["used_first"], window["used_last"]) == ("2026-08-20", "2026-10-01")
    assert window["current_30d_orders"] == 2 and window["excluded_out_of_window"] == 1
    summary = summarize(orders, date(2026, 8, 7), date(2026, 10, 5))
    assert summary.used == 3 and summary.excluded == 1


def test_basket_histogram_reads_only_current_window_orders(tmp_path: Path) -> None:
    snap = _sc_shop(tmp_path)
    inside = [_order(AS_OF - timedelta(days=3), "peer-0") for _ in range(25)]
    stale = [_order(date(2026, 7, 1), "peer-0", "peer-0") for _ in range(25)]
    report = _build(snap, [*inside, *stale])
    assert report.technical["orders_counted"] == 25


# --------------------------------------------------------------------------- live fetch


def test_orders_search_filters_by_creation_time() -> None:
    client = MagicMock()
    client.get_all_pages.return_value = []
    OrdersResource(client).search_all(create_time_from=10, create_time_to=20)
    assert client.get_all_pages.call_args[1]["body"] == {
        "create_time_ge": 10,
        "create_time_lt": 20,
    }
    OrdersResource(client).search_all(update_time_from=5)
    assert client.get_all_pages.call_args[1]["body"] == {"update_time_ge": 5}


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "shop_optimization_report.py"
    spec = importlib.util.spec_from_file_location("shop_optimization_report_levers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeOrders:
    def __init__(self, cap_on: int | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self._cap_on = cap_on

    def search_all(self, *, create_time_from: int, create_time_to: int) -> list[dict]:
        from juli_backend.integrations.tiktok import current_pagination_scope

        self.calls.append((create_time_from, create_time_to))
        if self._cap_on == len(self.calls):
            scope = current_pagination_scope()
            assert scope is not None
            scope.truncated = True
        return [
            {"id": f"{create_time_from}-{i}", "create_time": create_time_from} for i in range(2)
        ]


class _Res:
    def __init__(self, orders: _FakeOrders) -> None:
        self.orders = orders


def test_live_fetch_pages_orders_in_seven_day_slices(tmp_path: Path) -> None:
    script = _load_script()
    fake = _FakeOrders(cap_on=3)
    record = script._fetch_orders(_Res(fake), tmp_path, "2026-08-07", "2026-10-06", sleep_s=0)
    assert record["status"] == "ok" and len(record["slices"]) == 9  # 60 days = 8 x 7 + 4
    assert [s["orders"] for s in record["slices"]] == [2] * 9
    assert record["any_slice_hit_cap"] is True
    assert [s["hit_page_cap"] for s in record["slices"]].count(True) == 1
    for (lo, hi), _ in zip(fake.calls, record["slices"], strict=True):
        assert 0 < hi - lo <= 7 * 86400
    saved = __import__("json").loads((tmp_path / "orders.json").read_text())["orders"]
    assert len(saved) == 18


def test_live_fetch_records_a_failure_without_raising(tmp_path: Path) -> None:
    script = _load_script()

    class _Boom:
        def search_all(self, **_: object) -> list[dict]:
            raise RuntimeError("access_token=abcdefghijkl failed")

    record = script._fetch_orders(_Res(_Boom()), tmp_path, "2026-08-07", "2026-10-06", sleep_s=0)
    assert record["status"] == "error" and "abcdefghijkl" not in record["message"]

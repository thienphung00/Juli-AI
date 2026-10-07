"""Traffic-source check, discount share, promotions and LIVE/video parse (ADR-106 amendment 4).

Channel rows are built from the A-34 field names; expectations come from the
fixture numbers (ADR-101), not from restated literals of the verdict rule.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.discounts import discount_shares
from juli_backend.services.optimize_product.live_video import parse_appearances
from juli_backend.services.optimize_product.promotions import clause, parse_promotions
from juli_backend.services.optimize_product.shop_report import (
    STATUS_NOT_ASKED,
    STATUS_RULE,
    ShopReport,
    build_shop_report,
    render_html,
)
from juli_backend.services.optimize_product.traffic import (
    DILUTION,
    UNCLEAR,
    UNIFORM,
    attribute_traffic,
)
from tests.unit.test_shop_optimization_report import (
    TECH_HEADING,
    _snapshot,
    _write,
)

CONFIG = StageDiagnosisConfig()
ZONE = timezone(timedelta(hours=7))


def _block(impressions: int, ctr: str) -> dict:
    return {
        "product_impressions": impressions,
        "product_clicks": str(Decimal(impressions) * Decimal(ctr)),
    }


def _item(card: tuple[int, str], **others: tuple[int, str]) -> dict:
    """An A-34 row with the named channel blocks; keys are CHANNELS block names."""
    item: dict = {"id": "p", "seller_product_card_performance": _block(*card)}
    for name, spec in others.items():
        if name == "shop_tab_performance":
            impressions = Decimal(spec[0])
            item[name] = {
                "shop_tab_product_impressions": spec[0],
                "shop_tab_product_clicks": str(impressions * Decimal(spec[1])),
            }
        else:
            item[name] = _block(*spec)
    return item


def _verdict(current: dict, previous: dict) -> str:
    return attribute_traffic("p", current, previous, CONFIG).verdict


def test_uniform_drop_in_every_qualifying_channel() -> None:
    prev = _item((3000, "0.04"), shop_tab_performance=(2000, "0.04"))
    cur = _item((3000, "0.02"), shop_tab_performance=(2000, "0.02"))
    assert _verdict(cur, prev) == UNIFORM


def test_two_thirds_rule_needs_two_of_three_channels() -> None:
    prev = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.04"),
        affiliate_video_performance=(1000, "0.04"),
    )
    two_of_three = _item(
        (3000, "0.02"),
        shop_tab_performance=(2000, "0.02"),
        affiliate_video_performance=(1000, "0.04"),
    )
    one_of_three = _item(
        (3000, "0.02"),
        shop_tab_performance=(2000, "0.04"),
        affiliate_video_performance=(1000, "0.04"),
    )
    assert _verdict(two_of_three, prev) == UNIFORM
    assert _verdict(one_of_three, prev) != UNIFORM


def test_dilution_when_only_the_spiking_channel_lost_ctr() -> None:
    prev = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.04"),
        affiliate_video_performance=(1000, "0.05"),
    )
    cur = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.041"),
        affiliate_video_performance=(4000, "0.03"),
    )
    result = attribute_traffic("p", cur, prev, CONFIG)
    assert result.verdict == DILUTION
    assert result.top_impression_source == "Video affiliate"
    assert result.diluting_channels == ("Video affiliate",)


def test_a_non_spiking_channel_that_moves_blocks_dilution() -> None:
    prev = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.04"),
        affiliate_video_performance=(1000, "0.05"),
    )
    cur = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.05"),  # +25 %, not within the stable band
        affiliate_video_performance=(4000, "0.03"),
    )
    assert _verdict(cur, prev) == UNCLEAR


def test_a_dropping_channel_that_is_not_spiking_blocks_dilution() -> None:
    prev = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.04"),
        seller_live_performance=(1000, "0.05"),
        affiliate_video_performance=(1000, "0.05"),
    )
    cur = _item(
        (3000, "0.04"),
        shop_tab_performance=(2000, "0.04"),
        seller_live_performance=(1000, "0.03"),  # dropped, impressions flat
        affiliate_video_performance=(4000, "0.03"),
    )
    assert _verdict(cur, prev) == UNCLEAR


def test_fewer_than_two_qualifying_channels_is_unclear() -> None:
    prev = _item((3000, "0.04"), shop_tab_performance=(150, "0.04"))
    cur = _item((3000, "0.02"), shop_tab_performance=(150, "0.02"))
    result = attribute_traffic("p", cur, prev, CONFIG)
    assert result.verdict == UNCLEAR
    assert [c.label for c in result.channels if c.qualifies] == ["Thẻ sản phẩm"]


def test_channel_must_clear_the_floor_in_both_windows() -> None:
    prev = _item((3000, "0.04"), shop_tab_performance=(2000, "0.04"))
    cur = _item(
        (3000, "0.02"),
        shop_tab_performance=(CONFIG.traffic_min_channel_impressions - 1, "0.01"),
    )
    assert _verdict(cur, prev) == UNCLEAR


def test_thresholds_come_from_the_config() -> None:
    prev = _item((3000, "0.04"), shop_tab_performance=(2000, "0.04"))
    cur = _item((3000, "0.036"), shop_tab_performance=(2000, "0.036"))  # -10 %
    assert _verdict(cur, prev) == UNCLEAR
    strict = StageDiagnosisConfig(traffic_ctr_drop=Decimal("0.05"))
    assert attribute_traffic("p", cur, prev, strict).verdict == UNIFORM


def test_top_source_is_the_largest_absolute_increase_per_day() -> None:
    prev = _item(
        (3000, "0.04"),
        seller_live_performance=(300, "0.05"),
        affiliate_video_performance=(3000, "0.05"),
    )
    cur = _item(
        (6000, "0.04"),
        seller_live_performance=(2400, "0.05"),
        affiliate_video_performance=(4500, "0.05"),
    )
    result = attribute_traffic("p", cur, prev, CONFIG)
    assert result.top_impression_source == "Thẻ sản phẩm"  # +3000 beats +2100 and +1500
    flat = attribute_traffic("p", prev, prev, CONFIG)
    assert flat.top_impression_source == ""


def test_per_day_uses_each_window_length() -> None:
    prev = _item((3000, "0.04"))
    cur = _item((3000, "0.04"))
    result = attribute_traffic("p", cur, prev, CONFIG, days_current=15, days_previous=30)
    card = result.channels[0]
    assert card.impressions_per_day_current == Decimal(200)
    assert card.impressions_per_day_previous == Decimal(100)
    assert card.spiking


# --------------------------------------------------------------------------- discounts


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=ZONE).timestamp())


def _order(day: date, *lines: tuple[str, str, str], status: str = "COMPLETED") -> dict:
    return {
        "status": status,
        "create_time": _ts(day),
        "line_items": [
            {"product_id": pid, "platform_discount": plat, "seller_discount": sell}
            for pid, plat, sell in lines
        ],
    }


def test_discount_share_counts_lines_per_window() -> None:
    cur = (date(2026, 9, 6), date(2026, 10, 5))
    prev = (date(2026, 8, 7), date(2026, 9, 5))
    orders = [_order(date(2026, 9, 10), ("a", "5000", "0")) for _ in range(6)]
    orders += [_order(date(2026, 9, 11), ("a", "0", "3000")) for _ in range(4)]
    orders += [_order(date(2026, 8, 20), ("a", "0", "0")) for _ in range(12)]
    orders += [_order(date(2026, 9, 12), ("a", "5000", "0"), status="CANCELLED")]
    orders += [_order(date(2026, 7, 1), ("a", "5000", "0"))]  # outside both windows
    orders.append(
        {
            "status": "COMPLETED",
            "create_time": _ts(date(2026, 9, 13)),
            "line_items": [{"product_id": "a", "is_gift": True, "platform_discount": "9"}],
        }
    )
    pair = discount_shares(orders, current=cur, previous=prev, config=CONFIG)["a"]
    assert pair.current.lines == 10
    assert pair.current.platform_share == Decimal("0.6")
    assert pair.current.seller_share == Decimal("0.4")
    assert pair.previous.lines == 12 and pair.previous.platform_share == Decimal(0)


def test_discount_share_hidden_below_the_line_floor() -> None:
    cur = (date(2026, 9, 6), date(2026, 10, 5))
    orders = [_order(date(2026, 9, 10), ("a", "5", "0"))] * (CONFIG.platform_discount_min_lines - 1)
    pair = discount_shares(
        orders, current=cur, previous=(date(2026, 8, 7), date(2026, 9, 5)), config=CONFIG
    )["a"]
    assert pair.current.lines == CONFIG.platform_discount_min_lines - 1
    assert pair.current.platform_share is None


def test_order_day_is_read_in_the_shop_timezone() -> None:
    # 20:00 UTC on 5 Oct is already 6 Oct in UTC+7, outside a window ending 5 Oct.
    late = int(datetime(2026, 10, 5, 20, tzinfo=UTC).timestamp())
    order = {"status": "COMPLETED", "create_time": late, "line_items": [{"product_id": "a"}]}
    window = (date(2026, 9, 6), date(2026, 10, 5))
    got = discount_shares(
        [order], current=window, previous=(date(2026, 8, 7), date(2026, 9, 5)), config=CONFIG
    )
    assert got == {}


# --------------------------------------------------------------------------- promotions


def test_promotions_overlapping_the_window_are_indexed_per_product() -> None:
    window = (date(2026, 9, 6), date(2026, 10, 5))
    flash_end = _ts(date(2026, 10, 12))
    activities = {
        "activities": [
            {
                "id": "A1",
                "title": "Sale 10.10",
                "activity_type": "FLASHSALE",
                "status": "ONGOING",
                "begin_time": _ts(date(2026, 10, 1)),
                "end_time": flash_end,
            },
            {
                "id": "A2",
                "title": "Cũ",
                "activity_type": "DIRECT_DISCOUNT",
                "status": "EXPIRED",
                "begin_time": _ts(date(2026, 7, 1)),
                "end_time": _ts(date(2026, 7, 8)),
            },
            {
                "id": "A3",
                "title": "Không có chi tiết",
                "activity_type": "SHIPPING_DISCOUNT",
                "status": "ONGOING",
                "begin_time": _ts(date(2026, 9, 20)),
                "end_time": _ts(date(2026, 9, 25)),
            },
        ]
    }
    details = {"A1": {"data": {"products": [{"id": "p1", "discount": "20"}]}}}
    coupons = {
        "coupons": [
            {
                "title": "Voucher shop",
                "status": "ONGOING",
                "product_scope": "FULL_SHOP",
                "claim_duration": {
                    "start_time": _ts(date(2026, 9, 1)),
                    "end_time": _ts(date(2026, 9, 30)),
                },
                "discount": {"type": "PERCENT_OFF", "percentage": "5"},
            },
            {
                "title": "Voucher riêng",
                "status": "ONGOING",
                "product_scope": "SPECIFIC_PRODUCTS",
                "claim_duration": {
                    "start_time": _ts(date(2026, 9, 1)),
                    "end_time": _ts(date(2026, 9, 30)),
                },
            },
        ]
    }
    index = parse_promotions(activities, coupons, details, window)
    [flash] = index.by_product["p1"]
    assert (flash.kind, flash.summary, flash.end) == ("Flash sale", "giảm 20 %", "2026-10-12")
    assert flash.active_at_end
    assert [i.kind for i in index.for_product("p1")] == ["Flash sale", "Voucher"]
    assert [i.kind for i in index.for_product("other")] == ["Voucher"]
    assert index.unattributed == 2  # A3 has no detail, one coupon is product-specific
    assert clause(index.for_product("p1")) == "đang có Flash sale đến 12/10"
    assert clause([]) is None


# --------------------------------------------------------------------------- LIVE / video


def test_appearances_join_sessions_and_videos_to_products() -> None:
    sessions = [{"id": "L1", "title": "LIVE tối", "start_time": str(_ts(date(2026, 9, 20)))}]
    live_products = {
        "L1": {
            "data": {
                "products": [
                    {
                        "id": "p1",
                        "traffic": {"product_impressions": 900},
                        "sales": {"sku_orders": 7},
                    }
                ]
            }
        }
    }
    videos = [
        {
            "id": "V1",
            "title": "Video review",
            "video_post_time": "2026-09-25T03:00:00Z",
            "products": [{"id": "p1"}, {"id": "p2"}],
        }
    ]
    video_products = {"V1": {"data": {"products": [{"id": "p1", "units_sold": 12}]}}}
    got = parse_appearances(sessions, live_products, videos, video_products)
    live, video = got["p1"]
    assert (live.kind, live.day, live.impressions, live.orders) == ("LIVE", "2026-09-20", 900, 7)
    assert (video.kind, video.day, video.impressions, video.orders) == (
        "Video",
        "2026-09-25",
        None,
        12,
    )
    assert got["p2"][0].orders is None


# --------------------------------------------------------------------------- report


def _dilute(snap: Path, product_id: str) -> None:
    """Make ``product_id`` look diluted: affiliate video quadruples at a lower CTR."""
    for name, impressions, ctr in (
        ("a34_30d_current", 4000, "0.03"),
        ("a34_30d_previous", 1000, "0.08"),
    ):
        data = json.loads((snap / f"{name}.json").read_text())
        for row in data["products"]:
            if row["id"] == product_id:
                row["affiliate_video_performance"] = _block(impressions, ctr)
        _write(snap / f"{name}.json", data)


def test_diluted_card_branch_card_is_withheld_and_watched(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    _dilute(snap, "weak")
    report = build_shop_report(snap)
    assert all(c.product_id != "weak" for c in report.cards)
    [row] = [w for w in report.watch if w.product_id == "weak"]
    assert row.reason == (
        "CTR giảm do lượt hiển thị tăng mạnh từ video affiliate, không phải do trang sản phẩm"
    )
    assert report.technical["traffic_diluted"] == ["weak"]
    [block] = [b for b in report.traffic if b.product_id == "weak"]
    assert (block.verdict, block.has_card) == (DILUTION, False)
    text = render_html(report)
    above = text.split(TECH_HEADING)[0]
    assert "Traffic đến từ đâu" in above
    assert "traffic loãng, chưa nên sửa trang sản phẩm" in above
    assert "Không có card cho sản phẩm này" in above


def test_pending_card_is_withheld_too(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=False)
    _dilute(snap, "weak")
    report = build_shop_report(snap)
    assert all(c.product_id != "weak" for c in report.cards)
    assert report.technical["traffic_diluted"] == ["weak"]


def test_uniform_drop_keeps_the_card_with_a_source_clause(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    for name, scale in (("a34_30d_current", 1), ("a34_30d_previous", 0)):
        data = json.loads((snap / f"{name}.json").read_text())
        for row in data["products"]:
            if row["id"] == "weak":
                # card and Shop Tab both lose CTR in the current window; affiliate video spikes
                ctr = "0.02" if scale else "0.04"
                for key, imp_key, clk_key in (
                    ("seller_product_card_performance", "product_impressions", "product_clicks"),
                    (
                        "shop_tab_performance",
                        "shop_tab_product_impressions",
                        "shop_tab_product_clicks",
                    ),
                ):
                    impressions = Decimal(row[key][imp_key])
                    row[key][clk_key] = str(impressions * Decimal(ctr))
                row["affiliate_video_performance"] = _block(40000 if scale else 1000, ctr)
        _write(snap / f"{name}.json", data)
    report = build_shop_report(snap)
    [card] = [c for c in report.cards if c.product_id == "weak"]
    assert card.status in (STATUS_RULE, STATUS_NOT_ASKED)
    assert card.reason.endswith("lượt hiển thị tăng chủ yếu từ video affiliate")
    assert len(card.reason) <= 170
    [block] = [b for b in report.traffic if b.product_id == "weak"]
    assert (block.verdict, block.has_card, block.top_impression_source) == (
        UNIFORM,
        True,
        "Video affiliate",
    )


def _with_orders(snap: Path, product_id: str, platform: int, total: int) -> None:
    day = date(2026, 9, 20)
    orders = [_order(day, (product_id, "4000" if i < platform else "0", "0")) for i in range(total)]
    _write(snap / "orders.json", {"orders": orders})


def test_platform_discount_share_reaches_card_reason_and_top_table(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    _with_orders(snap, "weak", platform=14, total=20)
    report = build_shop_report(snap)
    [card] = [c for c in report.cards if c.product_id == "weak"]
    assert "70 % đơn có giảm giá của sàn" in card.reason
    [block] = [b for b in report.traffic if b.product_id == "weak"]
    assert block.discounts.current.platform_share == Decimal("0.7")
    text = render_html(report)
    above = text.split(TECH_HEADING)[0]
    assert "Đơn có giảm giá của sàn" in above and "Đơn có giảm giá của shop" in above


def test_low_platform_share_stays_off_the_card(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    _with_orders(snap, "weak", platform=4, total=20)
    report = build_shop_report(snap)
    [card] = [c for c in report.cards if c.product_id == "weak"]
    assert "giảm giá của sàn" not in card.reason


def test_promotion_clause_and_fetch_status(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    promo = snap / "promotions"
    _write(
        promo / "activities.json",
        {
            "activities": [
                {
                    "id": "A1",
                    "title": "Flash 10.10",
                    "activity_type": "FLASHSALE",
                    "status": "ONGOING",
                    "begin_time": _ts(date(2026, 10, 1)),
                    "end_time": _ts(date(2026, 10, 12)),
                }
            ]
        },
    )
    _write(promo / "coupons.json", {"coupons": []})
    _write(promo / "activity_details.json", {"A1": {"products": [{"id": "weak"}]}})
    _write(promo / "_error.json", {"error_class": "TikTokAPIError", "message": "boom"})
    report = build_shop_report(snap)
    [card] = [c for c in report.cards if c.product_id == "weak"]
    assert "đang có Flash sale đến 12/10" in card.reason
    status = report.technical["promotions_status"]
    assert status["status"] == "error" and "TikTokAPIError" in status["detail"]


def test_missing_fetches_are_reported_as_skipped(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    report = build_shop_report(snap)
    t = report.technical
    assert [t[k]["status"] for k in ("promotions_status", "live_status", "videos_status")] == [
        "skipped"
    ] * 3
    text = render_html(report)
    above, below = text.split(TECH_HEADING)
    assert "chưa lấy được khuyến mãi của shop, LIVE, video" in above
    assert "Điểm mù 1" in below and "Điểm mù 2" in below
    assert "GMV Max" in below and "bỏ qua" in below


def test_live_and_video_appearances_render_when_fetched(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    _write(
        snap / "live" / "sessions.json",
        {
            "sessions": [
                {"id": "L1", "title": "LIVE tối", "start_time": str(_ts(date(2026, 9, 20)))}
            ]
        },
    )
    _write(
        snap / "live" / "products" / "L1.json",
        {
            "data": {
                "products": [
                    {
                        "id": "weak",
                        "traffic": {"product_impressions": 900},
                        "sales": {"sku_orders": 7},
                    }
                ]
            }
        },
    )
    report = build_shop_report(snap)
    [block] = [b for b in report.traffic if b.product_id == "weak"]
    assert [(a.kind, a.impressions, a.orders) for a in block.appearances] == [("LIVE", 900, 7)]
    assert report.technical["live_status"]["status"] == "ok"
    assert "LIVE tối" in render_html(report)


def test_new_user_copy_has_no_technical_terms(tmp_path: Path) -> None:
    snap, _ = _snapshot(tmp_path, with_diagnosis=True)
    _with_orders(snap, "weak", platform=14, total=20)
    report: ShopReport = build_shop_report(snap)
    above = render_html(report).split(TECH_HEADING)[0]
    visible = re.sub(r"<style>.*?</style>", "", above, flags=re.DOTALL)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert not re.search(
        r"_performance|platform_discount|seller_discount|/analytics|/promotion", visible
    )
    assert not re.search(r"\b(dilution|spike|endpoint|config)\b|ADR-", visible)


# --------------------------------------------------------------------------- live fetch (fakes)


def _load_script():
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "shop_optimization_report.py"
    spec = importlib.util.spec_from_file_location("shop_optimization_report_fetch", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakePromotion:
    def __init__(self, activities: list[dict], *, fail_on: str | None = None) -> None:
        self.activities = activities
        self.fail_on = fail_on
        self.detail_calls: list[str] = []
        self.statuses: list[str] = []

    def search_activities_all(self, *, status: str) -> list[dict]:
        self.statuses.append(status)
        if self.fail_on == "search":
            raise RuntimeError("boom access_token=abcdef0123456789 trailing")
        return self.activities if status == "ONGOING" else []

    def search_coupons_all(self) -> list[dict]:
        return [{"id": "c1"}]

    def get_activity(self, activity_id: str) -> dict:
        self.detail_calls.append(activity_id)
        return {"data": {"products": [{"id": "weak"}]}}


class _Res:
    def __init__(self, promotion: _FakePromotion) -> None:
        self.promotion = promotion


def _activity(i: int, **extra: object) -> dict:
    base = {"id": f"A{i}", "begin_time": _ts(date(2026, 9, 10)), "end_time": _ts(date(2026, 9, 20))}
    return {**base, **extra}


def test_fetch_promotions_saves_raw_and_caps_detail_calls(tmp_path: Path) -> None:
    script = _load_script()
    activities = [_activity(i) for i in range(script.MAX_ACTIVITY_DETAIL_CALLS + 10)]
    activities.append(_activity(999, products=[{"id": "x"}]))  # list already present
    activities.append(
        _activity(1000, begin_time=_ts(date(2026, 1, 1)), end_time=_ts(date(2026, 1, 2)))
    )
    fake = _FakePromotion(activities)
    script._fetch_promotions(_Res(fake), tmp_path, "2026-09-06", "2026-10-06", sleep_s=0)
    assert fake.statuses == ["ONGOING", "NOT_START", "EXPIRED"]
    assert len(fake.detail_calls) == script.MAX_ACTIVITY_DETAIL_CALLS
    assert "A999" not in fake.detail_calls and "A1000" not in fake.detail_calls
    folder = tmp_path / "promotions"
    assert len(json.loads((folder / "activities.json").read_text())["activities"]) == len(
        activities
    )
    assert json.loads((folder / "coupons.json").read_text()) == {"coupons": [{"id": "c1"}]}
    assert not (folder / "_error.json").exists()


def test_fetch_promotions_failure_writes_a_sanitised_error_and_continues(tmp_path: Path) -> None:
    script = _load_script()
    script._fetch_promotions(
        _Res(_FakePromotion([], fail_on="search")), tmp_path, "2026-09-06", "2026-10-06", sleep_s=0
    )
    error = json.loads((tmp_path / "promotions" / "_error.json").read_text())
    assert error["error_class"] == "RuntimeError"
    assert "abcdef0123456789" not in error["message"] and "[redacted]" in error["message"]
    assert not (tmp_path / "promotions" / "activities.json").exists()

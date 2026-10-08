"""Shop diagnosis report (ADR-108): channels, decomposition, heroes, promotions, page.

Every snapshot is synthetic (``tests/support/shop_diagnosis.py``); expectations
are derived from the fixture rows rather than restated as opaque literals.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from juli_backend.services.shop_diagnosis import (
    Ranking,
    ShopDiagnosisConfig,
    build_message,
    build_report,
    load_snapshot,
    render_html,
)
from juli_backend.services.shop_diagnosis.channels import (
    ADDITIVE,
    Channel,
    Counts,
    build_series,
    read_counts,
    window_sum,
)
from juli_backend.services.shop_diagnosis.confidence import (
    Confidence,
    rate_label,
    series_label,
)
from juli_backend.services.shop_diagnosis.decomposition import (
    CartSide,
    Factor,
    FactorChange,
    FunnelComparison,
    Verdict,
    contributions,
    decide,
)
from juli_backend.services.shop_diagnosis.heroes import DROPPED, ENTERED, select_heroes
from juli_backend.services.shop_diagnosis.promotions import (
    FlashFlag,
    VoucherClass,
    analyse_flash,
    classify_voucher,
    coverage_by_day,
    parse_activities,
    parse_vouchers,
    yardstick,
)
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows
from tests.support.shop_diagnosis import (
    END,
    Block,
    DayRow,
    TabBlock,
    a34_row,
    order,
    seconds,
    window_days,
    write_snapshot,
)

CONFIG = ShopDiagnosisConfig()
WINDOWS = Windows.ending(END, CONFIG.window_days)

KPI_LABELS = (
    "Lượt hiển thị sản phẩm",
    "CTR (Tỷ lệ nhấp)",
    "Lượt nhấp vào sản phẩm",
    "Tỷ lệ thêm vào giỏ hàng",
    "Số lượt thêm vào giỏ hàng",
    "Đơn hàng SKU",
    "CTOR",
    "AOV (SKU)",
    "GMV",
    "Hoàn tiền",
)
CHANNEL_NAMES = (
    "Thẻ sản phẩm của người bán",
    "Tab Cửa hàng",
    "Video của người bán",
    "LIVE của người bán",
    "Liên kết",
    "Video liên kết",
    "LIVE liên kết",
)


def _row(pid: str, day_index: int, scale: int = 1) -> DayRow:
    """A product-day whose counts vary by day, so sums are not a multiple of one day."""
    k = day_index % 5 + 1
    return DayRow(
        pid,
        card=Block(200 * scale + k, 10 * scale + k, 3 * scale, 2 * scale, 200_000 * scale + k),
        tab=TabBlock(100 * scale, 8 * scale, "0.1250", 90_000 * scale),
        seller_video=Block(30, 2, 0, 1, 150_000),
        seller_live=Block(50, 4, 1, 1, 180_000),
        affiliate_video=Block(400, 12, 2, 2, 400_000),
        affiliate_live=Block(20, 1, 0, 0, 0),
        refunds=10_000,
    )


# --------------------------------------------------------------------------
# channels: daily sums, Shop Tab mapping
# --------------------------------------------------------------------------


def test_daily_sums_equal_the_window_aggregate() -> None:
    """Summing 30 daily rows reproduces the 30-day aggregate TikTok returns (ADR-108 d.1)."""
    days = WINDOWS.last_days()
    daily = {d: [a34_row(_row("p1", i))] for i, d in enumerate(days)}
    rows = [_row("p1", i) for i in range(len(days))]
    aggregate = a34_row(
        DayRow(
            "p1",
            card=Block(
                sum(r.card.impressions for r in rows),
                sum(r.card.clicks for r in rows),
                sum(r.card.add_to_cart for r in rows),
                sum(r.card.orders for r in rows),
                sum(r.card.gmv for r in rows),
            ),
        )
    )
    aggregate["seller_product_card_performance"]["click_order_rate"] = str(
        sum(r.card.orders for r in rows) / sum(r.card.clicks for r in rows)
    )

    summed = window_sum(build_series(daily), Channel.PRODUCT_CARD, days)
    expected = read_counts(aggregate, Channel.PRODUCT_CARD)

    assert summed == expected
    assert summed.ctor == pytest.approx(
        float(aggregate["seller_product_card_performance"]["click_order_rate"])
    )
    # The decoy unique_* fields (7× the real counts) never leak into a sum.
    assert summed.impressions == sum(r.card.impressions for r in rows)


def test_shop_tab_reads_prefixed_keys_and_derives_orders() -> None:
    row = a34_row(_row("p1", 0))
    tab = read_counts(row, Channel.SHOP_TAB)

    assert (tab.impressions, tab.clicks, tab.gmv) == (100, 8, 90_000)
    assert tab.add_to_cart is None and tab.add_to_cart_rate is None
    assert tab.sku_orders == pytest.approx(0.125 * 8)
    assert tab.orders_estimated is True

    # Unprefixed keys in the Shop Tab block are not this channel's fields.
    row["shop_tab_performance"] = {"product_impressions": 999, "product_clicks": 99}
    assert read_counts(row, Channel.SHOP_TAB).impressions == 0


def test_four_additive_channels_partition_the_total_and_shop_tab_does_not() -> None:
    row = a34_row(_row("p1", 3))
    total = read_counts(row, Channel.TOTAL)
    parts = [read_counts(row, c) for c in ADDITIVE]

    assert Channel.SHOP_TAB not in ADDITIVE
    assert sum(p.gmv for p in parts) == total.gmv
    assert sum(p.impressions for p in parts) == total.impressions
    assert sum(p.sku_orders or 0 for p in parts) == total.sku_orders


# --------------------------------------------------------------------------
# decomposition and decision tree
# --------------------------------------------------------------------------


def _counts(impressions: float, ctr: float, ctor: float, aov: float) -> Counts:
    clicks = impressions * ctr
    orders = clicks * ctor
    return Counts(impressions, clicks, clicks * 0.1, orders, orders * aov)


@pytest.mark.parametrize(
    ("prior", "last"),
    [
        (_counts(1000, 0.04, 0.05, 200_000), _counts(1300, 0.035, 0.04, 210_000)),
        (_counts(1000, 0.04, 0.05, 200_000), _counts(800, 0.05, 0.05, 200_000)),
        (_counts(1000, 0.04, 0.05, 200_000), _counts(1000, 0.04, 0.05, 200_000)),
    ],
)
def test_contributions_sum_to_the_gmv_change(prior: Counts, last: Counts) -> None:
    split = contributions(prior, last)

    assert split is not None
    assert sum(split.values()) == pytest.approx(last.gmv - prior.gmv, abs=1e-6)
    impressions_up = last.impressions > prior.impressions
    assert (split[Factor.IMPRESSIONS] > 0) == impressions_up or split[Factor.IMPRESSIONS] == 0


def test_contributions_are_undefined_without_orders() -> None:
    assert contributions(_counts(1000, 0.04, 0.05, 1), Counts(1000, 40, 4, 0, 0)) is None


def _comparison(
    gmv: tuple[float, float],
    orders: float,
    factors: dict[Factor, tuple[float, Confidence]],
    cart: tuple[float, float] = (0.10, 0.10),
    per_cart: tuple[float, float] = (0.5, 0.5),
) -> FunnelComparison:
    """A comparison whose card funnel has the given add-to-cart and order-per-cart rates."""

    def counts(g: float, cart_rate: float, opa: float) -> Counts:
        clicks = 100.0
        carts = clicks * cart_rate
        return Counts(1000, clicks, carts, carts * opa, g)

    return FunnelComparison(
        counts(gmv[0], cart[0], per_cart[0]),
        counts(gmv[1], cart[1], per_cart[1]),
        orders,
        orders,
        tuple(
            FactorChange(f, 1.0, 1.0 + (contribution > 0), contribution, label)
            for f, (contribution, label) in factors.items()
        ),
        Confidence.CLEAR,
        Confidence.CLEAR,
        Confidence.CLEAR,
    )


CLEAR, REF = Confidence.CLEAR, Confidence.REFERENCE


def test_decision_tree_insufficient_and_stable() -> None:
    few = _comparison((100, 50), 20, {Factor.CTR: (-50, CLEAR)})
    flat = _comparison((100, 105), 80, {Factor.CTR: (5, CLEAR)})

    assert decide(few, few, CONFIG).verdict is Verdict.INSUFFICIENT
    assert decide(flat, flat, CONFIG).verdict is Verdict.STABLE


def test_decision_tree_falls_back_from_impressions_to_the_next_clear_factor() -> None:
    group = _comparison(
        (100, 60),
        80,
        {
            Factor.IMPRESSIONS: (-25, CLEAR),
            Factor.CTR: (-10, CLEAR),
            Factor.CTOR: (-4, REF),
            Factor.AOV: (-1, REF),
        },
    )
    conclusion = decide(group, group, CONFIG)

    assert (conclusion.verdict, conclusion.factor) == (Verdict.STORY, Factor.CTR)


def test_decision_tree_impressions_only() -> None:
    group = _comparison((100, 60), 80, {Factor.IMPRESSIONS: (-40, CLEAR), Factor.CTR: (0, REF)})
    assert decide(group, group, CONFIG).verdict is Verdict.IMPRESSIONS_ONLY


@pytest.mark.parametrize(
    ("cart", "per_cart", "side"),
    [
        ((0.10, 0.06), (0.5, 0.48), CartSide.BEFORE),
        ((0.10, 0.098), (0.5, 0.30), CartSide.AFTER),
    ],
)
def test_ctor_story_splits_before_and_after_cart(
    cart: tuple[float, float], per_cart: tuple[float, float], side: CartSide
) -> None:
    group = _comparison(
        (100, 60), 80, {Factor.CTOR: (-35, CLEAR), Factor.CTR: (-5, CLEAR)}, cart, per_cart
    )
    conclusion = decide(group, group, CONFIG)

    assert (conclusion.factor, conclusion.side) == (Factor.CTOR, side)
    assert side.value in conclusion.headline


def test_no_clear_factor_reads_unclear_with_the_largest_for_reference() -> None:
    group = _comparison((100, 60), 80, {Factor.CTOR: (-30, REF), Factor.AOV: (-10, REF)})
    conclusion = decide(group, group, CONFIG)

    assert conclusion.verdict is Verdict.UNCLEAR
    assert conclusion.factor is Factor.CTOR
    assert "Chưa rõ nguyên nhân" in conclusion.headline


# --------------------------------------------------------------------------
# confidence labels
# --------------------------------------------------------------------------


def test_rate_labels_follow_order_floors_and_the_interval() -> None:
    # 5 % → 2.5 % CTOR on 2,000 clicks a side: 100 vs 50 orders, interval excludes 0.
    assert rate_label(100, 2000, 50, 2000, 100, 50, CONFIG) is Confidence.CLEAR
    # Same volume, same rate: inside the noise band.
    assert rate_label(100, 2000, 101, 2000, 100, 101, CONFIG) is Confidence.REFERENCE
    assert rate_label(20, 400, 5, 400, 20, 15, CONFIG) is Confidence.REFERENCE
    assert rate_label(20, 400, 2, 400, 20, 5, CONFIG) is Confidence.INSUFFICIENT


def test_series_label_uses_the_daily_spread() -> None:
    steady = [100.0, 101.0, 99.0, 100.0] * 7
    shifted = [v + 50 for v in steady]
    noisy = [0.0, 200.0] * 14

    assert series_label(steady, shifted, 60, 60, CONFIG) is Confidence.CLEAR
    assert series_label(noisy, [v + 5 for v in noisy], 60, 60, CONFIG) is Confidence.REFERENCE


# --------------------------------------------------------------------------
# hero ranking
# --------------------------------------------------------------------------


def _hero_daily() -> dict[date, list[dict]]:
    """``fallen`` sells only in the prior 30 days; five others sell steadily."""
    out: dict[date, list[dict]] = {}
    prior = set(WINDOWS.prior_days())
    for i, day in enumerate(window_days()):
        rows = [
            a34_row(DayRow(f"steady{n}", card=Block(100, 10, 2, 1, 100_000 - n))) for n in range(5)
        ]
        if day in prior:
            rows.append(a34_row(DayRow("fallen", card=Block(100, 10, 2, 1, 400_000))))
        out[day] = rows
    return out


def test_ranking_modes_and_dropped_products() -> None:
    series = build_series(_hero_daily())

    combined = select_heroes(series, WINDOWS, Ranking.COMBINED_60D, CONFIG)
    recent = select_heroes(series, WINDOWS, Ranking.LAST_30D, CONFIG)

    # steady4 is in the last-30 top five but not the 60-day five.
    assert "fallen" in combined.heroes
    assert combined.movers == (("steady4", ENTERED),)
    assert "fallen" not in recent.heroes
    assert ("fallen", DROPPED) in recent.movers
    assert combined.dispersed is False


def test_dispersed_shop_warns_when_top_five_carry_under_half() -> None:
    daily = {
        day: [a34_row(DayRow(f"p{n}", card=Block(10, 1, 0, 1, 1000))) for n in range(20)]
        for day in window_days()
    }
    selection = select_heroes(build_series(daily), WINDOWS, Ranking.COMBINED_60D, CONFIG)

    assert selection.gmv_share == pytest.approx(5 / 20)
    assert selection.dispersed is True


def test_gift_listings_are_never_heroes() -> None:
    series = build_series(_hero_daily())
    selection = select_heroes(
        series,
        WINDOWS,
        Ranking.COMBINED_60D,
        CONFIG,
        lambda pid: "Quà tặng kèm" if pid == "fallen" else "Sản phẩm",
    )
    assert "fallen" not in selection.heroes


# --------------------------------------------------------------------------
# promotions
# --------------------------------------------------------------------------


def _single_orders(values: list[float]) -> list[dict]:
    day = WINDOWS.last_first + timedelta(days=3)
    return [order(f"o{i}", day, ["p1"], v) for i, v in enumerate(values)]


def test_voucher_classes_from_configuration() -> None:
    values = [float(v) for v in range(100_000, 200_001, 10_000)]  # 11 single-item orders
    stick = yardstick(_single_orders(values), WINDOWS, CONFIG)
    assert stick is not None and stick.common_price == 150_000
    assert stick.closing_cut == 125_000  # 75 % of single-item orders reach it

    def coupon(threshold: int | None, limit: int = 100, scope: str = "FULL_SHOP") -> dict:
        body: dict = {
            "id": f"c{threshold}{limit}{scope}",
            "status": "ONGOING",
            "claim_duration": {"start_time": seconds(WINDOWS.last_first)},
            "discount": {"reduction_amount": {"amount": "10000"}},
            "product_scope": scope,
            "usage_limits": {"redemption_limit": limit},
        }
        if threshold:
            body["threshold"] = {"min_spend": {"amount": str(threshold)}}
        return body

    vouchers = parse_vouchers(
        [
            coupon(None),
            coupon(120_000),
            coupon(200_000),
            coupon(270_000),
            coupon(200_001, limit=2),
            coupon(200_002, scope="SPECIFIC_PRODUCTS"),
        ]
    )
    classes = [classify_voucher(v, stick, CONFIG) for v in vouchers]

    assert classes == [
        (VoucherClass.CLOSING, False),
        (VoucherClass.CLOSING, False),
        (VoucherClass.RAISE_VALUE, False),
        (VoucherClass.MULTI_ITEM, False),
        (VoucherClass.PERSONAL, False),
        (VoucherClass.RAISE_VALUE, True),
    ]


def test_coverage_marks_a_flash_day_at_half_a_day() -> None:
    day = WINDOWS.last_first
    coverage = coverage_by_day(
        [(seconds(day, 0), seconds(day, 12)), (seconds(day, 6), seconds(day, 9))],
        [day, day + timedelta(days=1)],
    )
    assert coverage[day] == pytest.approx(0.5)
    assert coverage[day + timedelta(days=1)] == 0


def _flash_snapshot(flash_days: list[date]) -> tuple[list, Snapshot]:
    """A running 10 % discount plus all-day flash sales at 2 % below the discounted price."""
    list_price = 100_000
    activities = [
        {
            "id": "disc",
            "activity_type": "DIRECT_DISCOUNT",
            "status": "ONGOING",
            "begin_time": seconds(WINDOWS.prior_first),
            "end_time": seconds(END + timedelta(days=30)),
        }
    ]
    details = {
        "disc": {"products": [{"id": "p1", "skus": [{"id": "s1", "discount": "10"}]}]},
    }
    for i, day in enumerate(flash_days):
        activities.append(
            {
                "id": f"f{i}",
                "activity_type": "FLASHSALE",
                "status": "EXPIRED",
                "begin_time": seconds(day, 0),
                "end_time": seconds(day + timedelta(days=1)),
            }
        )
        details[f"f{i}"] = {
            "products": [
                {"id": "p1", "skus": [{"id": "s1", "activity_price": {"amount": "88200"}}]}
            ]
        }
    snapshot = Snapshot(
        "shop",
        END,
        {},
        products={
            "p1": {
                "title": "Sản phẩm",
                "skus": [{"id": "s1", "price": {"sale_price": str(list_price)}}],
            }
        },
    )
    return parse_activities(activities, details), snapshot


def test_flash_true_depth_coverage_and_flags() -> None:
    last = WINDOWS.last_days()
    flash_days = [d for i, d in enumerate(last) if i % 3 != 0]  # two days in three
    promotions, snapshot = _flash_snapshot(flash_days)
    pre = {d: Counts(100, 50, 20, 10, 1) for d in WINDOWS.prior_days()}
    flash = {d: Counts(100, 50, 20, 8, 1) for d in flash_days}
    non = {d: Counts(100, 50, 20, 4, 1) for d in last if d not in flash}

    analysis = analyse_flash(promotions, WINDOWS, snapshot, {**pre, **flash, **non}, CONFIG, "p1")

    assert analysis.true_depth == pytest.approx(1 - 88_200 / 90_000)
    assert analysis.list_depth == pytest.approx(1 - 88_200 / 100_000)
    assert analysis.flash_days_last == len(flash_days)
    assert analysis.coverage_last == pytest.approx(len(flash_days) / len(last))
    assert set(analysis.flags) == {FlashFlag.CONTINUOUS, FlashFlag.SHALLOW, FlashFlag.WAITING}
    pre_cell, flash_cell, non_cell = analysis.cells
    # The last window's first day precedes the first flash day, so it is pre-flash.
    non_flash_after_start = len(last) - len(flash_days) - 1
    assert (pre_cell.days, flash_cell.days, non_cell.days) == (
        len(WINDOWS.prior_days()) + 1,
        len(flash_days),
        non_flash_after_start,
    )
    assert non_cell.orders_per_cart == pytest.approx(4 / 20)


def test_flash_cells_below_floor_are_insufficient_and_raise_no_waiting_flag() -> None:
    last = WINDOWS.last_days()
    promotions, snapshot = _flash_snapshot(last[:2])
    by_day = {d: Counts(100, 50, 20, 1, 1) for d in WINDOWS.all_days()}

    analysis = analyse_flash(promotions, WINDOWS, snapshot, by_day, CONFIG, "p1")

    assert analysis.cells[1].sufficient is False
    assert FlashFlag.WAITING not in analysis.flags
    assert FlashFlag.CONTINUOUS not in analysis.flags


# --------------------------------------------------------------------------
# the whole report: page and message
# --------------------------------------------------------------------------


def _full_snapshot(folder: Path) -> Path:
    """Six products; ``p0``'s product-card CTOR halves in the last 30 days."""
    last = set(WINDOWS.last_days())
    daily: dict[date, list[DayRow]] = {}
    for i, day in enumerate(window_days()):
        rows = [_row(f"p{n}", i, scale=6 - n) for n in range(1, 6)]
        orders = 2 if day in last else 4
        rows.append(
            DayRow(
                "p0",
                card=Block(400, 40, 8, orders, orders * 200_000),
                tab=TabBlock(200, 10, "0.1000", 200_000),
                affiliate_video=Block(500, 20, 3, 2, 400_000),
            )
        )
        daily[day] = rows
    orders = [
        order(f"o{i}", d, ["p0"], 150_000 + 1_000 * (i % 7)) for i, d in enumerate(window_days())
    ]
    return write_snapshot(
        folder,
        daily,
        orders=orders,
        products={f"p{n}": {"title": f"Sản phẩm số {n}"} for n in range(6)},
        activities=[
            {
                "id": "f1",
                "activity_type": "FLASHSALE",
                "status": "EXPIRED",
                "title": "Flash cuối tuần",
                "begin_time": seconds(WINDOWS.last_first, 0),
                "end_time": seconds(WINDOWS.last_first + timedelta(days=3)),
            }
        ],
        coupons=[
            {
                "id": "c1",
                "title": "Giảm 15k",
                "status": "ONGOING",
                "claim_duration": {"start_time": seconds(WINDOWS.last_first)},
                "threshold": {"min_spend": {"amount": "200000"}},
                "discount": {"reduction_amount": {"amount": "15000"}},
                "product_scope": "FULL_SHOP",
            }
        ],
    )


@pytest.fixture
def report(tmp_path: Path):
    return build_report(load_snapshot(_full_snapshot(tmp_path / "snap")), Ranking.COMBINED_60D)


def test_report_finds_the_card_ctor_drop_on_the_hero(report) -> None:
    hero = next(p for p in report.profiles if p.product_id == "p0")
    card = next(r for r in hero.channels if r.channel is Channel.PRODUCT_CARD)

    assert card.comparison.prior.ctor == pytest.approx(4 / 40)
    assert card.comparison.last.ctor == pytest.approx(2 / 40)
    assert hero.conclusion.verdict is Verdict.STORY
    assert hero.conclusion.factor is Factor.CTOR
    assert any("CTOR giảm" in tag for tag in card.tags)


def test_step_one_shares_of_additive_channels_sum_to_one(report) -> None:
    shares = [r.share_of_change for r in report.channels if r.additive]
    assert sum(s for s in shares if s is not None) == pytest.approx(1.0)
    tab = next(r for r in report.channels if r.channel is Channel.SHOP_TAB)
    assert tab.comparison.last.gmv > 0 and tab.additive is False


def test_page_is_vietnamese_with_no_code_identifiers(report) -> None:
    html = render_html(report)

    for label in (*KPI_LABELS, *CHANNEL_NAMES):
        assert label in html, label
    assert "TikTok không cung cấp" in html
    assert "ước tính" in html
    assert re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", html) == []
    for forbidden in ("/api", ".json", "endpoint", "<script", "http://", "https://"):
        assert forbidden not in html.lower(), forbidden
    order = [
        html.index(f'id="{anchor}"')
        for anchor in ("buoc-1", "buoc-2", "buoc-3", "buoc-4", "chi-so-shop", "ghi-chu")
    ]
    assert order == sorted(order)


def test_message_uses_only_clear_numbers_or_marks_them(report) -> None:
    message = build_message(report)
    total_label = report.total.gmv_confidence
    line = next(x for x in message.splitlines() if "toàn shop" in x and "GMV" in x)

    if total_label is Confidence.CLEAR:
        assert "dấu hiệu" not in line.lower()
    else:
        assert line.lower().startswith("- dấu hiệu")
    for row in report.channels:
        if row.comparison.gmv_confidence is Confidence.INSUFFICIENT:
            assert f"kênh {row.channel}" not in message


def test_json_holds_every_section(report) -> None:
    data = report.to_dict()
    assert {"total", "channels", "profiles", "shop_flash", "vouchers", "timelines"} <= data.keys()
    assert data["ranking"] == "60d"
    assert math.isclose(data["total"]["last"]["gmv"], report.total.last.gmv)

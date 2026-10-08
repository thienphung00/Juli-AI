"""Shop diagnosis report (ADR-108): channels, decomposition, heroes, promotions, page.

Every snapshot is synthetic (``tests/support/shop_diagnosis.py``); expectations
are derived from the fixture rows rather than restated as opaque literals.
"""

from __future__ import annotations

import dataclasses
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from juli_backend.services.optimize_product.live_video import Appearance
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
    FlashAnalysis,
    FlashFlag,
    VoucherClass,
    analyse_flash,
    analyse_vouchers,
    classify_voucher,
    coverage_by_day,
    parse_activities,
    parse_vouchers,
    yardstick,
)
from juli_backend.services.shop_diagnosis.render import _flash_section
from juli_backend.services.shop_diagnosis.report import Appearances
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


# --------------------------------------------------------------------------
# fixes after the first real run
# --------------------------------------------------------------------------

SCOPE = "Ở nhóm khách tự tìm đến (Thẻ sản phẩm và Tab Cửa hàng)"


def test_conclusion_headlines_name_the_self_search_scope() -> None:
    story = _comparison((100, 60), 80, {Factor.CTR: (-40, CLEAR)})
    unclear = _comparison((100, 60), 80, {Factor.CTOR: (-30, REF)})
    flat = _comparison((100, 105), 80, {Factor.CTR: (5, CLEAR)})

    headlines = [decide(c, c, CONFIG).headline for c in (story, unclear, flat)]

    assert headlines[0].startswith(f"{SCOPE}: GMV giảm 40 %")
    assert all(h.startswith(f"{SCOPE}: ") for h in headlines)


def test_rest_conclusion_and_message_line_name_the_scope(report) -> None:
    rest = report.rest_conclusion
    if rest.verdict is not Verdict.INSUFFICIENT:
        assert rest.headline.startswith(SCOPE)
    for profile in report.profiles:
        if profile.conclusion.verdict is not Verdict.INSUFFICIENT:
            assert profile.conclusion.headline.startswith(SCOPE)
    # A hint-qualified story keeps the scope in the message line.
    story = dataclasses.replace(
        report.profiles[0].conclusion, verdict=Verdict.STABLE, headline=f"{SCOPE}: GMV đổi +2 %"
    )
    profiles = (dataclasses.replace(report.profiles[0], conclusion=story),)
    message = build_message(dataclasses.replace(report, profiles=profiles))
    assert f"{SCOPE}: GMV đổi +2 %" in message


def _factor(kind: Factor, prior: float, last: float, label: Confidence) -> FactorChange:
    return FactorChange(kind, prior, last, None, label)


def test_message_calls_a_change_inside_the_noise_band_unchanged(report) -> None:
    total = dataclasses.replace(
        report.total,
        factors=(
            _factor(Factor.CTOR, 0.0500, 0.0504, REF),  # +0.8 %, Tham khảo
            _factor(Factor.CTR, 0.0400, 0.0300, REF),  # -25 %, Tham khảo
            _factor(Factor.AOV, 100_000, 100_100, CLEAR),  # Rõ keeps its direction
            _factor(Factor.IMPRESSIONS, 1000, 1100, REF),
        ),
    )
    message = build_message(dataclasses.replace(report, total=total))
    line = next(x for x in message.splitlines() if x.startswith("- Theo phễu"))

    assert "dấu hiệu CTOR gần như không đổi" in line
    assert "dấu hiệu CTR (Tỷ lệ nhấp) giảm" in line
    assert "AOV (SKU) tăng" in line and "dấu hiệu AOV" not in line
    assert "dấu hiệu CTOR tăng" not in line


def test_flash_summary_names_each_window_in_words() -> None:
    html = render_flash_section(_flash_analysis(true_depth=0.02))

    assert "(30 ngày trước: 0 ngày flash; 30 ngày gần đây: 21 ngày flash)" in html
    assert "0 và 21" not in html


def test_negative_true_depth_is_stated_and_still_flagged_shallow() -> None:
    html = render_flash_section(_flash_analysis(true_depth=-0.011))

    assert "giá flash cao hơn giá đang giảm sẵn 1,1 %" in html
    assert "-1,1 %" not in html
    assert FlashFlag.SHALLOW.value in html


def test_vouchers_read_the_total_claim_limit_and_cap_usage() -> None:
    values = [float(v) for v in range(100_000, 200_001, 10_000)]
    orders = [
        order(f"v{i}", d, ["p1"], value)
        for i, (d, value) in enumerate(zip(WINDOWS.last_days() * 3, values * 3, strict=False))
    ]
    orders += [order(f"w{i}", WINDOWS.last_days()[i % 30], ["p1"], 150_000) for i in range(40)]

    def coupon(coupon_id: str, limits: dict) -> dict:
        return {
            "id": coupon_id,
            "title": "Đền bù",
            "status": "ONGOING",
            "claim_duration": {"start_time": seconds(WINDOWS.last_first)},
            "discount": {"reduction_amount": {"amount": "50000"}},
            "product_scope": "FULL_SHOP",
            "usage_limits": limits,
        }

    vouchers = parse_vouchers(
        [
            coupon("a", {"single_buyer_claim_limit": 1, "total_claim_limit": 1}),
            coupon("b", {"redemption_limit": 2, "display_type": "CHAT"}),
            coupon("c", {"total_claim_limit": 5, "single_buyer_claim_limit": 1}),
            coupon("d", {"single_buyer_claim_limit": 1}),
        ]
    )
    summary = analyse_vouchers(vouchers, orders, WINDOWS, set(), CONFIG)
    by_id = {a.voucher.coupon_id: a for a in summary.live}

    assert by_id["a"].voucher_class is VoucherClass.PERSONAL
    assert by_id["b"].voucher_class is VoucherClass.PERSONAL
    assert by_id["c"].voucher_class is not VoucherClass.PERSONAL
    assert by_id["d"].voucher_class is not VoucherClass.PERSONAL
    assert by_id["a"].redemptions_upper == 1 and by_id["a"].cost_upper == 50_000
    assert by_id["b"].redemptions_upper == 2
    assert by_id["c"].redemptions_upper == 5
    assert by_id["d"].redemptions_upper > 5


def test_profile_tables_use_slash_dates_and_the_lifetime_label(report) -> None:
    video = Appearance("video", "Video thử", "2025-11-03", 10, 7)
    live = Appearance("live", "LIVE thử", "2026-10-02", 10, 3)
    appearances = Appearances((live,), 0, (video,), 0)
    profile = dataclasses.replace(report.profiles[0], appearances=appearances)
    html = render_html(dataclasses.replace(report, profiles=(profile,)))

    assert "Số món bán (từ khi đăng)" in html
    assert "<th>Số món bán</th>" not in html
    assert "03/11/2025" in html and "2025-11-03" not in html
    assert "02/10/2026" in html and "2026-10-02" not in html


def _flash_analysis(true_depth: float) -> FlashAnalysis:
    return FlashAnalysis(
        coverage={},
        weekly=(),
        coverage_last=0.68,
        coverage_prior=0.0,
        flash_days_last=21,
        flash_days_prior=0,
        true_depth=true_depth,
        list_depth=0.05,
        cells=(),
        flags=(FlashFlag.SHALLOW,),
        unattributed=0,
    )


def render_flash_section(flash: FlashAnalysis) -> str:
    return _flash_section(flash, [], False)

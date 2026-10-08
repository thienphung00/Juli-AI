"""Metric rankings (ADR-109 d.4–5, fast track AC-8.1): the pure computation.

Synthetic snapshots only (``tests/support/shop_diagnosis.py`` row shapes). The
core property is reconciliation: in every stream × metric table the listed rows
plus the three closing rows add up to the stream's own factor GMV, including
when a product or a whole stream has a zero side.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from juli_backend.services.shop_diagnosis import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.channels import Channel, Counts
from juli_backend.services.shop_diagnosis.decomposition import log_share, sequential_share
from juli_backend.services.shop_diagnosis.rankings import (
    STREAM_METRICS,
    Metric,
    VideoWindowMetrics,
    build_rankings,
    metric_values,
    reconciles,
    split,
)
from juli_backend.services.shop_diagnosis.snapshot import Snapshot
from tests.support.shop_diagnosis import END, Block, DayRow, TabBlock, a34_row, seconds, window_days

DAYS = window_days(END)
PRIOR, LAST = DAYS[:30], DAYS[30:]


def _card(day: date, prior: Block, last: Block) -> Block:
    return prior if day in PRIOR else last


def _catalogue(day: date, *, tab_prior: bool = True) -> list[DayRow]:
    """Five products with distinct stories; a little day-to-day wobble for the intervals."""
    w = day.toordinal() % 3  # 0, 1, 2
    tab = TabBlock(60 + w, 6, "0.2", 40_000) if (tab_prior or day in LAST) else TabBlock()
    return [
        # Falls: fewer clicks per impression and fewer orders per click.
        DayRow(
            "big",
            card=_card(
                day,
                Block(1_000 + 10 * w, 60, 12, 6, 600_000),
                Block(900 + 10 * w, 40, 8, 3, 300_000),
            ),
            tab=tab,
            seller_live=_card(day, Block(500, 25, 5, 2, 200_000), Block(700, 42, 8, 4, 400_000)),
        ),
        # New in the last window: a zero prior side.
        DayRow(
            "new",
            card=_card(day, Block(), Block(400 + w, 20, 4, 2, 180_000)),
        ),
        # Gone in the last window: a zero last side.
        DayRow(
            "gone",
            card=_card(day, Block(300 + w, 15, 3, 1, 90_000), Block()),
        ),
        # Too small for any list.
        DayRow("tiny", card=Block(20, 0, 0, 0, 0)),
        # Orders without an add-to-cart (buy now): CTOR cannot split into its steps.
        DayRow(
            "buynow",
            card=_card(day, Block(200, 10, 2, 1, 50_000), Block(200 + w, 10, 0, 1, 55_000)),
        ),
    ]


SESSIONS = [
    {  # last window, strong CTOR
        "id": "live-1",
        "title": "Sale tối",
        "start_time": str(seconds(LAST[5], 20)),
        "interaction_performance": {"product_impressions": 9_000, "product_clicks": 600},
        "sales_performance": {"sku_orders": 90, "gmv": {"amount": "9000000"}},
    },
    {  # last window, weak CTR
        "id": "live-2",
        "title": "Sáng",
        "start_time": str(seconds(LAST[20], 9)),
        "interaction_performance": {"product_impressions": 6_000, "product_clicks": 120},
        "sales_performance": {"sku_orders": 5, "gmv": {"amount": "500000"}},
    },
    {  # prior window: only sets the per-session impressions baseline
        "id": "live-0",
        "title": "Cũ",
        "start_time": str(seconds(PRIOR[3], 20)),
        "interaction_performance": {"product_impressions": 4_000, "product_clicks": 200},
        "sales_performance": {"sku_orders": 10, "gmv": {"amount": "1000000"}},
    },
]


def _snapshot(**kwargs) -> Snapshot:
    tab_prior = kwargs.pop("tab_prior", True)
    daily = {d: [a34_row(r) for r in _catalogue(d, tab_prior=tab_prior)] for d in DAYS}
    return Snapshot(
        shop_name="Shop Thử",
        end=END,
        daily=daily,
        live_sessions=SESSIONS,
        products={"big": {"title": "Nước kiềm 24 chai"}},
        **kwargs,
    )


def _by_key(rankings) -> dict[tuple[str, str], dict]:
    return {(r.stream.value, r.metric.value): r.payload for r in rankings}


def _all_rows(payload: dict) -> list[dict]:
    return [*payload["down"], *payload["up"]]


# ---------------------------------------------------------------------------
# The split itself
# ---------------------------------------------------------------------------


def test_sequential_substitution_telescopes_to_the_change_even_at_zero() -> None:
    before, after = [0.0, 0.05, 0.1, 90_000.0], [400.0, 0.05, 0.1, 90_000.0]
    shares = sequential_share(before, after)
    assert sum(shares) == pytest.approx(math.prod(after) - math.prod(before))
    assert shares[0] == pytest.approx(math.prod(after))  # all of it is impressions
    assert shares[1:] == [0.0, 0.0, 0.0]


def test_log_share_matches_the_report_contributions_and_sums_exactly() -> None:
    before, after = [1_000.0, 0.06, 0.1, 100_000.0], [900.0, 0.044, 0.075, 100_000.0]
    shares = log_share(before, after)
    assert shares is not None
    assert sum(shares) == pytest.approx(math.prod(after) - math.prod(before))
    assert shares[3] == pytest.approx(0.0)
    assert log_share([0.0, 1.0], [1.0, 1.0]) is None


def test_a_missing_prior_rate_takes_the_streams_prior_median() -> None:
    new = Counts(impressions=400, clicks=20, add_to_cart=4, sku_orders=2, gmv=180_000)
    before, after = metric_values(Counts()), metric_values(new)
    medians = {Metric.CTR: 0.04, Metric.CTOR: 0.08, Metric.AOV: 95_000.0}
    chain = (Metric.IMPRESSIONS, Metric.CTR, Metric.CTOR, Metric.AOV)
    shares, method = split(chain, before, after, medians)
    assert method == "sequential"
    assert sum(shares.values()) == pytest.approx(new.gmv)
    assert shares[Metric.IMPRESSIONS] == pytest.approx(400 * 0.04 * 0.08 * 95_000)
    assert shares[Metric.CTR] == pytest.approx(400 * (0.05 - 0.04) * 0.08 * 95_000)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_every_table_reconciles_to_its_stream_factor() -> None:
    rankings = build_rankings(_snapshot())
    assert {(r.stream, r.metric) for r in rankings} == {
        (s, m) for s, ms in STREAM_METRICS.items() if s is not Channel.SELLER_VIDEO for m in ms
    }
    for r in rankings:
        assert reconciles(r.payload), (r.stream, r.metric)


def test_product_card_factors_sum_to_the_streams_gmv_change() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    four = [
        tables[("product_card", m)]["stream_factor_gmv"]
        for m in ("impressions", "ctr", "ctor", "aov")
    ]
    card = tables[("product_card", "ctr")]
    assert sum(four) == pytest.approx(card["stream_gmv_change"])
    steps = [
        tables[("product_card", m)]["stream_factor_gmv"]
        for m in ("add_to_cart_rate", "orders_per_cart")
    ]
    assert sum(steps) == pytest.approx(tables[("product_card", "ctor")]["stream_factor_gmv"])


def test_a_new_product_is_split_sequentially_and_ranked_up_on_impressions() -> None:
    unfolded = ShopDiagnosisConfig(ranking_fold_share=0.0)
    tables = _by_key(build_rankings(_snapshot(), config=unfolded))
    impressions = tables[("product_card", "impressions")]
    new = next(r for r in impressions["up"] if r["id"] == "new")
    assert new["method"] == "sequential"
    assert new["quantity_prior"] == 0
    assert new["prior"] == 0
    # Its four factors together are its whole last-window GMV/day (prior rates = medians).
    # (A zero factor is not listed: here its AOV equals the median prior AOV.)
    total = sum(
        next(
            (r["gmv_per_day"] for r in _all_rows(tables[("product_card", m)]) if r["id"] == "new"),
            0.0,
        )
        for m in ("impressions", "ctr", "ctor", "aov")
    )
    assert total == pytest.approx(180_000)
    gone = next(r for r in impressions["down"] if r["id"] == "gone")
    assert gone["gmv_per_day"] == pytest.approx(-90_000)


def test_a_stream_with_a_zero_prior_side_still_reconciles() -> None:
    tables = _by_key(build_rankings(_snapshot(tab_prior=False)))
    for metric in STREAM_METRICS[Channel.SHOP_TAB]:
        payload = tables[("shop_tab", metric.value)]
        assert payload["method"] == "sequential"
        assert payload["orders_estimated"] is True
        assert reconciles(payload)
    assert tables[("shop_tab", "impressions")]["stream_factor_gmv"] == pytest.approx(
        tables[("shop_tab", "impressions")]["stream_gmv_change"]
    )


def test_ctor_rows_carry_their_two_steps_and_buy_now_stays_in_the_mix() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    big = next(r for r in _all_rows(tables[("product_card", "ctor")]) if r["id"] == "big")
    assert sum(big["steps"].values()) == pytest.approx(big["gmv_per_day"])
    for metric in ("add_to_cart_rate", "orders_per_cart"):
        payload = tables[("product_card", metric)]
        assert all(r["id"] != "buynow" for r in _all_rows(payload))
        assert reconciles(payload)
    assert "add_to_cart_rate" not in {m.value for m in STREAM_METRICS[Channel.SHOP_TAB]}


# ---------------------------------------------------------------------------
# Confidence, floors, order, folding
# ---------------------------------------------------------------------------


def test_impressions_use_the_1000_floor_and_small_rows_close_as_few() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    payload = tables[("product_card", "impressions")]
    listed = {r["id"] for r in _all_rows(payload)}
    assert "tiny" not in listed  # 600 impressions per window, both sides
    few = payload["closing"]["few"]
    assert few["count"] >= 1 and few["label"].endswith("sản phẩm ít lượt hiển thị")
    for row in _all_rows(payload):
        assert max(row["quantity_prior"], row["quantity_last"]) >= 1_000
    ctr = tables[("product_card", "ctr")]
    assert "tiny" not in {r["id"] for r in _all_rows(ctr)}  # under 10 clicks both sides
    assert ctr["closing"]["few"]["label"].endswith("ít lượt bấm")
    assert tables[("product_card", "ctor")]["closing"]["few"]["label"].endswith("ít đơn")


def test_rows_are_rõ_first_then_tham_khảo_each_by_size() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    for payload in tables.values():
        for side in ("down", "up"):
            rows = payload[side]
            labels = [r["confidence"] for r in rows]
            assert labels == sorted(labels, key=lambda c: c != "Rõ")
            for label in ("Rõ", "Tham khảo"):
                sizes = [abs(r["gmv_per_day"]) for r in rows if r["confidence"] == label]
                assert sizes == sorted(sizes, reverse=True)
            assert all(r["gmv_per_day"] < 0 for r in payload["down"])
            assert all(r["gmv_per_day"] > 0 for r in payload["up"])


def test_a_clear_row_needs_30_on_each_side_and_a_real_difference() -> None:
    tables = _by_key(
        build_rankings(_snapshot(), config=ShopDiagnosisConfig(ranking_fold_share=0.0))
    )
    big = next(r for r in tables[("product_card", "ctr")]["down"] if r["id"] == "big")
    assert big["confidence"] == "Rõ"  # 1,800 → 1,200 clicks, CTR 6 % → 4.4 %
    new = next(r for r in _all_rows(tables[("product_card", "ctr")]) if r["id"] == "new")
    assert new["confidence"] == "Tham khảo"  # 0 clicks before


def test_at_most_ten_rows_per_side_and_small_rows_fold_into_others() -> None:
    def rows(day: date) -> list[DayRow]:
        prior = day in PRIOR
        return [
            DayRow(f"p{n}", card=Block(2_000, 100 if prior else 100 - 3 * n, 20, 10, 1_000_000))
            for n in range(1, 16)
        ] + [DayRow("speck", card=Block(2_000, 100 if prior else 99, 20, 10, 1_000_000))]

    snapshot = Snapshot("x", END, {d: [a34_row(r) for r in rows(d)] for d in DAYS})
    payload = _by_key(build_rankings(snapshot))[("product_card", "ctr")]
    assert len(payload["down"]) == 10
    assert "speck" not in {r["id"] for r in payload["down"]}
    assert payload["closing"]["others"]["count"] == 6  # 5 beyond the top 10 + the speck
    assert reconciles(payload)


# ---------------------------------------------------------------------------
# Content rows
# ---------------------------------------------------------------------------


def test_live_sessions_are_measured_against_the_streams_prior_rates() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    ctor = tables[("seller_live", "ctor")]
    # Stream prior (A-34 LIVE block): 25 clicks, 2 orders, 200,000 ₫ per day.
    ctor0, aov0, ctr0 = 2 / 25, 100_000, 25 / 500
    live1 = next(r for r in ctor["up"] if r["id"] == "live-1")
    assert live1["gmv_per_day"] == pytest.approx(600 / 30 * (90 / 600 - ctor0) * aov0)
    assert live1["prior"] == pytest.approx(ctor0)
    assert live1["name"] == f"Sale tối · {LAST[5].strftime('%d/%m/%Y')}"
    assert live1["date"] == LAST[5].isoformat()
    ctr = tables[("seller_live", "ctr")]
    live2 = next(r for r in ctr["down"] if r["id"] == "live-2")
    assert live2["gmv_per_day"] == pytest.approx(6_000 / 30 * (120 / 6_000 - ctr0) * ctor0 * aov0)
    # The prior-window session is the impressions baseline, never a row.
    impressions = tables[("seller_live", "impressions")]
    assert all(r["id"] != "live-0" for t in tables.values() for r in _all_rows(t))
    live1_imp = next(r for r in _all_rows(impressions) if r["id"] == "live-1")
    assert live1_imp["gmv_per_day"] == pytest.approx((9_000 - 4_000) / 30 * ctr0 * ctor0 * aov0)
    for payload in (ctor, ctr, impressions):
        assert payload["row_kind"] == "live_session"
        assert reconciles(payload)


def test_videos_are_ranked_only_when_their_window_metrics_are_given() -> None:
    assert not any(r.stream is Channel.SELLER_VIDEO for r in build_rankings(_snapshot()))
    videos = [
        VideoWindowMetrics("v1", "Mở hộp", LAST[2], Counts(5_000, 250, None, 20, 2_000_000)),
        VideoWindowMetrics(
            "v2",
            "Cũ",
            PRIOR[1],
            Counts(1_500, 15, None, 1, 100_000),
            prior=Counts(3_000, 90, None, 6, 600_000),
        ),
    ]
    tables = _by_key(build_rankings(_snapshot(), videos=videos))
    assert {m for (s, m) in tables if s == "seller_video"} == {"impressions", "ctr"}
    for metric in ("impressions", "ctr"):
        payload = tables[("seller_video", metric)]
        assert payload["stream_label"] == "Video của người bán"
        assert payload["row_kind"] == "video"
        assert reconciles(payload)


def test_labels_are_tiktoks_own_words() -> None:
    tables = _by_key(build_rankings(_snapshot()))
    assert tables[("product_card", "impressions")]["metric_label"] == "Lượt hiển thị sản phẩm"
    assert tables[("product_card", "ctr")]["metric_label"] == "CTR"
    assert tables[("shop_tab", "aov")]["metric_label"] == "AOV"
    assert tables[("shop_tab", "ctor")]["stream_label"] == "Tab Cửa hàng"
    assert tables[("product_card", "ctor")]["stream_label"] == "Thẻ sản phẩm của người bán"
    assert tables[("seller_live", "ctor")]["stream_label"] == "LIVE của người bán"
    big = next(r for r in _all_rows(tables[("product_card", "ctr")]) if r["id"] == "big")
    assert big["name"] == "Nước kiềm 24 chai"


def test_a_snapshot_missing_a_window_is_refused() -> None:
    daily = {d: [a34_row(r) for r in _catalogue(d)] for d in LAST}
    with pytest.raises(ValueError, match="both 30-day windows"):
        build_rankings(Snapshot("x", END, daily))


def test_the_thresholds_come_from_the_config() -> None:
    config = ShopDiagnosisConfig(ranking_impressions_floor=10, ranking_max_rows=1)
    tables = _by_key(build_rankings(_snapshot(), config=config))
    payload = tables[("product_card", "impressions")]
    assert len(payload["down"]) <= 1 and len(payload["up"]) <= 1
    assert payload["closing"]["few"]["count"] == 0  # "tiny" has 600 ≥ 10 impressions
    assert reconciles(payload)
    assert timedelta(days=29) == date.fromisoformat(
        payload["windows"]["last"][1]
    ) - date.fromisoformat(payload["windows"]["last"][0])

"""P16 "Mô phỏng" math (D25.10, D25.11): baseline, trend, bands, locked cells, GMV."""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

import pytest

from juli_backend.services.ops import simulation as sim

END = date(2026, 10, 9)


def _report(days: int, *, end: date = END, imp=lambda i: 1000.0, products=None) -> dict:
    streams = {}
    for stream in sim.STREAMS:
        streams[stream] = {
            (end - timedelta(days=i)).isoformat(): [
                imp(i),
                imp(i) * 0.05,
                imp(i) * 0.005,
                imp(i) * 0.005 * 150_000,
            ]
            for i in range(days)
        }
    return {
        "daily_streams": streams,
        "daily_products": products or {},
        "titles": {},
        "seller_skus": {},
    }


def test_window_kpis_are_ratio_of_sums_and_daily_means():
    days = [sim.DayCounts(1000, 50, 5, 750_000), sim.DayCounts(3000, 90, 9, 1_350_000)]
    k = sim.window_kpis(days)
    assert k["impressions"] == 2000
    assert k["ctr"] == pytest.approx(140 / 4000)
    assert k["ctor"] == pytest.approx(14 / 140)
    assert k["aov"] == pytest.approx(2_100_000 / 14)
    assert k["gmv"] == pytest.approx(1_050_000)


def test_band_p10_p90_and_cv():
    b = sim.band([10, 10, 10, 10, 10, 10, 10, 10, 10, 20])
    assert b is not None
    assert b.p10 == pytest.approx(10)
    assert b.p90 == pytest.approx(11)
    assert b.mean == pytest.approx(11)
    assert b.band_pct == pytest.approx(1 / 11 * 100)
    assert b.cv == pytest.approx(3 / 11)
    assert sim.band([]) is None
    assert sim.band([0, 0]).band_pct is None


def test_stability_thresholds():
    assert sim.stability(0.1) == "stable"
    assert sim.stability(0.2) == "medium"
    assert sim.stability(0.5) == "volatile"
    assert sim.stability(None) == "unknown"


def test_simulate_gmv_is_product_of_four_kpis():
    base = {s: {"impressions": 1000, "ctr": 0.05, "ctor": 0.1, "aov": 100_000} for s in sim.STREAMS}
    out = sim.simulate(base, {"product_card": {"ctor": 10}})
    card = out["streams"]["product_card"]
    assert card["gmv_base"] == pytest.approx(500_000)
    assert card["gmv_new"] == pytest.approx(550_000)
    assert out["total_base"] == pytest.approx(2_000_000)
    assert out["delta_per_day"] == pytest.approx(50_000)
    assert out["delta_per_month"] == pytest.approx(1_500_000)
    assert out["delta_pct"] == pytest.approx(2.5)


@pytest.mark.parametrize(("stream", "kpi"), sorted(sim.LOCKED))
def test_locked_cells_refuse_a_change(stream, kpi):
    with pytest.raises(sim.SimulationError, match="locked"):
        sim.validate_deltas({stream: {kpi: 5}})


def test_locked_cells_are_exactly_video_ctor_aov_and_live_aov():
    assert sim.LOCKED == {("seller_video", "ctor"), ("seller_video", "aov"), ("seller_live", "aov")}


@pytest.mark.parametrize(
    "deltas",
    [
        {"nope": {"ctr": 5}},
        {"product_card": {"gmv": 5}},
        {"product_card": {"ctr": 3}},
        {"product_card": {"ctr": 1000}},
    ],
)
def test_invalid_deltas(deltas):
    with pytest.raises(sim.SimulationError):
        sim.validate_deltas(deltas)


def test_actions_follow_the_lever_map():
    acts = sim.actions_for({"product_card": {"ctr": 5}, "seller_video": {"impressions": -5}})
    assert [a["actions"] for a in acts] == ["ảnh bìa, tiêu đề", "đăng đều, GMV Max video"]


def test_baseline_window_and_trend_on_fixture():
    # impressions grow 1 % per day backwards → last 7 days lower than prior 7.
    history = sim.merge_reports([_report(60, imp=lambda i: 1000.0 + 10 * i)])
    payload = sim.baseline(history, 7)
    assert payload["status"]["baseline_available"] and payload["status"]["comparable"]
    card = next(s for s in payload["streams"] if s["stream"] == "product_card")
    imp = card["cells"][0]
    assert imp["value"] == pytest.approx(1030.0)  # mean of 1000..1060
    assert imp["trend_pct"] == pytest.approx((1030 - 1100) / 1100 * 100)
    # D28.1: the daily p10–p90 moved to daily_band; band is that of the window mean.
    assert imp["daily_band"]["p10"] == pytest.approx(1006.0)
    assert imp["daily_band"]["p90"] == pytest.approx(1054.0)
    daily = [1000.0 + 10 * i for i in range(7)]
    half = 1.2816 * statistics.stdev(daily) / math.sqrt(7)
    assert imp["band"]["band_pct"] == pytest.approx(half / 1030 * 100)
    assert imp["band"]["p10"] == pytest.approx(1030 - half)
    assert imp["indirect"] is True
    video = next(s for s in payload["streams"] if s["stream"] == "seller_video")
    assert [c["locked"] for c in video["cells"]] == [False, False, True, True]


def test_windows_needing_more_history_are_reported_not_invented():
    history = sim.merge_reports([_report(60)])
    windows = {w["days"]: w for w in sim.baseline(history, 30)["windows"]}
    assert windows[30]["comparable"] is True
    assert windows[90]["baseline_available"] is False
    assert windows[90]["needs_days"] == 180
    payload90 = sim.baseline(history, 90)
    assert payload90["streams"] == []
    assert payload90["status"]["history_days"] == 60


def test_newer_report_wins_and_history_extends():
    older = _report(60, end=END - timedelta(days=30), imp=lambda i: 500.0)
    newer = _report(60, imp=lambda i: 1000.0)
    history = sim.merge_reports([older, newer])
    assert history.days_available == 90
    assert history.streams["product_card"][END - timedelta(days=40)].impressions == 1000.0


def test_volatility_rows_sorted_stable_first():
    def rows(scale):
        return {
            (END - timedelta(days=i)).isoformat(): [100 + scale * (i % 2), 5, 1, 100_000]
            for i in range(30)
        }

    report = _report(30, products={"product_card": {"steady": rows(1), "jumpy": rows(80)}})
    payload = sim.baseline(sim.merge_reports([report]), 30)
    names = [r["id"] for r in payload["volatility"]["product_card"]["rows"]]
    assert names == ["steady", "jumpy"]
    assert payload["volatility"]["product_card"]["rows"][0]["stability"] == "stable"


def test_unknown_window_is_refused():
    with pytest.raises(sim.SimulationError):
        sim.baseline(sim.merge_reports([]), 60)


# -- D28: band of the window mean, low-data cells -------------------------------


def _cell(payload: dict, stream: str, kpi: str) -> dict:
    row = next(s for s in payload["streams"] if s["stream"] == stream)
    return next(c for c in row["cells"] if c["kpi"] == kpi)


def test_window_band_shrinks_with_sqrt_of_days():
    # Alternating 800 / 1200 impressions: the daily spread is the same in 7 and 30 days.
    history = sim.merge_reports([_report(60, imp=lambda i: 800.0 if i % 2 else 1200.0)])
    b7 = _cell(sim.baseline(history, 7), "product_card", "impressions")
    b30 = _cell(sim.baseline(history, 30), "product_card", "impressions")
    for b, n in ((b7, 7), (b30, 30)):
        daily = [800.0 if i % 2 else 1200.0 for i in range(n)]
        expected = 1.2816 * statistics.stdev(daily) / math.sqrt(n) / statistics.fmean(daily) * 100
        assert b["band"]["band_pct"] == pytest.approx(expected)
        assert b["band"]["days"] == n
    assert b30["band"]["band_pct"] < b7["band"]["band_pct"] / 2
    # The daily band barely moves with the window; the mean band shrinks ~ √(30/7).
    assert b30["daily_band"]["band_pct"] == pytest.approx(b7["daily_band"]["band_pct"], rel=0.15)


def test_mean_band_needs_two_days_and_a_positive_mean():
    assert sim.mean_band([]) is None
    assert sim.mean_band([5.0]).band_pct is None
    assert sim.mean_band([0.0, 0.0]).band_pct is None
    assert sim.mean_band([10.0, 10.0]).band_pct == 0


def test_daily_band_equals_the_old_band():
    history = sim.merge_reports([_report(60, imp=lambda i: 1000.0 + 37 * (i % 5))])
    payload = sim.baseline(history, 14)
    for row in payload["streams"]:
        days = sim._present(history.streams[row["stream"]], sim._days(history.last_day, 14))
        for cell in row["cells"]:
            old = sim.band(d.kpi(cell["kpi"]) for d in days)
            assert cell["daily_band"] == old.to_json()


@pytest.mark.parametrize(("orders_per_day", "low"), [(29 / 30, True), (1.0, False)])
def test_low_data_threshold_on_orders(orders_per_day, low):
    # 30 days × orders_per_day → 29 vs 30 SKU orders in the window.
    report = _report(30)
    for i, day in enumerate(sorted(report["daily_streams"]["product_card"])):
        report["daily_streams"]["product_card"][day] = [
            1000.0,
            100.0,
            (1 if i else 0) if low else 1,
            150_000.0,
        ]
    payload = sim.baseline(sim.merge_reports([report]), 30)
    for kpi in ("ctor", "aov"):
        cell = _cell(payload, "product_card", kpi)
        assert cell["event_kind"] == "order"
        assert cell["events"] == (29 if low else 30)
        assert cell["low_data"] is low
    ctr = _cell(payload, "product_card", "ctr")
    assert (ctr["event_kind"], ctr["events"], ctr["low_data"]) == ("click", 3000, False)


def test_low_data_threshold_on_clicks_and_impressions_never_low():
    report = _report(7, imp=lambda i: 80.0)  # 4 clicks/day → 28 clicks in 7 days
    payload = sim.baseline(sim.merge_reports([report]), 7)
    ctr = _cell(payload, "shop_tab", "ctr")
    assert (ctr["events"], ctr["low_data"]) == (28, True)
    imp = _cell(payload, "shop_tab", "impressions")
    assert (imp["events"], imp["event_kind"], imp["low_data"]) == (None, None, False)


def test_cell_verdict_uses_the_window_band_and_low_data():
    cell = {"band": {"band_pct": 7.4}, "low_data": False}
    assert sim.cell_verdict(cell, 0) is None
    assert sim.cell_verdict(cell, 5) == "in_noise"
    assert sim.cell_verdict(cell, -10) == "measurable"
    assert sim.cell_verdict({**cell, "low_data": True}, 50) == "low_data"
    assert sim.cell_verdict({"band": None, "low_data": False}, 50) == "in_noise"


# -- D31.7: strength of the ▲/▼ trend ---------------------------------------------


def _alternating_then_step(level_last: float, level_prior: float, n: int):
    """± 10 % alternating impressions around ``level_last`` (last n days), then prior."""

    def imp(i: int) -> float:
        level = level_last if i < n else level_prior
        return level * (0.9 if i % 2 else 1.1)

    return imp


@pytest.mark.parametrize(
    ("level_prior", "expected"),
    [(1000.0, "noise"), (930.0, "likely"), (850.0, "clear")],
)
def test_trend_strength_uses_both_windows_bands(level_prior, expected):
    n = 14
    history = sim.merge_reports([_report(60, imp=_alternating_then_step(1000.0, level_prior, n))])
    cell = _cell(sim.baseline(history, n), "product_card", "impressions")
    last = [1000.0 * (0.9 if i % 2 else 1.1) for i in range(n)]
    prior = [level_prior * (0.9 if i % 2 else 1.1) for i in range(n, 2 * n)]

    def pct(values):
        return 1.2816 * statistics.stdev(values) / math.sqrt(n) / statistics.fmean(values) * 100

    combined = math.hypot(pct(last), pct(prior))
    size = abs(cell["trend_pct"])
    assert cell["trend_strength"] == expected
    # The same rule, re-derived: ≥ 2 × combined clear, ≥ 1 × likely, else noise.
    assert expected == (
        "clear" if size >= 2 * combined else "likely" if size >= combined else "noise"
    )


def test_trend_strength_is_null_without_a_comparison_or_on_low_data():
    short = sim.baseline(sim.merge_reports([_report(20)]), 14)  # 20 < 2 × 14 days
    assert all(c["trend_strength"] is None for s in short["streams"] for c in s["cells"])
    thin = sim.baseline(sim.merge_reports([_report(60, imp=lambda i: 80.0)]), 7)
    ctr = _cell(thin, "shop_tab", "ctr")
    assert ctr["low_data"] is True and ctr["trend_strength"] is None
    # Hiển thị is never low-data: a flat series is graded (no change → noise).
    assert _cell(thin, "shop_tab", "impressions")["trend_strength"] == "noise"


def test_trend_strength_null_when_only_the_prior_window_is_thin():
    # Last 7 days: 10 clicks/day (70); the 7 before: 2 clicks/day (14 < 30).
    report = _report(14)
    for i, day in enumerate(sorted(report["daily_streams"]["product_card"], reverse=True)):
        clicks = 10.0 if i < 7 else 2.0
        report["daily_streams"]["product_card"][day] = [1000.0, clicks, 1.0, 150_000.0]
    cell = _cell(sim.baseline(sim.merge_reports([report]), 7), "product_card", "ctr")
    assert cell["low_data"] is False and cell["trend_pct"] is not None
    assert cell["trend_strength"] is None

"""P16 "Mô phỏng" math (D25.10, D25.11): baseline, trend, bands, locked cells, GMV."""

from __future__ import annotations

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
    assert imp["band"]["p10"] == pytest.approx(1006.0)
    assert imp["band"]["p90"] == pytest.approx(1054.0)
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

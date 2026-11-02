"""Phụ lục 01 arithmetic and expected move (services/shopee_kpi, ADR-117 step 3).

Synthetic series only, every expected value checkable by hand:

- ±D = (high week − low week) / 2 / baseline over the 4 full weeks, clamped to 5–15 %.
- the stability window is 14 days, 28 below 1,000 baseline clicks / 14 days and for
  CTOR / AOV; the first stable pass is the first full window at or above the pass level.
- data sufficiency: 3,000 impressions + 100 clicks / 30 days; CTOR / AOV 100 orders /
  28 days.
- acceptance: ⌈70 %⌉ of sufficient KPI metrics AND both product-card metrics.
- excluded days (10/10 ± 1) leave the baseline.
- milestones end the day before the same date k months later (29/10 → 28/11, 28/12, 28/01).
- expected move: lever shares, uniform variance, P(pass), trend weight, flow GMV.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from juli_backend.services.shopee_kpi import expected_move as em
from juli_backend.services.shopee_kpi.rules import (
    Acceptance,
    Adjustment,
    ContractTerms,
    ContractTermsError,
    FlowResult,
    FlowSpec,
    MetricResult,
    acceptance,
    excluded_days,
    flows_from_params,
    kpi_report,
    milestone_end,
    window_value,
)

START = date(2026, 6, 20)  # baseline 21/05 – 19/06: no excluded day near it
PARAMS = {"pass": 0.035, "target": 0.05}
CARD = FlowSpec("the_san_pham", ("impressions", "ctr"))
SHOP = FlowSpec("ca_shop", ("ctor", "aov"), tracking=True)


def terms(*flows: FlowSpec, start: date = START, **params: object) -> ContractTerms:
    return ContractTerms.from_params(
        {**PARAMS, **params}, measure_start=start, flows=flows or (CARD,)
    )


def constant(
    first: date, last: date, imp: float, clk: float, ordr: float = 0.0, gmv: float = 0.0
) -> dict[date, tuple[float, float, float, float]]:
    return {first + timedelta(i): (imp, clk, ordr, gmv) for i in range((last - first).days + 1)}


def baseline_with_week4(week4: float) -> dict[date, tuple[float, float, float, float]]:
    """1,000 impressions a day except the 4th full week (days 24–30 of the baseline)."""
    b0 = START - timedelta(30)
    s = constant(b0 - timedelta(60), START + timedelta(60), 1000, 100)
    for i in range(23, 30):
        s[b0 + timedelta(i)] = (week4, 100, 0.0, 0.0)
    return s


def metric(report, flow: str, name: str) -> MetricResult:
    fr = next(f for f in report.flows if f.flow == flow)
    return next(m for m in fr.metrics if m.metric == name)


# -- ±D clamp ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("week4", "raw", "clamped"),
    [
        # baseline (23·1000 + 7·week4)/30; raw = (week4 − 1000)/2/baseline
        (1100, 100 / 2 / (30700 / 30), 0.05),  # 4.9 % -> floor 5 %
        (1200, 200 / 2 / (31400 / 30), 200 / 2 / (31400 / 30)),  # 9.6 %, kept
        (1600, 600 / 2 / (34200 / 30), 0.15),  # 26.3 % -> cap 15 %
    ],
)
def test_d_is_half_the_week_range_over_the_baseline_clamped_to_5_15(week4, raw, clamped):
    report = kpi_report(terms(), {"the_san_pham": baseline_with_week4(week4)}, START)
    imp = metric(report, "the_san_pham", "impressions")
    assert imp.baseline == pytest.approx((23 * 1000 + 7 * week4) / 30)
    assert imp.d_raw == pytest.approx(raw)
    assert imp.d_pct == pytest.approx(clamped)
    assert imp.pass_level == pytest.approx(imp.baseline * 1.035)
    assert imp.target_level == pytest.approx(imp.baseline * 1.05)


# -- stability window ------------------------------------------------------------------


@pytest.mark.parametrize(("clicks_per_day", "window"), [(100, 14), (71, 28), (72, 14)])
def test_the_window_is_28_days_below_1000_clicks_per_14_days(clicks_per_day, window):
    # 71/day = 994 per 14 days (< 1,000) -> 28; 72/day = 1,008 -> 14.
    s = constant(START - timedelta(90), START + timedelta(60), 5000, clicks_per_day)
    report = kpi_report(terms(), {"the_san_pham": s}, START + timedelta(60))
    assert {m.window_days for m in report.flows[0].metrics} == {window}


def test_ctor_and_aov_always_use_the_28_day_window():
    s = constant(START - timedelta(90), START + timedelta(60), 0, 5000, 500, 5_000_000)
    report = kpi_report(terms(SHOP), {"ca_shop": s}, START + timedelta(60))
    assert {m.window_days for m in report.flows[0].metrics} == {28}


def test_the_first_stable_pass_is_the_first_full_window_at_the_pass_level():
    s = constant(START - timedelta(60), START + timedelta(40), 1000, 100)
    for i in range(41):  # +5 % impressions from day 0 of the measurement (pass = +3.5 %)
        s[START + timedelta(i)] = (1050, 105, 0.0, 0.0)
    report = kpi_report(terms(), {"the_san_pham": s}, START + timedelta(40))
    imp = metric(report, "the_san_pham", "impressions")
    assert imp.window_days == 14
    assert imp.first_stable_pass == {
        "window_end": (START + timedelta(13)).isoformat(),
        "value": pytest.approx(1050),
    }
    assert imp.last_window == pytest.approx(1050) and imp.vs_baseline == pytest.approx(0.05)
    # CTR did not move (105/1050 = 100/1000): optimised at the same time, never passes.
    assert metric(report, "the_san_pham", "ctr").first_stable_pass is None
    # unconfirmed achievement floor = first pass value × (1 − D) and it holds
    assert imp.achieved_floor == pytest.approx(1050 * (1 - 0.05)) and imp.achieved_ok is True


def test_a_window_reaching_before_measure_start_is_not_a_measurement():
    s = constant(START - timedelta(60), START + timedelta(10), 2000, 200)
    imp = metric(
        kpi_report(terms(), {"the_san_pham": s}, START + timedelta(10)),
        "the_san_pham",
        "impressions",
    )
    assert imp.last_window is None and imp.first_stable_pass is None


# -- data sufficiency ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("imp", "clk", "eligible"),
    [(100, 4, True), (99, 4, False), (100, 3.3, False), (100, 3.4, True)],
)
def test_sufficiency_is_3000_impressions_and_100_clicks_over_the_baseline(imp, clk, eligible):
    s = constant(START - timedelta(40), START, imp, clk)  # 30 kept days
    assert kpi_report(terms(), {"the_san_pham": s}, START).flows[0].eligible is eligible


@pytest.mark.parametrize(("orders_per_day", "eligible"), [(4, True), (3.5, False), (3.58, True)])
def test_ctor_aov_sufficiency_is_100_orders_in_the_28_days_before_start(orders_per_day, eligible):
    # 28 × 3.5 = 98 < 100; 28 × 3.58 = 100.24
    s = constant(START - timedelta(40), START, 0, 1000, orders_per_day, 1000 * orders_per_day)
    flow = kpi_report(terms(SHOP), {"ca_shop": s}, START).flows[0]
    assert flow.orders_28d == pytest.approx(28 * orders_per_day)
    assert flow.eligible is eligible


# -- acceptance --------------------------------------------------------------------------


def _m(name: str, passed: bool) -> MetricResult:
    return MetricResult(
        metric=name,
        tracking=False,
        baseline=1.0,
        d_pct=0.05,
        d_raw=0.05,
        window_days=14,
        last_window=1.1,
        vs_baseline=0.1,
        first_stable_pass={"window_end": "2026-07-03", "value": 1.1} if passed else None,
    )


def _f(
    flow: str, passes: tuple[bool, bool], *, eligible: bool = True, tracking: bool = False
) -> FlowResult:
    return FlowResult(
        flow=flow,
        tracking=tracking,
        eligible=eligible,
        baseline_days_kept=30,
        baseline_impressions_30d=1e5,
        baseline_clicks_30d=1e4,
        orders_28d=200,
        metrics=[_m("impressions", passes[0]), _m("ctr", passes[1])],
    )


def test_acceptance_needs_70_percent_of_sufficient_metrics_and_both_card_metrics():
    t = terms(CARD, FlowSpec("trang_shop", ("impressions", "ctr")))
    ok = acceptance(t, [_f("the_san_pham", (True, True)), _f("trang_shop", (True, False))])
    assert (ok.eligible, ok.passed, ok.needed) == (4, 3, 3)  # ⌈0.7 × 4⌉ = 3
    assert ok.accepted
    card_short = acceptance(t, [_f("the_san_pham", (True, False)), _f("trang_shop", (True, True))])
    assert card_short.passed == 3 and not card_short.required_flows_passed
    assert not card_short.accepted
    too_few = acceptance(t, [_f("the_san_pham", (True, True)), _f("trang_shop", (False, False))])
    assert too_few.passed == 2 and not too_few.accepted


def test_tracking_and_insufficient_flows_are_not_counted():
    t = terms(CARD, FlowSpec("trang_shop", ("impressions", "ctr")), SHOP)
    acc = acceptance(
        t,
        [
            _f("the_san_pham", (True, True)),
            _f("trang_shop", (False, False), eligible=False),
            _f("ca_shop", (False, False), tracking=True),
        ],
    )
    assert acc == Acceptance(eligible=2, passed=2, needed=2, required_flows_passed=True)
    assert acc.accepted


# -- excluded days, adjustments -----------------------------------------------------------


def test_sale_days_plus_minus_one_leave_the_baseline():
    start = date(2026, 10, 20)  # baseline 20/09 – 19/10 contains 09–11/10
    s = constant(start - timedelta(60), start, 1000, 30)
    for d in (date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11)):
        s[d] = (50_000, 5_000, 0.0, 0.0)
    report = kpi_report(terms(start=start), {"the_san_pham": s}, start)
    assert report.excluded_baseline == [date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11)]
    flow = report.flows[0]
    assert flow.baseline_days_kept == 27
    assert metric(report, "the_san_pham", "impressions").baseline == pytest.approx(1000)
    assert metric(report, "the_san_pham", "ctr").baseline == pytest.approx(0.03)


def test_extra_excluded_days_and_the_pad_come_from_the_contract():
    t = ContractTerms.from_params(
        {**PARAMS, "exclusions": {"sale_days": ["10-10"], "pad_days": 0}},
        measure_start=START,
        flows=[CARD],
        extra_excluded=[date(2026, 6, 1)],
    )
    days = excluded_days(t, date(2026, 5, 1), date(2026, 12, 31))
    assert days == frozenset({date(2026, 6, 1), date(2026, 10, 10)})


def test_a_confirmed_baseline_adjustment_scales_the_baseline_from_its_date():
    s = constant(START - timedelta(60), START + timedelta(5), 1000, 100)
    adj = Adjustment("the_san_pham", "impressions", "baseline_pct", -0.08, START)
    t = ContractTerms.from_params(PARAMS, measure_start=START, flows=[CARD], adjustments=[adj])
    report = kpi_report(t, {"the_san_pham": s}, START + timedelta(5))
    assert metric(report, "the_san_pham", "impressions").baseline == pytest.approx(920)
    assert report.warnings == []
    big = Adjustment("the_san_pham", "impressions", "baseline_pct", 0.12, START)
    t2 = ContractTerms.from_params(PARAMS, measure_start=START, flows=[CARD], adjustments=[big])
    assert "exceeds ±10%" in kpi_report(t2, {"the_san_pham": s}, START).warnings[0]


def test_window_value_is_a_ratio_of_sums_and_none_on_a_missing_day():
    s = {date(2026, 1, 2): (100.0, 10.0, 1.0, 50.0), date(2026, 1, 3): (300.0, 10.0, 3.0, 250.0)}
    a, b = date(2026, 1, 2), date(2026, 1, 3)
    assert window_value(s, a, b, "impressions") == 200
    assert window_value(s, a, b, "ctr") == pytest.approx(20 / 400)
    assert window_value(s, a, b, "ctor") == pytest.approx(4 / 20)
    assert window_value(s, a, b, "aov") == pytest.approx(300 / 4)
    assert window_value(s, a, date(2026, 1, 4), "ctr") is None


def test_contract_params_need_pass_and_target_and_known_metrics():
    with pytest.raises(ContractTermsError, match="pass"):
        ContractTerms.from_params({"target": 0.05}, measure_start=START, flows=[CARD])
    with pytest.raises(ContractTermsError, match="unknown metric"):
        ContractTerms.from_params(PARAMS, measure_start=START, flows=[FlowSpec("x", ("gmv",))])
    flows = flows_from_params(
        {"flows": {"a": {"metrics": ["ctr"]}, "b": {"metrics": ["aov"], "role": "theo_doi"}}}
    )
    assert flows == [FlowSpec("a", ("ctr",)), FlowSpec("b", ("aov",), tracking=True)]


# -- milestones -----------------------------------------------------------------------------


def test_milestones_end_the_day_before_the_same_date_k_months_later():
    start = date(2026, 10, 29)
    assert [milestone_end(start, k) for k in (1, 2, 3)] == [
        date(2026, 11, 28),
        date(2026, 12, 28),
        date(2027, 1, 28),
    ]
    # a 31st has no 31 November: clamp to the month's end, then the day before
    assert milestone_end(date(2026, 10, 31), 1) == date(2026, 11, 29)


# -- expected move --------------------------------------------------------------------------


def lever(flow: str, metric_name: str, low: float, high: float, starts_on: date, lag: int = 0):
    return em.LeverEffect("L1", 1, starts_on, lag, flow, metric_name, low, high)


def history(imp: float = 1000, clk: float = 100, growth: float = 0.0):
    first, last = START - timedelta(200), START - timedelta(1)
    return {
        first + timedelta(i): (imp * (1 + growth) ** i, clk * (1 + growth) ** i, 10.0, 1000.0)
        for i in range((last - first).days + 1)
    }


def test_a_fixed_lever_active_the_whole_window_multiplies_the_baseline():
    move = em.ExpectedMove(
        terms(),
        {"the_san_pham": history()},
        [lever("the_san_pham", "impressions", 0.1, 0.1, START)],
    )
    rows = {(f.metric, f.milestone, f.trend_weight): f for f in move.forecasts()}
    f = rows[("impressions", 1, 0.0)]
    assert f.window_end == date(2026, 7, 19) and f.window_days == 14
    assert f.expected == pytest.approx(1100)
    assert f.sd_log == pytest.approx(0.0) and f.p_pass == 1.0  # no noise in a constant history
    assert rows[("ctr", 1, 0.0)].expected == pytest.approx(0.1)  # no lever on CTR


def test_uniform_lever_variance_and_p_pass_are_log_normal():
    move = em.ExpectedMove(
        terms(),
        {"the_san_pham": history()},
        [lever("the_san_pham", "impressions", 0.0, 0.12, START)],
    )
    f = next(
        x
        for x in move.forecasts()
        if x.metric == "impressions" and x.milestone == 2 and x.trend_weight == 0
    )
    sd = math.sqrt(0.12**2 / 12)
    assert f.expected == pytest.approx(1060)
    assert f.sd_log == pytest.approx(sd)
    assert f.p_pass == pytest.approx(em.phi(math.log(1.06 / 1.035) / sd))
    assert f.lo90 == pytest.approx(1060 * math.exp(-1.645 * sd))
    assert f.hi90 == pytest.approx(1060 * math.exp(1.645 * sd))


def test_a_lever_counts_by_the_share_of_kept_window_days_it_is_active():
    end = milestone_end(START, 1)  # 19/07; 14-day window 06/07 – 19/07
    lv = lever("the_san_pham", "impressions", 0.2, 0.2, end - timedelta(6))  # last 7 of 14 days
    move = em.ExpectedMove(terms(), {"the_san_pham": history()}, [lv])
    f = next(
        x
        for x in move.forecasts()
        if x.metric == "impressions" and x.milestone == 1 and x.trend_weight == 0
    )
    assert f.expected == pytest.approx(1000 * (1 + 0.5 * 0.2))
    lagged = lever("the_san_pham", "impressions", 0.2, 0.2, end - timedelta(13), lag=7)
    g = em.ExpectedMove(terms(), {"the_san_pham": history()}, [lagged]).forecasts()
    assert g[0].expected == pytest.approx(1100)


def test_trend_weight_scales_the_historical_trend_linearly_in_log():
    move = em.ExpectedMove(terms(), {"the_san_pham": history(growth=0.002)}, [])
    dr = move.drift_of(CARD, "impressions")
    assert dr is not None and dr.mean > 0
    rows = {(f.metric, f.milestone, f.trend_weight): f for f in move.forecasts((0.0, 0.5, 1.0))}
    for k in (1, 2, 3):
        flat, half, full = (rows[("impressions", k, w)] for w in (0.0, 0.5, 1.0))
        assert full.expected / flat.expected == pytest.approx(math.exp(dr.mean * k))
        assert math.log(half.expected) == pytest.approx(
            (math.log(flat.expected) + math.log(full.expected)) / 2
        )
        assert flat.sd_log == pytest.approx(full.sd_log)


def test_too_little_history_gives_no_forecast():
    short = constant(START - timedelta(40), START - timedelta(1), 1000, 100)
    assert em.ExpectedMove(terms(), {"the_san_pham": short}, []).forecasts() == []


def test_flow_gmv_is_impressions_ctr_ctor_aov_times_30_with_added_variance():
    card = history()  # 1,000 imp, 100 clk, 10 orders, 1,000 gmv a day
    shop = {d: (0.0, 400.0, 20.0, 3000.0) for d in card}
    t = terms(CARD, SHOP)
    levers = [
        lever("the_san_pham", "ctr", 0.0, 0.12, START),
        lever("ca_shop", "aov", 0.0, 0.06, START),
    ]
    move = em.ExpectedMove(t, {"the_san_pham": card, "ca_shop": shop}, levers)
    gmv = next(
        f
        for f in move.forecasts()
        if f.metric == em.GMV_METRIC and f.milestone == 3 and f.trend_weight == 0
    )
    # the card's own baselines: 1,000 × 0.1 × (10/100) × (1,000/10) × 30 = 30,000
    assert gmv.baseline == pytest.approx(30_000)
    # CTR +6 % (card lever, 14-day window) and AOV +3 % (whole-shop lever, 28-day window)
    assert gmv.expected == pytest.approx(30_000 * 1.06 * 1.03)
    assert gmv.sd_log == pytest.approx(math.sqrt(0.12**2 / 12 + 0.06**2 / 12))
    assert gmv.p_pass is None

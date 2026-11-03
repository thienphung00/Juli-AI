"""P90 step 8 (ADR-121): the pure parts of the recommendation package -- vocabulary and wiring,
the predicted range (calibration shrinkage, simulation gate), the measurement plan (ADR-107
MDE rule), ranking (contract 11), the learning loop and the impact reader. Synthetic numbers."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.models import shop_proposals
from juli_backend.services.card_events import verification
from juli_backend.services.shopee_analytics.critical import CHANGE_KINDS
from juli_backend.services.shopee_recommendations import config, impact, learning, ranking
from juli_backend.services.shopee_recommendations.kinds import (
    FAMILIES,
    KINDS,
    WIRING,
    allowed_for_metric,
    kinds_of,
    spec,
)
from juli_backend.services.shopee_recommendations.model import Candidate, ProfitModel
from juli_backend.services.shopee_recommendations.plan import MetricStats, mde_for, measurement_plan
from juli_backend.services.shopee_recommendations.prediction import (
    convert,
    extra_orders_range,
    factor_from,
    gap_bucket,
    predict_lift,
    prior_range,
)
from juli_backend.services.shopee_recommendations.sheet import build_sheet
from juli_backend.services.shopee_recommendations.sim_priors import (
    SimImportError,
    SimPriors,
    SimRow,
    parse_priors,
)

# ------------------------------------------------------------------ vocabulary and wiring


def test_every_kind_belongs_to_a_family_and_maps_to_a_proposal_and_read_back_kind():
    assert set(FAMILIES) == {
        "ads",
        "promotion",
        "voucher",
        "sale",
        "combo",
        "affiliate",
        "mega_sale",
    }
    for key, s in KINDS.items():
        assert s.key == key and s.family in FAMILIES
        assert s.proposal_kind in shop_proposals.KINDS
        assert s.subject_type in shop_proposals.SUBJECT_TYPES
        if s.verify_kind is not None:
            assert s.verify_kind in verification.CHANGE_KINDS
    for family in FAMILIES:
        assert kinds_of(family), family


def test_section_8_wiring_is_the_analytics_wiring():
    for metric, kinds in CHANGE_KINDS.items():
        assert WIRING[metric] == tuple(kinds), metric
    assert allowed_for_metric("roas") == ("ads_roas_target", "ads_pause", "ads_purpose")
    assert allowed_for_metric("nope") == ()


def test_spec_refuses_an_unknown_kind():
    with pytest.raises(ValueError):
        spec("teleport")


# ------------------------------------------------------------------------- prediction


def _cand(kind="min_spend_voucher", gap=20.0, **inputs):
    return Candidate(kind=kind, items=("1",), inputs=inputs, gap_pct=gap)


def test_gap_bucket_and_prior_ranges():
    assert [gap_bucket(g) for g in (None, 5, 10, 29.9, 30, 80)] == [
        "unknown",
        "small",
        "medium",
        "medium",
        "large",
        "large",
    ]
    lo, hi = prior_range(KINDS["min_spend_voucher"], None, "medium")
    assert (lo, hi) == KINDS["min_spend_voucher"].prior
    lo2, hi2 = prior_range(KINDS["min_spend_voucher"], None, "large")
    assert lo2 == pytest.approx(lo * 1.5) and hi2 == pytest.approx(hi * 1.5)
    # a price cut scales with its size; a price rise flips the sign
    cut = prior_range(KINDS["product_discount"], 10.0, "unknown")
    rise = prior_range(KINDS["product_discount"], -10.0, "unknown")
    assert cut == pytest.approx((0.05, 0.2)) and rise == pytest.approx((-0.2, -0.05))
    # an ads budget step of 20 % is the prior; 40 % doubles it
    assert prior_range(KINDS["ads_budget"], 40.0, "unknown") == pytest.approx((0.06, 0.5))


def test_shop_factor_needs_five_results_and_is_shrunk_to_the_prior():
    assert factor_from(None, 0) == (1.0, "prior")
    assert factor_from(0.5, config.MIN_SHOP_RESULTS - 1) == (1.0, "prior")
    f, src = factor_from(0.5, 5)
    assert src == "shop" and f == pytest.approx(1 + 0.5 * (0.5 - 1))  # n / (n + K) = 5 / 10
    assert factor_from(9.0, 50)[0] == pytest.approx(1 + (50 / 55) * (config.FACTOR_MAX - 1))
    assert factor_from(0.01, 50)[0] == pytest.approx(1 + (50 / 55) * (config.FACTOR_MIN - 1))


def _env(calibration=None, sim=None):
    return SimpleNamespace(calibration=calibration or {}, sim=sim)


def test_calibration_moves_the_range_and_coverage_widens_it():
    s = KINDS["min_spend_voucher"]
    base = predict_lift(s, _cand(), _env(), None)
    state = learning.CalibrationState("min_spend_voucher", "aov", 10, 0.5, 10, 4, 1.4)
    cal = predict_lift(s, _cand(), _env({("min_spend_voucher", "aov"): state}), None)
    factor = 1 + (10 / 15) * (0.5 - 1)
    assert cal.factor == pytest.approx(factor) and cal.source == "shop"
    assert cal.mid == pytest.approx(base.mid * factor)
    assert (cal.high - cal.low) == pytest.approx((base.high - base.low) * factor * 1.4)
    assert base.source == "prior" and base.factor == 1.0


def _sim(weight: float, med=0.30, lo=0.20, hi=0.40) -> SimPriors:
    rows = [
        SimRow("1", "voucher_min_spend", "voucher_2x_10", "all", "aov", med, lo, hi, 0.01, True)
    ]
    return SimPriors(
        "run-1", "alias", "m", "p", {"voucher_min_spend": {"weight": weight, "status": "x"}}, rows
    )


def test_simulation_gate_weight_zero_leaves_the_range_exactly_as_without_it():
    s = KINDS["min_spend_voucher"]
    without = predict_lift(s, _cand(), _env(), None)
    gated = predict_lift(s, _cand(), _env(sim=_sim(0.0)), None, sim_variant=["voucher_2x_10"])
    assert (gated.low, gated.high, gated.factor, gated.source) == (
        without.low,
        without.high,
        without.factor,
        without.source,
    )
    assert gated.sim["gate_weight"] == 0.0 and gated.sim["applied"] is False
    assert gated.sim["row_found"] is True


def test_simulation_gate_weight_multiplies_its_influence():
    s = KINDS["min_spend_voucher"]
    plain = predict_lift(s, _cand(), _env(), None)
    half = predict_lift(s, _cand(), _env(sim=_sim(0.5)), None, sim_variant=["voucher_2x_10"])
    full = predict_lift(s, _cand(), _env(sim=_sim(1.0)), None, sim_variant=["voucher_2x_10"])
    assert half.sim["applied"] and full.sim["applied"]
    assert full.mid == pytest.approx(0.30)
    assert half.mid == pytest.approx((plain.mid + 0.30) / 2)
    # no matching variant = no influence even at weight 1
    miss = predict_lift(s, _cand(), _env(sim=_sim(1.0)), None, sim_variant=["voucher_9x_9"])
    assert (miss.low, miss.high) == (plain.low, plain.high) and not miss.sim["applied"]


def test_money_conversion_certain_plus_predicted_and_unit_cap():
    pm = ProfitModel(
        effect_days=30,
        base_gmv_per_day=D(100_000),
        aov=D(200_000),
        profit_per_gmv=D("0.25"),
        extra_cost_per_day=D(1_000),
        certain_dgmv_per_day=D(-500),
    )
    lift = predict_lift(KINDS["min_spend_voucher"], _cand(), _env(), None)
    m = convert(lift, pm)
    p50 = m["predicted"]["p50"]
    assert p50["dgmv"] == pytest.approx(100_000 * 30 * lift.mid)
    assert p50["dprofit"] == pytest.approx(p50["dgmv"] * 0.25)
    assert m["certain"] == {"dgmv": -15_000.0, "dprofit": -30_000.0, "dchi": 0.0}
    assert m["total"]["p50"]["dprofit"] == pytest.approx(p50["dprofit"] - 30_000)
    assert m["predicted"]["p10"]["dgmv"] < p50["dgmv"] < m["predicted"]["p90"]["dgmv"]
    assert m["predicted"]["p25"]["dgmv"] < p50["dgmv"] < m["predicted"]["p75"]["dgmv"]
    # a one-day slot with a unit cap cannot sell more than the cap
    slot = ProfitModel(
        effect_days=1,
        base_gmv_per_day=D(10_000_000),
        aov=D(100_000),
        profit_per_gmv=D("0.3"),
        max_extra_units=D(5),
    )
    big = convert(
        predict_lift(
            KINDS["flash_sale"], Candidate("flash_sale", ("1",), {"discount_pct": 40}), _env(), 40.0
        ),
        slot,
    )
    assert big["predicted"]["p90"]["dgmv"] <= 5 * 100_000
    # unknown profit stays None, never 0
    none = convert(lift, ProfitModel(base_gmv_per_day=D(1), aov=D(1)))
    assert none["predicted"]["p50"]["dprofit"] is None and none["total"]["p50"]["dprofit"] is None
    lo_hi = extra_orders_range(lift, pm)
    assert lo_hi is not None and lo_hi[0] < lo_hi[1]


# ------------------------------------------------------------------ measurement plan


def test_plan_picks_14_then_28_days_then_khó_kết_luận_by_the_mde_rule():
    busy = MetricStats(count_per_day=200.0, orders_per_day=200.0, phi=1.0)
    assert measurement_plan("orders", busy)["planned_days"] == 14
    # find a volume that fails at 14 days but passes at 28
    mid = None
    for per_day in [x / 4 for x in range(8, 800)]:
        s = MetricStats(count_per_day=per_day, orders_per_day=per_day)
        m14, m28 = mde_for("orders", s, 14), mde_for("orders", s, 28)
        if m14 > config.MDE_MAX >= m28:
            mid = s
            break
    assert mid is not None
    p = measurement_plan("orders", mid)
    assert p["planned_days"] == 28 and p["label"] == "Kết quả sau 28 ngày" and not p["pooled_only"]
    quiet = MetricStats(count_per_day=0.5, orders_per_day=0.5)
    q = measurement_plan("orders", quiet)
    assert q["planned_days"] is None and q["label"] == "khó kết luận" and q["pooled_only"]
    assert q["required_sample"] is None  # out of reach against a 28-day baseline


def test_plan_uses_the_metrics_own_variability():
    steady = MetricStats(orders_per_day=3.0, cv=0.2)
    wild = MetricStats(orders_per_day=3.0, cv=3.0)
    assert mde_for("aov", steady, 14) < mde_for("aov", wild, 14)
    rate = MetricStats(rate=0.05, trials_per_day=400.0)
    assert mde_for("ctr", rate, 28) < mde_for("ctr", rate, 14)
    assert mde_for("ctr", MetricStats(), 14) is None
    assert measurement_plan("none", MetricStats())["planned_days"] is None


# ----------------------------------------------------------------------------- ranking


def _ri(id, **kw):
    base = {"kind": "price", "family": "promotion", "items": (id,), "kpi_p25": {}, "dgmv_p25": 0.0}
    base.update(kw)
    return ranking.RankInput(id, **base)


GAPS = ranking.Gaps(
    {
        "gmv": {"target": 1_000_000.0, "current": 600_000.0, "gap": 400_000.0},
        "orders": {"target": 100.0, "current": 90.0, "gap": 10.0},
        "bien": {"target": 20.0, "current": 20.0, "gap": 0.0},
    }
)


def test_score_is_the_gap_share_weighted_to_the_furthest_behind_kpi():
    card = _ri("a", kpi_p25={"gmv": 100_000.0, "orders": 20.0})
    s, detail = ranking.score(card, GAPS)
    # weights: gmv gap/target = 0.4, orders = 0.1 -> 0.8 / 0.2; orders' gain is capped at its gap
    assert detail["mode"] == "gap_share_p25"
    assert detail["kpis"]["gmv"]["weight"] == pytest.approx(0.8)
    assert detail["kpis"]["orders"]["weight"] == pytest.approx(0.2)
    assert s == pytest.approx(0.8 * (100_000 / 400_000) + 0.2 * 1.0)
    assert "bien" not in detail["kpis"]  # not behind -> not scored


def test_a_negative_effect_on_a_lagging_kpi_lowers_the_score():
    s, _ = ranking.score(_ri("a", kpi_p25={"gmv": -40_000.0}), GAPS)
    assert s == pytest.approx(0.8 * -0.1)


def test_without_targets_the_score_is_dgmv_per_month_at_p25():
    none = ranking.Gaps({})
    s, detail = ranking.score(_ri("a", dgmv_p25=12_345.0), none)
    assert (s, detail["mode"]) == (12_345.0, "dgmv_month_p25")
    behind_nothing = ranking.Gaps({"gmv": {"target": 10.0, "current": 20.0, "gap": 0.0}})
    assert ranking.score(_ri("a", dgmv_p25=7.0), behind_nothing)[0] == 7.0


def test_every_hard_filter_drops_a_card_and_is_counted_once_under_the_first_it_fails():
    cards = [
        _ri("ok", kpi_p25={"gmv": 1.0}, dgmv_p25=1.0),
        _ri("locked", kpi_p25={"gmv": 9.0}),
        _ri("nostock", in_stock=False),
        _ri("floor", floor_breach=True),
        _ri("spend", spend_after=11.0, spend_cap=10.0),
        _ri("loss", dprofit_p50=-1.0),
        _ri("multi", floor_breach=True, dprofit_p50=-5.0),
    ]
    r = ranking.rank(cards, GAPS, locked={"locked": "sent:x"})
    assert [x.id for x in r.ordered] == ["ok"]
    assert r.counts == {
        "locked_by_plan": 1,
        "out_of_stock": 1,
        "below_operating_floor": 2,
        "over_spend_cap": 1,
        "negative_profit_p50": 1,
        "duplicate_product": 0,
    }
    assert (
        r.counts_any["negative_profit_p50"] == 2
    )  # "multi" fails two; counted under both in `any`
    reasons = {d["id"]: d["reasons"] for d in r.dropped}
    assert reasons["multi"] == ["below_operating_floor", "negative_profit_p50"]


def test_unknown_stock_and_profit_pass_but_are_counted():
    r = ranking.rank([_ri("a", in_stock=None, dprofit_p50=None)], GAPS)
    assert [x.id for x in r.ordered] == ["a"] and r.unknown == {"stock": 1, "profit": 1}


def test_one_change_per_product_keeps_the_best_card_and_a_mega_sale_holds_its_products():
    cards = [
        _ri("p1-lo", items=("p1",), kpi_p25={"gmv": 10.0}),
        _ri("p1-hi", items=("p1",), kpi_p25={"gmv": 90_000.0}),
        _ri("p2", items=("p2",), kpi_p25={"gmv": 5_000.0}),
        _ri(
            "mega",
            family="mega_sale",
            kind="mega_sale",
            items=(),
            mega_children_items=("p2", "p3"),
            kpi_p25={"gmv": 30_000.0},
        ),
    ]
    r = ranking.rank(cards, GAPS)
    assert [x.id for x in r.ordered] == ["p1-hi", "mega"]
    assert r.counts["duplicate_product"] == 2
    assert {d["id"] for d in r.dropped} == {"p1-lo", "p2"}


def test_acceptance_only_breaks_ties():
    a = _ri("a", items=("a",), kpi_p25={"gmv": 1_000.0}, acceptance=0.2)
    b = _ri("b", items=("b",), kpi_p25={"gmv": 1_000.0}, acceptance=0.9)
    assert [x.id for x in ranking.rank([a, b], GAPS).ordered] == ["b", "a"]
    c = _ri("c", items=("c",), kpi_p25={"gmv": 2_000.0}, acceptance=0.0)
    assert ranking.rank([a, b, c], GAPS).ordered[0].id == "c"


def test_the_dang_thu_slot_takes_the_largest_knowledge_gradient_among_the_eligible():
    cards = [
        _ri(f"c{i}", items=(f"c{i}",), kpi_p25={"gmv": 1000.0 - i}, kg_value=None) for i in range(6)
    ]
    cards[5].kg_value = 0.5
    cards[4].kg_value = 0.1
    plain = ranking.rank(cards, GAPS, top_n=3)
    assert [x.id for x in plain.ordered[:3]] == ["c0", "c1", "c2"]
    slot = ranking.rank(cards, GAPS, top_n=3, explore_slot=True)
    assert [x.id for x in slot.ordered[:3]] == ["c0", "c1", "c5"]
    assert slot.ordered[2].explore and slot.ordered[2].detail["slot"] == "dang_thu"
    assert [r.position for r in slot.ordered] == list(range(1, 7))


def test_month_gaps_project_the_window_pace_and_ignore_unset_targets():
    g = ranking.month_gaps(
        targets={
            "gmv_month": 3_000_000.0,
            "orders_month": None,
            "aov_month": 150_000.0,
            "margin_pct": 12.0,
        },
        gmv_30d=1_500_000.0,
        orders_30d=10.0,
        margin_pct=10.0,
        window_days=30,
        month_days=30,
    )
    assert set(g.rows) == {"gmv", "aov", "bien"}
    assert g.rows["gmv"]["gap"] == 1_500_000.0 and g.rows["aov"]["gap"] == 0.0
    assert g.rows["bien"]["gap"] == pytest.approx(2.0)
    assert set(g.behind) == {"gmv", "bien"}


# ----------------------------------------------------------------------- learning loop


def _obs(kind="min_spend_voucher", metric="aov", lo=0.04, hi=0.12, measured=0.08, se=None, **kw):
    return learning.Observation(kind, metric, lo, hi, measured, se, **kw)


def test_calibration_is_the_inverse_variance_pooled_measured_over_predicted():
    obs = [_obs(measured=0.04, se=0.01), _obs(measured=0.16, se=0.04)]  # ratios 0.5 and 2.0
    st = learning.calibrate(obs)[("min_spend_voucher", "aov")]
    w1, w2 = 1 / (0.01 / 0.08) ** 2, 1 / (0.04 / 0.08) ** 2
    assert st.pooled_ratio == pytest.approx((0.5 * w1 + 2.0 * w2) / (w1 + w2))
    assert st.n_results == 2
    eq = learning.calibrate([_obs(measured=0.04), _obs(measured=0.16)])[
        ("min_spend_voucher", "aov")
    ]
    assert eq.pooled_ratio == pytest.approx(1.25)  # no se -> equal weights


def test_stacked_changes_are_counted_but_never_enter_the_per_kind_calibration():
    obs = [_obs(measured=0.08), _obs(measured=0.50, bundle=True), _obs(measured=0.50, bundle=True)]
    st = learning.calibrate(obs)[("min_spend_voucher", "aov")]
    assert st.n_results == 1 and st.n_bundle_excluded == 2
    assert st.pooled_ratio == pytest.approx(1.0)


def test_coverage_scores_the_share_inside_the_range_and_widens_or_narrows_it():
    inside = [_obs(measured=0.08)] * 5
    assert (
        learning.calibrate(inside)[("min_spend_voucher", "aov")].range_scale
        == config.RANGE_SCALE_MIN
    )
    half = [_obs(measured=0.08)] * 3 + [_obs(measured=0.9)] * 2  # 60 % inside
    st = learning.calibrate(half)[("min_spend_voucher", "aov")]
    assert st.coverage == pytest.approx(0.6) and st.range_scale == pytest.approx(0.8 / 0.6)
    ok = [_obs(measured=0.08)] * 4 + [_obs(measured=0.9)]  # 80 %
    assert learning.calibrate(ok)[("min_spend_voucher", "aov")].range_scale == 1.0
    assert learning.range_scale_for(0, 3) == 1.0  # too few results to judge
    assert learning.range_scale_for(0, 10) == config.RANGE_SCALE_MAX
    rep = learning.coverage_report(learning.calibrate(half))
    assert rep[0]["coverage_n"] == 5 and rep[0]["coverage"] == 0.6


def test_a_reading_without_controls_is_kept_but_moves_neither_the_factor_nor_the_coverage():
    obs = [
        _obs(measured=0.08),
        _obs(measured=0.9, controlled=False),
        _obs(measured=0.9, controlled=False),
    ]
    st = learning.calibrate(obs)[("min_spend_voucher", "aov")]
    assert (st.n_results, st.coverage_n, st.pooled_ratio) == (1, 1, pytest.approx(1.0))
    assert st.sources == {"card": 1, "uncontrolled": 2}
    only = learning.calibrate([_obs(measured=0.9, controlled=False)])[("min_spend_voucher", "aov")]
    assert only.n_results == 0 and only.pooled_ratio is None and only.range_scale == 1.0


def test_observation_json_round_trips_and_zero_prediction_is_skipped():
    o = _obs(source="natural", ref="x")
    assert learning.Observation.from_json(o.json()) == o
    z = _obs(lo=-0.1, hi=0.1)
    assert z.ratio_and_variance() is None
    assert learning.calibrate([z])[("min_spend_voucher", "aov")].n_results == 0


def _events():
    def ev(t, kind="min_spend_voucher", **kw):
        return {
            "event_type": t,
            "reason_code": kw.pop("reason", None),
            "payload": {"change_kind": kind, **kw},
        }

    return [
        ev("accepted", final_vs_default={"value": 1.2}),
        ev("accepted", final_vs_default={"value": 1.2}),
        ev("accepted", final_vs_default={"value": 1.1}),
        ev("dismissed", reason="not_needed"),
        ev("dismissed", reason="later"),
        ev("expired"),
        ev("whatif_adjusted"),
        ev("accepted", kind="price"),
        {"event_type": "accepted", "payload": {}},  # no kind: ignored
    ]


def test_acceptance_statistics_feed_defaults_and_ties_not_effects():
    a = learning.acceptance_from_events(_events())
    assert (
        a.approved["min_spend_voucher"],
        a.dismissed["min_spend_voucher"],
        a.expired["min_spend_voucher"],
    ) == (3, 2, 1)
    assert a.adjusted["min_spend_voucher"] == 1
    assert a.rate("min_spend_voucher") == pytest.approx((3 + 1) / (6 + 2))
    assert a.rate("title") is None
    assert a.reasons["min_spend_voucher"] == {"not_needed": 1, "later": 1}
    # three approved adjustments move the default by their median (1.2), within +-30 %
    assert a.default_for("min_spend_voucher", "value", 10_000, 1_000, 500_000) == pytest.approx(
        12_000
    )
    assert a.default_for("min_spend_voucher", "quantity", 100, 1, 1000) == 100  # no evidence
    assert a.default_for("price", "new_price_pct", 105, 50, 150) == 105  # < 3 adjustments
    assert a.default_for("min_spend_voucher", "value", 10_000, 1_000, 11_000) == 11_000  # clamped


def test_the_effect_estimate_never_reads_acceptance():
    import inspect

    from juli_backend.services.shopee_recommendations import prediction

    assert "acceptance" not in inspect.getsource(prediction).lower().replace(
        "acceptance statistics never", ""
    )


def test_executed_change_days_cover_the_plan_inside_the_window():
    d = learning.executed_change_days(
        [(datetime(2026, 11, 2, 9), 14)], date(2026, 11, 1), date(2026, 11, 10)
    )
    assert min(d) == date(2026, 11, 2) and max(d) == date(2026, 11, 10) and len(d) == 9
    assert learning.executed_change_days([], date(2026, 11, 1), date(2026, 11, 10)) == frozenset()


# ------------------------------------------------------------------------ impact reader


def _series(
    rng, start, days, level, uplift_from=None, uplift=0.0, shock_from=None, shock=1.0, noise=0.05
):
    out = {}
    for i in range(days):
        d = start + timedelta(days=i)
        v = level * (1 + rng.gauss(0, noise))
        if uplift_from and d >= uplift_from:
            v *= 1 + uplift
        if shock_from and d >= shock_from:
            v *= shock
        out[d] = v
    return out


T = date(2026, 10, 20)
START = T - timedelta(days=15)


def _controls(rng, n=6, **kw):
    # a shared daily factor makes the controls correlate with the treated series
    common = {START + timedelta(days=i): 1 + rng.gauss(0, 0.15) for i in range(60)}
    out = {}
    for k in range(n):
        s = _series(rng, START, 45, 100.0, noise=0.03, **kw)
        out[f"c{k}"] = {d: v * common[d] for d, v in s.items()}
    return out, common


def test_a_known_uplift_is_recovered_and_a_zero_uplift_reads_about_zero():
    rng = random.Random(7)
    controls, common = _controls(rng)
    treated = {
        d: v * common[d]
        for d, v in _series(
            rng, START, 45, 100.0, noise=0.03, uplift_from=T + timedelta(days=1), uplift=0.10
        ).items()
    }
    r = impact.read_effect(treated, controls, T, post_days=14)
    assert r.confidence in ("cao", "trung_binh", "thap") and not r.fallback
    assert r.impact_pct == pytest.approx(0.10, abs=0.04)
    twin = {d: v * common[d] for d, v in _series(rng, START, 45, 100.0, noise=0.03).items()}
    z = impact.read_effect(twin, controls, T, post_days=14)
    assert abs(z.impact_pct) < 0.04


def test_a_shop_wide_shock_cancels_with_controls_but_not_in_naive_pre_post():
    rng = random.Random(11)
    shock = {"shock_from": T + timedelta(days=1), "shock": 1.5}
    controls, common = _controls(rng, **shock)
    treated = {
        d: v * common[d] for d, v in _series(rng, START, 45, 100.0, noise=0.03, **shock).items()
    }
    adjusted = impact.read_effect(treated, controls, T, post_days=14)
    naive = impact.read_effect(treated, {}, T, post_days=14)
    assert abs(adjusted.impact_pct) < 0.08
    assert (
        naive.impact_pct == pytest.approx(0.5, abs=0.12)
        and naive.fallback
        and naive.confidence == "thap"
    )
    assert adjusted.controls and len(adjusted.controls) <= impact.K_CONTROLS


def test_suppression_matrix():
    rng = random.Random(3)
    treated = _series(rng, START, 45, 100.0)
    assert (
        impact.read_effect(
            treated, {}, T, excluded=frozenset(START + timedelta(days=i) for i in range(30))
        ).reason
        == "too_few_days"
    )
    zero = dict.fromkeys(treated, 0.0)
    assert impact.read_effect(zero, {}, T).reason == "pre_below_floor"
    assert impact.read_effect(treated, {}, T, volume_floor_per_day=1e6).reason == "pre_below_floor"
    two = {"a": _series(rng, START, 45, 100.0), "b": _series(rng, START, 45, 100.0)}
    assert impact.read_effect(treated, two, T).fallback  # fewer than 3 controls


def test_excluded_days_are_dropped_from_both_windows():
    rng = random.Random(5)
    treated = _series(rng, START, 45, 100.0)
    treated[T + timedelta(days=3)] = 1e9  # a sale day
    skip = frozenset({T + timedelta(days=3)})
    r = impact.read_effect(treated, {}, T, excluded=skip)
    assert abs(r.impact_pct) < 0.1 and r.post_days_used == 13


# ------------------------------------------------------------------------ simulation file


def _doc(**over):
    doc = {
        "format": "juli-sim/priors/v1",
        "run_id": "r1",
        "platform": "shopee",
        "shop_alias": "alias",
        "gate": {
            "title": {"weight": 0.0, "status": "fail", "reason": "x"},
            "voucher_min_spend": {"weight": 1.0, "status": "pass"},
        },
        "versions": {"model_version": "m1", "priors_version": "p1"},
        "rows": [
            {
                "product_id": "1",
                "change_kind": "title",
                "variant": "v",
                "segment": "all",
                "metric": "ctr",
                "med": 0.01,
                "lo90": -0.1,
                "hi90": 0.2,
                "kg_value": None,
                "eligible": False,
            },
        ],
    }
    doc.update(over)
    return doc


def test_a_valid_priors_file_loads_with_its_gate_and_roundtrips_through_storage():
    p = parse_priors(_doc())
    assert (
        p.run_id == "r1"
        and p.gate_weight("title") == 0.0
        and p.gate_weight("voucher_min_spend") == 1.0
    )
    assert p.gate_weight("unknown_kind") == 0.0 and p.gate_status("unknown_kind") == "not_validated"
    back = SimPriors.from_stored({"run_id": "r1", "gate": p.gate}, p.to_stored())
    assert back.rows == p.rows


def test_gate_overrides_are_recorded_and_bounded():
    p = parse_priors(_doc(), gate_overrides={"title": 0.5})
    assert p.gate["title"]["weight"] == 0.5 and p.gate["title"]["override"] is True
    with pytest.raises(SimImportError):
        parse_priors(_doc(), gate_overrides={"title": 1.5})


@pytest.mark.parametrize(
    "bad",
    [
        {"format": "other"},
        {"platform": "tiktok"},
        {"run_id": ""},
        {"rows": "x"},
        {"gate": []},
        {"gate": {"title": {"weight": 2.0}}},
        {"rows": [{"product_id": "1"}]},
        {
            "rows": [
                {
                    "product_id": "1",
                    "change_kind": "t",
                    "variant": "v",
                    "segment": "all",
                    "metric": "ctr",
                    "med": "a",
                    "lo90": 0,
                    "hi90": 1,
                }
            ]
        },
        {
            "rows": [
                {
                    "product_id": "1",
                    "change_kind": "t",
                    "variant": "v",
                    "segment": "all",
                    "metric": "ctr",
                    "med": 0,
                    "lo90": 2,
                    "hi90": 1,
                }
            ]
        },
    ],
)
def test_an_invalid_priors_file_is_refused_without_quoting_values(bad):
    with pytest.raises(SimImportError) as exc:
        parse_priors(_doc(**bad))
    assert "alias" not in str(exc.value)


# ------------------------------------------------------------------- execution sheet


def test_the_sheet_changes_feed_the_read_back_contract():
    now = datetime(2026, 11, 4, 2, 0, tzinfo=UTC)
    sheet = build_sheet(
        "ads_budget",
        {"campaign_id": "8001"},
        {"daily_budget": 100_000},
        {"daily_budget": 120_000},
        {"daily_budget": 120_000},
    )
    (change,) = sheet["changes"]
    assert (
        change["change_kind"] == "daily_budget"
        and change["change_kind"] in verification.CHANGE_KINDS
    )
    ex = verification.ExecutedChange(
        shop_id=None,
        card_id=None,
        execution_ref="x",
        change_kind=change["change_kind"],  # type: ignore[arg-type]
        target=change["target"],
        expected=change["expected"],
        executed_at=now,
    )
    seen = [verification.Observation({"daily_budget": 120_000}, now + timedelta(hours=3))]
    assert verification.evaluate(ex, seen, now + timedelta(hours=4)).outcome == "verified"
    v = build_sheet(
        "min_spend_voucher",
        {},
        {},
        {"value": 15_000, "min_spend": 200_000, "quantity": 50, "days": 14},
        {"value": 15_000, "min_spend": 200_000, "quantity": 50},
    )
    assert v["changes"][0]["expected"] == {
        "discount_amount": 15_000,
        "min_spend": 200_000,
        "usage_limit": 50,
    }
    assert v["changes"][0]["target"] == {
        "voucher_id": None
    }  # filled in when the person marks "Đã làm"
    assert v["page"]["deep_link"].startswith("https://banhang.shopee.vn/portal/marketing/vouchers")
    assert v["save_hint"] and v["revert_steps"][0]["after"] == v["steps"][0]["before"]


def test_a_kind_without_a_reader_still_carries_its_change_under_its_own_name():
    s = build_sheet(
        "flash_sale",
        {"item_id": "1"},
        {"skus": [{"sku": "S", "price": 90_000}]},
        {"skus": [{"sku": "S", "price": 70_000}]},
        {"discount_pct": 30, "units": 20},
    )
    assert (
        s["changes"][0]["change_kind"] == "flash_sale"
    )  # a slot price has no read-back reader yet
    d = build_sheet(
        "product_discount",
        {"item_id": "1"},
        {"skus": [{"sku": "S", "price": 90_000}]},
        {"skus": [{"sku": "S", "price": 80_000}]},
        {"discount_pct": 20},
    )
    assert d["changes"][0] == {
        "change_kind": "price",
        "target": {"item_id": "1", "sku": "S"},
        "expected": {"current_price": 80_000},
    }
    g = build_sheet("add_on", {"item_id": "1"}, {}, {"addon_item_id": "2", "discount_pct": 10}, {})
    assert g["changes"][0]["change_kind"] == "add_on" and g["page"]["verified"] is False

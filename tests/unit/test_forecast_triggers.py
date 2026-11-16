"""F11: the shared trigger detector (pure) and the Shopee adapter's routing of cards."""

from __future__ import annotations

from datetime import date, timedelta

from juli_backend.services.forecast import triggers as trg
from juli_backend.services.shopee_recommendations import trigger_adapter as ta
from juli_backend.services.shopee_recommendations.model import Candidate

END = date(2026, 11, 10)


def _series(
    pid,
    before,
    now,
    *,
    views=(1000, 1000),
    ctr=(0.05, 0.05),
    ctor=(0.1, 0.1),
    aov=(100.0, 100.0),
    jitter=0.02,
):
    """60 days: the first 30 'before', the last 30 'now' (gmv from views x ctr x ctor x aov)."""
    rows = []
    for i in range(60):
        half = 0 if i < 46 else 1
        wob = 1 + jitter * (1 if i % 2 else -1)
        v = views[half] * wob
        clicks = v * ctr[half]
        orders = clicks * ctor[half]
        rows.append(trg.DayRow(END - timedelta(days=59 - i), v, clicks, orders, orders * aov[half]))
    return trg.ProductSeries(pid, tuple(rows))


class _Adapter:
    def __init__(self, median=None, margin=None, forecasts=(), rules=()):
        self.median, self.margin, self._f, self._r = median, margin, list(forecasts), list(rules)

    def reference(self, product_id):
        return trg.Reference(shop_median=self.median)

    def levers_for(self, metric):
        return (f"lever_{metric}",)

    def profit_per_gmv(self, product_id):
        return self.margin

    def forecasts(self, product_id):
        return [f for f in self._f if f.product_id == product_id]

    def rule_triggers(self):
        return self._r


def test_problem_only_beyond_the_band():
    flat = _series("a", 0, 0)
    assert trg.detect([flat], _Adapter(), as_of=END) == []
    tiny = _series("b", 0, 0, ctor=(0.1, 0.0997))  # -0.3 %: inside the band
    assert [
        t for t in trg.detect([tiny], _Adapter(), as_of=END) if t.trigger_type == "problem"
    ] == []
    big = _series("c", 0, 0, ctor=(0.1, 0.05))
    (t,) = trg.detect([big], _Adapter(), as_of=END)
    assert t.trigger_type == trg.PROBLEM and t.value > 0


def test_decomposition_picks_the_right_metric():
    for metric, kw in {
        "views": {"views": (1000, 500)},
        "ctr": {"ctr": (0.05, 0.025)},
        "ctor": {"ctor": (0.1, 0.05)},
        "aov": {"aov": (100.0, 50.0)},
    }.items():
        (t,) = trg.detect([_series("p", 0, 0, **kw)], _Adapter(), as_of=END)
        assert t.target_metric == metric and t.levers == (f"lever_{metric}",)


def test_low_data_metric_is_not_the_target():
    # clicks per window stay below the minimum: ctr / ctor are low-data, views explains the drop
    small = _series("s", 0, 0, views=(60, 30), ctr=(0.3, 0.3), ctor=(0.5, 0.5))
    rows = trg.detect([small], _Adapter(), as_of=END, min_events=1000)
    assert rows == []  # gmv itself is low-data: no trigger


def test_reference_is_the_max_and_value_uses_profit_when_known():
    p = _series("p", 0, 0, ctor=(0.1, 0.05))
    unknown = trg.detect([p], _Adapter(), as_of=END)[0]
    known = trg.detect([p], _Adapter(margin=0.2), as_of=END)[0]
    assert unknown.value_basis == "gmv" and known.value_basis == "profit"
    assert abs(known.value - unknown.value * 0.2) < 1e-6
    high = trg.detect([p], _Adapter(median=10_000_000.0), as_of=END)
    assert high and high[0].detail["reference_source"] == "shop_median"


def _forecast(dgmv, dprofit=None, pid="a", lever="flash_sale"):
    hist = [1000.0 + (i % 2) * 40 for i in range(30)]  # band of a 14-day total is ~ +-1.5k
    return trg.LeverForecast(pid, lever, "ctor", dgmv, dprofit, 14, hist)


def test_opportunity_gated_on_band_and_positive_value():
    flat = _series("a", 0, 0)
    big = trg.detect([flat], _Adapter(forecasts=[_forecast(50_000.0, 5.0)]), as_of=END)
    assert [t.trigger_type for t in big] == [trg.OPPORTUNITY]
    below = trg.detect([flat], _Adapter(forecasts=[_forecast(10.0, 5.0)]), as_of=END)
    assert below == []
    neg = trg.detect([flat], _Adapter(margin=0.2, forecasts=[_forecast(50_000.0, -5.0)]), as_of=END)
    assert neg == []
    # profit unknown: the value is the ΔGMV
    (t,) = trg.detect([flat], _Adapter(forecasts=[_forecast(50_000.0, None)]), as_of=END)
    assert t.value_basis == "gmv" and t.value == 50_000.0


def test_product_with_a_problem_gets_no_opportunity():
    p = _series("a", 0, 0, ctor=(0.1, 0.05))
    out = trg.detect([p], _Adapter(forecasts=[_forecast(50_000.0)]), as_of=END)
    assert [t.trigger_type for t in out] == [trg.PROBLEM]


def test_rule_passes_through():
    rule = trg.RuleTrigger("stock_alert", "a", urgency=3.0, value=1.0)
    (t,) = trg.detect([], _Adapter(rules=[rule]))
    assert t.trigger_type == trg.RULE and t.rule == "stock_alert" and t.urgency == 3.0


def _t(kind, value, urgency=0.0):
    return trg.Trigger(kind, "x", None, value, "gmv", urgency=urgency)


def test_ranking_order():
    ranked = trg.rank(
        [
            _t(trg.OPPORTUNITY, 100.0),
            _t(trg.PROBLEM, 95.0),  # similar to the opportunity: problem first
            _t(trg.PROBLEM, 50.0),
            _t(trg.RULE, 0.0, urgency=1.0),
            _t(trg.RULE, 0.0, urgency=9.0),
        ]
    )
    assert [(t.trigger_type, t.value, t.urgency) for t in ranked] == [
        (trg.RULE, 0.0, 9.0),
        (trg.RULE, 0.0, 1.0),
        (trg.PROBLEM, 95.0, 0.0),
        (trg.OPPORTUNITY, 100.0, 0.0),
        (trg.PROBLEM, 50.0, 0.0),
    ]
    far = trg.rank([_t(trg.OPPORTUNITY, 100.0), _t(trg.PROBLEM, 50.0)])
    assert [t.trigger_type for t in far] == [trg.OPPORTUNITY, trg.PROBLEM]


# ------------------------------------------------------------------ Shopee adapter


def _card(dgmv, hist, kind="flash_sale"):
    return {
        "metric": {"key": "orders"},
        "predicted": {
            "money_per_month": {
                "period": {"days": 14, "total": {"p50": {"dgmv": dgmv, "dprofit": dgmv / 10}}}
            }
        },
        "rank_inputs": {"dprofit_p50": 1.0},
        "_hist": hist,
    }


class _Env:
    class view:
        class profit:
            margin_pct = None

        class data:
            funnel = None

    funnel_history = None


def _route(monkeypatch, built):
    import juli_backend.services.shopee_recommendations.cards as cards

    monkeypatch.setattr(
        cards, "_history", lambda env, cand: {"gmv": [1000.0 + (i % 2) * 40 for i in range(30)]}
    )
    return ta.route_cards(_Env(), built)


def test_shopee_adapter_keeps_every_kind_that_clears_the_band(monkeypatch):
    crit = {"id": "c", "kpi": "ctor"}
    built = [
        (Candidate("product_discount", ("1",), critical=crit), _card(50_000.0, None)),
        (Candidate("voucher_cap", ("1",), critical=crit), _card(0.0, None)),
        (Candidate("flash_sale", ("1",)), _card(50_000.0, None)),
        (Candidate("keyword", ("2",)), _card(50_000.0, None)),
    ]
    kept, dropped = _route(monkeypatch, built)
    assert [c.kind for c, _ in kept] == [c.kind for c, _ in built] and not dropped
    assert [k["trigger_type"] for _, k in kept] == ["problem", "rule", "opportunity", "opportunity"]
    assert kept[0][1]["trigger_metric"] == "ctor"


def test_shopee_opportunity_below_the_band_is_dropped(monkeypatch):
    built = [
        (Candidate("flash_sale", ("1",)), _card(10.0, None)),
        (Candidate("keyword", ("2",)), _card(50_000.0, None)),
    ]
    kept, dropped = _route(monkeypatch, built)
    assert [c.kind for c, _ in kept] == ["keyword"] and dropped == {"flash_sale": 1}


def test_a_thin_product_falls_back_to_the_longest_window_not_low_data():
    """F2 amendment 2 (owner 2026-11-16): under min_events -> the 60-day window anyway."""
    from juli_backend.services.forecast import triggers

    as_of = date(2026, 11, 16)
    rows = {
        as_of - timedelta(days=i): triggers.DayRow(as_of - timedelta(days=i), 100, 10, 1, 50_000.0)
        for i in range(0, 60, 3)  # 20 orders in 60 days: never 30
    }
    assert triggers._adaptive_window(rows, as_of, "ctor", (14, 30, 60), 30) == (60, False)
    assert triggers._adaptive_window({}, as_of, "ctor", (14, 30, 60), 30) == (60, True)

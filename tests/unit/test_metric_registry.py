"""The metric registry (``services/metrics``), against ``docs/architecture/metric-registry.md``.

The registry is data, so most of these tests walk every metric: every id of doc §5 exists,
every formula reads known ids without a cycle, summable metrics are sums, and every ratio is
``None`` when its denominator is 0 or missing. The rest pin the evaluator's rules, the two
written allocation rules (ORY October 2026 as the acceptance case, doc §10) and ``kol_status``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from juli_backend.services.metrics import (
    COMPONENTS,
    DERIVATION_VERSION,
    METRICS,
    Comparison,
    KolState,
    change,
    channel_partition,
    evaluate,
    kol_status,
    per_day,
    shop_lines,
)
from juli_backend.services.metrics.components import (
    component_available,
    gate_source,
    resolve_components,
)
from juli_backend.services.metrics.compute import raw_value
from juli_backend.services.metrics.registry import (
    LINEAR_OPERATORS,
    TRAFFIC_SOURCES,
    Platform,
    ops,
    refs,
    source_available,
)
from juli_backend.services.shopee_profit.money import to_dong

D = Decimal
AS_OF = date(2026, 10, 31)

COSTS = (
    "cost_cogs",
    "cost_packaging",
    "cost_fees",
    "cost_shipping",
    "cost_ads",
    "cost_affiliate",
    "cost_offers",
    "cost_other",
    "cost_total",
    "cost_marketing",
)
CHANNELS = ("organic", "ads", "affiliate")
DOC_IDS = {
    # Volume
    "gmv",
    "orders",
    "units",
    "aov",
    "net_revenue",
    # Profit and margin
    "profit",
    "margin",
    "margin_sale",
    "contribution",
    # Costs
    *COSTS,
    *(f"{c}_pct" for c in COSTS),
    # Returns on cost
    "roi",
    "roas",
    "roas_direct",
    "roas_break_even",
    "roi_kol",
    "card_return",
    # Funnel
    "views",
    "clicks",
    "ctr",
    "ctor",
    "ctr_ads",
    "ctor_ads",
    # Channels
    *(f"channel_{kind}_{ch}" for kind in ("gmv", "share", "profit", "cost_pct") for ch in CHANNELS),
    # Stock
    "units_per_day",
    "days_left",
    "runs_out_on",
    "restock_units",
    # KOL
    "kol_gmv",
    "kol_share",
    "kol_commission",
    "kol_net",
    "kol_status",
}
HELPER_IDS = {
    m.id for m in METRICS.values() if isinstance(m.formula, tuple) and m.formula[0] == "helper"
}


def _metric_deps(metric_id: str) -> list[str]:
    return [r for r in refs(METRICS[metric_id].formula) if r not in COMPONENTS]


def _leaves(expr: Any) -> set[str]:
    """The component ids an expression reads, through the metrics it reads."""
    out: set[str] = set()
    for r in refs(expr):
        out |= {r} if r in COMPONENTS else _leaves(METRICS[r].formula)
    return out


def _divisions(expr: Any) -> list[Any]:
    if isinstance(expr, str):
        return [] if expr in COMPONENTS else _divisions(METRICS[expr].formula)
    op, *args = expr
    if op in ("const", "param", "helper"):
        return []
    found = [expr] if op == "div" else []
    for a in args:
        found += _divisions(a)
    return found


def ones(**overrides: Decimal | None) -> dict[str, Decimal | None]:
    comps: dict[str, Decimal | None] = {cid: D(1) for cid in COMPONENTS}
    comps["gmv"] = D(10)  # room for three non-empty channels
    comps.update(overrides)
    return comps


# -- the registry as data ---------------------------------------------------------------------


def test_every_doc_metric_id_is_registered() -> None:
    assert DOC_IDS - set(METRICS) == set()


def test_comparisons_are_an_enum_not_metrics() -> None:
    assert {c.value for c in Comparison} == {"prev", "month_prev", "target"}
    assert not {c.value for c in Comparison} & set(METRICS)


def test_derivation_version_is_dated() -> None:
    assert DERIVATION_VERSION == "2026-11-24.2"


@pytest.mark.parametrize("metric_id", sorted(METRICS))
def test_formula_reads_known_ids_and_known_operators(metric_id: str) -> None:
    metric = METRICS[metric_id]
    for r in refs(metric.formula):
        assert r in COMPONENTS or r in METRICS, f"{metric_id} reads unknown {r}"
    assert metric.components == tuple(dict.fromkeys(refs(metric.formula)))
    assert metric.label_vi
    assert "shopee" in metric.sources and "tiktok" not in metric.sources
    if metric.coverage is not None:
        assert metric.coverage in METRICS


def test_no_formula_cycles() -> None:
    state: dict[str, str] = {}

    def visit(mid: str, path: tuple[str, ...]) -> None:
        if state.get(mid) == "done":
            return
        assert state.get(mid) != "open", f"cycle: {' -> '.join((*path, mid))}"
        state[mid] = "open"
        for dep in _metric_deps(mid):
            visit(dep, (*path, mid))
        state[mid] = "done"

    for mid in METRICS:
        visit(mid, ())


@pytest.mark.parametrize("metric_id", sorted(m for m in METRICS if METRICS[m].summable))
def test_summable_metrics_are_sums_of_summable_ids(metric_id: str) -> None:
    formula = METRICS[metric_id].formula
    assert set(ops(formula)) <= LINEAR_OPERATORS
    for r in refs(formula):
        assert COMPONENTS[r].summable if r in COMPONENTS else METRICS[r].summable, r


@pytest.mark.parametrize("metric_id", sorted(set(METRICS) - HELPER_IDS))
def test_every_metric_evaluates_on_complete_components(metric_id: str) -> None:
    assert evaluate(metric_id, ones(), as_of=AS_OF).value is not None


@pytest.mark.parametrize("metric_id", sorted(set(METRICS) - HELPER_IDS))
def test_a_missing_component_is_none_not_zero(metric_id: str) -> None:
    for leaf in _leaves(METRICS[metric_id].formula):
        got = evaluate(metric_id, ones(**{leaf: None}), as_of=AS_OF).value
        assert got is None, f"{metric_id} with {leaf}=None gave {got}"


RATIO_CASES = [
    (mid, i, den)
    for mid in sorted(set(METRICS) - HELPER_IDS)
    for i, (_, _, den) in enumerate(_divisions(METRICS[mid].formula))
]


@pytest.mark.parametrize(("metric_id", "i", "denominator"), RATIO_CASES)
@pytest.mark.parametrize("blank", [D(0), None])
def test_every_ratio_is_none_when_its_denominator_is_zero_or_missing(
    metric_id: str, i: int, denominator: Any, blank: Decimal | None
) -> None:
    comps = ones(**dict.fromkeys(_leaves(denominator), blank))
    assert evaluate(metric_id, comps, as_of=AS_OF).value is None


# -- evaluator rules --------------------------------------------------------------------------


def test_ory_october_volume_and_aov() -> None:
    comps = {"gmv": D(21_336_200), "orders": D(123)}
    gmv = evaluate("gmv", comps, as_of=AS_OF)
    assert gmv.value == D(21_336_200)
    assert gmv.basis == "platform"
    assert gmv.as_of == AS_OF
    assert gmv.derivation_version == DERIVATION_VERSION
    assert evaluate("aov", comps).value == D(173_465)  # 173 465,04 -> đồng half up


@pytest.mark.parametrize(
    ("metric_id", "comps", "expected"),
    [
        ("aov", {"gmv": D(1001), "orders": D(2)}, D(501)),  # 500,5 half up
        ("margin", {}, None),
        ("ctr", {"clicks": D(1), "views": D(3)}, D("33.3")),
        ("ctr", {"clicks": D(2), "views": D(3)}, D("66.7")),
        ("roas", {"ads_gmv_platform": D(25), "ads_spend": D(10)}, D("2.5")),
        ("roas", {"ads_gmv_platform": D(1), "ads_spend": D(3)}, D("0.3")),
        ("units_per_day", {"units": D(10), "window_days": D(3)}, D("3.3")),
        ("days_left", {"stock_units": D(20), "units": D(30), "window_days": D(7)}, D(4)),
        ("cost_coverage", {"cogs_known_gmv": D(2), "line_gmv": D(3)}, D("0.667")),
    ],
)
def test_rounding_rules(metric_id: str, comps: dict[str, Decimal | None], expected: Any) -> None:
    assert evaluate(metric_id, comps).value == expected


def test_restock_rounds_up_and_uses_shop_rules() -> None:
    comps = {"units": D(10), "window_days": D(7), "stock_units": D(5)}
    # 10/7 × (7 + 14) − 5 = 25
    assert evaluate("restock_units", comps).value == D(25)
    # lead 3 + cover 14: 10/7 × 17 − 5 = 19,28… -> 20
    assert evaluate("restock_units", comps, params={"lead_time_days": D(3)}).value == D(20)
    assert evaluate("restock_units", {**comps, "stock_units": D(999)}).value == D(0)


def test_runs_out_on_is_a_date_from_as_of() -> None:
    comps = {"stock_units": D(20), "units": D(30), "window_days": D(7)}
    assert evaluate("runs_out_on", comps, as_of=AS_OF).value == date(2026, 11, 4)
    assert evaluate("runs_out_on", comps).value is None


def test_profit_carries_coverage_and_is_partial_below_full() -> None:
    comps = ones(
        net_revenue_known=D(1000),
        cogs=D(300),
        packaging=D(0),
        fees=D(100),
        shipping_net=D(0),
        affiliate_commission=D(50),
        ads_spend=D(200),
        other_marketing=D(0),
        cogs_known_gmv=D(900),
        line_gmv=D(1000),
    )
    profit = evaluate("profit", comps)
    assert profit.value == D(350)
    assert profit.coverage == D("0.9")
    assert profit.partial is True
    # decision #44: the ladder -- gộp (− giá vốn − đóng gói), đóng góp (− phí − vận chuyển ròng,
    # before ads and affiliate), ròng (− QC − AFF − marketing khác)
    assert evaluate("gross_profit", comps).value == D(700)
    assert evaluate("contribution", comps).value == D(600)
    assert evaluate("margin", comps).value == D("35.0")
    assert evaluate("margin_gross", comps).value == D("70.0")
    assert evaluate("margin_contribution", comps).value == D("60.0")
    full = evaluate("profit", {**comps, "cogs_known_gmv": D(1000)})
    assert (full.coverage, full.partial) == (D(1), False)


def test_ratios_come_from_summed_components_not_averages() -> None:
    days = [{"gmv": D(100), "orders": D(1)}, {"gmv": D(900), "orders": D(9)}, {"gmv": D(0)}]
    summed = {k: sum((d.get(k, D(0)) for d in days), D(0)) for k in ("gmv", "orders")}
    assert evaluate("aov", summed).value == D(100)
    assert evaluate("aov", days[2]).value is None  # a day without orders is no AOV, not 0


def test_a_helper_metric_is_refused_by_evaluate() -> None:
    with pytest.raises(ValueError, match="kol_status") as refused:
        evaluate("kol_status", ones())
    assert "kol_status" in str(refused.value)


@pytest.mark.parametrize(
    ("value", "ref", "expected"),
    [
        (D(120), D(100), D("0.2")),
        (D(80), D(100), D("-0.2")),
        (D(5), D(0), None),
        (None, D(100), None),
        (D(5), None, None),
    ],
)
def test_change(value: Decimal | None, ref: Decimal | None, expected: Decimal | None) -> None:
    assert change(value, ref) == expected


def test_per_day_only_for_summable_metrics() -> None:
    assert per_day("gmv", D(700), 7) == D(100)
    assert per_day("gmv", None, 7) is None
    assert per_day("gmv", D(700), 0) is None
    for ratio in ("aov", "margin", "ctr", "roi"):
        with pytest.raises(ValueError, match="not summable"):
            per_day(ratio, D(1), 7)


# -- allocation (doc §6, §7) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gmv", "affiliate", "ads", "expected"),
    [
        (D(100), D(20), D(30), (D(20), D(30), D(50))),
        (D(100), D(20), D(90), (D(20), D(80), D(0))),  # ads capped at gmv − affiliate
        (D(100), D(120), D(10), (D(100), D(0), D(0))),  # affiliate never above gmv
        (D(100), D(0), D(0), (D(0), D(0), D(100))),
        (D(0), D(0), D(0), (D(0), D(0), D(0))),
        (D(21_336_200), D(3_000_000), D(25_000_000), (D(3_000_000), D(18_336_200), D(0))),
        (D(100), None, D(30), (None, None, None)),
        (None, D(10), D(10), (None, None, None)),
    ],
)
def test_channel_partition_adds_up_to_shop_gmv(
    gmv: Decimal | None, affiliate: Decimal | None, ads: Decimal | None, expected: tuple
) -> None:
    got = channel_partition(gmv, affiliate, ads)
    assert (got["affiliate"], got["ads"], got["organic"]) == expected
    if gmv is not None and None not in expected:
        assert sum(expected, D(0)) == gmv
        assert all(v >= 0 for v in expected)


def test_channel_profit_adds_up_to_shop_profit() -> None:
    comps = ones(
        gmv=D(1000),
        affiliate_gmv=D(200),
        ads_gmv_confirmed=D(300),
        net_revenue_known=D(900),
        cogs=D(300),
        packaging=D(10),
        fees=D(90),
        shipping_net=D(0),
        affiliate_commission=D(20),
        ads_spend=D(100),
        other_marketing=D(0),
    )
    channels = [raw_value(f"channel_profit_{ch}", comps) for ch in CHANNELS]
    assert all(isinstance(v, Decimal) for v in channels)
    assert to_dong(sum(channels, D(0))) == raw_value("profit", comps) == D(380)


ORY_SHOP_PROFIT = D(2_838_185)
ORY_PRODUCTS_PROFIT = D(6_234_547)
ORY_COST_ADS = D(3_397_017)


def test_shop_lines_ory_october() -> None:
    shop = {
        "profit": ORY_SHOP_PROFIT,
        "ads_spend": ORY_COST_ADS,
        "other_marketing": D(0),
        "gmv": D(21_336_200),
        "orders": D(123),
    }
    products = [
        {
            "profit": ORY_PRODUCTS_PROFIT,
            "ads_spend": D(0),
            "line_gmv": D(21_336_200),
            "line_orders": D(123),
        }
    ]
    out = shop_lines(shop, products)
    by_key = {line.key: line for line in out.lines}
    assert [line.label_vi for line in out.lines] == [
        "Quảng cáo chưa gán sản phẩm",
        "Chi phí marketing khác",
        "Chênh lệch cơ sở",
        "Chênh lệch làm tròn / phân bổ",
    ]
    assert by_key["ads_unassigned"].profit == -ORY_COST_ADS
    assert by_key["other_marketing"].profit == 0
    assert (by_key["basis_gap"].gmv, by_key["basis_gap"].orders) == (D(0), D(0))
    # shop − Σ product = −3 396 362 against ads −3 397 017: the 655 đ is the labelled remainder
    assert by_key["rounding_allocation"].profit == D(655)
    assert out.gap == D(655)
    assert out.residual == D(0)


@pytest.mark.parametrize(
    ("shop", "products", "lines"),
    [
        (
            {
                "profit": D(700),
                "ads_spend": D(300),
                "other_marketing": D(50),
                "gmv": D(5000),
                "orders": D(10),
            },
            [
                {"profit": D(600), "ads_spend": D(100), "line_gmv": D(3000), "line_orders": D(6)},
                {"profit": D(350), "ads_spend": D(0), "line_gmv": D(1900), "line_orders": D(3)},
            ],
            {
                "ads_unassigned": (D(-200), None, None),
                "other_marketing": (D(-50), None, None),
                "basis_gap": (D(0), D(100), D(1)),
                "rounding_allocation": (D(0), None, None),
            },
        ),
        (
            {
                "profit": D(-100),
                "ads_spend": D(0),
                "other_marketing": D(0),
                "gmv": D(0),
                "orders": D(0),
            },
            [],
            {
                "ads_unassigned": (D(0), None, None),
                "other_marketing": (D(0), None, None),
                "basis_gap": (D(0), D(0), D(0)),
                "rounding_allocation": (D(-100), None, None),
            },
        ),
    ],
)
def test_shop_lines_add_up(shop: dict, products: list, lines: dict) -> None:
    out = shop_lines(shop, products)
    assert {ln.key: (ln.profit, ln.gmv, ln.orders) for ln in out.lines} == lines
    assert out.gap == (D(0) if products else D(-100))
    assert out.residual == D(0)


def test_shop_lines_missing_input_is_none() -> None:
    out = shop_lines(
        {"profit": D(1), "ads_spend": None, "other_marketing": D(0), "gmv": D(1), "orders": D(1)},
        [{"profit": D(1), "ads_spend": D(0), "line_gmv": D(1), "line_orders": D(1)}],
    )
    assert out.lines[0].profit is None
    assert out.gap is None
    assert out.residual is None


# -- kol_status (owner 2026-11-15) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("profits", "samples", "commission", "state"),
    [
        (
            [D(p) for p in (95, 100, 105, 98, 102, 100, 97, 103, 99, 101)],
            D(0),
            D(100),
            KolState.effective,
        ),
        ([D(p) for p in (10, 12, 11, 9, 10, 11, 12, 10)], D(0), D(1000), KolState.not_effective),
        ([D(p) for p in (-500, 900, -400, 800)], D(0), D(200), KolState.not_enough_data),
        ([D(1_000_000)], D(0), D(10), KolState.not_enough_data),  # one order: no spread
        ([], D(500), D(0), KolState.not_enough_data),
    ],
)
def test_kol_status(
    profits: list[Decimal], samples: Decimal, commission: Decimal, state: KolState
) -> None:
    got = kol_status(profits, samples, commission)
    assert got.state is state
    if got.low is not None and got.high is not None:
        assert got.roi is not None
        assert got.low <= got.roi <= got.high


def test_kol_status_samples_count_against_the_koc() -> None:
    profits = [D(p) for p in (95, 100, 105, 98, 102, 100, 97, 103, 99, 101)]
    assert kol_status(profits, D(5000), D(100)).state is KolState.not_effective
    assert kol_status(profits, D(5000), D(100)).roi == D(-4000) / D(5100)


SHOPEE_SOURCES = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
    "ads",
    "chenh_lech_nguon",
)
# W3 decision #7: the product card, shop tab, video, LIVE and affiliate (A-34 blocks)
# W3.1: plus the residual (the total of a day without the A-34 breakdown)
TIKTOK_SOURCES = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
    "chenh_lech_nguon",
)


def test_source_availability_matrix() -> None:
    assert set(TRAFFIC_SOURCES) == set(SHOPEE_SOURCES)
    assert all(source_available(Platform.shopee, s) for s in SHOPEE_SOURCES)
    on_tiktok = {s for s in SHOPEE_SOURCES if source_available(Platform.tiktok, s)}
    assert on_tiktok == set(TIKTOK_SOURCES)


def test_unavailable_source_is_none_never_zero() -> None:
    comps = {"views": D(100), "clicks": D(10)}
    gated = gate_source(Platform.tiktok, "ads", comps)
    assert gated == {"views": None, "clicks": None}
    assert evaluate("ctr", gated).value is None
    assert evaluate("views", gated).value is None
    assert evaluate("views", gate_source(Platform.tiktok, "video", comps)).value == D(100)
    assert gate_source(Platform.shopee, "ads", comps) == comps


def test_offers_fallback_to_the_seller_lump_on_tiktok() -> None:
    assert not component_available(Platform.tiktok, "offer_promo")
    assert component_available(Platform.tiktok, "offer_seller_total")
    assert not component_available(Platform.shopee, "offer_seller_total")
    comps = {"offer_seller_total": D(120_000)}
    got = evaluate("cost_offers", resolve_components(Platform.tiktok, comps))
    assert got.value == D(120_000)
    assert evaluate("cost_offers", resolve_components(Platform.tiktok, {})).value is None


def test_offers_on_shopee_are_unchanged() -> None:
    comps = {
        "offer_promo": D(10),
        "offer_voucher": D(20),
        "offer_combo": D(30),
        "offer_seller_total": D(999),
    }
    assert resolve_components(Platform.shopee, comps) == comps
    assert evaluate("cost_offers", resolve_components(Platform.shopee, comps)).value == D(60)
    partial = {"offer_promo": D(10), "offer_seller_total": D(999)}
    assert evaluate("cost_offers", resolve_components(Platform.shopee, partial)).value is None


def test_card_return_is_its_own_metric_and_roi_keeps_one_meaning() -> None:
    from juli_backend.services.shopee_builder.engine.wire import CARD_RETURN_ID, CARD_RETURN_LABEL

    assert METRICS[CARD_RETURN_ID].label_vi == CARD_RETURN_LABEL == "ΔGMV / chi phí"
    assert METRICS["roi"].label_vi == "ROI"


def test_roi_is_net_profit_over_total_cost() -> None:
    """Decision #44 (P8): ROI = lợi nhuận ròng ÷ cost_total (giá vốn + đóng gói + phí + vận chuyển
    + QC + AFF + Ưu đãi + khác), never ÷ the marketing costs only."""
    comps = ones(
        net_revenue_known=D(1000),
        cogs=D(300),
        packaging=D(0),
        fees=D(100),
        shipping_net=D(0),
        affiliate_commission=D(50),
        ads_spend=D(200),
        other_marketing=D(0),
        offer_promo=D(40),
        offer_voucher=D(10),
        offer_combo=D(0),
        cogs_known_gmv=D(1000),
        line_gmv=D(1000),
    )
    assert evaluate("cost_total", comps).value == D(700)
    assert METRICS["roi"].formula == ("div", "profit", "cost_total")
    assert evaluate("roi", comps).value == D("0.5")

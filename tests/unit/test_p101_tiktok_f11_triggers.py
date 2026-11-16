"""F11 on TikTok: the shared trigger detector opens the optimize_product cards.

``services.forecast.triggers`` (problem / opportunity / rule, then ``rank``) is the card
trigger by default (``diag_trigger = "shared"``); TikTok's side of it is
``optimize_product.trigger_adapter``. ``metric_first`` / ``gmv_first`` stay as rollback
values. Synthetic fixtures only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.forecast import triggers
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import ProductDay, product_funnel
from juli_backend.services.optimize_product.decision_cards import (
    LEVER_CODES,
    SKIP_NO_TRIGGER,
    TRIGGER_LEVERS,
    CatalogProduct,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.trigger_adapter import (
    LeverCandidate,
    ProductInputs,
    TikTokTriggerAdapter,
    day_rows,
    shop_median_gmv,
)
from juli_backend.services.optimize_product.tunables import (
    DIAG_TRIGGER,
    TRIGGER_GMV_FIRST,
    TRIGGER_METRIC_FIRST,
    TRIGGER_SHARED,
    DiagTunables,
    validate_tunable,
)
from juli_backend.services.optimize_product.volatility import STATUS_NO_DROP

AS_OF = date(2026, 10, 6)
CONFIG = StageDiagnosisConfig()


def _series(
    *,
    ctr: float = 0.05,
    recent_ctr: float = 1.0,
    gmv_swing: float = 0.0,
    days: int = 60,
    recent_days: int = 14,
) -> list[ProductDay]:
    """``days`` rows ending ``AS_OF``: 10 000 impressions, 20 orders at 100 000 ₫ a day.

    ``recent_ctr`` scales the CTR (and so orders and GMV) over the last ``recent_days``;
    ``gmv_swing`` alternates the AOV by ±swing day to day (the mean GMV is unchanged)."""
    rows = []
    for offset in range(days):
        scale = recent_ctr if offset < recent_days else 1.0
        sign = 1 if offset % 2 else -1
        clicks = 10_000 * ctr * scale
        orders = clicks * 0.04
        aov = 100_000 * (1 + sign * gmv_swing)
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(10_000),
                clicks=Decimal(str(round(clicks))),
                sku_orders=Decimal(str(round(orders, 2))),
                items_sold=Decimal(str(round(orders, 2))),
                gmv=Decimal(str(round(orders * aov))),
            )
        )
    return sorted(rows, key=lambda r: r.day)


def _plan(daily: dict[str, list[ProductDay]], tunables: DiagTunables | None = None):
    """TikTok was asked about every product and reported a duplicate cover image."""
    funnels = [
        product_funnel(
            pid,
            f"Sản phẩm {pid} dài đủ bốn mươi ký tự cho tiêu đề",
            rows,
            as_of=AS_OF,
            config=CONFIG,
        )
        for pid, rows in sorted(daily.items())
    ]
    catalog = {f.product_id: CatalogProduct(f.product_id, f.title, "ACTIVATE") for f in funnels}
    return plan_shop_cards(
        funnels,
        catalog,
        CONFIG,
        daily=daily,
        as_of=AS_OF,
        tunables=tunables or DiagTunables(),
        tiktok_evidence={
            pid: [Evidence("MAIN_IMG_DUPLICATE", EvidenceSource.TIKTOK)] for pid in daily
        },
    )


def _shop(**extra: list[ProductDay]) -> dict[str, list[ProductDay]]:
    """Three flat products, a CTR fall of 40 % on ``fell``, plus ``extra``."""
    return {
        "flat1": _series(),
        "flat2": _series(),
        "flat3": _series(),
        "fell": _series(recent_ctr=0.6),
        **extra,
    }


# =========================================================================== the adapter


def test_rows_map_impressions_to_views_and_missing_days_stay_missing():
    rows = [
        ProductDay(
            day=AS_OF,
            impressions=Decimal(900),
            clicks=Decimal(45),
            sku_orders=Decimal(3),
            gmv=Decimal(300_000),
        ),
        # 5/10 has no row; 4/10 the product was out of stock (F2: missing, not zero).
        ProductDay(day=AS_OF - timedelta(days=2), impressions=Decimal(10), available=False),
        ProductDay(day=AS_OF - timedelta(days=3), impressions=Decimal(800), clicks=Decimal(40)),
    ]
    mapped = day_rows(rows)
    assert [r.day for r in mapped] == [AS_OF - timedelta(days=3), AS_OF]
    assert mapped[-1] == triggers.DayRow(AS_OF, views=900.0, clicks=45.0, orders=3.0, gmv=300_000.0)
    assert mapped[0].orders == 0.0 and mapped[0].views == 800.0


def test_adapter_references_levers_profit_and_forecasts():
    rows = tuple(_series(days=30))
    adapter = TikTokTriggerAdapter(
        products={
            "p": ProductInputs(
                rows=rows,
                gmv_per_day=2_000_000.0,
                gmv_window_days=14,
                candidates=(LeverCandidate("cover_image", "ctr", 0.10),),
                benchmark_gmv_per_day=2_500_000.0,
            )
        },
        levers_by_metric=TRIGGER_LEVERS,
        as_of=AS_OF,
        shop_median_gmv=1_800_000.0,
    )
    assert adapter.reference("p") == triggers.Reference(1_800_000.0, 2_500_000.0)
    # views <-> impressions in one place: the detector asks for "views".
    assert adapter.levers_for("views") == ("title",)
    assert adapter.levers_for("ctr") == ("cover_image", "title")
    assert adapter.levers_for("ctor") == (
        "description",
        "product_discount",
        "flash_sale",
        "shipping_discount",
    )
    assert adapter.levers_for("aov") == ("buy_more_save_more",)
    assert adapter.profit_per_gmv("p") is None  # F9
    assert adapter.rule_triggers() == ()
    (forecast,) = adapter.forecasts("p")
    # ΔGMV P50 over the 14-day card: 2 000 000 × 10 % × 14; Δprofit unknown.
    assert forecast.dgmv_p50 == 2_800_000.0
    assert forecast.dprofit_p50 is None and forecast.period_days == 14
    assert forecast.target_metric == "ctr" and len(forecast.gmv_history) == 14
    # Stale data (F2) has no forecast, so no opportunity.
    stale = TikTokTriggerAdapter(
        products=adapter.products,
        levers_by_metric=TRIGGER_LEVERS,
        as_of=AS_OF,
        today=AS_OF + timedelta(days=10),
    )
    assert stale.forecasts("p")[0].dgmv_p50 is None


def test_shop_median_is_over_gmv_per_observed_day():
    daily = {"a": _series(days=10), "b": _series(days=10, recent_ctr=0.5, recent_days=10)}
    daily["c"] = []  # no analytics: not counted
    assert shop_median_gmv(daily, as_of=AS_OF, window_days=60) == 1_500_000.0


# =========================================================================== the cards


def test_default_trigger_is_shared_and_rollbacks_stay_valid():
    assert DiagTunables().diag_trigger == TRIGGER_SHARED
    assert DiagTunables().shared_trigger is True and DiagTunables().metric_first is False
    for value in (TRIGGER_SHARED, TRIGGER_METRIC_FIRST, TRIGGER_GMV_FIRST):
        assert validate_tunable(DIAG_TRIGGER, value) == value
    assert DiagTunables.from_overrides({DIAG_TRIGGER: "metric_first"}).metric_first is True


def test_problem_card_comes_from_the_shared_detector():
    plan = _plan(_shop())
    fell = [p for p in plan.proposals if p.product_id == "fell"]
    assert fell, plan.skips
    for p in fell:
        assert p.target_metric == "ctr"
        assert p.card_trigger is not None
        assert p.card_trigger["trigger_type"] == triggers.PROBLEM
        assert p.card_trigger["target_metric"] == "ctr"
        assert p.card_trigger["value_basis"] == "gmv"  # F9: TikTok profit unknown
        assert p.card_trigger["reference_source"] in {"shop_median", "own_earlier"}
        assert p.card_trigger["levers"] == list(TRIGGER_LEVERS["ctr"])
        assert p.metric_trigger is None
        # value: the GMV it would win back over 30 days, about 0.8 M ₫ a day.
        assert 20e6 < p.card_trigger["value"] < 28e6
    assert {LEVER_CODES[p.lever] for p in fell} == {"cover_image"}
    assert "nguyên nhân chính: CTR giảm 40 %" in fell[0].reason
    payload = fell[0].diagnosis_payload(as_of=AS_OF.isoformat(), medians=plan.medians)
    assert payload["card_trigger"]["trigger_type"] == triggers.PROBLEM


def test_opportunity_cards_only_beyond_the_band():
    # ``noisy`` swings its GMV ±90 % day to day: no fall, and no lever clears its band.
    plan = _plan(_shop(noisy=_series(gmv_swing=0.9)))
    by_product: dict[str, list] = {}
    for p in plan.proposals:
        by_product.setdefault(p.product_id, []).append(p)
    flat = by_product.get("flat1", [])
    assert flat, plan.skips
    for p in flat:
        assert p.card_trigger["trigger_type"] == triggers.OPPORTUNITY
        assert p.card_trigger["reference_source"] == "forecast"
        assert p.card_trigger["levers"] == [LEVER_CODES[p.lever]]  # one lever each
        assert p.card_trigger["value"] > 0
        assert p.reason.startswith("Nếu cải thiện")
    assert "noisy" not in by_product
    assert ("noisy", SKIP_NO_TRIGGER) in {(s.product_id, s.reason) for s in plan.skips}


def test_band_gate_on_the_adapter_forecasts():
    flat = tuple(_series(days=30))
    noisy = tuple(_series(days=30, gmv_swing=0.9))
    adapter = TikTokTriggerAdapter(
        products={
            pid: ProductInputs(
                rows=rows,
                gmv_per_day=2_000_000.0,
                gmv_window_days=14,
                candidates=(LeverCandidate("cover_image", "ctr", 0.10),),
            )
            for pid, rows in (("flat", flat), ("noisy", noisy))
        },
        levers_by_metric=TRIGGER_LEVERS,
        as_of=AS_OF,
    )
    assert triggers.clears_band(adapter.forecasts("flat")[0], profit_known=False) is True
    assert triggers.clears_band(adapter.forecasts("noisy")[0], profit_known=False) is False
    found = triggers.detect(adapter.series(), adapter, as_of=AS_OF)
    assert [(t.trigger_type, t.product_id, t.levers) for t in found] == [
        (triggers.OPPORTUNITY, "flat", ("cover_image",))
    ]


def test_no_problem_and_no_opportunity_is_skipped_with_a_reason():
    plan = _plan({"noisy": _series(gmv_swing=0.9)})
    assert plan.proposals == []
    assert [(s.product_id, s.reason) for s in plan.skips] == [("noisy", SKIP_NO_TRIGGER)]


def test_cards_follow_the_rank_problem_first_at_this_value():
    plan = _plan(_shop())
    ranks = [p.card_trigger["rank"] for p in plan.proposals if p.status == "rule"]
    assert ranks == sorted(ranks)
    first = next(p for p in plan.proposals if p.status == "rule")
    assert first.product_id == "fell"
    assert first.card_trigger["trigger_type"] == triggers.PROBLEM


def test_ranking_rules_by_urgency_then_problem_at_similar_value_then_value():
    adapter = TikTokTriggerAdapter(
        products={},
        levers_by_metric=TRIGGER_LEVERS,
        as_of=AS_OF,
        rules=(
            triggers.RuleTrigger("stock", "a", urgency=1.0),
            triggers.RuleTrigger("stock", "b", urgency=5.0),
        ),
    )
    rules = triggers.detect([], adapter, as_of=AS_OF)
    problem = triggers.Trigger(triggers.PROBLEM, "p", "ctr", 95.0, "gmv")
    opp_close = triggers.Trigger(triggers.OPPORTUNITY, "o1", "ctr", 100.0, "gmv")
    opp_big = triggers.Trigger(triggers.OPPORTUNITY, "o2", "ctr", 200.0, "gmv")
    ranked = triggers.rank([opp_close, *rules, problem, opp_big])
    assert [(t.trigger_type, t.product_id) for t in ranked] == [
        (triggers.RULE, "b"),
        (triggers.RULE, "a"),
        (triggers.OPPORTUNITY, "o2"),  # twice the value: value decides
        (triggers.PROBLEM, "p"),  # 95 % of the opportunity's value: the problem first
        (triggers.OPPORTUNITY, "o1"),
    ]


# =========================================================================== rollback modes


def test_metric_first_rollback_is_unchanged():
    plan = _plan(_shop(), DiagTunables(diag_trigger=TRIGGER_METRIC_FIRST))
    products = {p.product_id for p in plan.proposals}
    assert products == {"fell"}  # flat products get no growth card in D39.1
    for p in plan.proposals:
        assert p.card_trigger is None
        assert p.metric_trigger is not None and p.target_metric == "ctr"
    assert {s.reason for s in plan.skips if s.product_id.startswith("flat")} == {
        "d39:no_metric_drop"
    }


def test_gmv_first_rollback_is_unchanged():
    plan = _plan(_shop(), DiagTunables(diag_trigger=TRIGGER_GMV_FIRST))
    assert {p.product_id for p in plan.proposals} == {"fell"}
    for p in plan.proposals:
        assert p.card_trigger is None and p.metric_trigger is None
        assert p.target_metric == "ctr" and p.reason.startswith("GMV mỗi ngày giảm 40 %")
    assert {s.reason for s in plan.skips if s.product_id.startswith("flat")} == {
        f"d29:{STATUS_NO_DROP}"
    }


# =========================================================================== F2 amendment 2


def _thin(orders_every: int, *, recent_aov: float) -> triggers.ProductSeries:
    """120 daily rows; one order every ``orders_every`` days (0 = never); the last 60 days
    at ``recent_aov`` (the 60 before at 100 000 ₫)."""
    rows = []
    for offset in range(120):
        day = AS_OF - timedelta(days=offset)
        orders = 1.0 if orders_every and offset % orders_every == 0 else 0.0
        aov = recent_aov if offset < 60 else 100_000.0
        rows.append(triggers.DayRow(day, views=100.0, clicks=10.0, orders=orders, gmv=orders * aov))
    return triggers.ProductSeries("thin", tuple(sorted(rows, key=lambda r: r.day)))


def test_few_events_still_use_the_60_day_window():
    """Owner F2 amendment 2: 20 orders in 60 days (< 30) -> the 60-day window anyway."""
    adapter = TikTokTriggerAdapter(products={}, levers_by_metric=TRIGGER_LEVERS, as_of=AS_OF)
    found = triggers.detect_problem(
        _thin(3, recent_aov=50_000.0), triggers.Reference(), adapter, as_of=AS_OF
    )
    assert found is not None
    assert found.detail["window_days"] == 60
    assert found.target_metric == "aov"
    assert found.levers == ("buy_more_save_more",)


def test_zero_events_is_low_data_and_no_problem():
    adapter = TikTokTriggerAdapter(products={}, levers_by_metric=TRIGGER_LEVERS, as_of=AS_OF)
    found = triggers.detect_problem(
        _thin(0, recent_aov=50_000.0), triggers.Reference(shop_median=1.0), adapter, as_of=AS_OF
    )
    assert found is None

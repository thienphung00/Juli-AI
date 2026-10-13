"""D39.1 (N1A, fast track P30): the metric-first trigger.

A card opens when ANY funnel metric (Lượt hiển thị, CTR, CTOR, AOV) falls beyond its
own band on its channel, even when GMV holds; candidates rank on the GMV that metric
alone costs (the D29.2 decomposition). ``diag_trigger = "gmv_first"`` keeps the old
GMV gate per shop. Synthetic fixtures only.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import ProductDay, product_funnel
from juli_backend.services.optimize_product.decision_cards import (
    CatalogProduct,
    metric_first_reason,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.metric_trigger import (
    GMV_FELL,
    GMV_HELD,
    growth_candidates,
    metric_trigger,
)
from juli_backend.services.optimize_product.tunables import (
    DIAG_TRIGGER,
    TUNABLE_KEYS,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.optimize_product.volatility import assess_product

AS_OF = date(2026, 10, 6)
CONFIG = StageDiagnosisConfig()
METRIC_FIRST = DiagTunables()
GMV_FIRST = DiagTunables(diag_trigger="gmv_first")

#: Words the seller copy must never carry.
JARGON = ("band", "dao động gộp", "CV", "window", "D29", "D39", "GMV", "tunable", "%s")


def _series(
    *,
    impressions: float = 10_000,
    ctr: float = 0.05,
    ctor: float = 0.04,
    aov: float = 100_000,
    recent: dict[str, float] | None = None,
    days: int = 60,
    recent_days: int = 14,
    noise: float = 0.03,
    seed: int = 0,
) -> list[ProductDay]:
    """``days`` daily rows ending ``AS_OF``; the last ``recent_days`` scale by ``recent``.

    The day-to-day wobble alternates by day (±``noise``), so every 14-day window has
    the same mean wobble: "GMV flat" is flat, not flat-plus-luck. ``seed`` shifts it.
    """
    rows = []
    for offset in range(days):
        scale = {"impressions": 1.0, "ctr": 1.0, "ctor": 1.0, "aov": 1.0}
        if recent and offset < recent_days:
            scale.update(recent)
        sign = 1 if (offset + seed) % 2 else -1
        imp = impressions * scale["impressions"] * (1 + sign * noise)
        clicks = imp * ctr * scale["ctr"]
        orders = clicks * ctor * scale["ctor"] * (1 - sign * noise)
        gmv = orders * aov * scale["aov"]
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(str(round(imp))),
                clicks=Decimal(str(round(clicks))),
                sku_orders=Decimal(str(round(orders, 2))),
                items_sold=Decimal(str(round(orders, 2))),
                gmv=Decimal(str(round(gmv))),
            )
        )
    return sorted(rows, key=lambda r: r.day)


def _plan(daily: dict[str, list[ProductDay]], tunables: DiagTunables = METRIC_FIRST, **kwargs):
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
        tunables=tunables,
        tiktok_evidence={
            pid: [Evidence("MAIN_IMG_DUPLICATE", EvidenceSource.TIKTOK)] for pid in daily
        },
        **kwargs,
    )


#: CTOR −20 %, impressions +25 %: GMV/day flat (1.25 × 0.8 = 1).
HELD = {"impressions": 1.25, "ctor": 0.8}


# =========================================================================== the trigger


def test_ctor_drop_with_gmv_held_is_a_candidate():
    rows = _series(recent=HELD)
    assessment = assess_product("p", rows, as_of=AS_OF, tunables=METRIC_FIRST)
    # D29.2's gate sees no GMV fall ...
    assert assessment.status == "no_gmv_drop"
    trigger = metric_trigger(rows, as_of=AS_OF, tunables=METRIC_FIRST, assessment=assessment)
    # ... D39.1 sees the CTOR fall beyond its band, and GMV held by impressions.
    assert [d.metric for d in trigger.drops] == ["ctor"]
    drop = trigger.target
    assert drop is not None and drop.channel == "total"
    assert drop.drop_pct == pytest.approx(20, abs=2)
    assert drop.drop_pct > drop.band_pct
    assert trigger.gmv == GMV_HELD
    assert trigger.held_by == "impressions"
    # What the fall alone costs: GMV now × (e^(−c) − 1), c = ln(CTOR now / before).
    assert drop.contribution == pytest.approx(math.log(drop.current / drop.earlier))
    assert drop.gmv_cost_per_day == pytest.approx(
        drop.gmv_per_day * (math.exp(-drop.contribution) - 1)
    )
    assert drop.gmv_cost_per_day == pytest.approx(0.25 * drop.gmv_per_day, rel=0.1)


def test_noise_is_not_a_drop():
    rows = _series()
    assessment = assess_product("p", rows, as_of=AS_OF, tunables=METRIC_FIRST)
    trigger = metric_trigger(rows, as_of=AS_OF, tunables=METRIC_FIRST, assessment=assessment)
    assert trigger.drops == ()


def test_a_low_data_metric_never_triggers():
    # 2 orders a day: CTOR / AOV never reach 30 orders in 14 days... but do in 30/60,
    # so lift the minimum beyond what the longest window holds.
    rows = _series(impressions=1000, ctor=0.04, recent={"ctor": 0.5})
    strict = DiagTunables(min_events=1000)
    assessment = assess_product("p", rows, as_of=AS_OF, tunables=strict)
    assert assessment.metrics["ctor"].low_data
    trigger = metric_trigger(rows, as_of=AS_OF, tunables=strict, assessment=assessment)
    assert "ctor" not in {d.metric for d in trigger.drops}


# =========================================================================== the plan


def test_ctor_card_with_gmv_held_is_proposed_and_ranked_by_its_gmv_cost():
    daily = {
        # The bigger seller: CTOR −20 %, impressions +25 %, GMV flat.
        "best": _series(impressions=20_000, recent=HELD, seed=1),
        # A smaller product: the same CTOR fall with GMV falling too.
        "small": _series(impressions=5_000, recent={"ctor": 0.8}, seed=2),
        # A product whose numbers hold: no card.
        "flat": _series(impressions=8_000, seed=3),
    }
    plan = _plan(daily, discount_cap_set=True)
    proposed = [p.product_id for p in plan.proposals]
    assert "flat" not in proposed
    assert {s.product_id: s.reason for s in plan.skips}["flat"] == "d39:no_metric_drop"
    best = next(p for p in plan.proposals if p.product_id == "best")
    small = next(p for p in plan.proposals if p.product_id == "small")
    assert best.target_metric == small.target_metric == "ctor"
    # Ranked by the GMV the CTOR fall alone costs (× the neutral lever factors).
    best_cost = best.metric_trigger.target.gmv_cost_per_day
    small_cost = small.metric_trigger.target.gmv_cost_per_day
    assert best_cost > small_cost
    assert proposed.index("best") < proposed.index("small")
    expected = Decimal(str(round(best_cost, 4))) * Decimal(str(best.prediction.factor))
    assert best.d29_ranking_value / expected == pytest.approx(Decimal(1), rel=Decimal("1e-6"))
    # Seller copy: which metric fell, and that GMV held thanks to impressions.
    assert best.reason.startswith("CTOR giảm 2")
    assert "nhưng doanh thu được giữ nhờ lượt hiển thị tăng" in best.reason
    assert "nếu cải thiện CTOR, doanh thu có thể tăng thêm khoảng" in best.reason
    assert best.reason.endswith("₫/tháng")
    assert "kéo doanh thu giảm" in small.reason
    for word in JARGON:
        assert word not in best.reason
    # Ops sees the trigger in the payload's diagnosis (not in the seller allowlist).
    payload = best.diagnosis_payload(as_of=AS_OF.isoformat(), medians=plan.medians)
    assert payload["metric_trigger"]["drops"][0]["metric"] == "ctor"
    assert payload["metric_trigger"]["gmv"] == GMV_HELD


def test_gmv_first_reproduces_the_old_gate():
    daily = {
        "best": _series(impressions=20_000, recent=HELD, seed=1),
        "small": _series(impressions=5_000, recent={"ctor": 0.8}, seed=2),
    }
    plan = _plan(daily, tunables=GMV_FIRST, discount_cap_set=True)
    # GMV held on "best": no card, the D29 reason.
    assert {s.product_id: s.reason for s in plan.skips}["best"] == "d29:no_gmv_drop"
    [small] = [p for p in plan.proposals if p.product_id == "small"]
    assert small.metric_trigger is None
    assert small.reason.startswith("GMV mỗi ngày giảm")
    # Ranked on the recoverable-to-target GMV, as D29 did.
    expected = small.recoverable_gmv_per_day * Decimal(str(small.prediction.factor))
    assert small.d29_ranking_value / expected == pytest.approx(Decimal(1), rel=Decimal("1e-6"))
    assert "metric_trigger" not in small.diagnosis_payload(
        as_of=AS_OF.isoformat(), medians=plan.medians
    )


def test_one_metric_per_product_the_costliest():
    # CTR −30 % and CTOR −20 % on one product: one target metric, the costlier fall.
    rows = _series(recent={"ctr": 0.7, "ctor": 0.8})
    assessment = assess_product("p", rows, as_of=AS_OF, tunables=METRIC_FIRST)
    trigger = metric_trigger(rows, as_of=AS_OF, tunables=METRIC_FIRST, assessment=assessment)
    assert [d.metric for d in trigger.drops] == ["ctr", "ctor"]
    assert trigger.gmv == GMV_FELL
    plan = _plan({"p": rows}, discount_cap_set=True)
    assert {p.target_metric for p in plan.proposals} == {"ctr"}


def test_copy_variants_are_plain_vietnamese():
    rows = _series(recent=HELD)
    assessment = assess_product("p", rows, as_of=AS_OF, tunables=METRIC_FIRST)
    trigger = metric_trigger(rows, as_of=AS_OF, tunables=METRIC_FIRST, assessment=assessment)
    text = metric_first_reason(trigger.target, trigger)
    assert text.startswith("CTOR giảm 2") and " so với 14 ngày trước nhưng " in text
    monthly = round(trigger.target.gmv_cost_per_day * 30 / 1000) * 1000
    assert f"khoảng {monthly:,} ₫/tháng".replace(",", ".") in text


def test_growth_branch_is_a_seam_with_no_proposals():
    assert growth_candidates(skips=[], as_of=AS_OF) == []


# =========================================================================== the tunable


def test_diag_trigger_tunable_defaults_to_metric_first():
    assert DIAG_TRIGGER in TUNABLE_KEYS
    assert DiagTunables().diag_trigger == "metric_first"
    assert DiagTunables().metric_first is True
    assert DiagTunables.from_overrides({DIAG_TRIGGER: "gmv_first"}).metric_first is False
    # An invalid stored value is ignored (defaults kept).
    assert DiagTunables.from_overrides({DIAG_TRIGGER: "other"}).diag_trigger == "metric_first"
    assert validate_tunable(DIAG_TRIGGER, "gmv_first") == "gmv_first"
    with pytest.raises(TunableError):
        validate_tunable(DIAG_TRIGGER, "both")
    assert DiagTunables().to_json()[DIAG_TRIGGER] == "metric_first"

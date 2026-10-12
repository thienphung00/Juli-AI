"""Fast track P23: volatility-aware diagnosis and KPI (D29), Quality Score and
Performance Prediction (D30.2–3).

One test (or a small group) per rule: adaptive window, GMV-first trigger,
decomposition, reference, per-lever chains + one-metric rule + slots,
stable-first order, confidence, KPI clamps (point / range), verdicts with their
boundaries, guard-band defaults, the Ops tunables (read, PUT, Admin-only,
audit), Quality Score parts, prediction shrinkage; and a Fujiwa-like shop (few
products, high volatility).
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.core.security import get_current_user
from juli_backend.models.models import ActionCard, Product, User
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    emit_optimize_product_cards,
    plan_optimize_product_cards,
)
from juli_backend.services.action_cards.persist import SUPPRESSED_REASON_OTHER_METRIC_ACTIVE
from juli_backend.services.action_cards.subjects import (
    SUBJECT_TYPE_PRODUCT_LEVER,
    subject_product_ref,
)
from juli_backend.services.lever_flows.measurement import (
    VERDICT_MET,
    VERDICT_NOT_MET,
    VERDICT_PARTIAL,
    VERDICT_RISING,
    VERDICT_UNCLEAR,
    day7_verdict,
    day14_verdict,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import ProductDay, product_funnel
from juli_backend.services.optimize_product.decision_cards import (
    CatalogProduct,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.diagnosis import Branch
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.prediction import (
    MIN_SHOP_RESULTS,
    CalibrationStats,
    blended_factor,
    gmv_range_per_month,
    predict,
)
from juli_backend.services.optimize_product.quality_score import (
    ListingFacts,
    lever_weight,
    quality_score,
    risky_claims,
)
from juli_backend.services.optimize_product.tunables import (
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.optimize_product.volatility import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    STATUS_CANDIDATE,
    STATUS_LOW_DATA,
    STATUS_NO_DROP,
    assess_product,
    confidence,
    decompose,
    kpi_target,
    pick_target,
    reference_for,
    select_window,
    window_counts,
)
from juli_backend.services.run_changes.default_bands import default_bands, effective_bands
from juli_backend.services.shop_rules.diag_tunables import diag_tunables, set_tunable_overrides
from tests.support.api import build_app, client_for
from tests.support.builders import make_tenant, make_user

AS_OF = date(2026, 10, 6)
CONFIG = StageDiagnosisConfig()
TUNABLES = DiagTunables()


def _series(
    days: int,
    *,
    impressions: float = 4000,
    ctr: float = 0.05,
    ctor: float = 0.05,
    aov: float = 200_000,
    noise: float = 0.0,
    seed: int = 1,
    change: dict | None = None,
    change_days: int = 14,
) -> list[ProductDay]:
    """``days`` daily rows ending ``AS_OF``; the last ``change_days`` use ``change`` rates."""
    rng = random.Random(seed)
    rows: list[ProductDay] = []
    for offset in range(days):
        rates = {"impressions": impressions, "ctr": ctr, "ctor": ctor, "aov": aov}
        if change and offset < change_days:
            rates.update(change)
        jitter = (lambda: 1 + rng.uniform(-noise, noise)) if noise else (lambda: 1.0)
        imp = rates["impressions"] * jitter()
        clicks = imp * rates["ctr"] * jitter()
        orders = clicks * rates["ctor"] * jitter()
        gmv = orders * rates["aov"]
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


# =========================================================================== D29.1 window


def test_adaptive_window_is_the_shortest_with_enough_events():
    # ~4 orders a day: 14 days hold ≥ 30 orders.
    busy = _series(60, impressions=1600, ctr=0.05, ctor=0.05)
    assert select_window(busy, AS_OF, "ctor", TUNABLES).window_days == 14
    # ~1.2 orders a day: 14 days = 17 orders, 30 days = 36 -> 30.
    slow = _series(60, impressions=1600, ctr=0.05, ctor=0.015)
    window = select_window(slow, AS_OF, "ctor", TUNABLES)
    assert window.window_days == 30 and not window.low_data
    # ~0.3 orders a day: even 60 days < 30 -> "ít dữ liệu", no diagnosis.
    thin = _series(60, impressions=400, ctr=0.05, ctor=0.015)
    thin_window = select_window(thin, AS_OF, "ctor", TUNABLES)
    assert thin_window.low_data and thin_window.window_days == 60
    # CTR counts clicks, so it is not low-data on the same product.
    assert not select_window(thin, AS_OF, "ctr", TUNABLES).low_data
    # Hiển thị is never low-data.
    assert not select_window(thin, AS_OF, "impressions", TUNABLES).low_data


def test_window_tunables_change_the_choice():
    slow = _series(60, impressions=1600, ctr=0.05, ctor=0.015)
    lenient = DiagTunables(min_events=10)
    assert select_window(slow, AS_OF, "ctor", lenient).window_days == 14


# =========================================================================== D29.2 trigger


def test_gmv_first_trigger_needs_a_real_drop_beyond_the_band():
    flat = _series(60, noise=0.2, seed=3)
    assert assess_product("p", flat, as_of=AS_OF, tunables=TUNABLES).status == STATUS_NO_DROP
    # A 40 % CTOR fall over the last 14 days: GMV falls well beyond its band.
    fallen = _series(60, noise=0.2, seed=3, change={"ctor": 0.03})
    assessed = assess_product("p", fallen, as_of=AS_OF, tunables=TUNABLES)
    assert assessed.status == STATUS_CANDIDATE
    assert assessed.gmv_drop is not None and assessed.gmv_drop > assessed.gmv_band_abs
    # A dip inside the noise is not a candidate.
    dip = _series(60, noise=0.6, seed=4, change={"ctor": 0.048})
    assert assess_product("p", dip, as_of=AS_OF, tunables=TUNABLES).status != STATUS_CANDIDATE


def test_low_data_product_gets_no_diagnosis():
    thin = _series(60, impressions=300, ctr=0.05, ctor=0.01, change={"ctor": 0.005})
    assert assess_product("p", thin, as_of=AS_OF, tunables=TUNABLES).status == STATUS_LOW_DATA


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"ctr": 0.03}, "ctr"),
        ({"ctor": 0.03}, "ctor"),
        ({"aov": 120_000}, "aov"),
        ({"impressions": 2400}, "impressions"),
    ],
)
def test_decomposition_picks_the_metric_that_explains_the_fall(change, expected):
    rows = _series(60, noise=0.05, seed=7, change=change)
    assessed = assess_product("p", rows, as_of=AS_OF, tunables=TUNABLES)
    assert assessed.status == STATUS_CANDIDATE
    assert assessed.target_metric == expected
    # The log-contributions add up to the GMV log-ratio.
    now = window_counts(rows, AS_OF, assessed.window_days)
    before = window_counts(rows, AS_OF, assessed.window_days, offset=assessed.window_days)
    total = math.log(now.value("gmv") / before.value("gmv"))
    assert sum(decompose(now, before).values()) == pytest.approx(total, abs=1e-6)


def test_a_low_data_metric_is_never_the_target():
    assert pick_target({"ctor": -0.5, "ctr": -0.2}, ["ctor"]) == "ctr"
    assert pick_target({"ctor": -0.5}, ["ctor"]) is None
    assert pick_target({"ctr": 0.1}, []) is None


# =========================================================================== D29.3 reference


def test_reference_is_the_highest_of_median_own_level_and_benchmark():
    assert reference_for("ctr", shop_median=0.05, earlier=0.04) == (0.05, "shop_median")
    assert reference_for("ctr", shop_median=0.03, earlier=0.04) == (0.04, "own_earlier")
    assert reference_for("ctr", shop_median=0.03, earlier=0.04, benchmark=0.06) == (
        0.06,
        "category_benchmark",
    )
    assert reference_for("ctr", shop_median=None, earlier=None) == (None, None)


# =========================================================================== D29.5/6


def test_confidence_from_events_and_cv():
    assert confidence(events=200, cv=0.05, low_data=False, tunables=TUNABLES) == CONFIDENCE_HIGH
    assert confidence(events=60, cv=0.05, low_data=False, tunables=TUNABLES) == CONFIDENCE_MEDIUM
    assert confidence(events=200, cv=0.2, low_data=False, tunables=TUNABLES) == CONFIDENCE_MEDIUM
    assert confidence(events=200, cv=0.31, low_data=False, tunables=TUNABLES) == CONFIDENCE_LOW
    assert confidence(events=200, cv=0.05, low_data=True, tunables=TUNABLES) == CONFIDENCE_LOW
    # Boundary: exactly volatile_cv is still "medium"; the tunable moves it.
    assert confidence(events=200, cv=0.30, low_data=False, tunables=TUNABLES) == CONFIDENCE_MEDIUM
    strict = DiagTunables(volatile_cv=0.2)
    assert confidence(events=200, cv=0.25, low_data=False, tunables=strict) == CONFIDENCE_LOW


def _plan(daily: dict[str, list[ProductDay]], **kwargs):
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
    return plan_shop_cards(funnels, catalog, CONFIG, daily=daily, as_of=AS_OF, **kwargs)


def test_stable_products_rank_first():
    daily = {
        # Volatile but a bigger fall.
        "volatile": _series(60, impressions=8000, noise=0.7, seed=11, change={"ctor": 0.012}),
        # Stable, smaller.
        "stable": _series(60, impressions=3000, noise=0.03, seed=12, change={"ctor": 0.035}),
    }
    plan = _plan(daily)
    order = [p.product_id for p in plan.proposals]
    assert order.index("stable") < order.index("volatile")
    by_id = {p.product_id: p for p in plan.proposals}
    assert by_id["stable"].assessment.stability == "stable"
    assert by_id["volatile"].assessment.stability == "volatile"
    assert by_id["volatile"].confidence == CONFIDENCE_LOW


# =========================================================================== D29.7/10 KPI


def test_kpi_target_is_the_reference_clamped_to_one_to_three_bands():
    common = dict(metric="ctr", current=0.04, band_pct=5.0, window_days=14, tunables=TUNABLES)
    inside = kpi_target(reference=0.0446, volatile=False, **common)
    assert inside.target == pytest.approx(0.0446)
    assert (inside.target_min, inside.target_max) == (pytest.approx(0.042), pytest.approx(0.046))
    assert inside.display == "point" and not inside.day14_only
    low = kpi_target(reference=0.0405, volatile=False, **common)
    assert low.target == pytest.approx(0.042)  # below 1 band cannot be measured
    high = kpi_target(reference=0.06, volatile=False, **common)
    assert high.target == pytest.approx(0.046)  # above 3 bands over-promises
    volatile = kpi_target(reference=0.06, volatile=True, **common)
    assert volatile.display == "range" and volatile.day14_only
    # Tunable multipliers.
    wide = kpi_target(
        reference=0.06, volatile=False, **{**common, "tunables": DiagTunables(kpi_max_band_mult=5)}
    )
    assert wide.target == pytest.approx(0.05)
    # The prediction narrows the range when it overlaps, never widens it.
    narrowed = kpi_target(reference=0.06, volatile=True, predicted=(0.041, 0.044), **common)
    assert (narrowed.target_min, narrowed.target_max) == (
        pytest.approx(0.042),
        pytest.approx(0.044),
    )
    apart = kpi_target(reference=0.06, volatile=True, predicted=(0.05, 0.06), **common)
    assert apart.target_max == pytest.approx(0.046)


# =========================================================================== D29.8 verdicts


@pytest.mark.parametrize(
    ("pre", "post", "pre_gmv", "post_gmv", "expected"),
    [
        (Decimal("0.040"), Decimal("0.0421"), 100, 100, VERDICT_RISING),  # +5.25 % > 5 %
        (Decimal("0.040"), Decimal("0.0420"), 100, 100, VERDICT_UNCLEAR),  # exactly 1 band
        (Decimal("0.040"), Decimal("0.0450"), 100, 80, VERDICT_UNCLEAR),  # GMV fell 20 % > 10 %
        (Decimal("0.040"), Decimal("0.0450"), 100, 90, VERDICT_RISING),  # GMV fell exactly 10 %
    ],
)
def test_day7_verdict_boundaries(pre, post, pre_gmv, post_gmv, expected):
    assert (
        day7_verdict(
            pre_value=pre,
            post_value=post,
            band_pct=Decimal(5),
            pre_gmv=Decimal(pre_gmv),
            post_gmv=Decimal(post_gmv),
            gmv_band_pct=Decimal(10),
        )
        == expected
    )


@pytest.mark.parametrize(
    ("post", "post_gmv", "expected"),
    [
        (Decimal("0.046"), 100, VERDICT_MET),  # moved, at target, GMV held
        (Decimal("0.043"), 100, VERDICT_PARTIAL),  # moved, below the target
        (Decimal("0.046"), 70, VERDICT_PARTIAL),  # moved and reached, GMV fell
        (Decimal("0.041"), 100, VERDICT_NOT_MET),  # within the band
    ],
)
def test_day14_verdicts(post, post_gmv, expected):
    assert (
        day14_verdict(
            pre_value=Decimal("0.040"),
            post_value=post,
            band_pct=Decimal(5),
            target=Decimal("0.045"),
            pre_gmv=Decimal(100),
            post_gmv=Decimal(post_gmv),
            gmv_band_pct=Decimal(10),
        )
        == expected
    )
    assert (
        day14_verdict(
            pre_value=None,
            post_value=post,
            band_pct=Decimal(5),
            target=None,
            pre_gmv=None,
            post_gmv=None,
            gmv_band_pct=None,
        )
        is None
    )


# =========================================================================== D29.9 guard


def test_guard_default_is_the_window_mean_band_and_the_seller_wins():
    values = [100, 120, 80, 110, 90, 105, 95, 100, 115, 85, 100, 102, 98, 100]
    bands = default_bands({"impressions": values, "ctr": [None, None]})
    assert set(bands) == {"impressions"}
    import statistics

    expected = 1.2816 * statistics.stdev(values) / math.sqrt(len(values)) / statistics.fmean(values)
    assert float(bands["impressions"]) == pytest.approx(expected * 100, abs=0.01)
    doubled = default_bands({"impressions": values}, guard_band_mult=2)
    assert float(doubled["impressions"]) == pytest.approx(2 * expected * 100, abs=0.02)
    merged = effective_bands({"impressions": Decimal(3)}, {**bands, "gmv": Decimal(7)})
    assert merged["impressions"] == (Decimal(3), "seller")
    assert merged["gmv"] == (Decimal(7), "default")


# =========================================================================== D30.2 QS


def test_quality_score_parts_and_lever_weight():
    tiktok = [
        Evidence("MAIN_IMG_NUMBER_LESS_THAN_FIVE", EvidenceSource.TIKTOK),
        Evidence("MAIN_IMG_DUPLICATE", EvidenceSource.TIKTOK),
    ]
    facts = ListingFacts(
        title="Trà thảo mộc chữa bệnh dạ dày",  # 29 chars, a health claim
        category="Thực phẩm & Đồ uống",
        seo_words=["trà thảo mộc", "trà giảm cân"],
        tiktok_asked=True,
    )
    qs = quality_score(facts, tiktok)
    assert qs.parts["title"] == round(100 * 29 / 40)
    assert qs.parts["search_fit"] == 50
    assert qs.parts["image"] == 40  # two image codes
    assert qs.parts["description"] == 100  # asked, no description code
    assert qs.parts["compliance"] == 50
    assert qs.parts["video"] is None and qs.parts["attributes"] is None
    assert "risky_claim:chữa bệnh" in qs.issues
    assert 0 < qs.score < 100
    # The weak image part lifts the cover-image lever most.
    assert lever_weight(qs, "cover_image") == pytest.approx(1.3)
    assert lever_weight(qs, "description") == 1.0
    assert lever_weight(qs, "product_discount") == 1.0
    assert lever_weight(None, "title") == 1.0
    # Unknown parts are left out, not scored as 0.
    bare = quality_score(ListingFacts(title="x" * 60))
    assert bare.parts["image"] is None and bare.score == 100
    # Health claims only for food / beverage; absolute claims everywhere.
    assert risky_claims("Kem chữa bệnh da", "Làm đẹp") == []
    assert risky_claims("Rẻ nhất thị trường", "Làm đẹp") == ["rẻ nhất"]


# =========================================================================== D30.3 prediction


def test_prediction_shrinkage_shop_fleet_prior():
    assert blended_factor(None, None) == (1.0, "prior")
    # Fleet: 5 results at coefficient 1.0 (factor 2) -> halfway to 2.
    fleet = CalibrationStats(coefficient=1.0, results=5)
    assert blended_factor(None, fleet) == (pytest.approx(1.5), "fleet")
    # A shop under MIN_SHOP_RESULTS does not count yet.
    few = CalibrationStats(coefficient=0.125, results=MIN_SHOP_RESULTS - 1)
    assert blended_factor(few, fleet) == (pytest.approx(1.5), "fleet")
    # Enough shop results: blended from the fleet factor toward the shop's (0.25).
    shop = CalibrationStats(coefficient=0.125, results=MIN_SHOP_RESULTS)
    factor, source = blended_factor(shop, fleet)
    assert source == "shop" and factor == pytest.approx(1.5 + 0.5 * (0.25 - 1.5))
    prediction = predict("cover_image", 80, shop=shop, fleet=fleet)
    assert prediction.gap_bucket == "large"
    assert prediction.lift_low == pytest.approx(0.08 * factor)
    assert prediction.lift_high == pytest.approx(0.25 * factor)
    assert gmv_range_per_month(1_000_000, 0.04, 0.042, 0.046) == (
        pytest.approx(1_500_000),
        pytest.approx(4_500_000),
    )


# =========================================================================== D29.11 tunables


def test_tunables_validate_and_fall_back():
    with pytest.raises(TunableError):
        validate_tunable("volatile_cv", 30)  # a percent, not a fraction
    with pytest.raises(TunableError):
        validate_tunable("diag_windows", [5])
    loaded = DiagTunables.from_overrides(
        {"diag_windows": [30, 14], "volatile_cv": 9, "kpi_max_band_mult": 0.5}
    )
    assert loaded.windows == (14, 30)
    assert loaded.volatile_cv == 0.30  # invalid stored value ignored
    assert loaded.kpi_max_band_mult == loaded.kpi_min_band_mult  # never below min


async def test_tunables_are_read_by_the_algorithm(session):
    _, shop = await make_tenant(session)
    assert await diag_tunables(session, shop.id) == DiagTunables()
    await set_tunable_overrides(session, shop.id, {"diag_min_events": 50, "volatile_cv": 0.4})
    loaded = await diag_tunables(session, shop.id)
    assert loaded.min_events == 50 and loaded.volatile_cv == 0.4
    await set_tunable_overrides(session, shop.id, {"diag_min_events": None, "volatile_cv": None})
    assert await diag_tunables(session, shop.id) == DiagTunables()


@pytest.fixture
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def _staff_client(session, role: str):
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app), email


async def test_ops_settings_expose_put_and_audit_the_tunables(session, bypass_access):
    _, shop = await make_tenant(session)
    shop_id = shop.id
    url = f"/v1/ops/shops/{shop_id}/settings"
    operator, _ = await _staff_client(session, "operator")
    async with operator as client:
        got = (await client.get(url)).json()["settings"]
        assert got["defaults"]["diag_windows"] == [14, 30, 60]
        assert got["defaults"]["diag_min_events"] == 30
        assert got["defaults"]["kpi_min_band_mult"] == 1.0
        assert got["defaults"]["kpi_max_band_mult"] == 3.0
        assert got["defaults"]["guard_band_mult"] == 1.0
        assert got["defaults"]["volatile_cv"] == 0.3
        assert got["overrides"]["volatile_cv"] is None
        # Admin-only.
        denied = await client.put(url, json={"changes": {"volatile_cv": 0.4}})
        assert denied.status_code == 403
    admin, admin_email = await _staff_client(session, "admin")
    async with admin as client:
        put = await client.put(
            url, json={"changes": {"volatile_cv": 0.4, "diag_windows": [30, 60]}}
        )
        assert put.status_code == 200, put.text
        overrides = put.json()["settings"]["overrides"]
        assert overrides["volatile_cv"] == 0.4 and overrides["diag_windows"] == [30, 60]
        bad = await client.put(url, json={"changes": {"kpi_min_band_mult": 0}})
        assert bad.status_code == 422
        inverted = await client.put(
            url, json={"changes": {"kpi_min_band_mult": 4, "kpi_max_band_mult": 2}}
        )
        assert inverted.status_code == 422
    assert (await diag_tunables(session, shop_id)).volatile_cv == 0.4
    rows = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.shop_id == shop_id)))
        .scalars()
        .all()
    )
    update = next(r for r in rows if r.action == "settings_update")
    assert update.actor_email == admin_email
    assert update.before == {"diag_windows": None, "volatile_cv": None}
    assert update.after == {"diag_windows": [30, 60], "volatile_cv": 0.4}


# =========================================================================== D29.4 chains


def _evidence(*codes: str) -> list[Evidence]:
    return [Evidence(code, EvidenceSource.TIKTOK) for code in codes]


def test_one_target_metric_per_product_and_one_proposal_per_lever():
    daily = {"p1": _series(60, noise=0.03, seed=5, change={"ctr": 0.03})}
    plan = _plan(
        daily,
        tiktok_evidence={"p1": _evidence("MAIN_IMG_DUPLICATE", "TITLE_LESS_THAN_40_CHARACTERS")},
    )
    levers = sorted(p.lever.value for p in plan.proposals)
    assert levers == ["tiêu đề", "ảnh bìa"]
    assert {p.target_metric for p in plan.proposals} == {"ctr"}
    assert {p.sibling_cards for p in plan.proposals} == {1}


async def _seed_products(session, shop, daily: dict[str, list[ProductDay]]) -> dict[str, Product]:
    from sqlalchemy import insert

    from juli_backend.models.models import AnalyticsPerformanceInterval

    now = datetime.now(UTC).replace(tzinfo=None)
    products: dict[str, Product] = {}
    rows = []
    for pid, series in daily.items():
        title = f"Sản phẩm {pid} có tiêu đề đủ dài để không bị đánh dấu ngắn"
        product = Product(
            shop_id=shop.id,
            tiktok_product_id=pid,
            title=title,
            name=title,
            status="ACTIVATE",
            update_time=now,
        )
        session.add(product)
        products[pid] = product
        for day in series:
            rows.append(
                dict(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    snapshot_key=f"product:{pid}:{day.day.isoformat()}",
                    grain="product",
                    start_date=day.day,
                    end_date=day.day + timedelta(days=1),
                    tiktok_product_id=pid,
                    impressions=int(day.impressions),
                    clicks=int(day.clicks),
                    gmv=day.gmv,
                    items_sold=int(day.items_sold),
                    orders_count=int(day.sku_orders),
                    sku_orders=int(day.sku_orders),
                    update_time=now,
                )
            )
    await session.flush()
    await session.execute(insert(AnalyticsPerformanceInterval), rows)
    await session.flush()
    return products


COMPUTED_AT = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


async def test_per_lever_chains_and_the_one_metric_rule(session):
    _, shop = await make_tenant(session)
    daily = {"p1": _series(120, impressions=6000, noise=0.03, seed=5, change={"ctr": 0.03})}
    products = await _seed_products(session, shop, daily)
    product = products["p1"]
    op = await plan_optimize_product_cards(session, shop.id, now=COMPUTED_AT)
    assert op is not None
    # Two CTR levers once TikTok was asked: inject codes the quick scan would read.
    from dataclasses import replace

    from juli_backend.services.optimize_product.decision_cards import Angle

    [proposal] = op.plan.proposals
    title = replace(proposal, lever=Angle.TIEU_DE, sibling_cards=1)
    cover = replace(title, lever=Angle.ANH_BIA, rank=2)
    op = replace(op, plan=replace(op.plan, proposals=[title, cover]))
    decisions = await emit_optimize_product_cards(
        session,
        shop.id,
        op,
        computed_at=COMPUTED_AT,
        emission_config=DecisionEmissionConfig(),
    )
    cards = [d.card for d in decisions if d.suppressed_reason is None]
    assert len(cards) == 2
    assert {c.subject_type for c in cards} == {SUBJECT_TYPE_PRODUCT_LEVER}
    assert {subject_product_ref(c.subject_type, c.subject_id) for c in cards} == {str(product.id)}
    # Both live at once: the partial unique index is per (product, lever).
    for card in cards:
        card.surfaced_at = COMPUTED_AT
        payload = json.loads(card.recommendation_payload)
        assert payload["target_metric"] == "ctr"
        assert payload["sibling_cards"] == 1
        assert set(payload["kpi"]) >= {
            "metric",
            "current",
            "target",
            "target_min",
            "target_max",
            "display",
            "band_pct",
            "window_days",
            "low_data",
        }
        assert payload["confidence"] in {"high", "medium", "low"}
        assert payload["gmv_estimate"]["per_month_max"] >= payload["gmv_estimate"]["per_month_min"]
        assert payload["diagnosis"]["tiktok_product_id"] == "p1"
        assert set(payload["quality"]) == {"score", "parts", "issues"}
    await session.flush()

    # Now the diagnosis says CTOR for the same product: never two metrics at once.
    ctor = replace(
        title,
        lever=Angle.MO_TA,
        target_metric="ctor",
        stage=Branch.PAGE,
    )
    op2 = replace(op, plan=replace(op.plan, proposals=[title, cover, ctor]))
    decisions = await emit_optimize_product_cards(
        session,
        shop.id,
        op2,
        computed_at=COMPUTED_AT + timedelta(hours=1),
        emission_config=DecisionEmissionConfig(),
    )
    blocked = [d for d in decisions if d.suppressed_reason == SUPPRESSED_REASON_OTHER_METRIC_ACTIVE]
    assert len(blocked) == 1 and blocked[0].subject_id.endswith(":description")
    live = (
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop.id,
                    ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                    ActionCard.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 2


async def test_a_legacy_product_chain_keeps_its_ladder(session):
    """A pre-P23 card (subject "product") stays its lever's chain: re-scored in place."""
    _, shop = await make_tenant(session)
    daily = {"p1": _series(120, impressions=6000, noise=0.03, seed=5, change={"ctr": 0.03})}
    products = await _seed_products(session, shop, daily)
    op = await plan_optimize_product_cards(session, shop.id, now=COMPUTED_AT)
    [proposal] = op.plan.proposals
    from juli_backend.services.optimize_product.decision_cards import LEVER_CODES

    legacy = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=str(products["p1"].id),
        revision=1,
        priority=1,
        severity="warning",
        title="legacy",
        description="",
        recommendation_payload=json.dumps(
            {
                "diagnosis": {
                    "lever": {"code": LEVER_CODES[proposal.lever]},
                    "stage": {"code": "card"},
                }
            }
        ),
        status="active",
        surfaced_at=COMPUTED_AT - timedelta(days=1),
    )
    session.add(legacy)
    await session.flush()
    await emit_optimize_product_cards(
        session,
        shop.id,
        op,
        computed_at=COMPUTED_AT,
        emission_config=DecisionEmissionConfig(),
    )
    rows = (
        (await session.execute(select(ActionCard).where(ActionCard.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert [r.id for r in rows] == [legacy.id]  # no second card for the same lever


# =========================================================================== Fujiwa-like


def fujiwa_like_daily() -> dict[str, list[ProductDay]]:
    """Five listings, Thẻ sản phẩm moving ±26 % impressions and ±66 % CTOR a day
    (D29 context), low volume; one product's CTOR really fell 35 % over 30 days."""
    rng = random.Random(2026)
    shapes = {
        "fw-binh-giu-nhiet": (2600, 0.035, 0.030, 260_000, None),
        "fw-coc-su": (1400, 0.030, 0.025, 180_000, None),
        "fw-am-dun": (900, 0.028, 0.030, 420_000, {"ctor": 0.0195}),
        "fw-hop-com": (500, 0.030, 0.020, 150_000, None),
        "fw-qua-tang": (300, 0.020, 0.010, 90_000, None),
    }
    out: dict[str, list[ProductDay]] = {}
    for pid, (impr, ctr, ctor, aov, change) in shapes.items():
        rows = []
        for offset in range(120):
            rates = {"ctor": ctor}
            if change and offset < 30:
                rates.update(change)
            day_impr = impr * (1 + rng.uniform(-0.45, 0.45))  # CV ≈ 0.26
            clicks = day_impr * ctr * (1 + rng.uniform(-0.2, 0.2))
            orders = clicks * rates["ctor"] * (1 + rng.uniform(-1.0, 1.0))  # CV ≈ 0.6
            rows.append(
                ProductDay(
                    day=AS_OF - timedelta(days=offset),
                    impressions=Decimal(round(day_impr)),
                    clicks=Decimal(round(clicks)),
                    sku_orders=Decimal(str(round(max(orders, 0), 2))),
                    items_sold=Decimal(str(round(max(orders, 0), 2))),
                    gmv=Decimal(round(max(orders, 0) * aov)),
                )
            )
        out[pid] = sorted(rows, key=lambda r: r.day)
    return out


def test_fujiwa_like_shop_gets_few_honest_cards():
    daily = fujiwa_like_daily()
    plan = _plan(daily)
    reasons = {s.product_id: s.reason for s in plan.skips}
    proposed = {p.product_id for p in plan.proposals}
    # Only the product whose GMV really fell beyond its band is proposed.
    assert proposed == {"fw-am-dun"}
    [card] = plan.proposals
    assert card.target_metric == "ctor"
    # Volatile traffic: low confidence, KPI as a range, judged at day 14 only.
    assert card.assessment.stability in {"medium", "volatile"}
    assert card.kpi.target_min < card.kpi.target_max
    # The others: noise is not a fall, thin data is not a diagnosis.
    assert reasons["fw-binh-giu-nhiet"] == "d29:no_gmv_drop"
    assert reasons["fw-qua-tang"] == "d29:low_data"

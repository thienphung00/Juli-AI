"""Stage diagnosis (ADR-106 decision 4) and the catalog scan that drives it.

The shop below is synthetic but shaped like A-34 rows: six products, five of
them above every volume floor so the shop medians exist, one gift listing
that must be excluded, one product whose own trend fires while its median
gap does not, one AOV case, one with no evidence at all. Expectations are
derived from the inputs (the median is computed here, not hardcoded) per
ADR-101.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

import pytest

from juli_backend.services.optimize_product import (
    Angle,
    Branch,
    Diagnosis,
    Evidence,
    EvidenceSource,
    FunnelWindow,
    Label,
    ProductFunnel,
    ShopMedians,
    Skip,
    StageDiagnosisConfig,
    Trigger,
    build_cards,
    derive_local_evidence,
    diagnose_product,
    listing_signals_from_product,
    parse_tiktok_diagnoses,
)


def _load_banned_patterns():
    """Load the ADR-070 banned patterns without importing ``services.agent``.

    ``juli_backend.services.agent.__init__`` pulls the execution runner and its
    image stack (Pillow) in; this module only needs the pattern loader, whose
    own imports are stdlib. Loading it by path keeps the test runnable in a
    venv without the image dependency and asserts the same patterns CI does.
    """
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/src/juli_backend/services/agent/sanitize/banned_patterns.py"
    )
    spec = importlib.util.spec_from_file_location("banned_patterns_by_path", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module.load_banned_patterns()


CONFIG = StageDiagnosisConfig()
DAYS = CONFIG.current_window_days


def _window(
    *, impressions: int, ctr: str, ctor: str, aov: str, items_per_order: str = "1.2"
) -> FunnelWindow:
    """Build a 14-day window from the ratios a seller would read, so tests read like the card."""
    clicks = Decimal(impressions) * Decimal(ctr)
    orders = clicks * Decimal(ctor)
    return FunnelWindow(
        days=DAYS,
        impressions=Decimal(impressions),
        clicks=clicks,
        sku_orders=orders,
        items_sold=orders * Decimal(items_per_order),
        gmv=orders * Decimal(aov),
    )


def _product(
    pid: str,
    title: str,
    current: FunnelWindow,
    prior: FunnelWindow | None = None,
    gmv_28d="5000000",
    age_days=120,
) -> ProductFunnel:
    return ProductFunnel(
        product_id=pid,
        title=title,
        current=current,
        prior=prior,
        gmv_28d=Decimal(gmv_28d),
        age_days=age_days,
    )


# Five healthy peers: identical ratios so the median is unambiguous.
PEER = _window(impressions=5000, ctr="0.08", ctor="0.10", aov="200000")
PEERS = [_product(f"peer-{i}", f"Peer {i}", PEER) for i in range(5)]
MEDIANS = ShopMedians.from_products(PEERS, CONFIG)


def test_shop_medians_are_computed_over_peers_above_floor() -> None:
    assert MEDIANS.peers == {"ctr": 5, "ctor": 5, "aov": 5}
    assert MEDIANS.ctr == Decimal(str(median([PEER.ctr] * 5)))
    assert MEDIANS.ctor == PEER.ctor
    assert MEDIANS.aov == PEER.aov


def test_too_few_peers_means_no_median() -> None:
    few = ShopMedians.from_products(PEERS[:3], CONFIG)
    assert few.ctr is None and few.ctor is None and few.aov is None


def test_gift_listing_is_excluded_before_any_gap() -> None:
    weak = _window(impressions=5000, ctr="0.02", ctor="0.10", aov="200000")
    result = diagnose_product(
        _product("gift", "[Quà Tặng] Chai xịt", weak),
        MEDIANS,
        [],
        CONFIG,
        excluded_reason="title matches 'quà tặng'",
    )
    assert isinstance(result, Skip) and result.reason.startswith("excluded")


def test_below_floor_is_not_diagnosed() -> None:
    tiny = _window(impressions=100, ctr="0.01", ctor="0.01", aov="50000")
    result = diagnose_product(_product("tiny", "Tiny", tiny), MEDIANS, [], CONFIG)
    assert isinstance(result, Skip) and result.reason == "below_volume_floor"


def test_weak_ctr_routes_to_card_branch_image_first() -> None:
    weak_ctr = _window(impressions=5000, ctr="0.04", ctor="0.10", aov="200000")
    evidence = [
        Evidence("TITLE_LESS_THAN_40_CHARACTERS", EvidenceSource.LOCAL, "tiêu đề 20 ký tự"),
        Evidence("MAIN_IMG_NUMBER_LESS_THAN_FIVE", EvidenceSource.LOCAL, "1 ảnh chính"),
    ]
    result = diagnose_product(_product("p", "Weak CTR", weak_ctr), MEDIANS, evidence, CONFIG)
    assert isinstance(result, Diagnosis)
    assert result.label is Label.CTOR  # card KPI stays CTOR; CTR is the diagnostic that fired
    assert result.gap.factor == "ctr"
    assert result.branch is Branch.CARD
    assert result.angle is Angle.ANH_BIA  # fixed order: image before title
    assert result.other_angles == (Angle.TIEU_DE,)
    assert result.trigger is Trigger.SHOP_MEDIAN
    assert result.gap.gap == Decimal(1) - weak_ctr.ctr / MEDIANS.ctr


def test_weak_ctor_with_healthy_ctr_routes_to_description() -> None:
    weak_ctor = _window(impressions=5000, ctr="0.08", ctor="0.05", aov="200000")
    evidence = [
        Evidence("DESC_LESS_THAN_FIVE_HUNDRED_CHARS", EvidenceSource.LOCAL, "mô tả 38 ký tự")
    ]
    result = diagnose_product(_product("p", "Weak CTOR", weak_ctor), MEDIANS, evidence, CONFIG)
    assert isinstance(result, Diagnosis)
    assert (
        result.label is Label.CTOR and result.branch is Branch.PAGE and result.angle is Angle.MO_TA
    )


def test_discount_requires_no_description_code_and_a_cap() -> None:
    weak_ctor = _window(impressions=5000, ctr="0.08", ctor="0.05", aov="200000")
    product = _product("p", "Weak CTOR", weak_ctor)
    without_cap = diagnose_product(product, MEDIANS, [], CONFIG)
    assert isinstance(without_cap, Skip) and without_cap.reason == "no_diagnosis_codes"
    with_cap = diagnose_product(product, MEDIANS, [], CONFIG, discount_cap_set=True)
    assert isinstance(with_cap, Diagnosis) and with_cap.angle is Angle.GIAM_GIA
    locked = diagnose_product(
        product, MEDIANS, [], CONFIG, discount_cap_set=True, active_promotion=True
    )
    assert isinstance(locked, Skip)


def test_card_branch_without_evidence_falls_to_page_branch() -> None:
    weak_ctr = _window(impressions=5000, ctr="0.04", ctor="0.10", aov="200000")
    evidence = [Evidence("DESC_NO_NEW_LINE", EvidenceSource.LOCAL, "một khối")]
    result = diagnose_product(_product("p", "Weak CTR", weak_ctr), MEDIANS, evidence, CONFIG)
    assert isinstance(result, Diagnosis)
    assert result.branch is Branch.PAGE and result.angle is Angle.MO_TA
    assert any("chuyển sang nhánh trang" in c for c in result.caveats)


def test_own_trend_fires_when_median_does_not() -> None:
    # Equal to the shop median today, but 40 % below its own prior window.
    current = _window(impressions=5000, ctr="0.08", ctor="0.10", aov="200000")
    prior = FunnelWindow(
        days=CONFIG.prior_window_days,
        impressions=Decimal(4000),
        clicks=Decimal(4000) * Decimal("0.08"),
        sku_orders=Decimal(4000) * Decimal("0.08") * Decimal("0.1667"),
        items_sold=Decimal(60),
        gmv=Decimal(10_000_000),
    )
    evidence = [Evidence("DESC_LESS_THAN_FIVE_HUNDRED_CHARS", EvidenceSource.LOCAL, "")]
    result = diagnose_product(_product("p", "Falling", current, prior), MEDIANS, evidence, CONFIG)
    assert isinstance(result, Diagnosis)
    assert result.trigger is Trigger.OWN_TREND
    assert result.gap.gap_median == Decimal(0)
    assert result.gap.gap_trend == Decimal(1) - current.ctor / prior.ctor


def test_young_product_ignores_trend() -> None:
    current = _window(impressions=5000, ctr="0.08", ctor="0.10", aov="200000")
    prior = _window(impressions=5000, ctr="0.08", ctor="0.30", aov="200000")
    result = diagnose_product(
        _product("p", "Young", current, prior, age_days=10), MEDIANS, [], CONFIG
    )
    assert isinstance(result, Skip) and result.reason == "no_gap_above_threshold"


def test_weak_aov_with_healthy_ctor_is_a_bmsm_card() -> None:
    weak_aov = _window(
        impressions=5000, ctr="0.08", ctor="0.10", aov="120000", items_per_order="1.4"
    )
    result = diagnose_product(_product("p", "Weak AOV", weak_aov), MEDIANS, [], CONFIG)
    assert isinstance(result, Diagnosis)
    assert result.label is Label.AOV and result.angle is Angle.MUA_NHIEU_GIAM_NHIEU
    assert result.bmsm is not None
    assert result.bmsm.threshold_items == 2 + CONFIG.bmsm_threshold_plus  # ceil(1.4) + 1
    assert result.bmsm.percent_is_estimate is True


def test_ranking_and_open_slots_and_copy() -> None:
    weak_ctr = _window(impressions=5000, ctr="0.04", ctor="0.10", aov="200000")
    evidence = [Evidence("MAIN_IMG_NUMBER_LESS_THAN_FIVE", EvidenceSource.LOCAL, "1 ảnh chính")]
    diagnoses = []
    for i in range(7):
        result = diagnose_product(
            _product(f"p{i}", f"Sản phẩm {i}", weak_ctr, gmv_28d=str(1_000_000 * (i + 1))),
            MEDIANS,
            evidence,
            CONFIG,
        )
        assert isinstance(result, Diagnosis)
        diagnoses.append(result)
    cards = build_cards(diagnoses, CONFIG)
    assert [c.product_id for c in cards][:2] == ["p6", "p5"]  # higher GMV ranks first
    assert sum(c.within_open_slots for c in cards) == CONFIG.max_open_cards_per_shop
    first = cards[0]
    assert first.main_kpi == "CTOR" and first.angle == Angle.ANH_BIA.value
    assert "ước tính" in first.reason and "so với trung bình shop" in first.reason
    assert "Juli đánh giá" in first.action and "TikTok" not in first.action
    for pattern in _load_banned_patterns():
        assert not pattern.search(first.reason), pattern.pattern
        assert not pattern.search(first.action), pattern.pattern


def test_local_evidence_from_product_payload() -> None:
    product = {
        "id": "x",
        "title": "Chai Xịt Thơm Miệng Fujisalt 14mL",
        "description": "Xịt thơm miệng.",
        "main_images": [
            {"uri": "a", "width": 500, "height": 500},
            {"uri": "a", "width": 500, "height": 500},
        ],
        "skus": [{"price": {"sale_price": "72000"}}],
        "status": "ACTIVATE",
    }
    signals = listing_signals_from_product(product, CONFIG)
    codes = {e.code for e in derive_local_evidence(signals, CONFIG)}
    assert codes == {
        "TITLE_LESS_THAN_40_CHARACTERS",
        "DESC_LESS_THAN_FIVE_HUNDRED_CHARS",
        "DESC_NO_NEW_LINE",
        "MAIN_IMG_NUMBER_LESS_THAN_FIVE",
        "MAIN_IMG_DUPLICATE",
        "MAIN_IMG_FIRST_IMG_LOW_QUALITY",
    }
    assert signals.excluded_reason is None
    gift = listing_signals_from_product({**product, "title": "[Quà Tặng] Chai xịt"}, CONFIG)
    assert gift.excluded_reason


def test_parse_tiktok_diagnoses_keeps_source_and_fix() -> None:
    entry = {
        "id": "x",
        "diagnoses": [
            {
                "field": "TITLE",
                "diagnosis_results": [
                    {"code": "SEO_DIAGNOSTIC_ITEM", "how_to_solve": "Thêm từ khóa"}
                ],
            }
        ],
    }
    [evidence] = parse_tiktok_diagnoses(entry)
    assert evidence.source is EvidenceSource.TIKTOK and evidence.how_to_solve == "Thêm từ khóa"


def test_a34_window_reconstructs_counts_from_ratios() -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/analytics_backfill/product/a34_page1.json"
        ).read_text()
    )
    total = fixture["products"][0]["total_performance"]
    window = FunnelWindow.from_a34_total_performance(total, days=14)
    assert window.sku_orders == Decimal("10")
    assert window.clicks == Decimal("10") / Decimal("0.1064")
    assert window.impressions == window.clicks / Decimal("0.0759")
    assert window.ctor.quantize(Decimal("0.0001")) == Decimal("0.1064")


@pytest.mark.parametrize("with_channel_blocks", [False, True])
def test_catalog_scan_runs_from_a_snapshot(tmp_path: Path, with_channel_blocks: bool) -> None:
    from juli_backend.services.optimize_product import catalog_scan as module

    def a34(pid: str, ctr: str, ctor: str, orders: int, gmv: str) -> dict:
        return {
            "id": pid,
            "total_performance": {
                "gmv": {"amount": gmv, "currency": "VND"},
                "orders": orders,
                "sku_orders": orders,
                "items_sold": orders,
                "ctr": ctr,
                "click_order_rate": ctor,
            },
        }

    snapshot = tmp_path / "snap"
    peers = [a34(f"peer-{i}", "0.08", "0.10", 200, "40000000") for i in range(5)]
    weak = a34("weak", "0.03", "0.10", 200, "40000000")
    (snapshot).mkdir()
    (snapshot / "meta.json").write_text(json.dumps({"as_of": "2026-10-05"}))
    (snapshot / "a34_current.json").write_text(json.dumps({"products": peers + [weak]}))
    (snapshot / "a34_prior.json").write_text(json.dumps({"products": peers + [weak]}))
    (snapshot / "a34_last28.json").write_text(json.dumps({"products": peers + [weak]}))
    (snapshot / "products").mkdir()
    for item in peers + [weak]:
        (snapshot / "products" / f"{item['id']}.json").write_text(
            json.dumps(
                {
                    "id": item["id"],
                    "title": "Sản phẩm " + item["id"],
                    "description": "Ngắn.",
                    "main_images": [{"uri": "u", "width": 800, "height": 800}],
                    "status": "ACTIVATE",
                }
            )
        )
    if with_channel_blocks:
        # The live A-34 row carries per-channel blocks; the product-card scope
        # is seller_product_card_performance + shop_tab_performance.
        weak["seller_product_card_performance"] = {
            "product_impressions": 20000,
            "product_clicks": 600,
            "ctr": "0.03",
            "attributed_sku_orders": 60,
            "attributed_sold_items": 60,
            "attributed_gmv": {"amount": "12000000", "currency": "VND"},
            "click_order_rate": "0.10",
        }
        weak["shop_tab_performance"] = {
            "shop_tab_product_impressions": 10000,
            "shop_tab_product_clicks": 300,
            "shop_tab_ctr": "0.03",
            "shop_tab_ctor_sku": "0.10",
            "shop_tab_sold_items": 30,
            "shop_tab_gmv": {"amount": "6000000", "currency": "VND"},
        }
        (snapshot / "a34_current.json").write_text(json.dumps({"products": peers + [weak]}))

    out = module.run_snapshot(snapshot, tmp_path / "out", CONFIG)
    assert (tmp_path / "out" / "report.md").exists()
    cards = out["cards"]
    assert [c["product_id"] for c in cards] == ["weak"]
    assert cards[0]["angle"] == Angle.ANH_BIA.value
    assert cards[0]["channel_scope"] == ("PRODUCT_CARD" if with_channel_blocks else "ALL_CHANNELS")
    assert all(s["reason"] == "no_gap_above_threshold" for s in out["skips"])

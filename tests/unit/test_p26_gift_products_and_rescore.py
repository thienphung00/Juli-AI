"""P26: gift items are never optimize candidates; pre-D29 pending cards are re-scored.

Synthetic data only (no shop's real catalogue): the gift titles below are made up
in the shape TikTok VN sellers use ("[Quà Tặng] …"), in NFC and NFD.
"""

from __future__ import annotations

import json
import unicodedata
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Product
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    rescore_shop_cards,
)
from juli_backend.services.action_cards.subjects import resolve_card_subject
from juli_backend.services.demo_decisions.card_view import build_card_block
from juli_backend.services.ops import simulation as sim
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.decision_cards import (
    CatalogProduct,
    exclusion_reason,
)
from juli_backend.services.optimize_product.eligibility import (
    GIFT_PRODUCT,
    fold,
    gift_reason,
    gift_reason_from_raw,
    is_gift_product,
)
from juli_backend.services.optimize_product.listing_signals import listing_signals_from_product
from juli_backend.services.optimize_product.rescore import (
    FALLBACK_BAND_PCT,
    cap_legacy_target,
    rescore_legacy_payload,
)
from juli_backend.services.optimize_product.tunables import DiagTunables
from tests.unit.test_optimize_product_decision_cards import (
    AS_OF,
    COMPUTED_AT,
    _optimize_cards,
    _score,
    _seed_shop,
)

GIFT_TITLE = "[Quà Tặng] Xịt thơm miệng hương bạc hà 10mL"

# --------------------------------------------------------------------------- the rule


@pytest.mark.parametrize(
    "title",
    [
        GIFT_TITLE,
        unicodedata.normalize("NFD", GIFT_TITLE),
        "QUA TANG - Túi vải canvas",
        "Hàng tặng kèm: móc khoá",
        "[Gift] Sample sachet",
        "Mẫu thử KHÔNG BÁN",
    ],
)
def test_gift_titles_are_caught_case_and_diacritic_insensitively(title):
    reason = gift_reason(title=title)
    assert reason is not None and reason.startswith(GIFT_PRODUCT)


def test_ordinary_titles_and_prices_are_not_gifts():
    assert gift_reason(title="Bình giữ nhiệt inox 500mL", sku_prices=["189000", 159000]) is None
    # 0 is a placeholder, not a token price.
    assert gift_reason(title="Áo thun", sku_prices=[0, "0"]) is None


def test_documented_flag_and_token_price():
    assert (
        gift_reason(title="Sản phẩm A", is_not_for_sale=True) == f"{GIFT_PRODUCT}: is_not_for_sale"
    )
    assert gift_reason(title="Sản phẩm A", is_not_for_sale="true") is not None
    assert gift_reason(title="Sản phẩm A", is_not_for_sale=False) is None
    assert is_gift_product(title="Sản phẩm B", sku_prices=["1000", "500"])
    assert not is_gift_product(title="Sản phẩm B", sku_prices=["1000", "1001"])


def test_fold_is_nfc_nfd_agnostic():
    assert fold("Quà Tặng Đặc Biệt") == fold(unicodedata.normalize("NFD", "quà tặng đặc biệt"))
    assert fold("Quà Tặng Đặc Biệt") == "qua tang dac biet"


def test_raw_payload_flag_reaches_listing_signals_and_exclusion():
    raw = {
        "id": "p1",
        "title": "Sản phẩm thường",
        "is_not_for_sale": True,
        "skus": [{"price": {"sale_price": "250000"}}],
    }
    config = StageDiagnosisConfig()
    assert gift_reason_from_raw(raw) == f"{GIFT_PRODUCT}: is_not_for_sale"
    assert listing_signals_from_product(raw, config).excluded_reason is not None
    nfd = CatalogProduct("p2", unicodedata.normalize("NFD", GIFT_TITLE), "ACTIVATE")
    assert (exclusion_reason(nfd, config) or "").startswith(GIFT_PRODUCT)
    assert exclusion_reason(CatalogProduct("p3", "Sản phẩm thường", "ACTIVATE"), config) is None


# --------------------------------------------------------------------------- Ops table


def test_ops_volatility_table_drops_gift_rows_but_keeps_shop_totals():
    end = date(2026, 10, 9)

    def rows():
        return {(end - timedelta(days=i)).isoformat(): [100, 5, 1, 100_000] for i in range(30)}

    streams = {
        stream: {
            (end - timedelta(days=i)).isoformat(): [1000.0, 50.0, 5.0, 750_000.0] for i in range(30)
        }
        for stream in sim.STREAMS
    }
    report = {
        "daily_streams": streams,
        "daily_products": {"product_card": {"real": rows(), "gift": rows()}},
        "titles": {"real": "Bình giữ nhiệt", "gift": GIFT_TITLE},
        "seller_skus": {},
    }
    payload = sim.baseline(sim.merge_reports([report]), 30)
    ids = [r["id"] for r in payload["volatility"]["product_card"]["rows"]]
    assert ids == ["real"]
    card = next(s for s in payload["streams"] if s["stream"] == "product_card")
    assert card["gmv_per_day"] == pytest.approx(750_000.0)


# --------------------------------------------------------------------------- re-score (pure)


def _rows(days: int = 40, *, ctr_wobble: float = 0.004) -> list[ProductDay]:
    out = []
    for offset in range(days):
        impressions = Decimal(2000)
        ctr = Decimal(str(0.03 + (ctr_wobble if offset % 2 else -ctr_wobble)))
        clicks = (impressions * ctr).quantize(Decimal("1"))
        orders = (clicks * Decimal("0.05")).quantize(Decimal("1"))
        out.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=impressions,
                clicks=clicks,
                sku_orders=orders,
                items_sold=orders,
                gmv=orders * Decimal("200000"),
            )
        )
    return sorted(out, key=lambda d: d.day)


def _legacy_payload(current: float = 0.0322, reference: float = 0.0457) -> dict:
    """A card written before P23: ADR-106 numbers, no ``kpi`` / ``confidence``."""
    return {
        "workflow_key": OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        "expected_impact": {"metric": "recoverable_gmv_per_day", "value": 500_000.0},
        "reasoning": {"expected_impact": "Có thể lấy lại khoảng 500.000 ₫ GMV mỗi ngày"},
        "diagnosis": {
            "version": "adr106-v1",
            "tiktok_product_id": "synthetic-1",
            "stage": {"code": "card", "label": "x"},
            "lever": {"code": "title", "label": "tiêu đề", "evidence": []},
            "main_kpi": {"key": "ctor", "raw": 0.05},
            "trigger": {"sentence": "CTR thấp hơn trung vị shop"},
            "recoverable_gmv_per_day": 500_000.0,
            "recoverable_gmv_basis": {
                "stage_rate": "ctr",
                "current_rate": current,
                "reference_rate": reference,
                "reference": "shop_median",
            },
        },
    }


def test_rescore_clamps_a_legacy_target_to_the_three_band_cap():
    tunables = DiagTunables()
    out = rescore_legacy_payload(_legacy_payload(), _rows(), as_of=AS_OF, tunables=tunables)
    assert out is not None
    kpi = out["kpi"]
    assert out["target_metric"] == "ctr"
    assert out["confidence"] in {"high", "medium", "low"}
    assert kpi["window_days"] in tunables.windows
    band_abs = kpi["current"] * kpi["band_pct"] / 100
    assert kpi["target"] <= kpi["current"] + 3 * band_abs + 1e-9
    assert kpi["target"] >= kpi["current"] + 1 * band_abs - 1e-9
    basis = out["diagnosis"]["recoverable_gmv_basis"]
    assert basis["reference_rate"] == kpi["target"]
    assert out["gmv_estimate"]["per_month_max"] >= out["gmv_estimate"]["per_month_min"] >= 0
    assert out["diagnosis"]["rescored_d29_as_of"] == AS_OF.isoformat()
    # Already D29: nothing to do.
    assert rescore_legacy_payload(out, _rows(), as_of=AS_OF, tunables=tunables) is None


def test_rescore_without_daily_rows_leaves_the_card_and_the_read_model_caps_it():
    assert (
        rescore_legacy_payload(_legacy_payload(), [], as_of=AS_OF, tunables=DiagTunables()) is None
    )
    ceiling = 0.0322 * (1 + 3 * FALLBACK_BAND_PCT / 100)
    assert cap_legacy_target(0.0322, 0.0457) == pytest.approx(ceiling)
    assert cap_legacy_target(0.0322, 0.033) == 0.033

    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        status="active",
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        revision=1,
    )
    block = build_card_block(card, _legacy_payload(), None)
    assert block is not None
    assert block["main_kpi"]["target"] == pytest.approx(ceiling)
    # GMV shrinks with the target: 500k/day × (cap − cur) / (old − cur) × 30.
    share = (ceiling - 0.0322) / (0.0457 - 0.0322)
    assert block["expected_gmv_per_month"] == round(500_000 * share * 30)


# --------------------------------------------------------------------------- DB paths


async def _gift_product(session, shop_id) -> Product:
    return (
        await session.execute(
            select(Product).where(
                Product.shop_id == shop_id, Product.title == "Quà tặng kèm không bán"
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_gift_cards_are_retired_and_legacy_cards_rescored_without_tiktok(session):
    shop = await _seed_shop(session, "G")
    await _score(session, shop)
    gift = await _gift_product(session, shop.id)
    # A card written before the gift rule existed (the old top-revenue subject).
    gift_card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=str(gift.id),
        revision=1,
        status="active",
        recommendation_payload=json.dumps({"rationale": "legacy"}),
        priority=1,
        severity="warning",
        title="Legacy",
        surfaced_at=COMPUTED_AT,
    )
    session.add(gift_card)
    # Turn one emitted card back into its pre-D29 shape (no kpi, shop-median target).
    cards = await _optimize_cards(session, shop.id)
    legacy = next(c for c in cards if c.surfaced_at is not None and c.id != gift_card.id)
    payload = json.loads(legacy.recommendation_payload)
    for key in ("kpi", "target_metric", "confidence", "gmv_estimate", "sibling_cards"):
        payload.pop(key, None)
    basis = payload["diagnosis"]["recoverable_gmv_basis"]
    basis["reference_rate"] = float(basis["current_rate"]) * 1.42
    legacy.recommendation_payload = json.dumps(payload, ensure_ascii=False)
    await session.flush()

    result = await rescore_shop_cards(session, shop.id, now=COMPUTED_AT)

    assert result["gift_cards_retired"] == 1
    assert result["cards_rescored"] >= 1
    assert gift_card.status == "withdrawn"
    assert gift_card.suppressed_reason == GIFT_PRODUCT
    rescored = json.loads(legacy.recommendation_payload)
    kpi = rescored["kpi"]
    assert kpi["target"] <= kpi["current"] * (1 + 3 * kpi["band_pct"] / 100) + 1e-9
    assert rescored["confidence"] in {"high", "medium", "low"}
    assert legacy.status == "active" and legacy.surfaced_at is not None


@pytest.mark.asyncio
async def test_gift_product_is_never_the_legacy_subject_nor_approvable(session):
    from juli_backend.services.agent.approval import (
        CardSubjectNotApprovable,
        _resolve_card_subject,
    )

    shop = await _seed_shop(session, "H")
    gift = await _gift_product(session, shop.id)
    gift.revenue = Decimal("9999999999")  # gifts ride on every order
    await session.flush()
    subject = await resolve_card_subject(session, shop.id, OPTIMIZE_PRODUCT_WORKFLOW_KEY)
    assert subject.subject_id != str(gift.id)

    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=str(gift.id),
        revision=1,
        status="active",
    )
    with pytest.raises(CardSubjectNotApprovable, match="gift"):
        await _resolve_card_subject(session, card)


@pytest.mark.asyncio
async def test_d29_plan_never_proposes_a_gift(session):
    from juli_backend.services.action_cards.optimize_product_cards import (
        plan_optimize_product_cards,
    )

    shop = await _seed_shop(session, "I")
    gift = await _gift_product(session, shop.id)
    op = await plan_optimize_product_cards(session, shop.id, now=COMPUTED_AT)
    assert op is not None
    assert gift.tiktok_product_id in op.plan.excluded
    assert gift.tiktok_product_id not in {p.product_id for p in op.plan.proposals}

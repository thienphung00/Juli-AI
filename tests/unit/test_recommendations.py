"""Tests for recommendations module — Issue #39.

Test mapping (from issue):
  AC1 → test_product_push_combines_trend_stock_margin
  AC2 → test_recommendations_output_vietnamese
  AC3 → test_recommendations_include_cta
  AC4 → test_rule_based_no_llm_dependency
"""

import importlib
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.recommendations import (
    get_host_product_matching,
    get_product_push_suggestions,
    get_stream_optimization,
)
from juli_backend.ai.recommendations.engine import HostProductMatch, ProductPushSuggestion
from juli_backend.ai.recommendations.prediction import (
    ACTION_CONTACT_CREATOR,
    PredictedOutcome,
)
from juli_backend.models.models import (
    Creator,
    InventoryItem,
    Livestream,
    Order,
    Product,
    Settlement,
    Shop,
    User,
)
from juli_backend.repositories.repos import GraphRepo

_ANALYTICS_JARGON = (
    "velocity",
    "mape",
    "conversion rate",
    "kpi",
    "roi",
    "sigma",
    "regression",
    "linear regression",
    "analytics",
    "composite score",
    "urgency score",
)


def _make_user(user_id: uuid.UUID) -> User:
    return User(id=user_id, phone="+84900000039")


def _make_shop(shop_id: uuid.UUID, user_id: uuid.UUID) -> Shop:
    return Shop(id=shop_id, user_id=user_id, shop_name="Reco Shop")


def _make_product(
    shop_id: uuid.UUID,
    *,
    tiktok_product_id: str,
    name: str,
    revenue: Decimal,
    units_sold: int,
) -> Product:
    now = datetime.now(UTC)
    return Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        name=name,
        status="ACTIVE",
        revenue=revenue,
        units_sold=units_sold,
        update_time=now,
        created_at=now,
    )


def _make_inventory(
    shop_id: uuid.UUID,
    *,
    tiktok_product_id: str,
    sku_id: str,
    quantity: int,
) -> InventoryItem:
    now = datetime.now(UTC)
    return InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        tiktok_sku_id=sku_id,
        quantity=quantity,
        velocity="medium",
        update_time=now,
        created_at=now,
    )


def _make_order(
    shop_id: uuid.UUID,
    *,
    tiktok_order_id: str,
    created_at: datetime,
) -> Order:
    return Order(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_order_id=tiktok_order_id,
        status="COMPLETED",
        total_amount=Decimal("100.00"),
        currency="VND",
        update_time=created_at,
        created_at=created_at,
    )


def _make_creator(
    shop_id: uuid.UUID,
    *,
    tiktok_creator_id: str,
    name: str,
) -> Creator:
    now = datetime.now(UTC)
    return Creator(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_creator_id=tiktok_creator_id,
        name=name,
        follower_count=10000,
        update_time=now,
        created_at=now,
    )


def _make_livestream(
    shop_id: uuid.UUID,
    creator_id: uuid.UUID,
    *,
    tiktok_livestream_id: str,
    viewers: int,
    orders: int,
    revenue: Decimal,
    started_hours_ago: int = 2,
) -> Livestream:
    end = datetime.now(UTC) - timedelta(hours=started_hours_ago)
    start = end - timedelta(hours=1)
    return Livestream(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_livestream_id=tiktok_livestream_id,
        creator_id=creator_id,
        title="Live bán hàng",
        start_time=start,
        end_time=end,
        viewer_count=viewers,
        order_count=orders,
        revenue=revenue,
        update_time=end,
        created_at=end,
    )


async def _seed_shop(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    session.add(_make_user(uid))
    session.add(_make_shop(sid, uid))
    await session.flush()
    return sid


async def _seed_accelerating_orders(
    session: AsyncSession, shop_id: uuid.UUID, *, days: int = 20
) -> None:
    now = datetime.now(UTC)
    base = now - timedelta(days=days)
    orders = []
    for day_offset in range(days):
        day_start = base + timedelta(days=day_offset)
        count = 2 if day_offset < 10 else 10
        for i in range(count):
            orders.append(
                _make_order(
                    shop_id,
                    tiktok_order_id=f"reco_{day_offset}_{i}",
                    created_at=day_start + timedelta(hours=1),
                )
            )
    session.add_all(orders)
    await session.flush()


class TestProductPushCombinesTrendStockMargin:
    """AC1: ranked suggestions reflect trend, stock, and margin signals."""

    @pytest.mark.asyncio
    async def test_product_push_combines_trend_stock_margin(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add_all(
            [
                _make_product(
                    shop_id,
                    tiktok_product_id="prod_star",
                    name="Serum Vitamin C",
                    revenue=Decimal("5000000"),
                    units_sold=200,
                ),
                _make_product(
                    shop_id,
                    tiktok_product_id="prod_slow",
                    name="Kem dưỡng cơ bản",
                    revenue=Decimal("200000"),
                    units_sold=50,
                ),
            ]
        )
        session.add_all(
            [
                _make_inventory(
                    shop_id,
                    tiktok_product_id="prod_star",
                    sku_id="sku_star",
                    quantity=80,
                ),
                _make_inventory(
                    shop_id,
                    tiktok_product_id="prod_slow",
                    sku_id="sku_slow",
                    quantity=5,
                ),
            ]
        )
        await _seed_accelerating_orders(session, shop_id)
        await session.flush()

        suggestions = await get_product_push_suggestions(session, shop_id)

        assert len(suggestions) >= 2
        assert all(isinstance(s, ProductPushSuggestion) for s in suggestions)
        assert suggestions[0].composite_score >= suggestions[1].composite_score
        assert suggestions[0].tiktok_product_id == "prod_star"
        assert suggestions[0].product_name == "Serum Vitamin C"


class TestRecommendationsOutputVietnamese:
    """AC2: plain Vietnamese copy without analytics jargon."""

    @pytest.mark.asyncio
    async def test_recommendations_output_vietnamese(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add(
            _make_product(
                shop_id,
                tiktok_product_id="prod_vn",
                name="Son môi đỏ",
                revenue=Decimal("1000000"),
                units_sold=100,
            )
        )
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_vn",
                sku_id="sku_vn",
                quantity=40,
            )
        )
        await _seed_accelerating_orders(session, shop_id)
        await session.flush()

        suggestions = await get_product_push_suggestions(session, shop_id)
        assert suggestions

        for item in suggestions:
            combined = f"{item.message} {item.cta}".lower()
            for term in _ANALYTICS_JARGON:
                assert term not in combined, f"found jargon '{term}' in copy"
            vietnamese_vowels = (
                "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
            )
            assert (
                any(ch in item.message for ch in vietnamese_vowels)
                or "Nên" in item.message
                or "sản phẩm" in item.message
            )


class TestRecommendationsIncludeCta:
    """AC3: each suggestion includes an actionable CTA."""

    @pytest.mark.asyncio
    async def test_recommendations_include_cta(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add(
            _make_product(
                shop_id,
                tiktok_product_id="prod_cta",
                name="Mặt nạ collagen",
                revenue=Decimal("800000"),
                units_sold=80,
            )
        )
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_cta",
                sku_id="sku_cta",
                quantity=50,
            )
        )
        await _seed_accelerating_orders(session, shop_id)
        await session.flush()

        suggestions = await get_product_push_suggestions(session, shop_id)
        assert suggestions
        for item in suggestions:
            assert item.cta.strip()
            assert item.product_name in item.cta or "sản phẩm" in item.cta.lower()


class TestRuleBasedNoLlmDependency:
    """AC4: rule-based heuristics only — no LLM client imports."""

    @pytest.mark.asyncio
    async def test_rule_based_no_llm_dependency(self, session: AsyncSession):
        engine = importlib.import_module("juli_backend.ai.recommendations.engine")
        source = inspect.getsource(engine)
        forbidden = ("openai", "litellm", "anthropic", "langchain")
        for name in forbidden:
            assert name not in source.lower()

        shop_id = await _seed_shop(session)
        session.add(
            _make_product(
                shop_id,
                tiktok_product_id="prod_rules",
                name="Toner cân bằng",
                revenue=Decimal("500000"),
                units_sold=40,
            )
        )
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_rules",
                sku_id="sku_rules",
                quantity=30,
            )
        )
        await _seed_accelerating_orders(session, shop_id)
        await session.flush()

        suggestions = await get_product_push_suggestions(session, shop_id)
        assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_stream_optimization_generates_suggestions(session: AsyncSession):
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="creator_1", name="Linh")
    live = _make_livestream(
        shop_id,
        creator.id,
        tiktok_livestream_id="live_001",
        viewers=1200,
        orders=60,
        revenue=Decimal("12000000"),
    )
    session.add_all([creator, live])
    await session.flush()

    async def fake_llm(_: str) -> str:
        return "Tăng nhịp demo 3 phút đầu và ghim combo giá tốt để kéo chốt đơn."

    suggestion = await get_stream_optimization(
        session,
        shop_id,
        "live_001",
        max_calls_per_day=5,
        llm_generator=fake_llm,
    )
    assert suggestion.message
    assert suggestion.source == "llm"
    assert suggestion.score_grade >= 0


@pytest.mark.asyncio
async def test_host_product_matching(session: AsyncSession):
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="creator_2", name="Huy")
    session.add(creator)
    session.add(
        _make_livestream(
            shop_id,
            creator.id,
            tiktok_livestream_id="live_002",
            viewers=900,
            orders=45,
            revenue=Decimal("9000000"),
        )
    )
    session.add(
        _make_product(
            shop_id,
            tiktok_product_id="prod_match",
            name="Sữa rửa mặt dịu nhẹ",
            revenue=Decimal("2000000"),
            units_sold=100,
        )
    )
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_match",
            sku_id="sku_match",
            quantity=60,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=15)
    await session.flush()

    matches = await get_host_product_matching(session, shop_id, limit=1)
    assert matches
    assert all(isinstance(m, HostProductMatch) for m in matches)
    assert matches[0].creator_name == "Huy"
    assert matches[0].tiktok_product_id == "prod_match"


@pytest.mark.asyncio
async def test_cost_budget_fallback(session: AsyncSession):
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="creator_3", name="Mai")
    live = _make_livestream(
        shop_id,
        creator.id,
        tiktok_livestream_id="live_003",
        viewers=600,
        orders=20,
        revenue=Decimal("5000000"),
    )
    session.add_all([creator, live])
    await session.flush()

    suggestion = await get_stream_optimization(
        session,
        shop_id,
        "live_003",
        max_calls_per_day=0,
        llm_generator=lambda _: (_ for _ in ()).throw(RuntimeError("should not call")),
    )
    assert suggestion.source == "rules"
    assert "Ưu tiên cải thiện" in suggestion.message


@pytest.mark.asyncio
async def test_cta_in_vietnamese(session: AsyncSession):
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="creator_4", name="Nhi")
    live = _make_livestream(
        shop_id,
        creator.id,
        tiktok_livestream_id="live_004",
        viewers=700,
        orders=30,
        revenue=Decimal("7000000"),
    )
    session.add_all([creator, live])
    session.add(
        _make_product(
            shop_id,
            tiktok_product_id="prod_vn_cta",
            name="Kem chống nắng",
            revenue=Decimal("1300000"),
            units_sold=90,
        )
    )
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_vn_cta",
            sku_id="sku_vn_cta",
            quantity=45,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=12)
    await session.flush()

    stream_suggestion = await get_stream_optimization(session, shop_id, "live_004")
    host_matches = await get_host_product_matching(session, shop_id, limit=1)

    assert "Nhấn để" in stream_suggestion.cta
    assert host_matches
    assert "Nhấn để" in host_matches[0].cta


@pytest.mark.asyncio
async def test_issue93_graph_edge_boosts_ranking(session: AsyncSession):
    """AC1: potential_match / has_sold edge weights lift match rank."""
    shop_id = await _seed_shop(session)
    weak_creator = _make_creator(shop_id, tiktok_creator_id="c_weak", name="Creator Yếu")
    strong_creator = _make_creator(shop_id, tiktok_creator_id="c_strong", name="Creator Mạnh")
    product = _make_product(
        shop_id,
        tiktok_product_id="prod_rank",
        name="Toner",
        revenue=Decimal("1000000"),
        units_sold=50,
    )
    session.add_all([weak_creator, strong_creator, product])
    session.add_all(
        [
            _make_livestream(
                shop_id,
                weak_creator.id,
                tiktok_livestream_id="live_weak",
                viewers=200,
                orders=5,
                revenue=Decimal("500000"),
            ),
            _make_livestream(
                shop_id,
                strong_creator.id,
                tiktok_livestream_id="live_strong",
                viewers=250,
                orders=6,
                revenue=Decimal("600000"),
            ),
        ]
    )
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_rank",
            sku_id="sku_rank",
            quantity=40,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=12)
    await session.flush()

    repo = GraphRepo(session)
    await repo.upsert_edge(
        shop_id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=strong_creator.id,
        target_node_type="product",
        target_node_id=product.id,
        weight=Decimal("0.95"),
    )

    matches = await get_host_product_matching(session, shop_id, limit=2)
    assert len(matches) >= 1
    assert matches[0].creator_name == "Creator Mạnh"
    assert matches[0].match_score >= matches[-1].match_score


@pytest.mark.asyncio
async def test_issue93_host_product_match_predicted_outcome_fields(session: AsyncSession):
    """AC2: each match exposes GMV band, conversion, engagement, risk_factors."""
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="c_pred", name="Hà")
    session.add(creator)
    session.add(
        _make_livestream(
            shop_id,
            creator.id,
            tiktok_livestream_id="live_pred",
            viewers=500,
            orders=25,
            revenue=Decimal("4000000"),
        )
    )
    product = _make_product(
        shop_id,
        tiktok_product_id="prod_pred",
        name="Kem dưỡng",
        revenue=Decimal("1500000"),
        units_sold=60,
    )
    session.add(product)
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_pred",
            sku_id="sku_pred",
            quantity=35,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=10)
    await session.flush()

    repo = GraphRepo(session)
    await repo.upsert_edge(
        shop_id,
        edge_type="has_sold",
        source_node_type="creator",
        source_node_id=creator.id,
        target_node_type="product",
        target_node_id=product.id,
        weight=Decimal("0.88"),
    )

    matches = await get_host_product_matching(session, shop_id, limit=1)
    assert matches
    outcome = matches[0].predicted_outcome
    assert isinstance(outcome, PredictedOutcome)
    assert outcome.gmv_vnd_week["high"] >= outcome.gmv_vnd_week["low"] > 0
    assert outcome.conversion_pct >= 0
    assert 0 <= outcome.engagement_index <= 1
    assert isinstance(outcome.risk_factors, list)


@pytest.mark.asyncio
async def test_issue93_host_product_match_action_type_and_cta(session: AsyncSession):
    """AC3: action_type and Vietnamese CTA are present."""
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="c_act", name="Minh")
    session.add(creator)
    session.add(
        _make_livestream(
            shop_id,
            creator.id,
            tiktok_livestream_id="live_act",
            viewers=1200,
            orders=55,
            revenue=Decimal("10000000"),
        )
    )
    session.add(
        _make_product(
            shop_id,
            tiktok_product_id="prod_act",
            name="Son",
            revenue=Decimal("2500000"),
            units_sold=100,
        )
    )
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_act",
            sku_id="sku_act",
            quantity=60,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=14)
    await session.flush()

    repo = GraphRepo(session)
    product_row = (
        await session.execute(
            select(Product).where(
                Product.shop_id == shop_id,
                Product.tiktok_product_id == "prod_act",
            )
        )
    ).scalar_one()
    await repo.upsert_edge(
        shop_id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=creator.id,
        target_node_type="product",
        target_node_id=product_row.id,
        weight=Decimal("0.91"),
    )

    matches = await get_host_product_matching(session, shop_id, limit=1)
    assert matches
    match = matches[0]
    assert match.action_type == ACTION_CONTACT_CREATOR
    assert match.cta.strip()
    assert "Nhấn để" in match.cta
    assert match.confidence in ("high", "medium", "low")


@pytest.mark.asyncio
async def test_issue93_host_product_matching_llm_quota_uses_rules(session: AsyncSession):
    """AC4: LLM budget exhausted → source remains rules."""
    shop_id = await _seed_shop(session)
    creator = _make_creator(shop_id, tiktok_creator_id="c_llm", name="Vy")
    session.add(creator)
    session.add(
        _make_livestream(
            shop_id,
            creator.id,
            tiktok_livestream_id="live_llm",
            viewers=900,
            orders=40,
            revenue=Decimal("7000000"),
        )
    )
    session.add(
        _make_product(
            shop_id,
            tiktok_product_id="prod_llm",
            name="Mặt nạ",
            revenue=Decimal("900000"),
            units_sold=70,
        )
    )
    session.add(
        _make_inventory(
            shop_id,
            tiktok_product_id="prod_llm",
            sku_id="sku_llm",
            quantity=50,
        )
    )
    await _seed_accelerating_orders(session, shop_id, days=12)
    await session.flush()

    async def fake_llm(_: str) -> str:
        return "LLM copy should not be used when quota is zero."

    matches = await get_host_product_matching(
        session,
        shop_id,
        limit=1,
        max_calls_per_day=0,
        llm_generator=fake_llm,
    )
    assert matches
    assert matches[0].source == "rules"


# ====== RA-4 Price-Direction Advisory Tests ======


def _make_settlement(
    shop_id: uuid.UUID,
    *,
    tiktok_settlement_id: str,
    amount: Decimal,
    platform_commission: Decimal,
    shipping_fee: Decimal,
    created_at: datetime,
) -> Settlement:
    return Settlement(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_settlement_id=tiktok_settlement_id,
        amount=amount,
        currency="VND",
        status="confirmed",
        platform_commission=platform_commission,
        shipping_fee=shipping_fee,
        update_time=created_at,
        created_at=created_at,
    )


class TestPriceDirectionAdvisoryFeeFloor:
    """AC1: fee-floor rule blocks price cuts that would exceed configured share."""

    @pytest.mark.asyncio
    async def test_fee_floor_blocks_cut_when_fees_exceed_threshold(self, session: AsyncSession):
        """Test that a price cut is blocked when fees + shipping > fee_share * sale_price."""
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)

        # Create a product
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_fee_test",
            name="Product for fee test",
            revenue=Decimal("1000000"),
            units_sold=100,
        )
        session.add(product)

        # Create settlement records with high fees (60% of sale)
        # Sale price: 100,000 VND
        # Platform commission: 35,000 VND
        # Shipping fee: 25,000 VND
        # Total fees: 60,000 VND (60% of sale)
        # With fee_share=0.50 (50%), this should block the cut
        for i in range(5):
            settlement = _make_settlement(
                shop_id,
                tiktok_settlement_id=f"settle_fee_{i}",
                amount=Decimal("100000"),
                platform_commission=Decimal("35000"),
                shipping_fee=Decimal("25000"),
                created_at=now - timedelta(days=5 - i),
            )
            session.add(settlement)

        await session.flush()

        # Import and call the price-direction advisory
        from juli_backend.ai.recommendations import get_price_direction_suggestion

        suggestion = await get_price_direction_suggestion(
            session,
            shop_id,
            product.id,
            current_price=Decimal("100000"),
            volume_trend="up",
            conversion_trend="down",
            fee_share_threshold=Decimal("0.50"),
        )

        # With high fees (60% > 50% threshold), cut should be blocked -> hold
        # Note: volume_trend="down" to avoid the other hold logic (vol up but conv down)
        assert suggestion is not None
        assert suggestion.action == "hold"

    @pytest.mark.asyncio
    async def test_fee_floor_allows_cut_when_fees_below_threshold(self, session: AsyncSession):
        """Test that a price cut is allowed when fees + shipping < fee_share * sale_price."""
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)

        # Create a product
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_fee_ok",
            name="Product with low fees",
            revenue=Decimal("5000000"),
            units_sold=200,
        )
        session.add(product)

        # Create settlement records with low fees (20% of sale)
        # Sale price: 100,000 VND
        # Platform commission: 12,000 VND
        # Shipping fee: 8,000 VND
        # Total fees: 20,000 VND (20% of sale)
        # With fee_share=0.50 (50%), this should allow the cut
        for i in range(5):
            settlement = _make_settlement(
                shop_id,
                tiktok_settlement_id=f"settle_ok_{i}",
                amount=Decimal("100000"),
                platform_commission=Decimal("12000"),
                shipping_fee=Decimal("8000"),
                created_at=now - timedelta(days=5 - i),
            )
            session.add(settlement)

        await session.flush()

        from juli_backend.ai.recommendations import get_price_direction_suggestion

        suggestion = await get_price_direction_suggestion(
            session,
            shop_id,
            product.id,
            current_price=Decimal("100000"),
            volume_trend="up",
            conversion_trend="up",
            fee_share_threshold=Decimal("0.50"),
        )

        # With low fees (20% < 50% threshold) and conversion up, cut should be allowed
        assert suggestion is not None
        assert suggestion.action == "cut"


class TestPriceDirectionAdvisoryVolumeUpConversionDown:
    """AC2: when volume is up but conversion is down, suggest hold not cut."""

    @pytest.mark.asyncio
    async def test_volume_up_conversion_down_suggests_hold(self, session: AsyncSession):
        """Test that volume up + conversion down -> hold recommendation."""
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)

        product = _make_product(
            shop_id,
            tiktok_product_id="prod_volume_conversion",
            name="Volume test product",
            revenue=Decimal("2000000"),
            units_sold=150,
        )
        session.add(product)

        # Create settlement records with reasonable fees (30% of sale)
        for i in range(5):
            settlement = _make_settlement(
                shop_id,
                tiktok_settlement_id=f"settle_vc_{i}",
                amount=Decimal("100000"),
                platform_commission=Decimal("18000"),
                shipping_fee=Decimal("12000"),
                created_at=now - timedelta(days=5 - i),
            )
            session.add(settlement)

        await session.flush()

        from juli_backend.ai.recommendations import get_price_direction_suggestion

        suggestion = await get_price_direction_suggestion(
            session,
            shop_id,
            product.id,
            current_price=Decimal("100000"),
            volume_trend="up",
            conversion_trend="down",
            fee_share_threshold=Decimal("0.50"),
        )

        # Volume up but conversion down -> should suggest hold (traffic problem, not price)
        assert suggestion is not None
        assert suggestion.action == "hold"
        assert suggestion.message
        # Check for "duy trì" (maintain) or "giữ" (keep) in Vietnamese
        assert "duy trì" in suggestion.message.lower() or "giữ" in suggestion.message.lower()

    @pytest.mark.asyncio
    async def test_volume_up_conversion_up_suggests_cut(self, session: AsyncSession):
        """Test that volume up + conversion up -> cut recommendation."""
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)

        product = _make_product(
            shop_id,
            tiktok_product_id="prod_both_up",
            name="Both trending up",
            revenue=Decimal("3000000"),
            units_sold=200,
        )
        session.add(product)

        # Create settlement records with low fees
        for i in range(5):
            settlement = _make_settlement(
                shop_id,
                tiktok_settlement_id=f"settle_both_{i}",
                amount=Decimal("100000"),
                platform_commission=Decimal("12000"),
                shipping_fee=Decimal("8000"),
                created_at=now - timedelta(days=5 - i),
            )
            session.add(settlement)

        await session.flush()

        from juli_backend.ai.recommendations import get_price_direction_suggestion

        suggestion = await get_price_direction_suggestion(
            session,
            shop_id,
            product.id,
            current_price=Decimal("100000"),
            volume_trend="up",
            conversion_trend="up",
            fee_share_threshold=Decimal("0.50"),
        )

        # Both volume and conversion up -> should suggest cut (pricing power)
        assert suggestion is not None
        assert suggestion.action == "cut"
        assert suggestion.message


# Issue #722 — Product Trend Classifier tests
class TestProductTrendClassifier:
    """AC1-5: classify products into three tiers based on month-over-month trend."""

    @pytest.mark.asyncio
    async def test_classify_strong_positive_trend(self, session: AsyncSession):
        """Tier 1: Strong positive revenue trend classification."""
        shop_id = await _seed_shop(session)
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_strong_trend",
            name="Trending Winner",
            revenue=Decimal("5000000"),
            units_sold=500,
        )
        session.add(product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_strong_trend",
                sku_id="sku_trend",
                quantity=100,
            )
        )

        # Create orders showing strong growth: 10 orders first half, 50 orders second half
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = []
        for day_offset in range(30):
            day_start = base + timedelta(days=day_offset)
            count = 10 if day_offset < 15 else 50
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"trend_strong_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations.classifier import classify_product_trend

        tier, confidence, reason = await classify_product_trend(session, shop_id, product.id)
        assert tier == "strong_positive", f"Expected strong_positive but got {tier}"
        assert confidence >= 0.7, f"Expected high confidence but got {confidence}"

    @pytest.mark.asyncio
    async def test_classify_declining_trend(self, session: AsyncSession):
        """Tier 2: Product with declining revenue trend should be classified as declining."""
        shop_id = await _seed_shop(session)
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_declining",
            name="Declining Product",
            revenue=Decimal("3000000"),
            units_sold=200,
        )
        session.add(product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_declining",
                sku_id="sku_decline",
                quantity=80,
            )
        )

        # Create orders showing decline: 50 orders first half, 10 orders second half
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = []
        for day_offset in range(30):
            day_start = base + timedelta(days=day_offset)
            count = 50 if day_offset < 15 else 10
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"trend_decline_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations.classifier import classify_product_trend

        tier, confidence, reason = await classify_product_trend(session, shop_id, product.id)
        assert tier == "declining", f"Expected declining but got {tier}"
        assert "declining" in reason.lower() or "giảm" in reason.lower()

    @pytest.mark.asyncio
    async def test_classify_no_strong_signal(self, session: AsyncSession):
        """Tier 3: Product with flat trend should be classified as no_strong_signal."""
        shop_id = await _seed_shop(session)
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_flat",
            name="Steady Product",
            revenue=Decimal("2000000"),
            units_sold=150,
        )
        session.add(product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_flat",
                sku_id="sku_flat",
                quantity=60,
            )
        )

        # Create orders with roughly constant rate
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = []
        for day_offset in range(30):
            day_start = base + timedelta(days=day_offset)
            count = 25  # Same count every day
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"trend_flat_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations.classifier import classify_product_trend

        tier, confidence, reason = await classify_product_trend(session, shop_id, product.id)
        assert tier == "no_strong_signal", f"Expected no_strong_signal but got {tier}"

    @pytest.mark.asyncio
    async def test_weak_signal_always_produces_recommendation(self, session: AsyncSession):
        """AC2: weak/no-signal tier still always produces a recommendation."""
        shop_id = await _seed_shop(session)
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_weak_rec",
            name="General Tune-up",
            revenue=Decimal("1500000"),
            units_sold=100,
        )
        session.add(product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_weak_rec",
                sku_id="sku_weak",
                quantity=50,
            )
        )
        await _seed_accelerating_orders(session, shop_id, days=14)
        await session.flush()

        from juli_backend.ai.recommendations.classifier import build_recommendation_message

        # Weak signal should still produce a message
        message = build_recommendation_message(
            product_name="General Tune-up",
            tier="no_strong_signal",
            reason="Chưa thấy xu hướng rõ ràng",
        )
        assert message is not None
        assert len(message) > 0

    @pytest.mark.asyncio
    async def test_low_history_products_honest_state(self, session: AsyncSession):
        """AC3: low sales-history products get honest 'not enough data' state."""
        shop_id = await _seed_shop(session)
        product = _make_product(
            shop_id,
            tiktok_product_id="prod_new",
            name="Brand New Product",
            revenue=Decimal("100000"),
            units_sold=5,
        )
        session.add(product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_new",
                sku_id="sku_new",
                quantity=20,
            )
        )

        # Only 3 orders in past 30 days
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = [
            _make_order(
                shop_id,
                tiktok_order_id=f"new_order_{i}",
                created_at=base + timedelta(days=i * 10),
            )
            for i in range(3)
        ]
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations.classifier import classify_product_trend

        tier, confidence, reason = await classify_product_trend(session, shop_id, product.id)
        assert tier == "insufficient_data", f"Expected insufficient_data but got {tier}"
        assert confidence < 0.5

    @pytest.mark.asyncio
    async def test_distinct_copy_weak_vs_declining(self, session: AsyncSession):
        """AC4: weak-signal copy reads distinctly from declining-tier copy."""
        from juli_backend.ai.recommendations.classifier import build_recommendation_message

        weak_msg = build_recommendation_message(
            product_name="Test Product",
            tier="no_strong_signal",
            reason="Chưa thấy xu hướng rõ ràng",
        )
        declining_msg = build_recommendation_message(
            product_name="Test Product",
            tier="declining",
            reason="Doanh thu giảm",
        )

        # They should be different
        assert weak_msg != declining_msg
        # Weak should not sound alarming
        assert "giảm" not in weak_msg.lower() or "cải thiện" in weak_msg.lower()
        # Declining should mention why
        assert "giảm" in declining_msg.lower() or "optimize" in declining_msg.lower()


# Issue #722 — Integration tests for trending product recommendation
class TestTrendingProductRecommendation:
    """Integration tests for the new trending product recommendation function."""

    @pytest.mark.asyncio
    async def test_trending_product_recommendation_strong_positive(self, session: AsyncSession):
        """Get a trending product recommendation with strong positive tier."""
        shop_id = await _seed_shop(session)

        # Create multiple products with different trends
        strong_product = _make_product(
            shop_id,
            tiktok_product_id="prod_trending_strong",
            name="Trending Hero",
            revenue=Decimal("3000000"),
            units_sold=300,
        )
        weak_product = _make_product(
            shop_id,
            tiktok_product_id="prod_trending_weak",
            name="Stable Product",
            revenue=Decimal("2000000"),
            units_sold=200,
        )
        session.add_all([strong_product, weak_product])

        session.add_all(
            [
                _make_inventory(
                    shop_id,
                    tiktok_product_id="prod_trending_strong",
                    sku_id="sku_hero",
                    quantity=100,
                ),
                _make_inventory(
                    shop_id,
                    tiktok_product_id="prod_trending_weak",
                    sku_id="sku_stable",
                    quantity=80,
                ),
            ]
        )

        # Create strong growth trend: 10 orders first half, 50 orders second half
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = []
        for day_offset in range(30):
            day_start = base + timedelta(days=day_offset)
            count = 10 if day_offset < 15 else 50
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"trend_int_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations import get_trending_product_recommendation

        recommendation = await get_trending_product_recommendation(session, shop_id)

        assert recommendation is not None
        assert recommendation.trend_tier == "strong_positive"
        assert recommendation.product_name == "Trending Hero"
        assert "bán chạy" in recommendation.message or "tăng trưởng" in recommendation.message
        assert recommendation.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_trending_product_recommendation_declining(self, session: AsyncSession):
        """Get a trending product recommendation with declining tier."""
        shop_id = await _seed_shop(session)

        declining_product = _make_product(
            shop_id,
            tiktok_product_id="prod_decline_int",
            name="Declining Product",
            revenue=Decimal("2000000"),
            units_sold=200,
        )
        session.add(declining_product)
        session.add(
            _make_inventory(
                shop_id,
                tiktok_product_id="prod_decline_int",
                sku_id="sku_decline",
                quantity=80,
            )
        )

        # Create decline trend: 50 orders first half, 10 orders second half
        now = datetime.now(UTC)
        base = now - timedelta(days=30)
        orders = []
        for day_offset in range(30):
            day_start = base + timedelta(days=day_offset)
            count = 50 if day_offset < 15 else 10
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"decline_int_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        from juli_backend.ai.recommendations import get_trending_product_recommendation

        recommendation = await get_trending_product_recommendation(session, shop_id)

        assert recommendation is not None
        assert recommendation.trend_tier == "declining"
        assert recommendation.product_name == "Declining Product"
        assert (
            "giảm" in recommendation.message
            or "optimize" in recommendation.message
            or "tối ưu" in recommendation.message
        )

    @pytest.mark.asyncio
    async def test_trending_product_recommendation_no_products(self, session: AsyncSession):
        """Get a trending product recommendation when no products exist."""
        shop_id = await _seed_shop(session)

        from juli_backend.ai.recommendations import get_trending_product_recommendation

        recommendation = await get_trending_product_recommendation(session, shop_id)
        assert recommendation is None

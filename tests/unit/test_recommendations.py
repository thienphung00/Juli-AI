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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import Creator, InventoryItem, Livestream, Order, Product, Shop, User
from src.recommendations import (
    get_host_product_matching,
    get_product_push_suggestions,
    get_stream_optimization,
)
from src.recommendations.engine import HostProductMatch, ProductPushSuggestion

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
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
    end = datetime.now(timezone.utc) - timedelta(hours=started_hours_ago)
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
    now = datetime.now(timezone.utc)
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
    async def test_product_push_combines_trend_stock_margin(
        self, session: AsyncSession
    ):
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
            assert any(
                ch in item.message for ch in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
            ) or "Nên" in item.message or "sản phẩm" in item.message


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
        engine = importlib.import_module("src.recommendations.engine")
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

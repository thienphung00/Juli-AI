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

from src.data.models import InventoryItem, Order, Product, Shop, User
from src.recommendations import get_product_push_suggestions
from src.recommendations.engine import ProductPushSuggestion

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

"""The quick scan by paid orders for the zero-analytics sandbox shop (fast track P64, D73.3).

A shop read through its own ``sandbox_write`` credential whose 14-day A-34 rows are
all zero gets 1-3 title / description cards (executor ``juli``) on its best sellers
by real paid orders, each with a stored rule-based proposal (Trước / Sau). A real
shop with the same zero analytics gets nothing new (unchanged behaviour).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.ingestion import QUICK_SCAN_DONE
from juli_backend.models.models import ActionCard, Order, OrderItem, Product, Shop, User
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
)
from juli_backend.services.demo_decisions.card_view import build_card_block
from juli_backend.services.onboarding import quick_scan as qs
from juli_backend.services.onboarding.quick_scan_orders import (
    ProductSales,
    orders_proposal,
    propose_description,
    propose_title,
    rank_by_orders,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.reviewer import simulation
from juli_backend.services.shop_diagnosis_daily.orders_source import OrderLine

#: 2026-10-07 10:00 UTC = 17:00 UTC+7; the scan's last full day is 10-06.
SCAN_AT = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
LAST_DAY = date(2026, 10, 6)


@pytest.fixture(autouse=True)
def _quick_scan_env(monkeypatch):
    monkeypatch.delenv(qs.MAX_CARDS_ENV, raising=False)
    monkeypatch.delenv(qs.ENABLED_ENV, raising=False)
    monkeypatch.delenv(qs.TOP_PRODUCTS_ENV, raising=False)
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


def _listing(product_id: str, title: str, description: str = "Áo mềm. Mặc mát.") -> dict:
    return {
        "id": product_id,
        "title": title,
        "status": "ACTIVATE",
        "description": description,
        "brand": {"id": "b1", "name": "JuliWear"},
        "category_chains": [
            {"id": "1", "local_name": "Thời trang nữ", "is_leaf": False},
            {"id": "2", "local_name": "Áo thun", "is_leaf": True},
        ],
        "main_images": [{"uri": f"img-{n}", "width": 800, "height": 800} for n in range(5)],
        "skus": [
            {"id": "s1", "sales_attributes": [{"name": "Màu", "value_name": "Trắng"}]},
            {"id": "s2", "sales_attributes": [{"name": "Màu", "value_name": "Đen"}]},
        ],
    }


class FakeSandboxResources:
    """A-34 at zero for every product (the sandbox), diagnoses and Get Product."""

    def __init__(self, listings: dict[str, dict], diagnoses: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        outer = self

        class Analytics:
            def list_product_performance(self, **kwargs):
                outer.calls.append(("a34", kwargs))
                rows = [
                    {"id": pid, "total_performance": {"gmv": {"amount": "0"}, "sku_orders": 0}}
                    for pid in listings
                ]
                return {"products": rows, "next_page_token": ""}

        class Products:
            def get_diagnoses(self, product_ids):
                outer.calls.append(("diagnoses", list(product_ids)))
                return {"products": [d for d in diagnoses or [] if d["id"] in product_ids]}

            def get_details(self, product_id):
                outer.calls.append(("details", product_id))
                return listings[product_id]

        self.analytics = Analytics()
        self.products = Products()


async def _shop(session, capability: TikTokCapability) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8493{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Sandbox shop",
        tiktok_shop_id=f"tt-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    session.add_all([user, shop])
    await session.flush()
    await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token="access",
        refresh_token="refresh",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=f"merchant-{uuid.uuid4().hex[:6]}",
        capability=capability.value,
        shop_cipher="cipher",
    )
    await session.commit()
    return shop


async def _product(session, shop: Shop, product_id: str, title: str) -> None:
    session.add(
        Product(
            shop_id=shop.id,
            tiktok_product_id=product_id,
            title=title,
            name=title,
            status="ACTIVATE",
            update_time=datetime(2026, 10, 1),
        )
    )
    await session.commit()


async def _paid_order(
    session, shop: Shop, order_id: str, product_id: str, qty: int, price: int, status: str
) -> None:
    created = datetime(2026, 10, 3, 5, 0)
    order = Order(
        shop_id=shop.id,
        tiktok_order_id=order_id,
        status=status,
        total_amount=Decimal(qty * price),
        currency="VND",
        tiktok_created_at=created,
        update_time=created,
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderItem(
            shop_id=shop.id,
            order_id=order.id,
            tiktok_order_id=order_id,
            tiktok_product_id=product_id,
            tiktok_sku_id=f"{product_id}-s",
            quantity=qty,
            unit_price=Decimal(price),
            line_total=Decimal(qty * price),
            update_time=created,
        )
    )
    await session.commit()


async def _seed(session, shop: Shop) -> dict[str, dict]:
    await _product(session, shop, "p-best", "Áo thun nữ")
    await _product(session, shop, "p-second", "Áo thun cotton nữ form rộng tay lỡ cổ tròn basic")
    await _paid_order(session, shop, "o-1", "p-best", 3, 150_000, "confirmed")
    await _paid_order(session, shop, "o-2", "p-second", 1, 120_000, "delivered")
    # A cancelled order never ranks a product.
    await _paid_order(session, shop, "o-3", "p-second", 50, 120_000, "cancelled")
    return {
        "p-best": _listing("p-best", "Áo thun nữ"),
        "p-second": _listing(
            "p-second", "Áo thun cotton nữ form rộng tay lỡ cổ tròn basic JuliWear Trắng Đen"
        ),
    }


async def _scan(session_factory, shop, resources):
    return await qs.run_quick_scan(
        session_factory=session_factory,
        shop_id=shop.id,
        app_key="app",
        app_secret="secret",
        create_resources=lambda _cfg: resources,
        now=SCAN_AT,
    )


async def _cards(session, shop_id) -> list[ActionCard]:
    stmt = (
        select(ActionCard)
        .where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        )
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(stmt)).scalars())


@pytest.mark.asyncio
async def test_a_zero_analytics_sandbox_gets_title_and_description_cards_from_paid_orders(
    session, session_factory
):
    shop = await _shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = FakeSandboxResources(await _seed(session, shop))

    result = await _scan(session_factory, shop, resources)

    assert result.status == QUICK_SCAN_DONE and result.cards == 2, result
    assert resources.calls[1] == ("diagnoses", ["p-best", "p-second"]), "ranked by paid revenue"
    by_product = {}
    for card in await _cards(session, shop.id):
        payload = json.loads(card.recommendation_payload)
        by_product[payload["diagnosis"]["tiktok_product_id"]] = (card, payload)

    best_card, best = by_product["p-best"]
    diagnosis = best["diagnosis"]
    assert diagnosis["lever"]["code"] == "title"
    assert diagnosis["quick_scan"]["source"] == "orders"
    assert diagnosis["main_kpi"] == {
        "key": "aov",
        "label": "AOV",
        "value": "450.000 ₫",
        "raw": 450000.0,
    }
    assert "1 đơn, 3 sản phẩm, doanh thu 450.000 ₫" in diagnosis["trigger"]["sentence"]
    assert diagnosis["recoverable_gmv_per_day"] is None, "no funnel number is claimed"
    assert diagnosis["listing_proposal"] == {
        "field": "title",
        "before": "Áo thun nữ",
        "after": "Áo thun nữ - JuliWear - Trắng, Đen",
    }
    # The second product's title already says it all: its description is proposed.
    _, second = by_product["p-second"]
    assert second["diagnosis"]["lever"]["code"] == "description"
    after = second["diagnosis"]["listing_proposal"]["after"]
    assert after.startswith("<p>Áo thun cotton nữ") and "<li>Danh mục: Áo thun</li>" in after
    assert "<p>Áo mềm.</p><p>Mặc mát.</p>" in after

    # Duyệt shows Trước / Sau; Thực thi has the stored "Sau" as its content.
    block = build_card_block(best_card, best, None)
    assert block is not None
    assert block["reason_short"] == "Sản phẩm bán chạy theo đơn hàng"
    assert block["lever"]["executor"] == "juli"
    assert block["before_after"] == [
        {
            "field": "title",
            "label": "Tiêu đề",
            "before": "Áo thun nữ",
            "after": "Áo thun nữ - JuliWear - Trắng, Đen",
        }
    ]
    planned = simulation.simulate(
        {"id": str(best_card.id), "recommendation": {"card": block, "diagnosis": diagnosis}},
        "execute",
    )["change"]["fields"]
    assert planned[0]["before"] == "Áo thun nữ"
    assert planned[0]["after"] == "Áo thun nữ - JuliWear - Trắng, Đen"


@pytest.mark.asyncio
async def test_a_real_shop_with_zero_analytics_gets_no_orders_cards(session, session_factory):
    shop = await _shop(session, TikTokCapability.SELLER_CONNECT)
    resources = FakeSandboxResources(await _seed(session, shop))

    result = await _scan(session_factory, shop, resources)

    assert result.status == QUICK_SCAN_DONE and result.skipped_reason == "no_candidate"
    assert result.cards == 0 and await _cards(session, shop.id) == []
    assert [kind for kind, _ in resources.calls] == ["a34"], "no orders path, no extra read"


@pytest.mark.asyncio
async def test_a_sandbox_without_paid_orders_writes_nothing(session, session_factory):
    shop = await _shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = FakeSandboxResources({"p-x": _listing("p-x", "Áo")})

    result = await _scan(session_factory, shop, resources)

    assert result.skipped_reason == "no_paid_orders" and result.cards == 0


def test_rank_by_orders_sorts_by_revenue_then_units():
    lines = [
        OrderLine(LAST_DAY, "o1", "a", 1, 100.0),
        OrderLine(LAST_DAY, "o2", "b", 5, 100.0),
        OrderLine(LAST_DAY, "o3", "c", 1, 300.0),
        OrderLine(LAST_DAY, "o3", "c", 1, 0.0),
    ]
    ranked = rank_by_orders(lines, 2)
    assert [s.product_id for s in ranked] == ["c", "b"]
    assert ranked[0] == ProductSales("c", Decimal("300.0"), 2, 1)


def test_the_proposals_use_only_the_listings_own_facts():
    listing = _listing("p", "Áo thun nữ JuliWear")
    assert propose_title(listing) == "Áo thun nữ JuliWear - Trắng, Đen"
    # A category the title lacks is added; nothing is added twice.
    assert (
        propose_title({**listing, "title": "Váy nữ"}) == "Váy nữ - JuliWear - Áo thun - Trắng, Đen"
    )
    assert propose_title({**listing, "title": "Áo thun JuliWear Trắng Đen"}) is None
    assert propose_title({"title": ""}) is None
    description = propose_description({"title": "Áo", "description": ""})
    assert description == "<p>Áo</p>"


def test_no_listing_reason_means_no_card():
    listing = _listing(
        "p", "Áo thun cotton nữ form rộng tay lỡ cổ tròn basic JuliWear Trắng Đen", "x" * 600
    )
    listing["description"] = "<p>" + "x" * 600 + "</p><p>y</p>"
    sales = ProductSales("p", Decimal(100), 1, 1)
    assert orders_proposal(sales, listing, [], StageDiagnosisConfig()) is None

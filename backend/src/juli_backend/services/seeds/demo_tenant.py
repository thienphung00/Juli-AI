"""Seeded demo tenant provisioning — issue #1312 (W6-B, ADR-084 decision 1).

Provides a deterministic, idempotent seed that creates:
- A demo shop (no TikTok credentials)
- A demo user (shop owner)
- Demo products with sufficient historical analytics
- Demo action cards (active, surfaced) for executing the Optimize Product playbook

The demo tenant has no live business association; its data is entirely synthetic.
Calling seed_demo_tenant twice on the same database leaves exactly one demo shop,
one product set, and one card set — no duplicates, no drift.

Configuration: DEMO_SHOP_ID environment variable is required and must be set to
a UUID string. If unset, seed_demo_tenant raises KeyError loudly rather than
silently falling back.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import ActionCard, Product, Shop, User
from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
)


def _get_demo_shop_id() -> str:
    """Retrieve DEMO_SHOP_ID from environment; fail loudly if unset.

    Raises:
        KeyError: if DEMO_SHOP_ID is not set.
    """
    shop_id = os.getenv("DEMO_SHOP_ID", "").strip()
    if not shop_id:
        raise KeyError(
            "DEMO_SHOP_ID environment variable is required but not set. "
            "Set it to a UUID string before calling seed_demo_tenant."
        )
    return shop_id


async def seed_demo_tenant(session: AsyncSession) -> None:
    """Seed a deterministic demo tenant — idempotent and reproducible.

    Creates a demo shop, user, products, and action cards if they do not
    already exist. Running this function twice on the same database leaves
    exactly one demo shop and one set of products/cards.

    Args:
        session: AsyncSession for database operations.

    Raises:
        KeyError: if DEMO_SHOP_ID environment variable is not set.

    Behavior:
        - Demo user and shop are created by their fixed UUIDs (read from
          DEMO_SHOP_ID and derived deterministically).
        - Products are keyed by tiktok_product_id; calling twice does not
          create duplicates.
        - Action cards are keyed by (shop_id, workflow_key); calling twice
          does not create duplicates (upserted via merge semantics).
        - All timestamps are set to "now" (the time of the seed run).
    """
    demo_shop_id_str = _get_demo_shop_id()
    demo_shop_id = uuid.UUID(demo_shop_id_str)

    # Derive demo user ID deterministically from shop ID
    # (same seed run always produces same user)
    demo_user_uuid_int = uuid.UUID("12345678-1234-5678-1234-567812345678").int
    demo_user_id = uuid.UUID(int=(int(demo_shop_id) ^ demo_user_uuid_int))

    now = datetime.now(UTC)

    # === Create demo user (idempotent) ===
    stmt = select(User).where(User.id == demo_user_id)
    existing_user = await session.scalar(stmt)

    if not existing_user:
        demo_user = User(
            id=demo_user_id,
            phone="+84-demo-tenant",
            display_name="Demo Tenant",
            created_at=now,
            updated_at=now,
        )
        session.add(demo_user)
        await session.flush()  # Flush to ensure user is in DB before FK references

    # === Create demo shop (idempotent) ===
    shop_stmt = select(Shop).where(Shop.id == demo_shop_id)
    existing_shop = await session.scalar(shop_stmt)

    if not existing_shop:
        demo_shop = Shop(
            id=demo_shop_id,
            user_id=demo_user_id,
            shop_name="Demo Shop",
            tiktok_shop_id=None,  # No vendor identity
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(demo_shop)
        await session.flush()  # Flush to ensure shop is in DB before FK references

    # === Seed demo products (idempotent by tiktok_product_id) ===
    demo_products = [
        {
            "tiktok_product_id": "demo-product-001",
            "title": "Demo Wireless Headphones",
            "name": "Demo Wireless Headphones",
            "category": "Electronics",
            "price": 49.99,
            "inventory": 50,
            "status": "active",
            "revenue": 500.00,
            "units_sold": 10,
        },
        {
            "tiktok_product_id": "demo-product-002",
            "title": "Demo Phone Case",
            "name": "Demo Phone Case",
            "category": "Accessories",
            "price": 12.99,
            "inventory": 200,
            "status": "active",
            "revenue": 390.00,
            "units_sold": 30,
        },
        {
            "tiktok_product_id": "demo-product-003",
            "title": "Demo USB Cable",
            "name": "Demo USB Cable",
            "category": "Cables",
            "price": 5.99,
            "inventory": 500,
            "status": "active",
            "revenue": 180.00,
            "units_sold": 30,
        },
    ]

    for prod_data in demo_products:
        product_stmt = select(Product).where(
            (Product.shop_id == demo_shop_id)
            & (Product.tiktok_product_id == prod_data["tiktok_product_id"])
        )
        existing_product = await session.scalar(product_stmt)

        if not existing_product:
            product = Product(
                id=uuid.uuid4(),
                shop_id=demo_shop_id,
                tiktok_product_id=prod_data["tiktok_product_id"],
                title=prod_data["title"],
                name=prod_data["name"],
                category=prod_data["category"],
                price=prod_data["price"],
                price_currency="USD",
                inventory=prod_data["inventory"],
                audit_status="approved",
                status=prod_data["status"],
                revenue=prod_data["revenue"],
                units_sold=prod_data["units_sold"],
                update_time=now,
                created_at=now,
                updated_at=now,
            )
            session.add(product)

    # === Seed analytics data (performance intervals) ===
    # Provide sufficient analytics history so action card scoring can work
    for days_back in range(0, 30):
        interval_date = (now - timedelta(days=days_back)).date()
        interval_stmt = select(AnalyticsPerformanceInterval).where(
            (AnalyticsPerformanceInterval.shop_id == demo_shop_id)
            & (AnalyticsPerformanceInterval.start_date == interval_date)
        )
        existing_interval = await session.scalar(interval_stmt)

        if not existing_interval:
            interval = AnalyticsPerformanceInterval(
                id=uuid.uuid4(),
                shop_id=demo_shop_id,
                snapshot_key=f"demo-daily-{interval_date}",
                grain="daily",
                start_date=interval_date,
                end_date=interval_date,
                gmv=100.00 + (days_back * 10),  # Increasing revenue
                gmv_currency="USD",
                click_through_rate=0.05,
                click_order_rate=0.02,
                visitors=100 + (days_back * 5),
                impressions=500 + (days_back * 20),
                conversion_rate=0.10,
                active_products=3,
                update_time=now,
                created_at=now,
                updated_at=now,
            )
            session.add(interval)

    await session.flush()

    # === Seed demo action cards (idempotent by shop_id, workflow_key) ===
    card_stmt = select(ActionCard).where(
        (ActionCard.shop_id == demo_shop_id)
        & (ActionCard.workflow_key == OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key)
    )
    existing_card = await session.scalar(card_stmt)

    if not existing_card:
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=demo_shop_id,
            workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
            priority=1,
            severity="medium",
            title="Optimize Your Product Listing",
            description=(
                "Improve your product's visibility and sales by optimizing "
                "the title, description, and pricing based on market trends "
                "and SEO keywords."
            ),
            recommendation_payload='{"product_id": "demo-product-001"}',
            status="active",
            surfaced_at=now,  # Set surfaced_at so card appears in /v1/demo/decisions
            suppressed_reason=None,
            computed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(card)

    # Commit all changes
    await session.commit()

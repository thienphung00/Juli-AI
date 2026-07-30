"""Unit tests for silver orders/returns cutover (#607)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
    Order,
    Return,
    Shop,
    User,
)
from juli_backend.repositories.repos import (
    BronzeOrderRawPayloadsRepo,
    BronzeReturnRawPayloadsRepo,
    OrdersRepo,
)
from juli_backend.services.etl.silver_promotion import (
    SilverOrdersReturnsPromoter,
)


@pytest_asyncio.fixture
async def medallion_session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS bronze"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS silver"))
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    User.__table__,
                    Shop.__table__,
                    Order.__table__,
                    Return.__table__,
                    BronzeOrderRawPayload.__table__,
                    BronzeReturnRawPayload.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84936500607", display_name="Silver Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Silver Test Shop",
            tiktok_shop_id="607_silver_shop",
        )
        session.add(shop)
        await session.flush()
        shop_id = shop.id
        yield session, shop_id
        await session.rollback()
    await eng.dispose()


@pytest.mark.asyncio
async def test_bronze_append_to_silver_order_upsert_minimal_fixture(medallion_session):
    """Bronze append → silver upsert without gold KPI or live Partner (#607)."""
    session, shop_id = medallion_session
    bronze_repo = BronzeOrderRawPayloadsRepo(session)
    promoter = SilverOrdersReturnsPromoter(session)
    received_at = datetime(2026, 7, 30, 14, 0, tzinfo=UTC)

    bronze_rows = await bronze_repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": "webhook",
                "payload": {
                    "order_id": "577000607",
                    "order_status": "AWAITING_SHIPMENT",
                    "total_amount": "99.50",
                    "currency": "VND",
                    "update_time": int(received_at.timestamp()),
                },
                "received_at": received_at,
                "tiktok_order_id": "577000607",
                "source_event_id": "evt-607-order",
            },
        ]
    )

    order = await promoter.promote_order(bronze_rows[0])
    assert order.tiktok_order_id == "577000607"
    assert order.shop_id == shop_id

    # Idempotent re-promote updates same natural key
    order_again = await promoter.promote_order(bronze_rows[0])
    assert order_again.id == order.id

    result = await session.execute(
        select(Order).where(
            Order.shop_id == shop_id,
            Order.tiktok_order_id == "577000607",
        )
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_bronze_append_to_silver_return_upsert_resolves_order(medallion_session):
    session, shop_id = medallion_session
    orders_repo = OrdersRepo(session)
    update_time = datetime(2026, 7, 30, 14, 0, tzinfo=UTC).replace(tzinfo=None)
    await orders_repo.upsert(
        shop_id=shop_id,
        tiktok_order_id="577000607",
        status="confirmed",
        total_amount=99.50,
        currency="VND",
        update_time=update_time,
    )

    bronze_repo = BronzeReturnRawPayloadsRepo(session)
    promoter = SilverOrdersReturnsPromoter(session)
    received_at = datetime(2026, 7, 30, 14, 30, tzinfo=UTC)

    bronze_rows = await bronze_repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": "webhook",
                "payload": {
                    "return_id": "900000607",
                    "order_id": "577000607",
                    "refund_amount": "99.50",
                    "status": "pending_review",
                    "update_time": int(received_at.timestamp()),
                },
                "received_at": received_at,
                "tiktok_return_id": "900000607",
                "tiktok_order_id": "577000607",
                "source_event_id": "evt-607-return",
            },
        ]
    )

    ret = await promoter.promote_return(bronze_rows[0])
    assert ret.tiktok_return_id == "900000607"
    assert ret.tiktok_order_id == "577000607"
    assert ret.order_id is not None

    result = await session.execute(
        select(Return).where(
            Return.shop_id == shop_id,
            Return.tiktok_return_id == "900000607",
        )
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_orders_repo_writes_silver_schema(medallion_session):
    session, shop_id = medallion_session
    repo = OrdersRepo(session)
    update_time = datetime(2026, 7, 30, 15, 0, tzinfo=UTC).replace(tzinfo=None)
    order = await repo.upsert(
        shop_id=shop_id,
        tiktok_order_id="577000608",
        status="confirmed",
        total_amount=10,
        currency="VND",
        update_time=update_time,
    )
    assert Order.__table__.schema == "silver"
    assert order.tiktok_order_id == "577000608"

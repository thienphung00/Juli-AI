"""Unit tests for bronze orders/returns raw payload landing (#605)."""

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
    Shop,
    User,
)
from juli_backend.repositories.repos import (
    BronzeOrderRawPayloadsRepo,
    BronzeReturnRawPayloadsRepo,
)


@pytest_asyncio.fixture
async def bronze_session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS bronze"))
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    User.__table__,
                    Shop.__table__,
                    BronzeOrderRawPayload.__table__,
                    BronzeReturnRawPayload.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84936500605", display_name="Bronze Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Bronze Test Shop",
            tiktok_shop_id="605_bronze_shop",
        )
        session.add(shop)
        await session.flush()
        shop_id = shop.id
        yield session, shop_id
        await session.rollback()
    await eng.dispose()


@pytest.mark.asyncio
async def test_bronze_append_batch_repo_minimal_fixture_no_live_partner(bronze_session):
    session, shop_id = bronze_session
    repo = BronzeOrderRawPayloadsRepo(session)
    received_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

    rows = await repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": "webhook",
                "payload": {"order_id": "577000001", "status": "UNPAID"},
                "received_at": received_at,
                "tiktok_order_id": "577000001",
                "source_event_id": "evt-order-1",
            },
            {
                "shop_id": shop_id,
                "ingest_source": "targeted_fetch",
                "payload": {"order_id": "577000002", "status": "AWAITING_SHIPMENT"},
                "received_at": received_at,
                "tiktok_order_id": "577000002",
                "source_event_id": "fetch-page-1",
            },
        ]
    )

    assert len(rows) == 2
    result = await session.execute(
        select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop_id)
    )
    persisted = result.scalars().all()
    assert len(persisted) == 2
    assert {row.tiktok_order_id for row in persisted} == {"577000001", "577000002"}


@pytest.mark.asyncio
async def test_bronze_append_batch_empty_returns_empty(bronze_session):
    session, _shop_id = bronze_session
    repo = BronzeOrderRawPayloadsRepo(session)
    assert await repo.append_batch([]) == []


@pytest.mark.asyncio
async def test_bronze_return_append_batch_inserts_rows(bronze_session):
    session, shop_id = bronze_session
    repo = BronzeReturnRawPayloadsRepo(session)
    received_at = datetime(2026, 7, 30, 12, 30, tzinfo=UTC)

    rows = await repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": "webhook",
                "payload": {"return_id": "900000001", "order_id": "577000001"},
                "received_at": received_at,
                "tiktok_return_id": "900000001",
                "tiktok_order_id": "577000001",
                "source_event_id": "evt-return-1",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0].tiktok_return_id == "900000001"

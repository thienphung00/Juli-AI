"""The bank's shop: `seed_reco_shop` (three products, two weeks of orders, traffic, ads, a group
campaign, vouchers, the seller's costs) plus what Chat cases need beside it: a stock-out and an
unlisting in the stock history, one open draft card, and the Connector's voucher-list settings
(two vouchers). Every figure is invented. Seeded once per session into a SQLite file; the bank
only reads it."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.stock_alert import ShopeeStockHistory
from tests.support.shopee_analytics import CUR_END, CUR_START
from tests.support.shopee_reco import seed_reco_shop

SQLITE_MAP = {"schema_translate_map": {"ops": None, "bronze": None, "gold": None, "silver": None}}


def extras(sid: uuid.UUID) -> list[Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    out: list[Any] = [
        ShopeeStockHistory(
            shop_id=sid,
            item_id="1001",
            variation_id="",
            read_at=datetime(2026, 10, 5, 10),
            available=0,
            sellable=0,
            listing_status="normal",
        ),
        ShopeeStockHistory(
            shop_id=sid,
            item_id="1002",
            variation_id="",
            read_at=datetime(2026, 10, 6, 10),
            available=5,
            sellable=5,
            listing_status="unlisted",
        ),
        ShopProposal(
            shop_id=sid,
            platform="shopee",
            cycle="c1",
            kind="price",
            subject_type="item",
            item_id="1001",
            subject_label="Synthetic",
            change_before={},
            change_after={"x": 1},
            reason="synthetic",
            status="draft",
            code="JC-2610-0001",
            created_at=now,
            updated_at=now,
        ),
    ]
    for vid, name, amount in ((11, "SYN Giảm 5k", 5_000), (12, "SYN Giảm 10k", 10_000)):
        out.append(
            PlatformPromotion(
                shop_id=sid,
                platform="shopee",
                promo_type="voucher",
                program_name=name,
                starts_at=datetime.combine(CUR_START, datetime.min.time()),
                ends_at=datetime.combine(CUR_END, datetime.min.time()),
                ordinal=0,
                period_start=CUR_END,
                period_end=CUR_END,
                order_type="none",
                extra={"voucher_id": vid, "discount_amount": amount, "min_spend": 50_000},
                source="connector",
                source_rank=1,
                source_version="syn-1",
                captured_at=datetime.combine(CUR_END, datetime.min.time()),
                updated_at=now,
            )
        )
    return out


async def seed_into(session: AsyncSession) -> uuid.UUID:
    seeded = await seed_reco_shop(session)
    session.add_all(extras(seeded.shop_id))
    await session.flush()
    return seeded.shop_id


def build_sqlite(path: Path) -> uuid.UUID:
    """Create every table in a SQLite file and seed the bank's shop; returns its id."""
    from juli_backend.database.database import Base

    async def go() -> uuid.UUID:
        eng = create_async_engine(f"sqlite+aiosqlite:///{path}", execution_options=SQLITE_MAP)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, expire_on_commit=False)() as s:
            sid = await seed_into(s)
            await s.commit()
        await eng.dispose()
        return sid

    return asyncio.run(go())


@asynccontextmanager
async def sqlite_factory(path: Path):
    """A read session factory over the seeded file (one engine per test)."""
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{path}", execution_options=SQLITE_MAP, poolclass=NullPool
    )
    mk = async_sessionmaker(eng, expire_on_commit=False)

    @asynccontextmanager
    async def factory():
        async with mk() as s:
            yield s

    try:
        yield factory
    finally:
        await eng.dispose()

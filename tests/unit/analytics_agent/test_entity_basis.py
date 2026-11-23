"""Entity rows use the shop headline basis (registry / engine: paid, qty > 0, no refund status,
the line's order day): the entities of a partition add up to the shop total. Runs the real
`ServiceData` SQL on in-memory SQLite with synthetic order lines."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.models.shopee_profit import ShopeeAffiliateLine, ShopeeOrderLine
from juli_backend.services.analytics_agent.data_service import ServiceData
from juli_backend.services.shopee_profit.order_profit import REFUND_STATUSES

SHOP = uuid.uuid4()
A, B = date(2026, 11, 16), date(2026, 11, 22)


class SqliteData(ServiceData):
    async def _q(self, sql: str, **p: Any) -> list[dict[str, Any]]:  # SQLite stores uuid as hex
        from sqlalchemy import text

        async with self._f() as s:
            res = await s.execute(text(sql), {"s": self.shop.hex, **p})
            return [dict(r._mapping) for r in res]


def _line(
    ref: str,
    status: str,
    day: date,
    price: int,
    voucher: int,
    code: str | None,
    paid: bool = True,
    qty: int = 1,
    item: str = "p1",
) -> ShopeeOrderLine:
    at = datetime(day.year, day.month, day.day, 10)
    return ShopeeOrderLine(
        shop_id=SHOP, platform="shopee", order_ref=ref, line_no=1, ordered_at=at, day=day,
        status=status, item_id=item, qty=qty, original_price=Decimal(price),
        deal_price=Decimal(price),
        shop_voucher_share=Decimal(voucher), voucher_code=code, affiliate=False,
        paid_at=at if paid else None, source="test", source_version="t",
    )  # fmt: skip


@pytest_asyncio.fixture
async def data() -> AsyncIterator[SqliteData]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for t in (ShopeeOrderLine, ShopeeAffiliateLine):
            await conn.run_sync(lambda c, t=t: t.__table__.create(c))  # type: ignore[attr-defined]
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add_all(
            [
                _line("o1", "delivered", date(2026, 11, 17), 100, 10, "VC-A"),
                _line("o2", "in_transit", date(2026, 11, 18), 200, 20, "VC-B"),
                _line("o3", "delivered", date(2026, 11, 19), 300, 0, None),
                _line(
                    "o4", "cancelled", date(2026, 11, 19), 50, 0, None
                ),  # paid: counts (headline)
                _line("o5", "returned", date(2026, 11, 20), 999, 99, "VC-A"),  # refund: never
                _line(
                    "o6", "delivered", date(2026, 11, 20), 888, 0, None, paid=False
                ),  # never paid
                _line("o7", "delivered", date(2026, 11, 25), 777, 0, None),  # outside the window
            ]
        )
        await s.commit()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    yield SqliteData(factory, SHOP)
    await engine.dispose()


async def test_voucher_plus_no_voucher_is_the_shop_total(data: SqliteData) -> None:
    whole = await data.entity_totals("all", A, B)
    v = await data.entity_totals("voucher", A, B)
    n = await data.entity_totals("no_voucher", A, B)
    assert whole["orders"] == 4 and float(whole["gmv"]) == 650.0  # o1 o2 o3 o4
    assert v["orders"] + n["orders"] == whole["orders"]
    assert float(v["gmv"]) + float(n["gmv"]) == float(whole["gmv"])
    assert float(v["cost"]) == 30.0  # the voucher cost of o1 + o2


async def test_per_voucher_rows_partition_the_voucher_total(data: SqliteData) -> None:
    rows = await data.voucher_rows(A, B)
    v = await data.entity_totals("voucher", A, B)
    assert {r["code"] for r in rows} == {"VC-A", "VC-B"}  # the returned VC-A line is not counted
    assert sum(r["orders"] for r in rows) == v["orders"]
    assert sum(float(r["gmv"]) for r in rows) == float(v["gmv"])


async def test_one_product_is_a_subset_of_the_whole(data: SqliteData) -> None:
    whole = await data.entity_totals("all", A, B)
    one = await data.entity_totals("all", A, B, "p1")
    other = await data.entity_totals("all", A, B, "p2")
    assert one["orders"] == whole["orders"] and other["orders"] == 0


def test_basis_is_built_from_the_registry_refund_statuses() -> None:
    basis = ServiceData._sales_basis()
    assert "paid_at is not null" in basis and "qty > 0" in basis
    for st in REFUND_STATUSES:
        assert f"'{st.value}'" in basis
    assert "in_transit" not in basis and "delivered" not in basis  # no hardcoded counted set


@pytest.mark.parametrize("kind", ["voucher", "no_voucher", "affiliate", "all"])
async def test_every_kind_runs(data: SqliteData, kind: str) -> None:
    assert {"orders", "gmv", "cost"} <= set(await data.entity_totals(kind, A, B))

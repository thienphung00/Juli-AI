"""P101 W2 M3 / M4 on real Postgres, as the runtime role under the shop's scope:
``DbCanonicalWriter`` writes ``order_lines`` / ``order_settlements`` (platform ``tiktok``).

- writing twice leaves the same rows;
- a Connector row does not overwrite an API row (it only fills NULL columns);
- the mapper's aware-UTC times are stored as ``timestamptz`` and ``day`` is the VN date
  (a 03:00 VN order is the previous UTC date but its own VN day).

Synthetic tenants only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ingest.canonical import OrderLine, OrderSettlement
from juli_backend.services.ingest.canonical_writer import DbCanonicalWriter
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

D = Decimal
AT_0300_VN = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)  # 03:00 on 5 Oct in Vietnam


def _line(shop_id: uuid.UUID, ref: str, **over) -> OrderLine:
    values = {
        "shop_id": shop_id,
        "platform": "tiktok",
        "order_ref": ref,
        "line_no": 0,
        "ordered_at": AT_0300_VN,
        "status": "delivered",
        "item_id": "item-1",
        "variation_id": "var-1",
        "qty": 1,
        "original_price": D("100000"),
        "deal_price": D("90000"),
        "source": "api",
        "source_version": "tiktok:test",
        **over,
    }
    return OrderLine(**values)


def _settlement(shop_id: uuid.UUID, ref: str, **over) -> OrderSettlement:
    values = {
        "shop_id": shop_id,
        "platform": "tiktok",
        "order_ref": ref,
        "source": "api",
        "source_rank": 4,
        "source_version": "tiktok:test",
        "payout": D("70000"),
        **over,
    }
    return OrderSettlement(**values)


async def _write(shop_id: uuid.UUID, lines, settlements) -> tuple[int, int]:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            writer = DbCanonicalWriter(session)
            counts = (
                await writer.upsert_order_lines(shop_id, "tiktok", lines),
                await writer.upsert_settlements(shop_id, "tiktok", settlements),
            )
        await session.commit()
    return counts


async def _rows(shop_id: uuid.UUID, sql: str):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(sql))).all()


async def test_writing_twice_is_the_same_rows(two_tenants):
    shop = two_tenants[0].shop_id
    ref = f"w2-{uuid.uuid4().hex[:12]}"
    lines = [_line(shop, ref), _line(shop, ref, line_no=1, variation_id="var-2")]
    settlements = [_settlement(shop, ref, fee_other=D("4000"))]
    sql = (
        "SELECT line_no, status, deal_price, day, source, source_rank FROM public.order_lines "
        f"WHERE order_ref = '{ref}' ORDER BY line_no"
    )

    assert await _write(shop, lines, settlements) == (2, 1)
    first = await _rows(shop, sql)
    assert await _write(shop, lines, settlements) == (2, 1)

    assert await _rows(shop, sql) == first
    assert len(first) == 2 and {r.source for r in first} == {"api"}
    (income,) = await _rows(
        shop,
        f"SELECT count(*) AS n, max(fee_other) AS fee_other FROM public.order_settlements "
        f"WHERE order_ref = '{ref}'",
    )
    assert (income.n, income.fee_other) == (1, D("4000"))


async def test_a_connector_row_does_not_overwrite_an_api_row(two_tenants):
    shop = two_tenants[0].shop_id
    ref = f"w2-{uuid.uuid4().hex[:12]}"
    await _write(shop, [_line(shop, ref)], [_settlement(shop, ref)])

    await _write(
        shop,
        [_line(shop, ref, source="extension", status="cancelled", fee_fixed=D("9000"))],
        [_settlement(shop, ref, source="extension", source_rank=3, payout=D("1"))],
    )

    (line,) = await _rows(
        shop, f"SELECT status, source, fee_fixed FROM public.order_lines WHERE order_ref = '{ref}'"
    )
    (income,) = await _rows(
        shop, f"SELECT payout, source FROM public.order_settlements WHERE order_ref = '{ref}'"
    )
    assert (line.status, line.source, line.fee_fixed) == ("delivered", "api", D("9000"))
    assert (income.payout, income.source) == (D("70000"), "api")


async def test_times_are_timestamptz_and_day_is_the_vn_date(two_tenants):
    shop = two_tenants[0].shop_id
    ref = f"w2-{uuid.uuid4().hex[:12]}"
    await _write(shop, [_line(shop, ref)], [])

    (row,) = await _rows(
        shop,
        "SELECT ordered_at, day, pg_typeof(ordered_at)::text AS typ "
        f"FROM public.order_lines WHERE order_ref = '{ref}'",
    )
    assert row.typ == "timestamp with time zone"
    assert row.ordered_at == AT_0300_VN
    assert row.ordered_at.astimezone(UTC).date() == date(2026, 10, 4)
    assert row.day == date(2026, 10, 5)


async def test_a_row_of_another_shop_is_refused(two_tenants):
    shop, other = two_tenants[0].shop_id, two_tenants[1].shop_id
    with pytest.raises(ValueError, match="outside") as excinfo:
        await _write(shop, [_line(other, "x")], [])
    assert "shop / platform" in str(excinfo.value)

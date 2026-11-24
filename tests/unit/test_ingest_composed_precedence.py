"""The composed precedence rule (``rank_guard.ranked_set`` / ``ranked_where``), on SQLite: owner
2026-11-18 (API > Connector > file; a lower rank only fills NULLs; a NULL never clears) composed
with R7 (at an equal rank the newer capture wins). One expression path per column, on the
gateway's ranked metric upsert and on the line / settlement tables. Synthetic values only; the
same statements run on Postgres in ``tests/integration/test_ingest_composed_precedence_db.py``.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from juli_backend.models.ingest import IngestRawPayload, PlatformDailyMetric
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.ingest.rank_guard import (
    excluded_payload_captured_at,
    payload_captured_at,
    ranked_set,
    ranked_where,
)
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.ingest.schemas import ShopeeOrderLineRow
from juli_backend.services.ingest.writers import write_order_lines
from tests.support.builders import make_tenant
from tests.unit.test_shopee_file_datasets import _body, _ingest, _rows, _shop

CARD = "psd_label_product_card"
EARLY = "2026-10-29T09:20:00+07:00"
LATE = "2026-10-29T09:40:00+07:00"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _post(source: str, captured_at: str, **kpis: Any) -> dict[str, Any]:
    rows = [{"date": "2026-10-01", "source": CARD, **kpis}]
    return _body(
        rows,
        source=source,
        source_version=f"{source}-{captured_at[11:13]}{captured_at[14:16]}",
        captured_at=captured_at,
    )


async def _shop_row(session, shop) -> PlatformDailyMetric:
    (row,) = [m for m in await _rows(session, PlatformDailyMetric, shop) if m.segment == "all"]
    return row


async def _send(session, shop, *posts: dict[str, Any]) -> PlatformDailyMetric:
    for post in posts:
        await _ingest(session, shop, "traffic_overview", post)
    return await _shop_row(session, shop)


# ------------------------------------------------------------ the gateway's ranked metric upsert


async def test_equal_rank_a_newer_capture_with_a_value_replaces(session):
    shop = await _shop(session)
    row = await _send(
        session,
        shop,
        _post("extension", EARLY, sales=900, orders=4),
        _post("extension", LATE, sales=950),
    )
    assert (row.gmv, row.orders) == (Decimal("950"), 4)
    assert (row.captured_at.hour, row.captured_at.minute, row.source_version) == (
        2,
        40,
        "extension-0940",
    )


async def test_equal_rank_a_newer_capture_with_a_null_keeps_the_stored_value(session):
    shop = await _shop(session)
    row = await _send(
        session,
        shop,
        _post("extension", EARLY, sales=900, orders=4),
        _post("extension", LATE, orders=5),
    )
    assert (row.gmv, row.orders) == (Decimal("900"), 5)
    assert row.source_version == "extension-0940"


async def test_equal_rank_an_older_capture_is_ignored_even_over_a_null(session):
    shop = await _shop(session)
    row = await _send(
        session,
        shop,
        _post("extension", LATE, sales=950),
        _post("extension", EARLY, sales=900, orders=7),
    )
    assert (row.gmv, row.orders) == (Decimal("950"), None)
    assert (row.captured_at.minute, row.source_version) == (40, "extension-0940")


async def test_a_lower_rank_fills_a_null_and_the_provenance_stays_with_the_higher(session):
    shop = await _shop(session)
    row = await _send(
        session,
        shop,
        _post("extension", EARLY, sales=900),
        _post("file", LATE, sales=1000, orders=4),
    )
    assert (row.gmv, row.orders) == (Decimal("900"), 4)
    assert (row.source, row.source_rank, row.source_version) == ("extension", 3, "extension-0920")
    assert row.captured_at.minute == 20


async def test_a_higher_rank_replaces_even_with_an_older_capture(session):
    shop = await _shop(session)
    row = await _send(
        session,
        shop,
        _post("file", LATE, sales=1000, orders=4),
        _post("extension", EARLY, sales=900),
    )
    assert (row.gmv, row.orders) == (Decimal("900"), 4)
    assert (row.source, row.source_rank, row.captured_at.minute) == ("extension", 3, 20)


# ------------------------------------------------------------ the line tables (payload captures)

ORDER = f"{7:032x}"
AT = datetime(2026, 10, 1, 10, 0)


async def _payload(session, shop_id, source: str, captured_at: datetime) -> uuid.UUID:
    raw = IngestRawPayload(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        dataset="order_lines",
        source=source,
        source_version=f"{source}-1",
        captured_at=captured_at,
        received_at=captured_at,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 1),
        granularity="day",
        order_type="placed",
        content_hash=hashlib.sha256(f"{source}{captured_at}".encode()).hexdigest(),
        row_count=1,
        payload={},
    )
    session.add(raw)
    await session.flush()
    return raw.id


async def _write(session, shop_id, source: str, rank: int, captured: datetime, **over: Any):
    values = {
        "order_ref": ORDER,
        "ordered_at": AT,
        "status": "delivered",
        "sku": "G1",
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        **over,
    }
    provenance = {
        "shop_id": shop_id,
        "platform": "shopee",
        "source": source,
        "source_rank": rank,
        "source_version": f"{source}-{captured.minute}",
        "raw_payload_id": await _payload(session, shop_id, source, captured),
        "updated_at": captured,
    }
    line = ShopeeOrderLineRow.model_validate(values)
    await write_order_lines(session, [line], None, provenance)


async def _line(session) -> ShopeeOrderLine:
    stmt = select(ShopeeOrderLine).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


T1, T2 = datetime(2026, 10, 29, 2, 20), datetime(2026, 10, 29, 2, 40)


async def test_order_line_equal_rank_newer_value_replaces_and_newer_null_keeps(session):
    _, shop = await make_tenant(session)
    await _write(session, shop.id, "extension", 3, T1, fee_fixed=Decimal(1_000))
    await _write(session, shop.id, "extension", 3, T2, deal_price=Decimal(80_000))
    line = await _line(session)
    assert (line.deal_price, line.fee_fixed, line.source_version) == (
        Decimal(80_000),
        Decimal(1_000),
        "extension-40",
    )


async def test_order_line_equal_rank_older_capture_is_ignored(session):
    _, shop = await make_tenant(session)
    await _write(session, shop.id, "extension", 3, T2)
    await _write(
        session, shop.id, "extension", 3, T1, deal_price=Decimal(70_000), fee_fixed=Decimal(500)
    )
    line = await _line(session)
    assert (line.deal_price, line.fee_fixed, line.source_version) == (
        Decimal(90_000),
        None,
        "extension-40",
    )


async def test_order_line_lower_rank_fills_a_null_and_keeps_the_provenance(session):
    _, shop = await make_tenant(session)
    await _write(session, shop.id, "extension", 3, T1)
    await _write(
        session, shop.id, "file", 2, T2, deal_price=Decimal(70_000), fee_fixed=Decimal(500)
    )
    line = await _line(session)
    assert (line.deal_price, line.fee_fixed) == (Decimal(90_000), Decimal(500))
    assert (line.source, line.source_rank, line.source_version) == ("extension", 3, "extension-20")


async def test_order_line_higher_rank_replaces_even_when_older(session):
    _, shop = await make_tenant(session)
    await _write(session, shop.id, "file", 2, T2, fee_fixed=Decimal(500))
    await _write(session, shop.id, "extension", 3, T1, deal_price=Decimal(80_000))
    line = await _line(session)
    assert (line.deal_price, line.fee_fixed) == (Decimal(80_000), Decimal(500))
    assert (line.source, line.source_rank, line.source_version) == ("extension", 3, "extension-20")


# ------------------------------------------------------------ one expression path, rendered


def test_the_line_tables_name_the_renamed_table_and_excluded_in_the_capture_subqueries():
    """``literal_column`` carries the table's own name (``table.name``, the T5 name after the
    rename) and ``excluded`` by name: neither turns into a cross join in the subquery."""
    from sqlalchemy.dialects.postgresql import insert

    table = ShopeeOrderLine.__table__
    stmt = insert(ShopeeOrderLine).values(
        id=uuid.uuid4(), shop_id=uuid.uuid4(), platform="shopee", order_ref=ORDER, line_no=1
    )
    captures = {
        "stored_captured": payload_captured_at(table),
        "incoming_captured": excluded_payload_captured_at(),
    }
    upsert = stmt.on_conflict_do_update(
        index_elements=["shop_id", "platform", "order_ref", "line_no"],
        set_=ranked_set(table, stmt.excluded, ["fee_fixed", "source"], ["source"], **captures),
        where=ranked_where(table, stmt.excluded, **captures),
    )
    sql = str(upsert.compile(dialect=postgresql.dialect()))
    assert table.name == "order_lines"
    assert "order_lines.raw_payload_id" in sql and "excluded.raw_payload_id" in sql
    assert "shopee_order_lines" not in sql
    assert "FROM ingest_raw_payloads, " not in sql
    # the data column coalesces both ways; the provenance column does not
    assert sql.count("coalesce(") == 2


def test_the_metric_upsert_compiles_one_guarded_path_on_postgres():
    """``platform_daily_metrics`` on the Postgres dialect: the WHERE drops only an equal-rank
    older read, and each SET column chooses winner / gap-fill on the same rank-and-capture test
    (AND binds tighter than OR, so the equal-rank branch carries the capture check)."""
    from sqlalchemy.dialects.postgresql import insert

    table = PlatformDailyMetric.__table__
    stmt = insert(PlatformDailyMetric).values(id=uuid.uuid4(), gmv=1, source="file", source_rank=2)
    upsert = stmt.on_conflict_do_update(
        index_elements=["shop_id"],
        set_=ranked_set(table, stmt.excluded, ["gmv", "source"], ["source"]),
        where=ranked_where(table, stmt.excluded),
    )
    sql = str(upsert.compile(dialect=postgresql.dialect()))
    _, update = sql.split(" DO UPDATE SET ")
    _, where = update.split(" WHERE ")
    capture = (
        "platform_daily_metrics.captured_at IS NULL OR excluded.captured_at IS NULL OR "
        "platform_daily_metrics.captured_at <= excluded.captured_at"
    )
    assert where.endswith(f"END != excluded.source_rank OR {capture}")
    assert f"END = excluded.source_rank AND ({capture})) THEN coalesce(" in update
    assert "ELSE coalesce(platform_daily_metrics.gmv, excluded.gmv) END" in update
    assert "THEN excluded.source ELSE platform_daily_metrics.source END" in update


# ------------------------------------------------------------ C1: a placeholder item is unknown


async def _catalogue(session, shop_id) -> None:
    from juli_backend.models.platform_data import PlatformItem

    session.add(
        PlatformItem(
            id=uuid.uuid4(),
            shop_id=shop_id,
            platform="shopee",
            item_id="9001",
            variation_id="9002",
            seller_sku="G1",
            source="file",
            source_rank=2,
            source_version="t",
            mapper_version=1,
            captured_at=datetime(2026, 10, 29),
            updated_at=datetime(2026, 10, 29),
            first_seen_on=date(2026, 10, 1),
            last_seen_on=date(2026, 10, 28),
            extra={},
        )
    )
    await session.flush()


async def test_a_re_read_with_the_item_replaces_an_unknown_line(session):
    _, shop = await make_tenant(session)
    await _catalogue(session, shop.id)
    await _write(session, shop.id, "extension", 3, T1, sku=None)
    assert (await _line(session)).item_id == "sku:unknown"
    await _write(session, shop.id, "extension", 3, T2)
    line = await _line(session)
    assert (line.item_id, line.variation_id, line.source_version) == (
        "9001",
        "9002",
        "extension-40",
    )


async def test_a_lower_rank_file_fills_the_unknown_item_and_the_provenance_stays(session):
    _, shop = await make_tenant(session)
    await _catalogue(session, shop.id)
    await _write(session, shop.id, "extension", 3, T1, sku=None)
    await _write(session, shop.id, "file", 2, T2, deal_price=Decimal(70_000))
    line = await _line(session)
    assert (line.item_id, line.variation_id) == ("9001", "9002")
    assert line.deal_price == Decimal(90_000)  # the Connector's value stays
    assert (line.source, line.source_rank, line.source_version) == ("extension", 3, "extension-20")


async def test_a_placeholder_never_replaces_a_known_item(session):
    _, shop = await make_tenant(session)
    await _catalogue(session, shop.id)
    await _write(session, shop.id, "file", 2, T1)
    await _write(session, shop.id, "extension", 3, T2, sku=None, deal_price=Decimal(80_000))
    line = await _line(session)
    assert (line.item_id, line.variation_id) == ("9001", "9002")
    assert line.deal_price == Decimal(80_000)  # the higher rank still wins the rest
    assert line.source == "extension"


async def test_a_combo_re_read_names_each_sub_line_by_its_variation_sku(session):
    """batch-1124-b CONN: Connector 0.3.36 re-posts a combo's ``sku:unknown`` parent (line 0) as
    its sub-lines, each with the variation SKU only (the product SKU is empty, as on Shopee): line
    0 takes the catalogue item the SKU names, line 1 is new, through the same SKU join."""
    _, shop = await make_tenant(session)
    await _catalogue(session, shop.id)
    await _write(session, shop.id, "extension", 3, T1, sku=None, deal_price=Decimal(190_000))
    sub_lines = [
        ShopeeOrderLineRow.model_validate(
            {
                "order_ref": ORDER,
                "line_no": line_no,
                "ordered_at": AT,
                "status": "delivered",
                "variation_sku": "G1",
                "qty": 1,
                "original_price": Decimal(95_000),
                "deal_price": Decimal(95_000),
                "promo_kind": "bundle",
            }
        )
        for line_no in (0, 1)
    ]
    provenance = {
        "shop_id": shop.id,
        "platform": "shopee",
        "source": "extension",
        "source_rank": 3,
        "source_version": "extension-0.3.36",
        "raw_payload_id": await _payload(session, shop.id, "extension", T2),
        "updated_at": T2,
    }
    await write_order_lines(session, sub_lines, None, provenance)
    stmt = (
        select(ShopeeOrderLine)
        .order_by(ShopeeOrderLine.line_no)
        .execution_options(populate_existing=True)
    )
    lines = (await session.execute(stmt)).scalars().all()
    assert [(ln.line_no, ln.item_id, ln.variation_id, ln.deal_price) for ln in lines] == [
        (0, "9001", "9002", Decimal(95_000)),
        (1, "9001", "9002", Decimal(95_000)),
    ]

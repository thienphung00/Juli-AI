"""T5 (migration 134): the canonical fact tables, their times and the order-status vocabulary.

Static checks of the migration against the ORM, the ``timestamptz`` column type, the writers'
time and status rules (T7, T9) and the per-day readers (T8: a 23:30 Vietnam-local order counts on
its own day), on SQLite. The Postgres half (catalog names, RLS through the compat views, the
type conversion and the down / up round trip) is
``tests/integration/test_t5_canonical_tables_db.py``.
"""

from __future__ import annotations

import importlib.util
import logging
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import DateTime, select
from sqlalchemy.dialects import postgresql

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models.shopee_metrics import (
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.models.shopee_profit import (
    ORDER_LINE_STATUSES,
    VN_TZ,
    CanonicalTime,
    ShopeeAffiliateLine,
    ShopeeOrderIncome,
    ShopeeOrderLine,
    vn_day,
)
from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.services.ingest import schemas
from juli_backend.services.ingest.schemas import (
    ShopeeAffiliateOrderLineRow,
    ShopeeOrderLineRow,
)
from juli_backend.services.ingest.writers import (
    canonical_status,
    write_affiliate_lines,
    write_order_lines,
)
from tests.support.builders import make_tenant

REPO = Path(__file__).resolve().parents[2]
PG = postgresql.dialect()
VERSIONS = REPO / "backend/src/juli_backend/database/migrations/versions"
PATH = VERSIONS / "134_canonical_tables.py"
MODELS = (
    ShopeeOrderLine,
    ShopeeOrderIncome,
    ShopeeAffiliateLine,
    ShopeeShopMetricsDaily,
    ShopeeProductMetricsDaily,
    ShopeeSourceMetricsDaily,
    ShopeeStockHistory,
)
DAY = date(2026, 10, 1)
#: 23:30 Vietnam local on DAY: 16:30 UTC the same date, and still DAY in GMT+7
LATE = datetime(2026, 10, 1, 23, 30)
#: 00:30 Vietnam local the next day: 17:30 UTC on DAY, but DAY + 1 in GMT+7
EARLY_NEXT = datetime(2026, 10, 2, 0, 30)
#: 03:00 Vietnam local on DAY: 20:00 UTC the day BEFORE, so a UTC-computed day would be wrong
EARLY_SAME = datetime(2026, 10, 1, 3, 0)


def _module():
    spec = importlib.util.spec_from_file_location("m134", PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------ the migration (T1-T4)


def test_revision_fits_alembic_follows_135_and_is_the_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    mod = _module()
    assert mod.revision == "134_canonical_tables" and len(mod.revision) <= 32
    assert mod.down_revision == "135_connector_multi_computer"
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert script.get_heads() == ["140_data_layer_facts_opps"]  # data layer 140 on 138
    assert "134_canonical_tables" in {r.revision for r in script.walk_revisions()}


def test_the_seven_tables_map_old_to_new_with_unchanged_verbs():
    mod = _module()
    pairs = {old: new for old, new, _ in mod.TABLES}
    assert pairs == {
        "shopee_order_lines": "order_lines",
        "shopee_order_income": "order_settlements",
        "shopee_affiliate_lines": "affiliate_lines",
        "shopee_shop_metrics_daily": "shop_metrics_daily",
        "shopee_product_metrics_daily": "product_metrics_daily",
        "shopee_source_metrics_daily": "source_metrics_daily",
        "shopee_stock_history": "stock_history",
    }
    assert {model.__tablename__ for model in MODELS} == set(pairs.values())
    verbs = {new: v for _, new, v in mod.TABLES}
    assert verbs["stock_history"] == "SELECT, INSERT"
    assert {v for new, v in verbs.items() if new != "stock_history"} == {"SELECT, INSERT, UPDATE"}
    for old, new in pairs.items():
        assert TABLE_CLASSIFICATION_MAP[("public", new)] == "tenant_direct"
        assert ("public", old) not in TABLE_CLASSIFICATION_MAP  # a view, not a table


def test_upgrade_and_downgrade_set_a_transaction_local_lock_timeout():
    source = PATH.read_text()
    up = source.split("def upgrade")[1].split("def downgrade")[0]
    down = source.split("def downgrade")[1]
    assert "SET LOCAL lock_timeout" in source and _module().LOCK_TIMEOUT == "10s"
    assert "_fail_fast()" in up and "_fail_fast()" in down


def test_compat_views_are_security_invoker_and_granted():
    source = PATH.read_text("utf-8")
    up = source.split("def upgrade")[1].split("def downgrade")[0]
    assert "WITH (security_invoker = true)" in up and "SELECT * FROM public.{new}" in up
    assert "_grant(old, verbs)" in up
    down = source.split("def downgrade")[1]
    assert "DROP VIEW IF EXISTS public.{old}" in down


def test_renamed_and_added_columns_exist_on_the_models():
    mod = _module()
    assert set(mod.COLUMNS) == {
        ("order_lines", "shopee_subsidy", "platform_subsidy"),
        ("order_settlements", "ship_shopee_subsidy", "ship_platform_subsidy"),
        ("affiliate_lines", "order_status", "status"),
        ("affiliate_lines", "model_id", "variation_id"),
        ("stock_history", "model_id", "variation_id"),
    }
    by_name = {m.__tablename__: m.__table__.columns for m in MODELS}
    for table, old, new in mod.COLUMNS:
        assert new in by_name[table] and old not in by_name[table], (table, old)
    for table in ("order_lines", "affiliate_lines"):
        assert {"day", "source_rank"} <= set(by_name[table].keys())
    assert "fee_other" in by_name["order_settlements"]
    for kept in ("fee_piship", "ship_piship_refund", "fee_nttd", "fee_voucher_xtra"):
        assert kept in by_name["order_settlements"]
    unique = next(
        c for c in ShopeeAffiliateLine.__table__.constraints if c.name == "uq_affiliate_lines_line"
    )
    assert "variation_id" in {c.name for c in getattr(unique, "columns")}


def test_every_time_column_of_the_seven_tables_is_converted_by_its_meaning():
    mod = _module()
    converted = {(table, column): zone for table, column, zone in mod.TIMES}
    for model in MODELS:
        for column in model.__table__.columns:
            if isinstance(column.type, CanonicalTime):
                zone = "Asia/Ho_Chi_Minh" if column.type.naive_as is VN_TZ else "UTC"
                assert converted.pop((model.__tablename__, column.name)) == zone, column
            else:
                assert not isinstance(column.type, DateTime), (model.__tablename__, column.name)
    assert converted == {}
    order_times = {column for _, column, zone in mod.TIMES if zone == "Asia/Ho_Chi_Minh"}
    assert order_times == {"ordered_at", "paid_at", "completed_at", "conversion_at"}


def test_orm_names_follow_the_new_tables():
    """T3 on the ORM side; the catalog side is the Postgres test."""
    for model in MODELS:
        table = model.__table__
        names = [c.name for c in table.constraints if c.name] + [i.name for i in table.indexes]
        assert all("shopee_" not in str(n) for n in names), (table.name, names)
    assert {i.name for i in ShopeeStockHistory.__table__.indexes} >= {"ix_stock_history_read"}
    read_index = next(
        i for i in ShopeeStockHistory.__table__.indexes if i.name == "ix_stock_history_read"
    )
    assert [c.name for c in read_index.columns] == ["shop_id", "read_at"]


def test_the_migration_fills_source_rank_with_todays_ranks():
    import re

    from juli_backend.models.ingest import SOURCE_RANK

    mod = _module()
    filled = {s: int(r) for s, r in re.findall(r"WHEN '(\w+)' THEN (\d)", mod.RANK_CASE)}
    assert filled == SOURCE_RANK
    assert SOURCE_RANK["api"] > SOURCE_RANK["extension"] > SOURCE_RANK["file"]


def test_the_migration_status_vocabulary_is_the_models_and_the_wires():
    mod = _module()
    assert ORDER_LINE_STATUSES == schemas.ORDER_STATUSES
    assert [s.strip(" '") for s in mod.STATUSES.split(",")] == list(ORDER_LINE_STATUSES)
    assert set(ORDER_LINE_STATUSES) == {
        "pending",
        "confirmed",
        "in_transit",
        "delivered",
        "cancelled",
        "refunded_accepted",
        "refunded_not_received",
        "returned",
        "on_hold",
    }
    check = next(
        c for c in ShopeeOrderLine.__table__.constraints if c.name == "ck_order_lines_status"
    )
    assert "returned" in str(getattr(check, "sqltext"))


# ------------------------------------------------------------------------ the column type (T6)


def test_canonical_time_reads_a_naive_value_in_its_zone_and_keeps_an_aware_one():
    order_time = CanonicalTime(VN_TZ)
    bound = order_time.process_bind_param(LATE, PG)
    assert bound == datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
    aware = datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
    assert order_time.process_bind_param(aware, PG) == aware
    back = order_time.process_result_value(bound, PG)
    assert back is not None and back.tzinfo is VN_TZ and back.date() == DAY and back.hour == 23
    sqlite_naive = order_time.process_result_value(datetime(2026, 10, 1, 16, 30), PG)
    assert sqlite_naive == bound
    utc_time = CanonicalTime(UTC)
    assert utc_time.process_bind_param(datetime(2026, 10, 1, 17, 0), PG) == datetime(
        2026, 10, 1, 17, 0, tzinfo=UTC
    )
    assert vn_day(datetime(2026, 10, 1, 17, 0, tzinfo=UTC)) == DAY + timedelta(days=1)
    assert vn_day(LATE) == DAY


# ------------------------------------------------------------------------ statuses (T9)


@pytest.mark.parametrize("status", ORDER_LINE_STATUSES)
def test_a_canonical_status_is_stored_as_it_is(status):
    assert canonical_status(status.upper(), paid=False) == status


def test_an_unknown_status_is_in_transit_when_paid_else_pending_and_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="juli_backend.services.ingest.writers"):
        assert canonical_status("SHIPPED", paid=True) == "in_transit"
        assert canonical_status("mystery", paid=False) == "pending"
    logged = [r for r in caplog.records if r.getMessage() == "order_line_status_unknown"]
    assert [(getattr(r, "status"), getattr(r, "stored_as")) for r in logged] == [
        ("SHIPPED", "in_transit"),
        ("mystery", "pending"),
    ]


# ------------------------------------------------------------------------ the writers (T7)


def _provenance(shop_id) -> dict:
    return {
        "shop_id": shop_id,
        "platform": "shopee",
        "source": "file",
        "source_rank": 2,
        "source_version": "t5",
        "raw_payload_id": None,
        "updated_at": datetime(2026, 10, 3, 1, 0),
    }


def _order_row(n: int, at: datetime, **over) -> ShopeeOrderLineRow:
    values = {
        "order_ref": f"{n:032x}",
        "ordered_at": at,
        "status": "delivered",
        "sku": "G1",
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        "shopee_subsidy": Decimal(5_000),
        "paid_at": at + timedelta(minutes=2),
        **over,
    }
    return ShopeeOrderLineRow.model_validate(values)


async def test_order_line_writer_reads_naive_times_as_vietnam_local(session):
    _, shop = await make_tenant(session)
    gmt0 = timezone(timedelta(0))
    rows = [
        _order_row(1, LATE),
        _order_row(2, datetime(2026, 10, 1, 17, 30, tzinfo=gmt0)),  # aware: 00:30 VN on Oct 2
        _order_row(3, LATE, status="UNPAID_SOMETHING", paid_at=None),
        _order_row(4, EARLY_SAME),  # 03:00 VN: the previous date in UTC, still DAY in GMT+7
    ]
    await write_order_lines(session, rows, None, _provenance(shop.id))
    stored = {r.order_ref: r for r in (await session.execute(select(ShopeeOrderLine))).scalars()}
    first = stored[f"{1:032x}"]
    assert first.ordered_at == datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
    assert first.day == DAY and first.ordered_at.tzinfo is not None
    assert first.paid_at == datetime(2026, 10, 1, 16, 32, tzinfo=UTC)
    assert first.platform_subsidy == Decimal(5_000) and first.source_rank == 2
    second = stored[f"{2:032x}"]
    assert second.ordered_at == datetime(2026, 10, 1, 17, 30, tzinfo=UTC)
    assert second.day == DAY + timedelta(days=1)
    assert stored[f"{3:032x}"].status == "pending"
    fourth = stored[f"{4:032x}"]
    assert fourth.ordered_at == datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    assert fourth.day == DAY


async def test_affiliate_writer_stamps_day_variation_and_status(session):
    _, shop = await make_tenant(session)
    row = ShopeeAffiliateOrderLineRow.model_validate(
        {
            "order_ref": f"{7:032x}",
            "item_id": "1001",
            "model_id": "55",
            "qty": 1,
            "ordered_at": LATE,
            "order_status": "Đã hoàn thành",
            "valid": True,
        }
    )
    provenance = _provenance(shop.id)
    del provenance["source_rank"]  # a caller without the gateway's rank: the source's own
    await write_affiliate_lines(session, [row], None, provenance)
    stored = (await session.execute(select(ShopeeAffiliateLine))).scalar_one()
    assert (stored.variation_id, stored.status, stored.day) == ("55", "Đã hoàn thành", DAY)
    assert stored.ordered_at == datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
    assert stored.source_rank == 2  # SOURCE_RANK["file"] (API > Connector > file)


async def test_stock_history_writer_keeps_read_at_as_utc(session):
    from juli_backend.services.stock_alert.history import record

    _, shop = await make_tenant(session)
    row = schemas.ShopeeItemSnapshotRow.model_validate(
        {"item_id": "1001", "model_id": "55", "total_available_stock": 4}
    )
    provenance = {"shop_id": shop.id, "captured_at": datetime(2026, 10, 1, 17, 0)}
    assert await record(session, [row], provenance) == 1
    stored = (await session.execute(select(ShopeeStockHistory))).scalar_one()
    assert stored.variation_id == "55"
    assert stored.read_at == datetime(2026, 10, 1, 17, 0, tzinfo=UTC)


# ------------------------------------------------------------------------ the readers (T8)


def _line(shop_id: uuid.UUID, n: int, at: datetime, **over) -> ShopeeOrderLine:
    values = {
        "shop_id": shop_id,
        "platform": "shopee",
        "order_ref": f"{n:032x}",
        "line_no": 0,
        "ordered_at": at,
        "paid_at": at,
        "status": "delivered",
        "item_id": "1001",
        "variation_id": "55",
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        "affiliate": True,
        "kol_key": "k1",
        "source": "file",
        "source_version": "t5",
        **over,
    }
    return ShopeeOrderLine(**values)


@pytest.fixture
async def late_and_early(session):
    """One order at 23:30 VN on DAY, one at 00:30 VN on DAY + 1 (17:30 UTC on DAY)."""
    _, shop = await make_tenant(session)
    session.add_all([_line(shop.id, 1, LATE), _line(shop.id, 2, EARLY_NEXT)])
    await session.flush()
    return shop.id


async def test_the_day_default_is_the_vietnam_day_of_ordered_at(session, late_and_early):
    days = (await session.execute(select(ShopeeOrderLine.order_ref, ShopeeOrderLine.day))).all()
    assert sorted(d for _, d in days) == [DAY, DAY + timedelta(days=1)]


async def test_repo_windows_count_a_late_order_on_its_own_day(session, late_and_early):
    from juli_backend.repositories import ShopeeOrderLinesRepo

    repo = ShopeeOrderLinesRepo(session)
    assert [r.order_ref for r in await repo.in_window(late_and_early, DAY, DAY)] == [f"{1:032x}"]
    assert await repo.days_with_lines(late_and_early, DAY, DAY + timedelta(days=1)) == {
        DAY,
        DAY + timedelta(days=1),
    }
    assert await repo.day_bounds(late_and_early) == (DAY, DAY + timedelta(days=1))
    pair = await repo.kol_pair_lines(late_and_early, "k1", "1001", DAY, DAY)
    assert [r.order_ref for r in pair] == [f"{1:032x}"]


async def test_stored_and_materialize_days_use_the_stored_day(session, late_and_early):
    from juli_backend.services.shopee_analytics import materialize, stored
    from juli_backend.services.shopee_analytics.windows import Window

    assert DAY in await materialize.data_days(session, late_and_early)
    assert await stored.data_days_in(session, late_and_early, Window(DAY, DAY)) == {DAY}


async def test_engine_and_kol_series_put_the_late_order_on_its_day(session, late_and_early):
    from juli_backend.services.shopee_analytics import kol
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.shopee_analytics.engine import to_shop_lines
    from juli_backend.services.shopee_analytics.loaders import load_order_lines
    from juli_backend.services.shopee_analytics.windows import Window

    load = await load_order_lines(session, late_and_early, Window(DAY, DAY))
    lines = to_shop_lines(load.lines, Catalog())
    assert [(sl.line.order_id, sl.ordered_on, sl.line.order_date) for sl in lines] == [
        (f"{1:032x}", DAY, DAY)
    ]
    series = await kol.pair_daily(session, late_and_early, "k1", "1001", DAY, DAY)
    assert set(series) == {DAY} and series[DAY]["orders"] == 1


async def test_measure_item_days_use_the_stored_day(session, late_and_early):
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.shopee_recommendations.measure import load_item_days

    days = await load_item_days(session, late_and_early, DAY, DAY, catalog=Catalog())
    assert set(days.get("1001", {})) <= {DAY}
    assert days["1001"][DAY].gmv == pytest.approx(90_000)


async def test_affiliate_lines_load_by_their_day(session):
    from juli_backend.services.shopee_analytics.kol_affiliate import load_affiliate_lines

    _, shop = await make_tenant(session)
    for n, at in ((1, LATE), (2, EARLY_NEXT)):
        session.add(
            ShopeeAffiliateLine(
                shop_id=shop.id,
                platform="shopee",
                order_ref=f"{n:032x}",
                line_no=0,
                item_id="1001",
                ordered_at=at,
                source="file",
                source_version="t5",
            )
        )
    await session.flush()
    loaded = await load_affiliate_lines(session, shop.id, DAY, DAY)
    assert [(a.order_ref, a.day) for a in loaded] == [(f"{1:032x}", DAY)]


async def test_stock_alert_counts_the_late_order_on_its_day_and_through_it(session, late_and_early):
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.stock_alert.data import load_orders_through, load_skus

    session.add(
        ShopeeStockHistory(
            shop_id=late_and_early,
            item_id="1001",
            variation_id="55",
            read_at=datetime(2026, 10, 1, 17, 0),  # naive = UTC: 00:00 VN on Oct 2
            available=9,
        )
    )
    await session.flush()
    skus = await load_skus(session, late_and_early, Catalog(), DAY + timedelta(days=5))
    sku = skus["1001:55"]
    assert dict(sku.units) == {DAY: 1, DAY + timedelta(days=1): 1}
    assert await load_orders_through(session, late_and_early) == DAY + timedelta(days=1)


async def test_units_since_a_read_compare_utc_with_utc(session, late_and_early):
    """The boundary the coordinator named: a read at 17:00 UTC (00:00 VN on Oct 2) is BEFORE the
    00:30 VN order (17:30 UTC) and AFTER the 23:30 VN one (16:30 UTC). Before T5 the naive VN
    order time was compared with the naive UTC read time, 7 hours off."""
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.stock_alert import stock_basis as sb
    from juli_backend.services.stock_alert.data import load_skus

    read_at = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)
    session.add(
        ShopeeStockHistory(
            shop_id=late_and_early, item_id="1001", variation_id="55", read_at=read_at, available=9
        )
    )
    await session.flush()
    sku = (await load_skus(session, late_and_early, Catalog(), DAY + timedelta(days=5)))["1001:55"]
    last = sku.last
    assert last is not None and last.read_at.tzinfo is None  # naive UTC inside the package
    assert last.read_at == datetime(2026, 10, 1, 17, 0)
    assert all(at.tzinfo is None for at, _, _ in sku.lines)
    assert sku.since(last.read_at) == (1, 1)  # only the 00:30 VN order
    assert sb.naive_utc(datetime(2026, 10, 2, 0, 30, tzinfo=VN_TZ)) == datetime(2026, 10, 1, 17, 30)
    assert sb.local_day(read_at) == DAY + timedelta(days=1)

"""P90 step 2, migration 113 on real Postgres: RLS, grants, the gateway as ``juli_app``, up / down.

- the two new tables have row-level security on and give ``juli_app`` SELECT, INSERT only
  (append-only), ``juli_ops`` nothing; ``shopee_order_lines`` keeps SELECT, INSERT, UPDATE;
- two tenants: a shop sees and writes only its own rows in each new table;
- the gateway, as the runtime role under each shop's scope, writes order lines (upsert, a NULL
  fee never erases a stored one), marks them from the affiliate lane, appends the ad change log
  and shop health, and writes an item snapshot only on change - and the other shop sees none of it;
- the account purge sweeps the new tables (they carry a uuid ``shop_id``): by column;
- last: ``downgrade`` to 112 drops the tables and columns, ``upgrade head`` restores them.

Synthetic tenants only.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import column, delete, select, text, update
from sqlalchemy import table as sa_table
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as svc
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
NOW = datetime(2026, 11, 3, 3, 0)
NEW_TABLES = ("shop_health_daily", "ads_change_log")
LINES = "shopee_order_lines"
NEW_LINE_COLUMNS = (
    "buyer_shipping_fee",
    "bank_promo",
    "ad_attributed",
    "seller_subsidy",
    "shopee_subsidy",
    "returned_qty",
    "completed_at",
    "paid_at",
    "sku",
    "variation_sku",
)
REF_A = "a" * 32
REF_B = "b" * 32


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _insert(conn, table: str, shop_id: uuid.UUID, tag: str) -> None:
    if table == "shop_health_daily":
        sql = (
            "INSERT INTO public.shop_health_daily (id, shop_id, platform, day, metric_id, "
            "captured_at, source, source_rank, source_version) "
            "VALUES (:id, :shop, 'shopee', '2026-11-02', :tag, :now, 'extension', 2, 't1')"
        )
    else:
        sql = (
            "INSERT INTO public.ads_change_log (id, shop_id, platform, campaign_id, occurred_at, "
            "actor_kind, event_type, source, source_version) "
            "VALUES (:id, :shop, 'shopee', :tag, :now, 'system', 'x', 'file', 't1')"
        )
    conn.execute(text(sql), {"id": uuid.uuid4(), "shop": shop_id, "tag": tag, "now": NOW})


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def test_the_new_tables_have_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": list(NEW_TABLES)},
            ).all()
        )
    assert rows == dict.fromkeys(NEW_TABLES, True)


def test_grants_are_append_only_for_the_new_tables(owner_engine):
    with owner_engine.connect() as conn:
        for table in NEW_TABLES:
            assert _verbs(conn, RUNTIME_ROLE, table) == {"SELECT", "INSERT"}, table
        assert _verbs(conn, RUNTIME_ROLE, LINES) == {"SELECT", "INSERT", "UPDATE"}
        if _role_exists(conn, "juli_ops"):
            for table in (*NEW_TABLES, LINES):
                assert _verbs(conn, "juli_ops", table) == set(), table


def test_the_order_line_columns_exist_with_the_right_nullability(owner_engine):
    with owner_engine.connect() as conn:
        found = {
            name: nullable
            for name, nullable in conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = ANY(:c)"
                ),
                {"t": LINES, "c": list(NEW_LINE_COLUMNS)},
            ).all()
        }
    assert set(found) == set(NEW_LINE_COLUMNS)
    assert found["ad_attributed"] == "YES"
    assert found["seller_subsidy"] == "NO" and found["returned_qty"] == "NO"


@pytest.mark.parametrize("table", NEW_TABLES)
def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants, table):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, table, a.shop_id, f"{table}-a")
        _insert(conn, table, b.shop_id, f"{table}-b")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(conn.execute(_shop_ids(table)).scalars())
        assert shops == {a.shop_id}
        _insert(conn, table, a.shop_id, f"{table}-a2")
        with pytest.raises(DBAPIError):
            _insert(conn, table, b.shop_id, f"{table}-smuggled")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


@pytest.mark.parametrize("table", NEW_TABLES)
def test_the_new_tables_refuse_update_and_delete(owner_engine, two_tenants, table):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, table, a.shop_id, f"{table}-append-only")
    target = sa_table(table, column("source"), schema="public")
    for statement in (update(target).values(source="x"), delete(target)):
        with owner_engine.connect() as conn:
            _scope(conn, a.shop_id)
            with pytest.raises(DBAPIError):
                conn.execute(statement)
            conn.rollback()
            conn.execute(text("RESET ROLE"))


def test_the_purge_sweep_finds_the_new_tables(owner_engine):
    """The purge deletes from every base table with a uuid ``shop_id`` (094)."""
    with owner_engine.connect() as conn:
        found = set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                    "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                    "AND NOT a.attisdropped AND c.relname = ANY(:t)"
                ),
                {"t": [*NEW_TABLES, LINES]},
            ).scalars()
        )
    assert found == {*NEW_TABLES, LINES}


# ===================================================================== the gateway as juli_app


def _shop_ids(table: str):
    """``SELECT shop_id FROM public.<table>`` for a table named by the test's own constants."""
    return select(column("shop_id")).select_from(sa_table(table, schema="public"))


def _line(ref: str, **over) -> dict:
    base = {
        "order_ref": ref,
        "line_no": 0,
        "ordered_at": "2026-10-05T10:15:00",
        "status": "delivered",
        "sku": "SKU-A",
        "variation_sku": "SKU-A-1",
        "qty": 2,
        "original_price": 100000,
        "deal_price": 90000,
        "seller_subsidy": 20000,
        "shop_voucher_share": 1000,
        "buyer_shipping_fee": 5000,
        "fee_fixed": 4000,
        "fee_service": 0,
        "fee_payment": 2000,
        "paid_at": "2026-10-05T10:20:00",
    }
    return {**base, **over}


def _body(rows: list[dict], *, start: str = "2026-10-05", end: str = "2026-10-05", **over) -> dict:
    body = {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
        "captured_at": "2026-11-03T09:30:00+07:00",
        "period": {"start": start, "end": end, "granularity": "period"},
        "rows": rows,
    }
    body.update(over)
    return body


async def _post(shop_id: uuid.UUID, dataset: str, body: dict) -> None:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            await svc.ingest(
                session,
                shop_id=shop_id,
                platform="shopee",
                dataset=dataset,
                body=svc.IngestBody.model_validate(body),
                token_id=None,
                now=NOW,
            )
        await session.commit()


async def _scalar(shop_id: uuid.UUID, sql):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(sql) if isinstance(sql, str) else sql)).all()


async def test_the_gateway_writes_the_p90_datasets_as_the_runtime_role(shopee_tenants):
    a, b = shopee_tenants
    await _post(a.shop_id, "order_lines", _body([_line(REF_A)]))
    # The same order again with the fee block unfilled and the status moved: the fee stays.
    moved = _line(REF_A, status="refunded_accepted")
    for name in ("fee_fixed", "fee_service", "fee_payment"):
        del moved[name]
    await _post(
        a.shop_id,
        "order_lines",
        _body([moved], captured_at="2026-11-03T09:45:00+07:00"),
    )
    (line,) = await _scalar(
        a.shop_id,
        "SELECT status, fee_fixed, fee_payment, seller_subsidy, buyer_shipping_fee, "
        "ad_attributed, item_id, paid_at FROM public.shopee_order_lines",
    )
    assert line.status == "refunded_accepted"
    assert (float(line.fee_fixed), float(line.fee_payment)) == (4000.0, 2000.0)
    assert (float(line.seller_subsidy), float(line.buyer_shipping_fee)) == (20000.0, 5000.0)
    assert line.ad_attributed is None and line.item_id == "sku:SKU-A-1"
    assert line.paid_at == datetime(2026, 10, 5, 10, 20)

    affiliate = {
        "order_ref": REF_A,
        "item_id": "1001",
        "ordered_at": "2026-10-05T10:15:00",
        "cost": 900,
        "valid": True,
    }
    await _post(a.shop_id, "affiliate_order_lines", _body([affiliate]))
    (marked,) = await _scalar(
        a.shop_id, "SELECT affiliate, commission, traffic_source FROM public.shopee_order_lines"
    )
    assert marked.affiliate is True and float(marked.commission) == 900.0
    assert marked.traffic_source == "affiliate"

    log = {
        "campaign_id": "555000111",
        "occurred_at": "2026-10-05T10:00:00",
        "actor_kind": "system",
        "event_type": "Tối ưu tự động",
    }
    await _post(a.shop_id, "ads_change_log", _body([log]))
    await _post(
        a.shop_id,
        "ads_change_log",
        _body(
            [log, {**log, "occurred_at": "2026-10-06T10:00:00"}],
            captured_at="2026-11-03T09:50:00+07:00",
        ),
    )
    assert (
        len(
            await _scalar(
                a.shop_id, "SELECT 1 FROM public.ads_change_log WHERE campaign_id = '555000111'"
            )
        )
        == 2
    )

    snapshot = [
        {"item_id": "1001", "price_min": 100000, "price_max": 150000, "total_available_stock": 30}
    ]
    await _post(a.shop_id, "item_snapshot", _body(snapshot, start="2026-11-02", end="2026-11-02"))
    await _post(
        a.shop_id,
        "item_snapshot",
        _body(
            snapshot, start="2026-11-02", end="2026-11-02", captured_at="2026-11-03T09:55:00+07:00"
        ),
    )
    assert len(await _scalar(a.shop_id, "SELECT 1 FROM public.platform_item_snapshots")) == 1

    health = [{"date": "2026-11-02", "metric_id": "11", "value": 92, "passed": True}]
    await _post(
        a.shop_id,
        "shop_health_daily",
        {
            **_body(health),
            "period": {"start": "2026-11-02", "end": "2026-11-02", "granularity": "day"},
        },
    )
    assert (
        len(
            await _scalar(
                a.shop_id, "SELECT 1 FROM public.shop_health_daily WHERE metric_id = '11'"
            )
        )
        == 1
    )

    # Shop B sees none of it, and its own order is its own.
    await _post(b.shop_id, "order_lines", _body([_line(REF_B)]))
    for table in (LINES, "ads_change_log", "platform_item_snapshots", "shop_health_daily"):
        rows = await _scalar(b.shop_id, _shop_ids(table))
        assert {r.shop_id for r in rows} <= {b.shop_id}, table
    assert not await _scalar(
        b.shop_id, "SELECT 1 FROM public.ads_change_log WHERE campaign_id = '555000111'"
    )


# =========================================================================== down and up


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 112, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def tables() -> set[str]:
        with owner_engine.connect() as conn:
            return {
                name
                for name in NEW_TABLES
                if conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar()
                is not None
            }

    def line_columns() -> set[str]:
        with owner_engine.connect() as conn:
            return set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :t "
                        "AND column_name = ANY(:c)"
                    ),
                    {"t": LINES, "c": list(NEW_LINE_COLUMNS)},
                ).scalars()
            )

    assert tables() == set(NEW_TABLES) and line_columns() == set(NEW_LINE_COLUMNS)
    command.downgrade(cfg, "112_shopee_profit_and_history")
    try:
        assert tables() == set() and line_columns() == set()
        with owner_engine.connect() as conn:
            assert (
                conn.execute(text("SELECT to_regclass('public.shopee_order_lines')")).scalar()
                is not None
            )
    finally:
        command.upgrade(cfg, "head")
    assert tables() == set(NEW_TABLES) and line_columns() == set(NEW_LINE_COLUMNS)

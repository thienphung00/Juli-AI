"""P91 D-12, migration 117 on real Postgres: RLS, grants, the gateway as ``juli_app``, the engine
reading the stored rows, up / down.

- ``shopee_order_income`` has row-level security, gives ``juli_app`` SELECT, INSERT, UPDATE (no
  DELETE) and ``juli_ops`` nothing; the purge sweep finds it; ``variation_name`` is nullable;
- two tenants: a shop sees and writes only its own rows;
- the gateway, as the runtime role under each shop's scope, writes the income rows (a later post
  replaces, a Connector post does not outrank a file, a missing field erases nothing) and the
  order lines' variation name picks the right one of three variations sharing a SKU;
- the analytics engine reads them: combo costs by pack, the income order charged its actuals, the
  other order the formula, the Income coverage between the two;
- last: ``downgrade`` to 116 drops the table and the column, ``upgrade head`` restores them.

Synthetic tenants only.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import column, select, text
from sqlalchemy import table as sa_table
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as svc
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.engine import (
    build_fee_context,
    cost_coverage,
    income_coverage,
    profit_pairs,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.windows import Window
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
NOW = datetime(2026, 11, 4, 3, 0)
TABLE = "shopee_order_income"
LINES = "shopee_order_lines"
REF_1, REF_2, REF_3, REF_X = "1" * 32, "2" * 32, "3" * 32, "e" * 32


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def _insert(conn, shop_id: uuid.UUID, ref: str) -> None:
    conn.execute(
        text(
            "INSERT INTO public.shopee_order_income (id, shop_id, platform, order_ref, source, "
            "source_rank, source_version) VALUES (:id, :shop, 'shopee', :ref, 'file', 3, 't1')"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "ref": ref},
    )


def test_the_table_has_row_level_security_and_the_right_grants(owner_engine):
    with owner_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.shopee_order_income'::regclass"
            )
        ).scalar()
        assert _verbs(conn, RUNTIME_ROLE, TABLE) == {"SELECT", "INSERT", "UPDATE"}
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'juli_ops'")).scalar():
            assert _verbs(conn, "juli_ops", TABLE) == set()
        nullable = dict(
            conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t "
                    "AND column_name IN ('variation_name')"
                ),
                {"t": LINES},
            ).all()
        )
        assert nullable == {"variation_name": "YES"}


def test_the_purge_sweep_finds_the_table(owner_engine):
    with owner_engine.connect() as conn:
        found = set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                    "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                    "AND NOT a.attisdropped AND c.relname = :t"
                ),
                {"t": TABLE},
            ).scalars()
        )
    assert found == {TABLE}


def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, a.shop_id, REF_1)
        _insert(conn, b.shop_id, REF_2)
    shops = select(column("shop_id")).select_from(sa_table(TABLE, schema="public"))
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        assert set(conn.execute(shops).scalars()) == {a.shop_id}
        _insert(conn, a.shop_id, "a" * 32)
        with pytest.raises(DBAPIError):
            _insert(conn, b.shop_id, "b" * 32)
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_a_shop_updates_its_own_row_and_cannot_delete_or_touch_another(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        mine = conn.execute(
            text("UPDATE public.shopee_order_income SET payout = 1 WHERE order_ref = :r"),
            {"r": REF_1},
        ).rowcount
        theirs = conn.execute(
            text("UPDATE public.shopee_order_income SET payout = 1 WHERE order_ref = :r"),
            {"r": REF_2},
        ).rowcount
        assert (mine, theirs) == (1, 0)
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM public.shopee_order_income"))
        conn.rollback()
        conn.execute(text("RESET ROLE"))


# ===================================================================== the gateway as juli_app


def _body(rows: list[dict], *, dataset_period=("2026-10-01", "2026-10-31"), **over) -> dict:
    body = {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
        "captured_at": "2026-11-03T09:30:00+07:00",
        "period": {"start": dataset_period[0], "end": dataset_period[1], "granularity": "period"},
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


async def _rows(shop_id: uuid.UUID, sql: str):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(sql))).all()


def _income(ref: str, **over) -> dict:
    base = {
        "order_ref": ref,
        "ordered_on": "2026-10-05",
        "paid_on": "2026-10-09",
        "payout": 63_000,
        "product_price": 90_000,
        "fee_fixed": 12_330,
        "fee_service": 3_000,
        "fee_infra": 3_000,
        "fee_voucher_xtra": 0,
        "fee_payment": 5_400,
        "affiliate_commission": 0,
        "net_shipping_cost": 2_500,
        "transaction_fee_rate": 0.06,
    }
    return {**base, **over}


async def test_the_gateway_writes_income_rows_as_the_runtime_role(shopee_tenants):
    a, b = shopee_tenants
    await _post(a.shop_id, "order_income", _body([_income(REF_3), _income(REF_X)]))
    (row,) = await _rows(
        a.shop_id,
        f"SELECT payout, fee_infra, net_shipping_cost, transaction_fee_rate, paid_on, source_rank "
        f"FROM public.shopee_order_income WHERE order_ref = '{REF_3}'",
    )
    assert (float(row.payout), float(row.fee_infra), float(row.net_shipping_cost)) == (
        63000.0,
        3000.0,
        2500.0,
    )
    assert float(row.transaction_fee_rate) == 0.06 and row.paid_on == date(2026, 10, 9)
    assert row.source_rank == 3

    # A later post replaces the row (same rank) but a field it leaves out erases nothing.
    later = _income(REF_3, payout=64_000)
    del later["fee_infra"], later["fee_voucher_xtra"]
    await _post(
        a.shop_id,
        "order_income",
        _body([later], captured_at="2026-11-03T09:40:00+07:00"),
    )
    (row,) = await _rows(
        a.shop_id,
        f"SELECT payout, fee_infra FROM public.shopee_order_income WHERE order_ref = '{REF_3}'",
    )
    assert (float(row.payout), float(row.fee_infra)) == (64000.0, 3000.0)

    # A Connector post (rank 2) never replaces the file row.
    await _post(
        a.shop_id,
        "order_income",
        _body(
            [_income(REF_3, payout=1)],
            source="extension",
            source_version="connector-1",
            captured_at="2026-11-03T09:50:00+07:00",
        ),
    )
    (row,) = await _rows(
        a.shop_id,
        f"SELECT payout, source FROM public.shopee_order_income WHERE order_ref = '{REF_3}'",
    )
    assert (float(row.payout), row.source) == (64000.0, "file")

    # Shop B sees none of it.
    assert not await _rows(
        b.shop_id, f"SELECT 1 FROM public.shopee_order_income WHERE order_ref = '{REF_X}'"
    )


# ================================================================ the engine over stored rows

ITEM = "500"
WINDOW = Window(date(2026, 10, 5), date(2026, 10, 5))


def _seed_catalogue(owner_engine, shop_id: uuid.UUID) -> None:
    with owner_engine.begin() as conn:
        for variation_id, name in (("5003", "Combo 3 hộp"), ("5010", "Combo 10 hộp")):
            conn.execute(
                text(
                    "INSERT INTO public.platform_items (id, shop_id, platform, item_id, "
                    "variation_id, name, variation_name, seller_sku, extra, source, source_rank, "
                    "source_version, mapper_version, captured_at, updated_at) VALUES "
                    "(:id, :shop, 'shopee', :item, :var, 'Giấy ăn', :name, 'G500001', '{}', "
                    "'file', 3, 't', 1, :now, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "shop": shop_id,
                    "item": ITEM,
                    "var": variation_id,
                    "name": name,
                    "now": NOW,
                },
            )
        for key, value in (("sku_cost", 20_000), ("packaging_cost", 2_000)):
            conn.execute(
                text(
                    "INSERT INTO public.shop_rules (id, shop_id, rule_key, scope_ref, value, "
                    "set_by, set_at) VALUES (:id, :shop, :key, 'G500001', :value, 'seller', :now)"
                ),
                {"id": uuid.uuid4(), "shop": shop_id, "key": key, "value": str(value), "now": NOW},
            )


def _line(ref: str, name: str, price: int) -> dict:
    return {
        "order_ref": ref,
        "line_no": 0,
        "ordered_at": "2026-10-05T10:15:00",
        "status": "delivered",
        "sku": "G500001",
        "variation_sku": "G500001",
        "variation_name": name,
        "qty": 1,
        "original_price": price,
        "deal_price": price,
        "paid_at": "2026-10-05T10:20:00",
    }


async def test_the_engine_costs_combos_by_pack_and_charges_the_income_order_its_actuals(
    owner_engine, shopee_tenants
):
    a, _ = shopee_tenants
    _seed_catalogue(owner_engine, a.shop_id)
    await _post(
        a.shop_id,
        "order_lines",
        _body(
            [_line(REF_1, "Combo 3 hộp", 90_000), _line(REF_2, "combo 10 hộp", 260_000)],
            dataset_period=("2026-10-05", "2026-10-05"),
        ),
    )
    await _post(
        a.shop_id,
        "order_income",
        _body([_income(REF_1)], captured_at="2026-11-03T09:35:00+07:00"),
    )
    stored = await _rows(
        a.shop_id,
        "SELECT order_ref, variation_id, variation_name FROM public.shopee_order_lines "
        "ORDER BY order_ref",
    )
    assert [
        (r.variation_id, r.variation_name) for r in stored if r.order_ref in (REF_1, REF_2)
    ] == [
        ("5003", "Combo 3 hộp"),
        ("5010", "combo 10 hộp"),
    ]  # the name told the variations apart although they share one SKU

    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            ctx = await loaders.load_context(session, a.shop_id)
            load = await loaders.load_order_lines(session, a.shop_id, WINDOW)
    assert set(load.income) == {REF_1}
    lines = to_shop_lines(load.lines, ctx.catalog, ctx.rules, load.income)
    costs = resolve_costs(lines, ctx.rules)
    assert {k: c.cogs for k, c in costs.by_key.items()} == {
        "G500001×3": Decimal(60_000),
        "G500001×10": Decimal(200_000),
    }
    pairs = profit_pairs(
        lines, costs, build_fee_context([sl.product_id for sl in lines], ctx.catalog)
    )
    by_ref = {ln.order_id: pb for ln, pb in pairs}
    assert by_ref[REF_1].fee_source == "income" and by_ref[REF_2].fee_source == "formula"
    # 90000 - (12330 + 3000 + 5400) fees - 60000 cogs - 2000 packaging - 0 - 2500 shipping
    assert by_ref[REF_1].contribution == Decimal(4_770)
    cov = income_coverage(pairs)
    assert (cov.orders, cov.with_income, cov.orders_pct) == (2, 1, Decimal("50.0"))
    assert cost_coverage(pairs, costs).json()["real_pct"] == 100.0


# =========================================================================== down and up


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 116, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def present() -> tuple[bool, bool]:
        with owner_engine.connect() as conn:
            table = conn.execute(text("SELECT to_regclass('public.shopee_order_income')")).scalar()
            col = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                    "AND table_name = 'shopee_order_lines' AND column_name = 'variation_name'"
                )
            ).scalar()
            return table is not None, col is not None

    assert present() == (True, True)
    command.downgrade(cfg, "116_shopee_reco_codes")
    try:
        assert present() == (False, False)
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('public.shopee_order_lines')")).scalar()
    finally:
        command.upgrade(cfg, "head")
    assert present() == (True, True)

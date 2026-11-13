"""P96, migration 122 on real Postgres: ``shopee_affiliate_lines`` -- RLS, grants, the gateway as
``juli_app``, the KOL loader under each shop's scope, up / down.

- row-level security is on; ``juli_app`` has SELECT, INSERT, UPDATE (a later report moves a line),
  ``juli_ops`` nothing;
- two tenants: a shop sees and writes only its own lines; a smuggled insert for another shop fails;
- the gateway, as the runtime role under a shop's scope, stores every report line of an order the
  export does not hold, updates it on a re-read (one row), and the other shop sees none of it;
- ``kol_affiliate.load_affiliate_lines`` under a shop's scope returns only that shop's lines;
- the account purge sweeps the table (uuid ``shop_id``);
- last: ``downgrade`` to 121 drops the table, ``upgrade head`` restores it.

Synthetic tenants only; no buyer data exists in the table.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as svc
from juli_backend.services.shopee_analytics import kol_affiliate
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
NOW = datetime(2026, 11, 6, 3, 0)
TABLE = "shopee_affiliate_lines"
REF_A = "c" * 32
REF_B = "d" * 32


def _verbs(conn, role: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{TABLE}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _insert(conn, shop_id: uuid.UUID, ref: str) -> None:
    conn.execute(
        text(
            "INSERT INTO public.shopee_affiliate_lines (id, shop_id, platform, order_ref, line_no, "
            "item_id, ordered_at, source, source_version) "
            "VALUES (:id, :shop, 'shopee', :ref, 0, '1001', :now, 'extension', '0.3.6')"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "ref": ref, "now": NOW},
    )


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def test_the_table_has_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        on = conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :t"
            ),
            {"t": TABLE},
        ).scalar()
    assert on is True


def test_grants_are_upsert_for_the_runtime_role_and_none_for_ops(owner_engine):
    with owner_engine.connect() as conn:
        assert _verbs(conn, RUNTIME_ROLE) == {"SELECT", "INSERT", "UPDATE"}
        if _role_exists(conn, "juli_ops"):
            assert _verbs(conn, "juli_ops") == set()


def test_a_shop_sees_and_writes_only_its_own_lines(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, a.shop_id, "a" * 32)
        _insert(conn, b.shop_id, "b" * 32)
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(
            conn.execute(text("SELECT shop_id FROM public.shopee_affiliate_lines")).scalars()
        )
        assert shops == {a.shop_id}
        _insert(conn, a.shop_id, "e" * 32)
        with pytest.raises(DBAPIError):
            _insert(conn, b.shop_id, "f" * 32)
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_the_purge_sweep_finds_the_table(owner_engine):
    """The purge deletes from every base table with a uuid ``shop_id`` (094)."""
    with owner_engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                "AND NOT a.attisdropped AND c.relname = :t"
            ),
            {"t": TABLE},
        ).scalar()
    assert found == TABLE


def _report(ref: str, **over) -> dict:
    base = {
        "order_ref": ref,
        "item_id": "1001",
        "price": 90000,
        "qty": 1,
        "order_value": 90000,
        "ordered_at": "2026-11-05T10:15:00",
        "order_status": "Đang xử lý",
        "affiliate_account": "kol_moi",
        "channel": "Shopee Video",
        "cost": 4500,
        "valid": True,
    }
    return {**base, **over}


def _body(rows: list[dict]) -> dict:
    return {
        "source": "extension",
        "source_version": "0.3.6",
        "captured_at": "2026-11-06T09:30:00+07:00",
        "period": {"start": "2026-10-07", "end": "2026-11-05", "granularity": "period"},
        "rows": rows,
    }


async def _post(shop_id: uuid.UUID, body: dict) -> None:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            await svc.ingest(
                session,
                shop_id=shop_id,
                platform="shopee",
                dataset="affiliate_order_lines",
                body=svc.IngestBody.model_validate(body),
                token_id=None,
                now=NOW,
            )
        await session.commit()


async def _lines(shop_id: uuid.UUID) -> list[kol_affiliate.AffiliateLine]:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return await kol_affiliate.load_affiliate_lines(
                session, shop_id, date(2026, 10, 7), date(2026, 11, 5)
            )


async def test_the_gateway_stores_report_lines_without_the_export_as_the_runtime_role(
    shopee_tenants,
):
    a, b = shopee_tenants
    await _post(a.shop_id, _body([_report(REF_A), _report(REF_B, valid=False)]))
    # the next day's report: the order is finished now -- same key, one row, updated
    await _post(a.shop_id, _body([_report(REF_A, order_status="Đã hoàn thành")]))
    lines = await _lines(a.shop_id)
    by_ref = {line.order_ref: line for line in lines}
    assert set(by_ref) == {REF_A, REF_B}
    assert by_ref[REF_A].order_status == "Đã hoàn thành" and by_ref[REF_B].valid is False
    assert by_ref[REF_A].kol_handle == "kol_moi" and by_ref[REF_A].commission is not None
    assert await _lines(b.shop_id) == []


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 121, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def exists() -> bool:
        with owner_engine.connect() as conn:
            found = conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{TABLE}"}).scalar()
            return found is not None

    assert exists()
    command.downgrade(cfg, "121_shop_members")
    try:
        assert not exists()
    finally:
        command.upgrade(cfg, "head")
    assert exists()

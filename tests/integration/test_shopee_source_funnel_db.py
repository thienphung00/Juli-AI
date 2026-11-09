"""P98, migration 126 on real Postgres: ``shopee_source_metrics_daily`` -- RLS, grants, the natural
key with a NULL item, up / down.

- row-level security is on; ``juli_app`` has SELECT, INSERT, UPDATE, ``juli_ops`` nothing;
- two tenants: a shop sees and writes only its own rows; a smuggled insert for another shop fails;
- the shop row (``item_id`` NULL) and a product row are each unique per (shop, day, item, source):
  a second shop row for the same source fails, as does a second product row;
- the purge sweep finds the table (uuid ``shop_id``);
- last: ``downgrade`` to 125 drops the table, ``upgrade head`` restores it.

Synthetic tenants only; the table holds aggregates, no buyer data.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
TABLE = "shopee_source_metrics_daily"
DAY = date(2026, 11, 5)


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


def _insert(conn, shop_id: uuid.UUID, *, item: str | None = None, source: str = "video") -> None:
    conn.execute(
        text(
            "INSERT INTO public.shopee_source_metrics_daily (id, shop_id, day, item_id, source, "
            "views, clicks, orders, gmv) VALUES (:id, :shop, :day, :item, :source, 10, 2, 1, 50000)"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "day": DAY, "item": item, "source": source},
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


def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, a.shop_id, source="live")
        _insert(conn, b.shop_id, source="live")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(conn.execute(text(f"SELECT shop_id FROM public.{TABLE}")).scalars())  # nosec B608
        assert shops == {a.shop_id}
        _insert(conn, a.shop_id, source="lien_ket")
        with pytest.raises(DBAPIError):
            _insert(conn, b.shop_id, source="lien_ket")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_the_natural_key_holds_for_the_shop_row_and_the_product_row(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.connect() as conn:
        _insert(conn, a.shop_id, source="trang_shop")
        _insert(conn, a.shop_id, item="1001", source="trang_shop")
        with pytest.raises(IntegrityError):
            _insert(conn, a.shop_id, source="trang_shop")
        conn.rollback()
        _insert(conn, a.shop_id, item="1001", source="trang_shop")
        with pytest.raises(IntegrityError):
            _insert(conn, a.shop_id, item="1001", source="trang_shop")
        conn.rollback()


def test_an_unknown_source_is_refused(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            _insert(conn, a.shop_id, source="quang_cao")
        conn.rollback()


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


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 125, then back to head."""
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
    command.downgrade(cfg, "125_reco_plan_groups")
    try:
        assert not exists()
    finally:
        command.upgrade(cfg, "head")
    assert exists()

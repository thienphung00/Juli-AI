"""ADR-117, migration 108 on real Postgres: RLS, grants, round trip.

- every new table has row-level security on;
- the four client-lane tables isolate tenants under ``juli_app`` (a shop sees and writes
  only its own rows) and grant it exactly SELECT, INSERT, UPDATE;
- the KPI / lever / forecast and public-market tables grant ``juli_app``, ``anon`` and
  ``authenticated`` nothing, and ``juli_ops`` exactly the migration's verbs;
- ``downgrade`` to 107 removes the tables and ``mapper_version``; ``upgrade head`` brings
  them back.

It downgrades a revision, so it is in ``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES``
and gets a database of its own. Synthetic tenants only.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/108_shopee_ops_data.py"
)
OPS_ROLE = "juli_ops"
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _mig():
    spec = importlib.util.spec_from_file_location("mig108_db", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIG = _mig()
ALL_TABLES = (*MIG.TENANT_GRANTS, *MIG.OPS_GRANTS)


def _granted(engine, role: str, table: str) -> set[str]:
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        ).scalar()
        if not exists:
            return set()
        return {
            verb
            for verb in VERBS
            if conn.execute(
                text("SELECT has_table_privilege(:r, :t, :v)"),
                {"r": role, "t": f"public.{table}", "v": verb},
            ).scalar()
        }


def _verbs(spec: str) -> set[str]:
    return {v.strip() for v in spec.split(",")}


def _insert_period(conn, shop_id: uuid.UUID, item_id: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute(
        text(
            "INSERT INTO public.platform_period_metrics (id, shop_id, platform, dataset, "
            "period_start, period_end, item_id, stream, order_type, gmv, confidence, extra, "
            "source, source_rank, source_version, mapper_version, captured_at, updated_at) "
            "VALUES (:id, :shop, 'shopee', 'product_period', '2026-10-01', '2026-10-28', "
            ":item, 'total', 'confirmed', 1000, 'high', '{}'::jsonb, 'file', 2, 'test-1', 1, "
            ":now, :now)"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "item": item_id, "now": now},
    )


def test_every_new_table_has_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": list(ALL_TABLES)},
            ).all()
        )
    assert set(rows) == set(ALL_TABLES)
    assert all(rows.values()), rows


def test_client_lane_tables_grant_the_app_exactly_select_insert_update(owner_engine):
    for table, spec in MIG.TENANT_GRANTS.items():
        assert _granted(owner_engine, RUNTIME_ROLE, table) == _verbs(spec), table


def test_ops_tables_grant_the_app_nothing_and_ops_exactly_its_verbs(owner_engine):
    for table, spec in MIG.OPS_GRANTS.items():
        for role in (RUNTIME_ROLE, "anon", "authenticated"):
            assert _granted(owner_engine, role, table) == set(), (role, table)
        assert _granted(owner_engine, OPS_ROLE, table) == _verbs(spec), table


def test_a_shop_sees_and_writes_only_its_own_period_rows(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert_period(conn, a.shop_id, "111")
        _insert_period(conn, b.shop_id, "222")

    with owner_engine.connect() as conn:
        conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
        conn.execute(
            text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(a.shop_id)}
        )
        items = (
            conn.execute(text("SELECT item_id FROM public.platform_period_metrics")).scalars().all()
        )
        assert items == ["111"]
        # Writing another shop's row is refused by the WITH CHECK policy.
        with pytest.raises(DBAPIError):
            _insert_period(conn, b.shop_id, "333")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_zz_downgrade_removes_108_and_upgrade_restores_it(owner_engine):
    """Last in the module: down to 107 (tables and column gone), then back to head."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    # A later migration may sit on 108: the module starts and ends at head.
    head = ScriptDirectory.from_config(cfg).get_current_head()

    def state() -> tuple[str, set[str], bool]:
        with owner_engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            present = set(
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename = ANY(:t)"
                    ),
                    {"t": list(ALL_TABLES)},
                ).scalars()
            )
            column = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                    "AND table_name = 'platform_daily_metrics' AND column_name = 'mapper_version'"
                )
            ).scalar()
        return version, present, bool(column)

    assert state() == (head, set(ALL_TABLES), True)
    command.downgrade(cfg, MIG.down_revision)
    assert state() == (MIG.down_revision, set(), False)
    command.upgrade(cfg, "head")
    assert state() == (head, set(ALL_TABLES), True)
    for table, spec in MIG.OPS_GRANTS.items():
        assert _granted(owner_engine, OPS_ROLE, table) == _verbs(spec), table

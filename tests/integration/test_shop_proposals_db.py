"""ADR-118, migration 109 on real Postgres: RLS and grants of the manual cycle.

- the four tables have row-level security on;
- ``juli_app`` gets exactly the migration's verbs: proposals SELECT, INSERT, UPDATE;
  approvals and results SELECT, INSERT (append-only); executions SELECT, INSERT and
  UPDATE on ``verified_at`` / ``verified_how`` / ``verified_state`` only;
- a shop sees and writes only its own proposals, and cannot rewrite an approval or an
  execution's time.

Synthetic tenants only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/109_shop_proposals.py"
)
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _mig():
    spec = importlib.util.spec_from_file_location("mig109_db", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIG = _mig()
TABLES = tuple(MIG.TENANT_GRANTS)


def _table_verbs(conn, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": RUNTIME_ROLE, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _column_update(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT has_column_privilege(:r, :t, :c, 'UPDATE')"),
            {"r": RUNTIME_ROLE, "t": f"public.{table}", "c": column},
        ).scalar()
    )


def _as_shop(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def _insert_proposal(conn, shop_id: uuid.UUID, label: str) -> uuid.UUID:
    proposal_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.shop_proposals (id, shop_id, platform, cycle, kind, "
            "subject_type, subject_label, change_before, change_after, reason) "
            "VALUES (:id, :shop, 'shopee', '2026-11 Đợt 1', 'voucher', 'shop', :label, "
            "'{}'::jsonb, CAST(:after AS jsonb), 'synthetic')"
        ),
        {"id": proposal_id, "shop": shop_id, "label": label, "after": json.dumps({"v": 1})},
    )
    return proposal_id


def test_every_table_has_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": list(TABLES)},
            ).all()
        )
    assert set(rows) == set(TABLES)
    assert all(rows.values()), rows


def test_the_app_gets_exactly_the_migrations_verbs(owner_engine):
    with owner_engine.connect() as conn:
        assert _table_verbs(conn, "shop_proposals") == {"SELECT", "INSERT", "UPDATE"}
        for table in ("shop_proposal_approvals", "shop_proposal_results"):
            assert _table_verbs(conn, table) == {"SELECT", "INSERT"}, table
            assert not _column_update(conn, table, "created_at" if "appr" in table else "value")
        # Executions: no table-wide UPDATE, only the three verified_* columns.
        assert _table_verbs(conn, "shop_proposal_executions") == {"SELECT", "INSERT"}
        for column in ("verified_at", "verified_how", "verified_state"):
            assert _column_update(conn, "shop_proposal_executions", column), column
        for column in ("executed_at", "executor_role", "evidence_ref"):
            assert not _column_update(conn, "shop_proposal_executions", column), column


def test_a_shop_sees_and_writes_only_its_own_cycle(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        mine = _insert_proposal(conn, a.shop_id, "A voucher")
        _insert_proposal(conn, b.shop_id, "B voucher")
        conn.execute(
            text(
                "INSERT INTO public.shop_proposal_executions (id, shop_id, proposal_id, "
                "executed_at, executor_role, recorded_by_staff_id, channel) "
                "VALUES (:id, :shop, :p, :at, 'client_representative', :staff, 'ops')"
            ),
            {
                "id": uuid.uuid4(),
                "shop": a.shop_id,
                "p": mine,
                "at": datetime.now(UTC).replace(tzinfo=None),
                "staff": uuid.uuid4(),
            },
        )
    with owner_engine.connect() as conn:
        _as_shop(conn, a.shop_id)
        labels = conn.execute(text("SELECT subject_label FROM public.shop_proposals")).scalars()
        assert list(labels) == ["A voucher"]
        # The verified_* columns are writable; the execution time is not.
        conn.execute(
            text(
                "UPDATE public.shop_proposal_executions SET verified_at = now(), "
                "verified_how = 'export_readback', verified_state = '{}'::jsonb"
            )
        )
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE public.shop_proposal_executions SET executed_at = now()"))
        conn.rollback()
        _as_shop(conn, a.shop_id)
        # Another shop's proposal is refused by the WITH CHECK policy.
        with pytest.raises(DBAPIError):
            _insert_proposal(conn, b.shop_id, "smuggled")
        conn.rollback()
        conn.execute(text("RESET ROLE"))

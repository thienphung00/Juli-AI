"""Schema/migration checks for #1117 / AGT-W3A (migration
`034_workflow_runs_table`) -- ties directly to the issue's acceptance
criteria: the `workflow_runs` shape, the `tool_executions` idempotency-ledger
columns + uniqueness (with the twelve pre-existing columns proven
byte-identical before/after), the partial unique index's actual runtime
behavior, the deferred `impact_readings.run_id` FK, exactly one migration
head, and additive-only-ness across the whole schema.

File-content assertions (revision string, down_revision, single head) need
no database and always run. Everything else is gated by `requires_postgres`
(reused from `tests/integration/test_migrations.py`, the same gate every
other migration-shaped test in this repo already uses) and skips cleanly
wherever `DATABASE_URL` is not a reachable local Postgres.

The two "before/after migration 034" tests reset their own dedicated engine
back to revision 033 (a downgrade local to whatever *disposable* database
`DATABASE_URL` names) before upgrading to head again -- guarded by
`_assert_local_database_url`, the same "never touch a non-local host"
discipline `tests/integration/test_migrations.py` established for issue
#734, so this only ever runs against a throwaway local Postgres.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_034_PATH = MIGRATIONS_DIR / "034_workflow_runs_table.py"

_KNOWN_SCHEMAS = ("public", "bronze", "silver", "gold", "ops")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

EXPECTED_TOOL_EXECUTIONS_PRE_EXISTING_COLUMNS = (
    "id",
    "shop_id",
    "approval_id",
    "tool_name",
    "payload_json",
    "idempotency_key",
    "status",
    "celery_task_id",
    "outcome_json",
    "error_message",
    "error_category",
    "created_at",
    "updated_at",
)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


def _assert_local_database_url(url: str) -> None:
    """Refuse to downgrade against anything but a local, disposable Postgres
    -- issue #734's discipline, reproduced here rather than importing a
    private helper from another test module."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname}); this test only ever downgrades a "
            "throwaway local database."
        )


def _reset_to_revision(cfg: Config, revision: str) -> None:
    _assert_local_database_url(_database_url())
    command.downgrade(cfg, "base")
    command.upgrade(cfg, revision)


def _columns_by_name(engine: Engine, table: str, schema: str | None = None) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns(table, schema=schema)}


def _full_schema_snapshot(engine: Engine) -> dict[tuple[str, str], dict[str, dict]]:
    """{(schema, table): {column_name: column_info}} for every user schema."""
    inspector = inspect(engine)
    snapshot: dict[tuple[str, str], dict[str, dict]] = {}
    existing_schemas = set(inspector.get_schema_names())
    for schema in _KNOWN_SCHEMAS:
        if schema not in existing_schemas:
            continue
        for table in inspector.get_table_names(schema=schema):
            snapshot[(schema, table)] = _columns_by_name(engine, table, schema=schema)
    return snapshot


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_034_revision_equals_filename_stem():
    assert MIGRATION_034_PATH.exists(), f"missing {MIGRATION_034_PATH}"
    body = MIGRATION_034_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 034 has no `revision: str = ...` line"
    assert rev.group(1) == "034_workflow_runs_table"
    assert rev.group(1) == MIGRATION_034_PATH.stem


def test_migration_034_down_revision_is_033():
    body = MIGRATION_034_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 034 has no string `down_revision`"
    assert down.group(1) == "033_impact_readings_table"


def test_exactly_one_migration_head_after_034():
    """Walks the entire chain (not just 034) so a second, unrelated branch
    anywhere in the tree also fails this."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None
    parents = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in parents]
    assert heads == ["034_workflow_runs_table"], f"expected exactly one head, got {sorted(heads)}"


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
def test_workflow_runs_table_shape_at_head(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    assert "workflow_runs" in inspector.get_table_names()

    columns = _columns_by_name(postgres_at_head, "workflow_runs")
    expected_columns = {
        "id",
        "shop_id",
        "product_id",
        "state",
        "status",
        "stop_reason",
        "prompt_version",
        "prompt_sha256",
        "started_at",
        "completed_at",
        "waiting_approval_since",
        "running_seconds_elapsed",
        "created_at",
        "updated_at",
    }
    assert expected_columns <= set(columns), f"missing columns: {expected_columns - set(columns)}"

    assert "JSONB" in str(columns["state"]["type"]).upper()
    assert columns["state"]["nullable"] is False

    for str_col in ("status", "prompt_version", "prompt_sha256"):
        type_name = str(columns[str_col]["type"]).upper()
        assert "CHAR" in type_name, f"{str_col} expected a string type, got {type_name}"
        assert columns[str_col]["nullable"] is False

    assert "CHAR" in str(columns["stop_reason"]["type"]).upper()
    assert columns["stop_reason"]["nullable"] is True, "stop_reason must be nullable until terminal"

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("workflow_runs")
    }
    assert fks.get("shop_id") == "shops"
    assert fks.get("product_id") == "products"


@requires_postgres
def test_workflow_runs_partial_unique_index_blocks_second_active_run(postgres_at_head: Engine):
    """ADR-073 decision 4: one active run per (shop_id, product_id). A
    second INSERT while an existing row is queued/running/waiting_approval
    must raise a unique violation; a second INSERT once the existing row is
    terminal must NOT."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user = m.User(phone="+15550000001")
        session.add(user)
        session.flush()
        shop = m.Shop(user_id=user.id, shop_name="AGT-W3A Test Shop")
        session.add(shop)
        session.flush()
        product = m.Product(
            shop_id=shop.id,
            tiktok_product_id="agt-w3a-product-1",
            name="Test Widget",
            status="active",
            update_time=datetime.now(UTC),
        )
        session.add(product)
        session.flush()

        def new_run(status: str) -> m.WorkflowRun:
            return m.WorkflowRun(
                shop_id=shop.id,
                product_id=product.id,
                state={},
                status=status,
                prompt_version="optimize_product.v1",
                prompt_sha256="a" * 64,
            )

        run1 = new_run("running")
        session.add(run1)
        session.commit()

        for active_status in ("queued", "running", "waiting_approval"):
            run1.status = active_status
            session.commit()

            conflicting = new_run("queued")
            session.add(conflicting)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        for terminal_status in ("completed", "cancelled", "timed_out", "failed"):
            # Only one row may exist for the pair while the guard is active,
            # so retarget run1 to terminal, then prove a *second* row for
            # the same (shop_id, product_id) is allowed once nothing active
            # remains.
            run1.status = terminal_status
            session.commit()

            second = new_run(terminal_status)
            session.add(second)
            session.commit()
            session.delete(second)
            session.commit()


@requires_postgres
def test_tool_executions_gains_ledger_columns_and_unique_constraint(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    columns = _columns_by_name(postgres_at_head, "tool_executions")

    for col in ("workflow_run_id", "tool_call_id", "operation"):
        assert col in columns, f"missing ledger column: {col}"
        assert columns[col]["nullable"] is True, f"{col} must be nullable (legacy rows have none)"

    unique_column_sets = {
        frozenset(u["column_names"]) for u in inspector.get_unique_constraints("tool_executions")
    }
    assert frozenset({"workflow_run_id", "tool_call_id", "operation"}) in unique_column_sets

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("tool_executions")
    }
    assert fks.get("workflow_run_id") == "workflow_runs"


@requires_postgres
def test_tool_executions_pre_existing_columns_byte_identical_before_and_after_034():
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "033_impact_readings_table")
        before = _columns_by_name(engine, "tool_executions")
        assert set(EXPECTED_TOOL_EXECUTIONS_PRE_EXISTING_COLUMNS) <= set(before), (
            "test setup problem: expected pre-existing tool_executions columns "
            "are missing at revision 033"
        )

        command.upgrade(cfg, "034_workflow_runs_table")
        after = _columns_by_name(engine, "tool_executions")

        for name in EXPECTED_TOOL_EXECUTIONS_PRE_EXISTING_COLUMNS:
            assert name in after, f"pre-existing column dropped by migration 034: {name}"
            b, a = before[name], after[name]
            assert str(b["type"]) == str(a["type"]), (
                f"{name} type changed by migration 034: {b['type']} -> {a['type']}"
            )
            assert b["nullable"] == a["nullable"], (
                f"{name} nullability changed by migration 034: {b['nullable']} -> {a['nullable']}"
            )
    finally:
        engine.dispose()


@requires_postgres
def test_impact_readings_run_id_fk_and_033_constraints_unchanged(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)

    fk_by_col = {
        fk["constrained_columns"][0]: fk for fk in inspector.get_foreign_keys("impact_readings")
    }
    assert "run_id" in fk_by_col, "impact_readings.run_id has no FK at head"
    assert fk_by_col["run_id"]["referred_table"] == "workflow_runs"

    # Migration 033's own FK must be untouched.
    assert "tool_execution_id" in fk_by_col
    assert fk_by_col["tool_execution_id"]["referred_table"] == "tool_executions"

    uniques = {
        u["name"]: set(u["column_names"])
        for u in inspector.get_unique_constraints("impact_readings")
    }
    assert uniques.get("uq_impact_readings_execution_metric_kind") == {
        "tool_execution_id",
        "metric",
        "kind",
    }

    check_names = {c["name"] for c in inspector.get_check_constraints("impact_readings")}
    assert "ck_impact_readings_kind" in check_names
    assert "ck_impact_readings_confidence" in check_names

    columns = _columns_by_name(postgres_at_head, "impact_readings")
    assert columns["run_id"]["nullable"] is True, "run_id must stay nullable (legacy readings)"


@requires_postgres
def test_migration_034_is_additive_only_across_entire_schema():
    """No existing column anywhere in the schema is dropped, renamed,
    narrowed, or made NOT NULL by migration 034 -- the issue's explicit
    additive-only acceptance criterion, checked across every table in every
    schema the migration chain creates, not just workflow_runs/
    tool_executions/impact_readings."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "033_impact_readings_table")
        before = _full_schema_snapshot(engine)
        assert len(before) > 0, "test setup problem: schema snapshot at revision 033 is empty"

        command.upgrade(cfg, "034_workflow_runs_table")
        after = _full_schema_snapshot(engine)

        for (schema, table), before_columns in before.items():
            assert (schema, table) in after, f"table dropped by migration 034: {schema}.{table}"
            after_columns = after[(schema, table)]
            for col_name, before_info in before_columns.items():
                assert col_name in after_columns, (
                    f"column dropped by migration 034: {schema}.{table}.{col_name}"
                )
                after_info = after_columns[col_name]
                assert str(before_info["type"]) == str(after_info["type"]), (
                    f"column type changed by migration 034: {schema}.{table}.{col_name} "
                    f"{before_info['type']} -> {after_info['type']}"
                )
                if before_info["nullable"]:
                    assert after_info["nullable"], (
                        f"column narrowed to NOT NULL by migration 034: {schema}.{table}.{col_name}"
                    )
    finally:
        engine.dispose()

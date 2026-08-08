"""Unit tests for the additive-only migration gate (issue #834).

The gate exists because a candidate release and the stable release briefly share
one database. Additive-only change is what makes a code rollback safe: additive
changes stay compatible with the previous code, so reverting code needs no schema
undo. These tests therefore assert a *hard block* — a non-zero exit and a refusal
that names the offending change — never a warning.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent, indent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from migration_additive_gate import (  # noqa: E402
    GATE_EXIT_ACCEPTED,
    GATE_EXIT_REFUSED,
    evaluate_migration_paths,
    evaluate_migration_source,
    resolve_pending_migration_paths,
)

GATE_SCRIPT = SCRIPTS_DIR / "migration_additive_gate.py"


def _migration(body: str, revision: str = "999_test", downgrade: str = "    pass") -> str:
    """Build a migration module source.

    ``body`` and ``downgrade`` are normalised with dedent-then-indent rather than
    interpolated into an indented template: an f-string only carries the template's
    indent onto the *first* line of a multi-line value, which left later lines
    under-indented and made dedent strip the whole module's indentation instead.
    """
    return (
        '"""test migration"""\n'
        "\n"
        "import sqlalchemy as sa\n"
        "from alembic import op\n"
        "\n"
        f'revision = "{revision}"\n'
        'down_revision = "998_prev"\n'
        "\n"
        "\n"
        "def upgrade() -> None:\n"
        f"{indent(dedent(body), '    ')}\n"
        "\n"
        "\n"
        "def downgrade() -> None:\n"
        f"{indent(dedent(downgrade), '    ')}\n"
    )


def _write(tmp_path: Path, body: str, revision: str = "999_test", **kw) -> Path:
    path = tmp_path / f"{revision}.py"
    path.write_text(_migration(body, revision=revision, **kw), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Accepted: additive change
# --------------------------------------------------------------------------


def test_new_nullable_column_and_new_table_are_accepted():
    source = _migration(
        """\
    op.add_column(
        "orders", sa.Column("refund_note", sa.String(length=200), nullable=True)
    )
    op.create_table(
        "order_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_audit_order_id", "order_audit", ["order_id"])"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert result.accepted, result.report()
    assert result.findings == []


def test_new_table_may_declare_not_null_columns():
    # NOT NULL inside create_table constrains no pre-existing row, so it stays
    # compatible with the previous code, which never wrote to this table.
    source = _migration(
        """    op.create_table(
                "gold_kpi",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("value", sa.Numeric(18, 2), nullable=False),
                sa.PrimaryKeyConstraint("id"),
            )"""
    )
    assert evaluate_migration_source(source, revision="999_test").accepted


def test_added_not_null_column_with_server_default_is_accepted():
    source = _migration(
        """    op.add_column(
                "orders",
                sa.Column(
                    "retryable",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )"""
    )
    assert evaluate_migration_source(source, revision="999_test").accepted


def test_widening_type_change_is_accepted():
    source = _migration(
        """    op.alter_column(
                "orders",
                "external_id",
                existing_type=sa.String(length=64),
                type_=sa.String(length=255),
            )"""
    )
    assert evaluate_migration_source(source, revision="999_test").accepted


def test_non_destructive_raw_ddl_is_accepted():
    # RLS policies, schema creation and index drops move no rows and stay
    # readable by the previous code.
    source = _migration(
        """\
    op.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    op.execute("ALTER TABLE orders ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY orders_isolation ON orders USING (shop_id = 1)")
    op.drop_index("ix_orders_stale", table_name="orders")"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert result.accepted, result.report()


def test_destructive_statements_in_downgrade_are_ignored():
    # Migrations are never automatically reverted, so downgrade() is not part of
    # what a candidate start would apply.
    source = _migration(
        '    op.add_column("orders", sa.Column("note", sa.Text(), nullable=True))',
        downgrade='    op.drop_column("orders", "note")\n    op.drop_table("order_audit")',
    )
    assert evaluate_migration_source(source, revision="999_test").accepted


# --------------------------------------------------------------------------
# Refused: destructive change, with the offending change named
# --------------------------------------------------------------------------


def test_dropped_column_is_refused_and_names_the_column():
    source = _migration('    op.drop_column("orders", "legacy_status")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    report = result.report()
    assert "orders.legacy_status" in report
    assert "drop_column" in report
    assert any(f.kind == "destructive" for f in result.findings)


def test_dropped_table_is_refused_and_names_the_table():
    source = _migration('    op.drop_table("tiktok_sync_state")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "tiktok_sync_state" in result.report()


def test_renamed_table_is_refused_and_names_both_names():
    source = _migration('    op.rename_table("orders", "orders_v2")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    report = result.report()
    assert "orders" in report
    assert "orders_v2" in report


def test_renamed_column_is_refused_and_names_both_names():
    source = _migration(
        """    op.alter_column(
                "orders", "ship_time", new_column_name="shipped_at"
            )"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    report = result.report()
    assert "orders.ship_time" in report
    assert "shipped_at" in report


def test_narrowing_type_change_is_refused_and_names_both_types():
    source = _migration(
        """    op.alter_column(
                "products",
                "title",
                existing_type=sa.String(length=500),
                type_=sa.String(length=64),
            )"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    report = result.report()
    assert "products.title" in report
    assert "String(500)" in report
    assert "String(64)" in report


def test_narrowing_integer_type_change_is_refused():
    source = _migration(
        """    op.alter_column(
                "orders",
                "quantity",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
            )"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "orders.quantity" in result.report()


def test_type_change_without_existing_type_is_refused_as_unprovable():
    source = _migration('    op.alter_column("orders", "amount", type_=sa.Numeric(10, 2))')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "orders.amount" in result.report()


def test_setting_not_null_on_existing_column_is_refused():
    source = _migration(
        """    op.alter_column(
                "orders", "cancel_reason", existing_type=sa.String(length=500), nullable=False
            )"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "orders.cancel_reason" in result.report()


def test_added_not_null_column_without_server_default_is_refused():
    source = _migration(
        '    op.add_column("orders", sa.Column("channel", sa.String(length=20), nullable=False))'
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "orders.channel" in result.report()


def test_raw_sql_drop_column_is_refused():
    # Raw SQL must not be an escape hatch around the op.* checks.
    source = _migration('    op.execute("ALTER TABLE orders DROP COLUMN legacy_status")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "DROP COLUMN" in result.report().upper()


def test_raw_sql_drop_table_is_refused():
    source = _migration('    op.execute("DROP TABLE IF EXISTS orders_legacy")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert "orders_legacy" in result.report()


# --------------------------------------------------------------------------
# Refused: data-moving migration
# --------------------------------------------------------------------------


def test_data_moving_update_is_refused_and_names_the_statement():
    source = _migration(
        "    op.execute(\"UPDATE orders SET channel = 'tiktok' WHERE channel IS NULL\")"
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert any(f.kind == "data_moving" for f in result.findings)
    report = result.report()
    assert "UPDATE orders SET" in report


def test_data_moving_insert_select_backfill_is_refused():
    source = _migration(
        """\
    sql = "INSERT INTO silver_orders (id, shop_id) SELECT id, shop_id FROM bronze_orders"
    op.execute(sql)"""
    )
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert any(f.kind == "data_moving" for f in result.findings)
    assert "INSERT INTO silver_orders" in result.report()


def test_data_moving_delete_is_refused():
    source = _migration('    op.execute("DELETE FROM processed_events WHERE shop_id IS NULL")')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert any(f.kind == "data_moving" for f in result.findings)


def test_bulk_insert_is_refused():
    source = _migration('    op.bulk_insert(seed_table, [{"id": 1, "name": "default"}])')
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert any(f.kind == "data_moving" for f in result.findings)
    assert "bulk_insert" in result.report()


def test_unresolvable_execute_argument_is_refused_as_unverifiable():
    source = _migration("    op.execute(build_statement(table))")
    result = evaluate_migration_source(source, revision="999_test")
    assert not result.accepted
    assert any(f.kind == "unverifiable" for f in result.findings)


# --------------------------------------------------------------------------
# Whole-run behaviour: every offence named, hard block, revision resolution
# --------------------------------------------------------------------------


def test_report_names_every_offending_change_not_just_the_first(tmp_path: Path):
    a = _write(
        tmp_path,
        '    op.drop_column("orders", "legacy_status")',
        revision="900_drop_col",
    )
    b = _write(tmp_path, '    op.rename_table("shops", "shops_v2")', revision="901_rename")
    c = _write(
        tmp_path,
        '    op.execute("UPDATE orders SET total = 0")',
        revision="902_backfill",
    )
    result = evaluate_migration_paths([a, b, c])
    assert not result.accepted
    report = result.report()
    assert "orders.legacy_status" in report
    assert "shops_v2" in report
    assert "UPDATE orders SET" in report
    assert {"900_drop_col", "901_rename", "902_backfill"} <= set(result.inspected)


def test_resolve_pending_migration_paths_selects_only_pending_revisions(tmp_path: Path):
    _write(tmp_path, "    pass", revision="800_old")
    pending = _write(tmp_path, "    pass", revision="801_new")
    resolved = resolve_pending_migration_paths(tmp_path, ["801_new"])
    assert resolved == [pending]


def test_resolve_pending_migration_paths_raises_on_missing_revision(tmp_path: Path):
    _write(tmp_path, "    pass", revision="800_old")
    try:
        resolve_pending_migration_paths(tmp_path, ["nope_missing"])
    except RuntimeError as exc:
        assert "nope_missing" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected RuntimeError for an unresolvable revision")


def _run_gate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR),
        check=False,
    )


def test_cli_accepts_an_additive_migration_with_exit_zero(tmp_path: Path):
    path = _write(
        tmp_path,
        '    op.add_column("orders", sa.Column("note", sa.Text(), nullable=True))',
        revision="910_additive",
    )
    result = _run_gate("--migration-file", str(path))
    assert result.returncode == GATE_EXIT_ACCEPTED == 0, result.stdout + result.stderr
    assert "ADDITIVE-ONLY: ACCEPTED" in result.stdout


def test_cli_hard_blocks_a_destructive_migration(tmp_path: Path):
    path = _write(
        tmp_path,
        '    op.drop_column("orders", "legacy_status")',
        revision="911_destructive",
    )
    result = _run_gate("--migration-file", str(path))
    assert result.returncode == GATE_EXIT_REFUSED
    assert result.returncode != 0, "the gate must be a hard block, not a warning"
    assert "REFUSED" in result.stdout
    assert "orders.legacy_status" in result.stdout
    assert "WARN" not in result.stdout


def test_cli_refuses_a_data_moving_migration_from_automatic_release(tmp_path: Path):
    path = _write(
        tmp_path,
        '    op.execute("UPDATE orders SET total = 0 WHERE total IS NULL")',
        revision="912_backfill",
    )
    result = _run_gate("--migration-file", str(path))
    assert result.returncode == GATE_EXIT_REFUSED
    assert "UPDATE orders SET" in result.stdout


def test_cli_resolves_pending_revisions_from_a_migrations_dir(tmp_path: Path):
    _write(tmp_path, '    op.drop_table("orders")', revision="920_not_pending")
    _write(
        tmp_path,
        '    op.add_column("orders", sa.Column("note", sa.Text(), nullable=True))',
        revision="921_pending",
    )
    result = _run_gate("--migrations-dir", str(tmp_path), "--revisions", "921_pending")
    assert result.returncode == GATE_EXIT_ACCEPTED, result.stdout + result.stderr


def test_cli_with_no_pending_revisions_accepts(tmp_path: Path):
    result = _run_gate("--migrations-dir", str(tmp_path), "--revisions", "")
    assert result.returncode == GATE_EXIT_ACCEPTED
    assert "ADDITIVE-ONLY: ACCEPTED" in result.stdout

"""Contract tests for the demo_execution_records migration (#717, B-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/028_demo_execution_records.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain_extends_current_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "028_demo_execution_records"' in text
    assert 'down_revision: str | None = "027_decision_emission_budget"' in text


def test_migration_only_creates_a_new_table_and_indexes():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '"demo_execution_records"' in text
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert "op.create_table" in upgrade_body
    assert "op.create_index" in upgrade_body
    # Additive-only: no destructive ops, and no existing table is touched.
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    assert "rename_table" not in upgrade_body
    assert "alter_column" not in upgrade_body
    assert "add_column" not in upgrade_body


def test_migration_satisfies_additive_gate():
    """The migration additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_demo_execution_records_is_exactly_one_alembic_head_at_028():
    """Guards the single-head invariant; the literal head id advances as later
    slices stack on top of 028 (e.g. 029_bronze_ctor_live_hours, #880)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads == ["029_bronze_ctor_live_hours"]

"""Contract tests for the impact_readings migration (#1040, ADR-077 d.5, I9)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/033_impact_readings_table.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain_extends_current_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "033_impact_readings_table"' in text
    assert 'down_revision: str | None = "032_close_public_schema_defaults"' in text


def test_migration_creates_only_a_new_table_no_existing_table_touched():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert upgrade_body.count('op.create_table(\n        "impact_readings"') == 1
    # Additive-only: no destructive ops, no touching an existing table.
    assert "add_column" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body
    assert "rename_table" not in upgrade_body


def test_migration_declares_every_adr_077_d5_column():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    for column in (
        "run_id",
        "tool_execution_id",
        "metric",
        "kind",
        "pre",
        "post",
        "expected",
        "incremental",
        "impact_pct",
        "confidence",
        "control_set_json",
        "computed_at",
    ):
        assert f'"{column}"' in upgrade_body, f"missing column: {column}"


def test_run_id_has_no_foreign_key_constraint_but_tool_execution_id_does():
    """The known dependency constraint from the issue: `workflow_runs` does not
    exist yet, so `run_id` must not carry a FK; `tool_execution_id` targets
    the pre-existing `tool_executions` table and does."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert '["tool_execution_id"], ["tool_executions.id"]' in upgrade_body
    assert '"run_id"' in upgrade_body
    assert 'ForeignKeyConstraint(["run_id"]' not in upgrade_body, (
        "run_id must not carry a ForeignKeyConstraint until W3-A lands workflow_runs"
    )
    # Exactly one FK constraint call in op.create_table() — tool_execution_id's.
    assert upgrade_body.count("sa.ForeignKeyConstraint(") == 1
    # The deferred-constraint decision must be documented, not silent.
    assert "workflow_runs" in text
    assert "W3-A" in text


def test_unique_constraint_on_execution_metric_kind():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert "uq_impact_readings_execution_metric_kind" in upgrade_body
    assert '"tool_execution_id",\n            "metric",\n            "kind",' in upgrade_body


def test_check_constraints_enumerate_exactly_the_documented_values():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '_VALID_KINDS = ("preliminary", "final")' in text
    assert '_VALID_CONFIDENCE = ("cao", "trung_binh", "thap", "suppressed", "confounded")' in text
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert "ck_impact_readings_kind" in upgrade_body
    assert "ck_impact_readings_confidence" in upgrade_body


def test_numeric_precisions_reuse_analytics_performance_interval_scales():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    for column in ("pre", "post", "expected", "incremental"):
        assert re.search(rf'"{column}",\s*sa\.Numeric\(18, 2\)', upgrade_body), column
    assert re.search(r'"impact_pct",\s*sa\.Numeric\(10, 6\)', upgrade_body)


def test_downgrade_drops_the_table_and_its_indexes():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_body = text.split("def downgrade")[1]
    assert 'op.drop_table("impact_readings")' in downgrade_body
    assert "ix_impact_readings_run_id" in downgrade_body
    assert "ix_impact_readings_tool_execution" in downgrade_body


def test_migration_satisfies_additive_gate():
    """The migration additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_impact_readings_migration_is_exactly_one_alembic_head():
    """Guards the single-head invariant (no branching), not a pinned head id —
    same rationale as 032's equivalent test: pinning `heads == [...]` breaks
    the moment a later slice stacks on top for a reason unrelated to this
    file. Assert 033 remains an ancestor of whatever head is current."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    ancestry = {rev.revision for rev in script.walk_revisions(base="base", head="head")}
    assert "033_impact_readings_table" in ancestry

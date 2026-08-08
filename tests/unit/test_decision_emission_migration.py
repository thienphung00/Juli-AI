"""Contract tests for the decision-emission-budget migration (#716, B-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/027_decision_emission_budget.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain_extends_current_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "027_decision_emission_budget"' in text
    assert 'down_revision: str | None = "026_action_cards_computed_at"' in text


def test_migration_adds_only_nullable_columns_and_a_new_table():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    for column in ("dismissed_at", "surfaced_at", "suppressed_reason"):
        assert f'"{column}"' in text
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert upgrade_body.count("nullable=True") >= 3
    # Additive-only: no destructive ops anywhere in upgrade().
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    assert "rename_table" not in upgrade_body
    assert "alter_column" not in upgrade_body


def test_migration_satisfies_additive_gate():
    """The migration additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_action_cards_still_has_exactly_one_alembic_head_at_027():
    """Guards the single-head invariant; the literal head id advances as later
    slices stack on top of 027 (e.g. 028_demo_execution_records, #717 B-5)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads == ["028_demo_execution_records"]

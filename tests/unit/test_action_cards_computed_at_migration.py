"""Contract tests for the action_cards.computed_at freshness migration (#715, B-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/026_action_cards_computed_at.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain_extends_current_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "026_action_cards_computed_at"' in text
    assert 'down_revision: str | None = "025_silver_orders_returns"' in text


def test_migration_adds_nullable_computed_at_column_only():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'op.add_column(\n        "action_cards"' in text or (
        'op.add_column("action_cards"' in text
    )
    assert '"computed_at"' in text
    assert "nullable=True" in text
    # Additive-only: no destructive ops anywhere in upgrade().
    assert "drop_column" not in text.split("def downgrade")[0]
    assert "drop_table" not in text
    assert "rename_table" not in text
    assert "alter_column" not in text
    assert "NOT NULL" not in text.upper() or "nullable=True" in text


def test_migration_documents_adr_038_freshness_alignment():
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "adr-038" in text
    assert "computed_at" in text
    assert "gold.kpi_envelopes" in text or "goldkpienvelope" in text


def test_migration_satisfies_additive_gate():
    """The migration additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_action_cards_still_has_exactly_one_alembic_head():
    """Alembic revision chain has one head — this migration does not branch it.

    Asserts the actual invariant the name promises (single-headedness), not a
    pinned literal head id: later slices stack on top of 026 (e.g.
    027_decision_emission_budget, #716 B-4; 028_demo_execution_records, #717
    B-5; 029_close_public_schema_defaults, #897), so a literal-equality
    assertion here breaks on every subsequent migration for a reason unrelated
    to this file. Instead confirm 026 is still an ancestor of whatever head is
    current — the property this migration actually cares about not breaking.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    ancestry = {rev.revision for rev in script.walk_revisions(base="base", head="head")}
    assert "026_action_cards_computed_at" in ancestry

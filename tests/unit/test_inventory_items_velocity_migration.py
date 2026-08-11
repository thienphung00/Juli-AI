"""Contract tests for the inventory_items.velocity landing migration (#943 follow-on)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/031_inventory_items_velocity.py"
)


def test_inventory_items_velocity_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_inventory_items_velocity_migration_is_stacked_on_latest_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "031_inventory_items_velocity"' in text
    assert 'down_revision: str | None = "030_product_revenue_units_sold"' in text


def test_inventory_items_velocity_column_matches_model():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '"inventory_items"' in text
    assert '"velocity"' in text
    assert "sa.String(20)" in text
    assert "nullable=False" in text
    assert "server_default=sa.text(\"'low'\")" in text


def test_inventory_items_velocity_migration_is_additive_only_no_drops_in_upgrade():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "op.drop_table" not in upgrade_body
    assert "op.drop_column" not in upgrade_body
    assert "op.alter_column" not in upgrade_body


def test_inventory_items_velocity_migration_passes_additive_gate():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, [f.render() for f in result.findings]


def test_inventory_items_velocity_keeps_a_single_alembic_head():
    """Guards the single-head invariant, without pinning the head id.

    The previous version's own docstring said "the literal head id advances as later
    slices stack on top of 031" and then asserted that literal anyway, so it failed
    the moment 032_close_public_schema_defaults landed — for a reason unrelated to
    this migration. Assert what the test is actually for: one head, and this
    revision still reachable from it.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"migration graph has branched: {sorted(heads)}"

    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "031_inventory_items_velocity" in ancestry

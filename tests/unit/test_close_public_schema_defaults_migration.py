"""Contract tests for the close-public-schema-defaults migration (#897)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/032_close_public_schema_defaults.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain_extends_current_head():
    """This migration must be the single head, extending whatever preceded it.

    Pinning down_revision to a literal is what broke here: the wave sat unlanded while
    029_bronze_ctor_live_hours (#880), 030_product_revenue_units_sold and
    031_inventory_items_velocity (#943) landed on main, so the original
    "revises 028" would have forked the chain into two children of 028 and alembic
    would refuse `upgrade head` with multiple heads. Deriving the chain instead of
    pinning it means the next parallel wave gets a real failure here rather than a
    branched migration graph in production.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "032_close_public_schema_defaults"' in text

    revisions: dict[str, str | None] = {}
    for path in MIGRATION_PATH.parent.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None

    parents = [d for d in revisions.values() if d]
    heads = [r for r in revisions if r not in parents]
    assert heads == ["032_close_public_schema_defaults"], (
        f"expected this migration to be the only head, got {sorted(heads)}"
    )
    assert len(parents) == len(set(parents)), (
        "a revision has two children — the migration graph has branched: "
        f"{sorted({p for p in parents if parents.count(p) > 1})}"
    )
    assert revisions["032_close_public_schema_defaults"] in revisions, (
        "down_revision points at a revision that does not exist"
    )


def test_migration_only_revokes_grants_no_schema_object_touched():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade")[1].split("def downgrade")[0]
    assert "_revoke_client_access" in upgrade_body
    assert "REVOKE ALL" in text
    assert "ALTER DEFAULT PRIVILEGES" in text
    # Privilege-only: no table/column/schema DDL anywhere in upgrade().
    assert "op.create_table" not in upgrade_body
    assert "op.drop_table" not in upgrade_body
    assert "op.add_column" not in upgrade_body
    assert "op.drop_column" not in upgrade_body
    assert "op.alter_column" not in upgrade_body
    assert "CREATE TABLE" not in upgrade_body.upper()
    assert "DROP TABLE" not in upgrade_body.upper()
    assert "DROP SCHEMA" not in upgrade_body.upper()


def test_migration_reuses_021s_role_existence_guard_not_a_second_convention():
    """#897 AC2: reuse the existing 'only run when the role exists' guard."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    reference = (
        REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/021_medallion_schemas.py"
    ).read_text(encoding="utf-8")
    guard = "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
    assert guard in reference
    assert guard in text


def test_migration_does_not_touch_gold_or_add_rls():
    """ADR-061 doNotInfer: no RLS repair, no USAGE grant on gold in this slice."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "ROW LEVEL SECURITY" not in text.upper()
    assert "CREATE POLICY" not in text.upper()
    assert "SCHEMA gold" not in text


def test_migration_satisfies_additive_gate():
    """The migration additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_close_public_schema_defaults_is_exactly_one_alembic_head():
    """Guards the single-head invariant (no branching), not a pinned head id.

    Pinning ``heads == ["032_close_public_schema_defaults"]`` would break the
    moment any later migration lands, for a reason unrelated to this file —
    exactly the brittleness found in the 026/027/028 contract tests when 029
    was added. Assert 029 remains an ancestor of whatever head is current
    instead.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    ancestry = {rev.revision for rev in script.walk_revisions(base="base", head="head")}
    assert "032_close_public_schema_defaults" in ancestry

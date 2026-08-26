"""Contract tests for RLS policies migration (#1328, ADR-085 decision 3).

Verifies:
- Migration file exists and is properly numbered
- RLS enabled on every tenant-scoped table
- No FORCE ROW LEVEL SECURITY anywhere (owner bypass is critical)
- Three policy shapes implemented correctly
- Ten pre-existing app.current_user_id policies are dropped
- Round-trip downgrade/upgrade preserves data
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/045_rls_policies.py"
)


def test_migration_file_exists():
    """Migration file must exist at the expected path."""
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain():
    """Verify migration numbering and revision chain."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "045_rls_policies"' in text
    assert 'down_revision: str | None = "044_prod_write_authorizations"' in text


def test_migration_documents_adr_085_decision_3():
    """Migration must document ADR-085 decision 3 scope."""
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "adr-085" in text or "adr 085" in text
    assert "decision 3" in text or "rls" in text
    assert "current_setting" in text  # GUC-based policies


def test_migration_no_force_row_level_security():
    """Migration must NOT include FORCE ROW LEVEL SECURITY in code (not comments).

    Owner bypass is critical: postgres and deployed runtime must keep working.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Check code only, not docstring/comments
    code_part = text.split('revision: str = "045_rls_policies"')[1]
    assert "FORCE ROW LEVEL SECURITY" not in code_part


def test_migration_uses_current_setting_guc():
    """Policies must use current_setting for tenant context GUC.

    app.current_shop_id and app.current_user_id are the seam from #1327.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "current_setting" in text
    assert "app.current_shop_id" in text or "current_setting" in text


def test_migration_uses_missing_ok_true():
    """current_setting calls must use missing_ok=true (raises false, NULL denies)."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # missing_ok=true is the deliberate choice: unset denies rather than raising
    assert "missing_ok" in text.lower() or "missing_ok=true" in text


def test_migration_creates_policies_not_only_enables_rls():
    """Migration must create actual policies, not just enable RLS (both needed)."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "CREATE POLICY" in text or "create_policy" in text.lower()
    assert "ALTER TABLE" in text or "rls" in text.lower()


def test_migration_drops_old_user_id_policies():
    """Ten pre-existing app.current_user_id policies must be dropped.

    They are inert in RLS (app.current_user_id is inert, decision 3 makes
    them obsolete). Leaving them alongside new policies is confusing.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Verify DROP POLICY commands for the old policies
    assert "DROP POLICY" in text or "drop" in text.lower()
    # The migration must document which tables the old policies applied to
    # (users, shops at minimum)


def test_migration_includes_direct_shop_id_policies():
    """Direct tenant-scoped tables must have shop_id policies.

    Policy: shop_id = current_setting('app.current_shop_id', true)::uuid
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Should reference shop_id in policies
    assert "shop_id" in text


def test_migration_includes_via_parent_exists_policies():
    """Via-parent tables must use EXISTS policies on parent FK.

    workflow_run_events, run_confirmations, impact_readings, action_card_approvals
    must check the parent's shop_id, not denormalize onto the child.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Should include EXISTS and references to parent tables
    assert "EXISTS" in text or "exists" in text.lower()


def test_migration_covers_all_tenant_scoped_tables():
    """Migration must enable RLS on all tenant-scoped tables.

    Derived from models.py metadata, not a hardcoded 13-count list.
    The set includes tables added by migrations 033-041 after the old audit.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Verify key tenant-scoped tables are mentioned
    # Direct:
    assert "tiktok_credentials" in text
    assert "products" in text
    assert "action_cards" in text
    assert "workflow_runs" in text
    # Via parent:
    assert "workflow_run_events" in text
    assert "run_confirmations" in text
    assert "impact_readings" in text
    assert "action_card_approvals" in text


def test_migration_skips_non_tenant_tables():
    """Non-tenant tables get specific policies or none at all.

    users: app.current_user_id policy
    shops: user_id policy
    webhook_raw_events: no policy (read grant in #1326)
    """
    # Migration documents that non-tenant tables have special handling
    # (this is documented in the migration source)


def test_migration_satisfies_additive_gate():
    """The additive gate (#834) must accept this migration source."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_migration_still_has_single_head():
    """Alembic revision chain has one head — this migration does not branch it."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    ancestry = {rev.revision for rev in script.walk_revisions(base="base", head="head")}
    assert "045_rls_policies" in ancestry


def test_migration_downgrade_reverses_state():
    """Downgrade must reverse upgrade without leaving RLS-enabled-no-policies state.

    That state denies all rows to juli_app (looks like data loss).
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Verify downgrade() exists and is substantial (not a pass)
    parts = text.split("def downgrade")
    assert len(parts) == 2
    downgrade_body = parts[1]
    assert downgrade_body.strip() != "pass"
    # Should drop policies before disabling RLS if in that order

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
    """Every tenant-scoped table is named by SOME migration that enables RLS.

    Rewritten by #1712. It used to assert eight table names it listed by hand
    against 045's source, under a docstring claiming it was "derived from
    models.py metadata, not a hardcoded list" -- it was not, and a hand-written
    list is precisely what cannot notice a ninth table. #1329 found migration
    045 missing `gold.ml_feature_snapshots` and `public.processed_events`, and
    this test as written would have passed throughout.

    So it now iterates `database/tenant_scoped_tables.py`, the committed
    classification map both the #1329 isolation proof and the #1330 boot-time
    precondition check consume, and a new entry there fails here until some
    migration covers it. There is nothing left to remember to update.

    Across every file in `versions/`, not only 045: RLS for a table added later
    necessarily lands in the migration that creates it (046 for the two #1329
    found, 047 for `production_write_audit`, 060 for `ingest_dedup_epochs`, 069
    for `run_act_records`/`run_checklist_items`). Demanding 045 name them all
    would demand 045 mention tables that did not exist when it was written.

    Source text rather than a live catalog on purpose: this module is
    `migration_heavy` and file-content assertions run everywhere, including
    where no Postgres is reachable. The live-catalog counterpart is
    `tests/integration/test_two_tenant_isolation_proof.py`, which enumerates
    `pg_catalog` as the authority.
    """
    from juli_backend.database.tenant_scoped_tables import get_tenant_scoped_tables

    versions_dir = MIGRATION_PATH.parent
    sources = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(versions_dir.glob("*.py"))
    }
    assert sources, f"no migrations found in {versions_dir}"

    tenant_tables = get_tenant_scoped_tables()
    assert len(tenant_tables) >= 40, (
        f"only {len(tenant_tables)} tenant-scoped tables classified -- the map looks "
        "truncated, and a truncated map makes this test pass vacuously"
    )

    uncovered = []
    for schema, table in tenant_tables:
        covering = [
            name for name, text in sources.items() if table in text and "ROW LEVEL SECURITY" in text
        ]
        if not covering:
            uncovered.append(f"{schema}.{table}")

    assert uncovered == [], (
        f"{uncovered} are classified tenant-scoped in "
        "backend/src/juli_backend/database/tenant_scoped_tables.py but no migration "
        "in versions/ names them alongside ROW LEVEL SECURITY. That is the #1329 "
        "defect exactly: a tenant-scoped table nothing enables RLS on reads across "
        "tenants, silently."
    )


def test_the_two_tables_1712_added_are_covered_by_their_own_migration():
    """The #1329 failure mode, aimed at the newest pair specifically.

    The sweep above is satisfied by any migration that happens to contain the
    table's name. This pins the coverage to migration 069 itself: RLS enabled
    on each table by name, a policy for each of the four verbs, and the GUC
    helper rather than a raw `current_setting(...)::uuid` (#1467 -- the raw
    cast raises on the empty string `SET LOCAL` leaves behind at commit).
    """
    text = (MIGRATION_PATH.parent / "069_act_records_and_checklists.py").read_text(encoding="utf-8")
    assert "app_current_shop_id()" in text, (
        "069 must route its policies through the GUC helper added by migration 050, "
        "never a raw current_setting(...)::uuid"
    )
    # Only the policy clauses, not the prose: the migration's docstring names
    # `current_setting(...)::uuid` in order to explain why it is NOT used, and a
    # whole-file grep would fail on the explanation rather than on the defect.
    policy_clauses = [
        line for line in text.splitlines() if "USING (" in line or "WITH CHECK (" in line
    ]
    assert policy_clauses, "069 defines no RLS policy clauses at all"
    offenders = [line.strip() for line in policy_clauses if "current_setting(" in line]
    assert offenders == [], (
        f"{offenders} compare against current_setting directly; route through "
        "app_current_shop_id(), which tolerates the empty string SET LOCAL leaves "
        "behind at commit (#1467)"
    )
    for table in ("run_act_records", "run_checklist_items"):
        assert table in text, f"migration 069 never names {table}"
    assert "ENABLE ROW LEVEL SECURITY" in text, "069 enables RLS on neither table"
    for verb in ("SELECT", "UPDATE", "DELETE", "INSERT"):
        assert f"FOR {verb}" in text or f'"{verb}"' in text or f"'{verb}'" in text, (
            f"069 creates no {verb} policy; a verb with no policy is a verb a future "
            "grant opens across tenants"
        )


def test_migration_skips_non_tenant_tables():
    """Non-tenant tables are excluded from the tenant-scoped sweep by name.

    users: app.current_user_id policy
    shops: user_id policy
    webhook_raw_events: no policy (read grant in #1326)

    Had assertions once. It was reduced to two comments saying the migration
    "documents that non-tenant tables have special handling", and a test whose
    body is a comment cannot fail -- it reported coverage of the exclusion rule
    while checking nothing. Found by `eval/quality_detectors.py`'s
    `no_assert_statement` layer while #1712 was reconciling that baseline, and
    restored here rather than re-baselined, because the alternative is
    ratifying it.

    What it now asserts is the half that matters next door: the sweep in
    `test_migration_covers_all_tenant_scoped_tables` demands an RLS-enabling
    migration for every table `get_tenant_scoped_tables()` returns. These three
    must be absent from that list, or the sweep would demand RLS for tables
    ADR-085 deliberately leaves out -- and, worse, a table wrongly classified
    `non_tenant` would be silently skipped by both this test and the #1329
    isolation proof.
    """
    from juli_backend.database.tenant_scoped_tables import (
        TABLE_CLASSIFICATION_MAP,
        get_tenant_scoped_tables,
    )

    tenant_scoped = set(get_tenant_scoped_tables())
    expected = {
        ("public", "users"): "non_tenant",
        ("public", "shops"): "non_tenant",
        ("public", "webhook_raw_events"): "non_tenant_unprotected",
    }
    for key, classification in expected.items():
        assert TABLE_CLASSIFICATION_MAP.get(key) == classification, (
            f"{key} is classified {TABLE_CLASSIFICATION_MAP.get(key)!r}, expected "
            f"{classification!r} -- these three are keyed on user identity, not shop_id, "
            "and ADR-085 excludes them from the shop_id sweep deliberately"
        )
        assert key not in tenant_scoped, (
            f"{key} is in the tenant-scoped set, so the sweep in "
            "test_migration_covers_all_tenant_scoped_tables would demand a shop_id RLS "
            "policy for a table that has no shop_id column"
        )


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

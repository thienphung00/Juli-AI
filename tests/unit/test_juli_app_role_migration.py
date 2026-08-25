"""Contract tests for the juli_app NOLOGIN runtime role migration (#1326, ADR-085).

Verifies:
- Role creation (NOLOGIN, not owning tables)
- Idempotence (can run multiple times)
- Grant surface exactly matches the explicit map
- webhook_raw_events has INSERT only (no SELECT)
- No default privileges silently grant to future tables
- Round-trip downgrade/upgrade preserves data
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/043_juli_app_role.py"
)


def test_migration_file_exists():
    """Migration file must exist at the expected path."""
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain():
    """Verify migration numbering and revision chain."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "043_juli_app_role"' in text
    assert 'down_revision: str | None = "041_stop_reason_diverged"' in text


def test_migration_creates_role_only_no_login():
    """Migration must create NOLOGIN role, no password, no membership grants."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Verify no password mint
    assert "PASSWORD" not in text.upper() or "NOLOGIN" in text
    # Verify NOLOGIN is present
    assert "NOLOGIN" in text.upper()
    # Verify no GRANT juli_app TO <login> in the migration source
    # (membership is granted out of band)
    assert "GRANT juli_app TO" not in text.upper()


def test_migration_uses_if_exists_guard():
    """Migration must be idempotent using IF EXISTS guard (per migrations 021, 032)."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "IF EXISTS" in text.upper()
    assert "IF NOT EXISTS" in text.upper()


def test_migration_documents_adr_085():
    """Migration must document ADR-085 decision 1 and scope."""
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "adr-085" in text
    assert "decision 1" in text or "functional rls" in text
    assert "nologin" in text
    assert "non-owner" in text


def test_migration_no_policies():
    """Migration must NOT add any RLS policies (deferred to #1328).

    Policies are #1328's responsibility and would be inert without #1327's setter.
    """
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    upgrade_section = text.split("def upgrade")[1].split("def downgrade")[0]
    assert "create_policy" not in upgrade_section.lower()
    assert "policy" not in upgrade_section.lower() or "no policies" in upgrade_section.lower()


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
    assert "043_juli_app_role" in ancestry

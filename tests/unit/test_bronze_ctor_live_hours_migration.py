"""Contract tests for bronze ctor/live_hours landing migration (#880)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/029_bronze_ctor_live_hours.py"
)

BRONZE_TABLES = ("ctor_performance_raw_payloads", "live_hours_raw_payloads")


def test_bronze_ctor_live_hours_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_bronze_ctor_live_hours_migration_is_stacked_on_latest_head():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "029_bronze_ctor_live_hours"' in text
    assert 'down_revision: str | None = "028_demo_execution_records"' in text


def test_bronze_ctor_live_hours_tables_with_shop_scoped_time_index():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    for table in BRONZE_TABLES:
        assert table in text
        assert 'schema="bronze"' in text
    assert "ix_bronze_ctor_performance_raw_payloads_shop_received" in text
    assert "ix_bronze_live_hours_raw_payloads_shop_received" in text
    assert '"shop_id", "received_at"' in text or "'shop_id', 'received_at'" in text


def test_bronze_ctor_live_hours_migration_is_additive_only_no_drops_in_upgrade():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = text.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "op.drop_table" not in upgrade_body
    assert "op.drop_column" not in upgrade_body
    assert "op.alter_column" not in upgrade_body


def test_bronze_ctor_live_hours_migration_passes_additive_gate():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, [f.render() for f in result.findings]

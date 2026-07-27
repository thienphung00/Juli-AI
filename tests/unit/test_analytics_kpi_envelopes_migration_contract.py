"""Contract tests for P2.10-A1 analytics_kpi_envelopes migration (#525)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions"
    / "020_analytics_kpi_envelopes.py"
)

REQUIRED_COLUMNS = (
    "id",
    "shop_id",
    "kind",
    "envelope_version",
    "payload",
    "computed_at",
    "created_at",
    "updated_at",
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_020_analytics_kpi_envelopes",
        MIGRATION_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_020_file_exists() -> None:
    assert MIGRATION_PATH.is_file(), f"missing {MIGRATION_PATH}"


def test_migration_020_analytics_kpi_envelopes_unique_shop_kind_rls() -> None:
    migration = _load_migration_module()
    assert migration.revision == "020_analytics_kpi_envelopes"
    assert migration.down_revision == "019_backfill_partitions"

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "analytics_kpi_envelopes" in source
    for name in REQUIRED_COLUMNS:
        assert f'"{name}"' in source
    assert "UNIQUE" in source.upper() or "unique=True" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "analytics_kpi_envelopes_isolation" in source
    assert "app.current_user_id" in source
    assert "JSONB" in source or "postgresql.JSONB" in source

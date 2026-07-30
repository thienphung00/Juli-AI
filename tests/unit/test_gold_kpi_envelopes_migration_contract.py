"""Contract tests for A0 gold.kpi_envelopes migration (#606)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions"
    / "024_gold_kpi_envelopes.py"
)

GOLD_REQUIRED_COLUMNS = (
    "shop_id",
    "computed_at",
    "envelope_version",
    "payload",
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_024_gold_kpi_envelopes",
        MIGRATION_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_024_file_exists() -> None:
    assert MIGRATION_PATH.is_file(), f"missing {MIGRATION_PATH}"


def test_migration_024_gold_kpi_envelopes_contract() -> None:
    migration = _load_migration_module()
    assert migration.revision == "024_gold_kpi_envelopes"
    assert migration.down_revision == "023_bronze_orders_returns"

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "kpi_envelopes" in source
    assert "gold" in source
    for name in GOLD_REQUIRED_COLUMNS:
        assert f'"{name}"' in source
    assert "payload" in source and ("JSONB" in source or "JSON" in source)
    assert "analytics_kpi_envelopes_compat" in source
    assert "prevent_analytics_kpi_envelopes_writes" in source or "read-only" in source.lower()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "GIN" in source or "deferred" in source.lower()

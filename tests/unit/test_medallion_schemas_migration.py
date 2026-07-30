"""Contract tests for CDP medallion schema bootstrap migration (#603)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.phase_scaffold

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/021_medallion_schemas.py"
)
MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/database/MODULE.md"

MEDALLION_SCHEMAS = ("bronze", "silver", "gold", "ops")
CLIENT_ISOLATED_SCHEMAS = ("bronze", "silver", "ops")
POSTGREST_CLIENT_ROLES = ("anon", "authenticated")


def test_medallion_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_medallion_migration_creates_four_schemas():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'f"CREATE SCHEMA IF NOT EXISTS {schema}"' in text
    for schema in MEDALLION_SCHEMAS:
        assert schema in text


def test_medallion_migration_revokes_postgrest_roles_from_internal_layers():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'f"REVOKE ALL ON SCHEMA {schema} FROM {role}"' in text
    for schema in CLIENT_ISOLATED_SCHEMAS:
        assert schema in text
    for role in POSTGREST_CLIENT_ROLES:
        assert role in text


def test_medallion_migration_creates_gold_ml_feature_snapshots_stub():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '"ml_feature_snapshots"' in text or "'ml_feature_snapshots'" in text
    assert 'schema="gold"' in text or "schema='gold'" in text


def test_database_module_documents_silver_as_ml_feature_source():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "silver" in text.lower()
    assert "ML" in text or "ml_feature_snapshots" in text
    assert "feature" in text.lower() or "SoT" in text

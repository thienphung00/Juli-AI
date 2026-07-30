"""Contract tests for bronze orders/returns landing migration (#605)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/023_bronze_orders_returns.py"
)

BRONZE_TABLES = ("order_raw_payloads", "return_raw_payloads")


def test_bronze_orders_returns_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_bronze_orders_returns_tables_with_shop_scoped_time_index():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "023_bronze_orders_returns"' in text
    assert 'down_revision: str | None = "022_ops_backfill_partitions"' in text
    for table in BRONZE_TABLES:
        assert table in text
        assert 'schema="bronze"' in text
    assert "ix_bronze_order_raw_payloads_shop_received" in text
    assert "ix_bronze_return_raw_payloads_shop_received" in text
    assert '"shop_id", "received_at"' in text or "'shop_id', 'received_at'" in text


def test_bronze_migration_documents_webhook_raw_events_audit_shim():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "webhook_raw_events" in lowered
    assert "read-only audit shim" in lowered or "read-only audit" in lowered
    assert "bronze" in lowered
    assert "forward write path" in lowered


def test_bronze_migration_documents_no_indefinite_double_write():
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "no indefinite double-write" in text or "no indefinite double write" in text
    assert "webhook_raw_events" in text


def test_bronze_migration_a1_webhook_orchestration_out_of_scope():
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "out of scope" in text
    assert "a1" in text or "webhook enqueue" in text

"""Issue #604 — analytics_backfill_partitions must live under ops.*."""

from pathlib import Path

from juli_backend.models.models import AnalyticsBackfillPartition


def test_analytics_backfill_partition_model_uses_ops_schema() -> None:
    """Repo path: ORM model must target ops.analytics_backfill_partitions only."""
    table = AnalyticsBackfillPartition.__table__
    assert table.schema == "ops"
    assert table.fullname == "ops.analytics_backfill_partitions"


def test_ops_backfill_migration_no_partner_api_calls() -> None:
    """PR-safe lane: migration 022 is schema-only — no Partner API calls."""
    migration = (
        Path(__file__).resolve().parents[2]
        / "backend/src/juli_backend/database/migrations/versions/022_ops_backfill_partitions.py"
    )
    text = migration.read_text(encoding="utf-8").lower()
    assert "tiktok" not in text
    assert "partner" not in text

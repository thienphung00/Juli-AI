"""Contract tests for P2-9-1 analytics interval backfill columns (#463).

Model-level assertions are the PR signal; seeded DB proof lives in
``tests/integration/test_migrations.py`` (``migration_heavy``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from juli_backend.models.models import AnalyticsPerformanceInterval

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions"
    / "018_interval_backfill_cols.py"
)

BACKFILL_COLUMNS = (
    "live_hours",
    "live_sessions",
    "active_products",
    "new_products",
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_018_interval_backfill_cols",
        MIGRATION_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_analytics_performance_interval_model_exposes_backfill_columns() -> None:
    table_columns = AnalyticsPerformanceInterval.__table__.columns
    for name in BACKFILL_COLUMNS:
        assert name in table_columns
        assert table_columns[name].nullable is True


def test_migration_018_revision_chain() -> None:
    migration = _load_migration_module()
    assert migration.revision == "018_interval_backfill_cols"
    assert migration.down_revision == "017_analytics_perf_intervals"

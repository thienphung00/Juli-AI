"""P62-B (D72.2): ``processed_events`` retention -- constants, beat, migration 098 shape.

The behaviour (owner-role purge as ``juli_app``, two shops, batches, SQL floor) is proved on
real Postgres in ``tests/integration/test_p62b_scoped_reads_and_retention_db.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from juli_backend.services.etl.persistence.ingest import retention
from juli_backend.services.onboarding import history

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "098_processed_events_retention.py"
DEFERRED = (
    REPO / "backend/src/juli_backend/database/migrations/deferred/"
    "074_users_placeholder_phone_cleanup.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("mig_098", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retention_window_outlives_every_redelivery_horizon():
    nights_to_full_history = -(
        -(history.HISTORY_TARGET_DAYS - history.DEFAULT_CONNECT_DAYS)
        // (history.DEFAULT_NIGHTLY_CHUNKS * history.DEFAULT_NIGHTLY_CHUNK_DAYS)
    )
    assert nights_to_full_history == 4
    assert retention.PROCESSED_EVENTS_RETENTION_DAYS >= 7 * nights_to_full_history
    mig = _migration()
    assert retention.PROCESSED_EVENTS_RETENTION_DAYS >= mig.MIN_RETENTION_DAYS
    assert 0 < retention.PROCESSED_EVENTS_PURGE_BATCH <= mig.MAX_BATCH


def test_migration_chain_and_definer_shape():
    mig = _migration()
    assert mig.revision == "098_processed_events_retention" and len(mig.revision) <= 32
    assert mig.down_revision == "096_change_attribution"
    body = MIGRATION.read_text("utf-8")
    assert "SECURITY DEFINER" in body and "SET search_path = pg_catalog, public" in body
    assert "REVOKE ALL ON FUNCTION" in body and "TO {APP_ROLE}" in body
    assert "RAISE EXCEPTION" in body  # the floor
    assert 'down_revision: str | None = "098_processed_events_retention"' in DEFERRED.read_text(
        "utf-8"
    )


def test_model_carries_the_age_index():
    from juli_backend.services.etl.persistence.ingest.model import ProcessedEvent

    names = {ix.name for ix in ProcessedEvent.__table__.indexes}
    assert _migration().INDEX_NAME in names


def test_beat_entry_and_task_registration():
    from juli_backend.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["processed-events-retention"]
    assert entry["task"] == "juli_backend.processed_events_retention"
    assert "juli_backend.processed_events_retention" in celery_app.tasks
    assert "juli_backend.processed_events_retention" not in celery_app.conf.task_routes


class _Session:
    def __init__(self, counts: list[int], seen: list[dict]) -> None:
        self._counts, self._seen = counts, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt, params):
        self._seen.append(params)
        count = self._counts.pop(0)

        class _R:
            def scalar_one(self_inner):
                return count

        return _R()

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_purge_loops_in_batches_until_a_short_batch():
    seen: list[dict] = []
    counts = [3, 3, 1, 99]
    result = await retention.purge_processed_events(
        lambda: _Session(counts, seen), batch_size=3, max_batches=10
    )
    assert (result.deleted, result.batches, result.exhausted) == (7, 3, True)
    assert seen[0] == {"days": retention.PROCESSED_EVENTS_RETENTION_DAYS, "batch": 3}


@pytest.mark.asyncio
async def test_purge_stops_at_the_nightly_cap():
    seen: list[dict] = []
    result = await retention.purge_processed_events(
        lambda: _Session([2] * 10, seen), batch_size=2, max_batches=3
    )
    assert (result.deleted, result.batches, result.exhausted) == (6, 3, False)

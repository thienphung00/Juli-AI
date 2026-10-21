"""``processed_events`` retention: a batched owner-role purge function (fast track P62-B, D72.2).

``processed_events`` is the ETL ingest idempotency ledger (#32, epoch since #1968,
migration 060). It was a permanent, unbounded ledger and is now the largest table
(64 MB, D72 evidence), copied by every ``pg_dump``. D72.2 bounds it: rows older than
``services/etl/persistence/ingest/retention.py::PROCESSED_EVENTS_RETENTION_DAYS`` are
deleted by the nightly ``processed_events_retention`` beat.

Migration 060 refused DELETE as a *recovery* mechanism (an epoch advance is additive and
auditable). Retention is a different thing: a ledger row only has to outlive the window in
which the same ``(event_id, epoch)`` can be presented again. Past it, a re-presented event
is a no-op anyway -- every silver upsert refuses an ``update_time`` at or before the stored
one (``ShopScopedRepo._apply_if_newer``) -- so dropping the row costs at most one redundant
read-compare, never a duplicate or a rollback of data.

WHY A ``SECURITY DEFINER`` FUNCTION (ADR-089 shape, like 051 / 096).

``juli_app`` holds SELECT / INSERT / UPDATE on the ledger (043, 046) and no DELETE, and the
table is RLS'd on ``shop_id``, so a runtime-role DELETE sees one tenant at a time. The
purge is a fleet job. ``purge_processed_events(retention_days, batch_size)`` runs as the
migration role (the table owner), deletes ONE batch of the oldest expired rows and returns
how many it deleted; the caller loops and commits per batch. It stays narrow:

  1. **A floor in SQL.** ``retention_days`` below ``MIN_RETENTION_DAYS`` raises, so no
     caller -- a bug, a bad env value -- can turn the purge into a ledger wipe.
  2. **Bounded work.** ``batch_size`` is clamped to ``[1, MAX_BATCH]``.
  3. **No dynamic SQL, pinned ``search_path``, EXECUTE revoked from PUBLIC and granted to
     ``juli_app`` only** (051's reasoning, verbatim).

An index on ``processed_at`` keeps each batch an index range scan instead of a sequential
scan of the whole ledger.

REVERSIBLE. ``downgrade`` drops the function and the index. Rows already purged stay purged.

The deferred phone-cleanup step is re-parented onto this revision so it stays the tail.
Chained after P61-B's 097.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "098_processed_events_retention"
down_revision: str | None = "097_production_write_shops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
FUNCTION_SIGNATURE = "purge_processed_events(integer, integer)"
INDEX_NAME = "ix_processed_events_processed_at"
#: The SQL floor. Written out rather than imported (a migration must not change when the
#: service does); ``tests/unit/test_processed_events_retention.py`` pins the service's
#: ``PROCESSED_EVENTS_RETENTION_DAYS`` at or above it and its batch size at or below MAX_BATCH.
MIN_RETENTION_DAYS = 14
MAX_BATCH = 50_000


def upgrade() -> None:
    op.create_index(INDEX_NAME, "processed_events", ["processed_at"])
    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.purge_processed_events(
        retention_days integer,
        batch_size integer
    )
    RETURNS integer
      LANGUAGE plpgsql
      VOLATILE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
      DECLARE
        deleted integer;
      BEGIN
        IF retention_days IS NULL OR retention_days < {MIN_RETENTION_DAYS} THEN
          RAISE EXCEPTION 'processed_events retention must be at least {MIN_RETENTION_DAYS} days'
            USING ERRCODE = '22023';
        END IF;
        WITH doomed AS (
          SELECT p.event_id, p.epoch
            FROM public.processed_events AS p
           WHERE p.processed_at < (now() AT TIME ZONE 'UTC') - make_interval(days => retention_days)
           ORDER BY p.processed_at
           LIMIT greatest(1, least(coalesce(batch_size, 1), {MAX_BATCH}))
        )
        DELETE FROM public.processed_events AS t
         USING doomed
         WHERE t.event_id = doomed.event_id AND t.epoch = doomed.epoch;
        GET DIAGNOSTICS deleted = ROW_COUNT;
        RETURN deleted;
      END
      $fn$;
    """)
    # nosec B608: the signature and role are module constants, never request input.
    op.execute(f"REVOKE ALL ON FUNCTION public.{FUNCTION_SIGNATURE} FROM PUBLIC;")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.{FUNCTION_SIGNATURE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION_SIGNATURE};")  # nosec B608
    op.drop_index(INDEX_NAME, table_name="processed_events")

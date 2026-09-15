"""`juli_app` must hold SELECT on `webhook_raw_events`, or every insert raises (#1966).

`DatabaseRawWebhookEventRecorder.record` (services/tiktok/webhook_raw_log.py) calls
`WebhookRawEventsRepo.insert`, which goes through `SessionRepo._add`:

    self._session.add(entity)
    await self._session.flush()

`WebhookRawEvent.received_at` carries `server_default=func.now()` (models/models.py),
a server-generated column the ORM must read back to populate the in-memory object
after INSERT. SQLAlchemy's asyncpg dialect does that with `INSERT ... RETURNING
received_at`, and `RETURNING` needs SELECT on every column it returns -- not just
INSERT on the table. Migration 043 granted `juli_app` INSERT only on this table
(ADR-085 decision 3: "no tenant lineage, no read grant"), so every webhook delivery's
audit-log write raised

    asyncpg.exceptions.InsufficientPrivilegeError: permission denied for table webhook_raw_events

measured in production over 24h as 310 `webhook_raw_log_failed` log lines (173
order_status_change, 77 inventory_changed, 47 product_audit_status_change, plus
others) -- and because the recorder's failure is swallowed by
`TikTokWebhookService._safe_record`, every one of those deliveries still returned
HTTP 200, so TikTok never retried. Unretryable data loss.

WHY THIS RUNS AS `juli_app` AND NOT AS THE OWNER. A missing GRANT is invisible to
the table owner -- Postgres never checks table privileges for it, so the same
INSERT that raises in production would flush cleanly on an owner connection. Every
prior unit test of this recorder ran on SQLite or as the owner, which is exactly
why a dead production write path shipped with a green suite.

WHY A BARE INSERT WOULD PROVE NOTHING. `INSERT INTO webhook_raw_events (...) VALUES
(...)` with no `RETURNING` clause needs only INSERT and would pass under the
pre-migration grant, silently validating nothing. This test goes through the real
repository method so the real `RETURNING` is on the wire.

RED before migration 059 with `permission denied for table webhook_raw_events`;
GREEN after it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from juli_backend.repositories.workflow import WebhookRawEventsRepo
from tests.support.postgres import juli_app_async_sessionmaker, owner_sync_engine, requires_postgres

_READ_BACK = text(
    "SELECT tiktok_shop_id, event_type, http_status, processing_status, received_at "
    "FROM public.webhook_raw_events WHERE id = :id"
)


@pytest.fixture
def owner_engine():
    """A sync engine as the table owner, for reading back the inserted row.

    `tests/conftest.py::_shared_database_at_head` has already migrated the shared
    database to head before this test runs.
    """
    with owner_sync_engine() as engine:
        yield engine


async def _insert_as_juli_app():
    """Run the real repository method on a real `juli_app` session, and commit.

    The commit is load-bearing: a flush alone would not distinguish "the insert
    landed" from "nothing has happened yet" on read-back.
    """
    async with juli_app_async_sessionmaker() as sessionmaker:
        async with sessionmaker() as session:
            repo = WebhookRawEventsRepo(session)
            row = await repo.insert(
                tiktok_shop_id="7495990420104333542",
                event_type="order_status_change",
                event_id="evt-1966-select-grant",
                signature_header="sha256=deadbeef",
                headers=None,
                raw_body='{"type":"order_status_change"}',
                http_status=200,
                processing_status="dispatched",
            )
            await session.commit()
            return row.id


@requires_postgres
async def test_webhook_raw_event_insert_lands_as_juli_app(owner_engine):
    """The acceptance criterion: the audit row exists after a `juli_app` insert.

    RED before migration 059 with `permission denied for table
    webhook_raw_events` (the ORM's flush issues `INSERT ... RETURNING
    received_at`, which needs SELECT); GREEN after it.
    """
    row_id = await _insert_as_juli_app()

    with owner_engine.connect() as conn:
        row = conn.execute(_READ_BACK, {"id": str(row_id)}).one()

    assert row.tiktok_shop_id == "7495990420104333542"
    assert row.event_type == "order_status_change"
    assert row.http_status == 200
    assert row.processing_status == "dispatched"
    assert row.received_at is not None, (
        "received_at is server-generated -- its presence proves the RETURNING "
        "round-trip actually completed, not merely that the INSERT was staged"
    )

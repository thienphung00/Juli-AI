"""`tiktok_sync_state` records the last outcome per endpoint (#1950 criterion 4).

Before this, the only evidence a poll endpoint had ever worked was the presence
of a cursor row, and that proxy is worthless in both directions:

- #1948: Search Inventory failed on 100% of calls for the lifetime of the
  table. No `inventory` row was ever written, which looks exactly like a shop
  with nothing to sync. "Has this ever succeeded?" was not a question this
  database could answer.
- #1949: `orders` had a row, a freshly advanced `last_update_time` and a
  healthy `updated_at`, over 3,581 rows that never landed.

`last_success_at IS NULL` is the first question in SQL. The rest of the columns
are the last verdict, written where a Celery worker's log formatter cannot drop
them -- every field `poll_step_outcome` carries travels in `logger.extra`,
which only `configure_logging` renders, which `workers/celery_app.py` has never
called (#1978).

WHAT THE SQLITE FIXTURE PROVES AND WHAT IT DOES NOT. The `session` fixture is
in-memory SQLite built from `Base.metadata`, not from the Alembic chain. So the
tests below prove the repository's behaviour against the ORM model, and prove
NOTHING about the Postgres schema the migration produces, about RLS, or about
the `juli_app` grant. `TestTheMigrationMatchesTheModel` closes the first of
those statically -- the migration's column list and the model's must agree --
and names the other two as out of this fixture's reach rather than implying
they were checked.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from juli_backend.models.models import TikTokSyncState
from juli_backend.repositories.tiktok_credentials import (
    OUTCOME_DROPPED,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    TikTokSyncStateRepo,
)
from juli_backend.workers.services.polling.sync import SyncOutcome
from tests.support.builders import make_shop, make_user

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_ROOT = REPO_ROOT / "backend/src/juli_backend/database/migrations"
MIGRATION_PATH = MIGRATIONS_ROOT / "versions/067_tiktok_sync_state_last_outcome.py"
GRANT_MIGRATION_PATH = MIGRATIONS_ROOT / "versions/055_juli_app_sync_state_update.py"

OUTCOME_COLUMN_NAMES = (
    "last_outcome",
    "last_outcome_at",
    "last_fetched",
    "last_persisted",
    "last_error",
    "last_success_at",
)


def _outcome(resource: str, **fields: Any) -> SyncOutcome:
    return SyncOutcome(resource=resource, shop_id="7494001234567890123", **fields)


async def _rows(session, shop_id: uuid.UUID) -> dict[str, TikTokSyncState]:
    result = await session.execute(
        sa.select(TikTokSyncState).where(TikTokSyncState.shop_id == shop_id)
    )
    return {row.endpoint: row for row in result.scalars().all()}


@pytest.fixture
async def shop_id(session):
    user = await make_user(session)
    shop = await make_shop(session, user)
    return shop.id


class TestNeverSucceededIsQueryable:
    async def test_a_failed_endpoint_with_no_cursor_still_gets_a_row(self, session, shop_id):
        """The #1948 case, in one assertion.

        `save` writes nothing for an endpoint with no cursor -- it iterates the
        cursors present in `sync_state`, and a step that never persisted a row
        contributes none. So the row had to be INSERTED here, by the outcome
        write, or "never succeeded" stays indistinguishable from "no row yet".
        """
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("inventory", error="TikTokAPIError(11005)")])

        rows = await _rows(session, shop_id)
        assert "inventory" in rows, "a 100%-failing endpoint left no row to find it by"
        assert rows["inventory"].last_outcome == OUTCOME_FAILED
        assert rows["inventory"].last_success_at is None
        assert rows["inventory"].last_error

    async def test_a_dropped_everything_step_is_recorded_as_dropped_not_failed(
        self, session, shop_id
    ):
        """The #1949 case. The two failure modes are different questions."""
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(
            shop_id, [_outcome("orders", fetched=3581, persisted=0, failed=3581)]
        )

        row = (await _rows(session, shop_id))["orders"]
        assert row.last_outcome == OUTCOME_DROPPED
        assert row.last_fetched == 3581
        assert row.last_persisted == 0
        assert row.last_success_at is None

    async def test_a_successful_step_stamps_last_success_at(self, session, shop_id):
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("orders", fetched=12, persisted=12)])

        row = (await _rows(session, shop_id))["orders"]
        assert row.last_outcome == OUTCOME_OK
        assert row.last_success_at is not None
        assert row.last_error is None

    async def test_last_success_at_survives_a_later_failure(self, session, shop_id):
        """ "Did this EVER work" must not be erased by the next thing that breaks.

        Without this the column would answer "did the last run succeed", which
        is the question `last_outcome` already answers.
        """
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("orders", fetched=1, persisted=1)])
        first_success = (await _rows(session, shop_id))["orders"].last_success_at
        assert first_success is not None

        await repo.record_outcomes(shop_id, [_outcome("orders", error="boom")])

        row = (await _rows(session, shop_id))["orders"]
        assert row.last_outcome == OUTCOME_FAILED
        assert row.last_success_at == first_success

    async def test_a_rate_limited_step_is_skipped_not_failed(self, session, shop_id):
        """A step the rate limiter turned away has not failed, and has not succeeded."""
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("returns", skipped=True)])

        row = (await _rows(session, shop_id))["returns"]
        assert row.last_outcome == OUTCOME_SKIPPED
        assert row.last_success_at is None

    async def test_the_analytics_verdict_is_recorded_once_not_fanned_out(self, session, shop_id):
        """One step, one verdict row -- NOT one per analytics endpoint.

        This is the second design. Fanning the single `analytics` outcome out
        over the seven analytics endpoints looked like a fair
        over-approximation, and
        `tests/integration/test_fujiwa_polling_sync_state_e2e.py::
        test_repoll_is_idempotent_and_does_not_corrupt_sync_state` showed what
        it actually did: a poll carrying no `promotion_activity_ids` never runs
        A-25, and the fan-out stamped `promotion_activity` with
        `last_outcome='ok'` and a `last_success_at`.

        A recorded success for an endpoint that never executed is the exact
        class of comfortable-looking lie this issue exists to remove, and it
        poisons the one query criterion 4 is for. `sync_analytics` reports at
        step granularity, so that is the granularity recorded; claiming more
        would be invention, not measurement.
        """
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("analytics", fetched=9, persisted=9)])

        rows = await _rows(session, shop_id)
        assert set(rows) == {"analytics"}
        assert rows["analytics"].last_outcome == OUTCOME_OK
        assert rows["analytics"].last_success_at is not None

    async def test_a_cycle_that_never_ran_an_analytics_endpoint_claims_no_success_for_it(
        self, session, shop_id
    ):
        """The regression the integration lane caught, pinned here as a unit test.

        `promotion_activity` (A-25) runs only when `promotion_activity_ids` is
        present in sync_state. A poll without it must leave no trace claiming
        that endpoint succeeded.
        """
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("analytics", fetched=9, persisted=9)])

        rows = await _rows(session, shop_id)
        assert "promotion_activity" not in rows, (
            "a verdict was recorded for an analytics endpoint this cycle never ran"
        )

    async def test_the_analytics_verdict_row_is_not_read_back_as_a_cursor(self, session, shop_id):
        """`load` must ignore it, or the verdict row would look like sync state.

        `_ENDPOINT_STATE_KEYS` has no `analytics` key, so the row is invisible
        to the cursor read the poll cycle starts from.
        """
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("analytics", fetched=9, persisted=9)])

        assert await repo.load(shop_id) == {}

    async def test_recording_does_not_disturb_an_existing_cursor(self, session, shop_id):
        """The verdict is written BESIDE `last_update_time`, never over it.

        Resetting a cursor to 0 as a side effect of recording a failure would
        refetch the shop's whole history on the next cycle.
        """
        repo = TikTokSyncStateRepo(session)
        await repo.save(shop_id, {"orders_last_update_time": 1700000100})
        await repo.record_outcomes(shop_id, [_outcome("orders", error="boom")])

        row = (await _rows(session, shop_id))["orders"]
        assert row.last_update_time == 1700000100
        assert row.last_outcome == OUTCOME_FAILED

    async def test_an_unknown_resource_name_is_ignored_rather_than_guessed(self, session, shop_id):
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("creators", fetched=3, persisted=3)])
        assert await _rows(session, shop_id) == {}

    async def test_a_long_vendor_error_is_truncated_to_the_column_width(self, session, shop_id):
        """The code path that records a failure must not itself fail on one."""
        repo = TikTokSyncStateRepo(session)
        await repo.record_outcomes(shop_id, [_outcome("orders", error="x" * 5000)])

        row = (await _rows(session, shop_id))["orders"]
        assert row.last_error is not None
        assert len(row.last_error) <= 500


# ---------------------------------------------------------------------------
# The migration, checked statically. The `session` fixture is SQLite built from
# `Base.metadata`, so nothing above it reaches the Alembic chain.
# ---------------------------------------------------------------------------


class TestTheMigrationMatchesTheModel:
    def test_the_migration_exists_and_chains_onto_the_head_of_versions(self):
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        assert 'revision: str = "067_sync_state_last_outcome"' in text
        assert 'down_revision: str | None = "065_users_email"' in text

    def test_it_is_the_only_child_of_its_parent(self):
        """A second child of one revision forks the chain.

        The deferred contract step from #1972 was renumbered onto THIS revision
        in the same change for exactly this reason;
        `tests/unit/test_users_phone_placeholder_cleanup.py` is the test that
        enforces it from the other side.
        """
        versions = MIGRATIONS_ROOT / "versions"
        siblings = sorted(
            path.name
            for path in versions.glob("*.py")
            if re.search(r'^down_revision: str \| None = "065_users_email"', path.read_text(), re.M)
        )
        assert siblings == ["067_tiktok_sync_state_last_outcome.py"], siblings

    def test_every_model_column_is_added_by_the_migration(self):
        """The two lists must agree, or SQLite-backed tests pass over a schema
        Postgres does not have."""
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        model_columns = set(TikTokSyncState.__table__.columns.keys())
        for name in OUTCOME_COLUMN_NAMES:
            assert name in model_columns, f"{name} is in the migration but not on the model"
            assert f'"{name}"' in text, f"{name} is on the model but not in the migration"

    def test_the_upgrade_only_adds(self):
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade_body = text.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        assert "op.drop_column" not in upgrade_body
        assert "op.drop_table" not in upgrade_body
        assert "op.alter_column" not in upgrade_body
        assert "op.execute" not in upgrade_body

    def test_every_added_column_is_nullable(self):
        """A `server_default` would manufacture a verdict for rows that predate
        the column -- the comfortable-looking lie this issue removes."""
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        for match in re.finditer(r"sa\.Column\((.*?)\)\,\n", text, re.S):
            assert "nullable=True" in match.group(1)

    def test_the_migration_passes_the_additive_gate(self):
        sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
        from migration_additive_gate import evaluate_migration_paths

        result = evaluate_migration_paths([MIGRATION_PATH])
        assert [finding.render() for finding in result.findings] == []
        assert result.accepted is True
        assert result.inspected == ["067_sync_state_last_outcome"]

    def test_the_existing_update_grant_is_table_level_so_new_columns_are_covered(self):
        """The claim this migration rests on, checked rather than assumed.

        065's grant on `users` is COLUMN-scoped, and a column-scoped grant does
        not cover a column added later -- that mistake cost #1973 an
        `InsufficientPrivilegeError` in the authentication path. 055's grant on
        `tiktok_sync_state` is table-level, so the six new columns need no
        further privilege. If anyone narrows it, this fails instead of
        production.
        """
        text = GRANT_MIGRATION_PATH.read_text(encoding="utf-8")
        assert '"tiktok_sync_state": ("UPDATE",)' in text
        assert "UPDATE (" not in text, "055's grant has become column-scoped; 067 now needs its own"

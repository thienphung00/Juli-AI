"""tiktok_sync_state last-outcome columns -- make "never succeeded" queryable (#1950)

Revision ID: 071_sync_state_last_outcome
Revises: 069_act_records_and_checklists
Create Date: 2026-09-21

WHAT WAS MISSING. `tiktok_sync_state` stored one number per (shop, endpoint):
the incremental cursor. Nothing recorded whether the poll that last touched
that cursor had done anything. So the two questions an operator actually needs
to ask about a sync --

    Has this endpoint EVER succeeded?
    What happened the last time it ran?

-- had no answer in this database. The nearest available proxy was "does a row
exist", and #1948 is the proof that the proxy is worthless: Search Inventory
failed on 100% of calls for the lifetime of the table, and the absence of an
`inventory` row looked exactly like a shop with no inventory to sync. #1949 is
the other direction: `orders` had a row, with a freshly advanced
`last_update_time` and a healthy `updated_at`, over 3,581 fetched rows that
never landed.

`last_success_at IS NULL` is the first question, in SQL. The rest of the
columns are the last verdict.

SIX NULLABLE COLUMNS, NO DEFAULTS, DELIBERATELY. Every row that already exists
predates this revision and has no verdict to report. A `server_default` of
'ok', or of 0, would manufacture the claim that an endpoint succeeded -- which
is the exact class of comfortable-looking lie this issue exists to remove. A
NULL here means "not measured", and that is true.

WHY A COLUMN AND NOT JUST A LOG LINE. #1969 (PR #2009) already emits one
`poll_step_outcome` record per step carrying this triple. In the process where
the poll actually runs it carries nothing: every field travels in
`logger.*(extra={...})`, which only `JsonFormatter` renders, which only
`configure_logging` installs, whose sole caller is `api/main.py` --
`workers/celery_app.py` has never called it (#1978). A Celery operator reads
the event name and none of the numbers. A column does not go through a
formatter, and survives the process that wrote it.

LENGTHS. `last_outcome` is one of four fixed words ('ok', 'skipped',
'dropped', 'failed'); VARCHAR(20) leaves room for a fifth without another
migration. `last_error` is 500: `SyncOutcome.error` is already bounded to 200
characters by `polling/sync.py::_describe`, so the column is twice the
producer's bound rather than a guess, and the repository truncates to the
column width regardless -- the code path that records a poll failure must not
itself fail with `StringDataRightTruncation`.

NO CHECK CONSTRAINT ON `last_outcome`. A CHECK is not additive in the sense
this repo's gate cares about: the previously deployed code, which does not know
this column exists, is unaffected either way -- but a future verdict word would
need a constraint change coordinated with a code deploy, and the value domain
is already pinned by `_outcome_verdict` and its tests. The column is
operator-facing, not a foreign key.

NO INDEX. Nothing queries by outcome in this slice; the rows are read per shop,
and `ix_tiktok_sync_state_shop_endpoint` already serves that. An index with no
query behind it is maintenance cost paid for a guess (065's reasoning, same
conclusion).

ADDITIVE. Six nullable columns with no defaults leave the previously deployed
code -- which never mentions them -- fully compatible with this schema, so a
code rollback during the shared-database window of a release needs no schema
undo. `infra/scripts/migration_additive_gate.py` accepts it;
`tests/unit/test_tiktok_sync_state_outcome_migration.py` pins that.

RLS NEEDS NOTHING NEW. `tiktok_sync_state` carries its tenant policies from
045; they narrow by row (`shop_id`), and this revision adds no row-visibility
surface.

THE GRANT NEEDS NOTHING NEW EITHER, AND THAT IS CHECKED RATHER THAN ASSUMED.
Migration 055 granted `juli_app` **table-level** `UPDATE` on
`public.tiktok_sync_state` -- not column-scoped, unlike 065's grant on `users`.
A table-level UPDATE covers columns added afterwards, so the new writes need no
further privilege. `tests/unit/test_tiktok_sync_state_outcome_migration.py`
asserts 055's `GRANT_MAP` still names no column list, so this claim fails
loudly if that grant is ever narrowed.

CHAIN. Revises `069_act_records_and_checklists`, the head of `versions/`. This
revision was authored as `067` onto `065_users_email`; #1712 (PR #2071) merged
first, so it was rebased and renumbered rather than left as a second child of
065. The deferred contract step from #1972 is renumbered onto THIS revision in
the same change (`deferred/072_users_placeholder_phone_cleanup.py`) -- a
deferred step that keeps an older parent stops being the tail the moment a new
`versions/` revision lands above it, and it then forks the chain when an
operator copies it into a serving release's `versions/`.
`tests/unit/test_users_phone_placeholder_cleanup.py` is the test that says so,
and this is the THIRD time that rule has been rediscovered by hand
(065->066, 066->068, 070->072). It should be a pre-commit mechanism, not a
convention -- see this PR's body and the review artifact.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "071_sync_state_last_outcome"
down_revision: str | None = "069_act_records_and_checklists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "tiktok_sync_state"

#: `(name, type)` for each column, in the order they are added. Declared once so
#: `downgrade` cannot drift from `upgrade` by hand-editing one list.
OUTCOME_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("last_outcome", sa.String(length=20)),
    ("last_outcome_at", sa.DateTime()),
    ("last_fetched", sa.Integer()),
    ("last_persisted", sa.Integer()),
    ("last_error", sa.String(length=500)),
    ("last_success_at", sa.DateTime()),
)


def upgrade() -> None:
    """Add the six nullable verdict columns. No data is read or written."""
    for name, column_type in OUTCOME_COLUMNS:
        op.add_column(
            TABLE_NAME,
            sa.Column(name, column_type, nullable=True, server_default=None),
        )


def downgrade() -> None:
    """Drop the verdict columns.

    Destructive by nature -- it discards the only durable record of which poll
    endpoints have ever worked. Migrations here are schema-only and are never
    automatically reverted (ADR-027); this exists to complete the Alembic
    contract, not as an operational step. Dropped in reverse order purely so the
    two functions read as mirrors.
    """
    for name, _ in reversed(OUTCOME_COLUMNS):
        op.drop_column(TABLE_NAME, name)

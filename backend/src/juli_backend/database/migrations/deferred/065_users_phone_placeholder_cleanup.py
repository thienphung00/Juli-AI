"""CONTRACT step for #1972: null out the phone numbers Juli fabricated

Revision ID: 065_users_phone_placeholder_cleanup
Revises: 064_users_phone_nullable
Create Date: 2026-09-20

**This file is deliberately NOT in ``versions/``. Do not move it there until it
has been applied to production.** Read the next three sections before touching
it.

Why it is parked here
---------------------
``064_users_phone_nullable`` made ``users.phone`` nullable and the code stopped
fabricating, so no NEW row carries an invented number. The rows written before
that release still do, and clearing them is an ``UPDATE``.
``infra/scripts/migration_additive_gate.py`` refuses a data-moving migration
from an automatic release, by design and with no allowlist: during a release
the candidate and the still-serving stable instance share one database, and
only additive change keeps a code rollback possible. Putting this revision in
``versions/`` would make it pending on every release, the gate would refuse,
``deploy_lane_api`` would return before any candidate started, and nothing
would deploy at all -- the deadlock #2050 spent a week in.

``tests/unit/test_users_phone_placeholder_cleanup.py`` asserts that the gate
REFUSES this file -- and that nothing in ``versions/`` revises its parent,
which would fork the chain the moment this file is copied into a serving
release. That refusal is
the correct verdict and this step's signature; a version of it the gate
accepted would have stopped moving data, which is its entire purpose.

The predicate, and why it cannot match a real number
----------------------------------------------------
A row is cleared only when its stored phone is *byte-for-byte equal* to the
value the removed code would have derived **from that row's own id**::

    f"+849{user_id.int % 10_000_000_000:010d}"

That is the exact expression deleted from ``UsersRepo._provision_first_sighting``
and from ``services/tiktok/business_account_holder_store.py`` -- the only two
places that ever produced one -- reproduced here rather than approximated by a
``LIKE '+849%'`` prefix. The difference matters: ``+849`` is the prefix of every
Viettel/Vinaphone/Mobifone mobile in Vietnam, so a prefix match would delete
real numbers the moment a seller supplies one. Matching the derivation deletes
only values this codebase is known to have written.

Two independent reasons the predicate cannot take a real number with it:

1. **It is a per-row identity, not a pattern.** The comparison value is a pure
   function of that row's primary key. For a stored number to match by accident
   it would have to equal the ten-digit residue of its own owner's UUID -- one
   chance in 10^10 per row, and only for a row that has a number at all.
2. **The shape is not dialable.** ``"+849" + 10 digits`` is 13 digits after the
   ``+``. A Vietnamese mobile in E.164 is ``+84`` followed by nine digits: 11
   digits after the ``+``, e.g. ``+84901234567``. Every fabricated value is two
   digits too long to be a Vietnamese number at all. (The issue described it as
   "well-formed"; it is not, quite -- but it is well-formed *enough* that a
   human reading a CSV, or any system that dials a prefix, treats it as
   contactable, which is the harm.)

Rows this step deliberately leaves alone
----------------------------------------
``services/tiktok/oauth.py`` and ``app_review_store.py`` write
``+849000000001``, and ``advertiser_oauth_store.py`` writes ``+849000000002``.
Those are fixed sentinels for internal TikTok app-review and advertiser
accounts, not per-seller fabrications, and they do not match the derivation
(twelve digits after the ``+``, and not a function of any id). They are out of
#1972's scope -- which is about numbers minted per seller from a seller's own
identifier -- and clearing them would change what those internal accounts mean
without anyone having asked.

How it is operated
------------------
``docs/runbooks/backend-deploy-runbook.md`` section "Separately-operated
contract migrations" holds the procedure and the preconditions. In outline, on
the VPS, against the release directory that is *currently serving*:

1. Confirm the serving release contains ``064_users_phone_nullable`` (and so
   the code that stopped fabricating) and that ``alembic current`` reports
   ``064_users_phone_nullable`` or later. If it reports anything earlier,
   STOP: an older release would immediately mint fresh placeholders behind
   this cleanup.

   **Check the revision number before you run this.** #1973's follow-up PR
   adds ``065_users_email`` to ``versions/`` and renumbers this file to
   ``066_users_placeholder_phone_cleanup``, chained onto it, so that the
   deferred step stays the tail of the chain. Whichever of the two is on
   ``main`` when you run it is the correct one; they differ only in
   ``revision``/``down_revision`` and do exactly the same thing to the same
   rows. Running the older copy against a database already at
   ``065_users_email`` would stamp a revision Alembic cannot place.
2. Take the backup (``infra/scripts/safe-alembic-upgrade.sh`` does this).
3. Copy this file into that release's ``versions/`` directory and LEAVE IT
   THERE -- removing it afterwards would leave Alembic at a revision with no
   file on disk.
4. ``alembic upgrade head``.
5. Land a follow-up PR moving this file from ``deferred/`` into ``versions/``.
   At that point it is already applied, so it is no longer pending and the gate
   accepts the next release.

Unlike ``063_workflow_subject_contract``, running this LATE is harmless: every
day it waits is a day the fabricated rows sit in a column nothing reads. It is
running it *early* -- before the expand release serves -- that would be
pointless, because the old code would write the placeholders straight back.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "065_users_phone_placeholder_cleanup"
down_revision: str | None = "064_users_phone_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fabricated_phone_for(user_id: uuid.UUID) -> str:
    """Reproduce, exactly, the value the deleted code would have written.

    Kept as a function so the round-trip test can import it and assert that a
    row seeded with a fabricated number is cleared while a row holding a real
    number is not -- rather than the test re-deriving the same expression and
    proving only that it agrees with itself.
    """
    return f"+849{user_id.int % 10_000_000_000:010d}"


def upgrade() -> None:
    """Set `phone` to NULL on every row whose phone was derived from its own id.

    Row-by-row in Python rather than one set-based SQL statement, on purpose.
    The derivation reduces a 128-bit UUID modulo 10^10; expressing that in
    Postgres means hex-slicing `uuid_send(id)` into numeric chunks, and a
    transcription error there would either miss rows or -- far worse -- clear a
    real number. `users` holds a handful of rows on a five-shop trial, so the
    loop costs nothing and the predicate stays the same expression the
    application used, character for character.
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, phone FROM users WHERE phone IS NOT NULL")).fetchall()

    for row in rows:
        user_id = row.id if isinstance(row.id, uuid.UUID) else uuid.UUID(str(row.id))
        if row.phone != _fabricated_phone_for(user_id):
            continue
        bind.execute(
            sa.text("UPDATE users SET phone = NULL WHERE id = :id AND phone = :phone"),
            {"id": str(user_id), "phone": row.phone},
        )


def downgrade() -> None:
    """Re-fabricate the numbers this step removed.

    Deliberately NOT implemented. Reversing this migration means writing
    invented Vietnamese mobile numbers back into a contact column -- the exact
    harm #1972 exists to undo -- and it cannot even be done correctly, because
    a NULL phone after this step is indistinguishable from a seller who simply
    never supplied one. Migrations in this repo are schema-only and are never
    automatically reverted (ADR-027); the recovery path for a data step is the
    backup taken in the procedure above.
    """
    raise NotImplementedError(
        "066 is not reversible: re-deriving a phone number from a user id is "
        "the defect #1972 removed. Restore from the pre-migration backup."
    )

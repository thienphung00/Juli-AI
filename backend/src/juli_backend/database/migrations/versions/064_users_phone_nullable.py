"""users.phone becomes nullable -- stop requiring a number we do not have (#1972)

Revision ID: 064_users_phone_nullable
Revises: 063_workflow_subject_contract
Create Date: 2026-09-20

WHAT THIS UNDOES. ``users.phone`` was ``NOT NULL UNIQUE`` from migration 001,
because the column was the identity field of a phone/OTP login flow -- the
schema that predates Google sign-in (``dictionary.md`` still carries
``error.otp_incorrect``). When Google sign-in was layered on top (#1906),
first-sighting provisioning had nothing to put there, so it INVENTED a value::

    placeholder_phone = f"+849{user_id.int % 10_000_000_000:010d}"

Every Google-signed-in seller therefore carried a ``+849`` number derived from
their own UUID: not theirs, unmarked as synthetic, and holding a UNIQUE slot
that a seller supplying their real number could collide with. The landing page
offers 1:1 support to five trial shops, so the first person to work from this
column would have been messaging strangers.

WHY NULLABLE IS THE FIX AND NOT A DEFAULT. "We do not have this seller's phone
number" is a real state, and a column that cannot express it forces every
writer to lie. There is deliberately no ``server_default``: a default is just a
fabricated value with a different author.

ADDITIVE, AND THEREFORE RELEASE-SAFE. Dropping ``NOT NULL`` *widens* what the
column accepts, so the previously-deployed code -- which always supplied a
phone -- stays valid against this schema for the whole window in which the
candidate and the stable instance share one database, and a code rollback needs
no schema undo. ``infra/scripts/migration_additive_gate.py`` accepts this file;
``tests/unit/test_users_phone_nullable_migration.py`` pins that.

WHAT THIS MIGRATION DOES *NOT* DO. It does not touch the rows that already
carry a fabricated number. That cleanup is an ``UPDATE``, which is data-moving,
which the additive-only gate refuses from an automatic release -- correctly, and
the gate has no allowlist. It ships as a separately-operated contract step under
``migrations/deferred/`` and is run by hand; see
``docs/runbooks/backend-deploy-runbook.md`` section "Separately-operated
contract migrations". Until that step runs, the fabricated rows are still
present but no NEW one is created: ``UsersRepo._provision_first_sighting``
stopped fabricating in the same change as this migration.

THE UNIQUE CONSTRAINT SURVIVES UNCHANGED. ``users_phone_key`` is left exactly
as it was. In Postgres a UNIQUE constraint treats NULLs as distinct, so any
number of phone-less rows coexist under it while two identical real numbers
are still rejected -- which is the property worth keeping.

CHAINS ONTO 063, NOT 062. ``063_workflow_subject_contract`` is the contract
half of #2050's expand/contract split. It was applied to production by hand on
2026-09-20T12:06Z and promoted from ``deferred/`` into ``versions/`` by #2063
-- the step 5 that runbook section prescribes -- so it is the revision
production is actually at and the one Alembic resolves as the tip. This
revision's parent is therefore 063; chaining onto 062 instead would fork the
chain at the revision the database has already passed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "064_users_phone_nullable"
down_revision: str | None = "063_workflow_subject_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen users.phone to allow NULL. No data is read or written."""
    op.alter_column(
        "users",
        "phone",
        existing_type=sa.String(length=20),
        nullable=True,
    )


def downgrade() -> None:
    """Re-narrow the column, refusing rather than failing when it cannot.

    Migrations in this repo are schema-only and are NEVER automatically
    reverted (ADR-027), so this exists to complete the Alembic contract and to
    let the chain-walking tests pass through this revision -- not as an
    operational step.

    IT CANNOT ALWAYS SUCCEED, AND SAYS SO. The moment the expand release serves
    its first new sign-in there is a row with a NULL phone, and `SET NOT NULL`
    is then impossible without inventing a value for it -- which is precisely
    the data #1972 exists to remove. Left as a bare `alter_column`, Postgres
    answers that with

        psycopg2.errors.NotNullViolation: column "phone" of relation "users"
        contains null values

    from inside Alembic, naming neither the reason nor the fix. The explicit
    check below turns that into a sentence an operator can act on, and it is
    the same shape `063_workflow_subject_contract`'s downgrade already uses for
    its own un-revertible case.

    The count is deliberately NOT a "fix it for them" branch. There is no
    correct value to write: after 066's cleanup a NULL phone is
    indistinguishable from a seller who simply never supplied one, so anything
    written here would be a guess presented as a restoration.
    """
    bind = op.get_bind()
    phoneless = bind.execute(sa.text("SELECT count(*) FROM users WHERE phone IS NULL")).scalar_one()
    if phoneless:
        raise RuntimeError(
            f"cannot downgrade 064: {phoneless} users row(s) have no phone, and "
            "restoring NOT NULL would require inventing one for each -- the "
            "fabrication #1972 removed. Those rows are correct as they are; if "
            "this schema really must be reverted, restore from a pre-064 backup "
            "(ADR-027) rather than re-deriving contact data."
        )
    op.alter_column(
        "users",
        "phone",
        existing_type=sa.String(length=20),
        nullable=False,
    )

"""users.email -- keep the verified Google address the JWT already carries (#1973)

Revision ID: 065_users_email
Revises: 064_users_phone_nullable
Create Date: 2026-09-20

WHAT WAS MISSING. After a Google sign-in Juli held a UUID, a fabricated phone
(#1972) and nothing else -- no address, no name, no way to reach a seller,
while the landing page offers 1:1 support to five trial shops. The address was
never unavailable: a Supabase access token minted from a Google sign-in carries
`email`, `email_verified` and the display name, signed and already verified
against the project's JWKS. `apps/demo/src/lib/supabase-auth.ts` decodes that
same token client-side "for display only"; the backend read `sub` and discarded
the rest. This column is where the claim lands.

`display_name` needs no migration -- it has existed since 001 and was simply
never written. `core/security/claims.py` now populates both from the same
verified payload.

NULLABLE, NO DEFAULT. A token without a verified email must leave this column
empty rather than carry a plausible-looking value nobody confirmed -- which is
precisely the mistake #1972 exists to undo, and a `server_default` would be
that mistake with a different author.

NOT UNIQUE, DELIBERATELY. `users.id` is the Supabase `sub`. A seller who
deletes and re-creates their Supabase account returns with a NEW sub and the
SAME address, and a unique index would turn that into an `IntegrityError`
raised inside the authentication path -- a seller locked out of their own
account by a constraint defending an invariant nothing reads yet. Two rows
sharing an address is a support question, not a corruption.

NO INDEX YET, FOR THE SAME REASON. Nothing queries by email in this slice; the
column is written at authentication and read by a human. An index with no
query behind it is maintenance cost paid for a guess.

LENGTH. 320 is RFC 5321's maximum address length (64 local + @ + 255 domain).

ADDITIVE. Adding a nullable column with no default leaves the previously
deployed code -- which never mentions `email` -- fully compatible with this
schema, so a code rollback during the shared-database window of a release needs
no schema undo. `infra/scripts/migration_additive_gate.py` accepts it;
`tests/unit/test_users_email_migration.py` pins that.

RLS NEEDS NOTHING NEW. `users` already carries `users_select_public`,
`users_insert_public` AND `users_update_public` from migration 045, each
`(id = current_setting('app.current_user_id', true)::uuid)`. The policies
narrow by row and this revision adds no row-visibility surface.

THE GRANT DOES NEED SOMETHING NEW, AND IT IS THE RISKY HALF OF THIS FILE.
Migration 043 gave `juli_app` exactly `SELECT, INSERT` on `public.users`, and
058's audit recorded the table as append-only for that reason. #1973's backfill
breaks that: a returning seller whose row predates this column has their
verified email filled in during `get_for_authentication`, and that is an
UPDATE. Unfixed it would have failed exactly the way #1897's incident did --

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for table users

-- raised inside the authentication path, so every returning seller's next
request 500s. `tests/unit/test_juli_app_grants_cover_mutations.py` caught it
before it shipped, which is the whole reason that module exists.

SCOPED AS NARROWLY AS POSTGRES ALLOWS. The grant is COLUMN-LEVEL:

    GRANT UPDATE (email, display_name, updated_at) ON public.users TO juli_app

`juli_app` still cannot UPDATE `id` or `phone` -- so nothing in the application
can overwrite the identity a JWT is matched on, and nothing can write a phone
number back into the column #1972 just emptied. Combined with
`users_update_public`, the reachable set is "these three columns, on the
caller's own row, only". No DELETE is granted; there is still no DELETE
anywhere in the application on any mapped table.

`updated_at` is in the list because SQLAlchemy puts it in the statement, not
because any code assigns it -- see `BACKFILLABLE_COLUMNS` below. Postgres
checks the full column list of an UPDATE, so omitting it denies the whole
statement.

ADDITIVE, INCLUDING THE GRANT. Adding a nullable column with no default leaves
the previously deployed code -- which never mentions `email` -- fully
compatible with this schema, and a GRANT only widens what the previous code is
permitted to do. A code rollback during the shared-database window of a release
needs no schema undo. `infra/scripts/migration_additive_gate.py` accepts the
whole file; `tests/unit/test_users_email_migration.py` pins that.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "065_users_email"
down_revision: str | None = "064_users_phone_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

#: The two columns `UsersRepo._record_first_known_identity` assigns -- plus
#: `updated_at`, which SQLAlchemy writes on every UPDATE whether anyone asked or
#: not, because `User.updated_at` carries `onupdate=func.now()`. The emitted
#: statement is `UPDATE users SET email=..., updated_at=...`, so a grant naming
#: only the first two is denied in full: measured on a freshly migrated database
#: as `asyncpg.exceptions.InsufficientPrivilegeError: permission denied for
#: table users`, from `tests/integration/test_google_identity_provisioning.py`.
#: Postgres checks the whole column list, not the column the caller cared about.
BACKFILLABLE_COLUMNS = ("email", "display_name", "updated_at")


def _apply_column_update_privilege(keyword: str) -> None:
    """GRANT or REVOKE column-level UPDATE, guarded on the role and the table.

    Two guards, for two different absences, copied from 058's
    `_apply_table_privileges`: `pg_roles` covers a database in this cluster
    that has not run 043 (a role is cluster-global, a migration is not), and
    `pg_tables` covers a database migrated only part way. Either way the
    statement is skipped rather than failed, which is what makes this
    idempotent.
    """
    preposition = "TO" if keyword == "GRANT" else "FROM"
    columns = ", ".join(BACKFILLABLE_COLUMNS)
    op.execute(
        f"""
DO $apply_users_column_grant$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}')
     AND EXISTS (
       SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users'
     ) THEN
    EXECUTE '{keyword} UPDATE ({columns}) ON public.users {preposition} {ROLE_NAME}';
  END IF;
END
$apply_users_column_grant$;
"""  # nosec B608 -- role, table and column names are fixed module constants
    )


def upgrade() -> None:
    """Add the nullable email column and the column-scoped UPDATE it needs.

    No data is read or written. The GRANT must be in the SAME revision as the
    column: shipping the column alone would deploy a backfill that raises
    `InsufficientPrivilege` on every returning seller's request.
    """
    op.add_column(
        "users",
        sa.Column("email", sa.String(length=320), nullable=True, server_default=None),
    )
    _apply_column_update_privilege("GRANT")


def downgrade() -> None:
    """Revoke the column grant, then drop the column.

    Destructive by nature -- it discards every address captured since the
    upgrade, and those are not recoverable from this database (Supabase's
    `auth.users` is not Juli's Postgres). Migrations here are schema-only and
    are never automatically reverted (ADR-027); this exists to complete the
    Alembic contract, not as an operational step.

    The REVOKE comes first and names both columns, so 043's `SELECT, INSERT`
    survives and `public.users` returns to exactly the append-only privilege
    set 058's audit recorded.
    """
    _apply_column_update_privilege("REVOKE")
    op.drop_column("users", "email")

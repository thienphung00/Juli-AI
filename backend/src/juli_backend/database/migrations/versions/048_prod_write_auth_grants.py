"""Grant juli_app SELECT and UPDATE on production_write_authorizations (issue #1453).

Migration 044 created `production_write_authorizations` and granted `juli_app` nothing.
Migration 043's grant map could not have covered it — the table did not exist yet — and 044
did not add its own the way 047 later did for `production_write_audit`. Read from production
on 2026-09-01, after W7 deployed:

    production_write_authorizations : (none)
    production_write_audit          : INSERT,SELECT

`resolve_write_capability` reads the table through `ProductionWriteAuthorizationsRepo` on the
RUNTIME session, on the live execution path. Once `DATABASE_URL` is cut over to `juli_app`
(#1339 observation 1), the first production-write attempt fails with `permission denied`.

Observation 1 itself is unaffected: `resolve_write_capability` checks
`is_production_write_enabled()` first and returns the sandbox path before touching this table,
and that flag is fail-closed. The gap only bites when the capability is switched on — which is
observation 3, mid-gate, with a production write armed. That is why it is fixed before the
cutover rather than after.

SELECT and UPDATE, and nothing else:

  - `lookup()`  — SELECT
  - `consume()` — SELECT ... FOR UPDATE, then sets consumed_at and consumed_by_run_id

`issue()` and `revoke()` are operator actions through
`services/operations/production_write_authorizations_cli.py`, which takes `--db-url` as an
argument — the operator supplies an admin URL. Granting the runtime role INSERT or DELETE
would widen it for operations it never performs, against ADR-086 decision 8's DML-only,
least-privilege grant map.

RLS is already enabled on this table with four policies, so the grant does not weaken tenant
isolation: the policies still apply, and a grant without a matching tenant context returns
nothing. That is the split ADR-086 relies on — privileges say *which verbs*, policies say
*which rows*.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "048_prod_write_auth_grants"
down_revision: str | None = "047_prod_write_audit"
branch_labels: str | None = None
depends_on: str | None = None

ROLE_NAME = "juli_app"
TABLE_NAME = "production_write_authorizations"


def upgrade() -> None:
    """Grant the runtime role the two verbs its authorization path needs."""
    # Guarded on the role's existence for the same reason 043 guards CREATE ROLE:
    # roles are cluster-global while migrations are per-database, so a database
    # in the same cluster that has not yet run 043 would fail an unguarded GRANT.
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT SELECT, UPDATE ON {TABLE_NAME} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    """Revoke exactly what upgrade granted.

    `REVOKE SELECT, UPDATE` rather than `REVOKE ALL`: this migration is not the
    source of any other privilege on this table, and a blanket revoke would
    silently drop grants a later migration had added.
    """
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'REVOKE SELECT, UPDATE ON {TABLE_NAME} FROM {ROLE_NAME}';
        END IF;
    END
    $$;
    """)

"""Drop the two legacy FOR ALL isolation policies migration 045 documented but did not (#1455).

`public.shops` and `public.users` each carry five policies: the four safe per-command policies
045 created, plus one `FOR ALL` policy from migration 001 that 045 left in place.

    shops_select_public   SELECT   current_setting('app.current_user_id', true)   safe
    shops_insert_public   INSERT   ...                                            safe
    shops_update_public   UPDATE   ...                                            safe
    shops_delete_public   DELETE   ...                                            safe
    shops_isolation       ALL      current_setting('app.current_user_id')         UNSAFE

The one-argument form of `current_setting` RAISES when the parameter is unset; the
two-argument form returns NULL. Policies for the same command are OR'd, but Postgres still
evaluates the legacy qualifier, so it raises before any short-circuit could help:

    juli_app@prod=> select count(*) from shops;
    ERROR:  unrecognized configuration parameter "app.current_user_id"

Found on 2026-09-01 by connecting as `juli_app` for #1339 observation 1's pre-cutover check.
It does not affect the deployed system today, which connects as `postgres`: the table owner is
exempt from RLS, so no policy is evaluated at all. That is exactly why nothing caught it — the
defect is invisible from the only connection anyone has used.

WHY 045 MISSED THEM. Its own comment names them:

    Old policies were created in migrations 001 (users_isolation, shops_isolation,
    credentials_isolation), 002 (various {table}_isolation), 017, 019, 020, 022...

and its drop list has seventeen entries containing `credentials_isolation` and neither of the
other two. The intent was written down; the list did not match it. Third omission of that shape
on this wave, after 045's own missing RLS tables (#1329, fixed in 046) and 044's missing grants
(#1453, fixed in 048).

WHY DROPPING IS SAFE HERE. ADR-086 warns against leaving a table RLS-enabled with zero
policies, which denies everything to `juli_app` and is indistinguishable from data loss. That
hazard does not apply: both tables keep four per-command policies afterwards. The migration
asserts this rather than trusting it — see `_assert_command_coverage`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "049_drop_legacy_isolation"
down_revision: str | None = "048_prod_write_auth_grants"
branch_labels: str | None = None
depends_on: str | None = None

# (schema, table, policy, column) tuples this migration removes. Deliberately
# explicit rather than pattern-matched on `%_isolation`: 045 already dropped
# seventeen such policies legitimately, and a pattern would silently widen if
# another arrives.
#
# The column differs between the two, which is not obvious and cost a round here:
# migration 001 matches `users.id` but `shops.user_id`. A downgrade that assumed
# one column for both fails with `column "user_id" does not exist` — caught by
# running the migration suites rather than by reading the diff.
LEGACY_POLICIES: tuple[tuple[str, str, str, str], ...] = (
    ("public", "shops", "shops_isolation", "user_id"),
    ("public", "users", "users_isolation", "id"),
)

# A policy must remain for each of these after the drop, or the table denies that
# verb outright to the runtime role.
_REQUIRED_COMMANDS = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _assert_command_coverage(schema: str, table: str, excluding: str) -> None:
    """Refuse to drop a policy that is the last cover for any command.

    The failure this prevents is the one ADR-086 names: a table left RLS-enabled
    with no policy for some command denies it to `juli_app` entirely, and a
    denial reads exactly like an empty table. Checked before the drop, so a
    surprise aborts the migration instead of shipping a silent deny-all.
    """
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT cmd, count(*) AS n
              FROM pg_policies
             WHERE schemaname = :schema
               AND tablename = :table
               AND policyname <> :excluding
             GROUP BY cmd
            """
        ),
        {"schema": schema, "table": table, "excluding": excluding},
    ).all()

    # `cmd` is 'ALL' for a FOR ALL policy and the verb otherwise; an 'ALL' policy
    # covers every command.
    covered = {row.cmd for row in rows}
    if "ALL" in covered:
        return

    uncovered = [command for command in _REQUIRED_COMMANDS if command not in covered]
    if uncovered:
        raise RuntimeError(
            f"Refusing to drop {excluding} on {schema}.{table}: it is the last policy covering "
            f"{uncovered}. Dropping it would leave the table RLS-enabled and denying those "
            "commands to juli_app, which is indistinguishable from an empty table (ADR-086)."
        )


def upgrade() -> None:
    """Remove the legacy FOR ALL policies, after proving coverage survives."""
    for schema, table, policy, _column in LEGACY_POLICIES:
        _assert_command_coverage(schema, table, excluding=policy)
        # nosec B608: schema, table and policy come from the LEGACY_POLICIES
        # constant above — never parameters, never reachable from a request.
        # Policy names cannot be bound as query parameters. Same construction and
        # suppression as 045_rls_policies.py's own DROP POLICY loop.
        sql = f"DROP POLICY IF EXISTS {policy} ON {schema}.{table};"  # nosec B608
        op.execute(sql)


def downgrade() -> None:
    """Recreate the legacy policies exactly as migration 001 left them.

    Including the one-argument `current_setting`, which is the defect. A
    downgrade must restore the prior state faithfully rather than a corrected
    version of it — a downgrade that silently improves things makes the upgrade
    unreviewable and hides what actually changed.
    """
    for schema, table, policy, column in LEGACY_POLICIES:
        # `CREATE POLICY ... USING (...)` with no FOR clause defaults to FOR ALL,
        # which is how migration 001 wrote them and why pg_policies reports
        # cmd = 'ALL'. Written the same way here so the recreated policy is
        # byte-for-byte the one being restored.
        #
        # nosec B608: see the note in upgrade().
        sql = f"""
        CREATE POLICY {policy} ON {schema}.{table}
          USING ({column} = current_setting('app.current_user_id')::uuid);
        """  # nosec B608
        op.execute(sql)

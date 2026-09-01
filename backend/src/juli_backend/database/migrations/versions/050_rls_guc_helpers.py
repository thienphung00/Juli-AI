"""Route every RLS policy through a GUC helper that tolerates the empty string (#1467).

`SET LOCAL` does not unset a custom GUC at commit — it restores the parameter's default, which
for `app.current_shop_id` and `app.current_user_id` is the **empty string**, not unset. Every
policy casts the raw `current_setting(...)` to `uuid`, and `''::uuid` raises:

    juli_app@prod=> select count(*) from shops;   -- after any committed transaction
    ERROR:  invalid input syntax for type uuid: ""

`database/tenant_context.py` sets context with `set_config(name, val, true)` — the third
argument is `is_local`, so this is `SET LOCAL`, which ADR-086 decision 6 mandates. The GUC
therefore becomes `''` the moment that transaction commits, and the next query against a
policied table raises. On a Supavisor-pooled connection that poisons the connection for its
lifetime.

Measured against production at head `049_drop_legacy_isolation` on 2026-09-01: **166** policies
reference a GUC, **0** guard against the empty string.

    never set (fresh connection) -> current_setting(...) is NULL -> NULL::uuid -> no rows  OK
    after SET LOCAL + COMMIT     -> current_setting(...) is ''   -> ''::uuid   -> RAISES

WHY A HELPER FUNCTION RATHER THAN INLINE `nullif`.

Both fix the cast. The helper gives the semantics a single definition point, which matters here
specifically: three defects on this wave (#1329, #1453, #1455) were all a duplicated list or
expression drifting from its intent. With a helper, a policy either calls it or it does not, and
`tests/integration/test_rls_policy_guc_helper.py` can assert exactly that — a stronger and far
simpler invariant than checking `nullif` is positioned correctly inside 166 hand-written
expressions.

It costs nothing at runtime. A `STABLE` SQL function of this shape is inlined by the planner;
verified on a database at head that the index condition is preserved rather than degraded to a
filter:

    Index Cond: (workflow_runs.shop_id =
                 (NULLIF(current_setting('app.current_shop_id'::text, true), ''::text))::uuid)

WHY THE REWRITE IS DRIVEN BY THE CATALOG.

The alternative is to restate migration 045's table lists and regenerate. That is precisely the
pattern that produced #1329 (045 missed two tables), #1453 (044 granted nothing) and #1455 (045
documented two policies it did not drop): a hand-maintained list diverging from the database.

This migration instead reads `pg_policies` and rewrites what is actually there. It cannot miss a
policy a later migration added, and it cannot act on one that no longer exists. Production
renders exactly two distinct forms across all 166 policies, so the substitution is exact rather
than heuristic:

    current_setting('app.current_shop_id'::text, true)  ->  app_current_shop_id()
    current_setting('app.current_user_id'::text, true)  ->  app_current_user_id()
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "050_rls_guc_helpers"
down_revision: str | None = "049_drop_legacy_isolation"
branch_labels: str | None = None
depends_on: str | None = None

# The exact strings Postgres renders in pg_policies for the two GUCs, and the
# helper each maps to. Verified against production: these two forms cover all
# 166 policies, with no third variant.
#
# THE MAPPING IS NOT SYMMETRIC, and assuming it was cost a round. Forward, the
# raw call is replaced inside its cast — `(current_setting(...))::uuid` becomes
# `(app_current_shop_id())::uuid`, and Postgres then RE-RENDERS the stored
# expression, dropping the cast as redundant because the helper already returns
# uuid:
#
#     before:  (user_id = (current_setting('app.current_user_id'::text, true))::uuid)
#     after:   (user_id = app_current_user_id())
#
# So reversing by swapping the helper for the bare call yields
# `user_id = current_setting(...)` — text against uuid — and the downgrade dies
# on `operator does not exist: uuid = text`. The reverse direction must put the
# cast back.
_FORWARD: tuple[tuple[str, str], ...] = (
    ("current_setting('app.current_shop_id'::text, true)", "app_current_shop_id()"),
    ("current_setting('app.current_user_id'::text, true)", "app_current_user_id()"),
)

_REVERSE: tuple[tuple[str, str], ...] = (
    ("app_current_shop_id()", "(current_setting('app.current_shop_id'::text, true))::uuid"),
    ("app_current_user_id()", "(current_setting('app.current_user_id'::text, true))::uuid"),
)

_HELPERS: tuple[tuple[str, str], ...] = (
    ("app_current_shop_id", "app.current_shop_id"),
    ("app_current_user_id", "app.current_user_id"),
)


def _create_helpers() -> None:
    """Define the two helpers.

    `STABLE`, not `IMMUTABLE`: the value depends on session state, so declaring
    it immutable would let the planner cache it across a context change.

    Not `SECURITY DEFINER`: it reads a GUC and grants no access. `EXECUTE`
    defaults to PUBLIC for a new function, which is what policy evaluation
    needs; nothing narrower would let `juli_app` evaluate its own policies.

    `search_path` is pinned so the body cannot be captured by a schema earlier
    on a caller's path.
    """
    for function_name, guc in _HELPERS:
        # nosec B608: function_name and guc come from the _HELPERS constant above,
        # never from a parameter or a request.
        sql = f"""
        CREATE OR REPLACE FUNCTION public.{function_name}() RETURNS uuid
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, public
          AS $func$ SELECT nullif(current_setting('{guc}', true), '')::uuid $func$;
        """  # nosec B608
        op.execute(sql)


def _rewrite_policies(forward: bool) -> None:
    """Rewrite every policy expression that mentions one of the two GUCs.

    Reads `pg_policies` rather than a restated table list, so it covers exactly
    the policies that exist. `ALTER POLICY` is used rather than DROP + CREATE:
    the policy keeps its identity, its command and its roles, and there is no
    window in which the table sits with one fewer policy.

    A SELECT/UPDATE/DELETE policy has `qual` only; an INSERT policy has
    `with_check` only; an ALL policy may have both. `ALTER POLICY` rejects a
    clause the policy does not have, so each is emitted only when present.

    THE FILTER MUST FOLLOW THE DIRECTION. Selecting on `current_setting` in both
    directions looks symmetric and is not: after the forward pass no policy
    contains that string any more, so the reverse pass matched nothing, left
    every policy pointing at the helpers, and `DROP FUNCTION` then failed on 59
    dependent objects. The downgrade aborted rather than half-applying, but it
    was broken. Caught by running the round trip, not by reading the diff.
    """
    needle = "current_setting" if forward else "app_current_"
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT schemaname, tablename, policyname, qual, with_check
              FROM pg_policies
             WHERE coalesce(qual, '') LIKE :pattern
                OR coalesce(with_check, '') LIKE :pattern
            """
        ),
        {"pattern": f"%{needle}%"},
    ).all()

    for row in rows:
        clauses = []
        for attribute, keyword in (("qual", "USING"), ("with_check", "WITH CHECK")):
            expression = getattr(row, attribute)
            if not expression:
                continue
            rewritten = expression
            for source, target in _FORWARD if forward else _REVERSE:
                rewritten = rewritten.replace(source, target)
            if rewritten != expression:
                clauses.append(f"{keyword} ({rewritten})")

        if not clauses:
            continue

        # nosec B608: every value here comes from pg_policies on this same
        # connection — the database's own rendering of expressions it already
        # holds. There is no external input on this path, and a policy name
        # cannot be bound as a query parameter.
        statement = (
            f'ALTER POLICY "{row.policyname}" '
            f'ON "{row.schemaname}"."{row.tablename}" ' + " ".join(clauses) + ";"
        )  # nosec B608
        op.execute(statement)


def upgrade() -> None:
    """Create the helpers, then point every policy expression at them."""
    _create_helpers()
    _rewrite_policies(forward=True)


def downgrade() -> None:
    """Put the raw `current_setting` calls back, then drop the helpers.

    Order matters: the policies must stop referencing the functions before the
    functions can be dropped. This restores the pre-#1467 behaviour exactly,
    empty-string defect included — a downgrade that silently keeps the fix would
    make the upgrade unreviewable.
    """
    _rewrite_policies(forward=False)
    for function_name, _guc in _HELPERS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{function_name}();")  # nosec B608

"""Widen enumerate_active_workflow_runs to cover waiting_approval.

Issue #1489 / ADR-089 decision 3.

051 defined "active" as `queued`/`running`. The reaper has a second path —
`_reap_expired_waiting_approval` — and `waiting_approval` is not a terminal
state: a run parked on a human is still active. Left out of the enumeration,
that path has no fleet-wide read available to it, so under RLS as `juli_app`
with no shop context it selects zero rows and the reap silently never happens.
That is precisely the successful no-op this epic exists to remove, so the fix
belongs in the enumeration rather than in a context-less fallback query.

Columns are unchanged, so `test_fleet_enumeration_functions.py`'s column
contract still holds — only the status predicate widens.

`CREATE OR REPLACE FUNCTION` preserves the existing ACL, but the REVOKE/GRANT
is replayed anyway: this migration must leave the same end state whether or not
the function already carried 051's grants.
"""

from __future__ import annotations

from alembic import op

# The annotated form is not cosmetic: `_latest_revision()` in
# `tests/integration/test_migrations.py` derives the single head with a regex
# that requires `revision: str = "..."`. An untyped declaration is invisible to
# it, so the head-assertion silently checks the previous migration instead.
revision: str = "052_reaper_waiting_approval"
down_revision: str | None = "051_fleet_enumeration_fns"
branch_labels: str | None = None
depends_on: str | None = None

_SIGNATURE = "enumerate_active_workflow_runs()"

_BODY_WITH_WAITING_APPROVAL = "('queued', 'running', 'waiting_approval')"
_BODY_051 = "('queued', 'running')"


def _replace(statuses: str) -> None:
    # nosec B608: `statuses` is one of the two module constants above — never a
    # parameter, never reachable from a request.
    body = f"""
    CREATE OR REPLACE FUNCTION public.enumerate_active_workflow_runs()
    RETURNS TABLE (
        out_run_id uuid,
        out_shop_id uuid,
        out_status varchar,
        out_created_at timestamp without time zone,
        out_running_seconds_elapsed integer
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT r.id, r.shop_id, r.status, r.created_at, r.running_seconds_elapsed
          FROM public.workflow_runs AS r
         WHERE r.status IN {statuses}
      $fn$;
    """  # nosec B608
    op.execute(body)


def _restrict_execute() -> None:
    """Take EXECUTE from PUBLIC and give it only to the runtime role.

    Guarded on the role existing for the same reason 043 guards CREATE ROLE:
    roles are cluster-global while migrations are per-database.
    """
    # nosec B608: _SIGNATURE is the module constant above — never a parameter,
    # never reachable from a request. A function signature cannot be bound as a
    # query parameter.
    revoke = f"REVOKE ALL ON FUNCTION public.{_SIGNATURE} FROM PUBLIC;"  # nosec B608
    op.execute(revoke)
    grant = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            GRANT EXECUTE ON FUNCTION public.{_SIGNATURE} TO juli_app;
        END IF;
    END
    $$;
    """  # nosec B608
    op.execute(grant)


def upgrade() -> None:
    _replace(_BODY_WITH_WAITING_APPROVAL)
    _restrict_execute()


def downgrade() -> None:
    _replace(_BODY_051)
    _restrict_execute()

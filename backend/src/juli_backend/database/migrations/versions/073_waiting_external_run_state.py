"""waiting_external: widen both workflow_runs CHECKs, the active-run index and
the fleet enumeration, and add the two columns the wait is measured from (#1706)

Revision ID: 073_waiting_external
Revises: 071_sync_state_last_outcome
Create Date: 2026-09-22

WHAT THIS IS FOR. A run could only ever pause on a PERSON, for four hours
(``approval_timeout_h``). ADR-091 d.4 and ADR-093 d.2 need a run that pauses on
the WORLD -- a discount window running down, a supplier delivering -- for days.
That is a new value in the run-status vocabulary, and the vocabulary is pinned
in five places at once (the Python enum, this CHECK, the TypeScript union, the
status-mapping totality test, and the derived terminal/suspended sets). This
revision is the database half; all five move in the same commit.

FIVE STATEMENTS, ALL ADDITIVE, EACH FOR A DIFFERENT REASON
-----------------------------------------------------------
1. ``ck_workflow_runs_status`` gains ``'waiting_external'`` (16 characters,
   inside the column's ``String(20)``).
2. ``ck_workflow_runs_stop_reason`` gains ``'paused_for_external_wait'`` (24)
   and ``'external_wait_expired'`` (21), both inside ``String(32)``. The first
   is the suspending reason that targets the new status -- the analogue of
   ``paused_for_confirmation`` targeting ``waiting_approval`` -- and without it
   the reverse-totality test has no reason to assert; the second is the
   reaper's terminal cause when the wait runs out.
3. Two nullable columns: ``waiting_external_since`` and
   ``external_wait_reason``.
4. ``uq_workflow_runs_active_shop_product``'s partial predicate gains the new
   status.
5. ``enumerate_active_workflow_runs()`` gains it too.

WHY THE TWO COLUMNS ARE NOT REUSED FROM WHAT EXISTS. The reaper needs an
instant to measure the external wait from. ``waiting_approval_since`` is the
wrong instant by construction -- a run that paused for a seller and then, after
resuming, paused for a supplier would be judged from the seller pause, and
``updated_at`` moves on every unrelated write. So ``waiting_external_since`` is
its own column, nullable, no backfill: a run that has never waited externally
has no such instant and inventing one would be a false fact of exactly the kind
071 refused to manufacture. ``external_wait_reason`` records WHAT the run is
waiting for; it is what #1708's webhook dispatcher will match a signal against
in SQL, and without it the ``reason`` argument of
``WorkflowRunner.enter_external_wait`` would be decorative. ``String(64)``
matches ``subject_ref``'s width -- the reason is a short key, never prose.

WHY THE INDEX PREDICATE IS WIDENED, WHICH IS A DECISION AND NOT A DETAIL.
``uq_workflow_runs_active_shop_product`` (re-keyed by 062) is the structural
"one active run per subject" guard, and "active" there means "still holds its
subject". A run suspended on a supplier for two days holds its subject exactly
as a run suspended on a seller for four hours does. Leaving ``waiting_external``
out of the predicate would silently have released the subject's slot the moment
a run entered the state -- a second run could start on a subject a live run
still owns -- and would have undermined #1710's cross-workflow subject lock
before it was written. The widening cannot collide with existing data: no row
can carry ``'waiting_external'`` until the code that writes it ships, and it
ships in this same commit. ``op.drop_index`` is a relaxation, which the
additive gate tolerates by name, and the widened index is created before this
migration returns.

WHY THE ENUMERATION FUNCTION IS WIDENED. This is 052's lesson, reproduced
exactly. ``_reap_expired_waiting_approval`` had no fleet-wide read available to
it until 052 added ``waiting_approval`` to
``enumerate_active_workflow_runs()``; as ``juli_app`` with no shop context it
selected zero rows and the reap reported success having done nothing. A
``waiting_external`` reap path added without the same widening would be that
identical successful no-op, in production only -- the SQLite unit tests take
``_enumerate_active_runs``'s non-Postgres branch and would pass either way.
The column list is unchanged, so ``test_fleet_enumeration_functions.py``'s
column contract still holds; only the status predicate moves.

ADDITIVE. A widened IN-list accepts every value it accepted before; two
nullable columns with no defaults are invisible to code that never names them;
a widened partial index can only make MORE rows participate in a uniqueness
the previous code never violates, because the previous code cannot write the
new status at all. So the still-serving stable instance keeps reading and
writing ``workflow_runs`` unchanged during the shared-database window of a
release, and a code rollback needs no schema undo.
``infra/scripts/migration_additive_gate.py`` accepts it;
``tests/unit/test_waiting_external_migration.py`` pins that it does.

DOWNGRADE REFUSES RATHER THAN COERCES. Narrowing a CHECK under live rows is
the one direction that can destroy a record: an operator faced with an opaque
constraint-validation failure is tempted to delete the suspended runs. So
``downgrade`` counts the rows carrying the new vocabulary FIRST and raises,
naming them, before touching any constraint. A run left in ``waiting_external``
across a code-only rollback is inert -- the previous reaper does not recognise
the state and will never reap it -- so those runs must be drained deliberately
before a schema revert, not discovered during one.

CHAIN. Revises ``071_sync_state_last_outcome``, the head of ``versions/``. The
deferred contract step from #1972 is renumbered onto THIS revision in the same
change (``deferred/074_users_placeholder_phone_cleanup.py``) -- a deferred step
that keeps an older parent stops being the tail the moment a new ``versions/``
revision lands above it, and it then forks the chain when an operator copies it
into a serving release's ``versions/``. That is the FOURTH hand-renumber
(065->066, 066->068, 070->072, 072->074); it should be a pre-commit mechanism,
and #1950's PR body already says so.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "073_waiting_external"
down_revision: str | None = "071_sync_state_last_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "workflow_runs"

_STATUS_CONSTRAINT = "ck_workflow_runs_status"
_STOP_REASON_CONSTRAINT = "ck_workflow_runs_stop_reason"
_ACTIVE_INDEX = "uq_workflow_runs_active_shop_product"
_ACTIVE_INDEX_COLUMNS = ("shop_id", "workflow_key", "subject_type", "subject_ref")

#: The status vocabulary BEFORE this revision (034, unchanged since).
_STATUSES_BEFORE = (
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "cancelled",
    "timed_out",
    "failed",
)
#: ...and after. Order mirrors `services/agent/status.py::WorkflowRunStatus`.
_STATUSES_AFTER = (
    "queued",
    "running",
    "waiting_approval",
    "waiting_external",
    "completed",
    "cancelled",
    "timed_out",
    "failed",
)

#: The stop-reason vocabulary BEFORE this revision (043 was the last widening).
_STOP_REASONS_BEFORE = (
    "final_response",
    "confirmation_declined",
    "paused_for_confirmation",
    "cancelled_by_seller",
    "confirmation_expired",
    "confirmation_diverged",
    "prompt_version_unrecoverable",
    "iteration_cap_exceeded",
    "wall_clock_timeout",
    "tool_error_unrecoverable",
    "llm_error",
    "concurrency_conflict",
    "output_validation_failed",
    "worker_lost",
    "concluded_without_changes",
    "required_steps_unfulfilled",
)
_STOP_REASONS_AFTER = (
    *_STOP_REASONS_BEFORE,
    "paused_for_external_wait",
    "external_wait_expired",
)

#: Which statuses hold a subject's active-run slot, and which rows the fleet
#: enumeration hands the reaper. One tuple, two consumers, so the index
#: predicate and the SQL function cannot disagree about what "active" means.
_ACTIVE_STATUSES_BEFORE = ("queued", "running", "waiting_approval")
_ACTIVE_STATUSES_AFTER = ("queued", "running", "waiting_approval", "waiting_external")

#: `(name, type)` for each added column, declared once so `downgrade` cannot
#: drift from `upgrade` by hand-editing one list (071's shape).
WAIT_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("waiting_external_since", sa.DateTime(timezone=True)),
    ("external_wait_reason", sa.String(length=64)),
)

_NEW_STATUS = "waiting_external"
_NEW_STOP_REASONS = ("paused_for_external_wait", "external_wait_expired")

_ENUMERATION_SIGNATURE = "enumerate_active_workflow_runs()"


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(repr(value) for value in values)


def _replace_status_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(_STATUS_CONSTRAINT, TABLE_NAME, type_="check")
    op.create_check_constraint(
        _STATUS_CONSTRAINT,
        TABLE_NAME,
        f"status IN ({_in_list(values)})",
    )


def _replace_stop_reason_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(_STOP_REASON_CONSTRAINT, TABLE_NAME, type_="check")
    op.create_check_constraint(
        _STOP_REASON_CONSTRAINT,
        TABLE_NAME,
        f"stop_reason IS NULL OR stop_reason IN ({_in_list(values)})",
    )


def _replace_active_index(statuses: tuple[str, ...]) -> None:
    """Rebuild the partial unique with a different WHERE clause, same name.

    Postgres has no ``ALTER INDEX ... SET PREDICATE``; this is the only shape
    available, and it is the same one 062 used to re-key the index.
    """
    op.drop_index(_ACTIVE_INDEX, table_name=TABLE_NAME)
    op.create_index(
        _ACTIVE_INDEX,
        TABLE_NAME,
        list(_ACTIVE_INDEX_COLUMNS),
        unique=True,
        postgresql_where=sa.text(f"status IN ({_in_list(statuses)})"),
    )


def _replace_enumeration(statuses: tuple[str, ...]) -> None:
    """``CREATE OR REPLACE`` the fleet enumeration with a wider predicate.

    Body copied from 052 with the status tuple parameterised. The columns are
    identical -- narrowing the signature is #1510's, not this revision's.
    """
    # nosec B608: `statuses` is one of the two module tuples above -- never a
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
         WHERE r.status IN ({_in_list(statuses)})
      $fn$;
    """  # nosec B608
    op.execute(body)
    _restrict_enumeration_execute()


def _restrict_enumeration_execute() -> None:
    """Replay 052's REVOKE/GRANT so this migration leaves the same end state
    whether or not the function already carried them. Guarded on the role
    existing because roles are cluster-global while migrations are
    per-database."""
    # nosec B608: the signature is the module constant above -- a function
    # signature cannot be bound as a query parameter.
    op.execute(f"REVOKE ALL ON FUNCTION public.{_ENUMERATION_SIGNATURE} FROM PUBLIC;")  # nosec B608
    op.execute(  # nosec B608
        f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            GRANT EXECUTE ON FUNCTION public.{_ENUMERATION_SIGNATURE} TO juli_app;
        END IF;
    END
    $$;
    """
    )


def _refuse_if_the_new_vocabulary_is_in_use(bind: sa.engine.Connection) -> None:
    """Downgrade guard: narrowing a CHECK under live rows must fail by name.

    Counted and reported BEFORE anything is dropped, so the operator reads a
    sentence naming what is in the way rather than a constraint-validation
    error -- the failure mode that tempts someone into deleting suspended runs.
    """
    status_rows = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM public.{TABLE_NAME} WHERE status = :status"),
        {"status": _NEW_STATUS},
    ).scalar_one()
    reason_rows = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM public.{TABLE_NAME} WHERE stop_reason = ANY(:reasons)"),
        {"reasons": list(_NEW_STOP_REASONS)},
    ).scalar_one()
    if status_rows or reason_rows:
        raise RuntimeError(
            f"Refusing downgrade of {revision}: {status_rows} workflow_runs row(s) "
            f"carry status {_NEW_STATUS!r} and {reason_rows} carry one of "
            f"{sorted(_NEW_STOP_REASONS)}. Narrowing these CHECK constraints would "
            "fail at validation time, and the runs in question are INERT under the "
            "previous release -- its reaper does not recognise the state and will "
            "never reap them. Drain or reap those runs deliberately first."
        )


def upgrade() -> None:
    """Widen both CHECKs, add the two wait columns, widen the active-run index
    and the fleet enumeration. Nothing is read, nothing is written, nothing is
    dropped that is not immediately recreated wider."""
    _replace_status_check(_STATUSES_AFTER)
    _replace_stop_reason_check(_STOP_REASONS_AFTER)
    for name, column_type in WAIT_COLUMNS:
        op.add_column(
            TABLE_NAME,
            sa.Column(name, column_type, nullable=True, server_default=None),
        )
    _replace_active_index(_ACTIVE_STATUSES_AFTER)
    _replace_enumeration(_ACTIVE_STATUSES_AFTER)


def downgrade() -> None:
    """Restore the pre-#1706 vocabulary, or refuse loudly.

    Migrations here are schema-only and are never automatically reverted
    (ADR-027); this exists to complete the Alembic contract and to make the
    refusal above a tested fact rather than a hope.
    """
    _refuse_if_the_new_vocabulary_is_in_use(op.get_bind())
    _replace_enumeration(_ACTIVE_STATUSES_BEFORE)
    _replace_active_index(_ACTIVE_STATUSES_BEFORE)
    for name, _ in reversed(WAIT_COLUMNS):
        op.drop_column(TABLE_NAME, name)
    _replace_stop_reason_check(_STOP_REASONS_BEFORE)
    _replace_status_check(_STATUSES_BEFORE)

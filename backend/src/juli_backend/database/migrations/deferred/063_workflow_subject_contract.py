"""CONTRACT step for #1701/#2050: backfill workflow_runs.subject_ref, close the column

Revision ID: 063_workflow_subject_contract
Revises: 062_workflow_and_subject
Create Date: 2026-09-20

**This file is deliberately NOT in ``versions/``. Do not move it there until it
has been applied to production.** Read the next two sections before touching it.

Why it is parked here
---------------------
``062_workflow_and_subject`` originally carried these two statements. They are
non-additive, so ``infra/scripts/migration_additive_gate.py`` refused every
release from 2026-09-16 on and nothing deployed (#2050). #2050 split 062 into
an additive expand step and this contract step.

Putting this revision in ``versions/`` would not unblock anything -- it would
deadlock the release lane instead. The gate inspects every revision *pending*
between the database's current revision and head:

* with this file in ``versions/``, pending becomes ``[062, 063]``, the gate
  refuses on 063, ``deploy_lane_api`` returns before any candidate starts, and
  the expand code never reaches production;
* but this step must not run until that expand code IS in production, because
  making ``subject_ref`` NOT NULL is precisely what stops the older release
  from inserting a ``workflow_runs`` row.

Each side waits on the other. Keeping the file out of ``versions/`` breaks the
cycle: Alembic's head stays ``062_workflow_and_subject``, the release lane sees
one additive pending revision and passes, and this step is operated by hand
once the expand release is serving. That is the same shape as
``056_series_source_column``, run by hand on 2026-09-09 (see
``docs/handoffs/2026-09-09-w6-wave-to-main-reconcile.md``) -- the difference is
only that this file says so up front instead of being discovered at deploy
time.

The gate REFUSES this file, and that is the correct verdict, not a defect:
``tests/unit/test_workflow_subject_contract_migration.py`` asserts the refusal,
because "the gate accepts it" would mean it had stopped being the contract
step.

How it is operated
------------------
``docs/runbooks/backend-deploy-runbook.md`` § "Separately-operated contract
migrations" holds the procedure and the preconditions. In outline, on the VPS,
against the release directory that is *currently serving*:

1. Confirm the serving release contains ``062_workflow_and_subject`` and that
   ``alembic current`` reports it. If the database is still at 061, STOP: the
   expand step has not landed and this step's NOT NULL would break the running
   code.
2. Take the backup (``infra/scripts/safe-alembic-upgrade.sh`` does this; a
   manual ``pg_dump`` is the alternative when running the step standalone).
3. Copy this file into that release's ``versions/`` directory and leave it
   there -- removing it afterwards would leave Alembic at a revision with no
   file on disk.
4. ``alembic upgrade head``.
5. Land a follow-up PR moving this file from ``deferred/`` into ``versions/``.
   At that point it is already applied, so it is no longer pending and the gate
   accepts the next release.

What it does
------------
* Backfills ``workflow_runs.subject_ref`` from each row's own ``product_id``.
  A constant ``DEFAULT`` cannot express "this row's own ``product_id``", which
  is why this is an ``UPDATE`` and why it cannot be part of the expand step.
  Only rows written before 062 landed, or written afterwards by the older
  release during the rollout window, can be NULL -- every INSERT made by the
  code that ships with 062 already supplies the value client-side
  (``models.py::_default_workflow_run_subject_ref``).
* Refuses, loudly and before writing anything, if any row has BOTH
  ``subject_ref`` and ``product_id`` NULL. That row's subject is unknowable
  here, and ``product_id::text`` would silently write the string ``"None"``
  -- the same failure ``_default_workflow_run_subject_ref`` raises on
  client-side. Such a row cannot exist today (``product_id`` was NOT NULL
  until 062), so this guard is for a future non-product run that arrived
  between the two steps.
* Narrows ``subject_ref`` to NOT NULL, completing the shape ADR-087 d.1
  specifies and ``models.py`` already declares, and restoring the partial
  unique ``uq_workflow_runs_active_shop_product`` to full effect: while
  ``subject_ref`` is nullable that index does not constrain a NULL-subject row,
  because Postgres never treats two NULLs as equal.

The downgrade reopens the column to nullable and stops there. It deliberately
does NOT un-backfill: the backfilled values are the correct ones, dropping them
would destroy information, and 062's own downgrade drops the column outright
anyway.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "063_workflow_subject_contract"
down_revision: str | None = "062_workflow_and_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _refuse_if_a_subjectless_run_exists(bind: sa.engine.Connection) -> None:
    """A run with neither ``subject_ref`` nor ``product_id`` has no subject this
    step can infer, and ``product_id::text`` would write the literal ``"None"``."""
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM public.workflow_runs "
            "WHERE subject_ref IS NULL AND product_id IS NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Refusing {revision}: {count} workflow_runs row(s) have both a NULL "
            "subject_ref and a NULL product_id, so this step cannot infer their "
            "subject and would write the literal string 'None'. Give each of "
            "those rows an explicit subject_ref (the same rule "
            "models.py::_default_workflow_run_subject_ref enforces client-side) "
            "before running this contract step."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _refuse_if_a_subjectless_run_exists(bind)
    op.execute(
        "UPDATE public.workflow_runs SET subject_ref = product_id::text WHERE subject_ref IS NULL"
    )
    op.alter_column(
        "workflow_runs",
        "subject_ref",
        existing_type=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "subject_ref",
        existing_type=sa.String(length=64),
        nullable=True,
    )

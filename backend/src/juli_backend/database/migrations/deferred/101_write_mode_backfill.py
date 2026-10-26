"""DATA step for P61-F: mark agent runs that wrote to the SANDBOX as ``write_mode='simulated'``

Revision ID: 101_write_mode_backfill
Revises: 104_shop_pseudonym_keys
Create Date: 2026-10-21

DECISIONS D71.2 (owner, 2026-10-21); DEBT P61-B "No backfill of ``workflow_runs.write_mode``".

**This file is deliberately NOT in ``versions/``.** It is an ``UPDATE``, which
``infra/scripts/migration_additive_gate.py`` refuses from an automatic release by
design and with no allowlist (see ``074_users_placeholder_phone_cleanup`` in this
directory, and ``docs/runbooks/backend-deploy-runbook.md`` "Separately-operated
contract migrations"). In ``versions/`` it would be pending on every release, the
gate would refuse, and nothing would deploy. It ships as a separately-operated
step, exactly like 074, and ``074`` is re-parented onto it so that the deferred
steps form one chain and ``074`` stays the tail.

What it proves, and why that is enough
--------------------------------------
Migration 097 added ``workflow_runs.write_mode`` and the code that stamps it at
run construction. A run written before that is NULL. Before P61-F **no agent write
ever left the sandbox merchant**: production writes did not exist for agent runs,
and the dispatched path was behind ``PRODUCTION_WRITE_ENABLED`` (off in every
environment) and the per-shop ``production_write_shops`` row (097, empty). So a
NULL run that *executed a write* wrote to the sandbox. The predicate does not rest
on that history alone; it requires three facts in the database:

1. the run is still NULL (never overwrite a stamped value; this is also what makes
   a second run a no-op);
2. the run has a ``tool_executions`` row with status ``succeeded`` for one of the
   write tools (the agent's ``update_product_listing`` / ``upload_product_image`` /
   ``update_product_price``, or the dispatched ``listing.*`` tools), i.e. it really
   executed a write;
3. NO ``production_write_audit`` row of the run carries an authorization, and NO
   ``production_write_authorizations`` row was consumed by the run, i.e. no live
   authorization was ever spent on it. A run that did go live always leaves one of
   those (the resolver consumes the authorization and audits the allowed attempt in
   one transaction), so it is left alone.

A NULL run that wrote nothing (declined, cancelled, "no change") stays NULL: there
is nothing to call simulated.

Idempotent
----------
Re-running changes nothing (fact 1). Literal SQL in one ``op.execute``, so a gate
that reads the file sees exactly what runs.

Downgrade is a NO-OP, on purpose
--------------------------------
After this step a backfilled row is indistinguishable from a row P61-B's code
stamped ``simulated`` at construction, so restoring NULL would erase real stamps
and cannot be done safely. Leaving the value is harmless: 097's ``downgrade`` drops
the column, and the previous code ignores it.

How it is operated
------------------
Same procedure as 074: serving release at ``102_shops_tiktok_numeric_id`` (P68
re-parented this step onto it; it was ``100_sandbox_collision_xshop``); take the
backup (``infra/scripts/safe-alembic-upgrade.sh`` does); copy this file (and, if
running 074 too, that one) into the serving release's ``versions/`` and leave it
there; ``alembic upgrade head``; land a follow-up moving it from ``deferred/`` into
``versions/`` (already applied, so no longer pending). Running it late is harmless:
until it runs, those runs are shown and measured as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "101_write_mode_backfill"
down_revision: str | None = "104_shop_pseudonym_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    UPDATE public.workflow_runs
       SET write_mode = 'simulated'
     WHERE write_mode IS NULL
       AND EXISTS (
            SELECT 1 FROM public.tool_executions te
             WHERE te.workflow_run_id = workflow_runs.id
               AND te.status = 'succeeded'
               AND te.tool_name IN (
                    'update_product_listing', 'upload_product_image', 'update_product_price',
                    'listing.optimize_product', 'listing.create_hero_product'
               )
       )
       AND NOT EXISTS (
            SELECT 1 FROM public.production_write_audit a
             WHERE a.run_id = workflow_runs.id AND a.authorization_id IS NOT NULL
       )
       AND NOT EXISTS (
            SELECT 1 FROM public.production_write_authorizations pa
             WHERE pa.consumed_by_run_id = workflow_runs.id
       )
    """)


def downgrade() -> None:
    """No-op: a backfilled row cannot be told from one the code stamped (module docstring)."""

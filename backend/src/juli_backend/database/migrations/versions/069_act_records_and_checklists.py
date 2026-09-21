"""every act leaves one record: run_act_records + run_checklist_items (#1712)

Revision ID: 069_act_records_and_checklists
Revises: 065_users_email
Create Date: 2026-09-21

W9-A/P-SHARED-12, spec S-FR-12 and the P0 ladder's P0-8/P0-13. Two new tables
and nothing else: **this revision ships a schema with no reader and no writer.**
#1713 adds the producer. That is deliberate, not an unfinished slice -- the
epic (#1620) names "a consumer without a producer" as the failure mode this
wave exists to stop, and shipping the table first is how the producer gets a
real object to bind to instead of a double.

Because there is no call site yet, ``juli_app`` receives ``SELECT`` and nothing
else. Acceptance criterion 2 is a *read* by the runtime role with no tenant
context, and it must observe zero rows -- a role with no grant at all would
observe ``permission denied`` instead, which proves the grant is missing rather
than that the policy denies. ``INSERT``/``UPDATE`` arrive with #1713's writer,
alongside the call site that justifies them; granting them here would fail
``tests/integration/test_migrations.py::test_no_public_table_holds_update_beyond_its_call_site``
and would be a privilege nothing in the codebase could exercise.

The file number, and why ``down_revision`` is 065
-------------------------------------------------
The number 069 was reserved for this slice while #1950 held 067 and was
re-chaining the deferred phone cleanup onto it as 068. At the time this file
was written, neither of those existed anywhere outside a local worktree --
``origin/main`` was at ``c8ce54c0`` with ``065_users_email`` as the head of
``versions/``. Chaining onto a revision that is not on the branch would make
``ScriptDirectory`` unresolvable and fail every migration test here, so this
revision chains onto the head that actually exists and keeps the reserved
*file number*, which is what stops a filename collision.

Whichever of the two lands second rebases, exactly as #1701's migration was
renumbered 061 -> 062 when #2019 merged first (see
``062_workflow_and_subject``'s own docstring). There is no way for both to
avoid that: ``tests/unit/test_users_phone_placeholder_cleanup.py::
test_the_cleanup_step_is_the_tail_of_the_chain`` requires the deferred step to
be the tail, so *any* new ``versions/`` revision must take over as its parent,
and both of us are adding one. This revision moves the deferred step to
``deferred/070_users_placeholder_phone_cleanup.py`` revising 069; 070 is above
068 as well as 069, so it stays the tail in either merge order.

Why ``shop_id`` is on the row, and why that is safe here
-------------------------------------------------------
Both tables hang off a run, so the obvious classification is ADR-085's
``tenant_via_parent`` (``workflow_run_events``, ``run_confirmations``): no
tenancy column, an ``EXISTS``-on-parent policy. ADR-085 rejected denormalising
the tenancy column onto a child table in as many words -- "a duplicated
tenancy fact that can drift, and a drifting tenancy fact is a cross-tenant
leak".

#1712 nonetheless specifies ``shop id`` on both tables, and it is right to:
these are read on the seller's own timeline, filtered by shop and ordered by
time, and an ``EXISTS``-on-parent policy puts a join on the hot path of the one
surface a seller looks at most. This is also the established shape here rather
than a new one -- ``tool_executions`` has carried both a ``shop_id`` FK to
``shops`` and a ``workflow_run_id`` FK to ``workflow_runs`` since migration 034
and is classified ``tenant_direct``; these two tables are built exactly like it.

The obvious way to answer ADR-085's *drift* objection outright is a composite
foreign key onto ``workflow_runs (id, shop_id)``, which would make the
duplicated fact un-driftable in the database. It is deliberately **not** here:
that FK needs a new unique constraint on ``workflow_runs``, and ``workflow_runs``
belongs to #1701/#1706/#1707/#1709, which are in flight in this same wave
(#1712's own prepared scope says so in as many words). A cross-lane
``ALTER TABLE`` on a table three other slices are editing buys a guarantee at
the cost of a merge conflict and a shared-table surprise. Recorded here as the
right follow-up for whoever next owns ``workflow_runs``; until then the drift
risk is bounded by there being no writer at all -- #1713 introduces the first
one, and is the natural place to add the constraint alongside it.

Columns, and the two the issue names that SQL cannot spell
----------------------------------------------------------
The issue lists ``when`` and ``text``. ``WHEN`` is a reserved word in
PostgreSQL and cannot be an unquoted column name, so the act's own timestamp is
``occurred_at`` -- which is the more useful name anyway, because it is *not*
``created_at``: a digest row is written when the digest is assembled and
describes something that happened earlier, and the seller's timeline sorts on
the act, not on the insert. Both columns exist. ``text`` is merely a type name
in PostgreSQL rather than a reserved word, so ``run_checklist_items.text``
survives verbatim as the issue writes it.

``otherwise`` (what would otherwise have happened) and ``undo_hint`` (how to
undo) are nullable: a completion record has no counterfactual and a digest
entry has nothing to undo, and NOT NULL here would force #1713 to invent prose
for rows that have none.

``kind``, ``state`` and ``channel`` are ``CHECK``-constrained rather than
PostgreSQL ``ENUM`` types, following ``034_workflow_runs_table``'s
``ck_workflow_runs_status``: a CHECK widens with a plain ``ALTER TABLE`` that
the additive gate accepts, where adding a value to an ENUM cannot run in the
same transaction as its use. ``channel`` admits only ``in_app`` today because
v1 has no transport (spec §8.1 P0-8: "no transport wired; FCM stub; no
email"), and the constraint is where that fact is written down rather than
assumed.

``run_checklist_items`` carries the biconditional ``done`` <-> ``done_at``:
a ticked item without a tick time loses the ledger fact S-FR-12 requires
("the tick time is in the ledger"), and a tick time on an unticked item is
meaningless. #1713's writer must set both together or neither.

The downgrade drops both tables and the unique constraint. Those are the only
destructive statements in the file and they live only in ``downgrade()``, which
the additive gate does not read -- it evaluates ``upgrade()``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "069_act_records_and_checklists"
down_revision: str | None = "065_users_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

ACT_RECORDS = "run_act_records"
CHECKLIST_ITEMS = "run_checklist_items"

#: One record per notification, reminder, automated act, digest entry, run
#: completion and run exception (#1620, "Per-act record").
ACT_KINDS = ("reminder", "digest", "automated_act", "completion", "exception")

#: Delivery lifecycle. ``pending`` is the state a record is born in; ``read`` is
#: the only one a seller's own action produces.
ACT_STATES = ("pending", "delivered", "read", "failed")

#: v1 renders in the app and nowhere else -- there is no transport to name.
ACT_CHANNELS = ("in_app",)


def _in_clause(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _enable_rls_and_policies(table: str) -> None:
    """Tenant-scope a new table exactly as migration 060 scoped ``ingest_dedup_epochs``.

    Through ``app_current_shop_id()``, never a raw ``current_setting(...)::uuid``
    (#1467, migration 050): the raw cast raises on the empty string ``SET LOCAL``
    leaves behind at commit, so migration 046's older policy shape must not be
    copied verbatim into a new table.
    """
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    for verb, clause in (
        ("SELECT", "USING (shop_id = app_current_shop_id())"),
        (
            "UPDATE",
            "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
        ),
        ("DELETE", "USING (shop_id = app_current_shop_id())"),
        ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
    ):
        # Every verb is policed even though only SELECT is granted today, so
        # that #1713's grant of INSERT/UPDATE cannot by itself open a
        # cross-tenant write -- the policy is already there and already denies.
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {clause}"
        )
    # SELECT only, deliberately: see the module docstring. #1713 adds the write
    # grants together with the call site that justifies them.
    op.execute(f"GRANT SELECT ON public.{table} TO {ROLE_NAME}")


def upgrade() -> None:
    op.create_table(
        ACT_RECORDS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("what", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("otherwise", sa.Text(), nullable=True),
        sa.Column("undo_hint", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="in_app"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name=f"fk_{ACT_RECORDS}_run"
        ),
        sa.CheckConstraint(_in_clause("kind", ACT_KINDS), name=f"ck_{ACT_RECORDS}_kind"),
        sa.CheckConstraint(_in_clause("state", ACT_STATES), name=f"ck_{ACT_RECORDS}_state"),
        sa.CheckConstraint(_in_clause("channel", ACT_CHANNELS), name=f"ck_{ACT_RECORDS}_channel"),
    )
    # The seller's timeline reads one shop's records newest-first; the run index
    # serves "everything this run did".
    op.create_index(
        f"ix_{ACT_RECORDS}_shop_occurred",
        ACT_RECORDS,
        ["shop_id", sa.text("occurred_at DESC")],
    )
    op.create_index(f"ix_{ACT_RECORDS}_run", ACT_RECORDS, ["workflow_run_id"])

    op.create_table(
        CHECKLIST_ITEMS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_by_seller", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name=f"fk_{CHECKLIST_ITEMS}_run"
        ),
        # One item per key per run: a checklist is keyed, and "place the order"
        # appearing twice on one run is a duplicate, not a second task.
        sa.UniqueConstraint("workflow_run_id", "key", name=f"uq_{CHECKLIST_ITEMS}_run_key"),
        sa.CheckConstraint("position >= 0", name=f"ck_{CHECKLIST_ITEMS}_position"),
        # S-FR-12: "the tick time is in the ledger". Ticked without a time loses
        # that fact; a time without a tick describes nothing.
        sa.CheckConstraint(
            "(done AND done_at IS NOT NULL) OR (NOT done AND done_at IS NULL)",
            name=f"ck_{CHECKLIST_ITEMS}_done_at",
        ),
    )
    op.create_index(
        f"ix_{CHECKLIST_ITEMS}_shop_run", CHECKLIST_ITEMS, ["shop_id", "workflow_run_id"]
    )
    op.create_index(
        f"uq_{CHECKLIST_ITEMS}_run_position",
        CHECKLIST_ITEMS,
        ["workflow_run_id", "position"],
        unique=True,
    )

    _enable_rls_and_policies(ACT_RECORDS)
    _enable_rls_and_policies(CHECKLIST_ITEMS)


def downgrade() -> None:
    for table in (CHECKLIST_ITEMS, ACT_RECORDS):
        op.execute(f"REVOKE ALL ON public.{table} FROM {ROLE_NAME}")

    op.drop_index(f"uq_{CHECKLIST_ITEMS}_run_position", table_name=CHECKLIST_ITEMS)
    op.drop_index(f"ix_{CHECKLIST_ITEMS}_shop_run", table_name=CHECKLIST_ITEMS)
    op.drop_table(CHECKLIST_ITEMS)

    op.drop_index(f"ix_{ACT_RECORDS}_run", table_name=ACT_RECORDS)
    op.drop_index(f"ix_{ACT_RECORDS}_shop_occurred", table_name=ACT_RECORDS)
    op.drop_table(ACT_RECORDS)

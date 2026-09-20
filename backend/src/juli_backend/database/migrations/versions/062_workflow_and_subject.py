"""runs and cards carry their workflow and their subject (#1701, ADR-087 d.1-d.3)

Revision ID: 062_workflow_and_subject
Revises: 061_credential_owner_enum
Create Date: 2026-09-16

Renumbered from 061 to 062 (#1701): 061 was independently reserved by Meta
for two concurrent slices -- this one and #2019's
061_credential_owner_enumeration.py, which merged first as #2032. This
revision now chains onto that migration instead of 060_processed_events_epoch.

One additive, expand-only migration (ADR-027) touching two tables. Nothing in
this revision is read by any application code -- #1702 and #1703 are the
first readers. This migration must be a no-op for the currently-deployed
release: every column it adds is either optional or carries a default that
reproduces exactly what an unmodified writer already meant.

**This is the EXPAND half of an expand/contract pair (#2050).** As first
merged (#2027) this revision also backfilled ``subject_ref`` per row and then
narrowed it to NOT NULL. Both statements are non-additive, and
``infra/scripts/migration_additive_gate.py`` refused every release from
2026-09-16 on because of them -- correctly: during a release the candidate and
the still-serving stable instance share one database, and a NOT NULL
``subject_ref`` stops the stable release (which does not know the column) from
inserting a ``workflow_runs`` row at all, so a code rollback would no longer
recover. The backfill and the narrowing now live in the CONTRACT step,
``063_workflow_subject_contract``, which is deliberately parked OUTSIDE
``versions/`` and operated by hand after this expand release is serving --
see that file and ``docs/runbooks/backend-deploy-runbook.md``. This revision
had never been applied to any database when it was split, so editing it in
place reconciles nothing and rewrites no applied history.

``workflow_runs`` gains three columns:

* ``workflow_key`` -- which playbook a run is executing. NOT NULL with a
  permanent server default of ``'optimize_product_2'``, the one key
  ``playbooks/__init__.py::get_registered_playbooks`` returns today. Every
  pre-existing row IS that workflow (it is the only one that has ever
  existed), and the one production writer (``approval.py``'s
  ``approve_action_card``) never names this column, so the default also
  covers every row it inserts after this migration lands, until #1702 makes
  it the first caller to pass a real value.
* ``subject_type`` -- what kind of thing the run is about. NOT NULL with a
  permanent server default of ``'product'``, the only subject kind a run has
  ever had (``product_id`` was NOT NULL before this migration).
* ``subject_ref`` -- the subject's own identifier, as text. Added NULLABLE
  with no default and no backfill, because the correct value for every
  existing row is THAT row's own ``product_id``, which a constant Postgres
  ``DEFAULT`` cannot express and a per-row ``UPDATE`` is not allowed to
  express here (see the expand/contract note above). The ORM model
  (``models.py``) still declares it NOT NULL and supplies that per-row rule
  client-side via ``_default_workflow_run_subject_ref``, so every INSERT the
  code in THIS release makes carries a real value from the moment the
  migration lands; only rows written by the older, still-serving release --
  and the rows that predate this migration -- can hold NULL, and
  ``063_workflow_subject_contract`` is what fills them and closes the column.

``workflow_runs.product_id`` widens from NOT NULL to nullable -- a relaxation,
not a narrowing, and every existing row keeps the FK value it already had.
The active-run partial unique index ``uq_workflow_runs_active_shop_product``
is re-keyed from ``(shop_id, product_id)`` to
``(shop_id, workflow_key, subject_type, subject_ref)`` over the same
non-terminal statuses, and KEEPS its name -- #1703 and #1706 already refer to
"``uq_workflow_runs_active_shop_product`` (re-keyed by #1701)". Two DIFFERENT
workflows racing the SAME product do not collide on this index by design
(ADR-087 decision 2); that cross-workflow lock is #1710's, not this one.

Between this expand step and the contract step the index does NOT constrain a
row whose ``subject_ref`` is NULL -- Postgres never treats two NULLs as equal
under a unique index. That window is bounded and narrow: only a writer that
omits the column produces such a row, which is only the older release still
serving during the rollout, and the concurrency guard it weakens protects one
seller from double-starting their own run rather than enforcing a correctness
invariant. It is the same trade-off, and the same reasoning, as the constant
defaults chosen for ``action_cards`` below -- stated here rather than left to
be discovered. Running the contract step promptly is what closes it.

``action_cards`` gains four columns (``subject_type``, ``subject_id``,
``revision``, ``supersedes_card_id``) and swaps its identity from the single
``uq_action_cards_shop_workflow`` unique on ``(shop_id, workflow_key)`` to two
constraints on the wider tuple: a full unique over
``(shop_id, workflow_key, subject_type, subject_id, revision)`` for the whole
chain, and a partial unique over the same tuple minus ``revision`` where
``status = 'active'`` -- at most one live card per subject per workflow.

Unlike a ``workflow_run``, a card has never carried a subject: the bound
product is derived server-side at APPROVAL time (ADR-082 decision 1), not at
card-generation time, so there is no per-row value to backfill or default
``subject_type``/``subject_id`` to. Both get a permanent, CONSTANT server
default (``'unscoped'`` / ``''``) instead. This is the deliberate choice
named in this issue's release-evidence plan for the one genuine coexistence
hazard here: dropping the old single-key unique while the one production
writer (``ActionCardsRepo.upsert`` via ``services/action_cards/persist.py``,
which names neither new column) still only ever produces rows with the SAME
constant ``subject_type``/``subject_id`` means the new partial unique reduces
to exactly ``(shop_id, workflow_key)`` for those rows -- the identical
collision the dropped constraint gave them. A NULL default (the alternative)
would have defeated that backstop, since Postgres never treats two NULLs as
equal under a unique index.

``revision`` defaults to ``1`` -- the first, and until #1703 writes a chain,
only revision any card has. ``supersedes_card_id`` is a nullable
self-referential FK, NULL for every existing row and for a fresh card; a
revision is a new chained ROW, never an in-place edit (ADR-087 decision 3).

The downgrade is NOT unconditional. It refuses loudly, before dropping or
narrowing anything, in the two cases the forward migration's own defaults
make possible for the first time:

* any ``workflow_runs`` row with ``product_id IS NULL`` or
  ``subject_type <> 'product'`` -- restoring the NOT NULL FK would silently
  destroy a non-product run;
* any ``(shop_id, workflow_key)`` pair in ``action_cards`` with more than one
  row -- restoring the single-key unique would be impossible without
  deleting a card.

Neither case exists on the day this migration lands (nothing yet writes a
non-product run or a second card for one workflow_key), so the downgrade
succeeds today; it is guarded because #1702/#1703 change that.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "062_workflow_and_subject"
down_revision: str | None = "061_credential_owner_enum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_RUN_STATUSES = ("queued", "running", "waiting_approval")

_WORKFLOW_RUNS_ACTIVE_INDEX = "uq_workflow_runs_active_shop_product"
_ACTION_CARDS_FULL_UNIQUE = "uq_action_cards_shop_workflow_subject_revision"
_ACTION_CARDS_ACTIVE_INDEX = "uq_action_cards_active_shop_workflow_subject"
_ACTION_CARDS_LEGACY_UNIQUE = "uq_action_cards_shop_workflow"
_ACTION_CARDS_SUPERSEDES_FK = "fk_action_cards_supersedes_card_id"


def _refuse_if_non_product_runs_exist(bind: sa.engine.Connection) -> None:
    """Downgrade guard (a): a run this migration made expressible cannot be
    represented once ``product_id`` is NOT NULL again."""
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM public.workflow_runs "
            "WHERE product_id IS NULL OR subject_type <> 'product'"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Refusing downgrade of {revision}: {count} workflow_runs row(s) carry "
            "a NULL product_id or a non-product subject_type. Restoring the NOT "
            "NULL product_id foreign key would silently destroy that data. "
            "Resolve those rows (or accept the schema stays at this revision) "
            "before downgrading."
        )


def _refuse_if_duplicate_shop_workflow_cards_exist(bind: sa.engine.Connection) -> None:
    """Downgrade guard (b): the single-key unique this migration dropped
    cannot be restored while two rows share one (shop_id, workflow_key)."""
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT shop_id, workflow_key FROM public.action_cards "
            "GROUP BY shop_id, workflow_key HAVING COUNT(*) > 1"
            ") AS duplicated_shop_workflow"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Refusing downgrade of {revision}: {count} (shop_id, workflow_key) "
            "pair(s) in action_cards now hold more than one row. Restoring "
            f"{_ACTION_CARDS_LEGACY_UNIQUE} would require deleting a card. "
            "Resolve those rows (or accept the schema stays at this revision) "
            "before downgrading."
        )


def upgrade() -> None:
    # -- workflow_runs: workflow_key, subject_type (both constant-defaulted,
    # so Postgres backfills every existing row in the same ALTER TABLE that
    # adds the column), subject_ref (nullable here; no constant is true and a
    # per-row backfill is the contract step's job -- 063, run by hand).
    op.add_column(
        "workflow_runs",
        sa.Column(
            "workflow_key",
            sa.String(length=64),
            nullable=False,
            server_default="optimize_product_2",
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "subject_type",
            sa.String(length=32),
            nullable=False,
            server_default="product",
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("subject_ref", sa.String(length=64), nullable=True),
    )

    # product_id widens: NOT NULL -> nullable. A relaxation, not a narrowing.
    op.alter_column(
        "workflow_runs",
        "product_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    # Re-key the active-run partial unique index; keep its name.
    op.drop_index(_WORKFLOW_RUNS_ACTIVE_INDEX, table_name="workflow_runs")
    op.create_index(
        _WORKFLOW_RUNS_ACTIVE_INDEX,
        "workflow_runs",
        ["shop_id", "workflow_key", "subject_type", "subject_ref"],
        unique=True,
        postgresql_where=sa.text(
            "status IN (" + ", ".join(repr(s) for s in _ACTIVE_RUN_STATUSES) + ")"
        ),
    )

    # -- action_cards: subject_type/subject_id (both constant-defaulted, same
    # reasoning as above), revision (constant-defaulted), supersedes_card_id
    # (nullable self-FK, no default).
    op.add_column(
        "action_cards",
        sa.Column(
            "subject_type",
            sa.String(length=32),
            nullable=False,
            server_default="unscoped",
        ),
    )
    op.add_column(
        "action_cards",
        sa.Column(
            "subject_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "action_cards",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "action_cards",
        sa.Column("supersedes_card_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        _ACTION_CARDS_SUPERSEDES_FK,
        "action_cards",
        "action_cards",
        ["supersedes_card_id"],
        ["id"],
    )

    # Swap the identity: drop the single-key unique, add the full chain
    # unique plus the partial "one live card per subject" unique.
    op.drop_constraint(_ACTION_CARDS_LEGACY_UNIQUE, "action_cards", type_="unique")
    op.create_unique_constraint(
        _ACTION_CARDS_FULL_UNIQUE,
        "action_cards",
        ["shop_id", "workflow_key", "subject_type", "subject_id", "revision"],
    )
    op.create_index(
        _ACTION_CARDS_ACTIVE_INDEX,
        "action_cards",
        ["shop_id", "workflow_key", "subject_type", "subject_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # action_cards first (reverse of upgrade order): refuse before touching
    # anything if the old single-key unique can no longer be represented.
    _refuse_if_duplicate_shop_workflow_cards_exist(bind)
    op.drop_index(_ACTION_CARDS_ACTIVE_INDEX, table_name="action_cards")
    op.drop_constraint(_ACTION_CARDS_FULL_UNIQUE, "action_cards", type_="unique")
    op.create_unique_constraint(
        _ACTION_CARDS_LEGACY_UNIQUE, "action_cards", ["shop_id", "workflow_key"]
    )
    op.drop_constraint(_ACTION_CARDS_SUPERSEDES_FK, "action_cards", type_="foreignkey")
    op.drop_column("action_cards", "supersedes_card_id")
    op.drop_column("action_cards", "revision")
    op.drop_column("action_cards", "subject_id")
    op.drop_column("action_cards", "subject_type")

    # workflow_runs: refuse before restoring the NOT NULL FK if a non-product
    # run now exists.
    _refuse_if_non_product_runs_exist(bind)
    op.drop_index(_WORKFLOW_RUNS_ACTIVE_INDEX, table_name="workflow_runs")
    op.alter_column(
        "workflow_runs",
        "product_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_index(
        _WORKFLOW_RUNS_ACTIVE_INDEX,
        "workflow_runs",
        ["shop_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN (" + ", ".join(repr(s) for s in _ACTIVE_RUN_STATUSES) + ")"
        ),
    )
    op.drop_column("workflow_runs", "subject_ref")
    op.drop_column("workflow_runs", "subject_type")
    op.drop_column("workflow_runs", "workflow_key")

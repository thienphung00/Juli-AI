"""give the ETL dedup ledger an epoch so lost rows can be re-ingested (#1968)

`processed_events` was a permanent, unbounded ledger keyed on `event_id` alone.
When the destination table lost its rows — a wipe, a failed migration, a
rollback — the ledger still claimed those events were processed, so they could
never be re-ingested: the reference shop showed `orders` = 0 while the vendor
API served 3,581 orders over 90 days. Resetting the watermark cannot recover
that history, because the watermark controls what is *fetched* and the ledger
controls what is *persisted*.

This revision is the expand step (ADR-027), and it is expand-only on purpose —
during a release the candidate and the still-serving stable release share this
database:

* `processed_events.epoch` arrives NOT NULL with `SERVER_DEFAULT 0`, so every
  existing row resolves to epoch 0 and every insert the *stable* release makes
  (it does not know the column) also lands on epoch 0. Its dedup verdict is
  unchanged.
* The primary key widens from `(event_id)` to `(event_id, epoch)`. Widening a
  key *relaxes* uniqueness rather than narrowing it, and since the stable
  release only ever writes epoch 0, a repeated `event_id` still collides and
  still raises the `IntegrityError` its claim path depends on.
* `ingest_dedup_epochs` is created **empty**. A missing row means epoch 0, so
  applying this migration, importing the ETL package and starting a worker all
  leave every channel exactly where it was. Nothing here writes an epoch, and
  nothing may: an epoch that moved on deploy would re-ingest all history on
  every release. It moves only through `IngestDedupEpochsRepo.advance`, which
  refuses to run without an operator and a reason and records both.

Clearing or deleting ledger rows is deliberately *not* the mechanism: a DELETE
is irreversible and would destroy the only record of what was ingested and
when. An epoch is additive — the old rows stay, and the recovery is auditable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "060_processed_events_epoch"
down_revision: str | None = "059_webhook_raw_events_select"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
EPOCH_TABLE = "ingest_dedup_epochs"
LEDGER_PK = "processed_events_pkey"


def _enable_rls_and_policies() -> None:
    """Tenant-scope the new table the same way migration 046 scoped the ledger."""
    op.execute(f"ALTER TABLE public.{EPOCH_TABLE} ENABLE ROW LEVEL SECURITY")
    # Through `app_current_shop_id()`, never a raw `current_setting(...)::uuid`
    # (#1467, migration 050): the raw cast raises on the empty string that
    # `SET LOCAL` leaves behind at commit. Migration 046's policies predate the
    # helper, so copying its shape verbatim would reintroduce that bug.
    for verb, clause in (
        ("SELECT", "USING (shop_id = app_current_shop_id())"),
        (
            "UPDATE",
            "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
        ),
        ("DELETE", "USING (shop_id = app_current_shop_id())"),
        ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
    ):
        # Policies cover every verb so a future grant cannot leak across tenants;
        # the grant below is what actually limits juli_app to reading.
        policy = f"{EPOCH_TABLE}_{verb.lower()}_public"
        op.execute(  # nosec B608 — table, verb and clause are fixed module constants
            f"CREATE POLICY {policy} ON public.{EPOCH_TABLE} FOR {verb} {clause}"
        )
    # SELECT only, deliberately. `EtlConsumer` reads an epoch on every ingest;
    # advancing one is an operator action run as the owner. Withholding INSERT
    # and UPDATE means the runtime role *cannot* move an epoch even by accident,
    # which is the same guarantee this migration makes in code, enforced by the
    # database. Granting more would also fail
    # `test_no_public_table_holds_update_beyond_its_call_site`: there is no
    # application call site that mutates this table.
    op.execute(f"GRANT SELECT ON public.{EPOCH_TABLE} TO {ROLE_NAME}")


def upgrade() -> None:
    op.add_column(
        "processed_events",
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
    )

    # Widen the ledger's key so one event_id can be claimed once per epoch.
    op.drop_constraint(LEDGER_PK, "processed_events", type_="primary")
    op.create_primary_key(LEDGER_PK, "processed_events", ["event_id", "epoch"])

    op.create_table(
        EPOCH_TABLE,
        sa.Column("shop_id", sa.UUID(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("advanced_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("advanced_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", "channel"),
    )
    op.create_index(f"ix_{EPOCH_TABLE}_shop", EPOCH_TABLE, ["shop_id"])

    _enable_rls_and_policies()


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON public.{EPOCH_TABLE} FROM {ROLE_NAME}")
    op.drop_index(f"ix_{EPOCH_TABLE}_shop", table_name=EPOCH_TABLE)
    op.drop_table(EPOCH_TABLE)

    # Only reversible while no epoch has been advanced: past epoch 0 the ledger
    # legitimately holds the same event_id more than once, and a single-column
    # key can no longer describe it. That is the point at which the recovery it
    # records must not be silently undone.
    op.drop_constraint(LEDGER_PK, "processed_events", type_="primary")
    op.create_primary_key(LEDGER_PK, "processed_events", ["event_id"])
    op.drop_column("processed_events", "epoch")

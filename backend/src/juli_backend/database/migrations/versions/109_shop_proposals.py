"""Shopee manual cycle: proposals, approvals, executions and results (ADR-118)

Revision ID: 109_shop_proposals
Revises: 108_shopee_ops_data
Create Date: 2026-11-02

Four CLIENT-LANE tables, tenant-direct (``shop_id``, RLS by ``app_current_shop_id()``):
the client's representative reads and approves proposals, so they are tenant rows
(ADR-116), not Ops-only. Forecasts and expected effects stay in the Ops-only
``lever_plans`` / ``kpi_forecasts`` (D42 G4); ``lever_plan_id`` and the staff ids are
plain uuids, not foreign keys into Ops-only tables.

- ``shop_proposals`` -- one change an operator proposes for a platform item, the shop
  or a campaign. ``juli_app`` SELECT, INSERT, UPDATE (status moves forward).
- ``shop_proposal_approvals`` -- append-only: the client's decision, in the app or
  recorded by an operator from an email / document (``evidence_ref`` required then),
  with the verbatim proposal the client saw. SELECT, INSERT.
- ``shop_proposal_executions`` -- the change made on the shop: a role or a Juli user
  id, never a name. SELECT, INSERT, and UPDATE on the three ``verified_*`` columns only
  (the read-back from the next export).
- ``shop_proposal_results`` -- append-only measurement rows; the reader takes the
  latest ``computed_at``. SELECT, INSERT.

EXPAND-ONLY AND REVERSIBLE. Tables, indexes, policies and grants; no data change.
``downgrade`` drops them. The deferred write-mode backfill (and the phone cleanup
under it) is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "109_shop_proposals"
down_revision: str | None = "108_shopee_ops_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
PROPOSALS_TABLE = "shop_proposals"
APPROVALS_TABLE = "shop_proposal_approvals"
EXECUTIONS_TABLE = "shop_proposal_executions"
RESULTS_TABLE = "shop_proposal_results"
PROPOSAL_FK = f"{PROPOSALS_TABLE}.id"

#: Written out rather than imported from the models: a migration must not change when
#: the model does. ``tests/unit/test_shop_proposals_schema.py`` pins them equal.
PLATFORMS = ("tiktok", "shopee")
KINDS = (
    "title",
    "images",
    "price",
    "voucher",
    "flash_sale",
    "ads",
    "bundle",
    "program",
    "stock",
    "other",
)
SUBJECT_TYPES = ("item", "shop", "campaign")
STATUSES = (
    "draft",
    "sent",
    "approved",
    "rejected",
    "changes_requested",
    "executed",
    "measured",
    "withdrawn",
    "superseded",
)
DECISIONS = ("approved", "rejected", "changes_requested")
APPROVAL_CHANNELS = ("in_app", "email", "document")
EXECUTOR_ROLES = ("client_representative", "juli_operator", "platform_api")
EXECUTION_CHANNELS = ("ops", "in_app", "api")
VERIFIED_HOW = ("export_readback", "sub_account_read", "api")
METHODS = ("pre_post_vs_untested", "contract_kpi")
VERDICTS = ("dat", "khong_dat", "chua_ket_luan")

APPEND_ONLY_VERBS = "SELECT, INSERT"

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}

#: Table -> (verbs with a policy, the GRANT statement's privilege list).
TENANT_GRANTS: dict[str, tuple[str, str]] = {
    PROPOSALS_TABLE: ("SELECT, INSERT, UPDATE", "SELECT, INSERT, UPDATE"),
    APPROVALS_TABLE: (APPEND_ONLY_VERBS, APPEND_ONLY_VERBS),
    EXECUTIONS_TABLE: (
        "SELECT, INSERT, UPDATE",
        "SELECT, INSERT, UPDATE (verified_at, verified_how, verified_state)",
    ),
    RESULTS_TABLE: (APPEND_ONLY_VERBS, APPEND_ONLY_VERBS),
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _shop_column() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def _create_proposals() -> None:
    op.create_table(
        PROPOSALS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("cycle", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("subject_label", sa.String(length=255), nullable=False),
        sa.Column("change_before", postgresql.JSONB(), nullable=False),
        sa.Column("change_after", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("revision", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey(PROPOSAL_FK), nullable=True),
        sa.Column("lever_plan_id", sa.Uuid(), nullable=True),
        sa.Column("proposed_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PROPOSALS_TABLE}"),
        sa.CheckConstraint(
            f"platform IN ({_in(PLATFORMS)})", name=f"ck_{PROPOSALS_TABLE}_platform"
        ),
        sa.CheckConstraint(f"kind IN ({_in(KINDS)})", name=f"ck_{PROPOSALS_TABLE}_kind"),
        sa.CheckConstraint(
            f"subject_type IN ({_in(SUBJECT_TYPES)})", name=f"ck_{PROPOSALS_TABLE}_subject_type"
        ),
        sa.CheckConstraint(
            "(subject_type = 'item') = (item_id IS NOT NULL)", name=f"ck_{PROPOSALS_TABLE}_item"
        ),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name=f"ck_{PROPOSALS_TABLE}_status"),
        sa.CheckConstraint("revision >= 1", name=f"ck_{PROPOSALS_TABLE}_revision"),
    )
    op.create_index(f"ix_{PROPOSALS_TABLE}_shop_cycle", PROPOSALS_TABLE, ["shop_id", "cycle"])
    op.create_index(f"ix_{PROPOSALS_TABLE}_shop_status", PROPOSALS_TABLE, ["shop_id", "status"])


def _proposal_column() -> sa.Column:
    return sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey(PROPOSAL_FK), nullable=False)


def _create_approvals() -> None:
    op.create_table(
        APPROVALS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        _proposal_column(),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("recorded_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("proposal_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{APPROVALS_TABLE}"),
        sa.CheckConstraint(
            f"decision IN ({_in(DECISIONS)})", name=f"ck_{APPROVALS_TABLE}_decision"
        ),
        sa.CheckConstraint(
            f"channel IN ({_in(APPROVAL_CHANNELS)})", name=f"ck_{APPROVALS_TABLE}_channel"
        ),
        sa.CheckConstraint(
            "(channel = 'in_app' AND decided_by_user_id IS NOT NULL) OR "
            "(channel <> 'in_app' AND recorded_by_staff_id IS NOT NULL "
            "AND evidence_ref IS NOT NULL)",
            name=f"ck_{APPROVALS_TABLE}_who",
        ),
    )
    op.create_index(f"ix_{APPROVALS_TABLE}_proposal", APPROVALS_TABLE, ["proposal_id"])


def _create_executions() -> None:
    op.create_table(
        EXECUTIONS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        _proposal_column(),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("executor_role", sa.String(length=32), nullable=False),
        sa.Column("executed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("recorded_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_how", sa.String(length=24), nullable=True),
        sa.Column("verified_state", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{EXECUTIONS_TABLE}"),
        sa.CheckConstraint(
            f"executor_role IN ({_in(EXECUTOR_ROLES)})", name=f"ck_{EXECUTIONS_TABLE}_role"
        ),
        sa.CheckConstraint(
            f"channel IN ({_in(EXECUTION_CHANNELS)})", name=f"ck_{EXECUTIONS_TABLE}_channel"
        ),
        sa.CheckConstraint(
            f"verified_how IS NULL OR verified_how IN ({_in(VERIFIED_HOW)})",
            name=f"ck_{EXECUTIONS_TABLE}_verified_how",
        ),
        sa.CheckConstraint(
            "executor_role = 'platform_api' OR recorded_by_staff_id IS NOT NULL "
            "OR recorded_by_user_id IS NOT NULL",
            name=f"ck_{EXECUTIONS_TABLE}_recorded_by",
        ),
        sa.CheckConstraint(
            "(verified_at IS NULL) = (verified_how IS NULL)",
            name=f"ck_{EXECUTIONS_TABLE}_verified",
        ),
    )
    op.create_index(f"ix_{EXECUTIONS_TABLE}_proposal", EXECUTIONS_TABLE, ["proposal_id"])


def _create_results() -> None:
    op.create_table(
        RESULTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        _proposal_column(),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("pre_from", sa.Date(), nullable=True),
        sa.Column("pre_to", sa.Date(), nullable=True),
        sa.Column("post_from", sa.Date(), nullable=True),
        sa.Column("post_to", sa.Date(), nullable=True),
        sa.Column("value", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("comparison", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("band", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("data_through", sa.Date(), nullable=True),
        sa.Column("job_version", sa.String(length=32), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{RESULTS_TABLE}"),
        sa.CheckConstraint(f"method IN ({_in(METHODS)})", name=f"ck_{RESULTS_TABLE}_method"),
        sa.CheckConstraint(f"verdict IN ({_in(VERDICTS)})", name=f"ck_{RESULTS_TABLE}_verdict"),
    )
    op.create_index(f"ix_{RESULTS_TABLE}_proposal", RESULTS_TABLE, ["proposal_id", "computed_at"])


def _secure_tenant(table: str, policy_verbs: str, grant: str) -> None:
    """RLS on, one policy per verb, and the ``juli_app`` grant (108's shape)."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
    for verb in (v.strip() for v in policy_verbs.split(",")):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {_CLAUSES[verb]}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {grant} ON public.{table} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def upgrade() -> None:
    _create_proposals()
    _create_approvals()
    _create_executions()
    _create_results()
    for table, (policy_verbs, grant) in TENANT_GRANTS.items():
        _secure_tenant(table, policy_verbs, grant)


def downgrade() -> None:
    for table in TENANT_GRANTS:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    # Children before the parent.
    for table in (RESULTS_TABLE, EXECUTIONS_TABLE, APPROVALS_TABLE, PROPOSALS_TABLE):
        op.drop_table(table)

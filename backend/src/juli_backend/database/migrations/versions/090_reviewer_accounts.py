"""Partner reviewer trial accounts (fast track P32-A).

Revision ID: 090_reviewer_accounts
Revises: 089_card_groups
Create Date: 2026-10-14

DECISIONS D42; contract ``fasttrack/contracts/p32-reviewer-access.md``.

WHAT IT ADDS. One ops table, ``ops_reviewer_accounts``: a partner platform's
reviewer (e.g. Shopee's ISV review team) signs in with a team-created e-mail +
password and reads the reference shop masked; approval and execution are only
simulated. One row per account: platform label, ``expires_at`` (default 30
days, set by the provisioning command), ``revoked_at``, and the last Supabase
session seen (so each sign-in is audited once).

Like every 083 ops table it is NOT a tenant table: RLS is on, the only policy is
``FOR ALL TO juli_ops``, and ``juli_app`` (the seller role), ``anon`` and
``authenticated`` get no grant -- a seller request cannot read, create, extend
or un-revoke a reviewer account. Classified ``ops_only`` in
``database/tenant_scoped_tables.py``. Nothing is deleted (SELECT, INSERT,
UPDATE): revoking keeps the row.

EXPAND-ONLY AND REVERSIBLE. One new table; ``downgrade`` drops it. The deferred
phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090_reviewer_accounts"
down_revision: str | None = "089_card_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
TABLE = "ops_reviewer_accounts"
VERBS = "SELECT, INSERT, UPDATE"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="reviewer"),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_session_id", sa.String(length=64), nullable=True),
        sa.Column("last_sign_in_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reviewer_accounts"),
        sa.UniqueConstraint("user_id", name="uq_ops_reviewer_accounts_user_id"),
        sa.UniqueConstraint("email", name="uq_ops_reviewer_accounts_email"),
        sa.CheckConstraint("role IN ('reviewer')", name="ck_ops_reviewer_accounts_role"),
        sa.CheckConstraint("email = lower(email)", name="ck_ops_reviewer_accounts_email_lower"),
        sa.CheckConstraint(
            "platform = lower(platform) AND length(platform) > 0",
            name="ck_ops_reviewer_accounts_platform",
        ),
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TABLE}_ops_only ON public.{TABLE} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON public.{TABLE} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {VERBS} ON public.{TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_ops_only ON public.{TABLE}")
    op.drop_table(TABLE)

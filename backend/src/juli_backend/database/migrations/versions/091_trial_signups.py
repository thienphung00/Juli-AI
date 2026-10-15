"""Free-trial sign-ups from app-juli.com/dang-ky (fast track P33-F).

Revision ID: 091_trial_signups
Revises: 090_reviewer_accounts
Create Date: 2026-10-15

DECISIONS D43 (owner, 2026-10-15: a fast free-trial sign-up form); AC-33.11.

WHAT IT ADDS. One table, ``trial_signups``: the form's fields (name, phone /
Zalo, e-mail, shop name or link, role, optional note), the consent time, the
source (utm / referrer), an HMAC of the visitor's IP (never the address), and
the team's follow-up (status new / contacted / converted / spam, handled_by,
handled_at).

Like every 083 ops table it is NOT a tenant table: RLS is on, the only policy is
``FOR ALL TO juli_ops``, and ``juli_app`` (the seller/runtime role), ``anon`` and
``authenticated`` get no grant. The public endpoint and the Ops console both
reach it through ``SET LOCAL ROLE juli_ops`` (``services/ops/access.ops_role``).
Classified ``ops_only`` in ``database/tenant_scoped_tables.py``. ``juli_ops``
gets SELECT, INSERT, UPDATE and DELETE (deletion on request, privacy policy).

EXPAND-ONLY AND REVERSIBLE. One new table; ``downgrade`` drops it. The deferred
phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "091_trial_signups"
down_revision: str | None = "090_reviewer_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
TABLE = "trial_signups"
VERBS = "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("shop", sa.String(length=300), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("consent_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("handled_by", sa.String(length=320), nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_trial_signups"),
        sa.CheckConstraint(
            "role IN ('seller', 'affiliate', 'shop_operator', 'agency')",
            name="ck_trial_signups_role",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'converted', 'spam')",
            name="ck_trial_signups_status",
        ),
        sa.CheckConstraint("email = lower(email)", name="ck_trial_signups_email_lower"),
    )
    op.create_index("ix_trial_signups_created_at", TABLE, ["created_at"])
    op.create_index("ix_trial_signups_email_created_at", TABLE, ["email", "created_at"])
    op.create_index("ix_trial_signups_ip_hash_created_at", TABLE, ["ip_hash", "created_at"])
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
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM anon';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM authenticated';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {VERBS} ON public.{TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_ops_only ON public.{TABLE}")
    op.drop_index("ix_trial_signups_ip_hash_created_at", table_name=TABLE)
    op.drop_index("ix_trial_signups_email_created_at", table_name=TABLE)
    op.drop_index("ix_trial_signups_created_at", table_name=TABLE)
    op.drop_table(TABLE)

"""Juli Ops: system OpenAI limit, shop subscription periods (fast track P20).

Revision ID: 086_ops_cost_and_terms
Revises: 085_ops_daily_precompute
Create Date: 2026-10-12

DECISIONS D28.3 (tab Chi phí), D28.4 (tab Thời hạn), D28.5 (payment-ready grant).

WHAT IT ADDS.

- ``shop_subscription_periods`` (D28.4): one row per granted period -- shop,
  plan (``month`` | ``year``), ``days`` (30 | 365), ``starts_on`` / ``ends_on``,
  ``source`` (``contract`` from Juli Ops, ``payment`` from the future payment
  system), ``reference`` (contract no. / payment id, UNIQUE per source -- the
  grant is idempotent on it, D28.5), the actor. Expiry = the latest
  ``ends_on``. A tenant table like 085's: RLS on, one policy per verb through
  ``app_current_shop_id()``; ``juli_app`` gets SELECT, INSERT only -- the
  history is append-only (no UPDATE / DELETE grant). Ops writes it under the
  shop's own scope, like the shop's rules.
- ``ops_system_settings`` (D28.3): system-wide key → JSON value
  (``openai_system_cap_usd``, ``openai_alert_sent``). Holds no shop data: RLS
  on, ``FOR ALL TO juli_ops`` plus ``FOR SELECT TO juli_app USING (true)`` (the
  OpenAI gates read the system cap on the seller / worker paths). Grants:
  ``juli_ops`` every verb, ``juli_app`` SELECT.
- ``openai_spend_since(timestamp)`` (D28.3): the OpenAI spend of ALL shops since
  an instant -- ``workflow_runs.cost_usd`` + ``content_analyses.cost_usd`` by
  ``created_at`` (the same columns as ``openai_cap.openai_spend_this_month``).
  SECURITY DEFINER (ADR-089 shape, fixed SQL, ``search_path`` pinned) because a
  tenant-scoped session sees only its own shop's rows; it returns one number,
  no shop data. EXECUTE to ``juli_app`` and ``juli_ops`` only.

EXPAND-ONLY AND REVERSIBLE. Two new tables, one function, policies and grants;
no data change (the system cap's default comes from
``OPENAI_SYSTEM_CAP_USD_DEFAULT`` until an Admin saves one). ``downgrade``
drops them. The deferred phone-cleanup step is re-parented onto this revision
so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "086_ops_cost_and_terms"
down_revision: str | None = "085_ops_daily_precompute"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
PERIODS_TABLE = "shop_subscription_periods"
#: Append-only history: no UPDATE, no DELETE.
PERIODS_VERBS = "SELECT, INSERT"
SYSTEM_TABLE = "ops_system_settings"
SYSTEM_OPS_VERBS = "SELECT, INSERT, UPDATE, DELETE"
SYSTEM_APP_VERBS = "SELECT"
SPEND_FN = "public.openai_spend_since(timestamp)"


def _create_periods() -> None:
    op.create_table(
        PERIODS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shop_subscription_periods"),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name="fk_shop_subscription_periods_shop"
        ),
        sa.UniqueConstraint("source", "reference", name="uq_shop_subscription_periods_ref"),
        sa.CheckConstraint("plan IN ('month', 'year')", name="ck_shop_subscription_periods_plan"),
        sa.CheckConstraint("days IN (30, 365)", name="ck_shop_subscription_periods_days"),
        sa.CheckConstraint(
            "source IN ('contract', 'payment')", name="ck_shop_subscription_periods_source"
        ),
    )
    op.create_index("ix_shop_subscription_periods_shop_ends", PERIODS_TABLE, ["shop_id", "ends_on"])
    op.execute(f"ALTER TABLE public.{PERIODS_TABLE} ENABLE ROW LEVEL SECURITY")
    for verb, clause in (
        ("SELECT", "USING (shop_id = app_current_shop_id())"),
        ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
    ):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {PERIODS_TABLE}_{verb.lower()}_public ON public.{PERIODS_TABLE} "
            f"FOR {verb} {clause}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {PERIODS_VERBS} ON public.{PERIODS_TABLE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _create_system_settings() -> None:
    op.create_table(
        SYSTEM_TABLE,
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.PrimaryKeyConstraint("key", name="pk_ops_system_settings"),
    )
    op.execute(f"ALTER TABLE public.{SYSTEM_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {SYSTEM_TABLE}_ops_all ON public.{SYSTEM_TABLE} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {SYSTEM_TABLE}_app_select ON public.{SYSTEM_TABLE} "
        f"FOR SELECT TO {APP_ROLE} USING (true)"
    )
    op.execute(f"REVOKE ALL ON public.{SYSTEM_TABLE} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {SYSTEM_APP_VERBS} ON public.{SYSTEM_TABLE} TO {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {SYSTEM_OPS_VERBS} ON public.{SYSTEM_TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _create_spend_function() -> None:
    """The month's OpenAI spend of every shop: one number, no shop data."""
    op.execute("""
    CREATE OR REPLACE FUNCTION public.openai_spend_since(p_since timestamp)
    RETURNS numeric
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT
            COALESCE((SELECT SUM(r.cost_usd) FROM public.workflow_runs r
                      WHERE r.created_at >= p_since), 0)
          + COALESCE((SELECT SUM(a.cost_usd) FROM public.content_analyses a
                      WHERE a.created_at >= p_since), 0)
    $fn$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SPEND_FN} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {SPEND_FN} TO {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {SPEND_FN} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_periods()
    _create_system_settings()
    _create_spend_function()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SPEND_FN}")
    op.drop_table(SYSTEM_TABLE)
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{PERIODS_TABLE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_index("ix_shop_subscription_periods_shop_ends", table_name=PERIODS_TABLE)
    op.drop_table(PERIODS_TABLE)

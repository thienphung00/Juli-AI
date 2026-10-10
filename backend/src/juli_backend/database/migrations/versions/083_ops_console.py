"""Juli Ops console: staff, audit, per-shop overrides, scenarios, invites (fast track P16).

Revision ID: 083_ops_console
Revises: 081_order_cost_data
Create Date: 2026-10-10

DECISIONS D25 (items 1-10); contract ``fasttrack/contracts/p16-ops.md``.

WHAT IT ADDS.

- Role ``juli_ops`` (NOLOGIN, no BYPASSRLS). The ops path (``/v1/ops/*`` and the
  seller's invite accept) does ``SET LOCAL ROLE juli_ops`` around every read or
  write of an ops table. It is granted to every LOGIN role that is already a
  member of ``juli_app`` (the runtime's login), so the switch works on the
  deployed host with no owner step.
- Five ops tables (``ops_staff``, ``ops_audit_log``, ``ops_shop_settings``,
  ``ops_sim_scenarios``, ``ops_shop_invites``). NOT tenant tables: RLS is on,
  the only policy is ``FOR ALL TO juli_ops``, and ``juli_app`` (the seller
  role), ``anon`` and ``authenticated`` get no grant. Classified ``ops_only``
  in ``database/tenant_scoped_tables.py``. ``ops_audit_log`` is append-only
  (SELECT, INSERT).
- ``users.staff_access_consent_at`` (D25.6): when the seller accepted staff
  access "to support and operate the service" on the connect-shop screen.
  ``juli_app`` may UPDATE that one column (its own row, by the existing policy).
- There is NO act-for-seller state (D25.3 amended 2026-10-10: "Xem như shop"
  is always read-only; staff change a shop only through these overrides).
- Three SECURITY DEFINER functions (ADR-089 shape: fixed SQL, ``out_`` columns,
  EXECUTE revoked from PUBLIC):
  * ``ops_current_shop_overrides()`` -- the override row of
    ``app_current_shop_id()`` only, for the seller/worker paths that must honour
    it (card limits, streams, actions, content, promotion API, model, cap).
    EXECUTE to ``juli_app`` and ``juli_ops``. Carries no personal data.
  * ``ops_list_shops()`` -- every shop with its owner's id, e-mail and consent
    time, for the overview. EXECUTE to ``juli_ops`` only (seller e-mails are
    masked in every ops response).
  * ``ops_transfer_shop(shop, new_owner)`` -- the P9-B handover. EXECUTE to
    ``juli_ops`` only; called after the invite token, its expiry and the
    accepting user's verified e-mail were checked.

EXPAND-ONLY AND REVERSIBLE. New role, tables, one nullable column, functions.
``downgrade`` drops the functions, tables and column and revokes the role's
memberships (the role itself is cluster-wide and is left in place, like 043).
The deferred phone-cleanup step is re-parented onto this revision so it stays
the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "083_ops_console"
down_revision: str | None = "081_order_cost_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"

#: table -> the verbs juli_ops needs.
OPS_GRANTS: dict[str, str] = {
    "ops_staff": "SELECT, INSERT, UPDATE",
    "ops_audit_log": "SELECT, INSERT",
    "ops_shop_settings": "SELECT, INSERT, UPDATE, DELETE",
    "ops_sim_scenarios": "SELECT, INSERT, UPDATE, DELETE",
    "ops_shop_invites": "SELECT, INSERT, UPDATE",
}

_FUNCTIONS = (
    "public.ops_current_shop_overrides()",
    "public.ops_list_shops()",
    "public.ops_transfer_shop(uuid, uuid)",
)


def _create_role() -> None:
    op.execute(f"""
    DO $$
    DECLARE member record;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            CREATE ROLE {OPS_ROLE} NOLOGIN NOBYPASSRLS;
        END IF;
        EXECUTE 'GRANT USAGE ON SCHEMA public TO {OPS_ROLE}';
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            FOR member IN
                SELECT r.rolname
                FROM pg_auth_members m
                JOIN pg_roles g ON g.oid = m.roleid
                JOIN pg_roles r ON r.oid = m.member
                WHERE g.rolname = '{APP_ROLE}' AND r.rolcanlogin
            LOOP
                EXECUTE format('GRANT {OPS_ROLE} TO %I', member.rolname);
            END LOOP;
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed role names


def _create_tables() -> None:
    op.create_table(
        "ops_staff",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ops_staff"),
        sa.UniqueConstraint("user_id", name="uq_ops_staff_user_id"),
        sa.UniqueConstraint("email", name="uq_ops_staff_email"),
        sa.CheckConstraint("role IN ('viewer', 'operator', 'admin')", name="ck_ops_staff_role"),
        sa.CheckConstraint("email = lower(email)", name="ck_ops_staff_email_lower"),
    )
    op.create_table(
        "ops_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_staff_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("for_seller", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ops_audit_log"),
        sa.ForeignKeyConstraint(
            ["actor_staff_id"], ["ops_staff.id"], name="fk_ops_audit_log_actor"
        ),
    )
    op.create_index("ix_ops_audit_log_shop_at", "ops_audit_log", ["shop_id", "at"])
    op.create_table(
        "ops_shop_settings",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False, server_default="trial"),
        sa.Column("card_daily_limit", sa.Integer(), nullable=True),
        sa.Column("card_weekly_limit", sa.Integer(), nullable=True),
        sa.Column("card_open_limit", sa.Integer(), nullable=True),
        sa.Column("enabled_streams", sa.JSON(), nullable=True),
        sa.Column("enabled_actions", sa.JSON(), nullable=True),
        sa.Column("content_cards_enabled", sa.Boolean(), nullable=True),
        sa.Column("promotion_api_enabled", sa.Boolean(), nullable=True),
        sa.Column("openai_model", sa.String(length=64), nullable=True),
        sa.Column("openai_monthly_cap_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name="pk_ops_shop_settings"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ops_shop_settings_shop"),
        sa.CheckConstraint(
            "stage IN ('trial', 'self', 'pilot')", name="ck_ops_shop_settings_stage"
        ),
    )
    op.create_table(
        "ops_sim_scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("deltas", sa.JSON(), nullable=False),
        sa.Column("is_target", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sim_scenarios"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ops_sim_scenarios_shop"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["ops_staff.id"], name="fk_ops_sim_scenarios_created_by"
        ),
    )
    op.create_index("ix_ops_sim_scenarios_shop_id", "ops_sim_scenarios", ["shop_id"])
    op.create_index(
        "uq_ops_sim_scenarios_one_target",
        "ops_sim_scenarios",
        ["shop_id"],
        unique=True,
        postgresql_where=sa.text("is_target"),
        sqlite_where=sa.text("is_target"),
    )
    op.create_table(
        "ops_shop_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("keep_ops_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_user_id", sa.Uuid(), nullable=True),
        sa.Column("seller_kept_ops_access", sa.Boolean(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ops_shop_invites"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ops_shop_invites_shop"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["ops_staff.id"], name="fk_ops_shop_invites_created_by"
        ),
        sa.UniqueConstraint("token_hash", name="uq_ops_shop_invites_token_hash"),
    )
    op.create_index("ix_ops_shop_invites_shop_id", "ops_shop_invites", ["shop_id"])


def _lock_down_tables() -> None:
    for table, verbs in OPS_GRANTS.items():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(  # nosec B608 - fixed module constants
            f"CREATE POLICY {table}_ops_only ON public.{table} FOR ALL TO {OPS_ROLE} "
            "USING (true) WITH CHECK (true)"
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
            EXECUTE 'GRANT {verbs} ON public.{table} TO {OPS_ROLE}';
        END
        $$;
        """)  # nosec B608


def _consent_column() -> None:
    op.add_column("users", sa.Column("staff_access_consent_at", sa.DateTime(), nullable=True))
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT UPDATE (staff_access_consent_at) ON public.users TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _create_functions() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_current_shop_overrides()
    RETURNS TABLE (
        out_shop_id uuid,
        out_stage varchar,
        out_card_daily_limit integer,
        out_card_weekly_limit integer,
        out_card_open_limit integer,
        out_enabled_streams json,
        out_enabled_actions json,
        out_content_cards_enabled boolean,
        out_promotion_api_enabled boolean,
        out_openai_model varchar,
        out_openai_monthly_cap_usd numeric
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT s.shop_id, s.stage, s.card_daily_limit, s.card_weekly_limit,
               s.card_open_limit, s.enabled_streams, s.enabled_actions,
               s.content_cards_enabled, s.promotion_api_enabled, s.openai_model,
               s.openai_monthly_cap_usd
        FROM public.ops_shop_settings s
        WHERE s.shop_id = public.app_current_shop_id()
    $fn$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_list_shops()
    RETURNS TABLE (
        out_shop_id uuid,
        out_shop_name varchar,
        out_tiktok_shop_id varchar,
        out_is_active boolean,
        out_created_at timestamp,
        out_owner_user_id uuid,
        out_owner_email varchar,
        out_owner_consent_at timestamp
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
               u.id, u.email, u.staff_access_consent_at
        FROM public.shops s
        JOIN public.users u ON u.id = s.user_id
        ORDER BY s.created_at
    $fn$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_transfer_shop(p_shop_id uuid, p_new_user_id uuid)
    RETURNS TABLE (out_shop_id uuid, out_previous_user_id uuid, out_user_id uuid)
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        WITH previous AS (
            SELECT id, user_id FROM public.shops WHERE id = p_shop_id FOR UPDATE
        )
        UPDATE public.shops s
        SET user_id = p_new_user_id, updated_at = now()
        FROM previous
        WHERE s.id = previous.id
          AND EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_new_user_id)
        RETURNING s.id, previous.user_id, s.user_id
    $fn$;
    """)
    for fn in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.ops_current_shop_overrides() TO {APP_ROLE}';
        END IF;
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.ops_current_shop_overrides() TO {OPS_ROLE}';
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.ops_list_shops() TO {OPS_ROLE}';
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.ops_transfer_shop(uuid, uuid) TO {OPS_ROLE}';
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_role()
    _create_tables()
    _lock_down_tables()
    _consent_column()
    _create_functions()


def downgrade() -> None:
    for fn in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE UPDATE (staff_access_consent_at) ON public.users FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_column("users", "staff_access_consent_at")
    for table in ("ops_shop_invites", "ops_sim_scenarios", "ops_shop_settings", "ops_audit_log"):
        op.drop_table(table)
    op.drop_table("ops_staff")
    op.execute(f"""
    DO $$
    DECLARE member record;
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'REVOKE USAGE ON SCHEMA public FROM {OPS_ROLE}';
            FOR member IN
                SELECT r.rolname FROM pg_auth_members m
                JOIN pg_roles g ON g.oid = m.roleid
                JOIN pg_roles r ON r.oid = m.member
                WHERE g.rolname = '{OPS_ROLE}'
            LOOP
                EXECUTE format('REVOKE {OPS_ROLE} FROM %I', member.rolname);
            END LOOP;
        END IF;
    END
    $$;
    """)  # nosec B608

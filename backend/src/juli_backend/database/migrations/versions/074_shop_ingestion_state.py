"""Per-shop ingestion bootstrap state + the pollable-shop enumeration (fast track P1-B).

SPEC §3.1 / §3.2 / §3.7, AC-1.4 / AC-1.5 / AC-1.10.

WHAT IT ADDS.

1. ``shop_ingestion_state`` -- one row per shop: bootstrap phase
   (``not_started`` / ``fast_running`` / ``fast_done`` / ``history_running`` /
   ``history_done`` / ``failed``), the latency timestamps SPEC §3.7 asks for
   (connect committed, bootstrap enqueued, fast done, first card, history done),
   the history cursor (earliest date reached, chunks done) and the daily
   analytics cursor. A new table rather than columns on ``shops`` or
   ``tiktok_sync_state`` so it cannot collide with concurrent model changes.

   Tenant-scoped exactly like 069's tables: RLS on, one policy per verb through
   ``app_current_shop_id()`` (never the raw ``current_setting(...)::uuid`` cast,
   #1467), and ``juli_app`` granted SELECT / INSERT / UPDATE -- the three verbs
   the bootstrap task uses. DELETE stays ungranted.

2. ``enumerate_pollable_shops(text[], text)`` -- the fan-out beat's work list.
   It must look across tenants (it is the question "which shops exist to be
   polled"), which is the case ADR-089 decision 3 reserves for a reviewed
   SECURITY DEFINER enumeration, shaped like 051/061: pinned ``search_path``,
   EXECUTE revoked from PUBLIC and granted only to ``juli_app``, and a row type
   no wider than the caller needs -- a shop id and one boolean ("has this shop
   finished its fast phase"). No token material crosses the boundary; the
   per-shop task re-reads its credential under its own shop scope through
   ``resolve_read_credential_for_shop``.

   Both arguments only narrow: ``read_capabilities`` is the application's
   ``READ_CAPABILITIES`` (so ``sandbox_write`` never qualifies) and
   ``excluded_merchant`` is ``SANDBOX_AUTH_ID``, refused by identity as well as
   by capability, mirroring ``_assert_pollable_read_credential``. Neither is
   spelled into the schema as a literal, for 061's reason.

EXPAND-ONLY AND REVERSIBLE. A new table and a new function; nothing existing is
altered. ``downgrade`` drops both.

RE-CHAIN AT INTEGRATION. Authored onto ``073_waiting_external`` while a sibling
fast-track branch adds its own revision on the same parent; whichever lands
second must re-point its ``down_revision`` so the chain stays linear.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "074_shop_ingestion_state"
down_revision: str | None = "073_waiting_external"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "shop_ingestion_state"
FUNCTION_SIGNATURE = "enumerate_pollable_shops(text[], text)"

STATUSES = (
    "not_started",
    "fast_running",
    "fast_done",
    "history_running",
    "history_done",
    "failed",
)


def _in_clause(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_started"),
        sa.Column("failed_phase", sa.String(length=10), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("connect_committed_at", sa.DateTime(), nullable=True),
        sa.Column("bootstrap_enqueued_at", sa.DateTime(), nullable=True),
        sa.Column("fast_started_at", sa.DateTime(), nullable=True),
        sa.Column("fast_done_at", sa.DateTime(), nullable=True),
        sa.Column("first_card_at", sa.DateTime(), nullable=True),
        sa.Column("history_started_at", sa.DateTime(), nullable=True),
        sa.Column("history_done_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("history_earliest_date", sa.Date(), nullable=True),
        sa.Column("history_chunks_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("history_empty_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analytics_through_date", sa.Date(), nullable=True),
        sa.Column("analytics_last_run_on", sa.Date(), nullable=True),
        sa.Column("latest_available_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name=f"pk_{TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{TABLE}_shop"),
        sa.CheckConstraint(_in_clause("status", STATUSES), name=f"ck_{TABLE}_status"),
        sa.CheckConstraint(
            "failed_phase IS NULL OR failed_phase IN ('fast', 'history')",
            name=f"ck_{TABLE}_failed_phase",
        ),
    )


def _enable_rls_and_policies() -> None:
    """Tenant-scope the table the way 069 scoped its tables."""
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    for verb, clause in (
        ("SELECT", "USING (shop_id = app_current_shop_id())"),
        (
            "UPDATE",
            "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
        ),
        ("DELETE", "USING (shop_id = app_current_shop_id())"),
        ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
    ):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {TABLE}_{verb.lower()}_public ON public.{TABLE} FOR {verb} {clause}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{TABLE} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _create_enumeration() -> None:
    """The fan-out work list: one row per active shop holding a pollable credential.

    OUT parameters are prefixed ``out_`` for 051's reason: an unqualified name
    matching both an OUT parameter and a column silently compares the column to
    itself.
    """
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_pollable_shops(
        read_capabilities text[],
        excluded_merchant text
    )
    RETURNS TABLE (
        out_shop_id uuid,
        out_fast_done boolean
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT s.id,
               (st.fast_done_at IS NOT NULL)
          FROM public.shops AS s
          LEFT JOIN public.shop_ingestion_state AS st ON st.shop_id = s.id
         WHERE s.is_active IS DISTINCT FROM false
           AND EXISTS (
               SELECT 1
                 FROM public.tiktok_credentials AS c
                WHERE c.shop_id = s.id
                  AND c.capability = ANY(read_capabilities)
                  AND c.status <> 'needs_reauth'
                  AND c.merchant_authorization_id IS NOT NULL
                  AND c.merchant_authorization_id <> excluded_merchant
           )
         ORDER BY s.id
      $fn$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION public.{FUNCTION_SIGNATURE} FROM PUBLIC;")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.{FUNCTION_SIGNATURE} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_table()
    _enable_rls_and_policies()
    _create_enumeration()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION_SIGNATURE};")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_table(TABLE)

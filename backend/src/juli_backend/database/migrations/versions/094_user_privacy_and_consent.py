"""Seller privacy preferences, terms consent and account deletion (fast track P50-B).

Revision ID: 094_user_privacy_and_consent
Revises: 093_ops_group_lift_draws
Create Date: 2026-10-18

DECISIONS D68 (PDPL terms); contract ``fasttrack/contracts/p50-privacy.md``.

WHAT IT ADDS.

- Seven ``users`` columns: the three opt-outs/opt-in (``marketing_opt_out``,
  ``ad_measurement_opt_out``, ``case_study_opt_in``; NOT NULL DEFAULT false), the
  accepted terms date and the two acceptance stamps (D68.4: the liability clause
  is accepted separately), and ``deletion_scheduled_for`` (D68.10: 30 days to
  export, then deletion). ``juli_app`` may UPDATE exactly these columns -- its own
  row only, by the existing ``users_update_public`` policy -- column-scoped like
  065 and 083, so ``id`` and ``phone`` stay unwritable.
- ``shop_subscription_periods.shop_id`` becomes NULLABLE: the purge keeps the
  period rows (contract / payment references, kept 10 years, D68.10) and
  detaches them from the deleted shop instead of deleting them.
- ``enumerate_pollable_shops`` (074) skips shops whose owner has a pending
  deletion, so every fan-out built on it (poll, history extend, product
  history, content runs) stops syncing those shops.
- Two SECURITY DEFINER functions (ADR-089 shape: ``out_`` columns, pinned
  ``search_path``, EXECUTE revoked from PUBLIC, granted to ``juli_ops`` only --
  never ``juli_app``), called by the nightly ``privacy_account_purge`` task:
  * ``privacy_due_accounts(timestamptz)`` -- ids of users whose deletion date has
    passed (``users`` is RLS-scoped to the caller's own row, so a worker cannot
    list them otherwise).
  * ``privacy_purge_account(uuid)`` -- deletes one DUE account (it refuses one
    that is not due): every row of every table carrying a ``shop_id`` of the
    user's shops (found from the catalog, so a table added later is covered),
    the rows of tables that reference those rows without a ``shop_id`` of their
    own, the user's references in other shops' rows (SET NULL when nullable,
    else deleted), the shops and the user. No FK into ``shops``/``users`` has a
    cascade, so the deletes are ordered by retrying a table that a still-present
    child blocks. Kept: ``shop_subscription_periods`` (detached) and
    ``ops_audit_log`` (staff accountability; its own 90/365-day retention, 085).
    The legacy read-only tables (``orders``, ``returns``,
    ``analytics_kpi_envelopes``) carry a no-write trigger; their USER triggers are
    disabled for the delete inside this transaction only. Returns counts only.

ADDITIVE. Nullable / defaulted columns, a relaxed NOT NULL, functions and
grants. The function bodies move no rows at migration time; their DML is issued
through ``EXECUTE`` at call time. ``downgrade`` reverses everything (re-imposing
NOT NULL fails if a detached period exists, which is the correct refusal). The
deferred phone-cleanup step is re-parented onto this revision so it stays the
tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "094_user_privacy_and_consent"
down_revision: str | None = "093_ops_group_lift_draws"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"

#: The columns the seller writes on their own row (contract §PATCH, §consents, §deletion).
PRIVACY_COLUMNS = (
    "marketing_opt_out",
    "ad_measurement_opt_out",
    "case_study_opt_in",
    "terms_date_accepted",
    "terms_accepted_at",
    "liability_clause_accepted_at",
    "deletion_scheduled_for",
)

DUE_FN = "public.privacy_due_accounts(timestamptz)"
PURGE_FN = "public.privacy_purge_account(uuid)"
ENUM_FN = "public.enumerate_pollable_shops(text[], text)"

# Both lists are compared with ``oid::regclass::text`` inside a function whose
# search_path is pinned to ``pg_catalog, public``: a public table renders
# UNQUALIFIED ("orders"), any other schema qualified ("silver.orders").
#: Tables the purge keeps (D68.10 invoices; staff audit with its own retention).
KEPT_TABLES = ("shop_subscription_periods", "ops_audit_log")
#: Legacy read-only public tables guarded by a no-write trigger (#607 silver cutover).
GUARDED_TABLES = ("orders", "returns", "analytics_kpi_envelopes")


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _column_grant(keyword: str) -> None:
    preposition = "TO" if keyword == "GRANT" else "FROM"
    columns = ", ".join(PRIVACY_COLUMNS)
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE '{keyword} UPDATE ({columns}) ON public.users {preposition} {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - role and column names are fixed module constants


def _enumeration(pending_deletion_filter: bool) -> None:
    owner_clause = (
        """
           AND NOT EXISTS (
               SELECT 1 FROM public.users AS u
                WHERE u.id = s.user_id AND u.deletion_scheduled_for IS NOT NULL
           )"""
        if pending_deletion_filter
        else ""
    )
    op.execute(f"""
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
           ){owner_clause}
         ORDER BY s.id
      $fn$;
    """)  # nosec B608 - fixed SQL


def _create_functions() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.privacy_due_accounts(p_now timestamptz)
    RETURNS TABLE (out_user_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT u.id FROM public.users AS u
         WHERE u.deletion_scheduled_for IS NOT NULL AND u.deletion_scheduled_for <= p_now
         ORDER BY u.deletion_scheduled_for, u.id
         LIMIT 500
    $fn$;
    """)
    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.privacy_purge_account(p_user uuid)
    RETURNS TABLE (out_shops integer, out_rows bigint, out_kept_periods integer)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
    DECLARE
        v_shops uuid[];
        v_rows bigint := 0;
        v_n bigint;
        v_kept integer := 0;
        v_pending text[];
        v_next text[];
        v_tbl text;
        v_fk record;
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM public.users AS u
             WHERE u.id = p_user AND u.deletion_scheduled_for IS NOT NULL
               AND u.deletion_scheduled_for <= now()
        ) THEN
            RAISE EXCEPTION 'privacy_purge_account: account is not due for deletion'
                USING ERRCODE = 'P0001';
        END IF;
        v_shops := ARRAY(SELECT s.id FROM public.shops AS s WHERE s.user_id = p_user);

        -- 1. Keep the subscription periods (D68.10), detached from the shop.
        EXECUTE 'UPDATE public.shop_subscription_periods SET shop_id = NULL '
                'WHERE shop_id = ANY($1)' USING v_shops;
        GET DIAGNOSTICS v_kept = ROW_COUNT;

        -- 2. Rows without a shop_id that reference a shop-scoped row.
        FOR v_fk IN
            SELECT c.conrelid::regclass::text AS child, ca.attname AS child_col,
                   c.confrelid::regclass::text AS parent, pa.attname AS parent_col
              FROM pg_constraint AS c
              JOIN pg_attribute AS ca ON ca.attrelid = c.conrelid AND ca.attnum = c.conkey[1]
              JOIN pg_attribute AS pa ON pa.attrelid = c.confrelid AND pa.attnum = c.confkey[1]
             WHERE c.contype = 'f' AND cardinality(c.conkey) = 1
               AND EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.confrelid
                            AND a.attname = 'shop_id' AND NOT a.attisdropped)
               AND NOT EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.conrelid
                                AND a.attname = 'shop_id' AND NOT a.attisdropped)
             ORDER BY 1, 2
        LOOP
            EXECUTE format('DELETE FROM %s WHERE %I IN (SELECT %I FROM %s WHERE shop_id = ANY($1))',
                           v_fk.child, v_fk.child_col, v_fk.parent_col, v_fk.parent)
              USING v_shops;
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_rows := v_rows + v_n;
        END LOOP;

        -- 3. Every base table with a uuid shop_id, retried until FK order allows.
        v_pending := ARRAY(
        SELECT c.oid::regclass::text
          FROM pg_class AS c
          JOIN pg_namespace AS n ON n.oid = c.relnamespace
          JOIN pg_attribute AS a ON a.attrelid = c.oid AND a.attname = 'shop_id'
                                AND NOT a.attisdropped AND a.atttypid = 'uuid'::regtype
         WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
           AND n.nspname NOT IN ('pg_catalog', 'information_schema')
           AND n.nspname NOT LIKE 'pg\\_%'
           AND c.oid::regclass::text NOT IN ({_sql_list(KEPT_TABLES)})
         ORDER BY 1);
        WHILE cardinality(v_pending) > 0 LOOP
            v_next := '{{}}';
            FOREACH v_tbl IN ARRAY v_pending LOOP
                BEGIN
                    IF v_tbl IN ({_sql_list(GUARDED_TABLES)}) THEN
                        EXECUTE format('SELECT count(*) FROM %s WHERE shop_id = ANY($1)', v_tbl)
                          INTO v_n USING v_shops;
                        IF v_n > 0 THEN
                            EXECUTE format('ALTER TABLE %s DISABLE TRIGGER USER', v_tbl);
                            EXECUTE format('DELETE FROM %s WHERE shop_id = ANY($1)', v_tbl)
                              USING v_shops;
                            EXECUTE format('ALTER TABLE %s ENABLE TRIGGER USER', v_tbl);
                        END IF;
                    ELSE
                        EXECUTE format('DELETE FROM %s WHERE shop_id = ANY($1)', v_tbl)
                          USING v_shops;
                        GET DIAGNOSTICS v_n = ROW_COUNT;
                    END IF;
                    v_rows := v_rows + v_n;
                EXCEPTION WHEN foreign_key_violation THEN
                    v_next := v_next || v_tbl;
                END;
            END LOOP;
            IF cardinality(v_next) = cardinality(v_pending) THEN
                RAISE EXCEPTION 'privacy_purge_account: no delete order for %', v_next
                    USING ERRCODE = 'P0001';
            END IF;
            v_pending := v_next;
        END LOOP;

        -- 4. The user's references in rows that are not theirs.
        FOR v_fk IN
            SELECT c.conrelid::regclass::text AS child, ca.attname AS child_col,
                   ca.attnotnull AS not_null
              FROM pg_constraint AS c
              JOIN pg_attribute AS ca ON ca.attrelid = c.conrelid AND ca.attnum = c.conkey[1]
             WHERE c.contype = 'f' AND cardinality(c.conkey) = 1
               AND c.confrelid = 'public.users'::regclass
               AND c.conrelid <> 'public.shops'::regclass
             ORDER BY 1, 2
        LOOP
            IF v_fk.not_null THEN
                EXECUTE format('DELETE FROM %s WHERE %I = $1', v_fk.child, v_fk.child_col)
                  USING p_user;
            ELSE
                EXECUTE format('UPDATE %s SET %I = NULL WHERE %I = $1',
                               v_fk.child, v_fk.child_col, v_fk.child_col)
                  USING p_user;
            END IF;
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_rows := v_rows + v_n;
        END LOOP;

        -- 5. The shops, then the account.
        EXECUTE 'DELETE FROM public.shops WHERE user_id = $1' USING p_user;
        EXECUTE 'DELETE FROM public.users WHERE id = $1' USING p_user;

        out_shops := cardinality(v_shops);
        out_rows := v_rows;
        out_kept_periods := v_kept;
        RETURN NEXT;
    END
    $fn$;
    """)  # nosec B608 - fixed SQL; table lists are module constants
    for fn in (DUE_FN, PURGE_FN):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
                EXECUTE 'GRANT EXECUTE ON FUNCTION {fn} TO {OPS_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - role and function are fixed module constants


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("marketing_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column(
            "ad_measurement_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "users",
        sa.Column("case_study_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("terms_date_accepted", sa.Date(), nullable=True))
    op.add_column(
        "users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("liability_clause_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users", sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True)
    )
    _column_grant("GRANT")
    op.alter_column("shop_subscription_periods", "shop_id", nullable=True)
    _enumeration(pending_deletion_filter=True)
    _create_functions()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {PURGE_FN}")
    op.execute(f"DROP FUNCTION IF EXISTS {DUE_FN}")
    _enumeration(pending_deletion_filter=False)
    op.alter_column("shop_subscription_periods", "shop_id", nullable=False)
    _column_grant("REVOKE")
    for column in reversed(PRIVACY_COLUMNS):
        op.drop_column("users", column)

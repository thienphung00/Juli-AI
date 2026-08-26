"""Enable RLS and add tenant-scoped policies on missed tables (issue #1329, ADR-085 decision 3).

This migration realizes ADR-085 decision 3 enforcement on two tables that migration 045
left unprotected:

- gold.ml_feature_snapshots (has shop_id column)
- public.processed_events (has shop_id column)

Both have direct shop_id columns and receive the same DIRECT tenant-scoped policy shape
as migration 045: policies compare shop_id = current_setting('app.current_shop_id', true)::uuid
on the already-indexed column.

Additionally, this migration grants SELECT/INSERT/UPDATE to juli_app on these tables.
Migration 043 left ml_feature_snapshots ungrantedand processed_events with only SELECT/INSERT
(missing UPDATE needed for direct tenant-scoped tables). Both gaps are closed here.

No FORCE ROW LEVEL SECURITY — owner (postgres, alembic, admin, deployed runtime) must
keep working; policies apply to juli_app only.

SELECT, UPDATE, DELETE covered per table. INSERT carries WITH CHECK rejecting
foreign-tenant row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "046_rls_missed_tables"
down_revision: str | None = "045_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tenant-scoped tables with direct shop_id column that were missed in 045
MISSED_DIRECT_SHOP_ID_TABLES = [
    ("gold", "ml_feature_snapshots"),
    ("public", "processed_events"),
]

ROLE_NAME = "juli_app"

# Grant map for missed tables: (schema, table) -> privileges tuple
MISSED_TABLE_GRANTS = {
    ("public", "processed_events"): ("SELECT", "INSERT", "UPDATE"),
    ("gold", "ml_feature_snapshots"): ("SELECT", "INSERT", "UPDATE"),
}


def _grant_table_privileges_on_missed_tables() -> None:
    """Grant SELECT/INSERT/UPDATE to juli_app on missed tables."""
    for (schema, table), verbs in MISSED_TABLE_GRANTS.items():
        verb_str = ", ".join(verbs)
        sql = f"""
DO $grant_table$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}') THEN
    GRANT {verb_str} ON {schema}.{table} TO {ROLE_NAME};
  END IF;
END
$grant_table$;
"""  # nosec B608 — schema/table/role/verbs are fixed module constants
        op.execute(sql)


def _revoke_table_privileges_on_missed_tables() -> None:
    """Revoke all privileges from juli_app on missed tables (downgrade path)."""
    for schema, table in MISSED_DIRECT_SHOP_ID_TABLES:
        sql = f"""
DO $revoke_table$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}') THEN
    REVOKE ALL ON {schema}.{table} FROM {ROLE_NAME};
  END IF;
END
$revoke_table$;
"""  # nosec B608 — schema/table/role are fixed module constants
        op.execute(sql)


def _enable_rls_on_missed_tables() -> None:
    """Enable RLS on missed tenant-scoped tables."""
    for schema, table in MISSED_DIRECT_SHOP_ID_TABLES:
        sql = f"""
DO $rls_enable$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY;
  END IF;
END
$rls_enable$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(sql)


def _create_direct_shop_id_policies_for_missed_tables() -> None:
    """Create policies for missed direct tenant-scoped tables (shop_id column)."""
    for schema, table in MISSED_DIRECT_SHOP_ID_TABLES:
        # SELECT policy
        select_policy = f"""
DO $create_select$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    CREATE POLICY {table}_select_{schema} ON {schema}.{table}
      FOR SELECT
      USING (shop_id = current_setting('app.current_shop_id', true)::uuid);
  END IF;
END
$create_select$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(select_policy)

        # UPDATE policy
        update_policy = f"""
DO $create_update$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    CREATE POLICY {table}_update_{schema} ON {schema}.{table}
      FOR UPDATE
      USING (shop_id = current_setting('app.current_shop_id', true)::uuid)
      WITH CHECK (shop_id = current_setting('app.current_shop_id', true)::uuid);
  END IF;
END
$create_update$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(update_policy)

        # DELETE policy
        delete_policy = f"""
DO $create_delete$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    CREATE POLICY {table}_delete_{schema} ON {schema}.{table}
      FOR DELETE
      USING (shop_id = current_setting('app.current_shop_id', true)::uuid);
  END IF;
END
$create_delete$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(delete_policy)

        # INSERT policy with WITH CHECK
        insert_policy = f"""
DO $create_insert$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    CREATE POLICY {table}_insert_{schema} ON {schema}.{table}
      FOR INSERT
      WITH CHECK (shop_id = current_setting('app.current_shop_id', true)::uuid);
  END IF;
END
$create_insert$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(insert_policy)


def _drop_all_policies_on_missed_tables() -> None:
    """Drop all policies and disable RLS on missed tables (downgrade path)."""
    for schema, table, *_ in MISSED_DIRECT_SHOP_ID_TABLES:
        sql = f"""
DO $drop_policies$
DECLARE
  r RECORD;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    FOR r IN
      SELECT policyname FROM pg_policies
      WHERE schemaname = '{schema}' AND tablename = '{table}'
    LOOP
      EXECUTE 'DROP POLICY IF EXISTS ' || quote_ident(r.policyname) || ' ON {schema}.{table}';
    END LOOP;
  END IF;
END
$drop_policies$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(sql)

    # Disable RLS on all affected tables
    for schema, table, *_ in MISSED_DIRECT_SHOP_ID_TABLES:
        sql = f"""
DO $disable_rls$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY;
  END IF;
END
$disable_rls$;
"""  # nosec B608 — schema/table are fixed constants
        op.execute(sql)


def upgrade() -> None:
    """Enable RLS and create tenant-scoped policies on missed tables.

    Also grants SELECT/INSERT/UPDATE to juli_app.

    Applies the same DIRECT tenant-scoped policy shape as migration 045:
    shop_id = current_setting('app.current_shop_id', true)::uuid
    """
    _grant_table_privileges_on_missed_tables()
    _enable_rls_on_missed_tables()
    _create_direct_shop_id_policies_for_missed_tables()


def downgrade() -> None:
    """Disable RLS and drop all policies on missed tables, revoke privileges.

    Downgrade reverses the state: drops policies first, disables RLS, then revokes grants.
    Never leaves a table RLS-enabled with zero policies (that denies all to juli_app).
    """
    _drop_all_policies_on_missed_tables()
    _revoke_table_privileges_on_missed_tables()

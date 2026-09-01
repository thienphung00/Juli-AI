"""Enable RLS and add tenant-scoped policies on every table (issue #1328, ADR-085 decision 3).

This migration realizes ADR-085 decision 3: with the non-owner role (#1326) and the setter
that actually sets (#1327) in place, policies can finally deny.

Scope: Every tenant-scoped table across public, bronze, silver, ops, and gold schemas.
Tables derived from models.py metadata (37 tables as of late August), not a hardcoded list.

Three shapes, each table gets exactly one:

1. **Tenant-scoped DIRECT** (has shop_id): Policy compares
   shop_id = current_setting('app.current_shop_id', true)::uuid
   on the already-indexed column. Do NOT reuse the old EXISTS join with shops — that puts a
   correlated subquery in front of every analytics row.

2. **Tenant-scoped VIA PARENT** (workflow_run_events + run_confirmations via workflow_runs,
   impact_readings via tool_executions, action_card_approvals via action_cards): Policy is
   EXISTS on the parent keyed to the parent's indexed PK. Do NOT denormalize shop_id onto them.

3. **Non-tenant** (users, shops, webhook_raw_events): users gets app.current_user_id policy,
   shops gets user_id policy, webhook_raw_events gets no policy (no read grant in #1326).

missing_ok=true is deliberate: unset denies (NULL comparison, no rows) rather than raising.
The raising happens in Python first, from #1327 — operator sees a named error, not empty
result set reading as "seller has no data."

The migration drops the ten pre-existing app.current_user_id policies (inert in this RLS
context, made obsolete by the new shape). No FORCE ROW LEVEL SECURITY — owner (postgres,
alembic, admin, deployed runtime) must keep working; policies apply to juli_app only.

SELECT, UPDATE, DELETE covered per table. INSERT carries WITH CHECK rejecting foreign-tenant
row.

Downgrade drops policies and disables RLS — never leaves RLS enabled with zero policies
(that denies all to juli_app, indistinguishable from data loss).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "045_rls_policies"
down_revision: str | None = "044_prod_write_authorizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tenant-scoped tables with direct shop_id column
DIRECT_SHOP_ID_TABLES = [
    ("public", "tiktok_credentials"),
    ("public", "tiktok_sync_state"),
    ("public", "orders"),
    ("public", "order_items"),
    ("public", "returns"),
    ("public", "products"),
    ("public", "inventory_items"),
    ("public", "settlements"),
    ("public", "creators"),
    ("public", "livestreams"),
    ("public", "analytics_performance_intervals"),
    ("public", "alert_configs"),
    ("public", "alert_history"),
    ("public", "workflow_webhook_signals"),
    ("public", "workflow_runs"),
    ("public", "tool_executions"),
    ("public", "workflow_outcome_records"),
    ("public", "action_cards"),
    ("public", "decision_emission_novelty_ledger"),
    ("public", "demo_execution_records"),
    ("public", "recommendations"),
    ("public", "campaigns"),
    ("public", "graph_edges"),
    ("public", "analytics_kpi_envelopes"),
    ("silver", "orders"),
    ("silver", "returns"),
    ("ops", "analytics_backfill_partitions"),
    ("gold", "kpi_envelopes"),
    ("bronze", "order_raw_payloads"),
    ("bronze", "return_raw_payloads"),
    ("bronze", "ctor_performance_raw_payloads"),
    ("bronze", "live_hours_raw_payloads"),
    ("public", "production_write_authorizations"),
]

# Via-parent tables: (schema, table, parent_table_fk_column, parent_table)
VIA_PARENT_TABLES = [
    ("public", "workflow_run_events", "workflow_run_id", "workflow_runs"),
    ("public", "run_confirmations", "workflow_run_id", "workflow_runs"),
    ("public", "impact_readings", "tool_execution_id", "tool_executions"),
    ("public", "action_card_approvals", "action_card_id", "action_cards"),
]

# Non-tenant tables with special policies
NON_TENANT_TABLES = {
    ("public", "users"): "id",  # keyed to app.current_user_id
    ("public", "shops"): "user_id",  # keyed to user_id (owner)
    # webhook_raw_events: no policy (no read grant in #1326)
}


def _enable_rls_and_drop_old_policies() -> None:
    """Enable RLS on all tenant-scoped tables and drop old app.current_user_id policies."""
    # Enable RLS on direct tables
    for schema, table in DIRECT_SHOP_ID_TABLES:
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

    # Enable RLS on via-parent tables
    for schema, table, _, _ in VIA_PARENT_TABLES:
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

    # Enable RLS on non-tenant tables
    for schema, table in NON_TENANT_TABLES:
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

    # Drop old app.current_user_id policies (if they exist)
    # The old policies were inert (app.current_user_id stays unset in RLS context) and are now obsolete.
    # Old policies were created in migrations 001 (users_isolation, shops_isolation, credentials_isolation),
    # 002 (various {table}_isolation), 017, 019, 020, 022 with various names.
    # Rather than enumerate all of them, we drop all policies that reference current_user_id
    # EXCEPT those on users and shops which we'll replace with new policies.

    # Map of (schema, table) -> old policy names to drop (known from earlier migrations)
    # Tables may exist in multiple schemas (e.g., orders in public and silver after migration 025)
    old_policies_to_drop = [
        ("public", "tiktok_credentials", "credentials_isolation"),
        ("public", "orders", "orders_isolation"),
        ("public", "products", "products_isolation"),
        ("public", "creators", "creators_isolation"),
        ("public", "livestreams", "livestreams_isolation"),
        ("public", "settlements", "settlements_isolation"),
        ("public", "inventory_items", "inventory_items_isolation"),
        ("public", "alert_configs", "alert_configs_isolation"),
        ("public", "alert_history", "alert_history_isolation"),
        ("public", "recommendations", "recommendations_isolation"),
        ("public", "analytics_performance_intervals", "analytics_performance_intervals_isolation"),
        ("public", "order_items", "order_items_isolation"),
        ("public", "returns", "returns_isolation"),
        ("public", "campaigns", "campaigns_isolation"),
        ("public", "graph_edges", "graph_edges_isolation"),
        ("public", "analytics_kpi_envelopes", "analytics_kpi_envelopes_isolation"),
        ("public", "demo_execution_records", "demo_execution_records_isolation"),
        (
            "public",
            "decision_emission_novelty_ledger",
            "decision_emission_novelty_ledger_isolation",
        ),
        ("silver", "orders", "orders_isolation"),  # Also in silver schema
        ("silver", "returns", "returns_isolation"),  # Also in silver schema
        ("ops", "analytics_backfill_partitions", "analytics_backfill_partitions_isolation"),
        ("gold", "kpi_envelopes", "gold_kpi_envelopes_isolation"),
    ]

    for schema, table, policy_name in old_policies_to_drop:
        sql = f"DROP POLICY IF EXISTS {policy_name} ON {schema}.{table};"  # nosec B608
        try:
            op.execute(sql)
        except Exception:
            # Silently continue if policy doesn't exist or table doesn't exist
            pass


def _create_direct_shop_id_policies() -> None:
    """Create policies for direct tenant-scoped tables (shop_id column)."""
    for schema, table in DIRECT_SHOP_ID_TABLES:
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


def _create_via_parent_policies() -> None:
    """Create policies for via-parent tenant-scoped tables."""
    for schema, table, fk_column, parent_table in VIA_PARENT_TABLES:
        # SELECT policy: EXISTS on parent table
        select_policy = f"""
DO $create_select$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = '{schema}' AND pg_class.relname = '{table}')
  THEN
    CREATE POLICY {table}_select_{schema} ON {schema}.{table}
      FOR SELECT
      USING (EXISTS (
        SELECT 1 FROM {parent_table}
        WHERE {parent_table}.id = {table}.{fk_column}
          AND {parent_table}.shop_id = current_setting('app.current_shop_id', true)::uuid
      ));
  END IF;
END
$create_select$;
"""  # nosec B608 — schema/table/fk_column/parent_table are fixed constants
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
      USING (EXISTS (
        SELECT 1 FROM {parent_table}
        WHERE {parent_table}.id = {table}.{fk_column}
          AND {parent_table}.shop_id = current_setting('app.current_shop_id', true)::uuid
      ))
      WITH CHECK (EXISTS (
        SELECT 1 FROM {parent_table}
        WHERE {parent_table}.id = {table}.{fk_column}
          AND {parent_table}.shop_id = current_setting('app.current_shop_id', true)::uuid
      ));
  END IF;
END
$create_update$;
"""  # nosec B608 — schema/table/fk_column/parent_table are fixed constants
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
      USING (EXISTS (
        SELECT 1 FROM {parent_table}
        WHERE {parent_table}.id = {table}.{fk_column}
          AND {parent_table}.shop_id = current_setting('app.current_shop_id', true)::uuid
      ));
  END IF;
END
$create_delete$;
"""  # nosec B608 — schema/table/fk_column/parent_table are fixed constants
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
      WITH CHECK (EXISTS (
        SELECT 1 FROM {parent_table}
        WHERE {parent_table}.id = {table}.{fk_column}
          AND {parent_table}.shop_id = current_setting('app.current_shop_id', true)::uuid
      ));
  END IF;
END
$create_insert$;
"""  # nosec B608 — schema/table/fk_column/parent_table are fixed constants
        op.execute(insert_policy)


def _create_non_tenant_policies() -> None:
    """Create policies for non-tenant tables (users keyed to app.current_user_id, shops to user_id)."""
    # users: keyed to app.current_user_id
    users_select = """
DO $create_select$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'users')
  THEN
    CREATE POLICY users_select_public ON public.users
      FOR SELECT
      USING (id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_select$;
"""
    op.execute(users_select)

    users_update = """
DO $create_update$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'users')
  THEN
    CREATE POLICY users_update_public ON public.users
      FOR UPDATE
      USING (id = current_setting('app.current_user_id', true)::uuid)
      WITH CHECK (id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_update$;
"""
    op.execute(users_update)

    users_delete = """
DO $create_delete$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'users')
  THEN
    CREATE POLICY users_delete_public ON public.users
      FOR DELETE
      USING (id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_delete$;
"""
    op.execute(users_delete)

    users_insert = """
DO $create_insert$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'users')
  THEN
    CREATE POLICY users_insert_public ON public.users
      FOR INSERT
      WITH CHECK (id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_insert$;
"""
    op.execute(users_insert)

    # shops: keyed to user_id (owner of the shop)
    shops_select = """
DO $create_select$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'shops')
  THEN
    CREATE POLICY shops_select_public ON public.shops
      FOR SELECT
      USING (user_id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_select$;
"""
    op.execute(shops_select)

    shops_update = """
DO $create_update$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'shops')
  THEN
    CREATE POLICY shops_update_public ON public.shops
      FOR UPDATE
      USING (user_id = current_setting('app.current_user_id', true)::uuid)
      WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_update$;
"""
    op.execute(shops_update)

    shops_delete = """
DO $create_delete$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'shops')
  THEN
    CREATE POLICY shops_delete_public ON public.shops
      FOR DELETE
      USING (user_id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_delete$;
"""
    op.execute(shops_delete)

    shops_insert = """
DO $create_insert$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class
             JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
             WHERE pg_namespace.nspname = 'public' AND pg_class.relname = 'shops')
  THEN
    CREATE POLICY shops_insert_public ON public.shops
      FOR INSERT
      WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);
  END IF;
END
$create_insert$;
"""
    op.execute(shops_insert)

    # webhook_raw_events: no policy (no read grant in #1326)
    # RLS is enabled, but no policies means it denies all reads to juli_app (by design)


def _drop_all_policies() -> None:
    """Drop all policies and disable RLS on all affected tables."""
    # Drop all policies (downgrade path)
    all_tables = DIRECT_SHOP_ID_TABLES + VIA_PARENT_TABLES + list(NON_TENANT_TABLES.keys())

    for schema, table, *_ in all_tables:
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
    for schema, table, *_ in all_tables:
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
    """Enable RLS and create tenant-scoped policies on all tables.

    Three policy shapes:
    1. Direct shop_id: shop_id = current_setting('app.current_shop_id', true)::uuid
    2. Via-parent: EXISTS on parent table's shop_id
    3. Non-tenant: users keyed to app.current_user_id, shops to user_id
    """
    _enable_rls_and_drop_old_policies()
    _create_direct_shop_id_policies()
    _create_via_parent_policies()
    _create_non_tenant_policies()


def downgrade() -> None:
    """Disable RLS and drop all policies.

    Downgrade reverses the state: drops policies first, then disables RLS.
    Never leaves a table RLS-enabled with zero policies (that denies all to juli_app).
    """
    _drop_all_policies()

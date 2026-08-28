"""Create non-owner runtime role juli_app with explicit per-table grants (ADR-085 #1326)

Revision ID: 043_juli_app_role
Revises: 043_stop_reason_consent_pause
Create Date: 2026-08-25

ADR-085 decision 1: functional RLS requires a non-owner runtime role, not more policies.
This migration creates the `juli_app` role — NOLOGIN, owning nothing, granted exactly the
privileges the application needs.

The role is idempotent against an existing database (mirrors the IF EXISTS guard pattern
of migrations 021 and 032). It comes before all policies so they apply (Postgres does not
apply row-level policies to a table's owner, and the application connects as `postgres`
in this slice — the cutover to `juli_app` happens in gate #1339, after RLS is in place).

The migration grants:
- USAGE on the schemas the runtime reads (public, bronze, silver, ops, gold)
- Table-level SELECT/INSERT/UPDATE per table from an explicit map, never ALL TABLES IN SCHEMA
- Upsert tables (orders, products, inventory_items, etc.) receive UPDATE for row mutation
- Status-update tables (workflow_runs, action_cards, tiktok_credentials, tool_executions) receive UPDATE
- webhook_raw_events gets INSERT only (no tenant lineage, no read grant per ADR-085 decision 3)
- No ALTER DEFAULT PRIVILEGES — a future table must be granted deliberately

The login role is granted membership out of band (documented in the runbook), so no
credential enters git and no migration can mint one.

Downgrade drops the role and its grants. Unlike decision 1's example downgrade, dropping
a role with active sessions raises an error (expected and correct) rather than silently
succeeding — a failing downgrade that names the block is safe, not a permission leak.
"""

from collections.abc import Sequence

from alembic import op

# Type alias for grant map structure: schema -> {table -> (privileges...)}
GrantMap = dict[str, dict[str, tuple[str, ...]]]

revision: str = "043_juli_app_role"
down_revision: str | None = "043_stop_reason_consent_pause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
SCHEMAS = ("public", "bronze", "silver", "ops", "gold")

# Explicit per-table grant map: table -> verbs tuple
# Derived from backend repositories; webhook_raw_events has INSERT only (no tenant lineage, ADR-085 decision 3)
# SELECT+INSERT: read tables or insert audit/event rows
# SELECT+INSERT+UPDATE: upsert tables (#517 OrdersRepo, #589 OrderItemsRepo, #626 ReturnsRepo,
#   #631 ProductsRepo, #718 InventoryRepo, #723 SettlementsRepo, #733 CreatorsRepo,
#   #738 LivestreamsRepo, #743 AnalyticsPerformanceRepo, #914 ActionCardsRepo) or status updates
#   (tiktok_credentials.update_tokens, tool_executions.update_status, workflow_runs status changes,
#   action_cards status changes)
GRANT_MAP: GrantMap = {
    "public": {
        # SELECT+INSERT+UPDATE on upsert tables (products may use ON CONFLICT DO UPDATE)
        "tiktok_credentials": ("SELECT", "INSERT", "UPDATE"),  # update_tokens() repos.py:228
        "orders": ("SELECT", "INSERT", "UPDATE"),  # upsert() OrdersRepo repos.py:517
        "products": ("SELECT", "INSERT", "UPDATE"),  # upsert() ProductsRepo repos.py:631
        "order_items": ("SELECT", "INSERT", "UPDATE"),  # upsert() OrderItemsRepo repos.py:589
        "inventory_items": ("SELECT", "INSERT", "UPDATE"),  # upsert() InventoryRepo repos.py:718
        "settlements": ("SELECT", "INSERT", "UPDATE"),  # upsert() SettlementsRepo repos.py:723
        "creators": ("SELECT", "INSERT", "UPDATE"),  # upsert() CreatorsRepo repos.py:733
        "livestreams": ("SELECT", "INSERT", "UPDATE"),  # upsert() LivestreamsRepo repos.py:738
        "analytics_performance_intervals": ("SELECT", "INSERT", "UPDATE"),  # upsert() repos.py:743
        "action_cards": ("SELECT", "INSERT", "UPDATE"),  # upsert() ActionCardsRepo repos.py:914
        "tool_executions": ("SELECT", "INSERT", "UPDATE"),  # update_status() repos.py:1322
        "workflow_runs": (
            "SELECT",
            "INSERT",
            "UPDATE",
        ),  # status updates conversation_store.py:283-290
        "returns": ("SELECT", "INSERT", "UPDATE"),  # upsert() ReturnsRepo repos.py:626
        # SELECT+INSERT on other public tables
        "users": ("SELECT", "INSERT"),
        "shops": ("SELECT", "INSERT"),
        "tiktok_sync_state": ("SELECT", "INSERT"),
        "workflow_webhook_signals": ("SELECT", "INSERT"),
        "workflow_run_events": ("SELECT", "INSERT"),
        "run_confirmations": ("SELECT", "INSERT"),
        "workflow_outcome_records": ("SELECT", "INSERT"),
        "impact_readings": ("SELECT", "INSERT"),
        "action_card_approvals": ("SELECT", "INSERT"),
        "alert_configs": ("SELECT", "INSERT"),
        "alert_history": ("SELECT", "INSERT"),
        "recommendations": ("SELECT", "INSERT"),
        "campaigns": ("SELECT", "INSERT"),
        "graph_edges": ("SELECT", "INSERT"),
        "decision_emission_novelty_ledger": ("SELECT", "INSERT"),
        "demo_execution_records": ("SELECT", "INSERT"),
        "analytics_kpi_envelopes": ("SELECT", "INSERT"),
        "processed_events": ("SELECT", "INSERT"),
        # INSERT only on webhook_raw_events (no tenant lineage, ADR-085 decision 3)
        "webhook_raw_events": ("INSERT",),
    },
    "bronze": {
        # INSERT only for raw payload tables (ingest path)
        "order_raw_payloads": ("INSERT",),
        "return_raw_payloads": ("INSERT",),
        "ctor_performance_raw_payloads": ("INSERT",),
        "live_hours_raw_payloads": ("INSERT",),
    },
    "silver": {
        # SELECT+INSERT+UPDATE on silver fact tables (upsert path)
        "orders": ("SELECT", "INSERT", "UPDATE"),  # upsert() via OrdersRepo repos.py:517
        "returns": ("SELECT", "INSERT", "UPDATE"),  # upsert() via ReturnsRepo repos.py:626
    },
    "ops": {
        # SELECT+INSERT+UPDATE on analytics_backfill_partitions (upsert path)
        "analytics_backfill_partitions": ("SELECT", "INSERT", "UPDATE"),  # upsert() repos.py
    },
    "gold": {
        # SELECT+INSERT on KPI envelopes (upsert path)
        "kpi_envelopes": (
            "SELECT",
            "INSERT",
            "UPDATE",
        ),  # upsert() GoldKpiEnvelopesRepo repos.py:816
    },
}


def _grant_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Grant table-level privileges to juli_app from the explicit map."""
    for schema, tables in grant_map.items():
        for table, verbs in tables.items():
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


def _revoke_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Revoke all privileges from juli_app on all tables (downgrade path)."""
    for schema, tables in grant_map.items():
        for table in tables:
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


def upgrade() -> None:
    """Create juli_app role and grant exactly the privileges the app needs.

    Idempotent: IF EXISTS guard allows re-running on a database where the role
    already exists (mirrors migrations 021 and 032 pattern).
    """
    # Create NOLOGIN role, no login, no password, no membership grants
    sql = f"""
DO $create_role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
    CREATE ROLE {ROLE_NAME} NOLOGIN;
  END IF;
END
$create_role$;
"""  # nosec B608 — role name is a fixed module constant
    op.execute(sql)

    # Grant USAGE on all runtime schemas
    for schema in SCHEMAS:
        sql = f"""
DO $grant_schema_usage$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema}') THEN
    GRANT USAGE ON SCHEMA {schema} TO {ROLE_NAME};
  END IF;
END
$grant_schema_usage$;
"""  # nosec B608 — schema/role are fixed module constants
        op.execute(sql)

    # Grant table-level privileges from explicit map
    _grant_table_privileges()


def downgrade() -> None:
    """Revoke all privileges and drop the juli_app role.

    A ROLE is cluster-wide; DROP OWNED BY is database-local. A migration runs in
    ONE database and can therefore only ever clean up its own grants — it cannot
    see, let alone remove, grants held in a sibling database of the same cluster.
    So `DROP ROLE` here is an operation this migration cannot guarantee, and the
    original version's "fail loudly" stance made that unguaranteeable step abort
    the whole downgrade (issue #1405).

    That failure was not loud, it was silent and dangerous. `command.downgrade`
    runs the chain as one transaction, so the abort rolled everything back and
    left the database **at head with every table still present**, while the
    caller carried on believing it had reached base. The next operation then hit
    `workflow_runs` still carrying W7's foreign keys:

        cannot drop table workflow_runs because other objects depend on it
        DETAIL: production_write_authorizations_consumed_by_run_id_fkey
                production_write_audit_run_id_fkey

    which is how one cross-database grant turned into 19 failing schema tests.

    So: drop this database's grants, then attempt the role and tolerate the one
    outcome the migration cannot control. Leaving the role behind is not a
    permission leak — it is NOLOGIN, it owns nothing, and DROP OWNED BY has
    already removed every privilege it held *here*. A stranded NOLOGIN role is
    strictly safer than a downgrade that reports success from head.
    """
    sql = f"""
DO $drop_role$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
    -- Database-local: removes every privilege this role holds in THIS database.
    EXECUTE 'DROP OWNED BY {ROLE_NAME}';
    BEGIN
      EXECUTE 'DROP ROLE {ROLE_NAME}';
    EXCEPTION WHEN dependent_objects_still_exist THEN
      -- Objects in ANOTHER database of this cluster still depend on the role.
      -- Unreachable from here by construction. Keep the role, keep the
      -- downgrade honest, and say so.
      RAISE NOTICE
        'role {ROLE_NAME} kept: objects in another database of this cluster '
        'still depend on it. Every privilege it held in THIS database has been '
        'removed. Drop the role manually once no database references it.';
    END;
  END IF;
END
$drop_role$;
"""  # nosec B608 — role is a fixed constant
    op.execute(sql)

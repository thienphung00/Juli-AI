"""Create non-owner runtime role juli_app with explicit per-table grants (ADR-085 #1326)

Revision ID: 043_juli_app_role
Revises: 041_stop_reason_diverged
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
- Table-level SELECT/INSERT/DELETE per table from an explicit map, never ALL TABLES IN SCHEMA
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

revision: str = "043_juli_app_role"
down_revision: str | None = "041_stop_reason_diverged"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
SCHEMAS = ("public", "bronze", "silver", "ops", "gold")

# Explicit per-table grant map: table -> (SELECT?, INSERT?)
# Derived from backend repositories; webhook_raw_events has INSERT only
GRANT_MAP = {
    "public": {
        # SELECT and INSERT on all public tables except webhook_raw_events
        "users": ("SELECT", "INSERT"),
        "shops": ("SELECT", "INSERT"),
        "tiktok_credentials": ("SELECT", "INSERT"),
        "tiktok_sync_state": ("SELECT", "INSERT"),
        "orders": ("SELECT", "INSERT"),
        "products": ("SELECT", "INSERT"),
        "order_items": ("SELECT", "INSERT"),
        "inventory_items": ("SELECT", "INSERT"),
        "settlements": ("SELECT", "INSERT"),
        "creators": ("SELECT", "INSERT"),
        "livestreams": ("SELECT", "INSERT"),
        "analytics_performance_intervals": ("SELECT", "INSERT"),
        "alert_configs": ("SELECT", "INSERT"),
        "alert_history": ("SELECT", "INSERT"),
        "workflow_webhook_signals": ("SELECT", "INSERT"),
        "workflow_runs": ("SELECT", "INSERT"),
        "workflow_run_events": ("SELECT", "INSERT"),
        "run_confirmations": ("SELECT", "INSERT"),
        "tool_executions": ("SELECT", "INSERT"),
        "workflow_outcome_records": ("SELECT", "INSERT"),
        "impact_readings": ("SELECT", "INSERT"),
        "action_cards": ("SELECT", "INSERT"),
        "action_card_approvals": ("SELECT", "INSERT"),
        "recommendations": ("SELECT", "INSERT"),
        "campaigns": ("SELECT", "INSERT"),
        "graph_edges": ("SELECT", "INSERT"),
        "decision_emission_novelty_ledger": ("SELECT", "INSERT"),
        "demo_execution_records": ("SELECT", "INSERT"),
        "analytics_kpi_envelopes": ("SELECT", "INSERT"),
        "processed_events": ("SELECT", "INSERT"),
        "returns": ("SELECT", "INSERT"),
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
        # SELECT and INSERT on silver fact tables
        "orders": ("SELECT", "INSERT"),
        "returns": ("SELECT", "INSERT"),
    },
    "ops": {
        # SELECT and INSERT on analytics backfill state
        "analytics_backfill_partitions": ("SELECT", "INSERT"),
    },
    "gold": {
        # SELECT and INSERT on KPI envelopes
        "kpi_envelopes": ("SELECT", "INSERT"),
    },
}


def _grant_table_privileges() -> None:
    """Grant table-level privileges to juli_app from the explicit map."""
    for schema, tables in GRANT_MAP.items():
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


def _revoke_table_privileges() -> None:
    """Revoke all privileges from juli_app on all tables (downgrade path)."""
    for schema, tables in GRANT_MAP.items():
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

    Note: DROP ROLE fails loudly (not silently) if any session is connected as
    juli_app, which is correct — the runbook must say to cut DATABASE_URL back
    to 'postgres' before downgrading.
    """
    # Revoke table-level privileges
    _revoke_table_privileges()

    # Revoke USAGE on all runtime schemas
    for schema in SCHEMAS:
        sql = f"""
DO $revoke_schema_usage$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema}') THEN
    REVOKE USAGE ON SCHEMA {schema} FROM {ROLE_NAME};
  END IF;
END
$revoke_schema_usage$;
"""  # nosec B608 — schema/role are fixed module constants
        op.execute(sql)

    # Drop the role; fails loudly if sessions are connected as juli_app
    sql = f"DROP ROLE IF EXISTS {ROLE_NAME};"  # nosec B608 — role is a fixed constant
    op.execute(sql)

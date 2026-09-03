"""Grant SELECT on bronze raw-payload tables to juli_app (issue #1548).

Migration 043 granted INSERT only on the four bronze raw-payload tables,
assuming bronze is write-only (ingest path). The medallion READ path reads
from bronze in two locations:
  - services/cdp_speed/shared_compute_orchestrator.py: silver promotion
    selects from BronzeOrderRawPayload, BronzeReturnRawPayload,
    BronzeCtorPerformanceRawPayload, BronzeLiveHoursRawPayload
  - services/cdp_batch/partition_checkpoints.py: reconcile cursor
    recovery selects from BronzeOrderRawPayload

This migration grants SELECT only (verified: no UPDATE/DELETE on bronze
outside migrations), following 043's established GRANT_MAP + _grant_table_privileges
shape and its IF EXISTS guard.

Round-trip verified: upgrade → downgrade → upgrade on a test database
leaves the privilege set exactly as intended (INSERT from 043 untouched,
SELECT newly granted).
"""

from collections.abc import Sequence

from alembic import op

# Type alias for grant map structure: schema -> {table -> (privileges...)}
GrantMap = dict[str, dict[str, tuple[str, ...]]]

revision: str = "054_juli_app_bronze_select"
down_revision: str | None = "053_shops_shop_scope_select"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

# Grant map for bronze read path: SELECT only on raw payload tables
# This supplements (does not replace) 043's INSERT grants.
GRANT_MAP: GrantMap = {
    "bronze": {
        # SELECT on raw payload tables (medallion read path: silver promotion, reconcile)
        # Migration 043 keeps INSERT; this adds SELECT.
        "order_raw_payloads": ("SELECT",),
        "return_raw_payloads": ("SELECT",),
        "ctor_performance_raw_payloads": ("SELECT",),
        "live_hours_raw_payloads": ("SELECT",),
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
    """Revoke specified privileges from juli_app on all tables (downgrade path).

    Revokes only the privileges this migration granted (SELECT),
    leaving 043's INSERT intact.
    """
    for schema, tables in grant_map.items():
        for table, verbs in tables.items():
            verb_str = ", ".join(verbs)
            sql = f"""
DO $revoke_table$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}') THEN
    REVOKE {verb_str} ON {schema}.{table} FROM {ROLE_NAME};
  END IF;
END
$revoke_table$;
"""  # nosec B608 — schema/table/role/verbs are fixed module constants
            op.execute(sql)


def upgrade() -> None:
    """Grant SELECT on bronze raw-payload tables to juli_app.

    This supplements (does not replace) migration 043's INSERT grants.
    The role already exists; no role creation needed.
    Idempotent: IF EXISTS guard allows re-running.
    """
    _grant_table_privileges()


def downgrade() -> None:
    """Revoke SELECT from juli_app on bronze raw-payload tables.

    Migration 043's INSERT grants remain intact. This mirrors the
    specific-revoke pattern of 043's downgrade (revoke what was
    granted, nothing more).
    """
    _revoke_table_privileges()

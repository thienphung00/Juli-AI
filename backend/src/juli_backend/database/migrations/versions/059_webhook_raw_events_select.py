"""Grant SELECT on public.webhook_raw_events to juli_app (issue #1966).

Migration 043 granted `juli_app` INSERT only on `webhook_raw_events` (ADR-085
decision 3: "no tenant lineage, no read grant"). `WebhookRawEventsRepo.insert`
goes through `SessionRepo._add`, which every repository in this package uses:

    self._session.add(entity)
    await self._session.flush()

`WebhookRawEvent.received_at` (models/models.py) carries `server_default=func.now()`
-- a server-generated column the ORM must read back to populate the in-memory
object after INSERT. SQLAlchemy's asyncpg dialect does that with

    INSERT INTO webhook_raw_events (...) VALUES (...) RETURNING webhook_raw_events.received_at

and `RETURNING` requires SELECT on every column it returns, not just INSERT on
the table. Decision 3 treated "no tenant lineage" and "no read grant" as the
same axis; they are not. The ORM's own flush semantics need SELECT regardless
of whether any tenant-scoped *query* is ever issued against this table -- so
the decision was right about RLS (no tenant-scoped policy is needed, and none
is added here) and wrong about the grant.

Production, over the 24h ending 2026-09-14: 310 `webhook_raw_log_failed` log
lines (173 order_status_change, 77 inventory_changed, 47
product_audit_status_change, plus others), each

    asyncpg.exceptions.InsufficientPrivilegeError: permission denied for table webhook_raw_events

`TikTokWebhookService._safe_record` (services/tiktok/webhook.py) catches and
logs that exception rather than propagating it, so every one of those
deliveries still returned HTTP 200 to TikTok. TikTok reads 200 as delivered and
never retries -- this was unretryable audit-log data loss, not merely a slow
write path.

AUDIT OF THE OTHER INGEST TABLES (issue #1966 item 2). `webhook_raw_events` is
the only table in the 043/054/055/058 grant maps ever left at
INSERT-only: every other table that starts at ("INSERT",) is one of the four
bronze raw-payload tables, and those already received SELECT in migration 054
(#1548) for the same reason -- a medallion read path needed it. `orders`,
`processed_events`, `inventory_items`, and every other table this application
writes through `SessionRepo._add`/`ShopScopedRepo.upsert` already carries
SELECT from 043 (see that migration's GRANT_MAP). So this migration closes the
one remaining instance of the class, not one of several.

WHY SELECT ONLY, AND NOT ALSO A SHOP-SCOPED RLS POLICY. This table carries no
`shop_id` (`032_close_public_schema_defaults.py`, `045_rls_policies.py`) and
none is added here -- ADR-085 decision 3's "no tenant lineage" holds; only its
"no read grant" half is reversed. `webhook_raw_events` remains a read-only
audit shim with no RLS policy, exactly as 045/046 left it.

Follows 054's GRANT_MAP shape, guarded like 058: `pg_roles` covers a database
in this cluster that has not yet run 043 (the role is cluster-global, the
migration is not), `pg_tables` covers a database migrated only part way.
`054` alone guards on `pg_tables` only, which is fine on a database that has
already run 043 -- but leaving `pg_roles` off means an unguarded `GRANT ...
TO juli_app` against a sibling database in the same cluster that has not yet
run 043 raises `role "juli_app" does not exist` instead of skipping cleanly,
same failure 058's docstring calls out. This migration is not first past 043
either, so it takes 058's belt-and-suspenders shape rather than 054's.

`downgrade` revokes exactly the SELECT this migration granted; 043's INSERT
survives it, and the incident reproduces -- the honest consequence of reverting.
"""

from collections.abc import Sequence

from alembic import op

# Type alias for grant map structure: schema -> {table -> (privileges...)}
GrantMap = dict[str, dict[str, tuple[str, ...]]]

revision: str = "059_webhook_raw_events_select"
down_revision: str | None = "058_juli_app_update_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

# SELECT only on webhook_raw_events. Migration 043 keeps INSERT; this adds the
# SELECT that every flush()'s RETURNING clause needs, regardless of tenancy.
GRANT_MAP: GrantMap = {
    "public": {
        "webhook_raw_events": ("SELECT",),
    },
}


def _apply_table_privileges(keyword: str, grant_map: GrantMap = GRANT_MAP) -> None:
    """GRANT or REVOKE the mapped privileges, guarded on the role and the table.

    Two guards, for two different absences. `pg_roles` covers a database in this
    cluster that has not yet run 043 (the role is cluster-global, the migration
    is not); `pg_tables` covers a database migrated only part way. Either way the
    statement is skipped rather than failed, which is what makes this idempotent.
    Mirrors 058's `_apply_table_privileges` exactly.
    """
    preposition = "TO" if keyword == "GRANT" else "FROM"
    for schema, tables in grant_map.items():
        for table, verbs in tables.items():
            verb_str = ", ".join(verbs)
            sql = f"""
DO $apply_select_grant$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}')
     AND EXISTS (
       SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}'
     ) THEN
    EXECUTE '{keyword} {verb_str} ON {schema}.{table} {preposition} {ROLE_NAME}';
  END IF;
END
$apply_select_grant$;
"""  # nosec B608 — schema/table/role/verbs are fixed module constants
            op.execute(sql)


def _grant_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Grant the mapped SELECT privilege to juli_app."""
    _apply_table_privileges("GRANT", grant_map)


def _revoke_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Revoke only the SELECT this migration granted; 043's INSERT remains."""
    _apply_table_privileges("REVOKE", grant_map)


def upgrade() -> None:
    """Grant SELECT on webhook_raw_events to juli_app.

    Supplements (does not replace) migration 043's INSERT grant. The role
    already exists; no role creation needed. Idempotent: IF EXISTS guard
    allows re-running.
    """
    _grant_table_privileges()


def downgrade() -> None:
    """Revoke SELECT from juli_app on webhook_raw_events.

    Migration 043's INSERT grant remains intact. Mirrors the specific-revoke
    pattern of 043/054/058's downgrades (revoke what was granted, nothing more).
    """
    _revoke_table_privileges()

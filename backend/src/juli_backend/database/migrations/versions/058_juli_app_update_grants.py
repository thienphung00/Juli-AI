"""Grant UPDATE on the six tables juli_app mutates but could not write (issue #1897).

`run_confirmations` granted `juli_app` INSERT and SELECT and no UPDATE, so
`services/agent_runs/confirmations.py:116`'s

    UPDATE run_confirmations SET status=..., selected_option_id=..., decided_at=...
    WHERE id=... AND status='pending'

raised on every seller decision. Production, 2026-09-10 06:34:03Z, request
`07cb7ab2-40d7-4d26-aa2a-556428e8f884`, release `1a890bab`:

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for table run_confirmations

The entire human-in-the-loop write path was dead: a confirmation could be
raised and displayed, and no approve or decline could ever be recorded.

This is a GRANT gap, not an RLS one, and the two fail differently. A policy
denial returns zero rows; a missing privilege raises. Both `run_confirmations`
and every table below already carries its `_update_public` policy from
migration 045/046 — the policy was never the problem.

WHY SIX TABLES AND NOT SEVENTEEN. Seventeen public tables held SELECT with no
UPDATE. Each was audited against the code for `update(Model)`, `delete(Model)`,
ORM attribute assignment on a loaded row followed by a flush, `session.merge`,
and raw SQL. Six mutate; eleven are genuinely append-only and stay ungranted:
`action_card_approvals`, `alert_history`, `decision_emission_novelty_ledger`,
`impact_readings`, `production_write_audit`, `recommendations`, `users`,
`workflow_outcome_records`, `workflow_run_events`, `workflow_webhook_signals`
(each has a `create`/`insert` path and no mutation site), and
`analytics_kpi_envelopes`, which is a special case: since the #606 gold cutover
`AnalyticsKpiEnvelopesRepo` builds a TRANSIENT view object via
`_gold_to_legacy_envelope` that is never added to a session, and the durable
write goes to `gold.kpi_envelopes` — which already holds UPDATE from 043.

UPDATE ONLY, DELIBERATELY. The audit found no `delete(Model)` and no
`session.delete` anywhere in the application on any mapped table, so DELETE
stays ungranted on all six (least privilege). INSERT and SELECT are already
held from 043 and are untouched here.

Per table, with the call site that requires it:

  run_confirmations      services/agent_runs/confirmations.py:116
                         `update(RunConfirmation)` — the seller's approve or
                         decline, atomically out of 'pending'. THE INCIDENT.
  shops                  repositories/identity.py:142
                         `shop.is_active = False` — ShopsRepo.pause_automation,
                         run when the seller deauthorizes the app (#354).
  alert_configs          services/alerts/engine.py:48-51
                         `existing.channel = rule.channel` (+ is_active,
                         threshold_json) then `session.flush()` — configure_rules
                         rewrites an existing rule rather than inserting a second.
  campaigns              services/feedback/outcome_ingest.py:70-78, :92
                         `campaign.status = "completed"` (+ realized/predicted
                         figures, completed_at, idempotency_key) then flush —
                         ingest_campaign_outcome closes an existing campaign.
  graph_edges            repositories/graph.py:46-51
                         `existing.weight/metadata_json/computed_at` then flush —
                         GraphRepo.upsert_edge refreshes an existing edge's
                         measurements instead of duplicating it.
  demo_execution_records services/demo_execution/dry_run.py:135-153
                         the row is INSERTed as 'queued' and flushed, then walked
                         to 'running' and 'done' with completed_at and
                         narrative_json — three UPDATEs after the insert.

Follows the `GrantMap` + `_grant_table_privileges` / `_revoke_table_privileges`
shape of 043/054/055, and adds 048's `pg_roles` guard beside their `pg_tables`
one: a role is cluster-global while a migration is per-database, so a database
in the same cluster that has not yet run 043 must not fail an unguarded GRANT.

`downgrade` revokes exactly the UPDATE this migration granted and nothing else;
043's SELECT and INSERT survive it. Approvals break again, which is the honest
consequence of reverting.
"""

from collections.abc import Sequence

from alembic import op

# Type alias for grant map structure: schema -> {table -> (privileges...)}
GrantMap = dict[str, dict[str, tuple[str, ...]]]

revision: str = "058_juli_app_update_grants"
down_revision: str | None = "057_workflow_run_rollup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

GRANT_MAP: GrantMap = {
    "public": {
        # SELECT + INSERT already granted by 043; each of these adds the UPDATE
        # its own code path issues. See the module docstring for the call site.
        "run_confirmations": ("UPDATE",),  # confirmations.py:116 update(RunConfirmation)
        "shops": ("UPDATE",),  # identity.py:142 shop.is_active = False
        "alert_configs": ("UPDATE",),  # alerts/engine.py:48 existing.channel = ...
        "campaigns": ("UPDATE",),  # outcome_ingest.py:76 campaign.status = "completed"
        "graph_edges": ("UPDATE",),  # graph.py:46 existing.weight = weight
        "demo_execution_records": ("UPDATE",),  # dry_run.py:145 record.completed_at = ...
    },
}


def _apply_table_privileges(keyword: str, grant_map: GrantMap = GRANT_MAP) -> None:
    """GRANT or REVOKE the mapped privileges, guarded on the role and the table.

    Two guards, for two different absences. `pg_roles` covers a database in this
    cluster that has not yet run 043 (the role is cluster-global, the migration
    is not); `pg_tables` covers a database migrated only part way. Either way the
    statement is skipped rather than failed, which is what makes this idempotent.
    """
    preposition = "TO" if keyword == "GRANT" else "FROM"
    for schema, tables in grant_map.items():
        for table, verbs in tables.items():
            verb_str = ", ".join(verbs)
            sql = f"""
DO $apply_update_grant$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}')
     AND EXISTS (
       SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}'
     ) THEN
    EXECUTE '{keyword} {verb_str} ON {schema}.{table} {preposition} {ROLE_NAME}';
  END IF;
END
$apply_update_grant$;
"""  # nosec B608 — schema/table/role/verbs are fixed module constants
            op.execute(sql)


def _grant_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Grant the mapped UPDATE privileges to juli_app."""
    _apply_table_privileges("GRANT", grant_map)


def _revoke_table_privileges(grant_map: GrantMap = GRANT_MAP) -> None:
    """Revoke only the UPDATE this migration granted; 043's SELECT/INSERT remain."""
    _apply_table_privileges("REVOKE", grant_map)


def upgrade() -> None:
    """Grant UPDATE on the six mutated tables. Additive privileges only, no data change."""
    _grant_table_privileges()


def downgrade() -> None:
    """Revoke exactly the six UPDATE grants, leaving every other privilege intact."""
    _revoke_table_privileges()

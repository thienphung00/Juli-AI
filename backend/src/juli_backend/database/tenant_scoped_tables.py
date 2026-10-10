"""Tenant-scoped table classification map (issue #1329, #1330, ADR-085 decision 3).

This module is the single source of truth for which tables enforce row-level
security based on shop_id (tenant isolation). Both the isolation proof (#1329)
and the boot-time precondition check (#1330) consume this map to verify:

1. Every table in pg_catalog with shop_id is classified
2. Every RLS policy is in effect for production-write-capable deployments
3. No table bypasses isolation via unclassified schema access

The classification is committed (must be complete — an unclassified table FAILS
the proof). Each table is classified as one of:

- "tenant_direct": has shop_id column, RLS policy compares shop_id directly
- "tenant_via_parent": child of a tenant_direct table, RLS policy uses EXISTS
- "non_tenant": shared across tenants, user_id or app.current_user_id keyed
- "non_tenant_unprotected": no RLS policy (webhook_raw_events only)
- "ops_only": internal Juli Ops console tables (fast track P16, migration 083).
  Some carry a ``shop_id`` (the shop a setting / audit row / invite is ABOUT),
  but they are not tenant data: RLS is on, the only policy is ``TO juli_ops``
  and ``juli_app`` has no grant at all, so no seller path can read them.
"""

from __future__ import annotations

#: Classification map for every table that may hold data in the runtime.
#: Keys are (schema, table) tuples. Values are classification strings.
TABLE_CLASSIFICATION_MAP = {
    # Direct tenant-scoped tables (shop_id column)
    ("public", "tiktok_credentials"): "tenant_direct",
    ("public", "tiktok_sync_state"): "tenant_direct",
    ("public", "orders"): "tenant_direct",
    ("public", "order_items"): "tenant_direct",
    ("public", "returns"): "tenant_direct",
    ("public", "products"): "tenant_direct",
    ("public", "inventory_items"): "tenant_direct",
    ("public", "settlements"): "tenant_direct",
    ("public", "creators"): "tenant_direct",
    ("public", "livestreams"): "tenant_direct",
    ("public", "analytics_performance_intervals"): "tenant_direct",
    ("public", "alert_configs"): "tenant_direct",
    ("public", "alert_history"): "tenant_direct",
    ("public", "workflow_webhook_signals"): "tenant_direct",
    ("public", "workflow_runs"): "tenant_direct",
    ("public", "tool_executions"): "tenant_direct",
    ("public", "workflow_outcome_records"): "tenant_direct",
    ("public", "action_cards"): "tenant_direct",
    ("public", "decision_emission_novelty_ledger"): "tenant_direct",
    ("public", "demo_execution_records"): "tenant_direct",
    ("public", "recommendations"): "tenant_direct",
    ("public", "campaigns"): "tenant_direct",
    ("public", "graph_edges"): "tenant_direct",
    ("public", "analytics_kpi_envelopes"): "tenant_direct",
    ("silver", "orders"): "tenant_direct",
    ("silver", "returns"): "tenant_direct",
    ("ops", "analytics_backfill_partitions"): "tenant_direct",
    ("gold", "kpi_envelopes"): "tenant_direct",
    ("gold", "ml_feature_snapshots"): "tenant_direct",
    ("bronze", "order_raw_payloads"): "tenant_direct",
    ("bronze", "return_raw_payloads"): "tenant_direct",
    ("bronze", "ctor_performance_raw_payloads"): "tenant_direct",
    ("bronze", "live_hours_raw_payloads"): "tenant_direct",
    ("public", "processed_events"): "tenant_direct",
    ("public", "ingest_dedup_epochs"): "tenant_direct",
    ("public", "production_write_authorizations"): "tenant_direct",
    ("public", "production_write_audit"): "tenant_direct",
    # W9-A/P-SHARED-12 (#1712), migration 069. Both hang off a run and would
    # normally be "tenant_via_parent" like workflow_run_events — but each
    # carries its own shop_id, kept un-driftable by a composite foreign key
    # onto workflow_runs (id, shop_id), so the direct policy is both correct
    # and the one the seller's timeline can read without a join. There is no
    # reader or writer yet; #1713 adds the producer.
    ("public", "run_act_records"): "tenant_direct",
    ("public", "run_checklist_items"): "tenant_direct",
    # Fast track P1-B, migration 074: per-shop bootstrap state, keyed on shop_id.
    ("public", "shop_ingestion_state"): "tenant_direct",
    # Fast track P7-A, migration 076: stored ADR-108 shop diagnosis reports.
    ("public", "shop_diagnosis_reports"): "tenant_direct",
    # Fast track P8-A, migration 077: stored ADR-109 d.5 metric rankings.
    ("public", "shop_metric_rankings"): "tenant_direct",
    # Fast track P8-C, migration 078: before/after values of agent writes, the
    # seller-set rule store, and the day-7 "Hoàn tác?" questions.
    ("public", "run_write_values"): "tenant_direct",
    ("public", "shop_rules"): "tenant_direct",
    ("public", "run_revert_questions"): "tenant_direct",
    # Fast track P10-A, migration 079: seller reasons for reject/decline/revert
    # (and the 7-day per-lever cooldown they start).
    ("public", "decision_reasons"): "tenant_direct",
    # Fast track P10-B, migration 080: cover-image / promotion lever flows, the
    # photos they show, per-lever calibration and day-14 verdicts.
    ("public", "run_lever_flows"): "tenant_direct",
    ("public", "run_lever_photos"): "tenant_direct",
    ("public", "lever_calibrations"): "tenant_direct",
    ("public", "run_measurement_finals"): "tenant_direct",
    # Fast track P14-C, migration 081: per-order price detail (seller vs
    # platform deductions), finance transactions and their fetch state.
    ("public", "order_price_details"): "tenant_direct",
    ("public", "order_finance_transactions"): "tenant_direct",
    ("public", "order_cost_fetches"): "tenant_direct",
    # Fast track P15, migration 082: derived data of seller-uploaded videos /
    # LIVE recordings (the media itself is never stored in the database).
    ("public", "content_analyses"): "tenant_direct",
    # Via-parent tenant-scoped tables
    ("public", "workflow_run_events"): "tenant_via_parent",
    ("public", "run_confirmations"): "tenant_via_parent",
    ("public", "impact_readings"): "tenant_via_parent",
    ("public", "action_card_approvals"): "tenant_via_parent",
    # Non-tenant tables
    ("public", "users"): "non_tenant",
    ("public", "shops"): "non_tenant",
    ("public", "webhook_raw_events"): "non_tenant_unprotected",
    # Fast track P16 (D25), migration 083: the Juli Ops console. Reached only
    # through the ``juli_ops`` role on the /v1/ops path; never a tenant read.
    ("public", "ops_staff"): "ops_only",
    ("public", "ops_audit_log"): "ops_only",
    ("public", "ops_shop_settings"): "ops_only",
    ("public", "ops_sim_scenarios"): "ops_only",
    ("public", "ops_shop_invites"): "ops_only",
}

#: Metadata about via-parent relationships (child_table -> (parent_table, fk_col, pk_col))
VIA_PARENT_MAPPINGS = {
    ("public", "workflow_run_events"): ("workflow_runs", "workflow_run_id", "id"),
    ("public", "run_confirmations"): ("workflow_runs", "workflow_run_id", "id"),
    ("public", "impact_readings"): ("tool_executions", "tool_execution_id", "id"),
    ("public", "action_card_approvals"): ("action_cards", "action_card_id", "id"),
}


def get_ops_only_tables() -> list[tuple[str, str]]:
    """The Juli Ops tables (RLS on, ``juli_ops`` only, no ``juli_app`` grant)."""
    return [key for key, value in TABLE_CLASSIFICATION_MAP.items() if value == "ops_only"]


def get_tenant_scoped_tables() -> list[tuple[str, str]]:
    """Get all tenant-scoped tables (direct and via-parent).

    Returns:
        List of (schema, table) tuples for tables that must have RLS enabled.
    """
    return [
        (schema, table)
        for (schema, table), classification in TABLE_CLASSIFICATION_MAP.items()
        if classification in ("tenant_direct", "tenant_via_parent")
    ]

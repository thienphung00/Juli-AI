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
    # Fast track P61-B, migration 097: the owner's per-shop production write
    # enable (juli_app SELECT only).
    ("public", "production_write_shops"): "tenant_direct",
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
    # Fast track P18 (D27.2, migration 085): compact daily counts for Ops "Mô phỏng".
    ("public", "shop_daily_streams"): "tenant_direct",
    ("public", "shop_daily_products"): "tenant_direct",
    # Fast track P20 (D28.4, migration 086): shop subscription periods (append-only).
    ("public", "shop_subscription_periods"): "tenant_direct",
    # Fast track P23 (D30.1 / D30.4, migration 087): product history, promotions,
    # external changes (append-only except the promotion upserts) and run baselines.
    ("public", "product_snapshots"): "tenant_direct",
    ("public", "promotion_activities"): "tenant_direct",
    ("public", "promotion_activity_products"): "tenant_direct",
    ("public", "external_changes"): "tenant_direct",
    ("public", "run_baselines"): "tenant_direct",
    # Fast track P24 (D31.3 / D31.4, migration 088): the ingest gateway and the
    # Juli Connector pairing. ``ingest_pairing_codes``' SELECT policy also admits
    # the one row whose code hash the redeemer asserts (no shop known yet).
    ("public", "ingest_pairing_codes"): "tenant_direct",
    ("public", "ingest_tokens"): "tenant_direct",
    ("public", "ingest_raw_payloads"): "tenant_direct",
    ("public", "platform_daily_metrics"): "tenant_direct",
    # ADR-117 (migration 108): Shopee Seller Centre files beside the daily table --
    # period totals, items / variations, Shopee's product flags, promotion programs.
    ("public", "platform_period_metrics"): "tenant_direct",
    ("public", "platform_items"): "tenant_direct",
    ("public", "platform_product_flags"): "tenant_direct",
    ("public", "platform_promotions"): "tenant_direct",
    ("public", "ingest_dataset_status"): "tenant_direct",
    # ADR-118 (migration 109): the manual cycle -- proposals, the client's approvals,
    # executions made on the shop, measurement results.
    ("public", "shop_proposals"): "tenant_direct",
    ("public", "shop_proposal_approvals"): "tenant_direct",
    ("public", "shop_proposal_executions"): "tenant_direct",
    ("public", "shop_proposal_results"): "tenant_direct",
    ("public", "shop_proposal_code_counters"): "tenant_direct",
    # P91 migration 117: the draft plan, its cards and counter, and the measurement change sets
    ("public", "shop_reco_plans"): "tenant_direct",
    ("public", "shop_reco_plan_cards"): "tenant_direct",
    ("public", "shop_reco_plan_counters"): "tenant_direct",
    # P97 D85.14 / P94 (migration 125): the groups of a plan ("Nhóm A, B ...") and their members.
    ("public", "shop_reco_plan_groups"): "tenant_direct",
    ("public", "shop_reco_plan_group_members"): "tenant_direct",
    ("public", "shop_reco_change_sets"): "tenant_direct",
    ("public", "planned_change_imports"): "tenant_direct",
    ("public", "planned_change_refs"): "tenant_direct",
    ("public", "shopee_sim_prior_runs"): "tenant_direct",
    ("public", "shopee_reco_calibrations"): "tenant_direct",
    # ADR-119 (migration 111): which keyword combinations came from which of the shop's
    # items (the decomposed titles); Ops reads and writes them under the shop's scope.
    ("public", "shop_keyword_seeds"): "tenant_direct",
    # ADR-120 (migration 112): Shopee profit and history -- item snapshots (append-only),
    # the private copy of each image version, PII-free order lines (hashed order ref),
    # append-only rule versions and ad-campaign purposes.
    ("public", "platform_item_snapshots"): "tenant_direct",
    ("public", "product_image_assets"): "tenant_direct",
    ("public", "shopee_order_lines"): "tenant_direct",
    ("public", "shop_rule_versions"): "tenant_direct",
    ("public", "ad_campaign_purposes"): "tenant_direct",
    # P90 step 2 (migration 113): account-health readings and the ad change log, both
    # append-only (SELECT / INSERT for juli_app).
    ("public", "shop_health_daily"): "tenant_direct",
    ("public", "ads_change_log"): "tenant_direct",
    # P91 D-12 (migration 119): what Shopee actually charged and paid per order (the income
    # export), keyed by the same hashed order ref as the order lines.
    ("public", "shopee_order_income"): "tenant_direct",
    # P96 (migration 122): affiliate order lines of the conversion report, stored on their own
    # (the KOL tab no longer needs the order export); same hashed order ref, KOL handle only.
    ("public", "shopee_affiliate_lines"): "tenant_direct",
    # P97 D85.2 / D85.4 (migration 123): the materialized shop and product metrics per day and
    # the frozen base of a draft plan.
    ("public", "shopee_shop_metrics_daily"): "tenant_direct",
    ("public", "shopee_product_metrics_daily"): "tenant_direct",
    ("public", "shopee_plan_base_snapshots"): "tenant_direct",
    # P97 D85.6 (migration 124): the fill queue the Connector works through after an approval.
    ("public", "shopee_fill_jobs"): "tenant_direct",
    # Fast track P30 (D34 / D39.3, migration 089): card groups with a randomised
    # delayed control and their members (arm per product).
    ("public", "card_groups"): "tenant_direct",
    ("public", "card_group_members"): "tenant_direct",
    # Fast track P60-1a (D70.9, migration 095): the card journey log,
    # append-only (SELECT / INSERT for juli_app).
    ("public", "card_events"): "tenant_direct",
    # NDA work (D76, ADR-116 §2, migration 103): per-shop data-use consent;
    # juli_app SELECT / INSERT, UPDATE (revoked_at) on an open row only.
    ("public", "data_use_consents"): "tenant_direct",
    # NDA work (D76, ADR-116 §4, migration 104): per-shop sealed HMAC key for
    # buyer_id pseudonyms; juli_app SELECT / INSERT only.
    ("public", "shop_pseudonym_keys"): "tenant_direct",
    # NDA work (D76, ADR-116 §5, migration 105): one row per OpenAI call attempt,
    # metadata only; append-only (SELECT / INSERT for juli_app).
    ("public", "llm_call_log"): "tenant_direct",
    # Via-parent tenant-scoped tables
    ("public", "workflow_run_events"): "tenant_via_parent",
    ("public", "run_confirmations"): "tenant_via_parent",
    ("public", "impact_readings"): "tenant_via_parent",
    ("public", "action_card_approvals"): "tenant_via_parent",
    # Non-tenant tables
    ("public", "users"): "non_tenant",
    ("public", "shops"): "non_tenant",
    # P93 (migration 121): who may act on a shop. Keyed on ``user_id`` like ``shops`` (juli_app
    # SELECT of its own rows only; ``juli_ops`` writes), read by the ``shops`` policies.
    ("public", "shop_members"): "non_tenant",
    ("public", "webhook_raw_events"): "non_tenant_unprotected",
    # Fast track P20 (D28.3, migration 086): system-wide Ops settings (the OpenAI
    # system cap). No shop data: RLS on, juli_ops writes, juli_app may only read.
    ("public", "ops_system_settings"): "non_tenant",
    # ADR-120 (migration 112): the platform's public fee policy per category, versioned.
    # No shop data: RLS on, juli_ops writes, juli_app may only read (same shape).
    ("public", "platform_fee_formulas"): "non_tenant",
    # Fast track P16 (D25), migration 083: the Juli Ops console. Reached only
    # through the ``juli_ops`` role on the /v1/ops path; never a tenant read.
    ("public", "ops_staff"): "ops_only",
    ("public", "ops_audit_log"): "ops_only",
    ("public", "ops_shop_settings"): "ops_only",
    ("public", "ops_sim_scenarios"): "ops_only",
    ("public", "ops_shop_invites"): "ops_only",
    ("public", "ops_shop_daily_summary"): "ops_only",
    # Fast track P32-A (D42, migration 090): partner reviewer trial accounts.
    ("public", "ops_reviewer_accounts"): "ops_only",
    # Fast track P33-F (D43, migration 091): free-trial sign-ups from app-juli.com.
    ("public", "trial_signups"): "ops_only",
    # D76 / D15 (migration 107): who contributed to a persisted pooled figure -- shop
    # ids and counts only, written and read through ``juli_ops``.
    ("public", "pooled_contributor_sets"): "ops_only",
    # ADR-117 §4 (migration 108): contract KPI versions, targets, adjustments, excluded
    # days, lever plans and forecasts -- never shown to a seller, ``juli_ops`` only.
    ("public", "kpi_contracts"): "ops_only",
    ("public", "kpi_targets"): "ops_only",
    ("public", "kpi_adjustments"): "ops_only",
    ("public", "kpi_exclusions"): "ops_only",
    ("public", "lever_plans"): "ops_only",
    ("public", "kpi_forecasts"): "ops_only",
    # ADR-117 §5 (migration 108): the public Shopee market lane (ADR-116 §1) -- no
    # ``shop_id``; Ops-only until a seller-facing reader exists.
    ("public", "market_listing_snapshots"): "ops_only",
    ("public", "market_keyword_snapshots"): "ops_only",
    # ADR-119 (migration 111): shopeeanalytics.com keyword metrics the owner collects --
    # public lane, no ``shop_id``; Ops-only.
    ("public", "market_keyword_metrics"): "ops_only",
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

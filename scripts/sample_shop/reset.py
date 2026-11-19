"""Reset the sample shop: delete every row the shop accumulated, then the loader re-seeds it.

    python -m scripts.sample_shop --reset --database-url "$DATABASE_DIRECT_URL" \
        --allow-remote-database            # preview: counts per table, rolled back
    python -m scripts.sample_shop --reset --yes --database-url ... --allow-remote-database

An operator command on the migration OWNER connection (``DATABASE_DIRECT_URL``), never
``juli_app``: the append-only tables (card events, approvals, ...) stay ungranted for the app, so
reviewers' actions accumulate until the owner runs this (P100 S2-G, owner decision (c)).

Safety (all before anything is deleted):
- the shop must pass the loader's ``check_target``: Shopee, ``shopee_shop_id`` in the reserved
  synthetic range, no credential, not Fujiwa or the sandbox shop;
- the tables come from the live catalogue (every table with a ``shop_id`` column, plus the
  ``shop_id``-less tables whose foreign key points at one of them); every DELETE is filtered to
  this one shop's rows; one transaction, so a failure deletes nothing;
- kept: the ``shops`` row (its id is in ``REVIEWER_SHOP_IDS``), consent, membership, the audit
  log (``reviewer_sample_write`` rows) and the per-shop settings in ``KEEP_TABLES``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: Rows the reset leaves in place (``schema.table``).
KEEP_TABLES = frozenset(
    {
        "public.shops",
        "public.data_use_consents",
        "public.shop_members",
        "public.ops_shop_invites",
        "public.ops_audit_log",
        "public.ops_shop_settings",
        "public.shop_pseudonym_keys",
        "public.shop_subscription_periods",
        "public.llm_call_log",
    }
)

#: What a RELOAD replaces (``loader.load``): the data the loader posts (the raw payloads, so a
#: repeat post is not a duplicate that hides the new window) and every table built from it.
#: Everything else in the plan -- cards, approvals, plans, groups, comments, card events, the
#: seeded content and history -- is a reviewer's or the seed's and stays; only ``--reset``
#: removes it.
GENERATED_TABLES = frozenset(
    {
        "bronze.order_raw_payloads",
        "bronze.return_raw_payloads",
        "bronze.ctor_performance_raw_payloads",
        "bronze.live_hours_raw_payloads",
        "silver.orders",
        "silver.returns",
    }
    | {
        f"public.{t}"
        for t in (
            "ingest_raw_payloads",
            "ingest_dataset_status",
            "platform_daily_metrics",
            "platform_period_metrics",
            "order_items",
            "order_lines",
            "order_price_details",
            "order_settlements",
            "order_finance_transactions",
            "order_cost_fetches",
            "settlements",
            "affiliate_lines",
            "ads_change_log",
            "shop_health_daily",
            "shop_metrics_daily",
            "product_metrics_daily",
            "source_metrics_daily",
            "shop_daily_products",
            "shop_daily_streams",
            "shop_metric_rankings",
            "product_snapshots",
            "stock_history",
            "shop_ingestion_state",
        )
    }
)

#: Kept on a reload: what reviewers and the product did (cards, approvals, plans, groups, runs,
#: measurements, alerts, connector state, credentials). Only ``--reset`` removes it.
REVIEWER_TABLES = frozenset(
    {"gold.kpi_envelopes", "ops.analytics_backfill_partitions"}
    | {
        f"public.{t}"
        for t in (
            "action_cards", "action_card_approvals", "card_events", "card_group_members",
            "card_groups", "shop_proposals", "shop_proposal_approvals",
            "shop_proposal_code_counters", "shop_proposal_executions", "shop_proposal_results",
            "shop_reco_change_sets", "shop_reco_plan_cards", "shop_reco_plan_counters",
            "shop_reco_plan_group_members", "shop_reco_plan_groups", "shop_reco_plans",
            "shopee_plan_base_snapshots", "shopee_connector_commands", "shopee_connector_state",
            "shopee_connector_token_state", "shopee_fill_jobs", "shopee_reco_calibrations",
            "shopee_sim_prior_runs", "shopee_stock_alert_sends", "shopee_stock_alert_unsubscribes",
            "alert_configs", "alert_history", "decision_reasons",
            "decision_emission_novelty_ledger", "demo_execution_records", "external_changes",
            "planned_change_imports", "planned_change_refs", "lever_calibrations", "lever_plans",
            "run_baselines", "run_lever_flows", "run_lever_photos", "run_measurement_finals",
            "run_revert_questions", "run_write_values", "run_confirmations", "impact_readings",
            "workflow_runs", "workflow_run_events", "workflow_outcome_records",
            "workflow_webhook_signals", "tool_executions", "kpi_contracts", "kpi_forecasts",
            "kpi_adjustments", "kpi_exclusions", "kpi_targets", "analytics_kpi_envelopes",
            "analytics_performance_intervals", "shop_diagnosis_reports", "recommendations",
            "content_analyses", "campaigns", "ad_campaign_purposes", "production_write_audit",
            "production_write_authorizations", "production_write_shops", "ingest_pairing_codes",
            "ingest_tokens", "ingest_dedup_epochs", "tiktok_credentials", "tiktok_sync_state",
            "ops_sim_scenarios", "processed_events", "graph_edges",
        )
    }
)  # fmt: skip

#: Kept on a reload: the catalogue, rules and content the seed (or a Connector read) wrote once.
#: ``platform_promotions`` and ``platform_product_flags`` carry the load window's dates and
#: ``platform_items`` first/last seen days; ``platform_item_snapshots`` is also written by the seed.
SEED_TABLES = frozenset(
    f"public.{t}"
    for t in (
        "platform_items", "platform_item_snapshots", "platform_product_flags",
        "platform_promotions", "card_content_specs", "shop_keyword_seeds", "shop_rule_versions",
        "shop_rules", "product_image_assets", "products", "inventory_items",
        "shopee_sku_tracking", "creators", "livestreams", "promotion_activities",
        "promotion_activity_products", "ops_shop_daily_summary",
    )
)  # fmt: skip

_SHOP_TABLES = sa.text(
    """
    SELECT n.nspname, c.relname
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE a.attname = 'shop_id' AND a.attnum > 0 AND NOT a.attisdropped
      AND c.relkind IN ('r', 'p') AND NOT c.relispartition
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
    """
)

_FOREIGN_KEYS = sa.text(
    """
    SELECT cn.nspname, cc.relname, pn.nspname, pc.relname,
           ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(n, i)
                 JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n
                 ORDER BY k.i),
           ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(n, i)
                 JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.n
                 ORDER BY k.i)
    FROM pg_constraint con
    JOIN pg_class cc ON cc.oid = con.conrelid
    JOIN pg_namespace cn ON cn.oid = cc.relnamespace
    JOIN pg_class pc ON pc.oid = con.confrelid
    JOIN pg_namespace pn ON pn.oid = pc.relnamespace
    WHERE con.contype = 'f' AND NOT cc.relispartition
    """
)


class ResetRefused(Exception):
    """The catalogue holds a shape the reset does not handle; nothing was deleted."""


@dataclass(frozen=True)
class ForeignKey:
    child: str
    parent: str
    child_cols: tuple[str, ...]
    parent_cols: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    """Delete ``table``'s rows of the shop: by its own ``shop_id``, or through ``via``."""

    table: str
    via: ForeignKey | None = None


@dataclass
class ResetReport:
    shop_id: uuid.UUID
    committed: bool
    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def plan_deletes(
    shop_tables: set[str], fks: list[ForeignKey], keep: frozenset[str] = KEEP_TABLES
) -> list[Step]:
    """The DELETEs in a foreign-key-safe order (every referencing table before its parent)."""
    keep_set = set(keep)
    # a kept row may point at a shop row (shop_members.invite_id -> ops_shop_invites): keep that too
    changed = True
    while changed:
        changed = False
        for fk in fks:
            if fk.child in keep_set and fk.parent in shop_tables and fk.parent not in keep_set:
                keep_set.add(fk.parent)
                changed = True
    direct = {t for t in shop_tables if t not in keep_set}
    via: dict[str, ForeignKey] = {}
    for fk in fks:
        if fk.parent in direct and fk.child not in shop_tables and fk.child not in keep_set:
            if fk.child in via and via[fk.child].parent != fk.parent:
                continue  # one parent is enough to find the shop's rows
            via[fk.child] = fk
    for child, fk in via.items():
        for other in fks:
            if other.parent == child and other.child != child and other.child not in shop_tables:
                raise ResetRefused(
                    f"{other.child} references {child} (via {fk.parent}), which has no "
                    "shop_id: not handled"
                )
    tables = direct | set(via)
    children: dict[str, set[str]] = defaultdict(set)
    for fk in fks:
        if fk.child in tables and fk.parent in tables and fk.child != fk.parent:
            children[fk.parent].add(fk.child)
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(table: str, path: tuple[str, ...]) -> None:
        if state.get(table) == 2:
            return
        if state.get(table) == 1:
            raise ResetRefused(f"foreign-key cycle: {' -> '.join((*path, table))}")
        state[table] = 1
        for child in sorted(children[table]):
            visit(child, (*path, table))
        state[table] = 2
        order.append(table)

    for table in sorted(tables):
        visit(table, ())
    # `order` lists each table after every table that references it: children first
    return [Step(t, via.get(t)) for t in order]


def plan_reload_deletes(shop_tables: set[str], fks: list[ForeignKey]) -> list[Step]:
    """The reload's DELETEs: the generated tables of :func:`plan_deletes`, in the same order.

    Refused (nothing deleted) when a table that stays points at a generated one: the DELETE would
    fail on the foreign key, or leave a reviewer's row dangling."""
    steps = plan_deletes(shop_tables, fks)
    planned = {step.table for step in steps}
    for fk in fks:
        if (
            fk.parent in GENERATED_TABLES
            and fk.child in planned
            and fk.child not in GENERATED_TABLES
            and fk.child != fk.parent
        ):
            raise ResetRefused(
                f"{fk.child} references {fk.parent}, which a reload replaces: classify it"
            )
    return [step for step in steps if step.table in GENERATED_TABLES]


def _metadata_reload_steps() -> list[Step]:
    """The reload's DELETEs from the ORM metadata (non-Postgres databases): children first."""
    from juli_backend.database import Base

    return [
        Step(t.fullname)
        for t in reversed(Base.metadata.sorted_tables)
        if "shop_id" in t.c and not t.schema and f"public.{t.name}" in GENERATED_TABLES
    ]


def _table(qualified: str, *cols: str) -> sa.TableClause:
    schema, _, name = qualified.rpartition(".")
    return sa.table(name, *(sa.column(c) for c in cols), schema=schema or None)


def _delete(step: Step, shop_id: uuid.UUID) -> sa.Delete:
    if step.via is None:
        t = _table(step.table, "shop_id")
        return sa.delete(t).where(t.c.shop_id == shop_id)
    fk = step.via
    child = _table(fk.child, *fk.child_cols)
    parent = _table(fk.parent, "shop_id", *fk.parent_cols)
    keys = sa.select(*(parent.c[c] for c in fk.parent_cols)).where(parent.c.shop_id == shop_id)
    target = (
        child.c[fk.child_cols[0]]
        if len(fk.child_cols) == 1
        else sa.tuple_(*(child.c[c] for c in fk.child_cols))
    )
    return sa.delete(child).where(target.in_(keys))


async def read_catalogue(session: AsyncSession) -> tuple[set[str], list[ForeignKey]]:
    shop_tables = {f"{s}.{t}" for s, t in (await session.execute(_SHOP_TABLES)).all()}
    fks = [
        ForeignKey(f"{cs}.{ct}", f"{ps}.{pt}", tuple(cc), tuple(pc))
        for cs, ct, ps, pt, cc, pc in (await session.execute(_FOREIGN_KEYS)).all()
    ]
    return shop_tables, fks


async def wipe(
    factory: async_sessionmaker[AsyncSession],
    shop_id: uuid.UUID,
    *,
    commit: bool,
    generated_only: bool = False,
) -> ResetReport:
    """Delete the shop's rows (``commit=False``: count them and roll back).

    ``generated_only``: just the loader's own data (:data:`GENERATED_TABLES`), as a reload does."""
    from juli_backend.database.tenant_context import with_shop_scope
    from scripts.sample_shop.loader import _has_credentials, check_target

    report = ResetReport(shop_id, committed=False)
    async with factory() as session:
        from juli_backend.database import Shop

        shop = await session.get(Shop, shop_id)
        if shop is None:
            raise ResetRefused(f"shop {shop_id} does not exist")
        check_target(
            shop.id,
            platform=shop.platform,
            shopee_shop_id=shop.shopee_shop_id,
            has_credentials=await _has_credentials(session, shop.id),
        )
        if generated_only and session.get_bind().dialect.name != "postgresql":
            steps = _metadata_reload_steps()  # the unit tests' SQLite: no pg catalogue to read
        else:
            plan = plan_reload_deletes if generated_only else plan_deletes
            steps = plan(*await read_catalogue(session))
        async with with_shop_scope(session, shop_id):
            for step in steps:
                result = await session.execute(_delete(step, shop_id))
                if result.rowcount:
                    report.deleted[step.table] = result.rowcount
        if commit:
            await session.commit()
            report.committed = True
        else:
            await session.rollback()
    return report


async def replace_generated(
    factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID
) -> ResetReport:
    """A reload's first step: drop the shop's generated data (one transaction, this shop only)."""
    return await wipe(factory, shop_id, commit=True, generated_only=True)


__all__ = [
    "GENERATED_TABLES",
    "KEEP_TABLES",
    "REVIEWER_TABLES",
    "SEED_TABLES",
    "ForeignKey",
    "ResetRefused",
    "ResetReport",
    "Step",
    "plan_deletes",
    "plan_reload_deletes",
    "replace_generated",
    "read_catalogue",
    "wipe",
]

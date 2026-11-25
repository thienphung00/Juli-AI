"""Data layer: stored daily components, campaign days, every card candidate (decisions #62-#66)

Revision ID: 140_data_layer_facts_opps
Revises: 139_hot_path_indexes
Create Date: 2026-11-25

Every number a Shopee screen, the Excel export or Chat reads is stored once per day as additive
components (ids of ``services/metrics/components.py``); ratios are evaluated at read time.

- ``shop_metrics_daily`` / ``product_metrics_daily``: the profit-ladder components (doanh thu
  thực, giá vốn, đóng gói, phí, vận chuyển ròng, Ưu đãi in its three parts, AFF commission and
  GMV, covered GMV; the shop row also ``other_marketing``, the product row its de-overlapped
  ads-by-product GMV) as nullable ``numeric(18,2)`` (NULL = missing, never 0), plus
  ``derivation_version`` (``source_metrics_daily`` gets it too). A version bump rebuilds the
  stale rows in the background (``materialize.rebuild_outdated``).
- ``product_channel_metrics_daily``: one row per (shop, day, item, channel, discounted): Organic /
  Quảng cáo / TTLK x bought with / without a shop discount (``unknown`` = GMV no order line
  explains); the cells of a product day add up to its product row. ``juli_app``: SELECT,
  INSERT, UPDATE, DELETE (a cell that became empty is removed on rebuild: sparse rows).
- ``shop_channel_metrics_daily`` (contract §6): the shop day per (channel, discounted), the shop's
  own đơn once per order; the cells add up to the shop row. Same grants as the product cells.
- Both daily rows also get ``affiliate_commission_known`` / ``ads_spend_known`` (A2: the covered
  orders' AFF and ads cost) and the ads funnel components ``ads_gmv_direct``,
  ``ads_gmv_confirmed``, ``ads_views``, ``ads_clicks``, ``ads_orders``.
- ``shop_facts_status`` (deploy plan #74): one row per shop, is its stored layer current
  (``derivation_version``, ``complete`` / ``ready_from``); written by the triggered backfill.
  ``juli_app``: SELECT, INSERT, UPDATE.
- ``campaign_metrics_daily``: one row per (shop, day, campaign) from the Connector's
  ``ads_campaign_daily``, only for days with spend or GMV. ``juli_app``: SELECT, INSERT, UPDATE,
  DELETE (a campaign that no longer spent that day is removed on rebuild: sparse rows).
- ``shopee_opportunities`` (Track OPP O1): every candidate of a daily card run with its estimate
  and outcome (``source`` = the daily run or an on-demand ``generate_for``; ``variant_key`` =
  ``<campaign_key>|<version point>``); a same-day rerun upserts on the natural key.
  ``juli_app``: SELECT, INSERT, UPDATE.

Read paths: each natural UNIQUE key leads with (shop_id, day | run_date) and doubles as the
window read index; ``product_channel_metrics_daily`` also has (shop_id, item_id, day) for the
product page. Every fact table states its grain in ``COMMENT ON TABLE``.

Independent of 136 (T5 compat views); chained on ``139_hot_path_indexes`` (re-pointed from 138 at
integration, batch-1124-c-data).

EXPAND-ONLY AND REVERSIBLE: new nullable columns and two new tables with their indexes, RLS
policies and grants. No row is moved; the triggered rebuild fills the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "140_data_layer_facts_opps"
down_revision: str | None = "139_hot_path_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: the components both the shop and the product day carry (registry ids)
_COMPONENTS = (
    "net_revenue",
    "net_revenue_known",
    "cogs",
    "cogs_known_gmv",
    "packaging",
    "fees",
    "shipping_net",
    "offer_promo",
    "offer_voucher",
    "offer_combo",
    "affiliate_commission",
    "affiliate_gmv",
)
#: contract §6: the covered-order AFF / ads cost (A2) and the ads funnel, shop and product day
_KNOWN_AND_ADS_MONEY = (
    "affiliate_commission_known",
    "ads_spend_known",
    "ads_gmv_direct",
    "ads_gmv_confirmed",
)
_ADS_COUNTS = ("ads_views", "ads_clicks", "ads_orders")
#: the money columns of a channel cell beside GMV
_CHANNEL_MONEY = (
    "net_revenue",
    "net_revenue_known",
    "cogs",
    "cogs_known_gmv",
    "packaging",
    "fees",
    "shipping_net",
    "offer_promo",
    "offer_voucher",
    "offer_combo",
    "affiliate_commission",
    "ads_spend",
    "capped_gmv",
)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _money(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 2), nullable=True)


def upgrade() -> None:
    for name in _COMPONENTS:
        op.add_column("shop_metrics_daily", _money(name))
        op.add_column("product_metrics_daily", _money(name))
    op.add_column("shop_metrics_daily", _money("other_marketing"))
    op.add_column("product_metrics_daily", _money("ads_gmv"))
    for table in ("shop_metrics_daily", "product_metrics_daily"):
        for name in _KNOWN_AND_ADS_MONEY:
            op.add_column(table, _money(name))
        for name in _ADS_COUNTS:
            op.add_column(table, sa.Column(name, sa.Integer(), nullable=True))
    for table in ("shop_metrics_daily", "product_metrics_daily", "source_metrics_daily"):
        op.add_column(table, sa.Column("derivation_version", sa.String(length=32), nullable=True))

    op.create_table(
        "product_channel_metrics_daily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=12), nullable=False),
        sa.Column("discounted", sa.String(length=8), nullable=False),
        sa.Column("gmv", sa.Numeric(18, 2), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        *(_money(name) for name in _CHANNEL_MONEY),
        sa.Column("derivation_version", sa.String(length=32), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_channel_metrics_daily"),
        sa.UniqueConstraint(
            "shop_id",
            "day",
            "item_id",
            "channel",
            "discounted",
            name="uq_product_channel_metrics_daily",
        ),
        sa.CheckConstraint(
            "channel IN ('organic', 'ads', 'affiliate')",
            name="ck_product_channel_metrics_daily_channel",
        ),
        sa.CheckConstraint(
            "discounted IN ('with', 'without', 'unknown')",
            name="ck_product_channel_metrics_daily_discounted",
        ),
    )
    op.create_index(
        "ix_product_channel_metrics_daily_item",
        "product_channel_metrics_daily",
        ["shop_id", "item_id", "day"],
    )

    op.create_table(
        "shop_channel_metrics_daily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=12), nullable=False),
        sa.Column("discounted", sa.String(length=8), nullable=False),
        sa.Column("gmv", sa.Numeric(18, 2), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        *(_money(name) for name in _CHANNEL_MONEY),
        sa.Column("derivation_version", sa.String(length=32), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shop_channel_metrics_daily"),
        sa.UniqueConstraint(
            "shop_id", "day", "channel", "discounted", name="uq_shop_channel_metrics_daily"
        ),
        sa.CheckConstraint(
            "channel IN ('organic', 'ads', 'affiliate')",
            name="ck_shop_channel_metrics_daily_channel",
        ),
        sa.CheckConstraint(
            "discounted IN ('with', 'without', 'unknown')",
            name="ck_shop_channel_metrics_daily_discounted",
        ),
    )

    op.create_table(
        "shop_facts_status",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("derivation_version", sa.String(length=32), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ready_from", sa.Date(), nullable=True),
        sa.Column("pending_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shop_facts_status"),
        sa.UniqueConstraint("shop_id", name="uq_shop_facts_status"),
    )

    op.create_table(
        "campaign_metrics_daily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("ad_type", sa.String(length=32), nullable=True),
        _money("spend"),
        _money("gmv"),
        _money("gmv_direct"),
        sa.Column("orders", sa.Integer(), nullable=True),
        sa.Column("orders_direct", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        _money("contribution_products"),
        _money("daily_budget"),
        sa.Column("derivation_version", sa.String(length=32), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_metrics_daily"),
        sa.UniqueConstraint("shop_id", "day", "campaign_id", name="uq_campaign_metrics_daily"),
    )

    op.create_table(
        "shopee_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("item_key", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("variant_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("item_ids", _jsonb(), nullable=False, server_default="[]"),
        _money("delta_gmv"),
        _money("delta_profit"),
        _money("cost"),
        sa.Column("inputs", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("outcome", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="daily"),
        sa.Column("score", sa.Numeric(12, 6), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("card_code", sa.String(length=64), nullable=True),
        sa.Column("derivation_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shopee_opportunities"),
        sa.UniqueConstraint(
            "shop_id",
            "run_date",
            "kind",
            "item_key",
            "variant_key",
            name="uq_shopee_opportunities_run",
        ),
        sa.CheckConstraint(
            "outcome IN ('published', 'ranked_out', 'below_band', 'refused', 'duplicate')",
            name="ck_shopee_opportunities_outcome",
        ),
        sa.CheckConstraint("scope IN ('shop', 'product')", name="ck_shopee_opportunities_scope"),
        sa.CheckConstraint(
            "source IN ('daily', 'on_demand')", name="ck_shopee_opportunities_source"
        ),
    )

    op.execute("ALTER TABLE public.product_channel_metrics_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.shop_channel_metrics_daily ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY shop_channel_metrics_daily_select_public "
        "ON public.shop_channel_metrics_daily "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shop_channel_metrics_daily_insert_public "
        "ON public.shop_channel_metrics_daily "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shop_channel_metrics_daily_update_public "
        "ON public.shop_channel_metrics_daily "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shop_channel_metrics_daily_delete_public "
        "ON public.shop_channel_metrics_daily "
        "FOR DELETE USING (shop_id = app_current_shop_id())"
    )
    op.execute("ALTER TABLE public.shop_facts_status ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY shop_facts_status_select_public ON public.shop_facts_status "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shop_facts_status_insert_public ON public.shop_facts_status "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shop_facts_status_update_public ON public.shop_facts_status "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute("ALTER TABLE public.campaign_metrics_daily ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY product_channel_metrics_daily_select_public "
        "ON public.product_channel_metrics_daily "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY product_channel_metrics_daily_insert_public "
        "ON public.product_channel_metrics_daily "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY product_channel_metrics_daily_update_public "
        "ON public.product_channel_metrics_daily "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY product_channel_metrics_daily_delete_public "
        "ON public.product_channel_metrics_daily "
        "FOR DELETE USING (shop_id = app_current_shop_id())"
    )
    op.execute("ALTER TABLE public.shopee_opportunities ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY campaign_metrics_daily_select_public ON public.campaign_metrics_daily "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY campaign_metrics_daily_insert_public ON public.campaign_metrics_daily "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY campaign_metrics_daily_update_public ON public.campaign_metrics_daily "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY campaign_metrics_daily_delete_public ON public.campaign_metrics_daily "
        "FOR DELETE USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shopee_opportunities_select_public ON public.shopee_opportunities "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shopee_opportunities_insert_public ON public.shopee_opportunities "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY shopee_opportunities_update_public ON public.shopee_opportunities "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.product_channel_metrics_daily TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.shop_channel_metrics_daily TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.campaign_metrics_daily TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shop_facts_status TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_opportunities TO juli_app';
        END IF;
    END
    $$;
    """)

    op.execute(
        "COMMENT ON TABLE public.shop_metrics_daily IS 'grain: shop_id x day x order_type; "
        "additive registry components, ratios evaluated at read time'"
    )
    op.execute(
        "COMMENT ON TABLE public.product_metrics_daily IS 'grain: shop_id x day x order_type x "
        "item_id; products + __residual__ add up to the shop day; orders not summable over item_id'"
    )
    op.execute(
        "COMMENT ON TABLE public.source_metrics_daily IS 'grain: shop_id x day x item_id (NULL = "
        "shop) x source; traffic-report funnel, the six sources add up to their scope'"
    )
    op.execute(
        "COMMENT ON TABLE public.product_channel_metrics_daily IS 'grain: shop_id x day x item_id "
        "x channel x discounted; cells add up to the product day; sparse'"
    )
    op.execute(
        "COMMENT ON TABLE public.shop_channel_metrics_daily IS 'grain: shop_id x day x channel x "
        "discounted; the shop own orders once per order, cells add up to the shop day; sparse'"
    )
    op.execute(
        "COMMENT ON TABLE public.campaign_metrics_daily IS 'grain: shop_id x day x campaign_id; "
        "only days with spend or GMV; contribution_products not summable over campaign_id'"
    )
    op.execute(
        "COMMENT ON TABLE public.shopee_opportunities IS 'grain: shop_id x run_date x kind x "
        "item_key x variant_key; one card candidate of a daily run and its outcome'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON TABLE public.shop_metrics_daily IS NULL")
    op.execute("COMMENT ON TABLE public.product_metrics_daily IS NULL")
    op.execute("COMMENT ON TABLE public.source_metrics_daily IS NULL")
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'REVOKE ALL ON public.shopee_opportunities FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.campaign_metrics_daily FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.shop_facts_status FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.product_channel_metrics_daily FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.shop_channel_metrics_daily FROM juli_app';
        END IF;
    END
    $$;
    """)
    op.drop_table("shopee_opportunities")
    op.drop_table("campaign_metrics_daily")
    op.drop_table("shop_facts_status")
    op.drop_table("shop_channel_metrics_daily")
    op.drop_index(
        "ix_product_channel_metrics_daily_item", table_name="product_channel_metrics_daily"
    )
    op.drop_table("product_channel_metrics_daily")
    for table in ("source_metrics_daily", "product_metrics_daily", "shop_metrics_daily"):
        op.drop_column(table, "derivation_version")
    for table in ("product_metrics_daily", "shop_metrics_daily"):
        for name in reversed(_ADS_COUNTS):
            op.drop_column(table, name)
        for name in reversed(_KNOWN_AND_ADS_MONEY):
            op.drop_column(table, name)
    op.drop_column("product_metrics_daily", "ads_gmv")
    op.drop_column("shop_metrics_daily", "other_marketing")
    for name in reversed(_COMPONENTS):
        op.drop_column("product_metrics_daily", name)
        op.drop_column("shop_metrics_daily", name)

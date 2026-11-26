"""Drop the seven T5 compat views that migration 134 left under the old ``shopee_*`` names

Revision ID: 136_drop_t5_compat_views
Revises: 140_data_layer_facts_opps
Create Date: 2026-11-24

Owner decision 2026-11-20 (batch shape + window decision #34). Migration 134 renamed the seven
Shopee fact tables to their canonical names and kept a ``security_invoker`` view under each old
name for one release (D4). That release is over: no runtime code reads the old names (audit
2026-11-19), so the views go.

- Number 136 was claimed for this step; the revision chains after the head it found
  (``138_juli_agent_spend``), not by number; rebuilt on ``140_data_layer_facts_opps`` on
  2026-11-26 after 139 and 140 shipped (owner #89, #106).
- Upgrade: ``DROP VIEW IF EXISTS`` for each of the seven views, and nothing else. The tables,
  their rows, RLS, policies and grants are not touched. ``RESTRICT`` (the default, no
  ``CASCADE``): if an object outside the repo depends on a view, the drop fails and the whole
  transaction rolls back instead of silently dropping that object.
- Downgrade: the views come back exactly as 134 created them. Since 136 sits on 140 (rebuilt
  2026-11-26), three tables have columns 140 added after 134: their views select every column but
  those (``ADDED_AFTER_134``, written out literally in the SQL, so 140's downgrade can still
  drop them); the other four are ``SELECT *``. Either way: the table's columns at 134,
  ``security_invoker = true``, the table's ``juli_app`` verbs: SELECT, INSERT, UPDATE; for
  ``shopee_stock_history`` SELECT, INSERT.
- ``lock_timeout`` 10s, transaction-local, as in 134: a straggling query holding a lock makes the
  migration fail fast instead of queueing every later query behind it.

Literal SQL only, so ``infra/scripts/migration_additive_gate.py`` reads exactly what runs.

NOT ADDITIVE: the gate refuses ``DROP VIEW`` by design. Like 134 it ships in a maintenance window:
the owner runs ``alembic upgrade 136_drop_t5_compat_views`` on the VPS with the workers paused,
then the deploy tag runs with nothing pending. Runbook: ``docs/runbooks/t5-maintenance-window.md``
(section "Migration 136").
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "136_drop_t5_compat_views"
down_revision: str | None = "140_data_layer_facts_opps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_C140 = (
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
_K140 = ("affiliate_commission_known", "ads_spend_known", "ads_gmv_direct", "ads_gmv_confirmed")
_A140 = ("ads_views", "ads_clicks", "ads_orders")
#: The columns 140 added to three of the seven tables after 134 made the views; the downgrade's
#: literal ``NOT IN`` lists are exactly these (tests hold them to the SQL and to 140).
ADDED_AFTER_134: dict[str, tuple[str, ...]] = {
    "shop_metrics_daily": (*_C140, "other_marketing", *_K140, *_A140, "derivation_version"),
    "product_metrics_daily": (*_C140, "ads_gmv", *_K140, *_A140, "derivation_version"),
    "source_metrics_daily": ("derivation_version",),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS public.shopee_order_lines")
    op.execute("DROP VIEW IF EXISTS public.shopee_order_income")
    op.execute("DROP VIEW IF EXISTS public.shopee_affiliate_lines")
    op.execute("DROP VIEW IF EXISTS public.shopee_shop_metrics_daily")
    op.execute("DROP VIEW IF EXISTS public.shopee_product_metrics_daily")
    op.execute("DROP VIEW IF EXISTS public.shopee_source_metrics_daily")
    op.execute("DROP VIEW IF EXISTS public.shopee_stock_history")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
    CREATE VIEW public.shopee_order_lines WITH (security_invoker = true) AS SELECT * FROM public.order_lines;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_order_lines TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    CREATE VIEW public.shopee_order_income WITH (security_invoker = true) AS SELECT * FROM public.order_settlements;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_order_income TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    CREATE VIEW public.shopee_affiliate_lines WITH (security_invoker = true) AS SELECT * FROM public.affiliate_lines;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_affiliate_lines TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    DO $$
    DECLARE cols text;
    BEGIN
        SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
        FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'shop_metrics_daily'
        AND column_name NOT IN ('net_revenue', 'net_revenue_known', 'cogs', 'cogs_known_gmv', 'packaging', 'fees', 'shipping_net', 'offer_promo', 'offer_voucher', 'offer_combo', 'affiliate_commission', 'affiliate_gmv', 'other_marketing', 'affiliate_commission_known', 'ads_spend_known', 'ads_gmv_direct', 'ads_gmv_confirmed', 'ads_views', 'ads_clicks', 'ads_orders', 'derivation_version');
        EXECUTE 'CREATE VIEW public.shopee_shop_metrics_daily WITH (security_invoker = true) AS SELECT ' || cols || ' FROM public.shop_metrics_daily';
    END
    $$;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_shop_metrics_daily TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    DO $$
    DECLARE cols text;
    BEGIN
        SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
        FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'product_metrics_daily'
        AND column_name NOT IN ('net_revenue', 'net_revenue_known', 'cogs', 'cogs_known_gmv', 'packaging', 'fees', 'shipping_net', 'offer_promo', 'offer_voucher', 'offer_combo', 'affiliate_commission', 'affiliate_gmv', 'ads_gmv', 'affiliate_commission_known', 'ads_spend_known', 'ads_gmv_direct', 'ads_gmv_confirmed', 'ads_views', 'ads_clicks', 'ads_orders', 'derivation_version');
        EXECUTE 'CREATE VIEW public.shopee_product_metrics_daily WITH (security_invoker = true) AS SELECT ' || cols || ' FROM public.product_metrics_daily';
    END
    $$;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_product_metrics_daily TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    DO $$
    DECLARE cols text;
    BEGIN
        SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
        FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'source_metrics_daily'
        AND column_name NOT IN ('derivation_version');
        EXECUTE 'CREATE VIEW public.shopee_source_metrics_daily WITH (security_invoker = true) AS SELECT ' || cols || ' FROM public.source_metrics_daily';
    END
    $$;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.shopee_source_metrics_daily TO juli_app';
        END IF;
    END
    $$;
    """)
    op.execute("""
    CREATE VIEW public.shopee_stock_history WITH (security_invoker = true) AS SELECT * FROM public.stock_history;
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.shopee_stock_history TO juli_app';
        END IF;
    END
    $$;
    """)

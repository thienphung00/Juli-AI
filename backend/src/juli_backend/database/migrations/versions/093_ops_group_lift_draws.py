"""Ops: other shops' group comparisons for the EB prior (fast track P45).

Revision ID: 093_ops_group_lift_draws
Revises: 092_card_group_design
Create Date: 2026-10-17

DECISIONS D52 (Ops shows an empirical-Bayes shrunk group lift). The prior of a
lever type is estimated from the measured groups of that lever across ALL shops,
but ``card_groups`` is a tenant table (RLS by ``app_current_shop_id()``, 089) and
grants nothing to ``juli_ops``.

WHAT IT ADDS. ``ops_group_lift_draws()`` (SECURITY DEFINER, ADR-089 shape like
``ops_find_shop``, EXECUTE to ``juli_ops`` only -- never ``juli_app``): one row per
measured group comparison -- the group's primary comparison and each entry of its
``verdict.metrics`` -- as ``(shop, group, lever, metric, channel, comparison)``.
The comparison is the ``compare`` output only (medians, difference, interval,
counts): no product rows, titles or buyer data. Ops turns these into aggregate
priors (mean, spread, number of shops) and never returns another shop's rows.

EXPAND-ONLY AND REVERSIBLE. One function and its grant; no table or data change.
``downgrade`` drops it. The deferred phone-cleanup step is re-parented onto this
revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "093_ops_group_lift_draws"
down_revision: str | None = "092_card_group_design"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPS_ROLE = "juli_ops"
FUNCTION = "public.ops_group_lift_draws()"


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_group_lift_draws()
    RETURNS TABLE (
        out_shop_id uuid,
        out_group_id uuid,
        out_lever varchar,
        out_metric varchar,
        out_channel varchar,
        out_comparison jsonb
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        WITH measured AS (
            SELECT g.shop_id, g.id, g.lever, g.metric, g.channel, g.verdict::jsonb AS v
            FROM public.card_groups g
            WHERE g.status = 'measured' AND g.verdict IS NOT NULL
        )
        SELECT m.shop_id, m.id, m.lever, m.metric, m.channel, m.v -> 'primary'
        FROM measured m
        WHERE jsonb_typeof(m.v -> 'primary') = 'object'
        UNION ALL
        SELECT m.shop_id, m.id, m.lever,
               (e.value ->> 'metric')::varchar, (e.value ->> 'channel')::varchar,
               e.value -> 'primary'
        FROM measured m
        CROSS JOIN LATERAL jsonb_each(
            CASE WHEN jsonb_typeof(m.v -> 'metrics') = 'object'
                 THEN m.v -> 'metrics' ELSE '{}'::jsonb END
        ) AS e
        WHERE jsonb_typeof(e.value) = 'object'
          AND jsonb_typeof(e.value -> 'primary') = 'object'
    $fn$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {FUNCTION} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - role and function are fixed module constants


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")

"""Ops: the EB prior's cross-shop draws only from shops with ``pooled_training`` (NDA work).

Revision ID: 107_ops_pooled_consent
Revises: 106_write_platform_columns
Create Date: 2026-10-26

DECISIONS D76, D11 of the client-data grill; ADR-116 §3 "Ops console".

WHY. ``ops_group_lift_draws()`` (093) returned every shop's measured group comparisons,
and the Ops groups page pools them into the empirical-Bayes prior of a lever type
(``card_groups.apply_pooled_eb`` -> ``group_stats.estimate_prior``). Measuring ONE shop
with its own data is ``service``; a figure POOLED across shops may read only shops that
hold an open ``pooled_training`` grant (``data_use_consents``, 103). Any other shop
falls back to its own data.

WHAT CHANGES. The function body only: the measured groups are now limited to shops with
an open ``pooled_training`` row (``scope = 'pooled_training' AND revoked_at IS NULL``).
The function is SECURITY DEFINER, owned by the migration role: the tenant RLS of
``data_use_consents`` does not apply to it any more than ``card_groups``'s, so it can
read every shop's grants (it returns none of them).
Signature, ``out_`` columns, ``STABLE``, the pinned ``search_path`` and the grants
(EXECUTE to ``juli_ops`` only, revoked from PUBLIC) are exactly 093's;
``CREATE OR REPLACE`` keeps the ACL and the grants are re-asserted anyway. The viewed
shop's own side (no grant -> no pooled prior at all) is in ``api/routes/ops.py``.

EXPAND-ONLY AND REVERSIBLE. No table or data change. ``downgrade`` restores 093's body
verbatim. The deferred write-mode backfill (and the phone cleanup under it) is
re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "107_ops_pooled_consent"
down_revision: str | None = "106_write_platform_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPS_ROLE = "juli_ops"
FUNCTION = "public.ops_group_lift_draws()"
#: Written out rather than imported from the model: a migration must not change when the
#: model does. ``tests/unit/test_ops_pooled_consent.py`` pins it equal.
POOLED_SCOPE = "pooled_training"


def _grants() -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {FUNCTION} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - role and function are fixed module constants


def upgrade() -> None:
    # Literal SQL (an f-string of module constants): the additive deploy gate reads it.
    op.execute(f"""
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
              AND EXISTS (
                  SELECT 1
                  FROM public.data_use_consents c
                  WHERE c.shop_id = g.shop_id
                    AND c.scope = '{POOLED_SCOPE}'
                    AND c.revoked_at IS NULL
              )
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
                 THEN m.v -> 'metrics' ELSE '{{}}'::jsonb END
        ) AS e
        WHERE jsonb_typeof(e.value) = 'object'
          AND jsonb_typeof(e.value -> 'primary') = 'object'
    $fn$;
    """)  # nosec B608 - the scope is a fixed module constant
    _grants()


def downgrade() -> None:
    # 093's body, verbatim.
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
    _grants()

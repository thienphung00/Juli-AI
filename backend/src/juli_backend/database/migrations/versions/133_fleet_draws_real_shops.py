"""Pooled calibration draws come from real shops only (forecast grill F6)

Revision ID: 133_fleet_draws_real_shops
Revises: 132_credential_grant_id
Create Date: 2026-11-16

``public.ops_fleet_calibration_draws()`` (migration 107) now also requires the contributing
shop's ``shops.kind`` (migration 130) to be neither ``sample`` nor ``sandbox``: the reviewer
sample shop and Juli's TikTok sandbox shop never lend their results to the pooled level.

CREATE OR REPLACE keeps the function's owner and its EXECUTE grants (``juli_ops`` only, 107);
they are re-applied anyway so a fresh database ends in the same state. REVERSIBLE: downgrade
restores 107's body. No row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "133_fleet_draws_real_shops"
down_revision: str | None = "132_credential_grant_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grants() -> None:
    op.execute("REVOKE ALL ON FUNCTION public.ops_fleet_calibration_draws() FROM PUBLIC")
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_ops') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.ops_fleet_calibration_draws() TO juli_ops';
        END IF;
    END
    $$;
    """)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_fleet_calibration_draws()
    RETURNS TABLE (
        out_shop_id uuid,
        out_lever varchar,
        out_coefficient numeric,
        out_readings integer
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT l.shop_id, l.lever::varchar, l.coefficient::numeric, l.readings
        FROM public.lever_calibrations l
        WHERE l.readings > 0
          AND EXISTS (
              SELECT 1
              FROM public.data_use_consents c
              WHERE c.shop_id = l.shop_id
                AND c.scope = 'pooled_training'
                AND c.revoked_at IS NULL
          )
          AND EXISTS (
              SELECT 1
              FROM public.shops s
              WHERE s.id = l.shop_id
                AND s.kind NOT IN ('sample', 'sandbox')
          )
    $fn$;
    """)
    _grants()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_fleet_calibration_draws()
    RETURNS TABLE (
        out_shop_id uuid,
        out_lever varchar,
        out_coefficient numeric,
        out_readings integer
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT l.shop_id, l.lever::varchar, l.coefficient::numeric, l.readings
        FROM public.lever_calibrations l
        WHERE l.readings > 0
          AND EXISTS (
              SELECT 1
              FROM public.data_use_consents c
              WHERE c.shop_id = l.shop_id
                AND c.scope = 'pooled_training'
                AND c.revoked_at IS NULL
          )
    $fn$;
    """)
    _grants()

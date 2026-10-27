"""Pooled figures read only ``pooled_training`` shops; the contributor audit (NDA work).

Revision ID: 107_ops_pooled_consent
Revises: 106_write_platform_columns
Create Date: 2026-10-26

DECISIONS D76, D11 of the client-data grill; owner D14 / D15 / D17 (2026-10-27);
ADR-116 §3 "Ops console" and "Fleet calibration".

WHY. A figure POOLED across shops -- the Ops card-group EB prior and the D30.3 fleet
calibration factor -- may read only shops that hold an open ``pooled_training`` grant
(``data_use_consents``, 103), and only those shops receive it (D11 / D17: a shop without
the grant neither borrows nor lends; the grant is given only to Juli's own shops). The
pooled cells themselves (at least 5
contributing shops, no shop over 50 % of a cell, D14) are judged in Python
(``services/consent/pooling.py``); this migration only decides who is drawn and keeps
the audit (D15).

WHAT CHANGES.

- ``ops_group_lift_draws()`` (093): the body only -- the measured groups are limited to
  shops with an open ``pooled_training`` row (``scope = 'pooled_training' AND
  revoked_at IS NULL``). Signature, ``out_`` columns, ``STABLE``, the pinned
  ``search_path`` and the grants (EXECUTE to ``juli_ops`` only, revoked from PUBLIC) are
  exactly 093's; ``CREATE OR REPLACE`` keeps the ACL and the grants are re-asserted.
- ``ops_fleet_calibration_draws()`` (new, ADR-089 shape): each consenting shop's
  ``lever_calibrations`` rows with ``readings > 0`` -- ``out_shop_id``, ``out_lever``,
  ``out_coefficient``, ``out_readings`` -- so the nightly card plan, which runs under
  ONE shop's tenant scope, can pool the fleet level across shops (before, row-level
  security showed it only its own row). SECURITY DEFINER, ``STABLE``, fixed SQL,
  pinned ``search_path``, EXECUTE to ``juli_ops`` only; the caller (``lever_flows.
  measurement.fleet_calibration_stats``) switches with ``ops_role`` and keeps only
  aggregates and shop ids for the audit.
- ``pooled_contributor_sets`` (new, D15): one row per persisted pooled computation --
  ``figure``, ``applied_shop_id``, ``contributor_shop_ids`` (``shops.id`` values,
  never names), ``contributors_sha256``, ``cells`` (cell -> shop count),
  ``computed_at``. Like every 083 ops table it is NOT a tenant table: RLS on, the only
  policy ``FOR ALL TO juli_ops``; ``juli_ops`` gets SELECT, INSERT (append-only, as
  ``ops_audit_log``); ``juli_app``, ``anon``, ``authenticated`` get nothing.
  Classified ``ops_only`` in ``database/tenant_scoped_tables.py``. No foreign key: the
  audit outlives a deleted shop and holds its id only.

The functions are owned by the migration role: the tenant RLS of ``data_use_consents``
and ``lever_calibrations`` does not apply to them any more than ``card_groups``'s, so
they can read every shop's grants (they return none of them).

EXPAND-ONLY AND REVERSIBLE. No data change. ``downgrade`` drops the table and the new
function and restores 093's ``ops_group_lift_draws()`` body verbatim. The deferred
write-mode backfill (and the phone cleanup under it) is re-parented onto this revision
so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "107_ops_pooled_consent"
down_revision: str | None = "106_write_platform_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
FUNCTION = "public.ops_group_lift_draws()"
FLEET_FUNCTION = "public.ops_fleet_calibration_draws()"
TABLE = "pooled_contributor_sets"
#: Written out rather than imported from the model: a migration must not change when the
#: model does. ``tests/unit/test_ops_pooled_consent.py`` / ``test_pooled_cells.py`` pin
#: them equal.
POOLED_SCOPE = "pooled_training"
FIGURES = ("fleet_calibration", "ops_group_prior")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _grants(function: str) -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {function} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - role and function are fixed module constants


def _create_audit_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("figure", sa.String(length=32), nullable=False),
        sa.Column("applied_shop_id", sa.Uuid(), nullable=False),
        sa.Column("contributor_shop_ids", sa.JSON(), nullable=False),
        sa.Column("contributors_sha256", sa.String(length=64), nullable=False),
        sa.Column("cells", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pooled_contributor_sets"),
        sa.CheckConstraint(f"figure IN ({_in(FIGURES)})", name="ck_pooled_contributor_sets_figure"),
        sa.CheckConstraint(
            "length(contributors_sha256) = 64", name="ck_pooled_contributor_sets_sha256"
        ),
    )
    op.create_index("ix_pooled_contributor_sets_computed_at", TABLE, ["computed_at"])
    op.create_index(
        "ix_pooled_contributor_sets_applied_shop", TABLE, ["applied_shop_id", "computed_at"]
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TABLE}_ops_only ON public.{TABLE} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON public.{TABLE} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM anon';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM authenticated';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.{TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


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
    _grants(FUNCTION)

    op.execute(f"""
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
                AND c.scope = '{POOLED_SCOPE}'
                AND c.revoked_at IS NULL
          )
    $fn$;
    """)  # nosec B608 - the scope is a fixed module constant
    _grants(FLEET_FUNCTION)

    _create_audit_table()


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_ops_only ON public.{TABLE}")
    op.drop_index("ix_pooled_contributor_sets_applied_shop", table_name=TABLE)
    op.drop_index("ix_pooled_contributor_sets_computed_at", table_name=TABLE)
    op.drop_table(TABLE)
    op.execute(f"DROP FUNCTION IF EXISTS {FLEET_FUNCTION}")
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
    _grants(FUNCTION)

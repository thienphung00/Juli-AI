"""serving gold.kpi_envelopes + legacy compat view cutover (#606)

Revision ID: 024_gold_kpi_envelopes
Revises: 023_bronze_orders_returns
Create Date: 2026-07-30

Stacked after #605: down_revision = 023_bronze_orders_returns while #604+#605 land
022/023. Meta rebases to 023_bronze_orders_returns when opening the sequential PR.

Cutover:
- ``gold.kpi_envelopes`` is the serving SoT (PK ``shop_id``; flexible ``payload.kpis``).
- ``public.analytics_kpi_envelopes_compat`` preserves legacy read shape for Demo/Track B.
- ``public.analytics_kpi_envelopes`` becomes read-only (writers must use gold).
- Optional GIN on ``payload`` deferred until first containment query need (ADR-046).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "024_gold_kpi_envelopes"
down_revision: str | None = "023_bronze_orders_returns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
GOLD_TABLE = "gold.kpi_envelopes"
COMPAT_VIEW = "public.analytics_kpi_envelopes_compat"
LEGACY_TABLE = "public.analytics_kpi_envelopes"


def _grant_client_select(table_or_view: str) -> None:
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $gold$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    GRANT SELECT ON {table_or_view} TO {role};
  END IF;
END
$gold$;
"""  # nosec B608 — table/role are fixed module constants
        op.execute(sql)


def _revoke_client_select(table_or_view: str) -> None:
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $gold$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    REVOKE ALL ON {table_or_view} FROM {role};
  END IF;
END
$gold$;
"""  # nosec B608
        op.execute(sql)


def upgrade() -> None:
    op.create_table(
        "kpi_envelopes",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("envelope_version", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("shop_id"),
        schema="gold",
    )

    # Migrate legacy analytics envelopes (one row per shop) into gold SoT.
    op.execute(
        """
        INSERT INTO gold.kpi_envelopes (
            shop_id, computed_at, envelope_version, payload, created_at, updated_at
        )
        SELECT
            shop_id,
            computed_at,
            envelope_version,
            payload,
            created_at,
            updated_at
        FROM public.analytics_kpi_envelopes
        WHERE kind = 'analytics'
        ON CONFLICT (shop_id) DO UPDATE SET
            computed_at = EXCLUDED.computed_at,
            envelope_version = EXCLUDED.envelope_version,
            payload = EXCLUDED.payload,
            updated_at = EXCLUDED.updated_at
        """
    )

    op.execute(
        """
        ALTER TABLE gold.kpi_envelopes ENABLE ROW LEVEL SECURITY;
        CREATE POLICY gold_kpi_envelopes_isolation
            ON gold.kpi_envelopes
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
        """
    )  # nosec B608

    _grant_client_select(GOLD_TABLE)

    # Compat view: legacy column shape over gold (payload.kpis preserved).
    op.execute(
        """
        CREATE VIEW public.analytics_kpi_envelopes_compat AS
        SELECT
            md5(g.shop_id::text || chr(58) || 'analytics')::uuid AS id,
            g.shop_id,
            'analytics'::text AS kind,
            g.envelope_version,
            g.payload,
            g.computed_at,
            g.created_at,
            g.updated_at
        FROM gold.kpi_envelopes g
        """
    )
    _grant_client_select(COMPAT_VIEW)

    # Retire legacy writer — block competing SoT after cutover (#606 AC4).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_analytics_kpi_envelopes_writes()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'public.analytics_kpi_envelopes is read-only after gold cutover (#606); write gold.kpi_envelopes';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_analytics_kpi_envelopes_no_write
            BEFORE INSERT OR UPDATE OR DELETE
            ON public.analytics_kpi_envelopes
            FOR EACH ROW
            EXECUTE FUNCTION public.prevent_analytics_kpi_envelopes_writes();
        """
    )

    # GIN / expression index on payload deferred — document in migration notes (ADR-046).


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_analytics_kpi_envelopes_no_write "
        "ON public.analytics_kpi_envelopes"
    )
    op.execute("DROP FUNCTION IF EXISTS public.prevent_analytics_kpi_envelopes_writes()")

    _revoke_client_select(COMPAT_VIEW)
    op.execute("DROP VIEW IF EXISTS public.analytics_kpi_envelopes_compat")

    _revoke_client_select(GOLD_TABLE)
    op.execute("DROP POLICY IF EXISTS gold_kpi_envelopes_isolation ON gold.kpi_envelopes")
    op.execute("ALTER TABLE gold.kpi_envelopes DISABLE ROW LEVEL SECURITY")

    op.drop_table("kpi_envelopes", schema="gold")

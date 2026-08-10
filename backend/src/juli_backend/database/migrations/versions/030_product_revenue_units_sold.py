"""add revenue/units_sold columns to products (#943)

Revision ID: 030_product_revenue_units_sold
Revises: 029_bronze_ctor_live_hours
Create Date: 2026-08-10

Additive-only. ``models.Product`` has declared ``revenue`` (``Numeric(18, 2)``,
NOT NULL, default ``0``) and ``units_sold`` (``Integer``, NOT NULL, default
``0``) since #300/#374, but no migration ever added them to ``products`` —
prod's ``products`` table has 16 columns and neither of these. Every ORM
``SELECT`` of a full ``Product`` entity (e.g.
``ProductsRepo(session).list(...)`` in the rules-scoring pipeline) fails with
``asyncpg.exceptions.UndefinedColumnError: column products.revenue does not
exist``. Rules-based scoring has never worked in production as a result.

Both columns are added ``NOT NULL DEFAULT 0`` in one statement so existing
rows backfill in place — no separate ``UPDATE`` pass, no drops, no
destructive alters.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "030_product_revenue_units_sold"
down_revision: str | None = "029_bronze_ctor_live_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "revenue",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "units_sold",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "units_sold")
    op.drop_column("products", "revenue")

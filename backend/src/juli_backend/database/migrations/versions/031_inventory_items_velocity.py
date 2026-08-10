"""add velocity column to inventory_items (#943 follow-on)

Revision ID: 031_inventory_items_velocity
Revises: 030_product_revenue_units_sold
Create Date: 2026-08-10

Additive-only. ``models.InventoryItem`` has declared ``velocity``
(``String(20)``, NOT NULL, default ``"low"``) since it was added to the ORM
model, but no migration ever added it to ``inventory_items``. Migration 030
fixed ``products.revenue``/``products.units_sold`` — the same class of drift
that produced that bug — and rules-based scoring advanced exactly one step
before hitting the identical failure on this table::

    asyncpg.exceptions.UndefinedColumnError: column inventory_items.velocity
    does not exist

A full diff of ``Base.metadata`` against production's ``information_schema``
found this to be the only remaining drift across the entire ``public``
schema: zero missing tables, exactly one missing column.

Added ``NOT NULL DEFAULT 'low'`` in one statement so existing rows backfill
in place — no separate ``UPDATE`` pass, no drops, no destructive alters.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "031_inventory_items_velocity"
down_revision: str | None = "030_product_revenue_units_sold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column(
            "velocity",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'low'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("inventory_items", "velocity")

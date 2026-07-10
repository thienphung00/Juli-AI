"""commerce graph: campaigns + graph_edges (P1-1 / Issue #92)

Revision ID: 006_commerce_graph
Revises: 005_alert_config_threshold
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_commerce_graph"
down_revision: str | None = "005_alert_config_threshold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "product_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("predicted_gmv", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("realized_gmv", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "predicted_conversion", sa.Numeric(precision=10, scale=4), nullable=True
        ),
        sa.Column(
            "realized_conversion", sa.Numeric(precision=10, scale=4), nullable=True
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_shop_created", "campaigns", ["shop_id", "created_at"])
    op.create_index("ix_campaigns_shop_creator", "campaigns", ["shop_id", "creator_id"])
    op.create_index(
        "ix_campaigns_shop_idempotency",
        "campaigns",
        ["shop_id", "idempotency_key"],
        unique=True,
    )

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("edge_type", sa.String(length=50), nullable=False),
        sa.Column("source_node_type", sa.String(length=30), nullable=False),
        sa.Column("source_node_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_type", sa.String(length=30), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_edges_shop_type", "graph_edges", ["shop_id", "edge_type"]
    )
    op.create_index(
        "ix_graph_edges_natural_key",
        "graph_edges",
        [
            "shop_id",
            "edge_type",
            "source_node_type",
            "source_node_id",
            "target_node_type",
            "target_node_id",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_graph_edges_natural_key", table_name="graph_edges")
    op.drop_index("ix_graph_edges_shop_type", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_campaigns_shop_idempotency", table_name="campaigns")
    op.drop_index("ix_campaigns_shop_creator", table_name="campaigns")
    op.drop_index("ix_campaigns_shop_created", table_name="campaigns")
    op.drop_table("campaigns")

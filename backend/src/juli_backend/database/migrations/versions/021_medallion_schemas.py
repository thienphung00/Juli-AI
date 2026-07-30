"""create medallion schemas bronze/silver/gold/ops + grant isolation (#603)

Revision ID: 021_medallion_schemas
Revises: 020_analytics_kpi_envelopes
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_medallion_schemas"
down_revision: str | None = "020_analytics_kpi_envelopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEDALLION_SCHEMAS: tuple[str, ...] = ("bronze", "silver", "gold", "ops")
CLIENT_ISOLATED_SCHEMAS: tuple[str, ...] = ("bronze", "silver", "ops")
POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
SERVICE_ROLE = "service_role"


def _create_schemas() -> None:
    for schema in MEDALLION_SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def _revoke_client_access(schema: str) -> None:
    roles = ", ".join(POSTGREST_CLIENT_ROLES)
    for role in POSTGREST_CLIENT_ROLES:
        op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM {role}")
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {role}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {role}")
        op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schema} FROM {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {roles}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM {roles}")


def _grant_service_role(schema: str) -> None:
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {SERVICE_ROLE}")
    op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA {schema} TO {SERVICE_ROLE}")
    op.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema} TO {SERVICE_ROLE}")
    op.execute(f"GRANT ALL ON ALL FUNCTIONS IN SCHEMA {schema} TO {SERVICE_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO {SERVICE_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON SEQUENCES TO {SERVICE_ROLE}"
    )


def upgrade() -> None:
    _create_schemas()

    for schema in CLIENT_ISOLATED_SCHEMAS:
        _revoke_client_access(schema)

    for schema in MEDALLION_SCHEMAS:
        _grant_service_role(schema)

    op.create_table(
        "ml_feature_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="gold",
    )
    op.create_index(
        "ix_gold_ml_feature_snapshots_shop_snapshot",
        "ml_feature_snapshots",
        ["shop_id", "snapshot_at"],
        schema="gold",
    )

    for role in POSTGREST_CLIENT_ROLES:
        op.execute(f"REVOKE ALL ON TABLE gold.ml_feature_snapshots FROM {role}")


def downgrade() -> None:
    op.drop_index(
        "ix_gold_ml_feature_snapshots_shop_snapshot",
        table_name="ml_feature_snapshots",
        schema="gold",
    )
    op.drop_table("ml_feature_snapshots", schema="gold")

    for schema in reversed(MEDALLION_SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

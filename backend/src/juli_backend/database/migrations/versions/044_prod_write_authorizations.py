"""Create production_write_authorizations table (issue #1335).

Single-use owner authorizations for production mutations on listings. Scoped to
one shop, one product, one mutation kind. Expires after configurable TTL,
consumed atomically, revoked for audit (not deleted).

Down_revision is 043_juli_app_role (issue #1326, W7-A-AUTHZ-30), which has not
yet landed in main at this time (W7 is the concurrent wave). Migrations 042
(reserved for W6) and 043 have defined down_revision chains that land before
this one, so the upgrade/downgrade chain is well-formed once this issue lands
after #1326. The table's ORM behaviour is proven via tests against
ProductionWriteAuthorization model and PostgreSQL; the full alembic round-trip
test SKIPS when 043 is not in the versions directory, with the reason "requires
043_juli_app_role (issue #1326, merges first)".

Columns:
- id (UUID, PK)
- shop_id (UUID, FK to shops, no null)
- tiktok_product_id (string, no null)
- mutation_kind (string, no null) — vocabulary reuses tool_name from execution
- authorized_by (string, no null) — operator identity
- reason (text, nullable) — audit context
- expires_at (datetime, no null) — never null, defaults to now + 24h
- consumed_at (datetime, nullable) — set atomically with consumed_by_run_id
- consumed_by_run_id (UUID, FK to workflow_runs, nullable)
- revoked_at (datetime, nullable) — set on revoke, preserves row for audit
- revoke_reason (text, nullable)
- created_at (datetime, default now)

Indexes: shop_id (direct tenant isolation), (shop_id, tiktok_product_id, mutation_kind) for lookup.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "044_prod_write_authorizations"
down_revision: str | None = "043_juli_app_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_write_authorizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("shop_id", sa.UUID(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(100), nullable=False),
        sa.Column("mutation_kind", sa.String(100), nullable=False),
        sa.Column("authorized_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("consumed_by_run_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_prod_write_authz_shop"),
        sa.ForeignKeyConstraint(
            ["consumed_by_run_id"],
            ["workflow_runs.id"],
            name="fk_prod_write_authz_workflow_run",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_write_authorizations"),
    )

    op.create_index(
        "ix_production_write_authorizations_shop_id",
        "production_write_authorizations",
        ["shop_id"],
    )
    op.create_index(
        "ix_production_write_authorizations_lookup",
        "production_write_authorizations",
        ["shop_id", "tiktok_product_id", "mutation_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_production_write_authorizations_lookup")
    op.drop_index("ix_production_write_authorizations_shop_id")
    op.drop_table("production_write_authorizations")

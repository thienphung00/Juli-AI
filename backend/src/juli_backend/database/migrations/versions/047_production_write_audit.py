"""Create production_write_audit table with RLS (issue #1337, ADR-085 decision 7).

This migration creates the append-only audit table for production write attempts
(allowed and refused), recording every attempt with:
- run_id, shop_id, tiktok_product_id, mutation_kind (always)
- authorization_id if allowed, precondition_name if refused
- release_sha and timestamp

The table is tenant-scoped (direct shop_id) and receives the same RLS treatment
as migration 045-046: direct shop_id policies compare
shop_id = current_setting('app.current_shop_id', true)::uuid

Append-only: no UPDATE or DELETE grants. SELECT/INSERT only for juli_app.
INSERT uses WITH CHECK to enforce tenant isolation on insert.

Indexes on shop_id, run_id, and created_at for audit queries.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID

revision: str = "047_prod_write_audit"
down_revision: str | None = "046_rls_missed_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create production_write_audit table with RLS policies and grants."""
    # Create the table
    op.create_table(
        "production_write_audit",
        Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("run_id", UUID, ForeignKey("workflow_runs.id"), nullable=False),
        Column("shop_id", UUID, ForeignKey("shops.id"), nullable=False),
        Column("tiktok_product_id", String(100), nullable=False),
        Column("mutation_kind", String(100), nullable=False),
        Column("authorization_id", UUID, ForeignKey("production_write_authorizations.id")),
        Column("precondition_name", String(100)),
        Column("release_sha", String(40), nullable=False),
        Column("created_at", DateTime, server_default=func.now()),
        # Indexes for efficient querying
        Index("ix_production_write_audit_shop_id", "shop_id"),
        Index("ix_production_write_audit_run_id", "run_id"),
        Index("ix_production_write_audit_created_at", "created_at"),
    )

    # Enable RLS
    op.execute("""
    ALTER TABLE production_write_audit ENABLE ROW LEVEL SECURITY;
    """)

    # Create SELECT policy (direct shop_id)
    op.execute("""
    CREATE POLICY production_write_audit_select_public ON production_write_audit
      FOR SELECT
      USING (shop_id = current_setting('app.current_shop_id', true)::uuid);
    """)

    # Create INSERT policy with WITH CHECK (append-only, direct shop_id)
    op.execute("""
    CREATE POLICY production_write_audit_insert_public ON production_write_audit
      FOR INSERT
      WITH CHECK (shop_id = current_setting('app.current_shop_id', true)::uuid);
    """)

    # Grant SELECT and INSERT to juli_app (no UPDATE or DELETE — append-only)
    op.execute("""
    GRANT SELECT, INSERT ON production_write_audit TO juli_app;
    """)


def downgrade() -> None:
    """Drop production_write_audit table and remove grants."""
    # Revoke grants
    op.execute("""
    REVOKE ALL ON production_write_audit FROM juli_app;
    """)

    # Drop the table (which drops indexes and policies)
    op.drop_table("production_write_audit")

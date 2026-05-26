"""create users shops tiktok_credentials

Revision ID: 001
Revises:
Create Date: 2026-05-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
    )

    op.create_table(
        "shops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("shop_name", sa.String(200), nullable=False),
        sa.Column("tiktok_shop_id", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tiktok_shop_id"),
    )
    op.create_index("ix_shops_user_id", "shops", ["user_id"])

    op.create_table(
        "tiktok_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tiktok_credentials_shop_id", "tiktok_credentials", ["shop_id"])

    # RLS policies for Supabase — seller isolation (PRD AC-5)
    op.execute("""
        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
        CREATE POLICY users_isolation ON users
            USING (id = current_setting('app.current_user_id')::uuid);
    """)
    op.execute("""
        ALTER TABLE shops ENABLE ROW LEVEL SECURITY;
        CREATE POLICY shops_isolation ON shops
            USING (user_id = current_setting('app.current_user_id')::uuid);
    """)
    op.execute("""
        ALTER TABLE tiktok_credentials ENABLE ROW LEVEL SECURITY;
        CREATE POLICY credentials_isolation ON tiktok_credentials
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS credentials_isolation ON tiktok_credentials")
    op.execute("ALTER TABLE tiktok_credentials DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS shops_isolation ON shops")
    op.execute("ALTER TABLE shops DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS users_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_tiktok_credentials_shop_id", table_name="tiktok_credentials")
    op.drop_table("tiktok_credentials")
    op.drop_index("ix_shops_user_id", table_name="shops")
    op.drop_table("shops")
    op.drop_table("users")

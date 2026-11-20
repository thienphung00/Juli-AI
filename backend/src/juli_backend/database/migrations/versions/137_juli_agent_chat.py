"""The Juli tab: conversations, messages, routing decisions, card drafts (batch-1120 T3)

Revision ID: 137_juli_agent_chat
Revises: 134_canonical_tables
Create Date: 2026-11-20

Four tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``), shared by every member
of the shop, with no expiry. Model: ``models/agent_chat.py``.

- ``agent_conversations`` -- one thread (platform, title, who started it).
- ``agent_messages`` -- the question (``user``) and the answer (``assistant``: the engine's events
  in order, stop reasons, cost, ms, status running / done / cancelled / failed). A partial unique
  index allows ONE running answer per conversation.
- ``agent_routing_decisions`` -- every Jev answer of a run with its thresholds and outcome.
- ``agent_card_drafts`` -- the engine's card JSON and its fate (drafted / sent + JC code /
  dismissed).

``juli_app``: SELECT / INSERT / UPDATE on conversations, messages and drafts (a running answer
appends events and finishes; a draft is sent or dismissed); SELECT / INSERT on routing decisions
(append-only). No DELETE: the account purge (094) runs as the owner. ``juli_ops``: nothing.

Independent of 136 (T5 compat views): no view or object of it is touched. Chained on the tree's
head ``134_canonical_tables``; re-pointed at integration if 136 lands first.

EXPAND-ONLY AND REVERSIBLE: four new tables, their indexes, policies and grants; no row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "137_juli_agent_chat"
down_revision: str | None = "134_canonical_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_conversations"),
        sa.CheckConstraint(
            "platform IN ('shopee', 'tiktok')", name="ck_agent_conversations_platform"
        ),
    )
    op.create_index("ix_agent_conversations_shop", "agent_conversations", ["shop_id", "updated_at"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("template", sa.String(length=64), nullable=True),
        sa.Column("choice", _jsonb(), nullable=True),
        sa.Column("events", _jsonb(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pending", _jsonb(), nullable=True),
        sa.Column("stop_reasons", _jsonb(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_messages"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_agent_messages_role"),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'cancelled', 'failed')",
            name="ck_agent_messages_status",
        ),
    )
    op.create_index(
        "ix_agent_messages_conversation", "agent_messages", ["conversation_id", "created_at"]
    )
    op.create_index(
        "ix_agent_messages_shop_created", "agent_messages", ["shop_id", "role", "created_at"]
    )
    op.create_index(
        "uq_agent_messages_one_running",
        "agent_messages",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "agent_routing_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("agent_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("answers", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("thresholds", _jsonb(), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_routing_decisions"),
    )
    op.create_index("ix_agent_routing_decisions_message", "agent_routing_decisions", ["message_id"])

    op.create_table(
        "agent_card_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("agent_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_ref", sa.String(length=64), nullable=False),
        sa.Column("card", _jsonb(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version_label", sa.String(length=200), nullable=True),
        sa.Column("card_code", sa.String(length=32), nullable=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_card_drafts"),
        sa.UniqueConstraint("shop_id", "draft_ref", name="uq_agent_card_drafts_ref"),
        sa.CheckConstraint(
            "status IN ('drafted', 'sent', 'dismissed')", name="ck_agent_card_drafts_status"
        ),
    )
    op.create_index("ix_agent_card_drafts_message", "agent_card_drafts", ["message_id"])

    op.execute("ALTER TABLE public.agent_conversations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.agent_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.agent_routing_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.agent_card_drafts ENABLE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY agent_conversations_select_public ON public.agent_conversations "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_conversations_insert_public ON public.agent_conversations "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_conversations_update_public ON public.agent_conversations "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_messages_select_public ON public.agent_messages "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_messages_insert_public ON public.agent_messages "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_messages_update_public ON public.agent_messages "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_routing_decisions_select_public ON public.agent_routing_decisions "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_routing_decisions_insert_public ON public.agent_routing_decisions "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_card_drafts_select_public ON public.agent_card_drafts "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_card_drafts_insert_public ON public.agent_card_drafts "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(
        "CREATE POLICY agent_card_drafts_update_public ON public.agent_card_drafts "
        "FOR UPDATE USING (shop_id = app_current_shop_id()) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.agent_conversations TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.agent_messages TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT ON public.agent_routing_decisions TO juli_app';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.agent_card_drafts TO juli_app';
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'REVOKE ALL ON public.agent_card_drafts FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.agent_routing_decisions FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.agent_messages FROM juli_app';
            EXECUTE 'REVOKE ALL ON public.agent_conversations FROM juli_app';
        END IF;
    END
    $$;
    """)
    op.drop_index("ix_agent_card_drafts_message", table_name="agent_card_drafts")
    op.drop_table("agent_card_drafts")
    op.drop_index("ix_agent_routing_decisions_message", table_name="agent_routing_decisions")
    op.drop_table("agent_routing_decisions")
    op.drop_index("uq_agent_messages_one_running", table_name="agent_messages")
    op.drop_index("ix_agent_messages_shop_created", table_name="agent_messages")
    op.drop_index("ix_agent_messages_conversation", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_conversations_shop", table_name="agent_conversations")
    op.drop_table("agent_conversations")

"""The Juli tab's LLM cost in the system-wide spend (batch-1120, owner 2026-11-20)

Revision ID: 138_juli_agent_spend
Revises: 137_juli_agent_chat
Create Date: 2026-11-20

``public.openai_spend_since(timestamp)`` (086, D28.3) is the system cap's spend on Postgres: a
SECURITY DEFINER sum over every shop, because a tenant-scoped session sees only its own rows. It
now adds ``agent_messages.cost_usd`` (migration 137) to ``workflow_runs`` and
``content_analyses`` -- the same three sums as ``shop_rules.openai_cap.openai_spend_this_month``
and the SQLite path of ``ops.system_cap.system_spend_since``.

``CREATE OR REPLACE`` keeps the function's grants (EXECUTE to ``juli_app`` and ``juli_ops``
only, PUBLIC revoked in 086); the same signature, owner, ``search_path`` and SECURITY DEFINER.

REVERSIBLE: ``downgrade`` restores the 086 body (two sums). No table or row is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "138_juli_agent_spend"
down_revision: str | None = "137_juli_agent_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.openai_spend_since(p_since timestamp)
    RETURNS numeric
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT
            COALESCE((SELECT SUM(r.cost_usd) FROM public.workflow_runs r
                      WHERE r.created_at >= p_since), 0)
          + COALESCE((SELECT SUM(a.cost_usd) FROM public.content_analyses a
                      WHERE a.created_at >= p_since), 0)
          + COALESCE((SELECT SUM(m.cost_usd) FROM public.agent_messages m
                      WHERE m.created_at >= p_since), 0)
    $fn$;
    """)


def downgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.openai_spend_since(p_since timestamp)
    RETURNS numeric
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT
            COALESCE((SELECT SUM(r.cost_usd) FROM public.workflow_runs r
                      WHERE r.created_at >= p_since), 0)
          + COALESCE((SELECT SUM(a.cost_usd) FROM public.content_analyses a
                      WHERE a.created_at >= p_since), 0)
    $fn$;
    """)

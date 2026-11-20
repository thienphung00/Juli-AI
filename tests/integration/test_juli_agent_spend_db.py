"""Migration 138 on real Postgres: the system spend (``openai_spend_since``) counts the Juli tab.

- the SECURITY DEFINER sum adds ``agent_messages.cost_usd`` of every shop since the instant;
- it is still EXECUTE-able by ``juli_app`` (grants kept by ``CREATE OR REPLACE``) and, run as
  ``juli_app`` in one shop's scope, still sums every shop;
- last: ``downgrade`` to 137 restores the 086 body (no agent sum), ``upgrade head`` restores 138.

Synthetic tenants only.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
SINCE = datetime(2000, 1, 1)


def _spend(conn) -> Decimal:
    return Decimal(
        str(conn.execute(text("SELECT public.openai_spend_since(:s)"), {"s": SINCE}).scalar())
    )


def _answer(conn, shop_id: uuid.UUID, cost: str) -> None:
    conv = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.agent_conversations (id, shop_id, platform, title) "
            "VALUES (:id, :shop, 'shopee', 't')"
        ),
        {"id": conv, "shop": shop_id},
    )
    conn.execute(
        text(
            "INSERT INTO public.agent_messages "
            "(id, shop_id, conversation_id, role, status, events, cost_usd) "
            "VALUES (:id, :shop, :conv, 'assistant', 'done', '[]'::jsonb, :cost)"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "conv": conv, "cost": Decimal(cost)},
    )


def test_the_system_spend_counts_every_shops_juli_tab(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        before = _spend(conn)
        _answer(conn, a.shop_id, "0.25")
        _answer(conn, b.shop_id, "0.75")
        assert _spend(conn) - before == Decimal("1.00")


def test_the_runtime_role_still_runs_it_across_shops(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _answer(conn, b.shop_id, "0.50")
        owner_total = _spend(conn)
    with owner_engine.connect() as conn:
        conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
        conn.execute(
            text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(a.shop_id)}
        )
        assert _spend(conn) == owner_total  # one shop's scope, every shop's sum
        conn.execute(text("RESET ROLE"))


def test_zz_downgrade_restores_the_086_body(owner_engine, two_tenants):
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    a, _ = two_tenants
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def body() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(
                text("SELECT prosrc FROM pg_proc WHERE proname = 'openai_spend_since'")
            ).scalar()

    assert "agent_messages" in body()
    command.downgrade(cfg, "137_juli_agent_chat")
    try:
        assert "agent_messages" not in body() and "content_analyses" in body()
    finally:
        command.upgrade(cfg, "head")
    assert "agent_messages" in body()

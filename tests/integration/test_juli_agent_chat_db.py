"""Migration 137 on real Postgres: the Juli tab's four tenant tables.

- row-level security is on for all four; ``juli_app`` has SELECT / INSERT / UPDATE on
  conversations, messages and drafts, SELECT / INSERT on routing decisions, no DELETE;
  ``juli_ops`` nothing;
- two tenants: a shop sees and writes only its own rows; a smuggled insert for another shop fails;
- one running answer per conversation (the partial unique index);
- the engine's analysis session (``read_only_session_factory``) refuses every write, per
  transaction (nothing session-level);
- two concurrent sends of one draft make one card (the draft row is locked);
- the purge sweep finds every table (uuid ``shop_id``);
- last: ``downgrade`` to 134 drops the tables, ``upgrade head`` restores them.

Synthetic tenants only.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
TABLES = ("agent_conversations", "agent_messages", "agent_routing_decisions", "agent_card_drafts")
GRANTS = {
    "agent_conversations": {"SELECT", "INSERT", "UPDATE"},
    "agent_messages": {"SELECT", "INSERT", "UPDATE"},
    "agent_routing_decisions": {"SELECT", "INSERT"},
    "agent_card_drafts": {"SELECT", "INSERT", "UPDATE"},
}


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def _conversation(conn, shop_id: uuid.UUID) -> uuid.UUID:
    row_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.agent_conversations (id, shop_id, platform, title) "
            "VALUES (:id, :shop, 'shopee', 'GMV?')"
        ),
        {"id": row_id, "shop": shop_id},
    )
    return row_id


def _message(
    conn, shop_id: uuid.UUID, conversation_id: uuid.UUID, status: str = "running"
) -> uuid.UUID:
    row_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.agent_messages "
            "(id, shop_id, conversation_id, role, status, events) "
            "VALUES (:id, :shop, :conv, 'assistant', :status, CAST(:events AS jsonb))"
        ),
        {
            "id": row_id,
            "shop": shop_id,
            "conv": conversation_id,
            "status": status,
            "events": json.dumps([]),
        },
    )
    return row_id


def test_every_table_has_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        on = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": list(TABLES)},
            ).all()
        )
    assert on == dict.fromkeys(TABLES, True)


def test_grants_for_the_runtime_role_and_none_for_ops(owner_engine):
    with owner_engine.connect() as conn:
        assert {t: _verbs(conn, RUNTIME_ROLE, t) for t in TABLES} == GRANTS
        if _role_exists(conn, "juli_ops"):
            assert {t: _verbs(conn, "juli_ops", t) for t in TABLES} == dict.fromkeys(TABLES, set())


def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        conv_a = _conversation(conn, a.shop_id)
        _message(conn, a.shop_id, conv_a, status="done")
        conv_b = _conversation(conn, b.shop_id)
        _message(conn, b.shop_id, conv_b, status="done")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        for table in ("agent_conversations", "agent_messages"):
            shops = set(conn.execute(text(f"SELECT shop_id FROM public.{table}")).scalars())  # nosec B608
            assert shops == {a.shop_id}, table
        # another shop's row is invisible to UPDATE too
        hit = conn.execute(
            text("UPDATE public.agent_conversations SET title = 'x' WHERE id = :id"),
            {"id": conv_b},
        ).rowcount
        assert hit == 0
        with pytest.raises(DBAPIError):
            _conversation(conn, b.shop_id)
        conn.rollback()
        _scope(conn, a.shop_id)
        with pytest.raises(DBAPIError):
            conn.execute(
                text("DELETE FROM public.agent_conversations WHERE id = :id"), {"id": conv_a}
            )
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_one_running_answer_per_conversation(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        conv = _conversation(conn, a.shop_id)
        _message(conn, a.shop_id, conv, status="running")
        _message(conn, a.shop_id, conv, status="done")  # finished answers do not count
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as excinfo:
            _message(conn, a.shop_id, conv, status="running")
        assert "uq_agent_messages_one_running" in str(excinfo.value)
        conn.rollback()


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("agent_messages", "status", "paused"),
        ("agent_messages", "role", "system"),
        ("agent_conversations", "platform", "lazada"),
    ],
)
def test_the_checks_refuse_bad_values(owner_engine, two_tenants, table, column, value):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        conv = _conversation(conn, a.shop_id)
        msg = _message(conn, a.shop_id, conv, status="done")
    target = msg if table == "agent_messages" else conv
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as excinfo:
            conn.execute(
                text(f"UPDATE public.{table} SET {column} = :v WHERE id = :id"),  # nosec B608
                {"v": value, "id": target},
            )
        assert "ck_" in str(excinfo.value)
        conn.rollback()


async def test_the_analysis_session_is_read_only(two_tenants):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from juli_backend.core.async_db import async_database_url
    from juli_backend.services.juli_agent_api import read_only_session_factory

    a, _ = two_tenants
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]), poolclass=NullPool)
    try:
        factory = read_only_session_factory(async_sessionmaker(engine), a.shop_id)
        async with factory() as session:
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"
            # per transaction only: nothing session-level that a pooled connection could keep
            assert await session.scalar(text("SHOW default_transaction_read_only")) == "off"
            await session.commit()
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"  # next one
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(
                    text(
                        "INSERT INTO public.agent_conversations (id, shop_id, platform, title) "
                        "VALUES (:id, :shop, 'shopee', 'x')"
                    ),
                    {"id": uuid.uuid4(), "shop": a.shop_id},
                )
            assert "read-only" in str(excinfo.value)
    finally:
        await engine.dispose()


async def test_two_concurrent_sends_of_one_draft_make_one_card(owner_engine, two_tenants):
    import asyncio
    from datetime import datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from juli_backend.core.async_db import async_database_url
    from juli_backend.services.juli_agent_api import send_card

    a, _ = two_tenants
    ref = f"d_{uuid.uuid4().hex[:12]}"
    with owner_engine.begin() as conn:
        conv = _conversation(conn, a.shop_id)
        msg = _message(conn, a.shop_id, conv, status="done")
        conn.execute(
            text(
                "INSERT INTO public.agent_card_drafts (id, shop_id, message_id, draft_ref, card, "
                "status) VALUES (:id, :shop, :msg, :ref, CAST(:card AS jsonb), 'drafted')"
            ),
            {
                "id": uuid.uuid4(),
                "shop": a.shop_id,
                "msg": msg,
                "ref": ref,
                "card": json.dumps(
                    {
                        "draft_ref": ref,
                        "kind": "product_discount",
                        "item_id": "1001",
                        "recommended": "A",
                        "engine_card": {"versions": [{"label": "A", "inputs": {}}]},
                    }
                ),
            },
        )
    calls: list[int] = []

    async def create(session, shop_id, variants, chosen, user_id, **kw):
        calls.append(1)
        await asyncio.sleep(0.3)  # the second send waits on the row lock meanwhile
        return {"id": str(uuid.uuid4()), "code": "JC-2611-0001", "status": "sent"}

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def one() -> dict:
        async with factory() as session:
            out = await send_card(
                session,
                shop_id=a.shop_id,
                user_id=a.user_id,
                draft_ref=ref,
                version_label=None,
                now=datetime(2026, 11, 20, 3, 0),
                create=create,
            )
            await session.commit()
            return out

    try:
        first, second = await asyncio.gather(one(), one())
    finally:
        await engine.dispose()
    assert len(calls) == 1
    assert sorted([first["already_sent"], second["already_sent"]]) == [False, True]
    assert first["card_code"] == second["card_code"] == "JC-2611-0001"


def test_the_purge_sweep_finds_every_table(owner_engine):
    """The purge deletes from every base table with a uuid ``shop_id`` (094)."""
    with owner_engine.connect() as conn:
        found = set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                    "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                    "AND NOT a.attisdropped AND c.relname = ANY(:t)"
                ),
                {"t": list(TABLES)},
            ).scalars()
        )
    assert found == set(TABLES)


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade below 137, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def present() -> set[str]:
        with owner_engine.connect() as conn:
            return {
                t
                for t in TABLES
                if conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{t}"}).scalar()
            }

    assert present() == set(TABLES)
    command.downgrade(cfg, "137_juli_agent_chat-1")
    try:
        assert present() == set()
    finally:
        command.upgrade(cfg, "head")
    assert present() == set(TABLES)

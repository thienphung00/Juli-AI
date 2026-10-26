"""``llm_call_log`` on real Postgres as ``juli_app`` (ADR-116 §5, D76, migration 105).

- RLS on; ``juli_app`` granted SELECT and INSERT only; one policy per verb;
- two tenants (ADR-089): the gate under shop A's scope writes A's rows (in a
  SAVEPOINT on the caller's session, with consent granted through ``grant_consent``);
  under B's scope A's rows are invisible, B cannot insert a row for A, and B's gate
  without consent refuses and logs B's own ``refused`` row;
- append-only: ``juli_app`` UPDATE / DELETE are refused; the CHECKs hold;
- the migration's downgrade to 104 drops the table and ``upgrade head`` restores it.

It downgrades a revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its own.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.openai_adapter import (
    LLMGateRefusedError,
    OpenAIResponsesAdapter,
)
from juli_backend.services.llm_gate import LLM_PROCESSING, SessionCallLog, open_gate
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.consent import grant_llm_consent

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE = "llm_call_log"
CONFIG = LLMConfig(
    model="gpt-5.4-nano", max_output_tokens=50, temperature=0.0, request_timeout_seconds=5
)


@asynccontextmanager
async def app_session(shop_id: uuid.UUID):
    """A ``juli_app`` async session scoped to one shop whose commits really commit."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                    v=str(shop_id)
                )
            )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _rows(owner_engine, shop_id: uuid.UUID) -> list[tuple]:
    with owner_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT purpose, status, refusal_reason, input_tokens, output_tokens, "
                    "request_id, project FROM public.llm_call_log WHERE shop_id = :shop "
                    "ORDER BY created_at"
                ),
                {"shop": str(shop_id)},
            )
        )


def _transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {"input_tokens": 11, "output_tokens": 2},
            },
            headers={"x-request-id": "req_pg"},
        )

    return httpx.MockTransport(handler)


async def _call(gate, seen) -> None:
    await OpenAIResponsesAdapter(gate=gate, transport=_transport(seen)).complete(
        messages=[{"role": "user", "content": json.dumps({"title": "Mặt nạ", "sold": 3})}],
        system="s",
        tools=[],
        config=CONFIG,
    )


def test_rls_on_and_juli_app_may_select_and_insert_only(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text(f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{TABLE}'::regclass")  # nosec B608
        ).scalar_one()
        grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = :t AND grantee = :role"
                ),
                {"t": TABLE, "role": RUNTIME_ROLE},
            )
        }
        policies = {
            row[0]
            for row in conn.execute(
                text("SELECT cmd FROM pg_policies WHERE tablename = :t"), {"t": TABLE}
            )
        }
    assert rls is True
    assert grants == {"SELECT", "INSERT"}
    assert policies == {"SELECT", "INSERT"}


@pytest.mark.asyncio
async def test_the_gate_logs_each_shops_calls_under_its_own_scope(
    owner_engine, two_tenants, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")
    tenant_a, tenant_b = two_tenants
    seen: list[httpx.Request] = []

    async with app_session(tenant_a.shop_id) as session:
        await grant_llm_consent(session, tenant_a.shop_id, (LLM_PROCESSING,))
        gate = await open_gate(session, tenant_a.shop_id, sink=SessionCallLog(session))
        await _call(gate, seen)
        await session.commit()

    async with app_session(tenant_b.shop_id) as session:
        gate = await open_gate(session, tenant_b.shop_id, sink=SessionCallLog(session))
        with pytest.raises(LLMGateRefusedError):
            await _call(gate, seen)
        await session.commit()
        visible = (await session.execute(text("SELECT shop_id FROM public.llm_call_log"))).all()
        assert {row[0] for row in visible} == {tenant_b.shop_id}
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.llm_call_log (id, shop_id, purpose, model, endpoint, "
                    " project, input_tokens, output_tokens, status) VALUES (:id, :shop, "
                    " 'agent_run', 'm', '/v1/responses', 'p', 0, 0, 'sent')"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()

    assert len(seen) == 1  # B's refused call made no HTTP request
    assert _rows(owner_engine, tenant_a.shop_id) == [
        ("agent_run", "sent", None, 11, 2, "req_pg", "juli-client-data")
    ]
    assert _rows(owner_engine, tenant_b.shop_id) == [
        ("agent_run", "refused", "consent_llm_processing", 0, 0, None, "juli-client-data")
    ]


@pytest.mark.asyncio
async def test_append_only_for_juli_app(owner_engine, two_tenants):
    tenant_a, _ = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        await session.execute(
            text(
                "INSERT INTO public.llm_call_log (id, shop_id, purpose, model, endpoint, "
                " project, input_tokens, output_tokens, status) VALUES (:id, :shop, "
                " 'agent_run', 'm', '/v1/responses', 'p', 1, 1, 'sent')"
            ),
            {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
        )
        await session.commit()
        for statement in (
            "UPDATE public.llm_call_log SET input_tokens = 0 WHERE shop_id = :shop",
            "DELETE FROM public.llm_call_log WHERE shop_id = :shop",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(text(statement), {"shop": str(tenant_a.shop_id)})
            await session.rollback()
    assert [r[3] for r in _rows(owner_engine, tenant_a.shop_id)][-1] == 1  # untouched


def test_check_constraints_refuse_bad_values(owner_engine, two_tenants):
    _, tenant_b = two_tenants
    before = _rows(owner_engine, tenant_b.shop_id)
    for status, reason in (("done", None), ("refused", None), ("sent", "consent_llm_images")):
        with pytest.raises(IntegrityError, match="ck_llm_call_log"):
            with owner_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO public.llm_call_log (id, shop_id, purpose, model, "
                        " endpoint, project, input_tokens, output_tokens, status, "
                        " refusal_reason) VALUES (:id, :shop, 'agent_run', 'm', "
                        " '/v1/responses', 'p', 0, 0, :status, :reason)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "shop": str(tenant_b.shop_id),
                        "status": status,
                        "reason": reason,
                    },
                )
    assert _rows(owner_engine, tenant_b.shop_id) == before


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 105's parent, then back to head."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    parent = ScriptDirectory.from_config(cfg).get_revision("105_llm_call_log").down_revision

    def exists() -> bool:
        with owner_engine.connect() as conn:
            return (
                conn.execute(text(f"SELECT to_regclass('public.{TABLE}')")).scalar_one()  # nosec B608
                is not None
            )

    def current() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert exists()
    command.downgrade(cfg, parent)
    assert current() == parent and not exists()
    command.upgrade(cfg, "head")
    assert exists()

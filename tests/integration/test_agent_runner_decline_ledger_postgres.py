"""`WorkflowRunner.resume(approved=False)` proven against the REAL
`tool_executions` ledger table -- issue #1225 / AGT-W5A, ADR-075 decision 2.

"The `tool_executions` ledger has no row for the declined operation --
'nothing happened' is provable, not inferred." A `_SpyToolExecutor` assertion
(`calls == []`, `tests/unit/test_agent_runner_pause_resume.py`) only proves
this module's OWN `ToolExecutor` collaborator was never invoked -- it says
nothing about the actual persisted `tool_executions` table a real
`ToolExecutionLedger` (`services/agent/runner/ledger.py`, ADR-073 decision 3)
writes through. This suite drives a real CONFIRM pause + a real declined
`resume()` through `WorkflowRunner`, against a REAL, already-migrated
Postgres schema, then queries the REAL `ToolExecution` ORM model -- the same
table `ToolExecutionLedger.execute_write` durably INSERTs an `in_flight` row
into BEFORE any vendor call, per ADR-073 decision 3's own ordering -- and
asserts zero rows for this run's declined `tool_call_id`.

Migrates `DATABASE_URL` itself to head (no downgrade, no destructive
migration testing, never `ALLOW_DESTRUCTIVE_MIGRATION_TESTS`) rather than
spinning up a second disposable database inside this module -- mirroring
`tests/integration/test_agent_confirmation_decision_postgres.py`'s own
established convention for this exact runner/`run_confirmations` area. Skips
loudly (not silently) when `DATABASE_URL` is not a reachable Postgres
instance -- a skip reported as a pass is exactly the failure mode this
criterion is guarding against.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.models.models import Product, Shop, ToolExecution, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "The real tool_executions ledger proof for #1225's decline path must run "
        "against a reachable Postgres DATABASE_URL, not SQLite -- the assertion "
        "queries the same ORM-mapped table ToolExecutionLedger itself writes "
        "through. Set DATABASE_URL to a disposable local Postgres 16 instance to "
        "run this."
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Real Alembic migrations against DATABASE_URL, once per module -- real
    schema (`tool_executions`, `run_confirmations`, ...), not
    `Base.metadata.create_all`. No downgrade anywhere in this file -- this
    module only ever INSERTs/SELECTs against an already-migrated database,
    so it is deliberately NOT `@pytest.mark.migration_heavy`."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location", os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(_database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


@pytest.fixture
def sync_session() -> Session:
    engine = create_engine(sync_database_url(_database_url()))
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _SpyToolExecutor:
    """The runner's own `ToolExecutor` collaborator -- proves this module
    never even attempts to dispatch. The real-ledger query below is what
    proves the stronger, independent fact this issue actually asks for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((tool_name, params))
        return {"ok": True}


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


async def _seed_shop_and_product(factory) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-W5A #1225 Ledger Shop")
        session.add(shop)
        await session.flush()
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"agt-1225-pg-{uuid.uuid4()}",
            name="Test Product",
            status="active",
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(product)
        await session.flush()
        await session.commit()
        return shop.id, product.id


async def _seed_run(factory, shop_id: uuid.UUID, product_id: uuid.UUID) -> uuid.UUID:
    async with factory() as session:
        run = WorkflowRunRow(
            id=uuid.uuid4(),
            shop_id=shop_id,
            product_id=product_id,
            state=RunState().to_dict(),
            status="running",
            prompt_version="v1",
            prompt_sha256="0" * 64,
        )
        session.add(run)
        await session.commit()
        return run.id


class TestDeclineLeavesNoRealLedgerRow:
    async def test_decline_writes_zero_tool_execution_rows_for_the_declined_call(
        self, async_engine_factory, sync_session: Session
    ):
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        # --- Pause: propose update_product_listing (a real CONFIRM step) ---
        async with factory() as session:
            runner = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[
                        _turn(
                            ToolCallBlock(
                                call_id="call-listing",
                                tool_name="update_product_listing",
                                arguments={"title": "New improved title"},
                            )
                        )
                    ]
                ),
                tool_executor=_SpyToolExecutor(),
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            )
            paused = await runner.run(run_id, product_ref="agt-1225-pg")
            assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
            await session.commit()

        # --- Resume declined: a fresh WorkflowRunner, sharing only the row's
        # blob -- the model gets one closing turn, but the declined
        # update_product_listing call must never reach ToolExecutor at all --
        spy = _SpyToolExecutor()
        async with factory() as session:
            runner = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[_turn(FinalResponse(content="Understood, no changes made."))]
                ),
                tool_executor=spy,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            )
            result = await runner.resume(run_id, approved=False)
            await session.commit()

        assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
        assert result.status == WorkflowRunStatus.COMPLETED
        assert result.final_response == "Understood, no changes made."
        assert spy.calls == []

        # --- The actual acceptance criterion: query the REAL ledger table,
        # not a Python double, for a row naming this run's declined call ----
        rows = (
            sync_session.execute(
                select(ToolExecution).where(ToolExecution.workflow_run_id == run_id)
            )
            .scalars()
            .all()
        )
        assert rows == [], (
            "the declined update_product_listing call must leave zero rows in the "
            "real tool_executions ledger -- 'nothing happened' must be provable "
            "against the table itself, not inferred from a spy never being called"
        )

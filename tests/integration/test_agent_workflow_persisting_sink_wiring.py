"""Issue #1171 -- the real Celery task path (no injection) must construct
its `WorkflowRunner` with `PersistingEventSink`, not `InMemoryEventSink`
(`workers/tasks/agent_workflow.py::_construct_runner`, ADR-074 decision 3).
`tests/unit/test_agent_workflow_task_wiring.py`'s
`TestConstructRunnerUsesRealPersistingEventSink` proves the *type* of
`event_sink` `_construct_runner` builds; this module proves the
consequence end to end against real Postgres: a run driven through
`_run_agent_workflow_async` -- the exact function the Celery task body
calls, never the sink directly -- leaves `workflow_run_events` rows behind,
written by the sink `_construct_runner` builds for itself, not one this
test injects.

**What this module can and cannot drive.** `_construct_runner`'s three
composition seams (`_default_llm_service`/`_default_tool_registry`/
`_default_playbook`) no longer fail closed from `workers/` by default as of
issue #1173 -- `services/agent/composition.py` closes the depth-2
cross-package gap that used to block them (see `agent_workflow.py`'s own
module docstring). This module still overrides all three anyway: exercising
a real OpenAI completion (which `_default_llm_service` would now attempt
with a real `OPENAI_API_KEY`) is out of scope for a Postgres-plumbing test,
and this module's whole point is the `event_sink` hand-off, not the LLM/
tool-registry/playbook pieces -- so it keeps monkeypatching the three
`_default_*` composition points and `services.agent.runner.WorkflowRunner`,
exactly as `test_agent_workflow_task_wiring.py`'s own
`TestTaskBodiesCallRealRunnerMethods` does against sqlite, and swaps sqlite
for a real, disposable Postgres database to assert against
`workflow_run_events` directly. The monkeypatched runner still emits
through the REAL `event_sink` `_construct_runner` builds internally (never
one this test constructs and hands in) -- that hand-off is the one thing
this issue's scope is actually about.

Follows `test_agent_events_streaming_matrix.py`'s (#1131) disposable-Postgres
convention exactly: one throwaway database per session, created from
`DATABASE_URL`'s own connection parameters and dropped at teardown, never
touching `DATABASE_URL`'s own database directly. `DATABASE_URL` itself is
monkeypatched to point at that disposable database only inside each test
(not at fixture/session scope) -- `_construct_runner`'s new
`_resolve_event_publisher`/`_ensure_session_factory()` calls, and
`_sync_ledger_session`'s own sync engine, all read `DATABASE_URL` fresh
from the environment (`workers/tasks/database.py`'s single choke point),
exactly the surface a live worker process resolves against.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.database.database import Base
from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events import WorkflowRunEventAdapter
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep, TerminationPolicy
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.workers.tasks import agent_workflow

# ---------------------------------------------------------------------------
# Postgres reachability + disposable database -- mirrors
# tests/integration/test_agent_events_streaming_matrix.py's own fixtures
# (#1131), own db name prefix so the two never collide even run together.
# ---------------------------------------------------------------------------


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
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
        "Issue #1171's task-wiring integration test requires a reachable "
        "Postgres DATABASE_URL -- a skipped run here proves nothing; see "
        "the executor's report for pass/skip status with and without "
        "DATABASE_URL set."
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


@pytest.fixture(scope="session")
def _disposable_postgres_url():
    base_url = _database_url()
    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_agt_1171_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        yield disposable_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


@pytest.fixture(scope="session")
def _postgres_schema_ready(_disposable_postgres_url: str) -> None:
    engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        Base.metadata.create_all(conn, checkfirst=True)
    engine.dispose()


@pytest_asyncio.fixture
async def pg_engine(_disposable_postgres_url: str, _postgres_schema_ready: None):
    url = async_database_url(_disposable_postgres_url)
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Seeding -- a shop/product/workflow_run row, mirroring
# test_agent_events_streaming_matrix.py's own `_seed_shop`/`_seed_run`.
# ---------------------------------------------------------------------------


async def _seed_shop(session_factory: async_sessionmaker[AsyncSession]) -> Shop:
    async with session_factory() as session:
        user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(user_id=user.id, shop_name=f"AGT-1171-{uuid.uuid4()}")
        session.add(shop)
        await session.flush()
        await session.commit()
        return shop


async def _seed_run(
    session_factory: async_sessionmaker[AsyncSession], shop: Shop
) -> tuple[WorkflowRunRow, Product]:
    async with session_factory() as session:
        product = Product(
            shop_id=shop.id,
            tiktok_product_id=f"agt-1171-{uuid.uuid4()}",
            name="Sink Wiring Widget",
            status="active",
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(product)
        await session.flush()
        run = WorkflowRunRow(
            shop_id=shop.id,
            product_id=product.id,
            state={"basis_snapshots": {}},
            status="running",
            prompt_version="optimize_product.v1",
            prompt_sha256="c" * 64,
        )
        session.add(run)
        await session.flush()
        await session.commit()
        await session.refresh(run)
        await session.refresh(product)
        return run, product


def _dummy_playbook() -> Playbook:
    return Playbook(
        workflow_key="test_workflow",
        version=1,
        steps=(
            PlaybookStep(
                step_id="s1", intent="Do a thing.", tools=("noop",), policy=ToolPolicy.AUTO
            ),
        ),
        termination_policy=TerminationPolicy(
            max_iterations=1,
            max_extensions=0,
            extension_iterations=1,
            wall_clock_timeout_s=60,
            approval_timeout_h=1,
            required_steps=("noop",),
        ),
    )


class _EmittingSpyWorkflowRunner:
    """Stands in for the real `WorkflowRunner` -- structurally identical to
    `test_agent_workflow_task_wiring.py`'s own `_SpyWorkflowRunner`, but
    `run()` actually calls the constructed `event_sink.emit(...)` with one
    real `WorkflowRunEvent`, which is the one thing this module needs a spy
    to do that the unit-level spy does not: prove the sink `_construct_
    runner` built for itself (never injected here) is what ends up writing
    `workflow_run_events` rows.
    """

    last_kwargs: dict | None = None

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs

    async def run(self, workflow_run_id, *, product_ref):
        envelope = WorkflowRunEventAdapter.validate_python(
            {
                "workflow_run_id": workflow_run_id,
                "sequence_number": 1,
                "event_type": "workflow.started",
                "timestamp": datetime.now(UTC),
                "payload": {
                    "workflow_key": "optimize_product",
                    "product_ref": product_ref,
                    "prompt_version": "v1",
                },
                "v": 1,
            }
        )
        await type(self).last_kwargs["event_sink"].emit(envelope)
        return "RAN"

    async def resume(self, workflow_run_id, *, approved):
        return "RESUMED"


async def test_run_agent_workflow_async_persists_events_via_the_constructed_persisting_sink(
    _disposable_postgres_url: str,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    """Drives `_run_agent_workflow_async` -- the exact body the real
    `run_agent_workflow` Celery task calls -- with no `event_sink` injected
    anywhere in this test. `_construct_runner` must build its own
    `PersistingEventSink` from the real `DATABASE_URL`/`REDIS_URL`
    environment, and that sink's INSERT-then-commit must actually land a
    `workflow_run_events` row in the disposable Postgres database.

    `REDIS_URL` is explicitly unset (ADR-074 decision 3, issue #1171's own
    "Redis absence must not break correctness" clause): `_resolve_event_
    publisher` must fall back to `_NullEventPublisher` rather than raise or
    block, and the row must still persist regardless.
    """
    monkeypatch.setenv("DATABASE_URL", _disposable_postgres_url)
    monkeypatch.delenv("REDIS_URL", raising=False)

    import juli_backend.services.agent.runner as runner_pkg

    monkeypatch.setattr(runner_pkg, "WorkflowRunner", _EmittingSpyWorkflowRunner)
    monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
    monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
    monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)

    shop = await _seed_shop(pg_session_factory)
    run, product = await _seed_run(pg_session_factory, shop)

    await agent_workflow._run_agent_workflow_async(str(run.id))

    # The constructed runner's kwargs -- proof _construct_runner (not this
    # test) built the sink that then received the emit() call below.
    kwargs = _EmittingSpyWorkflowRunner.last_kwargs
    assert kwargs is not None
    assert isinstance(kwargs["event_sink"], PersistingEventSink)

    async with pg_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(WorkflowRunEventRow).where(WorkflowRunEventRow.workflow_run_id == run.id)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1, (
        "the real, non-injected PersistingEventSink _construct_runner builds "
        "must have persisted exactly one workflow_run_events row"
    )
    assert rows[0].sequence_number == 1
    assert rows[0].event_type == "workflow.started"
    assert rows[0].payload["product_ref"] == product.tiktok_product_id

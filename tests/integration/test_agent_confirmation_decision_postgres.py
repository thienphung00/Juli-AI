"""Postgres-only proofs for `POST /v1/demo/runs/{run_id}/confirmations/
{tool_call_id}` (ADR-075 decision 2, issue #1224 / AGT-W5A) that SQLite
cannot exercise:

1. **The two-sequential-CONFIRM regression** -- #1221's review empirically
   reproduced `IntegrityError: UNIQUE constraint failed:
   run_confirmations.workflow_run_id` when `resume(approved=True)`
   continues into a SECOND CONFIRM pause on the same run, because nothing
   transitioned the first row out of `pending` before the second row's
   INSERT. `uq_run_confirmations_pending_run` (migration `039_run_confirmations`)
   is a Postgres PARTIAL unique index (`WHERE status = 'pending'`) --
   SQLite does not enforce partial indexes identically, so this is only a
   real proof against real Postgres. `OPTIMIZE_PRODUCT_PLAYBOOK`'s own
   steps 5 and 6 (`update_product_listing`, `update_product_price`) are
   BOTH `CONFIRM` and both in `required_steps`
   (`services/agent/playbooks/optimize_product.py`) -- this is the real
   production shape, not a contrived one.

2. **Single-use under a race.** Two concurrent decisions on the same
   confirmation, on separate connections (`NullPool`, mirroring
   `test_credential_refresh_concurrency.py`'s own rationale: a shared
   pooled connection would silently make "concurrent" callers reuse the
   same backend session), must yield exactly one committed transition and
   one enqueue -- `_transition_confirmation_or_none`'s atomic conditional
   `UPDATE ... WHERE status = 'pending'` is what SQLite's single-process,
   single-connection unit suite could never actually contend on.

Skips loudly (not silently) when `DATABASE_URL` is not a reachable
Postgres instance -- the same convention `test_credential_refresh_concurrency.py`
and `test_migrations.py` already use. A skip reported as a pass is exactly
the failure mode ADR-075's phase gate is guarding against here, so the skip
reason names the concrete need rather than a bare boolean.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.models.models import Product, RunConfirmation, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.confirmation import compute_params_sha
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason
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
        "#1224's two-sequential-CONFIRM regression and single-use-under-a-race "
        "proofs require a reachable Postgres DATABASE_URL -- the partial unique "
        "index and real cross-connection contention cannot be exercised on "
        "SQLite. Set DATABASE_URL to a disposable local Postgres 16 instance to "
        "run these."
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Real Alembic migrations against DATABASE_URL, once per module --
    real schema (`run_confirmations`, `uq_run_confirmations_pending_run`),
    not `Base.metadata.create_all`. No downgrade anywhere in this file --
    both tests only ever INSERT/UPDATE/SELECT against an already-migrated
    database, so this is not a destructive schema-cycling test and is
    deliberately NOT `@pytest.mark.migration_heavy`."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location", os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    """Each call returns a fresh engine/sessionmaker pair with `NullPool` --
    a dedicated physical Postgres backend connection per caller, matching
    `test_credential_refresh_concurrency.py::async_engine_factory` exactly
    (see that fixture's own docstring for why a shared pooled connection
    cannot stand in for genuinely concurrent callers)."""
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(_database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Shared doubles / helpers
# ---------------------------------------------------------------------------


class _SpyToolExecutor:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((tool_name, params))
        return dict(self._result)


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


async def _seed_shop_and_product(factory) -> tuple[uuid.UUID, uuid.UUID]:
    # Flushed in FK dependency order (user -> shop -> product) rather than
    # one `add_all` -- real Postgres foreign keys enforce insert order the
    # SQLite unit suite's looser checking does not surface.
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-W5A #1224 Postgres Shop")
        session.add(shop)
        await session.flush()
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"agt-1224-pg-{uuid.uuid4()}",
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


# ---------------------------------------------------------------------------
# 1. Two-sequential-CONFIRM regression (#1221 review; the single most
#    important test in this slice)
# ---------------------------------------------------------------------------


class TestTwoSequentialConfirmStepsDoNotCollide:
    async def test_second_confirm_pause_does_not_raise_integrity_error(self, async_engine_factory):
        """Drives the REAL `OPTIMIZE_PRODUCT_PLAYBOOK` through both of its
        CONFIRM steps (`update_product_listing`, then `update_product_price`),
        approving each through `_transition_confirmation_or_none` -- the
        exact function `api/routes/agent_runs.py::submit_confirmation_decision`
        calls -- between the two pauses. Before #1224, nothing transitioned
        the first `run_confirmations` row out of `pending`, so the second
        pause's INSERT collided with `uq_run_confirmations_pending_run` and
        raised `IntegrityError`. This test proves that no longer happens,
        and that the run reaches its terminal state.
        """
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        # --- Pause #1: update_product_listing (step 5) ---------------------
        spy_1 = _SpyToolExecutor()
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
                tool_executor=spy_1,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            )
            result_1 = await runner.run(run_id, product_ref="tt-1224")
            assert result_1.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
            await session.commit()

        # Exactly one pending row exists after the first pause.
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].status == "pending"
            confirmation_1_id = rows[0].id
            confirmation_1_tool_call_id = rows[0].tool_call_id

        # --- Approve #1 THROUGH THE SAME TRANSITION FUNCTION THE ENDPOINT
        # USES -- committed before anything continues the run, exactly
        # like `submit_confirmation_decision` orders it. ---------------------
        async with factory() as session:
            stmt = (
                RunConfirmation.__table__.update()
                .where(
                    RunConfirmation.id == confirmation_1_id,
                    RunConfirmation.status == "pending",
                )
                .values(status="approved", selected_option_id="1", decided_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            assert result.rowcount == 1
            await session.commit()

        # --- Resume into pause #2: update_product_price (step 6) --- this is
        # the exact moment the pre-#1224 IntegrityError fired.
        spy_2 = _SpyToolExecutor(result={"title": "New improved title"})
        async with factory() as session:
            runner_2 = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[
                        _turn(
                            ToolCallBlock(
                                call_id="call-price",
                                tool_name="update_product_price",
                                arguments={
                                    "skus": [
                                        {"sku_ref": "S1", "amount": "199000", "currency": "VND"}
                                    ]
                                },
                            )
                        )
                    ]
                ),
                tool_executor=spy_2,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            )
            # This is the call that raised IntegrityError pre-#1224: it
            # dispatches the approved listing write, then continues the loop
            # straight into the SECOND CONFIRM pause, inserting a second
            # `run_confirmations` row while the run has exactly one prior
            # (now non-pending) row.
            result_2 = await runner_2.resume(run_id, approved=True)
            assert result_2.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
            assert [c[0] for c in spy_2.calls] == ["update_product_listing"]
            await session.commit()

        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RunConfirmation)
                        .where(RunConfirmation.workflow_run_id == run_id)
                        .order_by(RunConfirmation.created_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2, "the second pause's INSERT must succeed, not collide"
            assert rows[0].status == "approved"
            assert rows[0].tool_call_id == confirmation_1_tool_call_id
            assert rows[1].status == "pending"
            confirmation_2_id = rows[1].id

        # --- Approve #2, same transition function, then drive to a final
        # response -- the run must reach a terminal state. ------------------
        async with factory() as session:
            stmt = (
                RunConfirmation.__table__.update()
                .where(
                    RunConfirmation.id == confirmation_2_id,
                    RunConfirmation.status == "pending",
                )
                .values(status="approved", selected_option_id="1", decided_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            assert result.rowcount == 1
            await session.commit()

        spy_3 = _SpyToolExecutor(result={"updated_skus": []})
        async with factory() as session:
            runner_3 = WorkflowRunner(
                llm_service=FakeLLMService(script=[_turn(FinalResponse(content="All done."))]),
                tool_executor=spy_3,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            )
            result_3 = await runner_3.resume(run_id, approved=True)
            assert result_3.stop_reason == StopReason.FINAL_RESPONSE
            assert [c[0] for c in spy_3.calls] == ["update_product_price"]
            await session.commit()

        async with factory() as session:
            run = await session.get(WorkflowRunRow, run_id)
            assert run is not None
            assert run.status == "completed"
            assert run.stop_reason == "final_response"


# ---------------------------------------------------------------------------
# 2. Single-use under a race, against real concurrent connections
# ---------------------------------------------------------------------------


class TestSingleUseUnderConcurrentDecisions:
    async def test_two_concurrent_decisions_yield_exactly_one_transition_and_one_enqueue(
        self, async_engine_factory
    ):
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        proposed_change = {"title": "New improved title"}
        params_sha = compute_params_sha(proposed_change)
        async with factory() as session:
            run = await session.get(WorkflowRunRow, run_id)
            state = run.state
            state["pending_confirmation"] = {
                "call_id": "call-race",
                "tool_name": "update_product_listing",
                "arguments": proposed_change,
            }
            run.state = state
            run.status = "waiting_approval"
            confirmation = RunConfirmation(
                workflow_run_id=run_id,
                tool_call_id="call-race",
                options=[
                    {
                        "option_id": "1",
                        "proposed_change": proposed_change,
                        "rationale": "Improves conversion.",
                        "params_sha": params_sha,
                    }
                ],
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=4),
            )
            session.add(confirmation)
            await session.commit()
            confirmation_id = confirmation.id

        # Real HTTP, real dependency-injected sessions -- one per request,
        # each on ITS OWN connection (NullPool), mirroring what two genuinely
        # concurrent seller taps against two different API pods would do.
        from httpx import ASGITransport, AsyncClient

        from juli_backend.api.app import create_app
        from juli_backend.api.dependencies import get_active_shop
        from juli_backend.core.security import get_current_user
        from juli_backend.database import get_session

        application = create_app()

        async def _session_dependency():
            async with factory() as sess:
                yield sess

        # Fetched once, ahead of the concurrent requests -- `Shop`/`User`
        # are simple scalar-column rows here (no lazy relationship access
        # from the route), so reusing the same already-loaded ORM instance
        # as a static override across both concurrent requests is safe
        # (`expire_on_commit=False`, and neither object is committed again
        # after this read).
        async with factory() as seed_session:
            shop_obj = await seed_session.get(Shop, shop_id)
            user_obj = await seed_session.get(User, shop_obj.user_id)

        application.dependency_overrides[get_session] = _session_dependency
        application.dependency_overrides[get_active_shop] = lambda: shop_obj
        application.dependency_overrides[get_current_user] = lambda: user_obj

        mock_task = MagicMock()
        mock_task.delay.return_value = MagicMock(id="celery-task-id-race")

        async def _post_decision(decision_body: dict) -> int:
            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/demo/runs/{run_id}/confirmations/call-race",
                    json=decision_body,
                )
                return resp.status_code

        try:
            with patch(
                "juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task
            ):
                status_a, status_b = await asyncio.gather(
                    _post_decision({"decision": "approve", "option_id": "1"}),
                    _post_decision({"decision": "decline"}),
                )
        finally:
            application.dependency_overrides.clear()

        statuses = {status_a, status_b}
        assert 202 in statuses, f"exactly one decision must win: got {status_a}, {status_b}"
        assert statuses <= {202, 409}
        assert (status_a == 409) != (status_b == 409), "exactly one loser, never zero, never two"

        assert mock_task.delay.call_count == 1, (
            f"expected exactly one enqueue across two concurrent decisions, "
            f"got {mock_task.delay.call_count}"
        )

        async with factory() as session:
            confirmation = await session.get(RunConfirmation, confirmation_id)
            assert confirmation.status in ("approved", "declined")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))

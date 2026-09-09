"""Shared harness for the five-link outcome chain (issue #1655, W8-C / P10-3).

The chain must be proven against a run seeded through the REAL
``WorkflowRunner`` on real Postgres, and two suites need that same run: the
behaviour suite (``tests/unit/test_outcome_chain_query.py``) and the
operator-journey suite (``tests/integration/test_outcome_chain_postgres.py``).
The seeding lives here rather than being copied into both, so the two can
never drift into proving different things.

What this module provides:

- :func:`create_disposable_database_at_head` — a throwaway Postgres database
  migrated by the real Alembic chain. Never DDL against ``DATABASE_URL``'s own
  database, which the migration suites in the same pytest session own outright
  and run a full ``downgrade("base")`` round trip over.
- :class:`LedgerBackedToolExecutor` — a double bound to
  ``runner.tool_executor.ToolExecutor``'s real signature that routes WRITE
  calls through the REAL ``ToolExecutionLedger``. Only the vendor call itself
  is replaced, so the ``tool_executions`` row the chain joins on is written by
  the production ledger code path.
- the seeding helpers, all of which drive real objects.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.models.models import (
    ActionCard,
    ImpactReading,
    Product,
    Shop,
    ToolExecution,
    User,
    WorkflowOutcomeRecord,
    WorkflowRun,
)
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.ledger import (
    ToolExecutionLedger,
    ToolExecutionRequestPayload,
)
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from tests.support.postgres import database_url

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations")

#: Every WRITE tool this harness routes through the real ledger.
WRITE_TOOLS = frozenset({"update_product_listing", "update_product_price"})


@contextmanager
def _database_url_env(url: str) -> Iterator[None]:
    """Point ``DATABASE_URL``/``DATABASE_DIRECT_URL`` at ``url`` for the block.

    ``migrations/env.py`` overwrites ``sqlalchemy.url`` from
    ``migration_database_url()`` (``DATABASE_DIRECT_URL``, then
    ``DATABASE_URL``), so setting it on the alembic ``Config`` alone silently
    migrates the WRONG database.
    """
    names = ("DATABASE_URL", "DATABASE_DIRECT_URL")
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ[name] = url
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def create_disposable_database_at_head(prefix: str) -> Iterator[str]:
    """Yield a throwaway Postgres database URL, migrated to head, then drop it.

    Written as a generator so a caller can wrap it in a ``pytest.fixture`` at
    whatever scope it needs.
    """
    base_url = database_url()
    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"{prefix}_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    # `str(URL)` masks the password as `***`; `render_as_string(hide_password=False)`
    # is the documented way to get a connectable URL back out.
    disposable = (
        make_url(sync_database_url(base_url))
        .set(database=db_name)
        .render_as_string(hide_password=False)
    )

    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    with _database_url_env(disposable):
        command.upgrade(cfg, "head")

    try:
        yield disposable
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


class LedgerBackedToolExecutor:
    """Satisfies ``runner.tool_executor.ToolExecutor`` exactly (keyword-only
    ``tool_name``/``params``/``tool_call_id``, returning a JSON-safe mapping)
    and routes WRITE calls through the REAL ``ToolExecutionLedger``.

    The only thing replaced is the vendor call — the ``perform`` closure — so
    the ``tool_executions`` row the chain joins on is written by the
    production ledger, INSERT-before-vendor ordering and all, not by a
    hand-built fixture row.
    """

    def __init__(
        self,
        ledger: ToolExecutionLedger,
        *,
        workflow_run_id: uuid.UUID,
        product_id: str,
        write_tools: frozenset[str] = WRITE_TOOLS,
    ) -> None:
        self._ledger = ledger
        self._workflow_run_id = workflow_run_id
        self._product_id = product_id
        self._write_tools = write_tools
        self.calls: list[tuple[str, BaseModel]] = []

    def execute(
        self, *, tool_name: str, params: BaseModel, tool_call_id: str | None = None
    ) -> Mapping[str, Any]:
        self.calls.append((tool_name, params))
        if tool_name not in self._write_tools:
            return {"ok": True}
        return self._ledger.execute_write(
            workflow_run_id=self._workflow_run_id,
            tool_call_id=tool_call_id or "call-write",
            operation=tool_name,
            perform=lambda: {"ok": True, "updated": True},
            request_payload=ToolExecutionRequestPayload(product_id=self._product_id),
        )


class NeverCalledToolExecutor:
    """The same real signature, recording calls and dispatching nothing —
    used on the decline leg, where the point is that it is never reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, BaseModel]] = []

    def execute(
        self, *, tool_name: str, params: BaseModel, tool_call_id: str | None = None
    ) -> Mapping[str, Any]:
        self.calls.append((tool_name, params))
        return {"ok": True}


def full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def write_only_playbook() -> Playbook:
    """A single CONFIRM'd write step with no terminal tools — the same shape
    ``tests/unit/test_workflow_run_rollup.py`` uses to drive a real
    pause-then-approve leg, without the full Optimize Product playbook's
    required-steps retry adding turns these suites do not care about."""
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id="write",
                intent="Publish the improved listing.",
                tools=("update_product_listing",),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
    )


def turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def stamped_prompt_pin() -> tuple[str, str]:
    """The production-pinned ``(prompt_version, prompt_sha256)`` for Optimize
    Product — what ``approval.py::approve_action_card`` stamps on run
    creation, for fixtures that build the run row directly."""
    from juli_backend.services.agent import playbooks as playbooks_module
    from juli_backend.services.agent import prompts as prompts_module

    workflow_key = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    version = prompts_module.production_version(workflow_key)
    return (
        prompts_module.prompt_version(workflow_key, version),
        prompts_module.prompt_sha256(workflow_key, version),
    )


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


async def seed_shop_and_product(factory) -> tuple[uuid.UUID, uuid.UUID, str]:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="W8-C Outcome Chain Shop")
        session.add(shop)
        await session.flush()
        tiktok_product_id = f"w8c-{uuid.uuid4().hex[:12]}"
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=tiktok_product_id,
            name="Chain Product",
            status="active",
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(product)
        await session.commit()
        return shop.id, product.id, tiktok_product_id


async def seed_action_card(factory, shop_id: uuid.UUID) -> uuid.UUID:
    async with factory() as session:
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key=f"optimize_product_2_{uuid.uuid4().hex[:8]}",
            priority=1,
            severity="high",
            title="Giảm giá sản phẩm",
            description="Điều chỉnh giá để cạnh tranh hơn.",
            recommendation_payload=json.dumps({"kind": "price"}),
            status="approved",
        )
        session.add(card)
        await session.commit()
        return card.id


async def seed_run(
    factory,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    action_card_id: uuid.UUID | None,
) -> uuid.UUID:
    async with factory() as session:
        prompt_version, prompt_sha256 = stamped_prompt_pin()
        run = WorkflowRun(
            id=uuid.uuid4(),
            shop_id=shop_id,
            product_id=product_id,
            state=RunState().to_dict(),
            status="running",
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            action_card_id=action_card_id,
        )
        session.add(run)
        await session.commit()
        return run.id


async def run_a_real_write(
    factory,
    sync_session: Session,
    *,
    run_id: uuid.UUID,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
) -> None:
    """Pause on a real CONFIRM step then resume approved, through the REAL
    ``WorkflowRunner`` and the REAL ``ToolExecutionLedger``."""
    playbook = write_only_playbook()
    executor = LedgerBackedToolExecutor(
        ToolExecutionLedger(sync_session, shop_id=shop_id),
        workflow_run_id=run_id,
        product_id=tiktok_product_id,
    )

    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    turn(
                        ToolCallBlock(
                            call_id="call-listing",
                            tool_name="update_product_listing",
                            arguments={"title": "Tiêu đề mới, tốt hơn"},
                        )
                    )
                ]
            ),
            tool_executor=executor,
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=full_registry(),
            playbook=playbook,
        )
        paused = await runner.run(run_id, product_ref=tiktok_product_id)
        assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        await session.commit()

    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[turn(FinalResponse(content="Đã cập nhật xong."))]),
            tool_executor=executor,
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=full_registry(),
            playbook=playbook,
        )
        result = await runner.resume(run_id, approved=True)
        await session.commit()
    assert result.stop_reason == StopReason.FINAL_RESPONSE


async def run_a_real_decline(factory, *, run_id: uuid.UUID, tiktok_product_id: str) -> None:
    """Pause on a real CONFIRM step, then decline — through the real runner."""
    spy = NeverCalledToolExecutor()
    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    turn(
                        ToolCallBlock(
                            call_id="call-listing",
                            tool_name="update_product_listing",
                            arguments={"title": "Tiêu đề mới"},
                        )
                    )
                ]
            ),
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=full_registry(),
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        )
        paused = await runner.run(run_id, product_ref=tiktok_product_id)
        assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        await session.commit()

    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[turn(FinalResponse(content="Đã huỷ."))]),
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=full_registry(),
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        )
        result = await runner.resume(run_id, approved=False)
        await session.commit()
    assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
    assert spy.calls == []


async def execution_id_for(factory, run_id: uuid.UUID) -> uuid.UUID:
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(ToolExecution).where(ToolExecution.workflow_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
    return rows[0].id


async def backdate_execution(factory, execution_id: uuid.UUID, *, days_ago: int) -> None:
    """Move the write's execution date T back by ``days_ago`` days.

    ``ToolExecution.updated_at`` is the write's completion time — the same
    proxy ``workers/impact_reader/queries.py::execution_t`` reads T from. The
    column is ``TIMESTAMP WITHOUT TIME ZONE``, so the value is written naive.
    """
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).replace(tzinfo=None)
    async with factory() as session:
        await session.execute(
            text("UPDATE tool_executions SET updated_at = :ts WHERE id = :id"),
            {"ts": ts, "id": execution_id},
        )
        await session.commit()


async def seed_outcome_record(factory, *, shop_id: uuid.UUID, execution_id: uuid.UUID) -> None:
    async with factory() as session:
        session.add(
            WorkflowOutcomeRecord(
                id=uuid.uuid4(),
                shop_id=shop_id,
                approval_id=f"agent-ledger:{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                workflow_id="optimize_product_2",
                execution_status="succeeded",
                metrics_json=json.dumps({"cadences": []}),
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()


async def seed_reading(
    factory,
    *,
    run_id: uuid.UUID | None,
    execution_id: uuid.UUID,
    metric: str = "gmv",
    kind: str = "preliminary",
    confidence: str = "cao",
    post: Decimal | None = Decimal("120.00"),
    incremental: Decimal | None = Decimal("20.00"),
) -> None:
    async with factory() as session:
        session.add(
            ImpactReading(
                id=uuid.uuid4(),
                run_id=run_id,
                tool_execution_id=execution_id,
                metric=metric,
                kind=kind,
                pre=Decimal("100.00"),
                post=post,
                expected=Decimal("100.00"),
                incremental=incremental,
                impact_pct=Decimal("0.200000") if incremental is not None else None,
                confidence=confidence,
                control_set_json="{}",
                computed_at=datetime.now(UTC),
                series_source="measured",
            )
        )
        await session.commit()

"""A CONFIRM pause's persisted rationale is Vietnamese, not the LLM tool
description — issue #1904 (W6-FIX), against a REAL Postgres instance.

**Why this is integration-tier, against real Postgres, not the SQLite unit
substrate.** The defect this issue fixes was found in a live
`run_confirmations` row on the sandbox shop (run `4e00d60e`): the seller-
facing Đề xuất option picker rendered `spec.description`, the English,
LLM-facing tool description, on the exact screen where a click authorizes a
real mutation. An assertion against an in-memory `WorkflowApprovalRequiredPayload`
constructed by hand proves the payload *shape* is right; it does not prove
what a real run actually persists to the table a seller's consent is
recorded against. This module drives the REAL `WorkflowRunner`, through the
REAL `PersistingEventSink`, into a REAL Postgres `workflow_run_events` row
and a REAL `run_confirmations` row, and reads both back — the same
`tests.support.postgres` disposability contract
`tests/integration/test_series_source_enforced.py` uses, not the shared
`session` unit-test fixture (SQLite even when `DATABASE_URL` names Postgres;
a DB-level claim asserted through it would prove nothing about what
Postgres actually enforces or stores).

**Migration note.** `run_confirmations` rows committed before this issue's
merge carry the old English `spec.description` text and are NOT backfilled
-- the column is trustworthy only from this merge forward. Nothing in this
module assumes otherwise; every row asserted against here is written by
this module's own real run.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.models.models import Product, RunConfirmation, Shop, User, WorkflowRunEvent
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.composition import build_product_tool_registry
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.llm import AssistantTurn, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools.product_write import UPDATE_PRODUCT_LISTING_SPEC
from tests.support.postgres import database_url, requires_postgres

pytestmark = [pytest.mark.asyncio, requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_SNAKE_CASE_IDENTIFIER = re.compile(r"\b[a-z]+_[a-z]+\b")
_VIETNAMESE_LETTERS = "àáâãăằắẳẵặầấẩẫậèéêềếểễệìíĩỉịòóôõơồốổỗộờớởỡợùúũưừứửữựỳýỵỷỹđ"
_VIETNAMESE_DIACRITIC = re.compile(f"[{_VIETNAMESE_LETTERS}{_VIETNAMESE_LETTERS.upper()}]")


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Real Alembic migrations against `DATABASE_URL`, once per module — the
    real `run_confirmations`/`workflow_run_events` schema, not
    `Base.metadata.create_all`. No downgrade in this module."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location",
        str(REPO_ROOT / "backend/src/juli_backend/database/migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(database_url()))
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    """Fresh engine/sessionmaker pair with `NullPool` per call, mirroring
    `test_agent_confirmation_decision_postgres.py::async_engine_factory`."""
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


class _NullPublisher:
    """Publish is best-effort by contract (ADR-074 d.3); this module only
    asserts against the committed rows, so the Redis half is a no-op."""

    async def publish(self, channel: str, message: str) -> None:
        return None


class _SpyToolExecutor:
    """Never actually called here: `update_product_listing` is CONFIRM-policy,
    so the run pauses before dispatch. Present only so `WorkflowRunner`
    receives a real object matching `ToolExecutor`'s shape, mirroring
    `test_agent_confirmation_decision_postgres.py::_SpyToolExecutor`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, *, tool_name: str, params, tool_call_id: str | None = None):
        self.calls.append((tool_name, params))
        return {"ok": True}


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def _stamped_prompt_pin() -> tuple[str, str]:
    from juli_backend.services.agent import playbooks as playbooks_module
    from juli_backend.services.agent import prompts as prompts_module

    workflow_key = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    version = prompts_module.production_version(workflow_key)
    return (
        prompts_module.prompt_version(workflow_key, version),
        prompts_module.prompt_sha256(workflow_key, version),
    )


async def _seed_shop_and_product(factory) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-1904 Postgres Shop")
        session.add(shop)
        await session.flush()
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"agt-1904-pg-{uuid.uuid4()}",
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
        prompt_version, prompt_sha256 = _stamped_prompt_pin()
        run = WorkflowRunRow(
            id=uuid.uuid4(),
            shop_id=shop_id,
            product_id=product_id,
            state=RunState().to_dict(),
            status="running",
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
        )
        session.add(run)
        await session.commit()
        return run.id


async def _run_to_confirm_pause(factory, run_id: uuid.UUID) -> None:
    """Drives the REAL `OPTIMIZE_PRODUCT_PLAYBOOK` + REAL `WorkflowRunner`
    through the model calling `update_product_listing`, persisting through
    the REAL `PersistingEventSink` into REAL `workflow_run_events` /
    `run_confirmations` rows."""
    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="call-listing-1904",
                            tool_name="update_product_listing",
                            arguments={"title": "Tiêu đề đã tối ưu"},
                        )
                    )
                ]
            ),
            tool_executor=_SpyToolExecutor(),  # never reached: CONFIRM pauses before dispatch
            event_sink=PersistingEventSink(factory, _NullPublisher()),
            conversation_store=JsonbConversationStore(session),
            registry=build_product_tool_registry(),
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        )
        result = await runner.run(run_id, product_ref="tt-1904")
        assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION, (
            f"expected a CONFIRM pause; got {result.stop_reason}"
        )
        await session.commit()


class TestConfirmPauseCarriesVietnameseSellerCopyNotTheEnglishToolDescription:
    async def test_the_persisted_workflow_run_event_carries_seller_rationale_vi_not_description(
        self, async_engine_factory
    ):
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        await _run_to_confirm_pause(factory, run_id)

        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(WorkflowRunEvent)
                        .where(WorkflowRunEvent.workflow_run_id == run_id)
                        .where(WorkflowRunEvent.event_type == "workflow.approval_required")
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1, "expected exactly one persisted approval_required event"
        payload = rows[0].payload
        options = payload["options"]
        assert len(options) == 1
        assert options[0]["rationale"] == UPDATE_PRODUCT_LISTING_SPEC.seller_rationale_vi

        serialized_payload = json.dumps(payload, ensure_ascii=False)
        assert UPDATE_PRODUCT_LISTING_SPEC.description not in serialized_payload, (
            "the LLM-facing English tool description must never reach the persisted "
            "event payload a seller's client reads"
        )

    async def test_the_persisted_run_confirmations_row_carries_seller_rationale_vi_not_description(
        self, async_engine_factory
    ):
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        await _run_to_confirm_pause(factory, run_id)

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
        assert len(rows) == 1, "expected exactly one persisted run_confirmations row"
        row = rows[0]
        assert row.status == "pending"
        options = row.options
        assert len(options) == 1
        assert options[0]["rationale"] == UPDATE_PRODUCT_LISTING_SPEC.seller_rationale_vi

        serialized_row = json.dumps(options, ensure_ascii=False)
        assert UPDATE_PRODUCT_LISTING_SPEC.description not in serialized_row, (
            "the LLM-facing English tool description must never land in the "
            "run_confirmations row a seller's consent is recorded against — this is "
            "the exact defect confirmed live in run 4e00d60e (issue #1904)"
        )

    async def test_the_seller_rationale_is_vietnamese_with_no_leaked_identifier(
        self, async_engine_factory
    ):
        """Direct re-statement of the release-evidence journey's third
        assertion, against the SAME real persisted row the other two tests
        in this class assert against — not a separate in-memory construction."""
        factory = async_engine_factory()
        shop_id, product_id = await _seed_shop_and_product(factory)
        run_id = await _seed_run(factory, shop_id, product_id)

        await _run_to_confirm_pause(factory, run_id)

        async with factory() as session:
            row = (
                await session.execute(
                    select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                )
            ).scalar_one()

        rationale = row.options[0]["rationale"]
        assert _VIETNAMESE_DIACRITIC.search(rationale), (
            f"persisted rationale has no Vietnamese diacritic: {rationale!r}"
        )
        assert not _SNAKE_CASE_IDENTIFIER.search(rationale), (
            f"persisted rationale leaks a snake_case identifier: {rationale!r}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))

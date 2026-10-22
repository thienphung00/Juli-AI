"""LIVE (owner-run): the sandbox "Tạo sản phẩm" run end to end -- real OpenAI, real TikTok
SANDBOX (fast track P64, D73.3 / D73.4).

Drives the real ``WorkflowRunner`` with the real ``create_product`` playbook and prompt, the
real OpenAI adapter (``composition.build_llm_service``) and the sandbox shop's real
``SandboxWriteResources`` (``composition.build_read_resources`` / ``build_write_resources``)
to the CONFIRM pause on ``create_product``, resumes it approved, and asserts TikTok returned a
new product id that reads back. It CREATES A REAL LISTING on the sandbox shop.

Skipped unless every prerequisite is present (``live`` marker, deselected in CI):
``OPENAI_API_KEY``, ``TIKTOK_APP_KEY`` / ``TIKTOK_APP_SECRET``, a Postgres ``DATABASE_URL``
holding the sandbox shop's ``sandbox_write`` credential and at least one synced product of
that shop. Never touches a production credential.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from juli_backend.core.security import resolve_sandbox_write_credential
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import SandboxWriteResources
from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent import prompts as prompts_module
from juli_backend.services.agent import run_context as run_context_module
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.runner import (
    JsonbConversationStore,
    ProductToolExecutor,
    StopReason,
    ToolExecutionLedger,
    WorkflowRunner,
)
from juli_backend.workers.tasks.database import get_async_database_url, get_sync_database_url

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY", "").strip(), reason="OPENAI_API_KEY absent"
    ),
    pytest.mark.skipif(
        not (os.environ.get("TIKTOK_APP_KEY") and os.environ.get("TIKTOK_APP_SECRET")),
        reason="TIKTOK_APP_KEY / TIKTOK_APP_SECRET absent",
    ),
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
        reason="needs the Postgres DATABASE_URL holding the sandbox credential",
    ),
]


@pytest.fixture(autouse=True)
def token_encryption_key():
    """Shadow the integration conftest's dummy key: the real sandbox token must decrypt."""
    yield


class _NullPublisher:
    async def publish(self, channel: str, message: str) -> None:
        return None


async def test_live_create_product_run_creates_and_reads_back_a_sandbox_listing():
    async_engine = create_async_engine(get_async_database_url())
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    sync_engine = create_engine(get_sync_database_url())
    sync_factory = sessionmaker(bind=sync_engine)
    try:
        async with factory() as session:
            try:
                credential = await resolve_sandbox_write_credential(session)
            except NotFound:
                pytest.skip("no sandbox_write credential in this DATABASE_URL")
            product = (
                await session.execute(
                    select(Product)
                    .where(Product.shop_id == credential.shop_id)
                    .order_by(Product.units_sold.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if product is None:
                pytest.skip("the sandbox shop has no synced product to derive from")

            read_resources = await composition_module.build_read_resources(
                session, credential.shop_id
            )
            write_resources = await composition_module.build_write_resources(session)
            assert isinstance(read_resources, SandboxWriteResources)
            assert isinstance(write_resources, SandboxWriteResources)

            playbook = playbooks_module.CREATE_PRODUCT_PLAYBOOK
            key = playbook.workflow_key
            version = prompts_module.production_version(key)
            opening = run_context_module.build_opening_context_message(
                workflow_key=key,
                rationale="Tạo một sản phẩm mới trên shop sandbox từ sản phẩm bán chạy nhất.",
            )
            run = WorkflowRunRow(
                id=uuid.uuid4(),
                shop_id=credential.shop_id,
                product_id=product.id,
                workflow_key=key,
                subject_type="product",
                subject_ref=str(product.id),
                state=run_context_module.initial_run_state(opening),
                status="running",
                prompt_version=prompts_module.prompt_version(key, version),
                prompt_sha256=prompts_module.prompt_sha256(key, version),
            )
            session.add(run)
            await session.commit()
            registry = composition_module.build_product_tool_registry()
            llm = composition_module.build_llm_service()
            sink = PersistingEventSink(factory, _NullPublisher(), shop_id=credential.shop_id)

            def runner(sync_session):
                executor = ProductToolExecutor(
                    registry=registry,
                    read_resources=read_resources,
                    write_resources=write_resources,
                    product_id=product.tiktok_product_id,
                    ledger=ToolExecutionLedger(sync_session, shop_id=run.shop_id),
                    workflow_run_id=run.id,
                )
                return WorkflowRunner(
                    llm_service=llm,
                    tool_executor=executor,
                    event_sink=sink,
                    conversation_store=JsonbConversationStore(session),
                    registry=registry,
                    playbook=playbook,
                )

            with sync_factory() as sync_session:
                first = await runner(sync_session).run(
                    run.id, product_ref=product.tiktok_product_id
                )
            assert first.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION, first
            await session.refresh(run)
            pending = run.state["pending_confirmation"]
            assert pending["tool_name"] == "create_product"
            with sync_factory() as sync_session:
                await runner(sync_session).resume(run.id, approved=True)
            await session.refresh(run)
            results = [
                message["content"]
                for message in run.state.get("conversation_window", [])
                if message.get("role") == "tool" and message.get("tool_name") == "create_product"
            ]
            assert results and results[-1].get("ok") is True, results
            new_id = results[-1]["tiktok_product_id"]
            assert write_resources.products.get_details(new_id).get("id") == new_id
    finally:
        await async_engine.dispose()
        sync_engine.dispose()

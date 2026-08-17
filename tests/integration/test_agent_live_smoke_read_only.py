"""Live smoke (a) -- read-only Optimize Product run to `final_response`
(issue #1124, W3-A/P1-8, ADR-073 decision 6's test-strategy item; HITL).

This is the read-only half of the phase gate PLAN.md Sec.6 names: "two
`live` smokes complete -- (a) read-only run reaching `final_response`, (b)
full write-path run". It drives a REAL `WorkflowRunner` (`services/agent/
runner/core.py`, #1119/#1120/#1173) through a REAL GPT-5.4 nano completion
(`OpenAIResponsesAdapter`) and a REAL TikTok production-read call
(`ProductionReadResources`, ADR-068's read-only guard), against whatever
`workflow_runs` row this test creates the same way `POST /v1/demo/runs`
(`api/routes/agent_runs.py::create_run`) does -- same prompt-pin resolution,
same `WorkflowRunner` construction shape as `workers/tasks/agent_workflow.py
::_construct_runner`, reusing the exact composition seams (`services/agent/
composition.py`) that module uses, not a hand-rolled stand-in.

**No live API calls happen unless every skip condition below clears.** This
slice's own authoring phase has neither `OPENAI_API_KEY` nor a provisioned
TikTok credential row -- the two `pytest.mark.skipif` decorators plus the
runtime `pytest.skip()` calls in the test body are what a keyless/credential-
less CI or local run actually exercises; see the executor's report for the
exact skip reasons observed with `DATABASE_URL=postgresql://macos@localhost
:5432/postgres` and no `OPENAI_API_KEY` set.

## What the live run needs present, honestly

1. `OPENAI_API_KEY` -- resolved by `services/agent/llm/config.py`'s
   `resolve_llm_config()` (`require_env`), same as `test_agent_llm_live_
   roundtrip.py`. Skips (module-collection time) when absent.
2. `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` -- the shared TikTok Partner app
   credentials `services/agent/composition.py::build_read_resources` needs
   (`_tiktok_app_credentials`, `require_env`) before it can even attempt a
   credential-row lookup. Skips (module-collection time) when either is
   absent -- this codebase's `require_env` raises `RuntimeError`, not a
   skip, so this test checks the env directly rather than letting that
   propagate as a test error.
3. A `tiktok_credentials` row for `PRODUCTION_AUTH_ID` (Fujiwa,
   `integrations/tiktok/capabilities.py`) with capability `PRODUCTION_READ`,
   in **this** `DATABASE_URL` -- resolved via `resolve_production_read_
   credential` (`core/security/credential_resolver.py`), the same function
   `composition.py::build_read_resources` calls. Skips at runtime (a real
   async DB read, so this cannot be a `skipif`) via `pytest.skip()` when
   `NotFound`. Provisioning this row is the Fujiwa OAuth connect flow --
   out of this slice's scope; see `test_fujiwa_polling_sync_state_e2e.py`
   for how a `tiktok_credentials(merchant_authorization_id=PRODUCTION_
   AUTH_ID, capability="production_read")` row gets seeded in this
   codebase's other integration tests.
4. At least one `products` row under the `shops` row that credential
   belongs to (`credential.shop_id`) -- this test picks the first one it
   finds; it never invents a `tiktok_product_id`, since a fabricated one
   would 404 against the real TikTok API the moment `get_product_
   information` is called. In practice this means Fujiwa's polling sync
   (`workers/services/polling/orchestrate.py`) has run at least once
   against this `DATABASE_URL`. Skips at runtime when no such row exists.

No hardcoded shop or product id anywhere in this module -- every identifier
is resolved from the row structure above.

## Why this test restricts the model to READ tools by constructing its own
`Playbook`, not `OPTIMIZE_PRODUCT_PLAYBOOK` directly

`services/agent/prompts/composer.py::compose()` renders the `{playbook}`
prose slot from the **canonical** `OPTIMIZE_PRODUCT_PLAYBOOK` registered in
`_WORKFLOW_BINDINGS` -- not from whatever `Playbook` object is passed to
`WorkflowRunner`'s constructor. That means the composed system prompt (and
therefore `prompt_version`/`prompt_sha256`) is identical, real, and
production-pinned regardless of which `Playbook` this test hands the
runner. What a `Playbook` instance passed to `WorkflowRunner` DOES control
is `_tool_definitions()` (the tool schemas actually offered to the model)
and `_allowed_tool_names` (the allowlist `_dispatch_tool_call` enforces) --
both read off `self._playbook.steps`, never the canonical global. This test
builds a `Playbook` whose `steps` are exactly the three READ-classified
steps of `OPTIMIZE_PRODUCT_PLAYBOOK` (`get_product_information`,
`get_seo_keywords`, `check_product_status`) so the model is structurally
unable to call a WRITE tool -- not merely told not to -- guaranteeing
`stop_reason=final_response` is reachable in one run rather than pausing at
`waiting_approval` the moment the model proposes `update_product_listing`/
`update_product_price` (both CONFIRM-policy on the real playbook). The real,
full `ToolRegistry` (`composition.build_product_tool_registry()`, all six
tools) is still used underneath -- only the *offered* allowlist is narrowed,
matching the acceptance criterion's "real tool registry" wording.

## A known, pre-existing risk this smoke may surface (not this slice's to fix)

`services/agent/llm/openai_adapter.py::_translate_message` reads a tool
message's `call_id` key for `role == "tool"`, but `services/agent/runner/
core.py` appends tool-result conversation messages keyed `tool_call_id`
(see `_dispatch_tool_call`'s `state.conversation_window.append({"role":
"tool", "tool_call_id": ..., ...})`). If this run needs a second LLM
round-trip (READ tool call, then a final-text turn) -- the common case --
the second `LLMService.complete()` call would translate that tool result
with an empty `call_id`, which the stateless OpenAI Responses API is likely
to reject as a `function_call_output` with no matching prior `function_
call` in the same request (the adapter's own docstring already flags
"reconstructing a prior turn's tool-call proposal... is out of scope
here"). This is a `services/agent/llm/` file, explicitly out of this
slice's write path -- flagged here for the operator, not patched around.
If this run raises `LLMProviderError` on the second turn rather than
reaching `final_response`, that is this pre-existing gap surfacing, not a
defect in this test.

## The opening context message

Nothing in this codebase yet seeds the `source: "juli"` opening context
message `prompts/optimize_product/v1.md` Sec.4 describes ("Before your
first tool call, the run opens with one `source: "juli"` context
message") -- that wiring is P-CS/P-IM territory, deferred past this slice
(`docs/product/agent-workflow-execution/PLAN.md` Sec.7/11b), and this
slice's constraints forbid touching `services/agent/runner/*` production
modules to add it. This test seeds it directly into `workflow_runs.state
.conversation_window` before calling `runner.run()`, in the shape Sec.4
documents, so the model has a first turn to respond to at all.
"""

from __future__ import annotations

import dataclasses
import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.core.security import resolve_production_read_credential
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import ProductionReadResources
from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent import prompts as prompts_module
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.runner import (
    JsonbConversationStore,
    ProductToolExecutor,
    StopReason,
    WorkflowRunner,
    WorkflowRunStatus,
)
from juli_backend.workers.tasks.database import get_async_database_url

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Skip conditions -- module-collection-time (env-only) plus runtime (DB-only,
# below, inside the test body -- pytest.skip() cannot be a bare skipif since
# it needs an async credential-row lookup).
# ---------------------------------------------------------------------------


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
        "This live smoke requires a reachable Postgres DATABASE_URL carrying the real "
        "project schema (tiktok_credentials/products rows) -- a schema-only disposable "
        "database always fails the credential-row skip further below anyway."
    ),
)

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY", "").strip(),
    reason="OPENAI_API_KEY absent -- live GPT-5.4 nano read-only smoke skipped (ADR-040 live).",
)

requires_tiktok_app_credentials = pytest.mark.skipif(
    not (
        os.environ.get("TIKTOK_APP_KEY", "").strip()
        and os.environ.get("TIKTOK_APP_SECRET", "").strip()
    ),
    reason=(
        "TIKTOK_APP_KEY/TIKTOK_APP_SECRET absent -- services/agent/composition.py::"
        "build_read_resources cannot resolve the production-read credential without the "
        "shared TikTok Partner app secret (require_env, same pattern as webhook_tiktok.py)."
    ),
)

# READ-classified Optimize Product tool names (services/agent/tools/product.py)
# -- the only tools this smoke's restricted Playbook ever offers the model.
_READ_TOOL_NAMES = frozenset(
    {"get_product_information", "get_seo_keywords", "check_product_status"}
)


def _read_only_playbook():
    """A `Playbook` carrying only the real playbook's READ-classified steps.

    Same `workflow_key`/`version` as `OPTIMIZE_PRODUCT_PLAYBOOK` (compose()
    keys off those two fields only, from the canonical global binding -- see
    module docstring), same `termination_policy` values, `steps` filtered to
    the three READ-only entries. See module docstring for why this is
    necessary to guarantee `stop_reason=final_response` is reachable.
    """
    canonical = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK
    read_steps = tuple(step for step in canonical.steps if set(step.tools) <= _READ_TOOL_NAMES)
    assert read_steps, "OPTIMIZE_PRODUCT_PLAYBOOK must still carry its three READ steps"
    termination_policy = dataclasses.replace(
        canonical.termination_policy, required_steps=("get_product_information",)
    )
    return playbooks_module.Playbook(
        workflow_key=canonical.workflow_key,
        version=canonical.version,
        steps=read_steps,
        termination_policy=termination_policy,
    )


async def _find_product_for_shop(session, shop_id) -> Product | None:
    result = await session.execute(
        select(Product).where(Product.shop_id == shop_id).order_by(Product.created_at).limit(1)
    )
    return result.scalar_one_or_none()


class _NullPublisher:
    """A no-op `EventPublisher` -- this smoke never needs a live Redis
    pub/sub tier; correctness is Postgres-only (ADR-074 decision 3), the
    same reasoning `workers/tasks/agent_workflow.py::_NullEventPublisher`
    documents. Not imported directly since it is a private class there."""

    async def publish(self, channel: str, message: str) -> None:
        return None


def _opening_context_message() -> dict:
    """The `source: "juli"` opening context message
    `prompts/optimize_product/v1.md` Sec.4 documents -- see module
    docstring's "The opening context message" section for why this test
    seeds it directly rather than relying on production wiring that does
    not exist yet."""
    return {
        "source": "juli",
        "signals": [],
        "action_card": {
            "workflow_key": playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
            "rationale": (
                "Routine listing health check for this product -- read its current "
                "listing, SEO signal data, and status, then summarize what you find."
            ),
            "expected_impact": {"metric": "ctr", "confidence": "low"},
        },
        "product_binding": {"note": "confirms product binding; no raw vendor identifier"},
    }


@requires_postgres
@requires_openai_key
@requires_tiktok_app_credentials
@pytest.mark.timeout(180)
async def test_live_readonly_run_reaches_final_response():
    """Drive a real GPT-5.4 nano run, read-only tools only, through the
    real `WorkflowRunner`, to `stop_reason=final_response` -- issue #1124
    smoke (a). See module docstring for full prerequisites and known risks.
    """
    async_engine = create_async_engine(get_async_database_url())
    async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

    try:
        async with async_session_factory() as session:
            try:
                credential = await resolve_production_read_credential(session)
            except NotFound:
                pytest.skip(
                    "No PRODUCTION_READ TikTok credential row provisioned for "
                    "PRODUCTION_AUTH_ID (Fujiwa) in this DATABASE_URL -- run the Fujiwa "
                    "OAuth connect flow against this database before this smoke can run."
                )

            product = await _find_product_for_shop(session, credential.shop_id)
            if product is None:
                pytest.skip(
                    f"No products row exists for shop_id={credential.shop_id} (the shop "
                    "holding the PRODUCTION_READ credential) -- run Fujiwa polling sync "
                    "at least once against this DATABASE_URL so a real product is "
                    "available to read."
                )

            playbook = _read_only_playbook()
            registry = composition_module.build_product_tool_registry()
            llm_service = composition_module.build_llm_service()
            read_resources = await composition_module.build_read_resources(session)
            assert isinstance(read_resources, ProductionReadResources)

            workflow_key = playbook.workflow_key
            version = prompts_module.production_version(workflow_key)
            prompt_version_value = prompts_module.prompt_version(workflow_key, version)
            prompt_sha256_value = prompts_module.prompt_sha256(workflow_key, version)

            run = WorkflowRunRow(
                id=uuid.uuid4(),
                shop_id=credential.shop_id,
                product_id=product.id,
                state={
                    "conversation_window": [
                        {"role": "user", "content": json.dumps(_opening_context_message())}
                    ]
                },
                status="running",
                prompt_version=prompt_version_value,
                prompt_sha256=prompt_sha256_value,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            tool_executor = ProductToolExecutor(
                registry=registry,
                read_resources=read_resources,
                write_resources=None,
                product_id=product.tiktok_product_id,
            )
            # Acceptance criterion: "Smoke (a) never constructs or uses
            # SandboxWriteResources ... assert this by inspecting the
            # resources object type the run's ToolExecutor was given."
            assert tool_executor._write_resources is None
            assert isinstance(tool_executor._read_resources, ProductionReadResources)

            event_sink = PersistingEventSink(async_session_factory, _NullPublisher())
            conversation_store = JsonbConversationStore(session)

            runner = WorkflowRunner(
                llm_service=llm_service,
                tool_executor=tool_executor,
                event_sink=event_sink,
                conversation_store=conversation_store,
                registry=registry,
                playbook=playbook,
            )

            # `WorkflowRunner.run()` never writes `workflow_runs.status`/
            # `.stop_reason` back itself (`core.py`'s own docstring: "no
            # direct database access here"; no other slice does it for the
            # real Celery task path either -- `_run_agent_workflow_async`
            # discards the returned `RunResult`). This test writes them back
            # itself, in a `finally`, so a failed/erroring run still leaves
            # this row in a TERMINAL status rather than "running" forever --
            # `uq_workflow_runs_active_shop_product`'s partial unique index
            # would otherwise permanently block a second local run against
            # the same (shop_id, product_id) after the first one errors.
            try:
                result = await runner.run(run.id, product_ref=product.tiktok_product_id)
            except BaseException:
                run.status = WorkflowRunStatus.FAILED.value
                run.stop_reason = StopReason.LLM_ERROR.value
                await session.commit()
                raise
            run.status = result.status.value
            run.stop_reason = result.stop_reason.value
            await session.commit()

            assert result.stop_reason == StopReason.FINAL_RESPONSE, (
                f"expected final_response, got stop_reason={result.stop_reason!r} -- "
                "if this is llm_error on the second turn, see this module's docstring's "
                "known-risk note about openai_adapter.py's tool call_id translation"
            )
            assert result.status == WorkflowRunStatus.COMPLETED
            assert result.final_response, "final_response must carry non-empty content"
            assert result.prompt_version == prompt_version_value
            assert result.prompt_sha256 == prompt_sha256_value

            events_result = await session.execute(
                select(WorkflowRunEventRow)
                .where(WorkflowRunEventRow.workflow_run_id == run.id)
                .order_by(WorkflowRunEventRow.sequence_number)
            )
            events = events_result.scalars().all()
            assert events, (
                "a completed run must have persisted at least one workflow_run_events row"
            )
            sequence_numbers = [event.sequence_number for event in events]
            assert sequence_numbers == list(range(1, len(events) + 1)), (
                f"workflow_run_events sequence numbers must be continuous with no gaps, got "
                f"{sequence_numbers!r}"
            )
            assert events[-1].event_type == "workflow.completed"
    finally:
        await async_engine.dispose()

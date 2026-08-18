"""Live smoke (b) -- the full write-path Optimize Product run: CONFIRM
pause, resume, ledger, compare-before-write, sandbox-only write (issue
#1124, W3-A/P1-8, ADR-073 decisions 3+4; HITL).

This is the write-path half of the phase gate PLAN.md Sec.6 names: "(b)
full write-path run (CONFIRM, ledger, compare-before-write) against the
sandbox shop". It drives a REAL `WorkflowRunner` through a REAL GPT-5.4
nano completion to a `waiting_approval` pause, resumes it with the
already-authorized decision (mirroring #1123's pause/resume seam), and lets
the approved WRITE dispatch through the REAL `ToolExecutionLedger`
(#1121, `runner/ledger.py`) and the REAL `ConcurrencyGuard`
(#1122, `runner/concurrency.py`) against the REAL TikTok **sandbox** shop
only (`SandboxWriteResources`, `SANDBOX_AUTH_ID`) -- never production.

**No live API calls, and no sandbox write, happen unless every skip
condition below clears.** This slice's own authoring phase has neither
`OPENAI_API_KEY` nor a provisioned sandbox-write credential row -- see the
executor's report for the exact skip reasons observed with
`DATABASE_URL=postgresql://macos@localhost:5432/postgres` and no
`OPENAI_API_KEY` set.

## What the live run needs present, honestly

1. `OPENAI_API_KEY` -- same as smoke (a). Skips (collection time) when absent.
2. `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` -- needed by `composition.py::
   build_write_resources` (`_tiktok_app_credentials`, `require_env`).
   Skips (collection time) when either is absent.
3. A `tiktok_credentials` row for `SANDBOX_AUTH_ID`
   (`integrations/tiktok/capabilities.py`) with capability `SANDBOX_WRITE`,
   in **this** `DATABASE_URL` -- resolved via `resolve_sandbox_write_
   credential`, the exact function `composition.py::build_write_resources`
   calls. Skips at runtime via `pytest.skip()` when `NotFound`. Provisioning
   this row is the one-time Partner Center sandbox OAuth exchange --
   `tests/integration/test_tiktok_sandbox_oauth.py` /
   `tests/integration/tiktok_sandbox.py`'s `requires_sandbox_auth_code`/
   `requires_sandbox_refresh_token` helpers document the exact
   `TIKTOK_SANDBOX_AUTH_CODE`/`TIKTOK_SANDBOX_REFRESH_TOKEN` variables CI
   uses to seed it.
4. **At least one `products` row under the `shops` row that credential
   belongs to (`credential.shop_id`), with a `tiktok_product_id` that
   actually exists on the SANDBOX shop and carries at least one SKU.** This
   is the one precondition nothing else in this codebase auto-populates:
   unlike Fujiwa production (kept warm by polling sync), the sandbox shop
   has no automatic product sync -- an operator must seed this row by hand
   (or via a one-off script) with a real sandbox product id before this
   smoke can run. Skips at runtime when no such row exists, or when the
   product it finds carries no SKUs to price.

No hardcoded shop, product, or SKU id anywhere in this module. The SKU this
test prices is resolved live, by calling `write_resources.products.
get_details(product_id)` once during setup (a real vendor read against the
sandbox shop's own write-capable credential -- not the production-read
credential; see "Why this test never builds `read_resources`" below) and
taking its first SKU.

## Why this test never builds `read_resources` (`ProductionReadResources`)

`ProductionReadClientFactory.create()` (`integrations/tiktok/factories.py`)
hard-asserts `config.merchant_auth_id == PRODUCTION_AUTH_ID` -- it is
structurally impossible to build a `ProductionReadResources` pointed at the
sandbox merchant. Reading from Fujiwa production while writing to a
same-named product id in the sandbox shop would also be semantically wrong
(different catalogs, different SKU ids) -- and the issue's own explicit
warning is that smoke (b) must never touch the production credential at
all. So this test constructs its `ProductToolExecutor` with `read_resources
=None` and restricts the `Playbook` it hands `WorkflowRunner` to exactly one
CONFIRM-policy step (`update_product_price`) -- the model is never offered
a READ tool schema to begin with, so it cannot attempt one. The current
price/SKU-id ground truth it needs instead comes from this test's own
direct `write_resources.products.get_details(...)` call during setup (an
ordinary vendor read the sandbox write credential is fully capable of --
"write" names the guarded capability class, not a restriction against
reading), fed into the opening context message and the compare-before-write
basis snapshot. This also makes the acceptance criterion --
"smoke (b) only ever constructs resources via SandboxWriteClientFactory /
SANDBOX_AUTH_ID" -- true by construction: `composition.build_read_resources`
(which resolves the production credential) is never called anywhere in this
module.

## A known, pre-existing risk this smoke may surface (not this slice's to fix)

Same as smoke (a)'s docstring: `openai_adapter.py::_translate_message`
reads a tool message's `call_id` key, but `runner/core.py` appends it keyed
`tool_call_id`. `WorkflowRunner.resume`'s post-dispatch continuation
(`_drive_loop` again, after the approved write) makes exactly this second
LLM round-trip. If it raises `LLMProviderError` rather than reaching a
final text response after the write, that is this pre-existing
`services/agent/llm/` gap surfacing (out of this slice's write path),
**not** a defect in this test or in the ledger/compare-before-write path --
this test's own ledger/compare-before-write assertions run against the
already-persisted `ToolExecution` row regardless of whether the run's
*second* LLM turn afterward succeeds.

## The opening context message + compare-before-write basis

Same rationale as smoke (a)'s docstring for why this test seeds the
`source: "juli"` opening context message directly (nothing in this
codebase wires it yet). This test's context message additionally states
the current price and a concrete recommended new price for the resolved
SKU (using the opaque `sku_ref` token `"S1"`, never the raw vendor SKU id --
ADR-070 decision 1), so the model has what it needs to propose the exact
CONFIRM call this test expects. The compare-before-write basis snapshot
(`ConcurrencyGuard(basis_snapshot=...)`) is seeded from the same
`get_details` read used to resolve the SKU -- mirroring how a real run's
prior `get_product_information` READ call would have called
`ConcurrencyGuard.record_basis` (`tool_executor.py`), which this run's
restricted, READ-tool-free playbook never offers the model the chance to
do itself.

## The event-log fixture

Per the issue's acceptance criteria (implementation handoff Sec.8, "W3
close": this run's event log is P-UI's first golden scenario), a
successful run of this test writes the persisted `workflow_run_events` for
this run, sanitized (rebased relative timestamps, no raw vendor id, no
basis hash, no credential), to
`tests/fixtures/agent_live_write_smoke_event_log.json` and asserts it
exists, is non-empty, and contains none of the sensitive values checked for
below.
"""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.core.security import resolve_sandbox_write_credential
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import SandboxWriteResources
from juli_backend.models.models import Product
from juli_backend.models.models import ToolExecution as ToolExecutionRow
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent import prompts as prompts_module
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.runner import (
    ConcurrencyGuard,
    JsonbConversationStore,
    ProductToolExecutor,
    StopReason,
    ToolExecutionLedger,
    WorkflowRunner,
    WorkflowRunStatus,
    capture_basis_snapshot,
    extract_mutable_fields,
)
from juli_backend.services.agent.tools import ToolPolicy
from juli_backend.workers.tasks.database import get_async_database_url, get_sync_database_url

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def token_encryption_key():
    """Shadow `tests/integration/conftest.py`'s autouse fixture of the same name.

    Same reason as the read-only smoke's copy: that fixture pins
    `TIKTOK_TOKEN_ENCRYPTION_KEY` to a dummy value, which makes decrypting the
    REAL sandbox-write credential row impossible -- `decrypt_token` raises
    `cryptography.fernet.InvalidToken` inside `resolve_sandbox_write_credential`
    before the first vendor call. Module-level override applies here only.
    """
    yield


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "agent_live_write_smoke_event_log.json"
)

# ---------------------------------------------------------------------------
# Skip conditions -- same shape as test_agent_live_smoke_read_only.py.
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
    reason="OPENAI_API_KEY absent -- live GPT-5.4 nano write-path smoke skipped (ADR-040 live).",
)

requires_tiktok_app_credentials = pytest.mark.skipif(
    not (
        os.environ.get("TIKTOK_APP_KEY", "").strip()
        and os.environ.get("TIKTOK_APP_SECRET", "").strip()
    ),
    reason=(
        "TIKTOK_APP_KEY/TIKTOK_APP_SECRET absent -- services/agent/composition.py::"
        "build_write_resources cannot resolve the sandbox-write credential without the "
        "shared TikTok Partner app secret (require_env, same pattern as webhook_tiktok.py)."
    ),
)


def _write_only_playbook():
    """A `Playbook` offering exactly one CONFIRM-policy WRITE step
    (`update_product_price`). See module docstring's "Why this test never
    builds read_resources" for why READ steps are excluded entirely, not
    merely deprioritized.
    """
    canonical = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK
    price_step = next(step for step in canonical.steps if step.tools == ("update_product_price",))
    assert price_step.policy is ToolPolicy.CONFIRM
    termination_policy = dataclasses.replace(
        canonical.termination_policy, required_steps=("update_product_price",)
    )
    return playbooks_module.Playbook(
        workflow_key=canonical.workflow_key,
        version=canonical.version,
        steps=(price_step,),
        termination_policy=termination_policy,
    )


async def _find_product_for_shop(session, shop_id) -> Product | None:
    result = await session.execute(
        select(Product).where(Product.shop_id == shop_id).order_by(Product.created_at).limit(1)
    )
    return result.scalar_one_or_none()


class _NullPublisher:
    async def publish(self, channel: str, message: str) -> None:
        return None


def _bump_amount(amount: str) -> str:
    """A small, deterministic price bump for the smoke's proposed change --
    never the same value as the current one, so the write is a genuine
    mutation. Falls back to the unchanged amount (still a valid, if inert,
    write) if the vendor's amount string is not decimal-parseable -- this
    test must never fabricate a plausible-looking number."""
    try:
        return str(Decimal(amount) + Decimal("1000"))
    except (InvalidOperation, TypeError):
        return amount


def _opening_context_message(
    *, sku_ref: str, current_amount: str, new_amount: str, currency: str
) -> dict:
    return {
        "source": "juli",
        "signals": [],
        "action_card": {
            "workflow_key": playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
            "rationale": (
                f"Signal review recommends adjusting SKU {sku_ref}'s price from "
                f"{current_amount} {currency} to {new_amount} {currency} to better match "
                "category peers on the sandbox shop."
            ),
            "expected_impact": {"metric": "gmv", "confidence": "medium"},
        },
        "product_binding": {
            "note": "confirms product binding; no raw vendor identifier",
            "proposed_price": {"sku_ref": sku_ref, "amount": new_amount, "currency": currency},
        },
    }


def _write_fixture(
    events: list[WorkflowRunEventRow], *, workflow_key: str, vendor_sku_id: str
) -> None:
    """Sanitize and write the golden event-log fixture -- redacted
    timestamps (relative offsets only), no raw vendor id/credential/basis
    hash. See module docstring's "The event-log fixture" section."""
    base_ts = events[0].timestamp
    sanitized = {
        "workflowKey": workflow_key,
        "note": (
            "Golden scenario for P-UI (implementation handoff Sec.8, 'W3 close') -- "
            "captured by tests/integration/test_agent_live_smoke_sandbox_write.py. "
            "Timestamps are relative offsets from the first event, not wall-clock times."
        ),
        "events": [
            {
                "sequenceNumber": event.sequence_number,
                "eventType": event.event_type,
                "tOffsetSeconds": round((event.timestamp - base_ts).total_seconds(), 3),
                "payload": event.payload,
            }
            for event in events
        ],
    }
    _FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(sanitized, indent=2, ensure_ascii=False, sort_keys=True)
    assert vendor_sku_id not in serialized, "fixture must never carry a raw vendor SKU id"
    assert "access_token" not in serialized, "fixture must never carry a credential"
    _FIXTURE_PATH.write_text(serialized + "\n", encoding="utf-8")


@requires_postgres
@requires_openai_key
@requires_tiktok_app_credentials
@pytest.mark.timeout(240)
async def test_live_write_path_pauses_resumes_and_executes_exactly_once():
    """Drive a real GPT-5.4 nano run to a CONFIRM pause, resume it, and
    prove the approved WRITE went through the ledger + compare-before-write
    against the sandbox shop exactly once -- issue #1124 smoke (b). See
    module docstring for full prerequisites and known risks.
    """
    async_engine = create_async_engine(get_async_database_url())
    async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    sync_engine = create_engine(get_sync_database_url())
    SyncSession = sessionmaker(bind=sync_engine)

    try:
        async with async_session_factory() as session:
            try:
                credential = await resolve_sandbox_write_credential(session)
            except NotFound:
                pytest.skip(
                    "No SANDBOX_WRITE TikTok credential row provisioned for "
                    "SANDBOX_AUTH_ID in this DATABASE_URL -- provision it via the sandbox "
                    "OAuth exchange documented in tests/integration/test_tiktok_sandbox_"
                    "oauth.py / tiktok_sandbox.py before this smoke can run."
                )

            product = await _find_product_for_shop(session, credential.shop_id)
            if product is None:
                pytest.skip(
                    f"No products row exists for shop_id={credential.shop_id} (the shop "
                    "holding the SANDBOX_WRITE credential) -- seed one with a real TikTok "
                    "product id that exists on the sandbox shop; nothing in this codebase "
                    "auto-populates sandbox product rows today (see module docstring)."
                )

            write_resources = await composition_module.build_write_resources(session)
            assert isinstance(write_resources, SandboxWriteResources)

            raw = write_resources.products.get_details(product.tiktok_product_id)
            skus = raw.get("skus") or []
            if not skus:
                pytest.skip(
                    f"products row for tiktok_product_id={product.tiktok_product_id!r} "
                    "carries no SKUs on the sandbox shop -- this smoke needs at least one "
                    "priceable SKU to propose a price change for."
                )
            sku = skus[0]
            vendor_sku_id = str(sku.get("id"))
            price = sku.get("price") or {}
            current_amount = str(price.get("tax_exclusive_price"))
            currency = str(price.get("currency") or "VND")
            new_amount = _bump_amount(current_amount)

            sku_ref = "S1"
            sku_refs = {sku_ref: vendor_sku_id}
            basis_snapshot = capture_basis_snapshot(extract_mutable_fields(raw))

            playbook = _write_only_playbook()
            registry = composition_module.build_product_tool_registry()
            llm_service = composition_module.build_llm_service()

            workflow_key = playbook.workflow_key
            version = prompts_module.production_version(workflow_key)
            prompt_version_value = prompts_module.prompt_version(workflow_key, version)
            prompt_sha256_value = prompts_module.prompt_sha256(workflow_key, version)

            opening_message = _opening_context_message(
                sku_ref=sku_ref,
                current_amount=current_amount,
                new_amount=new_amount,
                currency=currency,
            )

            run = WorkflowRunRow(
                id=uuid.uuid4(),
                shop_id=credential.shop_id,
                product_id=product.id,
                state={
                    "conversation_window": [
                        {"role": "user", "content": json.dumps(opening_message)}
                    ],
                    "basis_snapshots": basis_snapshot,
                },
                status="running",
                prompt_version=prompt_version_value,
                prompt_sha256=prompt_sha256_value,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            event_sink = PersistingEventSink(async_session_factory, _NullPublisher())

            # --- leg 1: run to the CONFIRM pause ------------------------------
            sync_session_1 = SyncSession()
            try:
                ledger_1 = ToolExecutionLedger(sync_session_1, shop_id=run.shop_id)
                concurrency_guard_1 = ConcurrencyGuard(basis_snapshot=basis_snapshot)
                tool_executor_1 = ProductToolExecutor(
                    registry=registry,
                    read_resources=None,
                    write_resources=write_resources,
                    product_id=product.tiktok_product_id,
                    sku_refs=sku_refs,
                    ledger=ledger_1,
                    workflow_run_id=run.id,
                    concurrency_guard=concurrency_guard_1,
                )
                assert tool_executor_1._read_resources is None
                assert isinstance(tool_executor_1._write_resources, SandboxWriteResources)

                runner_1 = WorkflowRunner(
                    llm_service=llm_service,
                    tool_executor=tool_executor_1,
                    event_sink=event_sink,
                    conversation_store=JsonbConversationStore(session),
                    registry=registry,
                    playbook=playbook,
                )
                # See test_agent_live_smoke_read_only.py's identical
                # comment: WorkflowRunner never writes status/stop_reason
                # back itself, and this row's partial unique index
                # (uq_workflow_runs_active_shop_product) would otherwise
                # permanently block a second local run for this
                # (shop_id, product_id) after any failure here.
                try:
                    result_1 = await runner_1.run(run.id, product_ref=product.tiktok_product_id)
                except BaseException:
                    run.status = WorkflowRunStatus.FAILED.value
                    run.stop_reason = StopReason.LLM_ERROR.value
                    await session.commit()
                    raise
                run.status = result_1.status.value
                run.stop_reason = result_1.stop_reason.value
                await session.commit()
            finally:
                sync_session_1.close()

            assert result_1.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION, (
                f"expected a CONFIRM pause, got stop_reason={result_1.stop_reason!r} -- the "
                "live model did not propose update_product_price this run"
            )
            assert result_1.status == WorkflowRunStatus.WAITING_APPROVAL

            await session.refresh(run)
            pending = run.state.get("pending_confirmation")
            assert pending is not None, (
                "a paused_for_confirmation run must persist pending_confirmation"
            )
            call_id = pending["call_id"]
            assert pending["tool_name"] == "update_product_price"

            # --- leg 2: resume, approved -- a fresh runner/ledger/guard, ------
            # mirroring a second worker process picking the run back up
            # (P1-7's cross-process resume pattern).
            sync_session_2 = SyncSession()
            try:
                ledger_2 = ToolExecutionLedger(sync_session_2, shop_id=run.shop_id)
                concurrency_guard_2 = ConcurrencyGuard(
                    basis_snapshot=run.state.get("basis_snapshots", {})
                )
                spy_calls: list[str] = []
                real_check = concurrency_guard_2.check_before_write

                def _spied_check_before_write(*args, **kwargs):
                    spy_calls.append(kwargs.get("operation", args[0] if args else ""))
                    return real_check(*args, **kwargs)

                concurrency_guard_2.check_before_write = _spied_check_before_write  # type: ignore[method-assign]

                tool_executor_2 = ProductToolExecutor(
                    registry=registry,
                    read_resources=None,
                    write_resources=write_resources,
                    product_id=product.tiktok_product_id,
                    sku_refs=sku_refs,
                    ledger=ledger_2,
                    workflow_run_id=run.id,
                    concurrency_guard=concurrency_guard_2,
                )

                runner_2 = WorkflowRunner(
                    llm_service=llm_service,
                    tool_executor=tool_executor_2,
                    event_sink=event_sink,
                    conversation_store=JsonbConversationStore(session),
                    registry=registry,
                    playbook=playbook,
                )
                # Written back regardless of outcome -- see leg 1's identical
                # comment. This is what actually protects the ledger/
                # compare-before-write assertions below from the known
                # openai_adapter.py risk documented in the module docstring:
                # even if resume()'s post-write LLM turn raises, the WRITE
                # itself (and its ledger row) already landed before that
                # second turn was ever attempted -- this test's own
                # assertions run against that already-committed ledger row,
                # not against result_2's own stop_reason.
                try:
                    result_2 = await runner_2.resume(run.id, approved=True)
                except BaseException:
                    run.status = WorkflowRunStatus.FAILED.value
                    run.stop_reason = StopReason.LLM_ERROR.value
                    await session.commit()
                    raise
                run.status = result_2.status.value
                run.stop_reason = result_2.stop_reason.value
                await session.commit()
            finally:
                sync_session_2.close()

            # Acceptance criterion: "compare-before-write basis check runs
            # before signing" -- proven by a spy on the real
            # ConcurrencyGuard.check_before_write, not inference.
            assert spy_calls == ["update_product_price"], (
                f"expected exactly one compare-before-write check for update_product_price, "
                f"got {spy_calls!r}"
            )
            # result_2's own stop_reason depends on whether the model's
            # post-write turn reaches final_response -- see module
            # docstring's known-risk note. The ledger/compare-before-write
            # assertions below hold regardless of how leg 2 itself ends.
            assert result_2.stop_reason != StopReason.CONFIRMATION_DECLINED, (
                "the approved=True resume must not have been treated as declined"
            )

            # Acceptance criterion: "executes exactly once through the
            # ToolExecution ledger (claim-then-execute row asserted)".
            ledger_rows_result = await session.execute(
                select(ToolExecutionRow).where(
                    ToolExecutionRow.workflow_run_id == run.id,
                    ToolExecutionRow.tool_call_id == call_id,
                    ToolExecutionRow.operation == "update_product_price",
                )
            )
            ledger_rows = ledger_rows_result.scalars().all()
            assert len(ledger_rows) == 1, (
                f"expected exactly one ToolExecution ledger row for tool_call_id={call_id!r}, "
                f"got {len(ledger_rows)}"
            )
            ledger_row = ledger_rows[0]
            assert ledger_row.status == "succeeded"
            assert ledger_row.outcome_json

            # Acceptance criterion: "a simulated redelivery of the same
            # tool_call_id returns the stored sanitized result with zero
            # additional vendor calls."
            def _perform_must_not_be_called():
                raise AssertionError(
                    "perform() must not be called on ledger replay -- zero additional "
                    "vendor calls expected for a succeeded row"
                )

            sync_session_3 = SyncSession()
            try:
                replay_ledger = ToolExecutionLedger(sync_session_3, shop_id=run.shop_id)
                replayed = replay_ledger.execute_write(
                    workflow_run_id=run.id,
                    tool_call_id=call_id,
                    operation="update_product_price",
                    perform=_perform_must_not_be_called,
                )
            finally:
                sync_session_3.close()
            assert replayed == json.loads(ledger_row.outcome_json), (
                "a redelivered tool_call_id must replay the exact stored sanitized result"
            )

            # --- golden event-log fixture (issue #1124 acceptance criterion) ---
            events_result = await session.execute(
                select(WorkflowRunEventRow)
                .where(WorkflowRunEventRow.workflow_run_id == run.id)
                .order_by(WorkflowRunEventRow.sequence_number)
            )
            events = events_result.scalars().all()
            assert events, "a paused-then-resumed run must have persisted events"
            _write_fixture(events, workflow_key=workflow_key, vendor_sku_id=vendor_sku_id)
            assert _FIXTURE_PATH.exists()
            assert _FIXTURE_PATH.stat().st_size > 0
    finally:
        await async_engine.dispose()
        sync_engine.dispose()

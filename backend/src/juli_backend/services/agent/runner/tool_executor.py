"""`ToolExecutor` — the dispatch seam `WorkflowRunner` calls after validating a
`ToolCallBlock`'s params against the target `ToolSpec.input_model` (ADR-073
decision 1, issue #1119 / AGT-W3A).

`WorkflowRunner` (`core.py`) owns allowlist enforcement (registry + active
`Playbook`) and `input_model` validation *before* ever reaching this seam —
by the time `ToolExecutor.execute` is called, the tool name is known-good and
`params` is an already-validated `input_model` instance. This module's whole
job is narrower: resolve the target handler and its marketplace resources,
build a `ProductToolContext` (`tools/product.py`) from **server-held run
state bound at construction time** — never from `params`, and never from
anything the LLM supplied — call the handler, and hand back a plain
JSON-safe mapping. `WorkflowRunner` is what runs that mapping through
`guard_inbound_tool_result` (`sanitize/chokepoints.py`) before it reaches the
conversation; this seam does not call the guard itself, exactly as
`product.py`'s module docstring describes the boundary.

**Why the bound context is constructor state, not `RunState`.** `RunState`
(`state.py`, #1118) does not carry `product_id`/`sku_refs`/
`staged_image_uri`/`pending_image_bytes` — those fields live on
`ProductToolContext` itself, and `state.py` is explicitly not writable by
this slice. `ProductToolExecutor` is built once per run with the run's bound
product identity already resolved (by whatever constructs the runner for a
given `workflow_runs` row — a later slice's job), so every `execute` call
this run makes reflects that identity, never a value an agent could spoof
through `ToolCallBlock.arguments`.

**Idempotency-ledger routing (ADR-073 decision 3, issue #1121 / AGT-W3A).**
`ProductToolExecutor` optionally takes a `ledger` (`ledger.py`'s
`ToolExecutionLedger`) and the run's `workflow_run_id`. When both are
supplied *and* a caller passes `tool_call_id` to `execute` *and* the target
tool is `WRITE`-classified, dispatch routes through
`ToolExecutionLedger.execute_write` instead of calling the handler
directly — `READ` calls never take this branch regardless of whether a
ledger is configured, which is the whole of how "reads skip the ledger
entirely" holds. `ledger`/`workflow_run_id` default to `None` and
`tool_call_id` defaults to `None` so every pre-existing call site
(`core.py`'s `self._tool_executor.execute(tool_name=..., params=...)`,
and every test in `test_agent_runner_tool_executor.py` predating this
slice) keeps calling the handler directly, byte-for-byte as before —
this is an additive, opt-in extension, not a signature break.

`verify_applied` is passed as `None` from this wiring: a real per-operation
read-back check (re-read the product/price and compare against the
intended mutation) needs marketplace read access this module already has
in principle, but authoring that comparison logic per tool is `tools/`
domain logic this issue's boundary explicitly reserves for a later slice
(`#1122`, basis-hash compare-before-write, builds the same read-and-compare
machinery). Until that lands, any `in_flight`/`failed` row this
`ProductToolExecutor` encounters on a real retry fails closed
(`ToolExecutionUnrecoverableError`) rather than guessing — the safe default
`ledger.py` already implements for `verify_applied=None`, not a gap this
module papers over.

**Basis-hash concurrency routing (ADR-073 decision 4, issue #1122 /
AGT-W3A).** `ProductToolExecutor` optionally takes a `concurrency_guard`
(`concurrency.py`'s `ConcurrencyGuard`). When supplied and the target tool
is one `FIELD_SCOPE_BY_OPERATION` names, `execute` re-reads the product via
`write_resources.products.get_details` and runs
`ConcurrencyGuard.check_before_write` **before** the ledger-gated/direct
dispatch below ever runs — a `ConcurrencyConflict` short-circuits `execute`
entirely, returning the sanitized `{"conflict": True, "current_values":
...}` payload directly, so neither the handler nor the ledger nor any
vendor write call is ever reached (zero vendor calls on a mismatch,
ADR-073 decision 4: "rejected before signing"). A `ConcurrencyMatch` falls
through to dispatch unchanged; a second same-operation mismatch raises
`ConcurrencyExhaustedError` straight out of `execute` — this module never
catches it itself, mirroring `ToolExecutionUnrecoverableError`'s
propagation. Both are caught by the caller: `WorkflowRunner` (`core.py`,
issue #1172) wraps both of its `ToolExecutor.execute` call sites
(`_dispatch_tool_call` and `resume`) and translates whichever of the two
propagates into a graceful terminal run — `stop_reason=concurrency_conflict`
/ `tool_error_unrecoverable` respectively, via the same `workflow.failed`
machinery every other terminal reason uses. `get_product_information`
READ dispatch additionally re-reads the product once more to call
`ConcurrencyGuard.record_basis` — the "captured when the agent reads the
product" half of decision 4 — and a successful WRITE dispatch refreshes the
basis again afterward (`concurrency.py`'s module docstring, "Post-write
basis refresh", explains why). `concurrency_guard` defaults to `None`, so
every pre-existing call site and test keeps behaving byte-for-byte as
before — additive and opt-in, exactly like the ledger routing above.

**Reachability (issue #1145).** `core.py` now threads `block.call_id` /
the pending call's `call_id` into every `execute` call as `tool_call_id`
(both `_dispatch_tool_call` and `resume`), so a WRITE call dispatched
through a `ProductToolExecutor` constructed with `ledger` +
`workflow_run_id` genuinely reaches `ToolExecutionLedger.execute_write`,
and one constructed with `concurrency_guard` genuinely reaches
`ConcurrencyGuard.check_before_write` — both were structurally
unreachable before this. `core.py` still never constructs either
collaborator itself; that construction is the Celery task shell's job
(`workers/tasks/agent_workflow.py`'s `_construct_runner`), which #1145
also wires up. Whether that task shell can reach *real* marketplace
credentials to populate `read_resources`/`write_resources` is a separate,
still-open question — see that module's own docstring.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from juli_backend.integrations.tiktok import ProductionReadResources, SandboxWriteResources
from juli_backend.services.agent.runner.concurrency import (
    FIELD_SCOPE_BY_OPERATION,
    ConcurrencyConflict,
    ConcurrencyGuard,
    extract_mutable_fields,
)
from juli_backend.services.agent.runner.ledger import (
    ToolExecutionLedger,
    ToolExecutionRequestPayload,
)
from juli_backend.services.agent.tools import ToolClassification, ToolRegistry
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
)
from juli_backend.services.agent.tools.product_write import (
    PRODUCT_WRITE_TOOL_HANDLERS,
    UpdateProductListingInput,
    UpdateProductPriceInput,
)


class ToolExecutionError(RuntimeError):
    """Raised when a tool name resolves against the registry but has no
    registered handler in either `PRODUCT_READ_TOOL_HANDLERS` or
    `PRODUCT_WRITE_TOOL_HANDLERS`.

    A wiring defect (a `ToolSpec` registered without a matching handler
    entry), never a normal runtime outcome — the playbook allowlist and
    registry lookup `WorkflowRunner` performs before calling `execute` are
    what keep an ordinary bad tool name from ever reaching this far.
    """


@runtime_checkable
class ToolExecutor(Protocol):
    """One `execute`-shaped seam, structurally typed (the `LLMService`/
    `EventSink` pattern) so `WorkflowRunner` and any concrete implementation
    (this module's `ProductToolExecutor`, or a test spy) each satisfy it
    independently, with no shared base class.

    `params` arrives already validated against the target `ToolSpec`'s
    `input_model` — `execute` never re-validates raw LLM arguments. The
    return value is a plain JSON-safe mapping (the handler's declared
    `output_model` instance, dumped) — not yet run through
    `guard_inbound_tool_result`; that is the caller's job.
    """

    def execute(
        self, *, tool_name: str, params: BaseModel, tool_call_id: str | None = None
    ) -> Mapping[str, Any]: ...


class ProductToolExecutor:
    """The `ToolExecutor` this slice ships: Optimize Product's six product
    READ/WRITE capabilities (`tools/product.py`, `tools/product_write.py`),
    constructor-bound to one run's product identity.

    `read_resources`/`write_resources` are already-built, already-guarded
    marketplace resource bundles (`ProductionReadResources`/
    `SandboxWriteResources` — `integrations/tiktok/factories.py`); building
    those from real shop credentials is not this seam's job. Either may be
    left `None` when a run only ever needs the other side (e.g. a read-only
    scripted scenario never needs `write_resources`) — `execute` raises
    plainly if a call needs the missing side.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        read_resources: ProductionReadResources | None = None,
        write_resources: SandboxWriteResources | None = None,
        product_id: str,
        sku_refs: Mapping[str, str] | None = None,
        staged_image_uri: str | None = None,
        pending_image_bytes: bytes | None = None,
        image_inspector: Any | None = None,
        ledger: ToolExecutionLedger | None = None,
        workflow_run_id: uuid.UUID | None = None,
        concurrency_guard: ConcurrencyGuard | None = None,
    ) -> None:
        self._registry = registry
        self._read_resources = read_resources
        self._write_resources = write_resources
        self._product_id = product_id
        self._sku_refs = dict(sku_refs or {})
        self._staged_image_uri = staged_image_uri
        self._pending_image_bytes = pending_image_bytes
        # #1208: the vision collaborator `inspect_product_image` uses. Optional
        # so every existing construction site keeps working; the handler reports
        # `inspected=False` when absent rather than failing the run.
        self._image_inspector = image_inspector
        self._ledger = ledger
        self._workflow_run_id = workflow_run_id
        self._concurrency_guard = concurrency_guard

    def _build_request_payload(
        self, *, tool_name: str, params: BaseModel
    ) -> ToolExecutionRequestPayload | None:
        """Build the `ToolExecutionRequestPayload` `ToolExecutionLedger`
        persists as `payload_json` (issue #1215 / AGT-W4B) — in the shape
        `workers.impact_reader.classify.classify_mutation_kinds` and
        `workers.impact_reader.pipeline`/`queries.extract_payload` actually
        read (see `ledger.ToolExecutionRequestPayload`'s docstring), not the
        `ToolSpec.input_model` shape verbatim: `UpdateProductPriceInput`
        carries no `price_update` field (it has `skus`), and neither input
        model carries `product_id` at all (ADR-070 decision 1 keeps raw
        vendor IDs out of the LLM-facing schema) — this method is what
        bridges the two, from constructor-bound state
        (`self._product_id`/`self._staged_image_uri`), never from anything
        an agent could spoof through tool call arguments.

        Returns `None` for WRITE tools this reader does not classify (e.g.
        `upload_product_image`), leaving `payload_json` at the `ToolExecution`
        model's own default (`"{}"`) — unchanged from before this slice.
        """
        if isinstance(params, UpdateProductPriceInput):
            return ToolExecutionRequestPayload(
                product_id=self._product_id,
                price_update=[
                    {"sku_ref": sku.sku_ref, "amount": sku.amount, "currency": sku.currency}
                    for sku in params.skus
                ],
            )
        if isinstance(params, UpdateProductListingInput):
            return ToolExecutionRequestPayload(
                product_id=self._product_id,
                title=params.title,
                description=params.description,
                # The raw staged asset URI, never the LLM-facing
                # `attach_staged_image: bool` alone — this is a persisted
                # analytics record, not agent-facing output, so ADR-070
                # decision 2's "the model never sees the URI" constraint
                # (which governs tool *output*) does not apply here.
                image_uri=self._staged_image_uri if params.attach_staged_image else None,
            )
        return None

    def execute(
        self, *, tool_name: str, params: BaseModel, tool_call_id: str | None = None
    ) -> Mapping[str, Any]:
        spec = self._registry.get(tool_name)
        is_scoped_write = (
            spec.classification is ToolClassification.WRITE
            and tool_name in FIELD_SCOPE_BY_OPERATION
        )

        def _dispatch() -> Mapping[str, Any]:
            context = ProductToolContext(
                product_id=self._product_id,
                sku_refs=self._sku_refs,
                staged_image_uri=self._staged_image_uri,
                pending_image_bytes=self._pending_image_bytes,
                image_inspector=self._image_inspector,
            )

            if spec.classification is ToolClassification.READ:
                read_handler = PRODUCT_READ_TOOL_HANDLERS.get(tool_name)
                if read_handler is None:
                    raise ToolExecutionError(
                        f"Tool {tool_name!r} is registered READ but has no handler in "
                        "PRODUCT_READ_TOOL_HANDLERS."
                    )
                if self._read_resources is None:
                    raise ToolExecutionError(
                        f"Tool {tool_name!r} requires read_resources, but this "
                        "ProductToolExecutor was constructed without them."
                    )
                result = read_handler(self._read_resources, context, params)
                if tool_name == "get_product_information" and self._concurrency_guard is not None:
                    # ADR-073 decision 4: "captured when the agent reads the
                    # product" — a dedicated re-read, independent of the
                    # handler's own sanitized output (see concurrency.py's
                    # module docstring for why this module never reuses
                    # tools/product.py's sanitize-shaped result for hashing).
                    raw = self._read_resources.products.get_details(self._product_id)
                    self._concurrency_guard.record_basis(extract_mutable_fields(raw))
            else:
                write_handler = PRODUCT_WRITE_TOOL_HANDLERS.get(tool_name)
                if write_handler is None:
                    raise ToolExecutionError(
                        f"Tool {tool_name!r} is registered WRITE but has no handler in "
                        "PRODUCT_WRITE_TOOL_HANDLERS."
                    )
                if self._write_resources is None:
                    raise ToolExecutionError(
                        f"Tool {tool_name!r} requires write_resources, but this "
                        "ProductToolExecutor was constructed without them."
                    )
                result = write_handler(self._write_resources, context, params)

            return result.model_dump(mode="json")

        # ADR-073 decision 4 (#1122): a scoped WRITE with a configured
        # concurrency_guard is checked *before* the ledger-gated/direct
        # dispatch below ever runs. A conflict short-circuits execute()
        # entirely — _dispatch (and therefore the ledger and any vendor
        # write call) is never reached, which is the whole of how "rejected
        # before signing, zero vendor calls" holds. A second same-operation
        # mismatch raises ConcurrencyExhaustedError out of this method,
        # uncaught here (mirroring ToolExecutionUnrecoverableError's
        # propagation) — WorkflowRunner (core.py) is what catches it and
        # translates it into a terminal stop_reason=concurrency_conflict
        # run (issue #1172).
        if (
            is_scoped_write
            and self._concurrency_guard is not None
            and self._write_resources is not None
        ):
            raw = self._write_resources.products.get_details(self._product_id)
            check = self._concurrency_guard.check_before_write(
                operation=tool_name, current_fields=extract_mutable_fields(raw)
            )
            if isinstance(check, ConcurrencyConflict):
                return dict(check.payload)

        # ADR-073 decision 3 (#1121): WRITE calls route through the ledger
        # only when the caller opted in with all three of ledger,
        # workflow_run_id, and tool_call_id — see module docstring. READ
        # calls never take this branch, satisfying "reads skip the ledger
        # entirely" unconditionally.
        if (
            spec.classification is ToolClassification.WRITE
            and self._ledger is not None
            and self._workflow_run_id is not None
            and tool_call_id is not None
        ):
            result = self._ledger.execute_write(
                workflow_run_id=self._workflow_run_id,
                tool_call_id=tool_call_id,
                operation=tool_name,
                perform=_dispatch,
                verify_applied=None,
                request_payload=self._build_request_payload(tool_name=tool_name, params=params),
            )
        else:
            result = _dispatch()

        if (
            is_scoped_write
            and self._concurrency_guard is not None
            and self._write_resources is not None
        ):
            # Post-write basis refresh (concurrency.py's module docstring):
            # this run's own successful write must not be mistaken for a
            # competing edit on a later same-operation call.
            raw = self._write_resources.products.get_details(self._product_id)
            self._concurrency_guard.record_basis(extract_mutable_fields(raw))

        return result


__all__ = [
    "ProductToolExecutor",
    "ToolExecutionError",
    "ToolExecutor",
]

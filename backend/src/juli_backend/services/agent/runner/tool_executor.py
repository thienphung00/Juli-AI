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
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from juli_backend.integrations.tiktok import ProductionReadResources, SandboxWriteResources
from juli_backend.services.agent.tools import ToolClassification, ToolRegistry
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
)
from juli_backend.services.agent.tools.product_write import PRODUCT_WRITE_TOOL_HANDLERS


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

    def execute(self, *, tool_name: str, params: BaseModel) -> Mapping[str, Any]: ...


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
    ) -> None:
        self._registry = registry
        self._read_resources = read_resources
        self._write_resources = write_resources
        self._product_id = product_id
        self._sku_refs = dict(sku_refs or {})
        self._staged_image_uri = staged_image_uri
        self._pending_image_bytes = pending_image_bytes

    def execute(self, *, tool_name: str, params: BaseModel) -> Mapping[str, Any]:
        spec = self._registry.get(tool_name)
        context = ProductToolContext(
            product_id=self._product_id,
            sku_refs=self._sku_refs,
            staged_image_uri=self._staged_image_uri,
            pending_image_bytes=self._pending_image_bytes,
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


__all__ = [
    "ProductToolExecutor",
    "ToolExecutionError",
    "ToolExecutor",
]

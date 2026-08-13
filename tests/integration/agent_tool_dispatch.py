"""Minimal tool-call dispatch glue for W1-close integration tests (#996).

Not the production dispatcher — `WorkflowRunner` (W3-A, ADR-073) is not built yet, and
this module deliberately does not try to anticipate its shape. It exists only so the
integration tests proving I1 (LLMService) x I2 (ToolSpec/registry) x I3 (sanitized
result) compose don't each hand-roll the same four lines: look up a `ToolSpec` in a
real `ToolRegistry`, validate arguments against its `input_model`, call the matching
handler, and run the result through the inbound fail-closed banned-pattern chokepoint
(`guard_inbound_tool_result`, ADR-070 decision 6(a)) — the same boundary seam a real
dispatcher applies to every tool result before it reaches the conversation, regardless
of how much shaping the handler itself already did (see `product.py`'s module
docstring).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from juli_backend.services.agent.sanitize import guard_inbound_tool_result
from juli_backend.services.agent.tools.registry import ToolRegistry


def dispatch_and_sanitize(
    *,
    registry: ToolRegistry,
    handlers: Mapping[str, Callable[..., BaseModel]],
    tool_name: str,
    resources: Any,
    context: Any,
    arguments: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Look up ``tool_name`` in the real registry, call its real handler, sanitize.

    Raises `juli_backend.services.agent.tools.registry.UnknownToolError` if
    ``tool_name`` is not registered, and a `pydantic.ValidationError` if ``arguments``
    does not validate against the tool's declared `input_model` — both loud failures,
    never silently ignored, matching how a real dispatcher must treat an LLM proposing
    an unregistered tool or malformed arguments.
    """
    spec = registry.get(tool_name)
    params = spec.input_model.model_validate(dict(arguments or {}))
    handler = handlers[tool_name]
    output = handler(resources, context, params)
    if not isinstance(output, BaseModel):
        raise TypeError(
            f"handler for {tool_name!r} returned {type(output).__name__}, expected a "
            "pydantic BaseModel (ADR-069 decision 3's output_model contract)"
        )
    return guard_inbound_tool_result(output.model_dump(mode="json"), tool_name=tool_name)

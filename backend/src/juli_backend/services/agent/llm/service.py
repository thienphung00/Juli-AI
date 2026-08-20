"""`LLMService` — the neutral protocol callers depend on (ADR-071 decision 1).

Callers depend on this interface, never a concrete adapter. No provider wire
types may appear in the signature or return type; the OpenAI Responses
adapter (a later slice) implements this protocol privately behind its own
module boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypedDict, runtime_checkable

from juli_backend.services.agent.llm.blocks import AssistantTurn
from juli_backend.services.agent.llm.config import LLMConfig

# Opaque to this module: the durable conversation-message shape (P-CS store)
# and tool definitions (playbook tool registry) are owned by modules this
# slice does not build. `LLMService` only constrains the LLM service
# boundary itself, not the shape those upstream modules will eventually
# produce.
Message = Mapping[str, Any]


class ToolDefinition(TypedDict):
    """One model-facing tool, as the runner renders it from a `ToolSpec`.

    **Typed, unlike `Message`, because the untyped version cost a live
    defect.** This was `Mapping[str, Any]`. `runner/core.py::
    _tool_definitions` produced `input_schema`; `llm/openai_adapter.py::
    _translate_tool` read `parameters` and fell back to
    `{"type": "object", "properties": {}}` when it found nothing. Nothing
    reconciled the two, so **every tool reached the model declared as taking
    no arguments** — and the fallback made it silent. The read tools take no
    arguments, so they worked; `update_product_price` was called with `{}`
    on every live write attempt, and the model then explained, accurately,
    that it had not been given anything to send. It looked like a model
    failure for as long as nobody read the request body.

    This is the third bug of exactly this shape on this seam: issue #1177
    was `call_id` vs `tool_call_id` in `Message`, in the same adapter, with
    the same silent empty-string fallback. A `TypedDict` here makes the next
    one a type error instead of a production mystery.

    `input_schema` is the domain key on purpose — the adapter is what
    renames it to the Responses API's `parameters`, which is exactly the
    translation an adapter exists to perform.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@runtime_checkable
class LLMService(Protocol):
    """One provider call: messages + system + tools + config -> AssistantTurn."""

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
    ) -> AssistantTurn: ...

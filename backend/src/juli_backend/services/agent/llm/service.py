"""`LLMService` — the neutral protocol callers depend on (ADR-071 decision 1).

Callers depend on this interface, never a concrete adapter. No provider wire
types may appear in the signature or return type; the OpenAI Responses
adapter (a later slice) implements this protocol privately behind its own
module boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from juli_backend.services.agent.llm.blocks import AssistantTurn
from juli_backend.services.agent.llm.config import LLMConfig

# Opaque to this module: the durable conversation-message shape (P-CS store)
# and tool definitions (playbook tool registry) are owned by modules this
# slice does not build. `LLMService` only constrains the LLM service
# boundary itself, not the shape those upstream modules will eventually
# produce.
Message = Mapping[str, Any]
ToolDefinition = Mapping[str, Any]


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

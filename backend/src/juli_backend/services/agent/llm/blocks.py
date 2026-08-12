"""Juli-owned block vocabulary for LLM service turns (ADR-071 decision 1).

`AssistantTurn` carries only these dataclasses — never provider wire types.
This is the seam (the `integrations/tiktok` wrapping pattern) that keeps a
provider swap to one file: SDK/API-version migrations touch the adapter,
never P-CS storage or the P8 event protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextBlock:
    """Freeform assistant narration — reasoning or seller-facing commentary."""

    text: str


@dataclass(frozen=True)
class ToolCallBlock:
    """A proposed tool invocation for the executor to dispatch and resolve.

    Provider-agnostic: no assumption about how the underlying API represents
    tool calls on the wire (id shape, streaming assembly, etc).
    """

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalResponse:
    """Terminal block closing the turn with the agent's structured output.

    `structured_output` is intentionally untyped here — ADR-068 decision 7
    composes this into existing shipped contracts (`WorkflowReasoningCopy`,
    `proposed_actions[]`, ...) in a later slice; this module only owns the
    neutral block shape.
    """

    content: str
    structured_output: dict[str, Any] | None = None


Block = TextBlock | ToolCallBlock | FinalResponse


@dataclass(frozen=True)
class Usage:
    """Token accounting for a single provider call (ADR-071 decision 5)."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AssistantTurn:
    """One complete, non-streamed provider call (ADR-071 decision 3).

    Turn-level blocks only — no token deltas. `assistant.text.delta` is
    reserved for a future chat-like surface (ADR-071 decision 3); this
    module never emits partial blocks.
    """

    blocks: tuple[Block, ...]
    usage: Usage

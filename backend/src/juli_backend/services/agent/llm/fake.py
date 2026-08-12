"""Scripted `LLMService` fake -- the standard double for loop tests (ADR-071 decision 6).

A **shipped artifact**, not a test-local helper: downstream suites (the
WorkflowRunner in W3-A above all) depend on `FakeLLMService` to exercise loop
behavior exhaustively without network, cost, or non-determinism. It
implements the `LLMService` protocol (#985) exactly -- a caller cannot tell
it apart from `OpenAIResponsesAdapter` (#986) by type, only by constructing
it with a script instead of network credentials.

**Zero provider dependency.** This module imports nothing beyond the
standard library and `agent/llm`'s own block/config/service types -- no
`openai`, no `httpx`, no network library of any kind. The fake never makes a
call; it plays back a script.

Scripting model: a caller hands `FakeLLMService` a `script` of already-built
`AssistantTurn` objects -- the same neutral vocabulary (`TextBlock` /
`ToolCallBlock` / `FinalResponse` inside `AssistantTurn.blocks`) any real
`LLMService` returns, so scripting a plain text turn, a tool-call turn, or a
final response is just constructing the `AssistantTurn` a test wants back;
no second, fake-only turn language to learn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from juli_backend.services.agent.llm.blocks import AssistantTurn
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.service import Message, ToolDefinition


class ScriptExhaustedError(RuntimeError):
    """Raised when `FakeLLMService.complete` is called past the end of its script.

    A test that under-scripts a loop is a bug in the test, not something the
    fake should paper over by returning something arbitrary (ADR-071
    decision 6 / issue #987 acceptance criteria) -- this is the loud, specific
    failure that surfaces it.
    """


@dataclass(frozen=True)
class RecordedCall:
    """One `complete()` call the fake received, for test assertions.

    Captured verbatim (as a tuple snapshot, not a reference to the caller's
    mutable containers) so a test can assert exactly what was sent -- the
    messages, the system prompt, and the tools -- even after the caller has
    gone on to mutate or discard its own arguments.
    """

    messages: tuple[Message, ...]
    system: str
    tools: tuple[ToolDefinition, ...]
    config: LLMConfig


@dataclass
class FakeLLMService:
    """`LLMService` double that plays back a scripted sequence of `AssistantTurn`s.

    Construct with the turns to return, in order:

    ```python
    fake = FakeLLMService(
        script=[
            AssistantTurn(blocks=(TextBlock(text="checking stock"),), usage=Usage(0, 0)),
            AssistantTurn(
                blocks=(ToolCallBlock(call_id="c1", tool_name="get_inventory"),),
                usage=Usage(0, 0),
            ),
            AssistantTurn(blocks=(FinalResponse(content="done"),), usage=Usage(0, 0)),
        ]
    )
    ```

    Each `complete()` call returns the next scripted turn and advances an
    internal cursor -- turns are consumed in order across successive calls.
    A call made after the script is exhausted raises `ScriptExhaustedError`
    rather than returning something arbitrary (issue #987 acceptance
    criteria). Every call -- including the one that exhausts the script --
    is recorded on `recorded_calls` before the turn is resolved, so a test
    can inspect what was sent regardless of outcome.

    Each instance owns its own script and cursor; two `FakeLLMService`
    instances never share state.
    """

    script: Sequence[AssistantTurn]
    _next_index: int = field(default=0, init=False, repr=False)
    _recorded_calls: list[RecordedCall] = field(default_factory=list, init=False, repr=False)

    @property
    def recorded_calls(self) -> tuple[RecordedCall, ...]:
        """Every call received so far, in call order, as an immutable snapshot."""
        return tuple(self._recorded_calls)

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
    ) -> AssistantTurn:
        self._recorded_calls.append(
            RecordedCall(
                messages=tuple(messages),
                system=system,
                tools=tuple(tools),
                config=config,
            )
        )

        if self._next_index >= len(self.script):
            raise ScriptExhaustedError(
                f"FakeLLMService script exhausted: {len(self.script)} scripted turn(s) "
                f"configured, but complete() has now been called "
                f"{len(self._recorded_calls)} time(s). Script more turns or fix the "
                f"loop under test."
            )

        turn = self.script[self._next_index]
        self._next_index += 1
        return turn

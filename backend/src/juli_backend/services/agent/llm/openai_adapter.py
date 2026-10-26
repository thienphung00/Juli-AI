"""Stateless OpenAI Responses adapter (ADR-071 decisions 2, 3, 5; issue #986).

Implements the `LLMService` protocol (#985) against OpenAI's Responses API
HTTP surface. This module is the seam the rest of `agent/llm` was built to
keep open (`MODULE.md`): all provider-specific request/response translation
lives here and nowhere else in the package.

**No `openai` PyPI package import.** `backend/pyproject.toml` /
`backend/constraints.txt` do not declare the `openai` SDK, and CI installs
from a clean `pip install -e "./backend[dev]" -c backend/constraints.txt` --
an undeclared import would import successfully on a machine that happens to
have it installed ambiently and fail in CI. This adapter is built directly
on `httpx` (an already-declared dependency, the same library the vendor SDK
itself rides on) and speaks the Responses API's plain HTTP contract. Nothing
here is a vendor wire type by construction -- there is no vendor type to
begin with, only JSON dicts this module parses and immediately discards
after building Juli's own `Block`/`Usage` dataclasses.

**Stateless by construction** (ADR-071 decision 2): every request sets
``"store": False`` and never sends ``previous_response_id``. The full
message window is rebuilt from the caller-supplied ``messages`` on every
call; no provider-side thread is ever created or referenced.

**Through the shop's OpenAI gate** (ADR-116 §5, D76): the adapter builds the body
and hands it to `services.llm_gate.OpenAIGate`, which checks consent per input kind,
the payload allowlist and the ZDR flags, sends it with the one `OPENAI_API_KEY`, and
writes `llm_call_log`. A refusal surfaces as `LLMGateRefusedError` (an
`LLMProviderError`), so every caller's existing failure path handles it. An adapter
built without a gate refuses every call before any HTTP. `purpose` names the call in
the log (`agent_run`, `content_draft`, `content_scoring`, `content_frames`).

**Streaming is opt-in per call** (ADR-071 decision 3 as amended by D71.3,
P61-C). A call with no ``on_text_delta`` callback -- card drafts, structured
analysis, content scoring -- sends ``"stream": False`` exactly as before. A
call that passes ``on_text_delta`` while ``LLM_STREAMING`` is on (the
default, `config.llm_streaming_enabled`) sends ``"stream": True``, reads the
Responses API's server-sent events, hands every ``response.output_text.delta``
to the callback as it arrives, and still returns ONE complete
`AssistantTurn` -- the same blocks and usage the non-streamed call would
have produced. Tool-call arguments are assembled from
``response.function_call_arguments.delta`` / ``.done`` and
``response.output_item.done``; the terminal ``response.completed`` body is
authoritative when it carries ``output``. A ``response.failed`` / ``error``
event, a body that ends without a terminal event, or a malformed frame
raises `LLMProviderError` -- the turn fails cleanly, never half-returned.

**Message/tool shape.** `Message` and `ToolDefinition` are opaque
`Mapping[str, Any]` aliases owned by upstream modules this slice does not
build (`service.py`). This adapter interprets the minimal shape needed to
drive the Responses API:

- ``{"role": "user" | "assistant", "content": str}`` -> a plain input message.
- ``{"role": "tool", "tool_call_id": str, "content": str}`` -> a
  ``function_call_output`` item feeding a prior tool result back to the
  model (the stateless replay mechanism for tool round-trips).
  ``"tool_call_id"`` is the canonical key -- it matches the literal dict
  shape `services/agent/runner/core.py`'s `WorkflowRunner` appends to
  `state.conversation_window` on every tool round-trip. A legacy
  ``"call_id"`` key is also accepted as a fallback for any other caller of
  this adapter's `Message` shape (issue #1177: the adapter previously read
  only ``"call_id"``, so every runner-driven round-trip reached OpenAI with
  an empty ``call_id``).
- A tool definition -> ``{"name": str, "description": str, "input_schema":
  dict}`` (the `ToolDefinition` TypedDict in ``service.py``), carrying a
  Pydantic ``model_json_schema()`` render (ADR-069 decision 3, W1-A's
  registry shape), translated into a Responses API ``{"type": "function",
  ...}`` entry whose ``parameters`` is that schema. This module documented
  the key as ``parameters`` while the only producer emitted
  ``input_schema`` — see ``_translate_tool``.

Reconstructing a prior turn's own tool-call proposal as an ``input`` item is
out of scope here -- that composition belongs to the loop/P-CS module this
slice does not build.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from juli_backend.core.privacy import deidentify_text
from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    Block,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.config import LLMConfig, llm_streaming_enabled
from juli_backend.services.agent.llm.service import Message, TextDeltaCallback, ToolDefinition
from juli_backend.services.llm_gate import (
    OPENAI_BASE_URL,
    PURPOSE_AGENT_RUN,
    GateRefused,
    OpenAIGate,
    refuse_without_gate,
)

DEFAULT_BASE_URL = OPENAI_BASE_URL

# Responses API streaming event types this adapter reads (P61-C). Anything
# else (`response.created`, `response.in_progress`, `*.content_part.*`, ...)
# carries nothing the assembled turn needs and is skipped.
_EV_OUTPUT_ITEM_ADDED = "response.output_item.added"
_EV_OUTPUT_ITEM_DONE = "response.output_item.done"
_EV_TEXT_DELTA = "response.output_text.delta"
_EV_ARGS_DELTA = "response.function_call_arguments.delta"
_EV_ARGS_DONE = "response.function_call_arguments.done"
_EV_COMPLETED = "response.completed"
# `incomplete` (e.g. max_output_tokens reached) is terminal but not a failure:
# the non-streamed call returns the same partial body and it is parsed as is.
_EV_INCOMPLETE = "response.incomplete"
_EV_FAILED = "response.failed"
_EV_ERROR = "error"
_SSE_DATA_PREFIX = "data:"
_SSE_DONE_SENTINEL = "[DONE]"


@dataclass(frozen=True)
class JsonSchemaFormat:
    """A structured-output request: the JSON schema the model's text must follow.

    Translated to the Responses API's ``text.format`` (``type: json_schema``).
    ``strict`` asks OpenAI to guarantee the shape (every property required,
    ``additionalProperties: false`` -- the schema's author must comply).
    """

    name: str
    schema: Mapping[str, Any]
    strict: bool = True

    def to_wire(self) -> dict[str, Any]:
        return {
            "format": {
                "type": "json_schema",
                "name": self.name,
                "schema": dict(self.schema),
                "strict": self.strict,
            }
        }


class LLMProviderError(RuntimeError):
    """A Juli-level error for any OpenAI Responses API failure.

    Raised in place of any raw `httpx` exception or malformed-payload
    exception -- callers never see a provider/SDK-shaped exception type.
    """


class LLMGateRefusedError(LLMProviderError):
    """The OpenAI gate refused the call before any HTTP (ADR-116 §5): no consent for
    an input kind, a non-ZDR body, a payload outside the allowlist, or no shop gate.

    A subclass of `LLMProviderError` so every caller keeps its existing failure path
    (the runner ends the run `llm_error`, the drafter returns a provider error);
    ``refusal`` carries the gate's typed reason for callers that tell them apart.
    """

    def __init__(self, refusal: GateRefused) -> None:
        super().__init__(f"OpenAI call refused for this shop: {refusal.reason}")
        self.refusal = refusal


class OpenAIResponsesAdapter:
    """`LLMService` implementation over the OpenAI Responses API.

    ``transport`` is an injectable `httpx.AsyncBaseTransport` -- production
    code leaves it unset (real network); tests inject `httpx.MockTransport`
    over a recorded-shaped response body, mirroring the stubbed-transport
    pattern used for `tiktok_recorded_replay.py`, adapted to `httpx` because
    the OpenAI wire protocol (and the vendor SDK, when present) rides
    `httpx` rather than `requests`. The seam is typed as
    `AsyncBaseTransport` (not `BaseTransport`) because this adapter builds
    an `httpx.AsyncClient`, whose `transport` parameter only accepts the
    async transport base class.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        gate: OpenAIGate | None = None,
        purpose: str = PURPOSE_AGENT_RUN,
    ) -> None:
        self._transport: httpx.AsyncBaseTransport | None = transport
        self._base_url = base_url
        # ADR-116 §5: every request goes through the shop's gate; without one the
        # adapter refuses before any HTTP (`llm_gate.refuse_without_gate`).
        self._gate = gate
        self._purpose = purpose

    def with_gate(self, gate: OpenAIGate, *, purpose: str) -> OpenAIResponsesAdapter:
        """This adapter, sending through ``gate`` for ``purpose``."""
        return OpenAIResponsesAdapter(
            transport=self._transport, base_url=self._base_url, gate=gate, purpose=purpose
        )

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
        tool_choice: str | None = None,
        response_format: JsonSchemaFormat | None = None,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> AssistantTurn:
        """One Responses API call.

        ``on_text_delta`` (P61-C, D71.3) turns on streaming for this call when
        ``LLM_STREAMING`` is on: every output-text delta is awaited through
        it as it arrives, and the returned turn is still the complete one.
        Exceptions raised by the callback propagate unchanged (they are the
        caller's, not the provider's).

        ``response_format`` (fast track P14-E, D24.16) asks for OpenAI
        structured output: the model's text is then a JSON document that
        conforms to the given schema (``text.format`` = ``json_schema``,
        ``strict``). The text still arrives as the turn's ``FinalResponse``;
        the caller parses and validates it. Omitted, the request is unchanged.
        """
        stream = on_text_delta is not None and llm_streaming_enabled()
        body = _build_request_body(
            model=config.model,
            messages=messages,
            system=system,
            tools=tools,
            max_output_tokens=config.max_output_tokens,
            temperature=config.temperature,
            tool_choice=tool_choice,
            response_format=response_format,
            stream=stream,
        )
        if self._gate is None:
            raise LLMGateRefusedError(refuse_without_gate(self._purpose))
        try:
            if stream:
                assert on_text_delta is not None  # narrowed by `stream` above
                response_body = await self._post_streaming(
                    self._gate,
                    body=body,
                    timeout_seconds=config.request_timeout_seconds,
                    on_text_delta=on_text_delta,
                )
            else:
                response_body = await self._post(
                    self._gate, body=body, timeout_seconds=config.request_timeout_seconds
                )
        except GateRefused as exc:
            raise LLMGateRefusedError(exc) from exc

        blocks = _parse_output_blocks(response_body)
        usage = _parse_usage(response_body)
        return AssistantTurn(blocks=blocks, usage=usage)

    async def _post(
        self, gate: OpenAIGate, *, body: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        try:
            response = await gate.post_json(
                purpose=self._purpose,
                body=body,
                timeout=timeout_seconds,
                transport=self._transport,
                base_url=self._base_url,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"OpenAI Responses API returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenAI Responses API request failed: {exc}") from exc
        except ValueError as exc:
            # json.JSONDecodeError subclasses ValueError.
            raise LLMProviderError(f"OpenAI Responses API returned a non-JSON body: {exc}") from exc

    async def _post_streaming(
        self,
        gate: OpenAIGate,
        *,
        body: dict[str, Any],
        timeout_seconds: float,
        on_text_delta: TextDeltaCallback,
    ) -> dict[str, Any]:
        """POST with ``stream: true``; return a body shaped like the non-streamed one.

        Text deltas are forwarded to ``on_text_delta`` as they arrive. The
        returned dict has ``output`` + ``usage`` so `_parse_output_blocks` /
        `_parse_usage` build the turn exactly as for a non-streamed call.
        """
        assembler = _StreamAssembler()
        try:
            async with gate.stream_json(
                purpose=self._purpose,
                body=body,
                timeout=timeout_seconds,
                transport=self._transport,
                base_url=self._base_url,
            ) as call:
                call.response.raise_for_status()
                async for event in _iter_sse_events(call.response.aiter_lines()):
                    text_delta = assembler.feed(event)
                    if text_delta:
                        await on_text_delta(text_delta)
                    if assembler.done:
                        break
                usage = assembler.usage()
                call.input_tokens, call.output_tokens = usage.input_tokens, usage.output_tokens
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"OpenAI Responses API returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenAI Responses API stream failed: {exc}") from exc
        return assembler.result()


async def _iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Server-sent events -> parsed JSON ``data`` objects, in order.

    ``event:`` lines are ignored: every Responses API ``data`` object carries
    its own ``type``. Multi-line ``data`` is joined per the SSE spec; a blank
    line ends a frame; ``[DONE]`` is skipped.
    """
    data_lines: list[str] = []

    def _flush() -> dict[str, Any] | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines)
        data_lines.clear()
        if raw.strip() == _SSE_DONE_SENTINEL:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"OpenAI Responses API stream sent a non-JSON frame: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise LLMProviderError("OpenAI Responses API stream sent a non-object frame")
        return parsed

    async for line in lines:
        if line == "":
            event = _flush()
            if event is not None:
                yield event
            continue
        if line.startswith(_SSE_DATA_PREFIX):
            data_lines.append(line[len(_SSE_DATA_PREFIX) :].lstrip(" "))
    event = _flush()
    if event is not None:
        yield event


class _StreamAssembler:
    """Folds Responses API stream events into the non-streamed body shape.

    Output items are kept by ``output_index``: ``output_item.added`` opens
    one, text / argument deltas append to it, ``function_call_arguments.done``
    and ``output_item.done`` replace it with the provider's final copy. The
    terminal ``response.completed`` (or ``.incomplete``) body wins when it
    carries a non-empty ``output`` -- it is the provider's own assembled
    answer; the locally assembled items are the fallback for a terminal body
    that omits it.
    """

    def __init__(self) -> None:
        self._items: dict[int, dict[str, Any]] = {}
        self._final: dict[str, Any] | None = None

    @property
    def done(self) -> bool:
        return self._final is not None

    def feed(self, event: Mapping[str, Any]) -> str:
        """Fold one event; return its output-text delta ('' when it has none)."""
        event_type = event.get("type")
        if event_type == _EV_TEXT_DELTA:
            delta = event.get("delta")
            text = delta if isinstance(delta, str) else ""
            self._append_text(event, text)
            return text
        if event_type == _EV_OUTPUT_ITEM_ADDED or event_type == _EV_OUTPUT_ITEM_DONE:
            item = event.get("item")
            if isinstance(item, dict):
                self._items[self._index(event)] = dict(item)
        elif event_type == _EV_ARGS_DELTA:
            item = self._items.setdefault(self._index(event), {"type": "function_call"})
            delta = event.get("delta")
            item["arguments"] = str(item.get("arguments") or "") + (
                delta if isinstance(delta, str) else ""
            )
        elif event_type == _EV_ARGS_DONE:
            item = self._items.setdefault(self._index(event), {"type": "function_call"})
            if isinstance(event.get("arguments"), str):
                item["arguments"] = event["arguments"]
        elif event_type == _EV_COMPLETED or event_type == _EV_INCOMPLETE:
            response = event.get("response")
            self._final = dict(response) if isinstance(response, dict) else {}
        elif event_type == _EV_FAILED:
            response = event.get("response")
            error = response.get("error") if isinstance(response, dict) else None
            raise LLMProviderError(f"OpenAI Responses API stream failed: {_error_text(error)}")
        elif event_type == _EV_ERROR:
            raise LLMProviderError(f"OpenAI Responses API stream error: {_error_text(event)}")
        return ""

    def usage(self) -> Usage:
        """The terminal body's usage (zero before ``response.completed``)."""
        return _parse_usage(self._final or {})

    def result(self) -> dict[str, Any]:
        if self._final is None:
            raise LLMProviderError("OpenAI Responses API stream ended without response.completed")
        body = dict(self._final)
        if not body.get("output"):
            body["output"] = [self._items[index] for index in sorted(self._items)]
        return body

    @staticmethod
    def _index(event: Mapping[str, Any]) -> int:
        index = event.get("output_index")
        if not isinstance(index, int):
            raise LLMProviderError("OpenAI Responses API stream event has no output_index")
        return index

    def _append_text(self, event: Mapping[str, Any], text: str) -> None:
        item = self._items.setdefault(
            self._index(event), {"type": "message", "role": "assistant", "content": []}
        )
        content = item.setdefault("content", [])
        content_index = event.get("content_index", 0)
        while len(content) <= content_index:
            content.append({"type": "output_text", "text": ""})
        part = content[content_index]
        part["text"] = str(part.get("text") or "") + text


def _error_text(error: Any) -> str:
    if isinstance(error, Mapping):
        code = error.get("code") or ""
        message = error.get("message") or ""
        return f"{code} {message}".strip() or "unknown error"
    return "unknown error"


# ---------------------------------------------------------------------------
# Request translation: Juli messages/system/tools/config -> Responses body
# ---------------------------------------------------------------------------


def _build_request_body(
    *,
    model: str,
    messages: Sequence[Message],
    system: str,
    tools: Sequence[ToolDefinition],
    max_output_tokens: int,
    temperature: float,
    tool_choice: str | None = None,
    response_format: JsonSchemaFormat | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        # D68.2 (P50-P): this body is the single LLM boundary. Every text that
        # reaches the provider -- system text, messages, tool results -- is
        # de-identified first; tool schemas and the output schema are not text.
        "instructions": deidentify_text(system),
        "input": [_translate_message(message) for message in messages],
        "tools": [_translate_tool(tool) for tool in tools],
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        # Stateless by construction (ADR-071 decision 2): never persisted
        # server-side, never referenced via `previous_response_id`.
        "store": False,
        # Streamed only when the caller asked for text deltas and
        # LLM_STREAMING is on (D71.3); the returned turn is complete either way.
        "stream": stream,
    }
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if response_format is not None:
        body["text"] = response_format.to_wire()
    return body


def _translate_message(message: Message) -> dict[str, Any]:
    role = message.get("role")

    # The model's own tool-call proposal from a previous turn (issue #1191).
    # The Responses API is stateless: a `function_call_output` is only valid
    # when the request also replays the `function_call` it answers, with a
    # matching `call_id`. Without this branch the proposal fell through to the
    # generic text branch below and became an empty `output_text` item, so the
    # very next message referenced a `call_id` that did not exist in the
    # request and OpenAI returned 400 -- every tool-using run died on its
    # second turn. `arguments` is a JSON *string* in this API; the runner holds
    # it as a dict (`core.py::_tool_call_message`).
    tool_call = message.get("tool_call")
    if role == "assistant" and tool_call:
        return {
            "type": "function_call",
            "call_id": tool_call.get("call_id", ""),
            "name": tool_call.get("tool_name", ""),
            "arguments": json.dumps(tool_call.get("arguments") or {}),
        }

    if role == "tool":
        # "tool_call_id" is canonical (matches the runner's literal append
        # shape in `services/agent/runner/core.py`); "call_id" is a fallback
        # for any other caller of this adapter's `Message` shape (#1177).
        call_id = message.get("tool_call_id") or message.get("call_id", "")
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": deidentify_text(str(message.get("content", ""))),
        }
    content = message.get("content", "")
    if role == "user" and isinstance(content, list | tuple):
        # Fast track P15: a user message may carry content parts as the
        # Responses API spells them (``input_text`` / ``input_image``), so the
        # content-analysis vision step can send keyframes. Passed through as is.
        return {"role": "user", "content": [_deidentify_part(part) for part in content]}
    content_type = "input_text" if role == "user" else "output_text"
    return {
        "role": role,
        "content": [{"type": content_type, "text": deidentify_text(str(content))}],
    }


def _deidentify_part(part: Mapping[str, Any]) -> dict[str, Any]:
    """A content part with its text de-identified; image parts pass as they are."""
    out = dict(part)
    if isinstance(out.get("text"), str):
        out["text"] = deidentify_text(out["text"])
    return out


def _translate_tool(tool: ToolDefinition) -> dict[str, Any]:
    """One `ToolDefinition` -> one Responses API function-tool entry.

    Reads `input_schema` (the domain key `ToolDefinition` declares) and
    emits `parameters` (the wire key) — the rename is the translation. It
    used to read `parameters` from the definition itself, which the sole
    producer has never set, and substitute an empty schema when absent: see
    `ToolDefinition`'s docstring for what that cost live.

    A missing schema now raises rather than defaulting. An empty parameter
    schema is a lie the model cannot detect — it declares a tool takes no
    arguments — and it is indistinguishable downstream from a genuinely
    argument-less tool. Pydantic's `model_json_schema()` always returns a
    populated object (`{"type": "object", "properties": {...}, ...}`) even
    for a model with no fields, so a real `ToolSpec` render can never
    trigger this.
    """
    input_schema = tool.get("input_schema")
    if not input_schema:
        raise ValueError(
            f"tool definition {tool.get('name', '')!r} carries no 'input_schema'; refusing "
            "to declare it to the model as taking no arguments"
        )
    return {
        "type": "function",
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "parameters": input_schema,
    }


# ---------------------------------------------------------------------------
# Response translation: Responses API output -> Juli blocks + usage
# ---------------------------------------------------------------------------


def _parse_output_blocks(response_body: dict[str, Any]) -> tuple[Block, ...]:
    try:
        output_items = response_body.get("output", [])
    except AttributeError as exc:
        raise LLMProviderError("OpenAI Responses API returned an unexpected body shape") from exc

    text_parts: list[str] = []
    tool_call_blocks: list[ToolCallBlock] = []

    for item in output_items:
        item_type = item.get("type")
        if item_type == "message":
            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    text_parts.append(content_item.get("text", ""))
        elif item_type == "function_call":
            tool_call_blocks.append(_parse_tool_call(item))

    joined_text = "\n".join(part for part in text_parts if part)

    blocks: list[Block] = []
    if tool_call_blocks:
        # A turn that proposes a tool call is not yet final -- any narration
        # accompanying it is interim commentary, not the closing answer.
        if joined_text:
            blocks.append(TextBlock(text=joined_text))
        blocks.extend(tool_call_blocks)
    else:
        # No tool call: this text closes the turn.
        blocks.append(FinalResponse(content=joined_text))

    return tuple(blocks)


def _parse_tool_call(item: dict[str, Any]) -> ToolCallBlock:
    raw_arguments = item.get("arguments", "{}")
    try:
        arguments = (
            json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
        )
    except json.JSONDecodeError as exc:
        raise LLMProviderError(
            f"OpenAI Responses API returned malformed tool call arguments: {exc}"
        ) from exc

    return ToolCallBlock(
        call_id=item.get("call_id") or item.get("id", ""),
        tool_name=item.get("name", ""),
        arguments=arguments,
    )


def _parse_usage(response_body: dict[str, Any]) -> Usage:
    usage = response_body.get("usage") or {}
    return Usage(
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )

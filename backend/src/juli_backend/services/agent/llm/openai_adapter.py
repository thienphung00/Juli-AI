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

**Non-streamed** (ADR-071 decision 3): every request sets ``"stream":
False``. One HTTP call, one complete `AssistantTurn` -- no token deltas.

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
from collections.abc import Sequence
from typing import Any

import httpx

from juli_backend.core.config import require_env
from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    Block,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.service import Message, ToolDefinition

_API_KEY_ENV_VAR = "OPENAI_API_KEY"
DEFAULT_BASE_URL = "https://api.openai.com"
_RESPONSES_PATH = "/v1/responses"


class LLMProviderError(RuntimeError):
    """A Juli-level error for any OpenAI Responses API failure.

    Raised in place of any raw `httpx` exception or malformed-payload
    exception -- callers never see a provider/SDK-shaped exception type.
    """


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
    ) -> None:
        self._transport: httpx.AsyncBaseTransport | None = transport
        self._base_url = base_url

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
    ) -> AssistantTurn:
        api_key = require_env(_API_KEY_ENV_VAR)
        body = _build_request_body(
            model=config.model,
            messages=messages,
            system=system,
            tools=tools,
            max_output_tokens=config.max_output_tokens,
            temperature=config.temperature,
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response_body = await self._post(
            body=body, headers=headers, timeout_seconds=config.request_timeout_seconds
        )

        blocks = _parse_output_blocks(response_body)
        usage = _parse_usage(response_body)
        return AssistantTurn(blocks=blocks, usage=usage)

    async def _post(
        self, *, body: dict[str, Any], headers: dict[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                base_url=self._base_url,
                timeout=timeout_seconds,
            ) as client:
                response = await client.post(_RESPONSES_PATH, json=body, headers=headers)
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
) -> dict[str, Any]:
    return {
        "model": model,
        "instructions": system,
        "input": [_translate_message(message) for message in messages],
        "tools": [_translate_tool(tool) for tool in tools],
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        # Stateless by construction (ADR-071 decision 2): never persisted
        # server-side, never referenced via `previous_response_id`.
        "store": False,
        # Non-streamed (ADR-071 decision 3): one complete turn per call.
        "stream": False,
    }


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
            "output": str(message.get("content", "")),
        }
    content_type = "input_text" if role == "user" else "output_text"
    return {
        "role": role,
        "content": [{"type": content_type, "text": str(message.get("content", ""))}],
    }


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

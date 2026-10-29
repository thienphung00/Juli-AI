# Module: agent/llm

## Responsibility

Juli's own model vocabulary and the service contract over it (#985, ADR-071
decisions 1 and 4), the stateless OpenAI Responses adapter that implements
that contract (#986, ADR-071 decisions 2, 3, 5), and the scripted fake
implementing the same contract for loop tests (#987, ADR-071 decision 6).
Blocks the agent can produce, a usage record, an assistant turn, the
`LLMService` protocol, fail-closed `LLMConfig` resolution, one concrete
provider adapter, and one concrete test double. **No `openai` PyPI package
import anywhere in this module** — the `openai` package is not declared in
`backend/pyproject.toml` / `backend/constraints.txt`, so `openai_adapter.py`
is built directly on `httpx` (already declared) and speaks the Responses
API's HTTP contract without the vendor SDK; `fake.py` imports no
provider/network library at all. This is the seam (the `integrations/tiktok`
wrapping pattern) that keeps a future provider swap to one file;
provider-specific request/response knowledge lives only in
`openai_adapter.py`.

## Public Interface

Import from the package root, which re-exports the neutral vocabulary and the
test double. `OpenAIResponsesAdapter` and `LLMProviderError` are deliberately
**not** re-exported: the provider-touching class is reached explicitly via
`juli_backend.services.agent.llm.openai_adapter`, so nothing depends on a
concrete adapter by accident. Callers depend on the `LLMService` protocol.

```python
from juli_backend.services.agent.llm import (
    TextBlock, ToolCallBlock, FinalResponse, Block,
    Usage, AssistantTurn,
    LLMService, Message, ToolDefinition,
    LLMConfig, LLMConfigOverride, resolve_llm_config,
    DEFAULT_MODEL, DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TEMPERATURE, DEFAULT_REQUEST_TIMEOUT_SECONDS,
    FakeLLMService, RecordedCall, ScriptExhaustedError,
)
```

### Blocks (`blocks.py`)

- `TextBlock(text)` — freeform assistant narration
- `ToolCallBlock(call_id, tool_name, arguments={})` — a proposed tool invocation
- `FinalResponse(content, structured_output=None)` — terminal block closing the turn
- `Block` — `TextBlock | ToolCallBlock | FinalResponse`
- `Usage(input_tokens, output_tokens)` — token accounting for one provider call
- `AssistantTurn(blocks, usage)` — one complete provider call (streamed or not)

All frozen dataclasses. Turn-level only — token deltas never appear in a
turn; a streamed call hands them to `on_text_delta` (ADR-071 amendment,
D71.3 / P61-C).

### Service (`service.py`)

- `LLMService` — `runtime_checkable` `Protocol`:
  `async complete(*, messages, system, tools, config) -> AssistantTurn`
- `TextDeltaCallback` — `Callable[[str], Awaitable[None]]`, the opt-in
  `on_text_delta` keyword a streaming-capable service accepts. Deliberately
  not on the `LLMService` protocol: scripted planners and test doubles
  implement the protocol without it.
- `Message`, `ToolDefinition` — opaque `Mapping[str, Any]` aliases. The
  durable message shape (P-CS store) and tool definitions (playbook tool
  registry) are owned by modules this slice does not build; this protocol
  only constrains the LLM service boundary.

Callers depend on `LLMService` the interface, never a concrete adapter. A
scripted fake implementing `complete` is the standard test double (ADR-071
decision 6).

### Config (`config.py`)

- `LLMConfig(model, max_output_tokens, temperature, request_timeout_seconds)`
- `LLMConfigOverride(...)` — same fields, all optional; a workflow playbook's override
- `resolve_llm_config(override=None) -> LLMConfig` — resolves
  **playbook override -> environment -> defaults** per field. Fails closed:
  raises `RuntimeError` via `require_env("OPENAI_API_KEY")` when the key is
  absent or blank, before resolving any field. The key is never stored on
  `LLMConfig` — it is not a secrets carrier; a provider adapter reads the key
  directly at call time via the same `require_env` pattern.
- Defaults: `DEFAULT_MODEL = "gpt-5.4-nano"`, `DEFAULT_MAX_OUTPUT_TOKENS = 1024`,
  `DEFAULT_TEMPERATURE = 0.2`, `DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0`
- Environment variables: `OPENAI_API_KEY` (required), `LLM_MODEL`,
  `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`, `LLM_REQUEST_TIMEOUT_SECONDS`,
  `LLM_STREAMING` (default on; `0`/`false`/`no`/`off` turns streaming off)
- `llm_streaming_enabled() -> bool` — reads `LLM_STREAMING` at call time
  (`DEFAULT_LLM_STREAMING = True`)
- `ModelPrice(input_usd_per_million_tokens, output_usd_per_million_tokens)` —
  one model's static price row
- `PRICE_TABLE_USD_PER_MILLION_TOKENS` — the static price table (ADR-071
  decision 5); a maintained artifact, not a live feed
- `estimate_cost_usd(model, usage) -> float` — derives a USD estimate from
  the table; `0.0` for an unpriced model rather than raising

### OpenAI adapter (`openai_adapter.py`, #986)

- `OpenAIResponsesAdapter(transport=None, base_url=DEFAULT_BASE_URL, gate=None,
  purpose="agent_run")` — `LLMService` implementation over the OpenAI Responses
  API's HTTP surface, sending every request through the shop's
  `services.llm_gate.OpenAIGate` (ADR-116 §5). No gate → every call refused
  before any HTTP. `with_gate(gate, purpose=...)` returns a gated copy.
  `transport` is an injectable `httpx.AsyncBaseTransport`; tests pass
  `httpx.MockTransport` over a recorded-shaped response body, production
  leaves it unset (real network).
- `LLMProviderError(RuntimeError)` — the one error type this module raises
  for any provider failure (bad status, transport failure, malformed body,
  malformed tool-call arguments). Callers never see a raw `httpx` exception.
  `LLMGateRefusedError(LLMProviderError)` is the gate's refusal (`.refusal`).
- Stateless (ADR-071 decision 2): every request body sets `"store": False`
  and never includes `"previous_response_id"`; the full message window is
  rebuilt from the caller's `messages` on every call.
- Streaming is opt-in per call (ADR-071 amendment, D71.3 / P61-C):
  `complete(..., on_text_delta=cb)` with `LLM_STREAMING` on sends
  `"stream": True`, reads the Responses API server-sent events, awaits `cb`
  with every `response.output_text.delta`, and returns the same complete
  `AssistantTurn` (tool-call arguments assembled from
  `function_call_arguments.delta`/`.done` and `output_item.done`; the
  `response.completed` body's `output` wins when present). `response.failed`,
  `error`, a missing terminal event or a non-JSON frame raise
  `LLMProviderError`; callback exceptions propagate unchanged. Without a
  callback (card drafts, structured analysis, scoring) or with the flag off,
  the request is non-streamed (`"stream": False`) exactly as before.
- Message shape consumed: `{"role": "user"|"assistant", "content": str}` or
  `{"role": "tool", "call_id": str, "content": str}` (a prior tool result,
  translated to a `function_call_output` item). Reconstructing a prior
  turn's own tool-call proposal as an input item is out of scope for this
  slice.
- Tool shape consumed: `{"name": str, "description": str, "input_schema":
  dict}` (a Pydantic `model_json_schema()` render, per ADR-069 decision 3),
  translated to a Responses API `{"type": "function", "strict": true,
  "parameters": to_strict(input_schema)}` tool entry (P76-1, D78).
- `JsonSchemaFormat(name, schema, strict=True)` — a structured-output request;
  a strict schema goes out through `to_strict` as well.
- Response translation: a `function_call` output item becomes a
  `ToolCallBlock`; `output_text` message content becomes a `TextBlock` when
  the turn also proposes a tool call (interim narration), or a
  `FinalResponse` when it does not (the turn's closing answer).
- `Usage` on the returned `AssistantTurn` is read from the response body's
  `usage.input_tokens` / `usage.output_tokens`.

### Strict schemas (`strict_schema.py`, P76-1, D78)

The strict contract: every tool and every strict output format reaches OpenAI
in Structured Outputs strict form, so the model's arguments and structured
output are guaranteed to match the declared shape.

- `to_strict(schema) -> dict` — pure, idempotent; a conforming schema comes
  back equal. Inlines `$defs`; closes every object (`additionalProperties:
  false`, every property in `required`, optional ⇒ union with `null`); drops
  `title` / `default` / `examples` (a non-null default is stated in the
  description) and `minLength` / `maxLength` (stated in the description, still
  enforced by the tool's Pydantic model). Keeps `enum` / `const` / `anyOf` /
  `pattern` / `format` (supported values) / number bounds / `minItems` /
  `maxItems` / `description`.
- `StrictSchemaError` — anything else: open objects (`dict[str, X]`), `allOf`
  with more than one branch, `not` / `if` / `uniqueItems` / …, an unsupported
  `format`, a recursive model, a root `anyOf`. No silent degrade inside
  `to_strict`.
- `strict_problems(schema) -> list[str]` — the independent conformance checker.
- **D78.5:** an unconvertible schema fails
  `tests/unit/test_agent_strict_tool_schemas.py` (every registered tool, every
  playbook), never the running app — the adapter logs
  `strict_schema_unconvertible` and sends that one schema non-strict.
- The model sends `null` for an optional field it leaves out;
  `ToolSpec.parse_input` (`tools/registry.py`) turns it into the field default.
- Source for the supported keyword set: OpenAI Structured Outputs guide,
  "Supported schemas" (developers.openai.com/api/docs/guides/structured-outputs,
  read 2026-10-29).

### Fake (`fake.py`, #987)

- `FakeLLMService(script)` — `LLMService` implementation that plays back a
  scripted `Sequence[AssistantTurn]`, in order, across successive
  `complete()` calls. The **standard double for loop tests** (ADR-071
  decision 6) — downstream suites (the WorkflowRunner in W3-A above all)
  construct it directly instead of stubbing HTTP. Each instance owns its own
  script and cursor; two instances never share state.
  - Script a plain text turn, a tool-call turn, or a final response by
    constructing the corresponding `AssistantTurn` — no fake-only scripting
    language, the same block vocabulary every `LLMService` returns.
  - `recorded_calls` — a tuple of `RecordedCall(messages, system, tools,
    config)` snapshots, one per `complete()` call received, in call order
    (including the call that triggers exhaustion), for asserting what a
    caller sent.
  - Calling `complete()` past the end of the script raises
    `ScriptExhaustedError` rather than returning something arbitrary.
- `RecordedCall(messages, system, tools, config)` — frozen dataclass; one
  recorded `complete()` call.
- `ScriptExhaustedError(RuntimeError)` — raised on a `complete()` call past
  the end of the script.
- `stream_chunk_chars` (P61-C) — when set and a caller passes
  `on_text_delta`, the turn's text (`TextBlock` / `FinalResponse` text, in
  block order) is played through the callback in chunks of that size before
  the turn is returned.
- Zero provider dependency: imports only `agent/llm`'s own block/config/
  service types and the standard library — no `httpx`, no network library
  of any kind, unlike `openai_adapter.py`.

## Dependencies

- `juli_backend.core.config.require_env` — fail-closed env read (ADR-061)
- `httpx` (already a backend dependency) — the OpenAI adapter's HTTP client
- Standard library only otherwise (`fake.py` uses no third-party import at all)


## Invariants

- No `openai`/`anthropic`/`litellm`/`ollama`/`langchain` import anywhere under
  this package's top-level files (asserted by
  `tests/unit/test_agent_llm_contract.py`) — trivially true for
  `openai_adapter.py` too, since it never imports the `openai` package at
  all (undeclared dependency; see module docstring).
- `resolve_llm_config` never defaults `OPENAI_API_KEY` to an empty string.
- Blocks and `AssistantTurn` are frozen — a turn, once returned, does not mutate.
- `OpenAIResponsesAdapter` never sends `previous_response_id` and always
  sets `"store": False`; it sets `"stream": True` only for a call that
  passed `on_text_delta` while `LLM_STREAMING` is on.
- Every tool entry the adapter sends carries `"strict": true` unless its schema
  is unconvertible (then logged, never raised); every registered tool converts
  (CI gate, D78.5).
- `fake.py` imports no provider/network library (asserted by
  `tests/unit/test_agent_llm_fake.py`) — the fake never makes a network call.
- `FakeLLMService` returns scripted turns strictly in order and never
  returns past the end of its script (raises `ScriptExhaustedError` instead).

## Related modules

- ADR-071 — design authority for this module
- ADR-068 — block vocabulary and containment origin (decision 6)
- ADR-069 — tool registry / `ToolSpec` schema shape consumed by the adapter
- A second provider or fallback chain later means a second adapter behind
  the same `LLMService` interface; nothing upstream changes (ADR-071
  consequences).
- A future OpenAI Responses adapter (not this slice) implements `LLMService`
  privately behind this same package, per ADR-071 decision 2.

## Owners

- domain: agent workflow execution (backend)
- code: `backend/src/juli_backend/services/agent/llm/`

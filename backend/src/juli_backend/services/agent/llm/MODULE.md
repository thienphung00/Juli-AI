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

Import from the package root only:

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
- `AssistantTurn(blocks, usage)` — one complete, non-streamed provider call

All frozen dataclasses. Turn-level only — no token deltas
(`assistant.text.delta` is reserved for a future chat surface, ADR-071
decision 3).

### Service (`service.py`)

- `LLMService` — `runtime_checkable` `Protocol`:
  `async complete(*, messages, system, tools, config) -> AssistantTurn`
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
  `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`, `LLM_REQUEST_TIMEOUT_SECONDS`
- `ModelPrice(input_usd_per_million_tokens, output_usd_per_million_tokens)` —
  one model's static price row
- `PRICE_TABLE_USD_PER_MILLION_TOKENS` — the static price table (ADR-071
  decision 5); a maintained artifact, not a live feed
- `estimate_cost_usd(model, usage) -> float` — derives a USD estimate from
  the table; `0.0` for an unpriced model rather than raising

### OpenAI adapter (`openai_adapter.py`, #986)

- `OpenAIResponsesAdapter(transport=None, base_url=DEFAULT_BASE_URL)` —
  `LLMService` implementation over the OpenAI Responses API's HTTP surface.
  `transport` is an injectable `httpx.BaseTransport`; tests pass
  `httpx.MockTransport` over a recorded-shaped response body, production
  leaves it unset (real network).
- `LLMProviderError(RuntimeError)` — the one error type this module raises
  for any provider failure (bad status, transport failure, malformed body,
  malformed tool-call arguments). Callers never see a raw `httpx` exception.
- Stateless (ADR-071 decision 2): every request body sets `"store": False`
  and never includes `"previous_response_id"`; the full message window is
  rebuilt from the caller's `messages` on every call.
- Non-streamed (ADR-071 decision 3): every request body sets
  `"stream": False`; one HTTP call produces one complete `AssistantTurn`.
- Message shape consumed: `{"role": "user"|"assistant", "content": str}` or
  `{"role": "tool", "call_id": str, "content": str}` (a prior tool result,
  translated to a `function_call_output` item). Reconstructing a prior
  turn's own tool-call proposal as an input item is out of scope for this
  slice.
- Tool shape consumed: `{"name": str, "description": str, "parameters":
  dict}` (a Pydantic `model_json_schema()` render, per ADR-069 decision 3),
  translated to a Responses API `{"type": "function", ...}` tool entry.
- Response translation: a `function_call` output item becomes a
  `ToolCallBlock`; `output_text` message content becomes a `TextBlock` when
  the turn also proposes a tool call (interim narration), or a
  `FinalResponse` when it does not (the turn's closing answer).
- `Usage` on the returned `AssistantTurn` is read from the response body's
  `usage.input_tokens` / `usage.output_tokens`.

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
  sets `"store": False` / `"stream": False` on the outbound request.
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

## Owners

- domain: agent workflow execution (backend)
- code: `backend/src/juli_backend/services/agent/llm/`

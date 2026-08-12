# Module: agent/llm

## Responsibility

Juli's own model vocabulary and the service contract over it (#985, ADR-071
decisions 1 and 4). Blocks the agent can produce, a usage record, an
assistant turn, the `LLMService` protocol, and fail-closed `LLMConfig`
resolution. **No provider code lands in this module** — no `openai` import,
no wire types. This is the seam (the `integrations/tiktok` wrapping pattern)
that keeps a future provider swap to one file.

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

## Dependencies

- `juli_backend.core.config.require_env` — fail-closed env read (ADR-061)
- Standard library only otherwise

## Invariants

- No `openai`/`anthropic`/`litellm`/`ollama`/`langchain` import anywhere under
  this package (asserted by `tests/unit/test_agent_llm_contract.py`).
- `resolve_llm_config` never defaults `OPENAI_API_KEY` to an empty string.
- Blocks and `AssistantTurn` are frozen — a turn, once returned, does not mutate.

## Related modules

- ADR-071 — design authority for this module
- ADR-068 — block vocabulary and containment origin (decision 6)
- A future OpenAI Responses adapter (not this slice) implements `LLMService`
  privately behind this same package, per ADR-071 decision 2.

## Owners

- domain: agent workflow execution (backend)
- code: `backend/src/juli_backend/services/agent/llm/`

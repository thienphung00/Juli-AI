# backend/src/juli_backend/services/llm_gate

## Purpose

The one door to OpenAI for every backend call that carries shop data (ADR-116 §5,
fast track D76, grill D4 addendum / D6 revised). Migration 105, model
`models/llm_call_log.py`. Nothing else in `backend/src` may name `api.openai.com`
or an OpenAI state / storage endpoint (`tests/unit/test_llm_gate_ci_rule.py`).

Since the Juli tab (jev-router grill J9 / J10) it is also the one door to **Anthropic
Messages** (`api.anthropic.com/v1/messages`, plain + streamed) and **TypeSafe System One**
(`api.typesafe.ai/v1/systemone`) for the analytics agent (`vendors.py`). Neither host may
be named elsewhere in `backend/src` (same CI rule). Plain `httpx`, no vendor SDK.

## The four paths

| Path | Client | Gate method | Purpose |
|---|---|---|---|
| Agent runs | `agent/llm/openai_adapter.py` | `post_json` / `stream_json` | `agent_run` |
| Image inspection | `agent/vision.py` (sync tool handler) | `post_json_sync` | `image_inspection` |
| Content analysis | `content_analysis/openai_media.py` | `post_transcription`, adapter | `content_transcription`, `content_frames` |
| Scoring / drafts | `content_analysis/scoring.py`, `content_cards/drafter.py` via the adapter | `post_json` | `content_scoring`, `content_draft` |

Wiring: `workers/tasks/agent_workflow.py::_construct_runner` (agent + inspector +
content drafter share one gate per run leg), `content_cards/driver.py::wiring_for_run`,
`workers/tasks/content_analysis.py::run_analysis`.

## Analytics agent doors (`vendors.py`)

| Function | Host + path | Purposes | `llm_call_log.project` |
|---|---|---|---|
| `anthropic_messages(gate, purpose, body, timeout)` -> `(json, Usage)` | `api.anthropic.com` `/v1/messages` | `agent_chat_parse`, `agent_chat_write` | `anthropic` |
| `anthropic_stream(...)` (async context; `async for text in stream`; `stream.usage`) | same, `stream: true` | same | `anthropic` |
| `typesafe_system_one(gate, purpose, model, state, questions, timeout)` -> `(answers, Usage)` | `api.typesafe.ai` `/v1/systemone` | `agent_chat_route` | `typesafe` |

Same gate object, same order of checks: purpose bound to its provider (`unknown_purpose`),
endpoint pair (`endpoint_not_allowed`), shape allowlist (`payload_shape`; Messages keys
`model, system, messages, max_tokens, stream, tools, tool_choice, stop_sequences,
output_config, thinking` -- no `temperature`; blocks `text` / `tool_use` / `tool_result`
only; System One exactly `{model, state, questions}`, questions `choice` / `noul`), consent
`llm_processing` (`consent_llm_processing`), key `ANTHROPIC_API_KEY` / `TYPESAFE_API_KEY`
(`unconfigured`). Minimisation as below, plus every image URL in text is stripped (images
never go to these vendors). After sending, a failure (status, transport, stream error,
no `answers`) is an `error` row and `GateCallFailed(reason, status_code, retry_after)`.

## Per call, before any HTTP (OpenAI)

1. Endpoint allowlist: `/v1/responses`, `/v1/audio/transcriptions`.
2. Shape allowlist + ZDR flags (`payload.py`): `store: false`; no
   `previous_response_id` / `background` / `conversation`. Transcription has no
   `store` field.
3. Input kinds -> consent: text -> `llm_processing`; `input_image` -> `llm_images`
   (a `data:` keyframe in `content_frames` -> `llm_media`); audio -> `llm_media`.
   Image URLs inside text are kept only with `llm_images`, else replaced by
   `[ảnh đã ẩn]`.
4. Minimisation: forbidden keys dropped from every JSON text at any depth
   (`is_forbidden_key`: shop name / ids / cipher, buyer* / recipient*, user ids,
   tokens, secrets, credentials); the shop's Juli / TikTok / Shopee ids replaced by
   `[shop]` in all text.
5. `GateRefused(reason)` or the call; one `llm_call_log` row either way.

## Public API

```python
from juli_backend.services.llm_gate import (
    OpenAIGate, GateRefused, open_gate, SessionCallLog, SyncSessionCallLog,
    MemoryCallLog, LLM_PROCESSING, LLM_IMAGES, LLM_MEDIA, PURPOSE_AGENT_RUN, ...
)
gate = await open_gate(session, shop_id, sink=SessionCallLog(session))
```

`open_gate` reads the three grants once (`services.consent.has_consent`); consent
changes apply to the next run leg / analysis / draft.

## Must-nots

- No HTTP to OpenAI, Anthropic or TypeSafe outside this package; no second OpenAI key, no
  key routing.
- No prompt or output content in `llm_call_log` (metadata only).
- A log write never raises into the call path.
- A client built without a gate refuses (`no_shop_gate`) — never sends.

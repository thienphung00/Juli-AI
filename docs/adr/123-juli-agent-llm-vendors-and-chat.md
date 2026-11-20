# ADR-123: The Juli tab's analytics agent — Anthropic and TypeSafe through the gate, read-only analysis, cards only through the existing flow

**Status:** Proposed (batch-1120-juli-tab; owner-approved design: grills of 2026-11-19)
**Date:** 2026-11-20
**Amends:** [ADR-116](116-client-data-lanes-consent-and-model-split.md) §5 (the one door to an LLM).
**Related:** ADR-068/069/070 (agent boundary, tools, sanitisation), ADR-121 (Shopee recommendation engine),
grill logs `jev-router-grill-2026-11-19.md` (J1–J11, P1b–P1d) and `juli-tab-ui-grill-2026-11-19.md` (U1–U12).

## Context

The Juli tab answers a seller's question (or one of 5 templates) about the shop's numbers: a data answer, an
explanation, or a draft card the seller may send into Đề xuất. ADR-116 §5 made `services/llm_gate` the only way
shop data reaches an LLM, and only OpenAI. The agent uses Claude Haiku 5.5 (parsing the Vietnamese question,
writing the explanation) and TypeSafe's Jev System One model (routing decisions, product choice, card choice,
overlap check).

## Decision

1. **Two new vendor doors in `services/llm_gate`, same guarantees as OpenAI** (`vendors.py`):
   `https://api.anthropic.com/v1/messages` (plain and streamed) and `https://api.typesafe.ai/v1/systemone`, plain
   `httpx`, no vendor SDK. Purposes are bound to a vendor: `agent_chat_parse`, `agent_chat_write` → Anthropic;
   `agent_chat_route` → TypeSafe; any other pairing is refused. Checks before any HTTP: purpose, endpoint pair,
   shape, consent `llm_processing`, key. Refusals: `unknown_purpose`, `endpoint_not_allowed`, `payload_shape`,
   `consent_llm_processing`, `unconfigured` (missing `ANTHROPIC_API_KEY` / `TYPESAFE_API_KEY`).
   - Messages shape: `model, system, messages, max_tokens, stream (set by the gate), tools, tool_choice,
     stop_sequences, output_config, thinking`; roles user/assistant; blocks text, tool_use, tool_result; no images
     or documents; `temperature` and any other key refused.
   - System One shape: exactly `{model, state, questions}`; questions `choice` or `noul` only; no assets.
   - Minimisation as for OpenAI (deidentify, forbidden keys at any depth, shop ids → `[shop]`, image URLs hidden),
     applied to system text, messages, tool inputs/results and the System One state, instructions and criteria.
   - One `llm_call_log` row per attempt; `project` = `anthropic` / `typesafe` (OpenAI rows keep
     `juli-client-data`, so its monthly reconciliation is unchanged); a stream logs once, `sent` only on
     `message_stop`. Send failures raise `GateCallFailed` with no response body copied.
   - The CI rule allows `api.anthropic.com` and `api.typesafe.ai` only inside `services/llm_gate`.
2. **Jev reads English JSON produced by the backend only** (intent fields, option lists, candidate product names,
   card fields); never tool results or numbers. The LLM only parses the question and writes the explanation; every
   endpoint call, SQL query, number and card value is computed by code or Juli's recommendation engine.
3. **Analysis is read-only.** Chains and data answers run on read-only sessions (`default_transaction_read_only`),
   through the analytics service, the metric registry and named queries bound to the shop server-side; nothing in
   the agent imports `shopee_analytics/materialize.py` or a write tool.
4. **Cards only through the existing flow.** A draft's values come from the recommendation engine (the kind's
   generator fitted to the floors, `versions.build_versions`, `result_store.compute_many`), gated G1–G5 (stop
   reason, WIRING, engine values, overlap by code then Jev, evidence). "Gửi vào Đề xuất" creates the card through the
   Tự tạo path with origin `agent`; approval, execution and measurement stay as they are.
5. **Output safety.** Every explanation passes an alignment check (accepted cards named, no other action
   recommended) and a sanitiser (no raw keys, ids, JSON, paths, internal words), one rewrite then a code template.
6. **Storage and access.** Migration 137 adds tenant tables for conversations, messages, routing decisions and card
   drafts (shared per shop, kept). Routes `/v1/demo/juli/*` sit behind the capability gate and `JULI_AGENT_ENABLED`
   (off by default); the reviewer allowlist includes them.

## Consequences

- Two more sub-processors carry shop text (owner handles the client side).
- A new chain or card kind is added as code + an eval question, never by prompting.
- When TikTok's analytics routes open (P101 W3), the same agent answers TikTok shops through `can()`.

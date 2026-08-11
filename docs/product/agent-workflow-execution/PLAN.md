# Agent Workflow Execution — Implementation Plan

Status: **approved 2026-08-11**. Sequential, minimal-first implementation; one workflow end-to-end (Optimize Product, `optimize_product_2`) before rollout to the remaining 10. Update the progress tracker as phases complete.

## Locked decisions

- **D1 — Real LLM agent loop, production-grade.** Real provider calls, real user data, real external APIs. The 3 no-LLM contract tests (`tests/unit/test_rules_copy_layer_contract.py:45-51`, `tests/unit/test_recommendations.py:329-338`, `apps/dashboard/src/__tests__/test_listing_rules_engine.test.ts:159`) are lifted deliberately; ADR-012/021/055 amended via a new ADR.
- **D2 — SSE transport** with a typed event protocol (`workflow.started/status`, `assistant.text`, `tool.started/completed`, `workflow.approval_required`, `workflow.completed/failed`), event IDs + ordering.
- **D3 — Celery worker + event relay.** Loop runs in a Celery task; events appended to a sequence-numbered event store and published on Redis pub/sub; thin SSE endpoint subscribes + replays from `Last-Event-ID`. Loop emits through an **EventSink interface** (in-process sink for tests/dev). Preserves the "HTTP handlers never execute inline" invariant.
- **D4 — Sequential, minimal-first, one workflow end-to-end.** Each phase ships only the minimal specs needed to unblock the next; revisit when required. Remaining 10 workflows onboard via Phase 13 (edge cases).
- **D5 — Conversation storage.** Recent conversation (messages, tool calls, current workflow state) in **Redis**; permanent history (conversations, messages, tool calls, workflow runs) in **Supabase/Postgres**.
- **D6 — Demo UI polish** for Optimize Product is an explicit phase.

## Progress tracker (implementation order is top-to-bottom, sequential)

| # | Phase (draft-checklist numbering kept) | Status | Gate passed |
|---|---|---|---|
| 1 | P0 — Execution model & lifecycle (0.1 + 0.2) | 🟨 grilled 2026-08-11 — [ADR-068](../../adr/068-agent-workflow-execution-boundary.md) drafted (Proposed) | ⬜ gate = ADR landed on main |
| 2 | P3+P4 — Tool registry + tool schemas (minimal) | 🟨 design grilled 2026-08-11 — [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md) drafted; implementation pending | ⬜ |
| 3 | P5 — TikTok sanitization (product surface only) | ⬜ | ⬜ |
| 4 | P11 — Model abstraction (minimal LLM service) | ⬜ | ⬜ |
| 5 | P12 — Prompt architecture (system + Optimize Product) | ⬜ | ⬜ |
| 6 | P1 — Agent execution loop (blocks + runner) | ⬜ | ⬜ |
| 7 | P-CS — Conversation & state storage (NEW) | ⬜ | ⬜ |
| 8 | P8 — Streaming (SSE + Celery relay) | ⬜ | ⬜ |
| 9 | P7 — Structured output contract | ⬜ | ⬜ |
| 10 | P9+P14 — Approval, safety & security prerequisites | ⬜ | ⬜ |
| 11 | P-UI — Demo UI polish + wiring (Optimize Product) (NEW) | ⬜ | ⬜ |
| 12 | P10 — Observability baseline | ⬜ | ⬜ |
| 13 | P15 — E2E prototype complete (Optimize Product) | ⬜ | ⬜ |
| 14 | P13 — Edge cases + rollout to remaining 10 workflows | ⬜ | ⬜ |
| 15 | P6 — Documentation retrieval tool (deferred, optional) | ⬜ | ⬜ |

## Phases — minimal specs + gate to proceed

### 1. P0 — Execution model & lifecycle *(grill-with-docs target — first)*
Minimal specs:
- New ADR: agent workflow execution boundary (Client → Juli Server → LLM; LLM never touches TikTok/internal services), read/recommend/mutate classification, which operations require confirmation.
- Unified `WorkflowRunStatus` enum + documented mapping to the 4 existing vocabularies (`ExecutionStatus`, `ActionCard.status`, `DemoExecutionState`, frontend `ExecutionLifecycleStatus`). Includes failure/cancelled/timeout/waiting_approval.
- Decision recorded: lift the 3 no-LLM contract tests; replacement boundary tests specified.

Gate: ADR merged; enum + mapping reviewed; every later phase can name its states without inventing new ones.

### 2. P3+P4 — Tool registry + schemas (minimal) — *design settled in [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md)*
Minimal specs (per ADR-069):
- New `services/agent/tools/` module: `ToolSpec` dataclass (name, description, Pydantic input/output models → `model_json_schema()`, read|write, auto|confirm, timeout), explicit registration, domain-grouped handlers. Legacy `runner.py` untouched.
- **Decision-point granularity** — 6 Optimize Product tools: `get_product_information`, `get_seo_keywords` (steps 2+3 bundled), `upload_product_image`, `update_product_listing` (CONFIRM), `update_product_price` (CONFIRM), `check_product_status` (webhook #5 closes post-run via `WorkflowOutcomeRecord`).
- Writes execute in-run with a `ToolExecution` row per write (shared persistence helper with the legacy dispatcher); outbound `RateLimiter` attaches at the tool executor. Revisit trigger documented for nested-enqueue upgrade at heavier write volume.
- Allowlists live in playbooks; import-time contract tests cross-validate playbook↔registry both directions. Also flag (don't yet fix) the 4 unregistered legacy tools (`fulfillment.process_order`, `returns.prevent_*`).

Gate: LLM-consumable JSON schemas render for the 6-tool Optimize Product set; playbook↔registry contract test green.

### 3. P5 — Sanitization (product surface only)
Minimal specs:
- Agent-safe serializer for product + SEO tool results (business semantics; no endpoints/vendor IDs/status codes), reusing `integrations/tiktok/mapping.py` + `schemas.py`.
- TikTok error taxonomy → human-readable tool errors.

Gate: golden-file test — raw sandbox product response in, agent-safe result out, zero banned identifiers (server-side check mirroring `SELLER_COPY_BANNED_PATTERNS`).

### 4. P11 — Model abstraction (minimal)
Minimal specs:
- `LLMService` (messages, system, tools, usage) with one provider (Anthropic) + config surface (model, max_tokens, temperature, API key via ADR-030 pattern). No fallback chains yet.
- Replace/retire the dead `LlmGenerator` seam (`ai/recommendations/engine.py:49`); lift no-LLM tests per P0 decision.

Gate: one real tool-calling round-trip against the provider passes an integration test (recorded-replay for CI).

### 5. P12 — Prompt architecture (minimal)
Minimal specs:
- `services/agent/prompts/`: versioned system prompt + Optimize Product workflow prompt; language/tone from `dictionary.md`; prohibited-behavior + output-contract sections; untrusted-content wrapping convention for product data.

Gate: prompt review against seller-copy rules; snapshot test pins version 1.

### 6. P1 — Agent execution loop (minimal)
Minimal specs:
- Block types (TextBlock/ToolCallBlock/ToolCallResult/FinalResponse); loop: context → LLM → validate tool vs `ToolSpec` → execute via `run_tool_async` → sanitize → inject → repeat; iteration cap + wall-clock timeout + cancellation flag; `EventSink` interface (in-process sink only at this phase).

Gate: unit suite with fake `LLMService` covers happy path, iteration cap, timeout, unauthorized tool, malformed tool params; real-provider smoke run completes for Optimize Product with read-only tools.

### 7. P-CS — Conversation & state storage
Minimal specs:
- **Redis (hot)**: recent conversation window (messages, tool calls) + current workflow run state, keyed by run/conversation ID, with TTL; the loop reads/writes this — process-restart-safe.
- **Supabase/Postgres (permanent)**: migrations for `conversations`, `messages`, `tool_calls`, `workflow_runs`; append-on-event writes from the loop; JSON/JSONB payloads.
- Clear write path: Redis is the working set, Postgres is the durable record (write-through on each loop step).

Gate: kill-and-resume test — restart mid-run, state reconstructed from Redis; full history queryable from Postgres after completion.

### 8. P8 — Streaming (minimal)
Minimal specs:
- Typed SSE event protocol with event IDs/ordering, shared via `packages/contracts`.
- Celery task `run_agent_workflow` (dedicated queue; real Redis broker — currently `memory://` in `workers/celery_app.py`); Redis pub/sub `EventSink`; SSE endpoint with Last-Event-ID replay from P-CS storage + heartbeats; cancel endpoint.

Gate: browser sees live events for a real run; reconnect mid-run replays without gaps/duplicates; cancellation stops the loop.

### 9. P7 — Structured output contract
Minimal specs:
- Optimize Product output schema (summary/findings/recommendations/actions/requires_confirmation) in `packages/contracts` + Pydantic; validate final LLM output; one repair retry; rules-template fallback (extend `CopySource` literal at `services/scoring/types.py:132`).

Gate: malformed-output test falls back cleanly; frontend can type against the schema.

### 10. P9+P14 — Approval, safety & security prerequisites
Minimal specs:
- Server-side approval gate: run created only from an `ActionCard` the user approved (closes the unverified `approval_id` gap in `api/routes/executions.py`); CONFIRM-class write tools pause with `workflow.approval_required` + resume endpoint.
- Fail-closed JWT startup assertion (empty `SUPABASE_JWT_SECRET` must crash, not bypass — `core/security/dependencies.py:27`) — **required before real user data flows**.
- Prompt-injection posture: product content tagged untrusted; server-side output guard on.

Gate: unauthorized/unapproved run attempts rejected in tests; write tool blocked without confirmation; auth assertion verified.

### 11. P-UI — Demo UI polish + wiring, Optimize Product only
Minimal specs:
- Fix `fetchRecommendations()` path bug (`/v1/demo/recommendations` → `/v1/demo/decisions` in `apps/demo/src/lib/recommendations.ts`); surface failures instead of silent fixture fallback.
- Approve → create run → `EventSource` consumption; execution view rendered from the event protocol (agent text, tool progress, approval pause, final structured output); replace localStorage `startExecution` (`apps/demo/src/lib/executions.ts:163-196`) for this workflow; polish per `ui-ux-design` skill; update `apps/demo/MODULE.md` invariant.

Gate: a user can run Optimize Product end-to-end in the Demo page against the real backend and watch it stream.

### 12. P10 — Observability baseline
Minimal specs:
- dictConfig JSON logging + request-ID middleware; per-run rollup (tokens, cost, latency, tool calls) from P-CS tables; log redaction (no tokens/PII).

Gate: one run produces a complete, queryable run tree; logs actually emit.

### 13. P15 — E2E prototype complete
Minimal specs: hardening pass over the full Optimize Product path (frontend + backend); extract reusable per-workflow config template (prompt + allowlist + output schema).

Gate: demo-able, repeatable, documented run; template extraction reviewed.

### 14. P13 — Edge cases + rollout to remaining 10 workflows
Minimal specs: work the edge-case matrix (API down/timeouts, malformed LLM output, unavailable tool, rate limits, cancellation, disconnects, duplicates, partial completion) against Optimize Product; then onboard each remaining workflow via the template, registering the 4 missing tool handlers as their workflows land.

Gate: edge-case matrix green; each workflow onboarded with its own prompt/allowlist/schema + tests.

### 15. P6 — Documentation retrieval (deferred)
Optional `search_juli_documentation` tool over curated docs (ADR-051 catalog pattern, not embeddings). Only if agent answers need it.

## Target architecture — swimlane sequence diagram

Four lanes; the LLM never touches TikTok or internal services — every tool call crosses the Juli Server execution boundary. `═══>` arrows = streamed SSE events; `───>` = request/response.

```
┌─────────────┐   ┌──────────────────────────────┐   ┌─────────────┐   ┌───────────────────────────┐
│   Client    │   │         Juli Server          │   │ LLM Server  │   │ External/Internal Tools   │
│  apps/demo  │   │  FastAPI + workflow engine   │   │ (provider)  │   │ TikTok API · Analytics ·  │
│  Demo page  │   │  (orchestrator & boundary)   │   │             │   │ Scoring/Decision Layer    │
└──────┬──────┘   └──────────────┬───────────────┘   └──────┬──────┘   └─────────────┬─────────────┘
       │                         │                          │                        │
       │ Approve workflow        │                          │                        │
       │ POST /v1/demo/decisions/{id}/approve               │                        │
       │────────────────────────>│                          │                        │
       │                         │ verify ActionCard        │                        │
       │                         │ status + tenant scope    │                        │
       │                         │ (approval gate)          │                        │
       │   SSE: workflow.started │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ system + workflow prompt │                        │
       │                         │ + tool schemas (registry)│                        │
       │                         │─────────────────────────>│                        │
       │                         │<─────────────────────────│                        │
       │                         │ AssistantMessage:        │                        │
       │                         │  TextBlock               │                        │
       │                         │  ToolCallBlock           │                        │
       │  SSE: assistant.text    │                          │                        │
       │  SSE: tool.started      │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ validate tool + params   │                        │
       │                         │ (allowlist, guards,      │                        │
       │                         │  read/write policy)      │                        │
       │                         │ run_tool_async(name, payload)                     │
       │                         │──────────────────────────────────────────────────>│
       │                         │              execute via guarded client           │
       │                         │              (sandbox write / prod read)          │
       │                         │<──────────────────────────────────────────────────│
       │                         │ raw result → normalize   │                        │
       │                         │ → agent-safe sanitize    │                        │
       │                         │ = ToolCallResult         │                        │
       │  SSE: tool.completed    │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ ToolCallResult appended  │                        │
       │                         │ to conversation          │                        │
       │                         │─────────────────────────>│                        │
       │                         │<─────────────────────────│                        │
       │                         │  ╭─ loop until FinalResponse or iteration cap ─╮  │
       │                         │                          │                        │
       │                         │ Final TextBlock +        │                        │
       │                         │ structured output,       │                        │
       │                         │ validated vs workflow    │                        │
       │                         │ output schema            │                        │
       │  SSE: workflow.completed│                          │                        │
       │<════════════════════════│                          │                        │
       │ render summary,         │                          │                        │
       │ recommendations,        │                          │                        │
       │ next actions            │                          │                        │
```

Boundary rules:
- `LLM → ToolCallBlock → Juli Server → validate → execute → sanitize → ToolCallResult → LLM` — the LLM only ever sees business semantics; TikTok endpoints, credentials, and raw responses stay server-side.
- Approval gate sits before the loop; CONFIRM-class write tools pause the loop with `workflow.approval_required` inside it.

## Codebase verification findings (2026-08-11 baseline)

Condensed from four exploration reports; full evidence lives in the session plan.

| Draft-checklist phase | Verdict | Key evidence |
|---|---|---|
| 0.1 Execution model | PARTIAL | Read/write boundary is strong (`integrations/tiktok/capabilities.py`, `guards.py`, `factories.py`, `services/execution/sandbox_guard.py`); no per-tool confirmation classification. |
| 0.2 Lifecycle | MISSING | Four disjoint vocabularies (`ExecutionStatus`, `ActionCard.status`, `DemoExecutionState`, frontend lifecycle); no retry/timeout/cancellation anywhere. |
| 1 Engine | PARTIAL | Celery dispatch + tool registry exist (`services/execution/`); orchestration hard-coded per tool handler; no agent loop. |
| 2 The 11 workflows | EXISTS (catalog) | `WORKFLOW_TOOL_CATALOG` (`tool_routing.py:14-42`) + `WORKFLOW_DISPLAY_NAMES` (`kpi_catalog.py:82-94`) + `docs/product/execution_layer.md`; 4 keys route to unregistered tools. |
| 3/4 Tool registry & schemas | PARTIAL/MISSING | name→callable only; no metadata/schemas; handlers take `dict[str, Any]`. |
| 5 Sanitization | PARTIAL | `mapping.py` normalizers + Pydantic DTOs + `SELLER_COPY_BANNED_PATTERNS`; no agent-safe serializer. |
| 6 Docs retrieval | PARTIAL | ADR-051 catalog+grep for dev agents; embedding RAG rejected; nothing product-runtime. |
| 7 Structured output | MISSING (LLM) | No block types/validation/repair; `CopySource = Literal["rules"]` is the designed switch. |
| 8 Streaming | MISSING | No SSE/WS/polling anywhere; demo approve returns full narrative synchronously. |
| 9 Safety | PARTIAL | Transport guards excellent; `POST /v1/executions` trusts caller-supplied `approval_id` unverified. |
| 10 Observability | MISSING | No logging config, request IDs, metrics; ADR-039/061 designed, unimplemented. |
| 11 Model abstraction | MISSING | No LLM SDK; dead `LlmGenerator` seam. |
| 12 Prompts | MISSING | 3 inline f-strings; deterministic `copy_layer.py` templates are the stand-in. |
| 13 Errors | PARTIAL | Good TikTok client retry taxonomy; no Celery retry/timeout/cancellation/global handler. |
| 14 Security | PARTIAL + 2 live vulns | JWT fails open (`core/security/dependencies.py:27`); RLS non-functional; prompt-injection defense required once LLM lands. |
| 15 E2E (SEO) | PARTIAL | `optimize_product_2` chain exists using TikTok's own SEO endpoints; no agent loop. |

Demo page baseline: all-11 plan/review/execution modules exist client-side but execution is a localStorage mock; `fetchRecommendations()` targets nonexistent `/v1/demo/recommendations` and silently falls back to fixtures; the backend demo surface is unconsumed.

## Verification strategy

- Unit: loop runner with fake `LLMService` (scripted tool-call sequences) — iteration cap, timeout, cancellation, malformed-output repair, unauthorized-tool rejection.
- Contract: registry↔catalog cross-validation; event-schema snapshot tests in `packages/contracts`; new LLM-boundary tests replacing the lifted no-LLM tests.
- Integration: sandbox-write guarded run of `optimize_product_2` (`tests/integration/tiktok_sandbox.py` helpers); SSE reconnect/replay test.
- E2E: Demo page approve → live stream → rendered structured output against the real provider (manual, then recorded-replay fixture).

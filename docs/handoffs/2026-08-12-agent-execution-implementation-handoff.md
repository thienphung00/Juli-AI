# Agent Workflow Execution — implementation handoff (Architect → Meta phase owners)

**Date:** 2026-08-12 · **Author:** Architect (Fable) · **Audience:** one Meta Agent (Opus) per phase, each in its own session.
**Design authority (do not restate, do not re-litigate):** ADR-068…077 + `docs/product/agent-workflow-execution/PLAN.md` (tracker + per-phase settled specs) + `PUI-DESIGN.md` + CONTEXT.md glossary. This file owns *orchestration only*: order, isolation, pinned interfaces, session bootstrap.

## 1. Session summary

All design grills for the Optimize Product (`optimize_product_2`) end-to-end agent path are complete and merged: ADR-068–077 (PRs #962–#975). No code exists yet under `services/agent/`. This handoff decomposes the implementation into 9 phase assignments across 4 parallel waves, each executable by an independent Meta session.

## 2. How to use this handoff (Meta session bootstrap)

You are a Meta Agent (Opus) owning exactly ONE phase block from §6. In order:
1. Read this file, then your phase's ADR(s), then your phase's section in `docs/product/agent-workflow-execution/PLAN.md`, then the CONTEXT.md terms your ADR introduces. Read nothing else up front.
2. Verify your **Depends on** rows are merged to `main` (check the PLAN.md tracker + `git log`). If a dependency is unmerged, STOP and report — do not start against an unmerged interface.
3. Run `focus`, then `to-prd` → `to-issues` for your phase scope only. Issues must be sized for Sonnet executors.
4. Orchestrate the Executor/Review loop per repo policy (`meta_prepare_executor.py --issue <N>` gate; `readyForExecutor: true` or halt). Executor/Reviewer = Sonnet; escalate a single unusually hard issue to Opus only with the user's explicit approval first.
5. Land via PR → your wave's integration branch → `main` (ADR-052 wave pattern). Never push `main`. The **user merges every PR** — request merges, never run `gh pr merge`.
6. On completion: flip your PLAN.md tracker row (🟨 design grilled → ✅ implemented, gate ✅), append blockers/decisions to your phase section, and write `docs/handoffs/issue-<N>-*.md` checkpoints per the shared checkpoint doc.

## 3. Standing decisions (settled — re-opening any of these is a defect)

- Base model **GPT-5.4 nano** via OpenAI Responses API, stateless (ADR-071). LLM never sees TikTok endpoints/credentials/raw payloads.
- Scoring owns WHAT, LLM owns HOW (ADR-068). Writes: sandbox shop only for now; production write is target state behind the ADR-068 amendment's unlock list.
- One workflow only — `optimize_product_2`. The other 10 arrive in P13 (not in this handoff).
- P-CS (conversation storage) and P7 (structured output) are **user-deferred**: build against their seams (run-state JSONB blob; prose final response). Do not implement them.
- Termination numbers (ADR-073): max_iterations 6 (+1 extension ×2 → hard 8), wall clock 300s running-time, approval expiry 4h, checkpoint cancellation never interrupts an in-flight write.
- Demo entry: Supabase **anonymous sign-in** for "Dùng thử Demo"; Google → Supabase Auth → TikTok OAuth for merchants (ADR-076). Demo replay must be indistinguishable from live.
- Vietnamese copy from `dictionary.md`; EN prompt instructions + VI exemplars (ADR-072).
- Executor/scout sub-agents run Sonnet/Haiku, never Opus/Fable, except the approved-escalation path above.

## 4. Recommended parallel implementation order

```
WAVE 1 (3 parallel)   W1-A  P3+P4  Tool registry            ADR-069
                      W1-B  P11    LLM service              ADR-071
                      W1-C  P5     Sanitizer                ADR-070
WAVE 2 (2 parallel)   W2-A  P12    Prompt + Playbook        ADR-072   ← needs W1-A merged
                      W2-B  P-IM   Impact readings          ADR-077   ← independent of agent stack
WAVE 3 (2 parallel)   W3-A  P1     WorkflowRunner           ADR-073   ← needs all W1 + W2-A
                      W3-B  P8     Events/relay/SSE         ADR-074   ← contracts first; live gate after W3-A
WAVE 4 (2 parallel)   W4-A  P9+P14 Approval + security      ADR-075   ← needs W3-A, W3-B
                      W4-B  P-UI   Demo experience          ADR-076   ← starts on W3-B fixtures; wires after W4-A
FINAL (serial)        Cross-phase verification checkpoint (§8), then P10/P15/P13 return to the Architect.
```

Rationale: W1 modules are mutually disjoint and dependency-free. P12 cross-validates against the registry at import time, so it follows W1-A. P-IM touches only analytics/outcome code — it parallelizes with anything (its *final* gate item, one real backdated reading, waits for W3-A). P8's deliverable splits cleanly: event contracts + relay + SSE endpoint build against the pinned EventSink protocol in parallel with the runner; only its live browser gate serializes after W3-A. P-UI develops the reducer + staged view against P8's golden fixtures before endpoints are final.

## 5. Pinned cross-phase interfaces (the parallelism contract)

These shapes are frozen by ADR; build against them, never renegotiate them in an executor loop. Full definitions live in the cited ADR — flag any mismatch to the Architect instead of adapting silently.

| # | Interface | Producer → Consumer | Authority |
|---|---|---|---|
| I1 | `LLMService.complete(messages, system, tools, config) → AssistantTurn` (neutral blocks; `assistant.text.delta` reserved) | P11 → P1 | ADR-071 |
| I2 | `ToolSpec` (name, schemas, read/write, AUTO/CONFIRM/NEVER, timeout) + registry render to LLM-consumable JSON | P3+P4 → P1, P12 | ADR-069 |
| I3 | Sanitized result envelope (`source: juli|vendor|seller`, caps + `{truncated, omitted_count}`) and error envelope `{error: {category, message, retryable}}` | P5 → P1 | ADR-070 |
| I4 | Frozen `Playbook` dataclass + `compose(workflow_key, version)`; `prompt_version`/`prompt_sha256` stamped on runs | P12 → P1, P-IM (A/B seam) | ADR-072 |
| I5 | `EventSink` protocol; event envelope `{workflow_run_id, sequence_number, event_type, timestamp, payload, v:1}`; 8-event union; runner owns sequence numbers | P1 emits → P8 persists/relays → P-UI consumes | ADR-073/074 |
| I6 | `workflow_runs.state` JSONB blob + total `stop_reason` → `WorkflowRunStatus` mapping (incl. `worker_lost`) | P1 → P8, P9+P14, P-IM | ADR-073 |
| I7 | `ToolExecution` idempotency ledger (`workflow_run_id + tool_call_id + operation`, claim-then-execute, stored sanitized result) | P1 → P-IM (T anchor) | ADR-069/073 |
| I8 | Decision request: 1..N options, per-option `params_sha` consent binding, single-use `run_confirmations` row; approve-IS-run-creation | P9+P14 ↔ P1 (pause/resume), → P-UI | ADR-075 |
| I9 | `impact_readings` table, unique `(tool_execution_id, metric, kind)` | P-IM → future P10 | ADR-077 |

## 6. Phase handoffs

Common to every block: worktree `git worktree add .worktrees/<wt> -b <branch> origin/main`; preflight before edits; conventional commits; PR → wave branch; PLAN.md tracker update rides the final PR of the phase.

### W1-A · P3+P4 — Tool registry (`ADR-069`)
- **Scope:** `ToolSpec` + registry module `services/agent/tools/`, the 6 Optimize Product tools (names/granularity per ADR-069), wrapping existing `services/execution/runner.py` handlers; import-time cross-validation vs `WORKFLOW_TOOL_CATALOG` (flag, don't fix, the 4 unregistered legacy tools).
- **Depends on:** nothing. **Write paths:** `services/agent/tools/`, `tests/unit/agent/tools/`. **Worktree:** `agent-tools` / `feature/agent-tool-registry`.
- **Gate:** LLM-consumable JSON schemas render for all 6 tools; registry↔catalog contract test green; AUTO/CONFIRM/NEVER + read/write class on every spec.
- **Trap:** decision-point granularity — do not collapse to one mega-tool or explode to per-endpoint tools; ADR-069's list is exact.

### W1-B · P11 — LLM service (`ADR-071`)
- **Scope:** `LLMService` (I1) in `services/agent/llm/`; OpenAI Responses adapter, stateless; `LLMConfig` precedence playbook > env > defaults; usage/cost capture; fail-closed key assertion via `require_env`; fake `LLMService` for downstream suites; recorded-replay harness + `live` pytest marker + AST containment test (no OpenAI SDK import outside the adapter).
- **Depends on:** nothing. **Write paths:** `services/agent/llm/`, `tests/unit/agent/llm/`, `tests/integration/` (live-marked). **Worktree:** `agent-llm` / `feature/agent-llm-service`.
- **Gate:** one real GPT-5.4 nano tool-calling round-trip green live; same test green in CI via recorded replay; fake service exported.
- **Trap:** the three no-LLM contract tests were deliberately lifted by ADR-068 — replace with the boundary tests ADR-071 names; do not "fix" them back.

### W1-C · P5 — Sanitizer (`ADR-070`)
- **Scope:** agent-safe serializer for product/SEO tool results (context-bound IDs — no ID params, server injects from run context; machine values; hard caps + truncation markers), error translation, source-role envelopes (I3); banned-pattern list extracted to `packages/contracts/seller-copy-banned-patterns.json` consumed by both TS and Python with a dual-dialect compile test; two fail-closed chokepoints (tool output → conversation; agent output → stream/persist).
- **Depends on:** nothing (develop against recorded sandbox fixtures; integrate with W1-A at wave close). **Write paths:** `services/agent/sanitize/`, `packages/contracts/` (json + TS re-export), tests. **Worktree:** `agent-sanitize` / `feature/agent-sanitizer`.
- **Gate:** golden-file test — raw sandbox product response in → agent-safe result out, zero banned identifiers; caps enforced with signaled truncation; error envelope from curated retryable codes.
- **Trap:** shaping is deterministic — no LLM-side summarization; goldens must be reproducible.

### W2-A · P12 — Prompt + Playbook (`ADR-072`)
- **Scope:** monolithic versioned prompt `services/agent/prompts/optimize_product/v1.md` (8 sections, EN instructions + VI exemplars + mini-glossary from `dictionary.md`, 3 source-role rules, 7 prohibitions); typed frozen `Playbook` at `services/agent/playbooks/optimize_product.py` (incl. ADR-073's `TerminationPolicy` values); deterministic `compose()` (I4).
- **Depends on:** W1-A merged (playbook↔registry cross-validation). **Write paths:** `services/agent/prompts/`, `services/agent/playbooks/`, tests. **Worktree:** `agent-prompts` / `feature/agent-prompt-playbook`.
- **Gate:** 4 import-time tests — snapshot (immutability), ≤3,000-token budget, playbook↔registry consistency, banned-pattern check on prompt text.
- **Trap:** versions are immutable — edits mean `v2.md`, never mutating `v1.md`; `prompt_sha256` is the future A/B treatment label.

### W2-B · P-IM — Impact readings (`ADR-077`)
- **Scope:** `impact_readings` table + migration (I9); ratio-form DiD compute (funnel-first metric map, K=5 correlated-sibling controls, confidence tiers/suppression exactly per ADR-077); daily impact-reader beat task scheduled after `analytics-backfill-topup`; fill legacy outcome envelope; `WORKFLOW_OUTCOME_SUCCESS_CRITERIA` gains `optimize_product_2`.
- **Depends on:** nothing in the agent stack (reads `analytics_performance_intervals` + `ToolExecution` schema; use synthetic T fixtures until W3-A). **Write paths:** `services/impact/` (new), `workers/tasks/`, `models/models.py` (one table) + migration, outcome_tracking touch-ups, tests. **Worktree:** `agent-impact` / `feature/agent-impact-readings`.
- **Gate:** ADR-077 §6 suite (synthetic-uplift recovery, shock cancellation, placebo battery, suppression matrix, reader idempotency) green on real-shaped fixtures; the one real backdated-run reading waits for W3-A and lands in §8's checkpoint.
- **Trap (recorded in PLAN.md flagged gaps):** daily analytics topup covers only the reference shop — assert `suppressed` (not crash, not fabricate) on missing daily rows.

### W3-A · P1 — WorkflowRunner (`ADR-073`)
- **Scope:** `WorkflowRunner` + 4 injected protocols (LLMService, ToolExecutor, EventSink, ConversationStore stand-in); run-state JSONB serialization; total stop_reason→status mapping (I6); claim-then-execute idempotency on `ToolExecution` (I7) with verify-then-decide crash reconciliation; basis field-hash concurrency (compare-before-write, one bounded revalidation, partial unique index: one active run per shop+product); checkpoint cancellation; termination policy from Playbook.
- **Depends on:** W1-A/B/C + W2-A all merged. **Write paths:** `services/agent/runner/`, `models/models.py` (workflow_runs/tool_executions columns) + migration, tests. **Worktree:** `agent-runner` / `feature/agent-workflow-runner`.
- **Gate:** fake-LLMService unit suite (happy path, iteration cap, timeout, unauthorized tool, malformed params, idempotent retry, concurrency conflict, cancellation at checkpoint, every stop_reason reachable); then one real GPT-5.4 nano read-only run to `final_response` + one production write on the **sandbox shop**.
- **Trap:** in-flight writes are never interrupted — cancellation and timeout both resolve at checkpoints only; non-verifiable crash states fail closed.

### W3-B · P8 — Events, relay, SSE (`ADR-074`)
- **Scope:** `workflow_run_events` table (unique `(run_id, seq)`) + Pydantic event union + TS mirror + golden fixtures in both languages (I5); `PersistingEventSink` (insert-commit-then-publish, Redis pub/sub); SSE endpoint `GET /v1/demo/runs/{id}/events` (subscribe-before-replay, dedupe, 15s heartbeats, terminal close, 2s Postgres-poll fallback); Celery `agent_runs` queue on real Redis + fail-closed broker assertion; acks_late + blob-resume retry; 5-min reaper (incl. `worker_lost`, 4h approval expiry); `POST .../cancel` (202, idempotent); fetch-streaming client helper.
- **Depends on:** interfaces only (I5/I6 pinned) — build in parallel with W3-A against a scripted fake runner; live gate needs W3-A merged. **Write paths:** `models/models.py` (events table) + migration, `services/agent/events/`, `api/routes/`, `workers/`, `packages/contracts/src/`, `apps/demo/src/lib/` (client helper only), tests. **Worktree:** `agent-streaming` / `feature/agent-event-streaming`.
- **Gate (2 stages):** contracts stage — golden fixtures byte-equal across Python/TS, replay-after-seq-N test, reaper unit tests; live stage (§8) — browser sees a real run stream, reconnect mid-run replays without gap/dupe, cancel stops the loop.
- **Trap:** the Celery broker defaults to `memory://` today — the boot assertion must make agent paths refuse to start on it.

### W4-A · P9+P14 — Approval gate + security (`ADR-075`)
- **Scope:** approve-IS-run-creation (atomic; raced double-approve → exactly one run); decision requests + `run_confirmations` (I8, single-use, params_sha consent binding, decline-as-conversation); reserved `POST .../confirmations/{tool_call_id}` endpoint made real; 6-check `assert_agent_runtime_config()` boot assertion; per-shop rate limits (runs 5/hr burst 2, confirmations 30/hr, 10 SSE streams, cancel unthrottled; 429 + security event); invisible-Unicode/bidi stripping + adversarial injection fixture suite; harden legacy `/v1/executions` separately.
- **Depends on:** W3-A + W3-B merged. **Write paths:** `api/routes/`, `core/security/`, `services/agent/` (confirmation resume), `models/models.py` (`run_confirmations`) + migration, tests. **Worktree:** `agent-approval` / `feature/agent-approval-security`.
- **Gate:** unapproved/double/expired approval attempts rejected in tests with exactly-one-run invariant; option consent binds to params hash (mutated params → rejected); limits return 429; injection suite green; boot assertion crashes on each missing config.
- **Trap:** JWT fail-closed and /docs gating already landed (#902+) — verify, don't rebuild. RLS repair stays on the production-write unlock list, out of scope here.

### W4-B · P-UI — Demo experience (`ADR-076` + `PUI-DESIGN.md`)
- **Scope:** dual entry (anonymous sign-in demo session pinned to reference shop; Google→Supabase→TikTok connect screen, live merchant OAuth flagged follow-up); `useRunStream` + pure event→stage reducer; staged run view (one stage at a time, top stepper, back-to-frozen/forward-to-live); consent-grade option picker; In-Progress run ledger (honest terminal states); recorded-replay golden scenarios (real sandbox run event logs, recorded-delta pacing, rebased timestamps, one continuation per decision option); delete the localStorage `startExecution` mock for this workflow; motion + VI copy tables per PUI-DESIGN.md.
- **Depends on:** W3-B contracts stage (fixtures) to start; W4-A endpoints to finish wiring. **Write paths:** `apps/demo/` only (+ `packages/contracts` consumption). **Worktree:** `agent-demo-ui` / `feature/agent-demo-experience`.
- **Gate:** reducer replay ≡ live on golden fixtures in CI; a visitor completes Optimize Product end-to-end through the staged view against the real backend; no replay tells in demo mode; `apps/demo/MODULE.md` invariant updated.
- **Trap:** design authority is PUI-DESIGN.md, which deliberately overrides older demo design-language files for this workflow's surfaces — do not "reconcile" back.

## 7. Global execution rules (every Meta, every Executor)

- **Git:** repo policy verbatim (CLAUDE.md/git-baseline): preflight, worktree-only work, primary stays on `main` clean, conventional commits, PR-only flow, issue-`<N>` branches emit artifacts (never commit the five gitignored body dirs), user merges.
- **Isolation:** touch only your phase's write paths. Shared hotspots — `models/models.py` + `database/migrations/` (W2-B, W3-A, W3-B, W4-A) and `packages/contracts` (W1-C, W3-B): rebase onto the wave branch before landing; exactly one Alembic head after each wave (integration owner resolves).
- **Tests:** pin `PYTHONPATH` when running pytest inside a worktree (bare pytest silently tests the main checkout). Live-provider/live-Redis tests carry markers per ADR-040 lanes; CI runs recorded-replay.
- **Shell discipline:** verify `pwd` + `git branch --show-current` before every commit (subagents inherit the parent shell cwd — a sibling worktree commit is a known failure mode here).
- **Env/secrets:** keys via `require_env` (fail-closed); never commit `.env`; sandbox credentials for writes; reference-shop production credential is read-only.
- **PLAN.md:** update tracker + your phase section in the same PR as the completing change, not after.

## 8. Integration & verification checkpoints (wave gates)

- **W1 close:** sanitizer runs against real registry tool outputs (W1-A×W1-C integration test); fake LLMService consumed by at least one downstream-shaped test.
- **W2 close:** `compose()` renders the full system prompt from the real registry; P-IM suite green on fixtures.
- **W3 close (the big one):** real GPT-5.4 nano run — ActionCard → runner → tools → sandbox write → `final_response` — streamed live to a browser via SSE with reconnect replay verified. Record this run's event log: it becomes P-UI's first golden scenario.
- **W4 close:** anonymous demo session completes the full staged flow incl. a multi-option decision request; rate limits + injection suite green; P-IM's one real backdated reading computed and visible in the finished-run UI.
- **After W4:** hand back to the Architect for P10 (observability — consumes I9 for the four-metric aggregation), P15 (hardening), P13 (rollout). These are deliberately NOT in this handoff (undesigned).

## 9. Current state

- Merged: ADR-068–077 and all grill recordings (#962, #963, #967, #969–#975). `main` at `2db2b55b`. No `services/agent/` code exists.
- Open worktrees from other efforts exist under `.worktrees/` — do not touch them; create your own.
- Deferred by user: P-CS, P7. Not designed: P10, P15, P13, P6.

## 10. Open questions / flagged items (not blockers — do not solve in-phase)

- Multi-product Optimize Product ActionCard shape (stacked top-3 vs cap) — ActionCard layer, pre-P13.
- Cold-start bootstrap (OAuth → 7D backfill → signals, measured ≈6–8 min) and per-shop daily analytics topup — recorded in PLAN.md P-IM flagged gaps; needed before multi-shop rollout, independent of these waves.
- Live TikTok merchant OAuth exchange for arbitrary shops; TikTok Login Kit as IdP — flagged follow-ups (ADR-076).
- RLS repair — hard precondition on the production-write unlock list (ADR-075), separate effort.

## Files changed (this session)

- `docs/product/agent-workflow-execution/PLAN.md` — P-IM flagged-gaps block (#975, merged).
- `docs/handoffs/2026-08-12-agent-execution-implementation-handoff.md` — this file.

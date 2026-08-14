# Agent workflow execution — authority & supersession map

**Purpose:** one place that says which document wins when two disagree, and which
statements in still-live documents have been superseded. Written after a stale line in
`PLAN.md` D1 nearly caused an executor to delete three deliberate determinism guarantees.

**Maintained by:** the Meta agent of each wave. Append a row when you find a conflict;
never resolve one silently.

## Authority order

```
merged ADR  >  PLAN.md settled-spec section  >  implementation handoff  >  PLAN.md preamble (D1-D6)
```

Rationale: the ADRs were grilled and merged last and carry the decisions; the handoff
explicitly disclaims design authority ("owns *orchestration only*: order, isolation,
pinned interfaces, session bootstrap"); `PLAN.md`'s D1–D6 preamble predates the ADR grills
and was not always re-annotated when an ADR settled the question differently.

**Rule: a conflict is reported to the Architect, never adapted around silently.**

## Superseded statements still present in live documents

| Live statement | Where | Superseded by | What is actually true |
|---|---|---|---|
| "The 3 no-LLM contract tests … are lifted deliberately" | `PLAN.md` D1 (now annotated); **implementation handoff §6, W1-B "Trap" — still uncorrected** | **ADR-068 d.6** | The three tests are **kept unchanged**. Three *new* boundary tests are added alongside: provider-SDK import containment; agent tool handlers never import `TikTokClient`; agent-authored seller copy passes the server-side banned-pattern check. |
| Claude Haiku / Ollama as the copy-layer LLM provider | ADR-012, phase-4 docs | **ADR-071** (+ user decision 2026-08-11) | Base model is **OpenAI GPT-5.4 nano** via the Responses API **for the agent path**. The rules modules' existing provider-free guarantees are unaffected. |
| `ToolExecution` is an audit row; writes execute in-run | ADR-069 d.2 | **ADR-073** (amendment, quoted inside ADR-069 itself) | `ToolExecution` is promoted to an **idempotency ledger** — unique `(workflow_run_id, tool_call_id, operation)`, claim-then-execute, verify-then-decide crash reconciliation. **This belongs to W3-A, not W1-A.** |
| `stop_reason` enum as originally listed | ADR-073 | **ADR-074** (additive) | `worker_lost` is an additive member, set by the 5-minute reaper. |
| Demo design-language files for the Optimize Product surfaces | older `docs/product/design` material | **ADR-076 + PUI-DESIGN.md** | PUI-DESIGN.md **deliberately overrides** them for these surfaces. Do not "reconcile" back. |
| "the OpenAI SDK rides httpx like the TikTok client" — implying the SDK is used | ADR-071 d.6 | **Architect decision 2026-08-12 (Option A)** | The adapter is built directly on `httpx`; the `openai` SDK is **not** used. ADR-071's rationale (contain wire types, stay swappable, mirror the hand-rolled `integrations/tiktok` client) is satisfied without it. ADR-068 d.6(a)'s containment test still applies as a guard against future SDK creep. Revisit if we adopt streaming or structured outputs. |
| Platform/rollback shape | ADR-035 | **ADR-057** (platform, in part) | Single-VPS pre-user delivery. Relevant when the public-release evidence gate fires. |
| `WorkflowRunner` lives in `services/agent/runner.py` — a single file | **ADR-073 d.1** and `PLAN.md` §6, in agreement | **Implementation handoff §6, W3-A "Write paths"** — `services/agent/runner/`, a package | W3-A builds the **package** form (`status.py`, `state.py`, `conversation_store.py`, `core.py`, `tool_executor.py`, `termination.py`, `ledger.py`, `concurrency.py`). Seven of the eight P1 slices touch runner-owned logic and need disjoint write paths for Review to grade them independently; a single file makes every slice collide. Note this **inverts the usual authority order** — the handoff wins over two higher-authority documents on an operational point neither of them was deciding. Flagged for the Architect to ratify or correct at source. |
| P8's phase gate is one flat list of green checks | **ADR-074 d.6** | Implementation handoff §6, W3-B — an explicit **2-stage** gate (contracts stage / live stage) | W3-B follows the handoff's two-stage split: the wave's parallelism contract (build against pinned I5/I6 while W3-A is in flight; live gate only after W3-A merges) is unbuildable without it. The ADR does not contradict the split — it simply does not name it. Recorded so the ADR can absorb the staging language rather than the handoff quietly outranking it twice. |

## Deferred — build to the seam, do not implement

| Phase | Status | Seam to build against |
|---|---|---|
| **P-CS** conversation storage | user-deferred 2026-08-11 | `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol (ADR-073 d.5) |
| **P7** structured output | user-deferred 2026-08-11 | prose final response now; machine schema attaches at `FinalResponse` + an explicit prompt v2 bump |

## Verify-don't-rebuild

Already landed on `main`; confirm with a test rather than reimplementing:

- JWT fail-closed via `require_env` (#902) and `/docs` production gating (#903) — ADR-075 turns both into verification tests.
- Request-ID middleware + dictConfig partially landed (#963+) — P10 re-verifies the baseline.
- **RLS is non-functional** and stays a hard precondition on the production-write unlock list — out of scope for the agent waves.

## Hard phase gates

- **ADR-051:** Executor and Review agents must never open the TikTok corpora catalogs or
  bodies. Curated `tiktok_api` / `tiktok_platform` docs + ADRs only. Architect/Meta only.
- Executor sub-agents have **no MCP tools** by construction. An executor that believes it
  needs a design reference is a signal that Meta routing was wrong — stop and report.
- Executor/scout sub-agents run **Sonnet/Haiku**, never Opus/Fable, except an
  explicitly user-approved escalation.

## Open doc-hygiene items for the Architect

1. **ADR-068 through ADR-077 are all still marked `**Status:** Proposed`** while being
   implemented as merged design authority. They should be flipped to `Accepted`.
2. The implementation handoff §6 W1-B "Trap" still asserts the superseded "lifted" claim
   and should be corrected at source.
3. Handoff §9 pins `main` at `2db2b55b`; `main` has since advanced.
4. **Handoff §6 W3-A/W3-B imply a wave branch per phase.** Wave 3 runs both phases on one
   branch (`feature/agent-w3-wave`, manifest `wave-agent-w3`) because they share
   `models/models.py`, one Alembic head, the `EventSink` seam, and a single wave-close gate —
   and because two wave branches would put W3-A's runner slice on a sibling wave's branch,
   which receives zero CI checks. Rationale recorded in `PLAN.md`'s "Wave 3 status" section;
   the W1 precedent (#1034) is the same shape.

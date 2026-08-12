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
| Platform/rollback shape | ADR-035 | **ADR-057** (platform, in part) | Single-VPS pre-user delivery. Relevant when the public-release evidence gate fires. |

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

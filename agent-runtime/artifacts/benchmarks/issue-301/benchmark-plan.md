# Benchmark Plan — Issue #301 Prompt-Cache A/B

**Benchmark type:** `multi-agent-workflow` (Type D) per
[`agent-runtime/docs/agent-runtime-benchmarks.md`](../../../docs/agent-runtime-benchmarks.md)
and [`task-type-d-multi-agent-workflow.md`](../../../docs/benchmarks/task-type-d-multi-agent-workflow.md).

**Child issue:** #301 — P2-A1: Layer 2 sandbox write validation resources
**Parent issue:** #278 — Phase 2: Contract-first TikTok Shop read sync and sandbox write validation
**Layer 0 contracts:** #287 (inventory + product), #289 (promotion lifecycle), #291 (fulfillment ship + package)

**Authority:** [`EXECUTION.md`](../../../EXECUTION.md) P2-A1 · handoff:
[`docs/handoffs/phase-2-tiktok-implementation.md`](../../../docs/handoffs/phase-2-tiktok-implementation.md) ·
verified contracts: [`docs/integrations/tiktok_api/contract-collection.md`](../../../docs/integrations/tiktok_api/contract-collection.md),
[`docs/integrations/tiktok_api/endpoints.md`](../../../docs/integrations/tiktok_api/endpoints.md) ·
acceptance criteria: GitHub issue #301 body.

This branch (`experiment/301-common`) is the **neutral baseline** shared by both treatments.
It contains no hidden tests and no #301 implementation. It exists only to fix the
controlled variables and define what gets measured, identically, for A and B. It does
carry the repo's generic agent-runtime / prompt-caching harness machinery (skills,
schemas, templates, config) — that mechanism is available to both treatments equally;
only whether it is *activated* differs (see §2).

---

## 1. Controlled variables (identical for A and B)

| Variable | Control |
|----------|---------|
| Model + model settings | Same model, same temperature/settings for both runs — record the exact values in the experiment manifest before each run starts |
| Tool permissions | Same tool allowlist for both runs |
| Session | Fresh session per run — no prior chat history, no memory of the other treatment |
| Source | Same `BASE_SHA` → same `COMMON_SHA` starting tree. `A_START_SHA = COMMON_SHA`; `B_START_SHA = B_SETUP_SHA`, where the only diff between `COMMON_SHA` and `B_SETUP_SHA` is the B-only cache artifacts under `agent-runtime/artifacts/grill-cache/` |
| Acceptance criteria | Same GitHub issue #301 body, same handoff acceptance section |
| Visible repository tests | Same visible test suite at `COMMON_SHA` (hidden evaluator tests on `experiment/301-evaluator` are **not** merged into either treatment branch) |
| Cross-treatment access | Neither run may read the other branch, its worktree, its transcript, or its artifacts |

## 2. Independent variable

| Treatment | Condition |
|-----------|-----------|
| **A** — `experiment/301-a-no-cache` | Prompt caching explicitly disabled by benchmark override. No `parent-cache-issue-278.json` / `grill-cache-issue-301.json` present or injected. Agent runs the normal Scope/Meta → Executor → Review → Validate flow cold, per [`prompt-caching`](../../../.cursor/skills/standalone/prompt-caching/SKILL.md) "cache missing" path. |
| **B** — `experiment/301-b-cache-hit` | Valid parent (`parent-cache-issue-278.json`) and child (`grill-cache-issue-301.json`) caches are prepared and validated **before** measurement starts, then injected per the `prompt-caching` skill's injection order. `cacheStatus: valid` on both. |

Only the caching condition differs. Everything else in §1 is held constant.

## 3. Timing boundary

- **Start:** immediately before Scope/Meta begins (before any grill-cache load/inject
  decision, before any doc is read for #301 implementation purposes).
- **End:** after Validate completes **and** post-validation Harness Optimization (Meta
  Agent, per `agent-runtime.md` "Harness Optimization" phase) completes.
- **Excluded:** all B-only cache preparation and validation time — the diff between
  `COMMON_SHA` and `B_SETUP_SHA`. Reported separately as `cacheSetupDurationMs` in the
  experiment manifest, never folded into B's measured duration.
- **Executor duration:** report separately from total wall-clock whenever the runtime
  emits a distinguishable Executor-phase boundary (e.g. a `phaseCacheBlocks.executor`
  write timestamp or an implementation-artifact phase marker). If the harness does not
  expose that boundary, record `executorDurationMs: null` with an `unavailableReason` —
  never estimate.

## 4. Metrics

See [`measurement-manifest.json`](measurement-manifest.json) for the machine-readable
schema. Summary:

- Wall-clock duration by phase (scope/meta, executor, review, validate, harness
  optimization) and total
- Token input/output/total — only when platform telemetry provides it
- Tool invocation count
- Context files loaded: paths, count, bytes
- Skills loaded: paths, count
- Cache hits and misses
- Context transfer count
- Retries and phase loops
- Production LOC added/deleted
- Test LOC added/deleted
- Documentation LOC and runtime-artifact LOC, reported separately from production/test LOC
- Tests collected/passed/failed/skipped, pass rate, coverage percentage
- Review status + failures; validation status + failures
- Acceptance-criterion mapping (which ACs are covered by which tests)
- Implementation, Review, Validation, and Optimization sub-scores per
  [`agent-runtime-benchmarks.md`](../../../docs/agent-runtime-benchmarks.md) §"Sub-scores"

**Never estimate unavailable token or timing data.** Any metric the runtime cannot
observe directly must be recorded as `null` with a one-line `unavailableReason` — never a
guess, average, or extrapolation.

## 5. Test / coverage commands (identical for A and B)

Run from repo root, backend installed editable (`pip install -e "./backend[dev]"`):

```bash
# Full visible regression sweep with coverage (defined on this branch and both treatments)
pytest tests/ -v --tb=short --cov=juli_backend --cov-report=term-missing --cov-fail-under=80
```

The hidden evaluator suite's file path and contents are defined **only** on
`experiment/301-evaluator` (see `EVALUATOR_SHA`) and are intentionally **not** referenced
by path on this branch, to avoid signalling test location to either treatment before its
run completes. Grading applies the hidden suite against each treatment's final tree after
the run, out of band from the treatment's own session.

## 6. Files excluded from implementation LOC

- `agent-runtime/artifacts/benchmarks/` (this plan + manifest)
- `agent-runtime/artifacts/grill-cache/` (cache prep is excluded per §3)
- `agent-runtime/artifacts/implementations/`, `.../reviews/`, `.../validation/`,
  `.../optimization/` (these are *outputs* of the run, not implementation LOC)
- `agent-runtime/scripts/benchmarks/` (measurement support tooling)
- Hidden evaluator test file(s) authored on `experiment/301-evaluator` (evaluator-owned;
  counted separately as "test LOC" only if a treatment adds its *own* additional tests)

## 7. Non-negotiables

- Do not implement #301 production behavior on this branch.
- Do not add anything here that leaks #301 solution shape beyond what the public issue
  body / handoff / contract-collection doc already state.
- Do not give either treatment branch knowledge of the other's existence beyond the
  branch names already fixed in the experiment manifest.

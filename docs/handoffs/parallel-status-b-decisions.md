# Parallel status — Head Meta 3.5-B (Continuous CDP Decisions)

**Status: ALL SIX SLICES LANDED; EXIT GATE SATISFIED** (2026-08-08) — cleared to merge
**Parent PRD:** [#599](https://github.com/thienphung00/Juli-AI/issues/599)
**Integration branch:** `feature/b-decisions-wave` (`.worktrees/b-decisions-wave`), cut from `origin/main` @ `9e9e4ad1`
**Head Meta:** owns this file, slice routing registration, ops-lock arbitration, exit gate

## Epic gate — SATISFIED 2026-08-08

#599 was blocked on **A1 Speed (#601) exit** per ADR-047. When this wave was built,
[#780](https://github.com/thienphung00/Juli-AI/issues/780) was open and 3 of the 5 Demo Main
KPIs resolved `unavailable`; the operator authorised building on this wave branch anyway,
with `main` explicitly withheld.

**#780 closed 2026-08-08T14:32Z** with runtime evidence on release `55dd9a67`: all five KPIs
(`gmv_tiktok`, `aov`, `cancellation_rate`, `ctor`, `live_hours`) report `available`, sustained
since 05:00; envelope recomputing hourly; orders sync 12s behind the run with `silver.orders`
not stale. The A1 exit condition (5/5 available) is met, so this wave's merge gate is cleared.

**What that close explicitly does not claim** — carried forward, not quietly dropped: the
original cause stands. No bronze domain exists for A-34/A-28, `targeted_fetch_bronze_deferred`
still fires every run, and the interval source is a frozen snapshot ending 2026-07-21
(`stale = true`, ~18.6 days and growing, surfaced continuously by the envelope and the
15-minute alarm). That work is re-scoped to
[#880](https://github.com/thienphung00/Juli-AI/issues/880) and is **not** exit-blocking.
3.5-B does not depend on it — the Decision chain reads persisted candidates, not the
`ctor`/`live_hours` inputs.

## Slice DAG

```
B-1 #713 → B-2 #714 → B-3 #715 ─┬→ B-4 #716 ─┐
                                └→ B-5 #717 ─┴→ B-6 #718
```

Parallelism is available only at **#716 ∥ #717**; the rest is a strict chain.

## Locked decisions

| # | Decision |
|---|----------|
| 1 | PR base = `feature/b-decisions-wave`, never `main` |
| 2 | Head Meta alone edits this file and `agent-runtime/config/slices/B-*.yml` |
| 3 | Executor domain: `backend` for B-1/B-2/B-5/B-6; **`data-platform` for B-3/B-4** (both need Alembic migrations — `computed_at` on cards, emission state + cooldown index). Never dual-load. |
| 4 | Postgres is SoT for candidates + emission state; Redis read-through only (ADR-038/ADR-021) |
| 5 | #716 and #718 are public-surface slices — release-evidence plan required before Executor |
| 6 | Wave → `main` exit gate blocked on #780 / #601 exit (see above) |

## Issue board

| Issue | Slice | Domain | Branch | Validate | Status |
|-------|-------|--------|--------|----------|--------|
| [#713](https://github.com/thienphung00/Juli-AI/issues/713) | B-1 | backend | `feature/issue-713` | 21/21 PASS | **merged to wave** |
| [#714](https://github.com/thienphung00/Juli-AI/issues/714) | B-2 | backend | `feature/issue-714` | 21/21 PASS | **merged to wave** |
| [#715](https://github.com/thienphung00/Juli-AI/issues/715) | B-3 | data-platform + backend | `feature/issue-715` | 21/21 PASS | **merged to wave** (mig `026`) |
| [#716](https://github.com/thienphung00/Juli-AI/issues/716) | B-4 | data-platform + backend | `feature/issue-716` | 21/21 PASS, 6/6 AC | **merged to wave** (mig `027`) |
| [#717](https://github.com/thienphung00/Juli-AI/issues/717) | B-5 | backend | `feature/issue-717` | 21/21 PASS | **merged to wave** (mig `028`) |
| [#718](https://github.com/thienphung00/Juli-AI/issues/718) | B-6 | backend | `feature/issue-718` | 21/21 PASS (slice + delta reviewed separately) | **merged to wave** |

Wave at integration: **2351 passed, 4 skipped, 0 failed**; single Alembic head
`028_demo_execution_records`; all six status records committed.

## Review coverage — what was reviewed by whom

Every slice had a Review-agent pass. Two hardening deltas landed **after** their slice's
Review and needed separate treatment:

| Delta | Reviewed by |
|---|---|
| #718 `c40cb591` (row resilience, flush→commit) | **Review agent**, scoped delta pass — ship-ready YES |
| #717 `2b5da6e2` (import-boundary recursion, approve idempotency) | **Head Meta only** — no Review-agent pass |

#717's delta remains the one place in this wave where a code change was verified by the
coordinator rather than an independent Review. It is recorded here rather than smoothed over.

The #718 delta pass independently reproduced the vacuity claim (reverted `commit()`→`flush()`,
confirmed both tests still passed vacuously, restored byte-for-byte), confirmed the per-row
handler catches `ValidationError` only and not bare `Exception`, and ruled the detail-endpoint
500 is not a practical existence oracle — a malformed row in another shop, or a suppressed one,
still 404s identically because the WHERE clause excludes it before validation runs.

Two non-blocking recommendations carried forward: alert on `demo_decisions_row_dropped_invalid_shape`
volume (an all-rows-malformed feed returns an empty 200 that a client cannot distinguish from a
genuinely empty feed), and optionally log-500-respond-404 on detail for an absolute 404 invariant.

## Integration hazard found at merge time — stacked branches need explicit merges

Each issue branch was cut from its predecessor *before* the predecessor received
follow-up commits (Review sent work back three times). Merging only the tip branch
(`feature/issue-717`) reported a **clean merge with no conflicts** while silently
dropping five commits — including `e8e9da93`, the operator's fill-to-cap novelty
decision, and the status records for #714/#715/#716.

Verify with an explicit ancestry check per slice commit, never by trusting a clean
tip merge:

```bash
for c in <every slice commit>; do
  git merge-base --is-ancestor $c HEAD && echo "$c OK" || echo "$c MISSING"
done
```

Every branch must be merged individually. This is the cost of stacked-branch
pipelining, and it is worth paying — but only if the completeness check is run.

## Executor environment — mandatory

`juli_backend` is installed into the ambient python (`/opt/homebrew/anaconda3`) as an
editable install pointing at the **main checkout**. A bare `python -m pytest` inside any
worktree therefore imports the wrong source tree, and the main checkout is parked on an
unrelated stale branch. Every Executor and the Review agent must run:

```bash
PYTHONPATH=$PWD/backend/src python -m pytest <paths> -q
```

Verify with `PYTHONPATH=$PWD/backend/src python -c "import juli_backend;print(juli_backend.__file__)"` —
the path must be inside the worktree. Baseline on this wave with the fix applied:
`test_cdp_speed_shared_compute_orchestrator.py test_scoring.py test_action_cards_contract.py`
= **44 passed**. Full `tests/unit` on the wave base: **2239 passed, 5 skipped** (94s).

## Pipelining

Issue branches chain off their predecessor rather than waiting for the wave merge:
`feature/issue-714` is cut from `feature/issue-713`, not from the wave. Each branch is
rebased onto the wave once its predecessor's PR lands, so the wave history stays linear
and a slice never waits on its predecessor's Review to start.

## Carried follow-ups (not in any slice's AC)

| Item | Detail |
|---|---|
| A2 batch call site | `services/cdp_batch/batch_reconcile_orchestrator.py:200` constructs `SharedComputeOrchestrator` directly and so never dispatches the Decision scoring stage. `cdp_batch` is A2 and is in this epic's doNotLoad — PRD US-30 defers it ("when A2 exists"). Needs its own issue if Decisions must refresh on the A2 daily stagger. |
| `cdp_speed` unregistered in `docs/architecture/map.md` | Makes the `module_boundaries` and `module_md_sync` validation gates **no-op pass** for that module — they report green without checking. The real contract in `.importlinter.toml` does cover it and passes. Pre-existing, not introduced by this wave. |
| `ruff` config discovery | `ruff check backend tests` from the repo root does not discover `backend/pyproject.toml` for files under `tests/`, yielding ~124 spurious errors / ~104 reformat hits. `CLAUDE.md` documents the bare form. Needs `--config backend/pyproject.toml`. |
| Reconcile scoring wiring | `workers/tasks/mock_analytics_reconcile.py:128` called `run_shared_compute_job` with no `scoring_stage` — folded into B-2 rather than deferred, since PRD US-30 requires reconcile to heal Decision staleness. |

## Alembic serialization — why #716 ∥ #717 probably cannot run concurrently

The repo keeps exactly **one** Alembic head (currently `025_silver_orders_returns`). B-3,
B-4 and B-5 each need a migration. Two executors branching from the same base would both
author `026_*` with `down_revision = 025_*`, producing **two heads** and a broken chain.

So the only concurrency the logical DAG offers is cancelled by the revision chain unless
revision ids are pre-assigned by Head Meta and the branches stay stacked:

| Slice | Revision | down_revision |
|---|---|---|
| B-3 #715 | `026_*` | `025_silver_orders_returns` |
| B-4 #716 | `027_*` | `026_*` |
| B-5 #717 | `028_*` | `027_*` |

Throughput in this wave therefore comes from **stacked-branch pipelining**, not fan-out.
Record this honestly rather than claiming parallelism the chain cannot deliver.

## Artifact-hygiene gotchas hit in this wave

These cost two Review round-trips; brief every Executor on them up front.

1. **Run the Meta gate from the issue's own worktree.** `issue-context-cache-<n>.json` is
   written into the CWD's worktree. Running it centrally leaves the issue worktree without
   a cache, which fails five validate gates at once (`public_release_classification`,
   `public_release_evidence_plan`, `executor_domain_matches_cache`, `phase_run_correlation`,
   `release_evidence_plan_continuity`).
2. **`implementation-artifact.schema.json` sets `additionalProperties: false`.** Only its
   23 named keys are allowed. #713's artifact carried 7 extra keys; #714's had `stage`
   values outside the `red|green|refactor|implementation|other` enum.
3. **`tokenUsage` is required** by `implementation_artifact_present`, but its `input` /
   `output` / `total` sub-fields are individually optional. When the harness exposes only a
   cumulative figure, record `total` alone — do not fabricate a split, and do not add a
   `note` field (schema-rejected).
4. **Regenerate the status record after validation flips.** `generate_status_records.py`
   snapshots the validation status; a record written while validate was FAIL keeps failing
   `test_status_record_gate.py` after the underlying gate goes green.
5. **#713's status record is still missing** — its review/validation artifacts live only in
   `.worktrees/issue-713` and are gitignored, so the generator cannot see them from the tip
   branch. Regenerate all status records at wave-integration time.

## Design note for B-4 (#716) — read before dispatching

B-3 landed status preservation as: if an existing card's status is in
`IN_FLIGHT_STATUSES = {approved, dismissed, executing}`, the re-scoring candidate is
**dropped entirely** for that `workflow_key` — the row is left untouched, content and
`computed_at` included. That is exactly what B-3's AC2 asks for, and it is correct as
delivered. It collides with two PRD requirements that land in B-4:

1. **US-11 — "candidates recomputed even when emission budget suppresses surfacing, so
   promotion logic can catch up."** With one row per `(shop_id, workflow_key)` and the
   in-flight skip, a recomputed candidate for an in-flight card is discarded, not stored.
   B-4's `candidate` / `surfaced` / `suppressed` split has to give the candidate somewhere
   to live that is not the in-flight row.
2. **7-day cooldown expiry.** `dismissed` is inside `IN_FLIGHT_STATUSES`, so a dismissed
   card is never refreshed by re-scoring. Once B-4 adds "cooldown expires after 7 days and
   the workflow may surface again", nothing will ever produce a fresh candidate for that
   `workflow_key` — the cooldown can start but never finish. B-4 must either narrow the
   skip set or let a post-cooldown candidate overwrite a `dismissed` row.

Neither is a defect in B-3. Both are B-4's to resolve, and B-4 must not "fix" them by
weakening B-3's status-preservation test.

## Structural lesson — the data-platform/backend split leaks a wiring gap every time

Twice now, routing a slice to `data-platform` produced correct, well-tested code that
**nothing called**, because the call site lives in `services/cdp_speed/` (backend paths):

| Slice | Built | Never called by | Caught by |
|---|---|---|---|
| B-3 #715 | `persist_scoring_result` upsert semantics | the scoring stage | Executor self-report |
| B-4 #716 | `apply_emission_budget` | the scoring stage | Head Meta grep before Review |

Both Executors behaved correctly — they stopped at their path boundary and reported rather
than widening scope. The defect is in the **routing**, which is Meta's: these slices need a
migration *and* a call site, and no single domain owns both.

**Rule for the rest of this wave:** before dispatching any `data-platform` slice, decide up
front who wires the call site, and either budget a backend increment on the same branch or
route the slice to `backend` with explicit, documented migration authorization. Do not let
the gap be discovered after Review.

**For B-5 (#717):** dispatch as a single `backend` Executor with explicit Meta authorization
for migration `028_*` — the cost of the split has now been paid twice.

## Open questions for the operator (not blockers, but real)

1. **Is the weekly novelty quota meant to be soft?** PRD/ADR-038 §6 call it a *soft* quota of
   3, but it runs as a gate ahead of the active cap of 5 — so a shop with more than 3 new
   workflows in a week never reaches 5 surfaced Decisions. Routed to B-4's Review for a
   ruling; if it is a genuine mismatch it is a product-config decision, not an Executor fix.
2. **In-flight cards freeze their `computed_at`.** B-3 drops the recomputed candidate for an
   approved/executing/dismissed card, so that row's freshness metadata stops advancing while
   re-scoring keeps running. This matches AC2 exactly and is not a defect — but the Demo
   surfaces `computed_at` as trust copy, so a card a seller is acting on will visibly age.
   Worth a follow-up on what the Demo should display for in-flight cards.
3. **AC4's savepoint rationale did not reproduce.** B-3's Executor redesigned its negative
   test claiming SQLite/aiosqlite does not reliably roll back a released SAVEPOINT. Review
   reproduced the scenario in four configurations and rollback worked correctly every time.
   The delivered test still genuinely proves AC4, so this is not a defect — but the stated
   rationale is unverified, and the original design may have been abandoned unnecessarily.

## Ops lock

**Holder:** Head Meta. Stagger remote ops ≥30s; one PR push/merge at a time. Only #716 and
#717 ever run concurrently — they are path-disjoint (emission budget persistence vs dry-run
execution module).

## Exit gate (wave → main)

- [ ] All six slices merged into `feature/b-decisions-wave`, Review + validate PASS each
- [ ] Release-evidence plans committed for #716 and #718
- [ ] Dry-run isolation test proves no `/v1/executions`, `enqueue_approved_tool`, or `run_tool_async` on the Demo path
- [x] **#780 closed and A1 exit confirmed** — 5/5 KPIs available on `55dd9a67`; residual cause re-scoped to #880 (non-blocking)
- [ ] `feature/b-decisions-wave` → `main` PR green

# Handoff: Executor/Review audit — attested vs executed evidence, and a worktree cleanup

**Date:** 2026-08-28 · **Phase:** Planning (Architect grill) → harness implementation → repo cleanup

## Session summary

An Architect grilling session on Executor/Review implementation ability and efficiency, backed by
six parallel read-only scouts. The audit found one root cause — **every in-loop verification layer
bottoms out in a claim the agent wrote about itself** — and three fixes were built, merged, and
verified. The session then cleaned ~4 GB of stale worktrees and repaired a diverged primary
checkout, which surfaced a live safety defect: migration tests can run against **production**.

## Decisions made

1. The failure mode is **(c) coupled** — gates added for correctness caused the slowness and fixed
   neither. Named in `CONTEXT.md` as **Trial-and-fix convergence** and **Attested evidence**.
2. Fix specification quality by **worked examples**, not a structural AC grammar (owner's call).
3. Red→green becomes a **measured** property (`check_differential_tdd`), landing **advisory** with a
   written promotion trigger rather than blocking on day one.
4. TDD applicability inverted from an allowlist to a **denylist** — decided only after measuring
   that 1 of the last 60 merged commits would be newly gated.
5. `mlGates.thresholds` declared copy **removed**; the gate reads source instead.
6. **Not** generating `MODULE.md` symbol lists from AST — rejected after inspection (it carries
   semantic prose AST cannot produce, and a `--fix` would let authors game the gate).
7. Worktree removal always **tags first** (`archive/<name>`), making deletion reversible.
8. `landing-wiring` preserved — it holds uncommitted work that exists nowhere else.
9. `reconcile-w7` / `reconcile-w6` left untouched — another agent owns W7 wave→main (#1402/#1405).

## Current state

**Merged to main:** #1391 (reorder-basis fix), #1392 (skill exemplars), #1393 (differential TDD +
denylist + ML de-pin). All checks green.

**Primary checkout:** on `main` at `2d37170c`, in sync, clean except untracked artifacts and a
stray `.CLAUDE.md.swp`. Previously diverged (1 unpushed commit carrying a **wrong-schema**
`status/issue-1318.json`, superseded by the canonical version on the W6 wave; tagged
`archive/local-main-1318-status`).

**Worktrees:** 26 → 20. Disk 7.1 GB → ~3.2 GB. **15 `archive/*` tags** preserve every removed
branch; all verified to resolve after deletion.

**Open, verified startable (clean worktrees created, 0 dirty, 0 behind):**
- **#1311** golden scenarios — no blockers; gates #1315
- **#1272** seller-facing reason codes — no blockers; gates #1317

**Open, blocked or not ready:**
- **#1313** anonymous demo session — unblocked by #1312, but its 3 commits **regress**
  `test_agent_abuse_limits_gate.py` (27 pass → 17 fail) against current main. Needs rework, not a
  rebase. Replay lives in `.worktrees/issue-1313-redo`; originals in `archive/issue-1313-demo-session`.
- **#1319** Google sign-in — behind #1313, so further out than it appears.
- **#1339** W7 gate — all 7 blockers have merged PRs *into `feature/w7-wave`*, but the wave is not
  on main. **PR #1402 is `MERGEABLE` but `BLOCKED`** on `full-regression` + `status-check`;
  **#1405 is the open cause**. Observations 1–2 act on the deployed system, so nothing in #1339 can
  start until #1402 lands and deploys.

## Next steps

1. **Fix `requires_postgres` (highest priority — safety).** See Open questions #1.
2. Decide whether the two `CONTEXT.md` glossary terms go onto a PR — the patch is parked at
   `scratchpad/context-terms.patch` and was **discarded from the working tree** by the reset.
3. Start **#1311** or **#1272** — both have clean worktrees ready.
4. File an issue for the **#1313 abuse-limits regression** and drop `.worktrees/issue-1313-redo`,
   or keep it as the reproduction.
5. Tier C worktrees still need owner judgement (no PR ever opened, nothing recoverable from
   GitHub): `demo-launch-grill`, `grill-agent-nfr`, `sweet-mendeleev-3af5ea`, plus `handoff2`
   (PR closed **without** merging). `landing-wiring` is **keep**.
6. Promote `differential_tdd` from advisory to blocking after 10 consecutive issues with zero
   false `no_discrimination` — condition is written at the constant in
   `generate_validation_artifact.py`.

## Open questions

1. **`requires_postgres` skips on *unreachable*, not *non-local*.** With `.env` present,
   `core/config/runtime.py:15` `load_dotenv(...)` injects the production `DATABASE_URL` at import
   time, so migration tests connect to production Supabase and attempt DDL. Verified after this
   session's reset: prod is **intact** (alembic `043`, 34 tables, data present) — the downgrade
   guard refused and an `ADD CONSTRAINT` rolled back. Before the reset, the *stale* checkout was
   accidentally the protection. Same class as the 2026-07-30 prod wipe. One-line fix; needs owner
   sign-off on scope.
2. **ADR status is inverted.** 18 ADRs are `Proposed` — almost all 068–085, the *current* W-wave
   work — while older superseded ones say `Accepted`. No ADR uses `Superseded` as a status value;
   supersession is prose only. 23 of 83 have no `Status:` header. Proposal: derive status from
   merge evidence rather than adjudicating 18 decisions by hand.
3. **`CODE_CHANGE_PREFIXES`** — resolved for the new denylist, but confirm the exclusion list is
   right (docs, config, artifacts, tests).
4. Whether `docs/handoffs/` should be pruned. **Do not bulk-delete** — `contextFilesLoaded` shows
   executors actively read handoffs, ADRs, `docs/product`, and `EXECUTION.md`, none of which are in
   their declared load list.
5. **`EXECUTION.md` (Tier 0) is stale** — describes Phase 3.5 with #601/#599 "open" (both closed),
   zero mention of W1–W7. Every executor loads its slice as baseline context.

## Files changed

Merged via #1391 / #1392 / #1393:

```
agent-runtime/scripts/ci/differential_tdd.py            (new)
agent-runtime/scripts/validate/check_differential_tdd.py (new)
agent-runtime/scripts/ci/generate_validation_artifact.py
agent-runtime/scripts/ci/implementation_tdd.py
agent-runtime/scripts/ci/ml_thresholds.py
agent-runtime/scripts/ci/common.py
agent-runtime/scripts/validate/check_ml_gates.py
backend/src/juli_backend/ai/forecasting/forecaster.py
backend/src/juli_backend/ai/forecasting/__init__.py
backend/src/juli_backend/ai/forecasting/MODULE.md
backend/src/juli_backend/api/routes/action_cards.py
tests/unit/test_differential_tdd.py                     (new)
tests/unit/test_ml_thresholds.py                        (new)
tests/unit/test_action_card_inputs_contract.py
tests/unit/test_implementation_tdd_evidence.py
tests/unit/test_generate_validation_artifact.py
tests/unit/test_review_status.py
.cursor/skills/standalone/to-issues/SKILL.md
.cursor/skills/standalone/to-prd/SKILL.md
```

Environment-only (not committed): repointed `_editable_impl_juli_backend.pth` from a stale
worktree to the primary checkout, and installed the pinned-but-missing Pillow. Together these took
pytest collection from **114 errors / 2629 tests** to **0 errors / 4612 tests**.

## Audit findings worth carrying forward

- Only **3 of 21** gates in Review's `validate` chain read code; the rest check artifact shape.
- **Review never runs pytest** — `testCoverage.unit.failed` is a number Review types in.
- The **prompt cache emits no `cache_control`** anywhere; it is JSON reuse, not prompt caching.
  `meta_prepare_executor.py` makes 8–9 redundant `gh` calls (~1.09 s each) with no memoization.
- `check_artifact_retention_guard` reads a status field generated from the same local artifacts —
  a hand-written `PASS`/`PASS` is undetectable by CI, by its own docstring.
- Measured amplification: every tuning commit costs **+2 mandatory JSON artifacts regardless of
  diff size** — 50% of changed files on a 63-line fix.
- Pre-commit judges with `backend/pyproject.toml` (`E,F,I,UP`); root `ruff.toml` selects
  `E4,E7,E9,F`. **Local `ruff check` passing does not mean pre-commit will pass.**
- `worktree_gc.py --close` refuses any squash-merged branch ("N unpushed commits"). The PR state
  (`gh pr list --head <branch> --state all`) is the signal that resolves it.

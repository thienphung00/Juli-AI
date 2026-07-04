# MVP parallel run — Issues #118, #119, #120

**Worktrees created:** 2026-06-05 · **Coordination:** [`parallel-status.md`](parallel-status.md)

Open **three separate Cursor windows**, one per worktree path below. Paste the matching prompt into each window's agent chat.

---

## Window 1 — Issue #118 (ship verify + GitHub ops owner)

**Folder:** `/Users/macos/Juli-AI-Next/.worktrees/issue-118`  
**Branch:** `feature/issue-118-ship-verify`

### Prompt

```
Build-feature implementation loop for GitHub issue #118.

This issue is ALREADY MERGED (PR #129). Run ship verification only — do not re-implement unless tests fail.

Pipeline: focus → tdd → review → ship

1. focus — Read docs/handoffs/issue-118-focus.md and docs/handoffs/parallel-status.md. You hold the GitHub ops lock for this parallel run.

2. tdd — Run web tests (test_seller_home_shell, full suite). Fix only if regressions found.

3. review — Confirm artifacts/reviews/review-issue-118.json PASS. Re-run review skill if needed.

4. ship — Close GitHub issue #118 if still open. Coordinate pushes/PRs for #119 and #120 (stagger remote gh/git ops ≥ 30s; update parallel-status.md Last remote op log).

Rules: .cursor/rules/issue-workflow.mdc, build-feature SKILL.md implementation loop.
DO NOT touch web/src/components/workflows/ (owned by #119/#120).
```

---

## Window 2 — Issue #119 (New Seller Copilot UI)

**Folder:** `/Users/macos/Juli-AI-Next/.worktrees/issue-119`  
**Branch:** `feature/issue-119-new-seller-copilot`

### Prompt

```
Build-feature implementation loop for GitHub issue #119 — New Seller Copilot UI (mocked).

Pipeline: focus → tdd → review → ship

1. focus — Read docs/handoffs/issue-119-focus.md. Load web/MODULE.md, SellerHomeShell, TaskQueue, new-persona fixture. Follow focus SKILL.md.

2. tdd — Red-green-refactor per acceptance criteria in issue-119-focus.md:
   - NewSellerCopilotPanel with checklist + first-sale milestone progress
   - Wire into SellerHomeShell when workflowId === "new_seller"
   - Integration tests in test_new_seller_copilot.test.tsx
   - Commit on feature/issue-119-new-seller-copilot

3. review — Run full web test suite. Write artifacts/reviews/review-issue-119.json. Prepare PR body (What/Why/How/Testing/Rollback).

4. ship — Hand push/gh pr create to Window #118 (GitHub ops owner) OR wait ≥ 30s and run if lock transferred. Merge when CI passes. Update EXECUTION.md P1-2 checkbox.

Parallel rules: docs/handoffs/parallel-status.md — modules web/workflows/new-seller only. DO NOT edit web/workflows/leakage/ (#120).
Skills: tdd, review, ship from .cursor/skills/standalone/.
```

---

## Window 3 — Issue #120 (Revenue Leakage Detection UI)

**Folder:** `/Users/macos/Juli-AI-Next/.worktrees/issue-120`  
**Branch:** `feature/issue-120-revenue-leakage-ui`

### Prompt

```
Build-feature implementation loop for GitHub issue #120 — Revenue Leakage Detection UI (mocked).

Pipeline: focus → tdd → review → ship

1. focus — Read docs/handoffs/issue-120-focus.md. Load web/MODULE.md, SellerHomeShell, TaskCard, leakage-persona fixture, schemas (evidence_refs). Follow focus SKILL.md.

2. tdd — Red-green-refactor per acceptance criteria in issue-120-focus.md:
   - resolve-evidence.ts maps evidence_refs to masked orders/returns/affiliate rows
   - LeakageCopilotPanel + EvidenceDrawer drill-down
   - Wire into SellerHomeShell when workflowId === "leakage"
   - Empty state: "Không phát hiện rò rỉ tuần này"
   - Integration tests in test_revenue_leakage_ui.test.tsx
   - Commit on feature/issue-120-revenue-leakage-ui

3. review — Run full web test suite. Write artifacts/reviews/review-issue-120.json. Prepare PR body.

4. ship — Hand push/gh pr create to Window #118 (GitHub ops owner) OR wait ≥ 30s. Merge when CI passes. Update EXECUTION.md P1-3 checkbox.

Parallel rules: docs/handoffs/parallel-status.md — modules web/workflows/leakage only. DO NOT edit web/workflows/new-seller/ (#119).
Skills: tdd, review, ship from .cursor/skills/standalone/.
```

---

## Suggested run order

| Step | Window | Action |
|------|--------|--------|
| 1 | All three | Paste prompts; each agent runs **focus** (read handoff, confirm scope) |
| 2 | #119 + #120 | **tdd** in parallel (disjoint directories) |
| 3 | #118 | **tdd** = run tests only (verify green) |
| 4 | #119 → #120 | **review** then request ops push (stagger 30s) |
| 5 | #118 | **ship** — push PRs, merge, close issues, update parallel-status |

## Quick commands

```bash
# List worktrees
git worktree list

# Run tests in a worktree
cd /Users/macos/Juli-AI-Next/.worktrees/issue-119/web && npm test

# Remove worktrees after all issues shipped
git worktree remove .worktrees/issue-118
git worktree remove .worktrees/issue-119
git worktree remove .worktrees/issue-120
```

# Bootstrap — parallel issue implementation

Use this when running multiple AFK issues in isolated worktrees.

## Prerequisites

- Dependencies merged on `main` (for #119/#120: #114, #115, #116, #117, #118 ✓)
- `gh auth login` if pushing or opening PRs
- One Cursor window per worktree

## Worktrees (this run)

| Issue | Path | Branch |
|-------|------|--------|
| #118 | `/Users/macos/Juli-AI-Next/.worktrees/issue-118` | `feature/issue-118-ship-verify` |
| #119 | `/Users/macos/Juli-AI-Next/.worktrees/issue-119` | `feature/issue-119-new-seller-copilot` |
| #120 | `/Users/macos/Juli-AI-Next/.worktrees/issue-120` | `feature/issue-120-revenue-leakage-ui` |

Open each path in a **separate Cursor window** (`File → Open Folder`).

## Per-window pipeline

Each window runs the Implementation agent phase:

```
focus → Executor (built-in TDD) → intent-review → guardrails → validate → ship
```

1. **focus** — read `docs/handoffs/issue-<N>-focus.md`; load context; do not code yet.
2. **Executor** — red-green-refactor per acceptance criteria; commit on feature branch.
3. **intent-review** — Spec fidelity × structure vs fixed point (usually `main`); emit intent-review artifact.
4. **guardrails** — Domain quality + AC coverage; write `artifacts/reviews/review-issue-<N>.json`; open PR (ops owner) or prepare PR body locally.
5. **validate** — run validation gates; write validation artifact.
6. **ship** — merge when gates pass; close issue; update `EXECUTION.md`.

## GitHub ops coordination

See [`parallel-status.md`](parallel-status.md).

- **One window** holds the GitHub ops lock (#118 window for this run).
- Non-ops windows: commit locally, paste PR body into ops window or wait for stagger slot.
- **≥ 30 seconds** between remote GitHub commands.

## Prompts

Copy-paste prompts for each window: [`mvp-118-120-parallel.md`](mvp-118-120-parallel.md).

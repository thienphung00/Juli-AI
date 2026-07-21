# Worktree & branch topology

**Status:** active · **Agreed:** 2026-07-21 (Architect grill)

Trunk-based slots with a frozen shared core. No persistent `product/frontend` or `product/backend` lanes.

## Persistent slots

| Slot | Branch | Worktree | Push? |
|------|--------|----------|-------|
| Primary | `main` | repo root | — (keep clean) |
| Agent runtime | `agent/runtime` | `.worktrees/agent-runtime` | Yes → PR |
| Debug / hotfix | `scratch/debug` | `.worktrees/debug` | Yes → short PR; reset after merge. Skip ADR-003 artifacts per `agent-runtime.config.yml` → `artifact_gates.quickCommitSkip` (branch must lack `issue-<N>`; CI mirror in `pr.yml`). Do not edit `pr.yml`/rules here — promote via `agent/runtime`. |
| Ad-hoc / reports | `local/adhoc` | `.worktrees/adhoc` | **Never** |

## Product work (ephemeral)

- Branch: `feature/<short-desc>` (optional `feature/be-…` / `feature/fe-…`).
- Cut from latest `main`; one worktree **per task** when agents run in parallel.
- Delete branch + worktree after merge. Do not accumulate lane history.

## Shared core (Isolate)

Never edit in the same PR as a product feature:

- `packages/contracts` (**FE-owned** until OpenAPI/codegen ADR)
- Root workspace / CI / lockfile churn
- Canonical `docs/architecture/*`, `CONTEXT.md`

Flow: shared-core PR → merge → reset task worktrees → feature PR.

## Parallel agents

1. Path-disjoint tasks → parallel worktrees; else Isolate.
2. Pipeline per issue: implement → review → commit → individual PR → CI → **sync-before-merge** → merge ([`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc)).
3. Ops lock + stagger: same rule file.
4. Per-run registry: create/update `docs/handoffs/parallel-status.md` for that run only.
5. Inside one checkout, path-disjoint mechanical edits may use Composer Task subagents (`model: composer-2.5-fast`, ≤3 concurrent — ask if more) per [`.cursor/rules/core-orchestration.mdc`](../../.cursor/rules/core-orchestration.mdc) — that is not a substitute for separate worktrees when modules conflict.

## After each merge (task worktree)

```bash
git checkout main && git pull
git worktree remove .worktrees/<task>   # if used
git branch -d feature/<short-desc>      # after remote delete / PR merge
```

Reset `scratch/debug` to `main` after each shipped hotfix.

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

## Local pre-commit (every worktree)

Git hooks are **per checkout**, not shared across worktrees. After creating or entering a worktree, install once:

```bash
pip install pre-commit
pre-commit install
```

(`default_install_hook_types` in `.pre-commit-config.yaml` registers both **pre-commit** and **commit-msg**; the explicit `pre-commit install --hook-type pre-commit --hook-type commit-msg` form is equivalent.)

Hooks (staged files only):

| Hook | Scope |
|------|--------|
| `ruff-check` | Lint + auto-fix staged `backend/`, `tests/`, `scripts/` Python |
| `ruff-format` | Format staged Python in those paths |
| `conventional-pre-commit` | Commit message types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci` |

Optional manual run before commit: `pre-commit run` (staged) or `pre-commit run --files path/to/file.py`. Frontend formatting and heavy checks (mypy, bandit, gitleaks, full test suite) remain CI / Merge Queue only.

## Shared core (Isolate)

Never edit in the same PR as a product feature:

- `packages/contracts` (**FE-owned** until OpenAPI/codegen ADR)
- Root workspace / CI / lockfile churn
- Canonical `docs/architecture/*`, `CONTEXT.md`

Flow: shared-core PR → merge → reset task worktrees → feature PR.

## GitHub settings (`main`)

- **Ruleset:** `Protect main` (id `16862793`) — branch ruleset on `refs/heads/main`.
- **Required status check:** `status-check` (job in workflow **PR Validation**, `.github/workflows/pr.yml`). Strict policy (branch must be up to date). Check context name verified from PR head commits (not `PR Validation / status-check`).
- **Reviews:** 0 approvals (unchanged); stale review dismissal on push.
- **Merge Queue:** **not enabled** — repo owner is a **User** account (`thienphung00`); GitHub allows merge queue only on **organization-owned** public repos (or private org repos on Enterprise Cloud). Rulesets API returns `422 Invalid rule 'merge_queue'` on user-owned repos.
  - **Manual enable (after org transfer):** GitHub → **Settings** → **Rules** → **Protect main** → **Add rule** → **Require merge queue** — squash merge, required check `status-check`, HEADGREEN grouping. Or `PUT` ruleset `16862793` with a `merge_queue` rule (same parameters as agent-runtime handoff).
  - **Until then:** use **sync-before-merge** + PR fast CI; keep `merge_group` trigger in `pr.yml` dormant-ready.

## Parallel agents

1. Path-disjoint tasks → parallel worktrees; else Isolate.
2. Pipeline per issue: implement → review → commit → individual PR → PR **fast CI** → **GitHub Merge Queue** (`merge_group` full suite) → merge ([`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc)). **Sync-before-merge** is fallback only when Merge Queue is unavailable. CI: `.github/workflows/pr.yml` — `pull_request` path-filtered; `merge_group` full suite; require `status-check`.
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

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

## Two lanes: pick by what the diff touches

| Lane | When | Isolation | Merge | Cleanup |
|------|------|-----------|-------|---------|
| **Standard** | Any code change, or mixed code + docs | Branch / worktree per task | PR → green → land (sync-before-merge; MQ dormant) | `worktree_gc.py --close <task>` |
| **Fast-track** | **Non-code only** (docs/rules/skills/text) | Short branch, no worktree | PR → immediate `--admin` self-merge | branch auto-deleted on merge |

If a changeset touches **any** code file (`.py`, `.ts`, `.tsx`, `.js`, `.sql`, `.sh`, code configs), it is **standard lane** — even if it also edits docs.

## Product work — standard lane (ephemeral)

- Branch: `feature/<short-desc>` (optional `feature/be-…` / `feature/fe-…`).
- Cut from latest `main`; one worktree **per task** when agents run in parallel.
- Delete branch + worktree after merge (`worktree_gc.py --close`). Do not accumulate lane history.

## Fast-track lane — non-code docs (no worktree)

For changesets touching **only** document files — `*.md`, `*.mdc`, `*.txt`, `docs/**`,
`.cursor/rules/**`, `.cursor/skills/**`, READMEs, ADRs, handoffs — and **no** code. Still a
PR (audit + CI-where-applicable + revert-via-PR), just without the worktree or review wait:

```bash
git switch -c docs/<short-desc> origin/main   # short branch off latest main
# …edit the document files, then:
git add -A && git commit -m "docs: <what changed>"
git push -u origin docs/<short-desc>
gh pr create --fill
gh pr merge --squash --delete-branch --admin  # immediate; --admin merges before a
                                              # never-running required check blocks a docs-only PR
```

- `--admin` uses the owner's ruleset bypass to merge right away; for `.cursor/**` /
  `agent-runtime/**` PRs (which **do** trigger CI) prefer letting checks go green first, or
  use `--admin` knowingly.
- `allow_auto_merge` and `delete_branch_on_merge` are **off** repo-wide, so `--auto` is not
  available and `--delete-branch` must be explicit.
- **Guard:** if `git diff --name-only origin/main` shows any code path, abort the fast-track
  and switch to the standard lane.

### Mid-code doc fix (stash, don't branch)

Halfway through a coding session and spot a doc error to fix now — don't spin up a worktree:

```bash
git stash push -m "wip: <feature>"     # pause + hide current code changes
git switch -c docs/<short-desc> origin/main
# …edit docs, then commit / push / PR / --admin merge as above…
git switch -                           # back to your feature branch
git stash pop                          # restore paused work
```

Use when: mid-implementation but a documentation fix must ship immediately without mixing
into your feature's commits.

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
2. Pipeline per issue, three-tier CI + wave free-merge ([ADR-052](../adr/052-wave-free-merge-deferred-artifact-gate.md)): implement → review → commit → individual issue PR into the run's `feature/*-wave` branch → PR **fast checks** (issue tier: path-filtered lint/type/cheap tests + `policy-checks`; **no** artifact validate/generate jobs) → merge into wave. **No "up to date with base" requirement on `feature/*-wave`** — sibling issue merges free-merge in without forcing a rebase/rewait. **The issue→wave PR owns the wave-manifest bump** (`agent-runtime/artifacts/waves/wave-<id>.json` gains the issue number; `policy-checks` fails if missing). **Wave push** CI path-filters the push's **before→after** SHAs — domain-matched integration/architecture/contract checks for what just landed, not the full suite. When the run's issues are all in, one **wave → `main`** PR runs full main-tier gates plus the **artifact-gate** job, which owns asserting each manifest issue's review/validation artifacts exist with `status: PASS` ([`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc)). **Sync-before-merge** is the fallback at wave→main when Merge Queue is unavailable (current default on this user-owned repo — see § GitHub settings). CI: `.github/workflows/pr.yml` — issue/wave/main tiers per `classify-tier`; require `status-check`.
3. Ops lock + stagger: same rule file.
4. Per-run registry: create/update `docs/handoffs/parallel-status.md` for that run only. **This file is human ops UI — a status board for agents/operators — not a CI source of truth; CI reads the wave manifest and `pr.yml` only, never this markdown.**
5. Inside one checkout, path-disjoint mechanical edits may use Composer Task subagents (`model: composer-2.5-fast`, ≤3 concurrent — ask if more) per [`.cursor/rules/core-orchestration.mdc`](../../.cursor/rules/core-orchestration.mdc) — that is not a substitute for separate worktrees when modules conflict.

## After each merge (task worktree)

Governed cleanup trigger — run the moment a task's PR merges:

```bash
# From ANY worktree — does not require checking out main (main lives in its own worktree)
python agent-runtime/scripts/git/worktree_gc.py --close <task>
```

Equivalent manual form (only if the script is unavailable):

```bash
git fetch --prune
git worktree remove .worktrees/<task>       # --force ONLY to intentionally discard changes
git branch -D feature/<short-desc>          # -d MISSES squash-merges; verify via `gh pr` first
```

> Why not `git checkout main && git branch -d`: `git checkout main` fails when `main` is
> checked out in another worktree (the normal topology here), and `git branch -d` refuses
> squash-merged branches (this repo squash-merges), so both silently leave branches behind.

### Safe-close verification (what `--close` enforces)

A worktree/branch is auto-closed only when **all four** hold; otherwise the script reports
it and the agent must confirm with the user before deleting:

1. **PR merged** — `gh pr list --state merged --head <branch>` non-empty (catches squash).
2. **Clean** — `git -C <wt> status --porcelain` empty (no uncommitted changes).
3. **No unpushed commits** — `git -C <wt> rev-list @{u}..HEAD` == 0.
4. **Not protected** — never `main`, `agent/runtime`, `scratch/debug`, or `local/adhoc`.

A branch with no upstream and no merged PR, or a **closed-not-merged** PR, is left in place
for a human decision. `worktree_gc.py --report` shows this classification for everything;
`--sweep` closes all safe ones and lists the rest.

### Prune cadence

`--close`, `--sweep`, and `--report` each run `git fetch --prune origin` first, so
gone-upstream refs never accumulate. There is no separate scheduled prune — hygiene rides
on the post-merge close.

Reset `scratch/debug` to `main` after each shipped hotfix.

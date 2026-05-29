# Parallel Worktree Bootstrap Protocol

How agents claim, coordinate, and release work when implementing GitHub
issues in parallel git worktrees.

## Prerequisites

- The issue exists on GitHub and is assigned or ready for work.
- `docs/handoffs/parallel-status.md` is the single source of truth for
  who is writing what **and** who may talk to GitHub.

## GitHub ops coordination

When more than one agent is active, **only one agent** may run remote GitHub
commands at a time. This reduces DNS/API flakiness and rate-limit pressure.

### Roles

| Role | Remote commands allowed | Local-only |
|------|-------------------------|------------|
| **GitHub ops owner** | `git push`, `git fetch`, `gh pr create`, `gh pr merge`, `gh pr checks`, `gh issue *`, updates to `parallel-status.md` on `main` | also codes in its worktree |
| **Implementation agent** | none | `git commit`, tests, lint, edit files in its worktree |

### Claiming GitHub ops

1. Read `## GitHub ops lock` in `parallel-status.md`.
2. If `Owner` is `_(none)_`, set yourself as owner before the first remote op.
3. If another owner is listed, **do not** push or call `gh` — commit locally and
   note in chat that ops handoff is needed.
4. Release the lock (`Owner` → `_(none)_`) when all in-flight PRs are merged
   or when explicitly handing off to another coordinator agent.

### Stagger remote operations

After **every** remote GitHub command, update `Last remote op (UTC)` in the
registry, then wait **≥ 30 seconds** before the next remote command — even if
you are the ops owner. Other agents must not start a remote op until 30 seconds
after the timestamp shown in the registry.

```bash
# Example: ops owner pushing two PRs in sequence
git push -u origin HEAD
# update Last remote op in parallel-status.md on main, commit if needed
sleep 30
gh pr create ...
# update Last remote op again
```

### What implementation agents do instead of push/PR

1. Finish code + tests locally in the worktree.
2. Leave branch ready with commits on the local branch.
3. Tell the GitHub ops owner (or coordinator): issue #, branch name, PR title/body draft.
4. Ops owner pushes, opens PR, watches checks, merges, updates registry phases.

## Claiming Work

1. **Check `parallel-status.md`** — ensure no other in-flight row lists
   the module(s) you intend to modify under `Writer of`.
2. **Create a worktree**:
   ```bash
   git worktree add ../juli-ai-issue-<N> -b feat/issue-<N>-<slug> main
   ```
3. **Add your row** to the `## In-flight` table in `parallel-status.md`
   on the `main` branch (not your worktree) with phase `focus`.
   - Only the **GitHub ops owner** may commit this registry update when another
     agent is in-flight; otherwise note the row in chat and wait for ops.
4. Ops owner **pushes** the status update so other agents see it immediately.

## Module Locking Rules

- Only **one** in-flight row may list a given module path under `Writer of`.
- Multiple rows may list the same module under `Reader of` (read-only).
- If you need a module already claimed, either:
  - Wait for the writer to merge, or
  - Coordinate a hand-off (update both rows atomically).

## Phase Transitions

Update your row in `parallel-status.md` at every phase change:

| Phase | Meaning |
|-------|---------|
| `focus` | Loading context, reading specs, planning implementation |
| `tdd-red` | Writing failing tests |
| `tdd-green` | Making tests pass |
| `review` | Self-review, linting, final checks |
| `pr-open` | PR created, awaiting review/merge |
| `merged` | PR merged into main |
| `blocked` | Cannot proceed — note reason in commit or comment |

## After Merge

1. Mark your row's phase as `merged`.
2. Move your row from `## In-flight` to `## Archive` on the next sweep.
3. Remove the worktree:
   ```bash
   git worktree remove ../juli-ai-issue-<N>
   ```
4. Delete the local branch if no longer needed:
   ```bash
   git branch -d feat/issue-<N>-<slug>
   ```

## Conflict Resolution

- If two agents accidentally claim the same module, the **earlier
  timestamp** wins. The later agent must either wait or negotiate.
- Merge conflicts on `parallel-status.md` itself are resolved by keeping
  all rows and deduplicating.

## Branch Naming

| Type | Pattern |
|------|---------|
| Feature | `feat/issue-<N>-<slug>` |
| Bug fix | `fix/issue-<N>-<slug>` |
| Refactor | `refactor/issue-<N>-<slug>` |

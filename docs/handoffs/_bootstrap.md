# Parallel Worktree Bootstrap Protocol

How agents claim, coordinate, and release work when implementing GitHub
issues in parallel git worktrees.

## Prerequisites

- The issue exists on GitHub and is assigned or ready for work.
- `docs/handoffs/parallel-status.md` is the single source of truth for
  who is writing what.

## Claiming Work

1. **Check `parallel-status.md`** — ensure no other in-flight row lists
   the module(s) you intend to modify under `Writer of`.
2. **Create a worktree**:
   ```bash
   git worktree add ../juli-ai-issue-<N> -b feat/issue-<N>-<slug> main
   ```
3. **Add your row** to the `## In-flight` table in `parallel-status.md`
   on the `main` branch (not your worktree) with phase `focus`.
4. **Push the status update** so other agents see it immediately.

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

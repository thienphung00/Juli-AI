# ADR-100: A wave reconcile lands as a merge commit, under its own issue

**Status:** Proposed
**Date:** 2026-09-09
**Deciders:** Owner, W7/backend
**Related:** #1451, #1844, #1853, #1640, #1851, #1856

## Context

`feature/agent-w6-wave` has been reconciled with `main` three times: #1640
(2026-09-05), #1851 and #1856 (both 2026-09-09). Each reconcile resolved its
conflicts correctly. After each, **#1844 (wave → main) still reported the same
conflicts**, and the next reconcile had to resolve them again.

The cause is the merge strategy, not the resolutions. Every one of those PRs was
**squash-merged**. A squash collapses the merge into a single new commit and
discards the merge parentage, so git retains no record that the wave ever
incorporated `main`. Measured after #1851 was merged:

```
is the #1851 branch an ancestor of the wave?   NO
wave still behind origin/main:                 124
```

`git rev-list --parents -n 1` confirms `576c84758` (#1640) and `195ee5ce3`
(#1851) are single-parent commits. #1844 therefore recomputes from the original
merge base and finds the same 46 conflicts, minus whatever content happened to
converge.

The handoff for #1856 had already diagnosed this for the two *earlier*
reconciles — it described them as PRs that "replayed main's content into the
wave as new commits, which is why they are not reachable from `main` and why
they conflict" — and the diagnosis was then repeated on the very PR that quoted
it. The failure is systemic, not a lapse of attention: the green button defaults
to squash, and the cost is invisible until the next wave→main attempt.

A second, independent deadlock surfaced alongside it. Reconciles are filed under
one standing issue, **#1451**, whose status record predates #1562 and therefore
carries no `architecturalChange` field. `check_adr` resolves that question from
a ladder — a `docs/architecture/map.md` edit in the diff, the review body, then
the status record — and for a reconcile all three can be silent: `map.md` lands
in the first reconcile and is absent from the next, review bodies are gitignored
by ADR-003 and never present in CI, and the record cannot acquire the field
because #1562's Architect lock forbids backfilling, with two tests enforcing it.
The gate then fails closed, permanently, for every future PR under #1451.

## Decision

**1. A reconcile PR into a wave branch is merged with a merge commit, never
squashed.** `gh pr merge <n> --merge`, or the "Create a merge commit" option.
The repository already allows it (`allow_merge_commit=true`).

**2. Each reconcile is filed under its own issue, not under the standing #1451.**

**3. Neither rule is enforced by weakening a gate.** The alternative considered
and rejected was a `check_adr` rung that skips the ADR requirement for merge
commits; see Rationale.

## Rationale

**Why a merge commit rather than a squash.** What a squash destroys is the
parentage, not the content. No resolution of the conflicting files can
compensate, because the information #1844 needs — "has this branch already taken
`main`?" — lives in the commit graph and nowhere else. A merge commit makes
`merge-base(wave, main)` advance to the reconciled point, which is the entire
purpose of running a reconcile.

**Why a fresh issue per reconcile.** The `check_adr` deadlock is a consequence of
reusing an issue whose record predates the field the gate reads. A new issue does
not inherit that: `generate_status_records.py` emits `architecturalChange` for
records it creates, and the same guard that forbids backfilling states that
"committing a NEW record is what an issue-tier PR is *required* to do". It is
also more honest — #1640, #1851 and #1856 are three distinct pieces of work
sharing one issue number, which is why none of their status records can describe
any of them accurately.

**Why not fix the gate instead.** The obvious code change — classify a merge
commit as non-architectural — loosens the requirement for authored work too:
anyone merging `main` into a feature branch would have the ADR requirement
skipped for their own changes in the same PR. The tighter variant, "every path
byte-identical to one merge parent", does not fire for a real reconcile either,
because the wave manifest and `pr.yml` are legitimately synthesised as unions and
match neither side. A guard that blocks a merge is doing its job; the answer is
to stop asking it the wrong question, not to make it ask less.

## Consequences

- #1844 becomes mergeable once a reconcile lands with its parentage intact.
  Until then it will keep reporting conflicts however many times they are
  resolved.
- Wave history gains merge commits. That is the point: the graph records what
  actually happened.
- One extra issue per reconcile, with the status record that issue tier already
  requires.
- #1853 stays open for the underlying gate defect. This ADR routes around it
  rather than closing it: a reconcile filed under a fresh issue resolves at rung
  3, but the gate's inability to answer for a merge remains.
- Branch protection could enforce decision 1 by disallowing squash on wave
  bases. Not proposed here — a repository-settings change is the owner's, and
  three occurrences may not yet justify it.

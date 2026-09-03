# ADR-092 — When a gate's configuration may be edited

**Status:** Accepted — 2026-09-03 (#1540, PR #1561)

## Context

Architect lock 6 for the Harness-E epic (#1434) reads: *no gate may be satisfied by
editing gate configuration.* It exists because the cheapest way to clear a red gate is to
move the thing the gate is measured against, and a harness whose subject is "gates that
cannot fail" must not acquire that habit.

The lock was written as an absolute, and it was applied as one. Two W4 reviewers hit
`harness_bootstrap_pinned` failing on their branches, traced it to
`workflow_prompt_cache.bootstrap.pinBranch: HEAD` in
`agent-runtime/config/agent-runtime.config.yml`, and declined to touch the file. They were
right to decline on the evidence they had, but the gate stayed broken, and it was broken in
a specific way: `HEAD` is symbolic, so it re-resolved at check time to the checked-out
branch's own tip. The gate compared the branch against itself. It went red on a branch's
first commit, green only on a branch that had done no work, and at no point looked at the
harness it exists to watch.

So an absolute reading of lock 6 leaves a permanently broken gate with no legal repair, and
the repair genuinely does require editing the config file the lock protects. The lock needs
a discriminator, not an exception.

## Decision

**Lock 6 forbids changing what a gate is measured *against* in order to clear a red. It
does not forbid changing what a gate *measures*, when the current measurement is provably
incapable of detecting the condition the gate names.**

A config edit that touches a gate is legitimate only if all four hold:

1. **The defect is in the predicate, not in the value.** The field's old content must be
   unable to express the intended check at all — not merely stale. Bumping a pinned SHA to
   match the current one is always laundering; `pinBranch` never held a SHA, it held the
   string `HEAD`, and the edit changed what kind of thing the field denotes.
2. **The gate can still be made red afterwards, and this is demonstrated, not asserted.**
   Exhibit a concrete input under the *new* configuration that produces a FAIL. If no such
   input exists, the edit converted an always-red gate into an always-green one, which is
   strictly worse than the bug and is laundering by a longer route.
3. **No hand-maintained number is introduced.** An anchor that must be bumped each run
   makes "bump the pin" routine, and routine is how lock 6 erodes in practice. Prefer an
   anchor that is derived and fixed for the life of the branch.
4. **The new configuration space is guarded against re-introducing the defect**, at the
   resolver and by a test asserting the shipped value — not by reviewer vigilance.

Criterion 2 is the operative one. It is mechanical and falsifiable, and a reviewer can
execute it in a throwaway repository in under a minute.

For this gate specifically: `pinBranch` is now an **anchor spec**, `merge-base:origin/main`
— the fork point between the branch and its integration base. The branch's own commits
cannot move it and unrelated traffic on the base cannot either. The pinned SHA
(`bootstrapRef.commitSha`) remains derived by `ensure_workflow_cache`, never hand-set.

A stable anchor alone would have failed criterion 2: a branch's own harness edits never
move its fork point, so the old commit-identity check would have passed unconditionally.
The predicate is therefore **content**: `diff_harness_paths_since` diffs the configured
bootstrap `sourcePaths` between the pin and the **working tree**, catching drift that is
committed, uncommitted, untracked, or a deletion. Pin → working tree rather than pin → HEAD
is deliberate: the harness a run actually reads is the one on disk.

Self-referential anchors are rejected at the resolver and at cache-write time. The check
applies to the whole spec *and* to the base ref of a `merge-base:` spec — checking only the
whole spec leaves `merge-base:HEAD` accepted, and `git merge-base HEAD HEAD` is `HEAD`.
An anchor naming the checked-out branch is rejected by resolved identity rather than by
spelling.

## Rationale

The distinction is between the two halves of a measurement. A gate is a predicate applied
to a reference point. Lock 6's target is moving the reference point so the predicate stops
firing — the number, the SHA, the threshold. Its target is not repairing a predicate that
was never able to fire correctly, because a predicate that cannot discriminate is not a
gate at all, and preserving it preserves nothing.

The reason lock 6 was written absolutely is that the two are hard to tell apart from the
diff alone: both look like "someone edited the config and the red went away." Criterion 2
separates them at the level of behaviour rather than intent, which is the only level that
survives an agent's own account of what it was doing. Requiring a demonstrated red closes
the gap that "I fixed the semantics" would otherwise open — an agent can claim a semantics
change, but it cannot fabricate a FAIL from a gate that no longer has one.

Criterion 4 exists because this review found the guard bypassable after the fix:
`merge-base:HEAD` and the branch's own name both laundered real committed drift to PASS.
A guard against a config defect must live in the resolver and in a test on the shipped
value, because the next person to edit the field will not have read this ADR.

Alternatives considered for the anchor: `origin/main` (stable against the branch, but moves
under unrelated merges, so the gate reddens for reasons unrelated to the run) and an
explicit SHA (correct but hand-bumped every run — the treadmill criterion 3 rejects).

## Consequences

- Editing `agent-runtime.config.yml` to repair a gate is permitted under the four criteria
  above, and a review that permits it must record the demonstrated red as evidence. Absent
  that evidence the edit is refused, and the W4 reviewers' instinct remains the default.
- `pinBranch` is an anchor spec, not a branch name. Values that resolve to the checked-out
  branch's tip are rejected. `eval/fixtures/parent-cache.template.json` still supplies
  `"HEAD"` and goes red once #1561 lands; that is tracked as #1563 and is the intended
  fail-closed behaviour, not a regression.
- Shallow checkouts have no fork point, and `actions/checkout` is depth-1 by default. The
  anchor degrades to the base ref and records `anchorDegraded` with a reason — never to
  `HEAD` and never to a silent pass. A missing base ref fails closed. On a grafted checkout
  this degraded path is the only path taken, so the gate is effectively anchored to the
  base tip there and will redden when the base advances with a harness change. That is
  loud and correct, but it is a real operational cost.
- One residual is accepted knowingly: an explicit SHA that happens to equal the branch tip
  is still accepted, because it is indistinguishable from a legitimate deliberate pin on a
  freshly cut branch. It is caught for the shipped configuration by
  `test_shipped_config_pin_branch_resolves_against_this_repository`.
- `sourcePaths` is now the load-bearing input rather than an index input. Emptying it fails
  closed; narrowing it does not, and narrowing is therefore a live lock-6 surface that
  needs its own assertion. Tracked in #1563.

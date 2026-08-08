# ADR-059: Scoped artifact waiver for `wave-dpr-demo`

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Repository owner (approving the waiver); review performed by Claude Code

**Builds on:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven CI), [ADR-052](052-wave-free-merge-deferred-artifact-gate.md) (deferred artifact gate), [ADR-055](055-decision-plan-review.md) (the work this wave delivered).
**Does not change:** the `artifact-gate` contract for any other wave; the per-issue artifact requirement going forward; ADR-003 principles.
**Out of scope:** the issue-tier enforcement gap that produced this situation (recorded below as a consequence, to be addressed separately).

## Context

`wave-dpr-demo` carries 18 issues (#759–#776) delivering the ADR-055 Situation →
Decision → Details plan review. All 18 merged into the wave branch through their own
PRs and all are closed. The wave→main `artifact-gate` fails with 18 errors: not one
issue has the compact status record at `agent-runtime/artifacts/status/issue-<N>.json`
that ADR-052 item 6 makes the merge-time source of truth.

The evidence does not exist and cannot be recovered. Searched, and empty in all of:

- the wave worktree and the full repo tree
- all 10 surviving `.worktrees/issue-<N>` checkouts — these bodies are gitignored, so
  uncommitted copies would have survived there if they had ever been written
- git history across every ref
- CI artifact retention for the 18 merged PRs, which holds only `gitleaks-results.sarif`,
  because ADR-052 item 2 runs no artifact jobs at issue tier

Running the full gate set for #759 fails 16 of 26 checks, every one rooted in a missing
implementation or review artifact.

**This is specific to this wave, not a harness defect.** The sibling manifests pass the
same gate cleanly: `wave-a1-cdp-speed` (5 issues) and `wave-dux-demo` (10 issues), both
0 errors. `artifact_gates` in `agent-runtime.config.yml` exempts only `.worktrees/debug`
with a `scratch/debug` branch lacking an issue suffix; these issues used
`feature/…-issue-<N>` branches, so `requireIssueArtifactsWhenBranchMatchesIssue: true`
applied. The artifacts were required by policy and were never emitted.

### Why the records cannot simply be generated

A status record asserts `review.status: PASS` and `validation.status: PASS`. Validation
cannot reach PASS without an implementation artifact carrying TDD red→green evidence,
`contextFilesLoaded` and `tokenUsage` — telemetry of implementation work that already
happened and was not recorded. Writing those records now would fabricate exactly the
evidence this gate exists to verify. That option was rejected outright.

### What was done instead

The 18 merged diffs were reviewed against the merged code before this waiver was granted,
so the decision rests on evidence rather than on amnesty. Nine diffs were read in full
(#759, #762, #763, #767, #770, #771, #774, #775, #776); the other nine were screened for
defect signatures and test ratios.

Six defects were found and fixed in `39f53a7`:

| # | Issue(s) | Defect |
|---|---|---|
| 1 | #776 | Supporting-document upload rejected every PDF — the document path used the image-only screener. No test covered `file_content_base64`. |
| 2 | #774 + #776 | Size caps disagreed: 10 MB **raw** on the client, 10 MB **base64** (~7.5 MB raw) on the server. Files in between always failed. |
| 3 | #767 | `approvedInputs` carried both delivery branches' fields plus a hardcoded `shipping_type: "Ship by TikTok"`, contradicting the invariant documented in the same file and PRD #758 user story 12. |
| 4 | #776 | A dimension rejection was relabelled "corrupt or invalid" by the catch-all. |
| 5 | #776 | Animated GIFs lost every frame but the first on re-encode. |
| 6 | #774/#776 | The seller-copy rationale still described screening as MIME-type-and-truncation-only. |

A seventh defect — the Phase 2.6 e2e exit-gate suite driving the superseded five-stage
review DOM for 10 of 11 workflows — was found and fixed earlier in `13e5261`. `demo-e2e`
is a main-tier job, so it had never run against the plan spine until the exit PR.

Findings 2 and 6 span issue boundaries and finding 7 spans the whole wave: no per-issue
review could have surfaced them. That is the substantive answer to whether the missing
artifacts were merely paperwork. They were not.

## Decision

1. **Grant a waiver scoped to `wave-dpr-demo` and to issues #759–#776 by name.** It is
   recorded as an `artifactWaiver` block inside that wave's own manifest, so it cannot
   reach another wave, and it names each issue, so an issue added to this wave later is
   never covered retroactively.
2. **The gate prints the waiver.** `artifact-gate` emits a `WAIVED` line naming this ADR,
   the approver, the reason and the covered issues. A waived gate must never read like a
   clean one in the CI log.
3. **A waiver that covers an issue outside its wave is an error**, not a no-op — the gate
   fails on it.
4. **No `WAIVED` status on per-issue status records.** Introducing one would create a
   per-issue escape hatch that gets reused casually, and would misrepresent a single
   governance decision as eighteen independent ones.
5. **The 18 issues stay on the manifest.** Removing them would quiet the gate by hiding
   the wave, and would break ADR-052 item 5.
6. **This waiver is not precedent.** It is granted because the evidence is unrecoverable
   *and* the code was reviewed in its place. A future wave that simply skipped artifact
   emission should be re-run, not waived.

## Consequences

- `wave-dpr-demo` can merge to `main` with `artifact-gate` passing and the exception on
  the record, rather than merging via an admin override that leaves no durable trace.
- The wave's quality rests on a review performed after the fact, dated accordingly, and
  on the six defects it fixed — not on artifacts that never existed.
- **The root cause is structural and remains open.** ADR-052 item 2 runs no artifact jobs
  at issue tier while item 6 relies on agents emitting artifacts voluntarily. This wave is
  what that looks like when the voluntary half does not happen: 18 issues merged, and the
  gap surfaced only at the exit gate, weeks later. A cheap existence check at issue tier —
  does `status/issue-<N>.json` exist for this PR's issue — would have failed in hours.
  Filing that is follow-on work.
- Separately, `generate_status_records.py:128` copies `modulesTouched` from review
  artifacts as objects while `status-record.schema.json` declares strings. Two committed
  records (`issue-623`, `issue-720`) are already schema-invalid; both are harmless only
  because neither is on a wave manifest. Any newly generated record would inherit it.

# ADR-062: Scoped artifact waiver for `wave-security-baseline` (six original slices)

**Status:** Accepted
**Date:** 2026-08-10
**Deciders:** Repository owner (approving the waiver); implementation and review performed by Claude Code

**Builds on:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven CI),
[ADR-052](052-wave-free-merge-deferred-artifact-gate.md) (deferred artifact gate),
[ADR-059](059-dpr-wave-artifact-waiver.md) (the waiver mechanism and its precedent),
[ADR-061](061-first-user-security-baseline.md) (the work this wave delivers).
**Does not change:** the `artifact-gate` contract for any other wave; the per-issue artifact
requirement going forward; ADR-003 principles.
**Scope:** the **six original slices only** — #894, #896, #897, #898, #899, #900. The four
fix slices on the same wave (#926–#929) are **explicitly not covered**; they emitted complete
implementation artifacts and must pass the gate on their own evidence.

## Context

`wave-security-baseline` carries ten issues: the six ADR-061 security slices, plus four
fixes for defects the Review phase found in them. All ten merged into the wave through their
own PRs.

The six original slices have no `agent-runtime/artifacts/status/issue-<N>.json` records,
because **no implementation artifact was ever emitted for them**. The cause is known and
recorded plainly: the Executor briefs for those six asked for code, tests, a commit and a PR,
and did not ask for the ADR-003 artifact. That was an orchestration error, not an executor
failure.

Five validation gates fail for each of the six, all cascading from that one absence:
`implementation_artifact_present`, `implementation_schema_valid`,
`implementation_tdd_evidence`, `executor_domain_matches_cache`, `phase_run_correlation`.

### Why the records cannot simply be generated

Identical to [ADR-059](059-dpr-wave-artifact-waiver.md)'s reasoning, which this ADR adopts
rather than re-argues. A status record asserts `review.status: PASS` and
`validation.status: PASS`; validation cannot reach PASS without an implementation artifact
carrying `phaseRunId`, `startedAt`, `executionDurationMs`, `toolInvocationCount` and TDD
red→green evidence. That is **telemetry of work already done and not recorded**. Writing it
now would fabricate exactly the evidence the gate exists to verify.

Every one of the six Review agents reached this conclusion independently and refused to
produce one. One stated it directly: *"I did not fabricate one; this reflects a real,
honestly-reported gap in the local artifact chain, not a code quality problem."*

### What exists in its place — and why it is stronger than the ADR-059 case

ADR-059 was granted because the diffs were reviewed instead. Here the same substitution
applies, but with materially better evidence:

- **All six slices received a full Review pass** — `intent-review` → `guardrails` → `validate`
  — each running the real 21-gate sweep and recording actual output.
- **Reviewers verified by execution, not by reading.** #899's reviewer ran all three
  fail-closed paths in a standalone script. #896's reviewer rebuilt both HTTP call shapes
  against a real refused connection and observed the credential leak in the old form and its
  absence in the new. #897's reviewer stood up Postgres 16 and reproduced the migration
  sequence. #898's and #900's reviewers fault-injected — deleting a `limit_req` directive,
  registering an unprotected route — and confirmed the gates fired.
- **Three real defects were found and fixed** — a blocking Redis call on a single-worker
  event loop (#927), a webhook ceiling mis-sized because the rate-limit key was
  misunderstood (#928), and a migration whose central clause CI could not prove (#929).
  None were visible from green CI.
- **The fix slices demonstrate the loop works when run correctly.** #926–#929 each emitted a
  schema-valid implementation artifact with real telemetry. The gap was procedural, not a
  harness defect.

## Decision

1. **Grant a waiver scoped to `wave-security-baseline` and to issues #894, #896, #897, #898,
   #899, #900 by name.** Recorded as an `artifactWaiver` block in that wave's own manifest,
   so it cannot reach another wave, and naming each issue, so an issue added later is never
   covered retroactively.
2. **The four fix slices are not waived.** #926, #927, #928 and #929 emitted proper artifacts
   and must satisfy the gate on their own evidence. A waiver covering them would discard the
   one thing this round proved.
3. **The gate prints the waiver** — a `WAIVED` line naming this ADR, the approver, the reason
   and the covered issues, per ADR-059 item 2. A waived gate must never read like a clean one.
4. **No `WAIVED` status on per-issue status records**, per ADR-059 item 4.
5. **The six issues stay on the manifest**, per ADR-059 item 5.
6. **This waiver is not precedent.** It is granted because the telemetry is unrecoverable
   *and* the code was reviewed in its place, more rigorously than the gate itself would have
   required. A future wave that simply skipped artifact emission should be re-run, not waived.

## Consequences

- **Positive:** the wave can reach main carrying both the security baseline and the fixes for
  every defect review found — main never receives the defective versions followed by patches.
- **Positive:** the four fix slices establish a working reference for what the loop produces
  when the Executor brief includes the artifact requirement.
- **Negative:** two waivers now exist within three days (ADR-059, this one), from two
  different causes — one where artifacts were never emitted at issue tier, one where the
  orchestrator's brief omitted them. That pattern is itself a signal; see below.
- **Follow-up, not addressed here:** nothing in the harness forces an Executor brief to
  include the artifact requirement. Both waivers trace to the same class of omission — a
  human or agent instruction that silently skipped a required output. A gate that fails an
  issue-tier PR when its branch matches `issue-<N>` and no implementation artifact was
  uploaded to CI retention would have caught both. Worth its own issue.

## Options considered

| Alternative | Why rejected |
|---|---|
| Generate the six status records from the merged diffs | Fabricates the telemetry the gate verifies. Rejected outright by ADR-059 and independently by all six Review agents |
| Re-run the six slices through the full loop | Repeats work already merged, reviewed and fixed; produces artifacts describing a re-enactment rather than the implementation that actually shipped |
| Remove the six issues from the manifest | Quiets the gate by hiding the wave; breaks ADR-052 item 5 |
| Waive all ten issues for simplicity | Discards the four slices' genuine artifacts and the evidence that the loop works when briefed correctly |

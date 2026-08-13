# ADR-079: Wave 2 artifact disposition — a decision, not a waiver request

**Status:** Proposed — requires repository owner decision. **This ADR deliberately does not
recommend granting a third waiver.**
**Date:** 2026-08-13
**Deciders:** Repository owner. Orchestration, implementation and review performed by Claude Code.

**Builds on:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven CI),
[ADR-052](052-wave-free-merge-deferred-artifact-gate.md) (deferred artifact gate),
[ADR-059](059-dpr-wave-artifact-waiver.md) (waiver mechanism),
[ADR-062](062-security-baseline-wave-artifact-waiver.md) (second waiver, same cause),
[ADR-078](078-agent-w1-wave-artifact-waiver.md) (third waiver — which stated it must be the last).
**Scope:** `wave-agent-w2-p12` and `wave-agent-w2-pim`, issues **#1036–#1043** only.
**Not in scope:** #1044 and #1045, whose implementation artifacts survive and can reach genuine
status records once Review and signoff run.

## Context

Wave 2 delivered ten slices across two waves. The code is merged into both wave branches,
independently verified, and a full retrospective Review pass over both waves found and fixed a
HIGH-severity defect that ten green PRs had passed over (control-pool candidate screening
compared a count-calibrated volume floor against a rate metric, silently disabling
K-nearest-correlated-sibling selection for half of ADR-077's metric map — fixed in #1062).

Neither wave can reach `main`: `artifact-gate` requires a committed
`agent-runtime/artifacts/status/issue-<N>.json` per issue, and none exist.

### Cause, stated plainly

Two orchestration errors by the Meta agent, both mine:

1. **`meta_prepare_executor.py` was never run for any slice.** `CLAUDE.md` requires Meta to run
   it before assigning an Executor and to halt unless it prints `readyForExecutor: true`. Without
   the child workflow cache it produces, five validation gates cannot pass. Compounding this, the
   ten issue bodies carried `## Parent` followed by prose rather than an issue number, and no PRD
   parents existed — so the gate could not have resolved even if it had been run. #1057 and #1058
   (the PRD parents) and #1059 (epic + slice-routing registration) fix this; #1059 demonstrably
   moves issue #1044 from `readyForExecutor: false` to `true` and its validation from 8 failures
   to 5.

2. **Executor worktrees were torn down before Review ran**, destroying the implementation
   artifacts for #1036–#1043. Their telemetry — `phaseRunId`, `startedAt`,
   `executionDurationMs`, `toolInvocationCount`, TDD red→green evidence — is **unrecoverable**.

The second error is the material one, and it is worse than W1's: in W1 the artifacts were never
created. Here they **were** created, correctly, with real telemetry — several were verified at
the time — and then destroyed by over-eager cleanup.

### Why the records cannot be generated

Unchanged from ADR-059, ADR-062 and ADR-078: validation cannot reach PASS without an
implementation artifact carrying real telemetry. Writing one now fabricates exactly the evidence
the gate exists to verify. This ADR does not propose doing so under any option.

## The tension this ADR exists to resolve

**ADR-078 item 6 says:** *"This waiver is not precedent… A future wave that simply skipped
artifact emission should be re-run, not waived."* and *"A third occurrence should be refused."*

Wave 2 is that occurrence. Taking ADR-078 at its word means **refusing** a fourth waiver.

But **ADR-062 rejected re-running** as an option, on the grounds that it *"repeats work already
merged, reviewed and fixed; produces artifacts describing a re-enactment rather than the
implementation that actually shipped."*

So the two governing ADRs point in opposite directions for this exact case. That conflict is a
decision for the repository owner, not something an agent should resolve by picking the
convenient half.

## Options

### Option A — Grant a scoped waiver for #1036–#1043

**For:** The evidence substitution ADR-062 accepted is present and stronger than the gate would
have required. Both waves received a full retrospective Review pass verifying by execution, not
by reading: it reproduced the control-pool defect against the real pipeline, proved fail-closed
paths under fault injection, asserted exact tier boundaries, and independently re-derived the
prompt gates. It found a HIGH-severity production defect and two documentation defects, all now
fixed. #1044 and #1045 keep genuine records, so the waiver would not blanket the wave.

**Against:** ADR-078 explicitly said this should be refused. Granting it makes "the last waiver"
a phrase with no force, and the pattern — four waivers, all from an instruction that silently
skipped a required output — is itself the signal ADR-062 flagged and nobody acted on.

### Option B — Refuse the waiver; land the waves on their branches and defer `main`

**For:** Honours ADR-078's own terms. Nothing is fabricated, nothing is hidden, no work is lost —
both wave branches keep the merged, reviewed code. W3 re-runs the loop correctly with #1059 in
place, and the W2 slices reach `main` behind a properly evidenced wave.

**Against:** Strands ten reviewed slices outside `main`. W3-A depends on W2-A being merged
(playbook↔registry cross-validation), so this blocks the next wave, not just this one.

### Option C — Re-run the eight slices inside the harness contract

**For:** Produces genuine artifacts with real telemetry and needs no waiver.

**Against:** ADR-062 rejected precisely this: the code already exists and is merged, so an
executor would emit telemetry describing a re-enactment, not the implementation that shipped.
That is closer to fabrication in substance than a waiver is, while looking cleaner on paper.

## Recommendation

**Option B**, with a documented follow-up.

ADR-078 named the condition under which a further waiver should be refused, and this is exactly
that condition — with an aggravating factor: the artifacts existed and were destroyed. Granting
Option A would be the fourth waiver in eleven days, from the same class of omission each time,
and would establish that the mechanism has no floor.

Option B's real cost is blocking W3-A. That cost is worth paying once, to make the artifact
requirement mean something.

## Consequences

- **Positive (B):** the loop's evidence contract regains force; #1059 makes the correct path
  available for W3; nothing is fabricated.
- **Negative (B):** ten reviewed slices sit outside `main`; W3-A is blocked until W2-A lands.
- **Either way:** the harness still does not force an Executor brief to include the artifact
  requirement, nor force Meta through `meta_prepare_executor.py`. ADR-062 flagged this as *"worth
  its own issue"*; it remains unbuilt, and is now implicated in four waivers. **A gate failing an
  issue-tier PR whose branch matches `issue-<N>` when no implementation artifact was uploaded to
  CI retention would have caught every one of them.**

## What is not in question

The Wave 2 code itself. Both waves are verified in main-tier shape (P12: 3,052 unit;
P-IM: 3,158 unit + 42 integration), both phase gates are met with real measurements, and the
Review pass that would substitute for artifacts under Option A has already been run and its
findings fixed. This ADR is about evidence of process, not about whether the work is sound.

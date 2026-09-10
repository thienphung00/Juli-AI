# ADR-101: A test derives from a captured fixture; it never restates one

**Status:** Proposed
**Date:** 2026-09-09
**Deciders:** Owner, W6/W7
**Related:** #1451, #1677, #1862, #1844, ADR-100

## Context

On 2026-09-09 the W6 wave→main PR (#1844) failed on **13 tests across 4 files**
in `apps/demo`. None of the demo source had changed: `apps/demo`, `packages/`
and `pnpm-lock.yaml` were byte-identical to the pre-reconcile wave, verified by
tree hash, and that wave passed 1428/1428.

What changed was one fixture beneath them.
`tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json` was
re-captured by #1862 with deterministic values, so that running the unit suite
would stop rewriting it on every pass (#1677 — the suite was mutating a
committed file, which is its own defect).

Three values moved, and the tests had hardcoded all three:

| value | restated in tests | re-captured | failures |
|---|---|---|---|
| tool summary | `"completed"` | `"Hoàn tất"` | 2 |
| `expires_at` | `2026-08-28T09:32:13Z` | `2026-01-01T04:00:00Z` | 9 |
| `workflow_run_id` | `6fed3803-…` | `00000000-…-b453` | 2 |

The re-capture was **correct in every case**: `"Hoàn tất"` is the seller-facing
Vietnamese copy the product actually ships, and deterministic timestamps and ids
are what stop the fixture rewriting itself.

The nine-failure cluster is the instructive one. The tests hardcoded a "one hour
before expiry" instant as a literal date. The re-capture moved `expires_at` four
months *earlier*, so that literal became an instant **after** expiry. Every
option then rendered as expired, the confirm button became inert, and nine tests
about two-step consent and decline behaviour failed — none of which is about a
clock. The failure message said the click handler was never called, which points
at the component rather than at the fixture that actually caused it.

## Decision

**A test that consumes a captured fixture derives its expectations from that
fixture. It does not restate the fixture's values as literals.**

Concretely:

- Read the value from the capture — `summaryFor(events, toolCallId)` rather than
  `summary: "completed"`.
- Derive relative instants from the captured ones — `expiresAt - 1h` rather than
  a literal date chosen to sit before whatever `expiresAt` was on the day the
  test was written.
- Import the identifier the source already derives — `REPLAY_SCENARIO_RUN_ID`
  rather than a copy of the UUID it resolves to.

**A derived expectation must fail loudly when the fixture cannot supply it.**
`summaryFor` throws when no `tool.completed` frame carries a summary, because an
expectation that quietly becomes `undefined` on both sides turns a real
assertion into a vacuous one — trading a brittle test for a dead one, which is
worse.

**Where the literal IS the subject, keep it.** A test asserting that copy shown
to a seller reads exactly "Hoàn tất" should hardcode that string; that test is
*about* the copy, and it should fail when the copy changes.

## Rationale

A restated literal duplicates a fact that already has one home. When the capture
is regenerated — which #1677 makes routine rather than exceptional — every copy
goes stale at once, and each one fails somewhere far from the change, with a
message describing a symptom rather than a cause.

The distinction is what a test is *about*. These nine option-picker tests are
about two-step consent: that selecting an option does not submit, and that
confirming does. The expiry instant is scaffolding they need in order to reach
the behaviour. Scaffolding should follow the fixture; subject matter should be
asserted.

This is the same principle ADR-100 reached from the other side: a value with two
homes eventually disagrees with itself, and the fix is to keep one home rather
than to synchronise both by hand.

## Amendment — 2026-09-09, the deliberate-transcription case

The decision above assumes a test can import the fixture. One place in this
repo deliberately cannot, and the omission cost a second failure the same day.

`apps/demo/e2e/fixtures/replay-scenario.ts` **transcribes** the captured
scenario's identifiers rather than importing them, so the Playwright runner
never imports app source. Its stated reason: *"a drift between the two is a
visible diff in review, not a silent shared-import coupling."*

**The stated benefit did not hold.** #1862 re-captured the scenario; the
transcription kept the old run id and clock pin; no diff made that visible; and
nothing failed until the replay journey rendered "không tìm thấy luồng thực
hiện" at the wave→main gate, several steps removed from the change that caused
it.

**And the obvious repair is worse than the problem.** Importing the fixture
across the runner boundary — the direct application of the decision above —
broke **five unrelated suites** with a jsdom `Not implemented: navigation`
error. That is precisely the shared-runner coupling the transcription exists to
avoid, arriving from the other side.

**Amended:** where a transcription is deliberate and importing is not
available, keep the transcription and **guard it with a text-level
comparison** — read the transcribing file as text, extract its constants, and
assert them against the capture. The drift then fails in a unit run naming both
values, rather than in an end-to-end journey that reports a missing page.

Two details that are part of the decision, not incidental:

- The guard asserts only values the capture actually contains. The first
  version asserted a product name that is not in the capture at all and failed
  on its own assertion — a derived expectation must be derivable.
- A deliberate transcription remains legitimate. This amendment does not
  require importing; it requires that a restatement be *checked*, which is the
  property the original rationale assumed it already had.

## Consequences

- Re-capturing a golden scenario no longer breaks tests that are not about the
  values that changed. The one test that *is* about it — the byte-identity check
  between the fixture and the demo's bundled copy — still fails, correctly, and
  is fixed by syncing the copy.
- Derived expectations are weaker than literals in one specific way: they cannot
  catch a fixture that is itself wrong. The throwing helper narrows that gap; a
  contract test on the fixture's shape closes the rest, and `replay-scenario.test.ts`
  already carries one.
- A reviewer reading `summary: summaryFor(events, "c1")` must open the fixture to
  know the expected value. That is a real cost, accepted: the alternative is a
  literal that is right on the day it is written and silently wrong afterwards.

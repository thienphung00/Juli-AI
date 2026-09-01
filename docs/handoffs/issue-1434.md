# Epic handoff — #1434 · Harness-E (P-EVAL)

> Parent PRD: [#1434](https://github.com/thienphung00/Juli-AI/issues/1434).
> Injected as `{handoffPath}` into every P-EVAL executor cache. Keep it short.

## The one-sentence scope

**The agent's artifact is a prediction. CI is the oracle. The disagreement is both the
merge blocker and the eval label.** Every slice moves one thing out of the boundary the
graded agent can reach.

## Why the epic exists

- 269 of 270 committed status records are shippable; `acceptanceMapped < acceptanceTotal`
  has occurred **0 times in 270**. A metric that never disagrees measures nothing.
- `grep -rn "scripts/validate" .github/workflows/` returns **zero**. The 29 gates have
  never run in CI, and **28 of 29 issue no `subprocess` call at all**.
- `gh api repos/:owner/:repo/rules/branches/feature%2Fw7-wave` returns **`[]`**. Every
  issue-tier gate is advisory by construction.
- **240 of 538** `artifactRef`/`sha256` pairs name a path in no commit on any branch.
- **487 of 541** pytest runs are narrower than CI's; **88 of 239** gate-result claims have
  no matching run.

## Product boundary

- Harness only: `agent-runtime/`, `.github/workflows/`, `eval/`, `tests/unit/`.
- **No product code.** `backend/src/`, `apps/`, `ios/`, `packages/` are out of scope for
  every slice in this epic. A P-EVAL slice that edits product code is mis-scoped — stop
  and report rather than widening.
- No migrations. No API routes. No UI.

## Architect locks

1. **The verdict is computed where the agent cannot write.** A slice satisfied by having
   an agent report a value has not been satisfied.
2. **Fail-closed, always.** Missing input, lookup error, unparseable file: each fails. A
   check must never pass because it could not determine an answer.
3. **No backfill, no history rewrite.** 270 records stay at `gateVersion: 1`; the 240
   dangling refs are marked unresolvable, not repaired — the files exist nowhere.
4. **`pr.yml` has one writer at a time.** Duplicate `- <job>` entries under `needs:` make
   string-replace edits land on the wrong job; an empty `needs.X.result` is the only
   symptom. Verify the edited job's `needs` graph after any change.
5. **Only factual gates ship blocking.** A factual gate compares two recorded values and
   cannot false-positive. A heuristic gate infers intent, ships advisory, and carries a
   measurable promotion criterion **and** an expiry — unpromoted at expiry means deleted.
6. **No gate may be satisfied by editing gate configuration.**
7. **The judge never blocks until calibrated.** `k=3` self-consistency is never described
   as independence — it measures variance, not bias.
8. **Ratchets are identity sets**, never counts. `mypy_statement_coverage` must not fall.
9. **Emit is not commit.** The five gitignored artifact body directories stay gitignored
   and are never `git add -f`'d.
10. **Done means `git log --all -- <path>` shows the files.** A prior session reported a
    five-file pipeline delivered with a table of ✅ marks; nothing existed in any branch,
    worktree or stash. That is the failure class this epic ends — do not reproduce it.

## Testing contract

Every new check gets a test that **plants a lie** and asserts the check catches it: an
artifact citing a command never invoked, a fingerprint disagreeing with the resolved
module path, a selector narrower than CI's, an `artifactRef` naming a path in no commit.

A happy-path-only test is not accepted. The defect class here is a check that passes
vacuously, and `agent-runtime/scripts/validate/` holds 28 examples of exactly that.

Fail-closed is tested explicitly: lookup error, malformed input, unreadable file and
absent file must each fail rather than pass. Prior art:
`tests/unit/test_check_artifact_retention_guard.py`, `tests/unit/test_status_record_gate.py`.

CI-wiring slices are verified against a **real PR**, not a fixture — the standard #1064
was held to.

## Slice map

| Group | Slices |
|---|---|
| **HE-A** enforcement boundary | #1435 `[HITL]` · #1437 · #1440 · #1436 `[HITL]` |
| **HE-B** captured evidence | #1438 · #1441 · #1442 · #1458 · #1443 · #1444 · #1445 · #1439 · #1446 |
| **HE-C** measurable negatives | #1456 · #1457 · #1459 |
| **HE-D** judge, calibrated | #1460 · #1461 `[HITL]` |
| **HE-E** ratchets | #1462 · #1463 |

**#1438 blocks all of Wave 2** — it ships the capture-provider seam so each later slice
adds a module rather than editing `generate_status_records.py`. Do not edit that writer
from a Wave-2 slice; register a provider instead.

## Do not load

`apps/` · `ios/` · `packages/` · `backend/src/` · `docs/product/design/` ·
`docs/integrations/tiktok_corpora/` · sibling issue context caches

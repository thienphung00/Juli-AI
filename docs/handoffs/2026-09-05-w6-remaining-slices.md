# W6: what is actually left, and in what order

Scoping pass, 2026-09-05. Written after reconciling the wave with main (#1451 / PR #1640).

**Read this before picking up a W6 issue.** The issue list is stale in two directions: one
slice is done but its issue is open, and one issue understates a defect that is live in the
demo today.

## Corrected inventory

The W6 PRD (#1308) is **closed** while eleven of its children are open — that discrepancy is
worth resolving on its own, because "W6" currently means two different things depending on
whether you read the epic or the issues.

Verified against the tree on `feature/w6-reconcile-issue-1451`, not against issue state:

| Slice | Issue | Status | Domain |
|---|---|---|---|
| Seller-facing reason codes | #1272 | **done**, on the wave | backend |
| Visual identity + motion | #1314 | **done**, on the wave | ui-ux |
| In-Progress run ledger | #1318 | **done**, on the wave | ui-ux |
| Golden scenarios: capture, schema, replay | #1311 | **done** — landed as #1423; issue is stale | backend |
| `useRunStream` + pure reducer | #1315 | not built | ui-ux |
| Staged run view | #1316 | not built | ui-ux |
| Consent-grade option picker | #1317 | not built | ui-ux |
| Delete the mock layer | #1320 | not built | ui-ux |
| Replay journey in CI + dictionary + MODULE.md | #1321 | **partial** — e2e infra exists, replay journey does not | ui-ux |
| Anonymous demo session | #1313 | not built | **backend**, not ui-ux |
| HITL gate | #1322 | gate observation, not engineering | — |

So it is **six** slices, not seven. #1311 being done matters more than the count: it is the
foundation #1315 and #1321 are specified against.

## Dependency order

`#1311` (done) unblocks everything else. Then:

```
#1315 reducer ──► #1316 staged view ──► #1317 option picker ──► #1320 delete mock ──► #1321 CI journey
#1313 anonymous session ─────────────────────────────────────► (independent; needed before #1322)
```

Three things force this order rather than taste:

1. **#1315 before #1316/#1317.** Both are specified as "driven entirely by the reducer's
   output"; the stage canvas "renders what the events said and nothing it computed itself."
   Building either first means inventing a state shape the reducer will then contradict.
2. **#1320 after the real path works.** It deletes `startExecution` and the fixture fallback.
   Delete before the replacement exists and the demo has no working path at all.
3. **#1321 last.** Its journey walks the whole surface end to end, so it cannot be written
   before the surface exists. Its dictionary and MODULE.md work is also the honest close-out
   of the invariant #1320 retires.

**#1313 is backend, not ui-ux**, despite sitting in a UI wave. Routing it to a `ui-ux`
executor would be a domain mismatch: it is Supabase anonymous sign-in, JWT verification
through the real ES256/JWKS path, shop resolution, and rate-bucket keying.

## A live defect #1320 understates

Confirmed present in the tree today:

- `apps/demo/src/components/recommendations-panel.tsx` still falls back to
  `recommendationFixtures` on a failed fetch — a broken backend renders as a healthy surface.
- The recommendations path constant is `/v1/demo/recommendations`. **That route does not
  exist.** The real surface is `/v1/demo/decisions`.

So the demo's recommendations panel is, today, showing fixture content against a 404. That is
not a future slice; it is a defect shipping now, and it is the cheapest item on this list.
It is worth pulling out of #1320 and fixing on its own rather than waiting for the run
surface.

## Sizing and risk

- **#1315** is the load-bearing one and the best specified. Its tests must run on captured
  scenario files, never hand-built event objects — that is the whole point of the slice, and
  a reviewer should reject hand-built fixtures outright.
- **#1316** and **#1317** are the largest. #1317 authorizes a real mutation, so its two-step
  consent and "no single click authorizes anything" assertion are security properties, not
  UX polish.
- **#1320** is small but destructive; its own AC says the other ten workflows' tests are the
  regression net and **must not be edited** to accommodate the removal.
- **#1321** requires determinism across ten consecutive runs. Flakiness is specified as a
  failure, not a retry.
- **#1313** carries the W5 gate's lesson explicitly: mint through the **real provider path**,
  never a self-signed test token. The verifier was once hardcoded to HS256 while the provider
  issued ES256, and a self-signed token verifies the code against its own assumption.

## What this scoping does not decide

Whether W6 ships at all before W7's gate (#1339) closes. These slices are independent of that
gate, but they compete for the same attention, and #1322 is a second HITL gate on top.

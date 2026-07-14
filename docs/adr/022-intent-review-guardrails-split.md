# ADR 022: Intent-review / Guardrails split and structure authority

## Status
Accepted

**Context session:** `grill-with-docs`, 2026-07-14 — Review-phase skill boundaries.
**Amends:** Review Agent sequence and skill names under `.cursor/skills/standalone/`.
**Preserves:** [ADR-003](003-ai-native-cicd-policy.md) CI gate on `review-issue-<n>.json`
(still emitted by **guardrails**, formerly the `review` skill).

## Context

After introducing a two-axis branch review skill, Review Agent had overlapping judges:

1. Standards / maintainability / Fowler smells vs Guardrails domain tables.
2. Spec "intent match" vs acceptance-criteria ↔ test mapping — two different questions
   that agents under time pressure conflate.
3. Executor TDD Refactor vs post-implementation structure review — "Act ≠ Judge" without
   an explicit authority rule left both agents free to claim final say on structure.

Option B (merge Standards into Guardrails) was rejected: one skill judging everything
erases criterion-level traceability needed by dual-signoff / ADR-003. Option C (keep
duplication) was rejected as documenting rather than removing the overlap.

## Decision

### 1. Rename skills to match ownership

| Former name | New name | Owns |
|-------------|----------|------|
| `code-review` | **`intent-review`** | Spec fidelity (intent-to-code), Fowler smells, light convention citations; emits intent-review artifact |
| `review` | **`guardrails`** | Reliability / security / observability / performance checklists, patches, AC **coverage** gaps, ADR-003 review artifact |

Sequence: `intent-review` → `guardrails` → `validate` → ship-ready.

### 2. Artifact contract (required)

`intent-review` emits `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json`
with at least:

```json
{
  "spec_fidelity": "pass" | "fail",
  "smells": [],
  "convention_notes": []
}
```

`guardrails`:

- Reads `spec_fidelity` **as given** — does not re-judge intent-match.
- Runs AC coverage-gap checks **only when** `spec_fidelity == "pass"`.
- Treats coverage gap as a distinct failure mode from Spec fidelity failure.
- Imports blocking smells/convention notes; does not re-scan those smell classes.

### 3. Spec fidelity vs AC coverage

- **Spec fidelity** (intent-review): developer-level intent-to-code match vs PR/design.
- **AC coverage** (guardrails): product-level requirement-to-test fidelity vs ticket ACs.

These can diverge and must not be conflated.

### 4. Structure authority rule (verbatim)

> Executor MAY clean up structure during GREEN (refactor step). Only intent-review MAY block merge on structure.

Executor refactor is advisory/non-blocking. intent-review is the sole blocking structural judge.

Canonical prose: [`.cursor/skills/standalone/intent-review/BOUNDARY.md`](../../.cursor/skills/standalone/intent-review/BOUNDARY.md).

## Consequences

- Agents must not "re-check Spec just to be sure" inside Guardrails.
- ADR-003 path `artifacts/reviews/review-issue-*.json` unchanged; producer skill renamed.
- New artifact type `intent_review` is committed on feature branches; Guardrails fails closed if missing during a full Review Agent run.
- Domain executor skills document the authority rule next to TDD Refactor.

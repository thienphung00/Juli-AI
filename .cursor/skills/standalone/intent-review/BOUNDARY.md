# Review-phase skill boundaries

Canonical split for Review Agent:
`intent-review` → `guardrails` → `validate` → ship-ready

Derived from grill session (Standards ownership option A + Executor authority rule).
ADR: [`docs/adr/022-intent-review-guardrails-split.md`](../../../docs/adr/022-intent-review-guardrails-split.md).

## Ownership matrix

| Skill | Owns | Does NOT do |
|-------|------|-------------|
| **intent-review** | Spec fidelity (intent-to-code), Fowler smells, light convention/pattern citations; emits intent-review artifact | Full Guardrails domain tables; reliability/security/observability/performance checks; AC↔test coverage mapping; ADR-003 review artifact |
| **guardrails** | Reliability / security / observability / performance checklists, patch suggestions, ADR-003 review artifact, AC **coverage** gaps | Re-running smell-baseline; re-auditing naming/DRY already covered by intent-review; re-judging Spec intent-match |
| **validate** | Deterministic gate scripts + validation artifact | Judgment on intent, smells, or Guardrails domains |
| **ship** | Release readiness after validation PASS | Re-audit of prior axes |

## Spec fidelity vs AC coverage (must not conflate)

| Question | Owner | Failure mode |
|----------|-------|--------------|
| Did the diff implement what the PR/design **intended**? (intent-to-code, developer-level) | **intent-review** → `spec_fidelity` | Spec fidelity `fail` |
| Does every ticket **acceptance criterion** have corresponding test/behavior? (requirement-to-test, product-level) | **guardrails** → AC coverage | Coverage gap finding |

These can diverge: code may match a design that missed an AC, or satisfy every AC while violating unstated design intent.

### Artifact handoff contract

**intent-review emits** (minimum):

```json
{
  "spec_fidelity": "pass" | "fail",
  "smells": [],
  "convention_notes": []
}
```

**guardrails MUST:**

1. Read `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json` before judging.
2. Treat `spec_fidelity` **as given** — do **not** re-judge intent-match.
3. When `spec_fidelity == "fail"`: record that state on the review artifact (block merge); **skip** AC coverage gap analysis for that run (fix intent first).
4. When `spec_fidelity == "pass"`: check the AC list **only** for **coverage gaps** (an AC exists with no corresponding test/behavior). A coverage gap is a distinct failure mode from Spec fidelity failure — never rename one as the other.
5. Fold blocking smells / convention_notes into `criticalFindings` when they block merge; do **not** re-scan for the same smell classes from scratch.

## Authority rule (Executor Refactor ↔ intent-review)

**Verbatim — both Executor domain skills and intent-review must include this:**

> Executor MAY clean up structure during GREEN (refactor step). Only intent-review MAY block merge on structure.

### Consequences

- Executor's refactor pass is **advisory and non-blocking** — like a developer running a linter before opening a PR. No approve/reject authority.
- intent-review's smell-check is the **sole blocking judgment** on structural quality. If Executor's refactor was insufficient, intent-review sends the work back.
- This is **not** duplicate judgment — one judge (intent-review) and one non-authoritative practitioner (Executor).

## Forbidden under time pressure

- Guardrails agents must **not** "quickly re-check Spec just to be sure."
- intent-review must **not** run reliability/security/observability/performance domain tables.
- Executor must **not** treat its GREEN refactor as merge approval for structure.

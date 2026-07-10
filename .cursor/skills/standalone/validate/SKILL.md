---
name: validate
description: >-
  Deterministically validates an issue's implementation before ship by running every
  agent-runtime/scripts/validate/*.py gate and emitting agent-runtime/artifacts/validation/validation-issue-<n>.json.
  Use when the review handoff is complete and the next step would be ship, when CI fails
  on artifact gates, or when an agent needs a machine-verifiable PASS before merging.
---

# Validate

Sits between `review` and `ship` in the Review Agent phase. Generates the
machine-readable JSON artifact that `ship` and CI consume to gate merges.

This skill is non-conversational. It runs Python scripts, aggregates their
outputs into a single JSON file, and exits with PASS or FAIL. The repository
artifact — not the chat output — is the system of record.

## When to invoke

- After `review` has emitted `agent-runtime/artifacts/reviews/review-issue-<n>.json` and
  before `ship` runs.
- After fixing a CI failure surfaced by `pr.yml`.
- Before opening a PR locally to catch failures early.

## Inputs

- Issue number (`<n>`).
- Branch under review (current `HEAD`).
- Existing review artifact at `agent-runtime/artifacts/reviews/review-issue-<n>.json`.
- Implementation artifact at `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` (required; validate **FAIL** if missing).

## Outputs

- `agent-runtime/artifacts/validation/validation-issue-<n>.json`
  - ADR-003 CI fields: [`docs/deployment/implementation-guide.md`](../../../docs/deployment/implementation-guide.md)
  - Meta fields: [`agent-runtime/docs/agent-runtime-artifacts.md`](../../../agent-runtime/docs/agent-runtime-artifacts.md)
  - Schema: [`agent-runtime/docs/schemas/validation-artifact.schema.json`](../../../agent-runtime/docs/schemas/validation-artifact.schema.json)
- Process exit code: `0` if every check passes, `1` otherwise.
- Concise console summary (one line per check).

The generator enriches the artifact with `schemaVersion`, `validationFailures`,
`readyForShip`, and test counts derived from the review artifact when available.

## Pipeline

```
review artifact -> validate skill -> validation artifact -> ship skill / CI
```

The validate skill itself orchestrates thirteen gate scripts. Each gate
is a single-purpose Python file under `agent-runtime/scripts/validate/`. Per-check semantics
are documented in [checks.md](checks.md).

## Run

The canonical entry point is the artifact generator. It runs every gate,
collects their results, and writes the validation artifact.

```bash
python agent-runtime/agent-runtime/scripts/ci/generate_validation_artifact.py --issue <n>
```

For a single gate while debugging:

```bash
python agent-runtime/scripts/validate/check_module_boundaries.py
python agent-runtime/scripts/validate/check_module_drift.py
# ... etc.
```

## Required Behavior

1. Read the review artifact. If missing or malformed, fail with check
   `review_artifact_present: FAIL` — do **not** synthesize a review.
2. Run every gate script in `agent-runtime/scripts/validate/` regardless of earlier
   failures (so the JSON artifact lists every problem in one pass).
3. Aggregate results into the validation artifact schema.
4. Write the artifact, print a one-line summary per check, exit 0/1.
5. Never modify production code. This skill is read-only against `src/`,
   `web/`, `ios/`, and `tests/`.

## Status semantics

| Validation status | Blocks merge? | Condition |
|-------------------|---------------|-----------|
| `PASS` | No | Every check is `PASS`; review is `PASS` or `PASS_WITH_WARNINGS` with full signoff |
| `FAIL` | Yes | Any check is `FAIL`, or review `status` is `FAIL` |

`PASS_WITH_WARNINGS` on the **review** artifact blocks merge until
`findings_acknowledged`, `reviewer_signoff_present`, and `owner_signoff_present`
all pass. Warnings live in `criticalFindings[*].severity == "WARNING"` with
`acceptanceByReviewer`, `ownerAck`, and `fixedInCommit` or `shipAsIsReason`.

## Handoff to `ship`

Ship **requires** `readyForMerge: true` on the validation artifact. Do not hand off
when `status` is `FAIL` or `readyForMerge` is `false`.

```markdown
## Handoff: validate -> ship

### Issue
- #<n> -- <title>

### Validation Artifact
- File: agent-runtime/artifacts/validation/validation-issue-<n>.json
- Status: PASS
- Checks: 13/13 passed

### Notes
- [Any gate that emitted warnings, even at PASS]
- [If a check was skipped because its precondition was absent — e.g. no
  handoff on the branch — note here]
```

If status is `FAIL`, do NOT hand off to `ship`. Return to `review` (or the
appropriate skill) with the failed-check summary.

## Integration with rules

- [`.cursor/rules/git-baseline.mdc`](../../../.cursor/rules/git-baseline.mdc) —
  CI/CD subsection; this skill is the local mirror of the `pr.yml` validate-artifacts job.
- [`.cursor/rules/issue-workflow.mdc`](../../../.cursor/rules/issue-workflow.mdc) —
  the `>3 modules` warning surfaced here defers to the disjoint-modules rule.
- [`.cursor/rules/core-orchestration.mdc`](../../../.cursor/rules/core-orchestration.mdc) —
  skills governance; this skill is read-only; it never creates new skills or rules.

## Integration with other skills

| Skill | How validate interacts |
|-------|------------------------|
| `review` | Consumes the review artifact; never edits it |
| `ship` | Reads the validation artifact as the merge gate (`readyForMerge` / `readyForShip`) |
| `focus` | Meta Agent routes here after review; consumes validation artifact for harness optimization |
| Executor (domain skills) | If validate fails on `acceptance_criteria_mapped`, hands back to Executor to add tests |
| `qa` | Not consulted by validate; used upstream when filing bug issues before Implementation |

## Anti-patterns

- Generating a "passing" validation artifact when checks fail. The artifact's
  `status` field MUST reflect reality.
- Editing the review artifact to make checks pass. `validate` is a verifier,
  not a fixer.
- Running only a subset of checks. Always run the full sweep, even on rerun.
- Treating console output as authoritative. The JSON artifact is the system
  of record.

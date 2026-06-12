---
name: validate
description: >-
  Deterministically validates an issue's implementation before ship by running every
  scripts/validate/*.py gate and emitting artifacts/validation/validation-issue-<n>.json.
  Use when the review handoff is complete and the next step would be ship, when CI fails
  on artifact gates, or when an agent needs a machine-verifiable PASS before merging.
---

# Validate

Sits between `review` and `ship` in both workflow chains. Generates the
machine-readable JSON artifact that `ship` and CI consume to gate merges.

This skill is non-conversational. It runs Python scripts, aggregates their
outputs into a single JSON file, and exits with PASS or FAIL. The repository
artifact — not the chat output — is the system of record.

## When to invoke

- After `review` has emitted `artifacts/reviews/review-issue-<n>.json` and
  before `ship` runs.
- After fixing a CI failure surfaced by `pr.yml`.
- Before opening a PR locally to catch failures early.

## Inputs

- Issue number (`<n>`).
- Branch under review (current `HEAD`).
- Existing review artifact at `artifacts/reviews/review-issue-<n>.json`.

## Outputs

- `artifacts/validation/validation-issue-<n>.json` (schema in
  [`docs/ci/implementation-guide.md`](../../../docs/ci/implementation-guide.md)).
- Process exit code: `0` if every check passes, `1` otherwise.
- Concise console summary (one line per check).

## Pipeline

```
review artifact -> validate skill -> validation artifact -> ship skill / CI
```

The validate skill itself just orchestrates the seven gate scripts. Each gate
is a single-purpose Python file under `scripts/validate/`. Per-check semantics
are documented in [checks.md](checks.md).

## Run

The canonical entry point is the artifact generator. It runs every gate,
collects their results, and writes the validation artifact.

```bash
python scripts/ci/generate_validation_artifact.py --issue <n>
```

For a single gate while debugging:

```bash
python scripts/validate/check_module_boundaries.py
python scripts/validate/check_module_drift.py
# ... etc.
```

## Required Behavior

1. Read the review artifact. If missing or malformed, fail with check
   `review_artifact_present: FAIL` — do **not** synthesize a review.
2. Run every gate script in `scripts/validate/` regardless of earlier
   failures (so the JSON artifact lists every problem in one pass).
3. Aggregate results into the validation artifact schema.
4. Write the artifact, print a one-line summary per check, exit 0/1.
5. Never modify production code. This skill is read-only against `src/`,
   `web/`, `ios/`, and `tests/`.

## Status semantics

| Validation status | Condition |
|-------------------|-----------|
| `PASS` | Every check is `PASS` |
| `FAIL` | Any check is `FAIL` |

There is no `PASS_WITH_WARNINGS` at the validation layer. Warnings live in the
review artifact's `criticalFindings[*].severity == "WARNING"` and the nightly
audit artifacts.

## Handoff to `ship`

```markdown
## Handoff: validate -> ship

### Issue
- #<n> -- <title>

### Validation Artifact
- File: artifacts/validation/validation-issue-<n>.json
- Status: PASS
- Checks: 7/7 passed

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
| `ship` | Reads the validation artifact as the merge gate |
| `focus` | Routes here after the review handoff |
| `tdd` | If validate fails on `acceptance_criteria_mapped`, hands back to tdd to add tests |
| `qa` | Not consulted by validate; only used upstream in fix-bug |

## Anti-patterns

- Generating a "passing" validation artifact when checks fail. The artifact's
  `status` field MUST reflect reality.
- Editing the review artifact to make checks pass. `validate` is a verifier,
  not a fixer.
- Running only a subset of checks. Always run the full sweep, even on rerun.
- Treating console output as authoritative. The JSON artifact is the system
  of record.

---
description: Run Meta harness optimization — consume implementation/review/validation artifacts and emit a harness-optimization artifact.
argument-hint: <issue-number>
---

Dispatch the `meta` subagent to run harness optimization for issue **#$1**.

Task it with: read `agent-runtime/artifacts/implementations/implementation-issue-$1.json`,
`agent-runtime/artifacts/reviews/review-issue-$1.json`, and
`agent-runtime/artifacts/validation/validation-issue-$1.json`; classify the root cause
against `optimization.root_cause_categories`; emit a `harness-optimization-artifact`.

Constraints to restate to it:

- Change only declarative harness configuration, via
  `agent-runtime/scripts/harness_config.py` against `harness-editable.yml` and
  `harness-safelist.yml`. `dry_run_default: true` — show the diff before applying anything.
- Preserve product code, ADRs, PRDs, and architecture documents.
- Prefer measurable changes: context budget, routing thresholds, skill loading, model
  choice, tools, benchmark thresholds.
- Do not edit skills, rules, ADRs, or `.github/workflows/pr.yml`.

Report the root cause, the proposed config diff, and the benchmark deltas against
`baseline_metrics`.
